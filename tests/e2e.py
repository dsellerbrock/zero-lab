#!/usr/bin/env python3
"""End-to-end check against a running Zero Lab server (same API the UI uses).

  python3 tests/e2e.py --url http://127.0.0.1:8642 [--provision SOURCE] [--image NAME]
                       [--gpu soft|venus] [--accel auto|tcg|hvf] [--out DIR]

Steps: (optional) add+provision an image; boot; wait for the desktop; screenshot; GPIO round trip
(widget-style drive -> guest program reads it -> guest drives LED pin -> host sees it) with both
samples; stop. Prints one JSON summary line; exit status 0 only if every step passed.
"""
import argparse
import json
import re
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Client:
    def __init__(self, url):
        self.url = url.rstrip("/")
        html = urllib.request.urlopen(self.url + "/").read().decode()
        self.token = re.search(r'ZL_TOKEN = "([^"]+)"', html).group(1)
        self.events, self.cond = [], threading.Condition()
        threading.Thread(target=self._sse, daemon=True).start()

    def call(self, path, body=None, raw=None, headers=None):
        h = {"X-Zero-Lab-Token": self.token, **(headers or {})}
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        if body is not None:
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(self.url + path, data=data, headers=h, method="POST" if data is not None else "GET")
        try:
            return json.loads(urllib.request.urlopen(req, timeout=300).read() or b"{}")
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{path}: {e.code} {e.read().decode(errors='replace')}") from None

    def _sse(self):
        r = urllib.request.urlopen(f"{self.url}/api/events?t={self.token}", timeout=None)
        for line in r:
            if line.startswith(b"data: "):
                with self.cond:
                    self.events.append(json.loads(line[6:]))
                    self.cond.notify_all()

    def wait(self, pred, timeout, since=0):
        end = time.time() + timeout
        with self.cond:
            while True:
                for i in range(since, len(self.events)):
                    if pred(self.events[i]):
                        return self.events[i]
                left = end - time.time()
                if left <= 0:
                    return None
                self.cond.wait(left)

    def mark(self):
        with self.cond:
            return len(self.events)

    def pins(self):
        with self.cond:
            g = [e for e in self.events if e["type"] == "gpio"]
        return g[-1] if g else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8642")
    ap.add_argument("--provision", help="catalog id or image path to add first")
    ap.add_argument("--image", default="e2e")
    ap.add_argument("--gpu", default="soft")
    ap.add_argument("--accel", default="auto")
    ap.add_argument("--boot-timeout", type=int, default=3600)
    ap.add_argument("--out", type=Path, default=Path("."))
    a = ap.parse_args()
    c = Client(a.url)
    res = {"steps": {}}

    def step(name, ok, **info):
        res["steps"][name] = {"ok": bool(ok), **info}
        print(f"[{'PASS' if ok else 'FAIL'}] {name} {json.dumps(info)}", flush=True)
        if not ok:
            print(json.dumps(res))
            c.call("/api/stop", {})
            sys.exit(1)

    if a.provision:
        t0, m = time.time(), c.mark()
        c.call("/api/image/add", {"name": a.image, "source": a.provision, "user": "pi", "password": "zero-lab-e2e"})
        e = c.wait(lambda e: e["type"] == "provision" and e.get("stage") in ("done", "error"), 4 * 3600, m)
        step("provision", e and e["stage"] == "done", seconds=round(time.time() - t0), error=e and e.get("error"))

    c.call("/api/config", {"image": a.image, "gpu": a.gpu, "accel": a.accel, "snapshot": False, "network": True,
                           "display": "app", "ram": 512, "cpus": 4})
    cfg = c.call("/api/state")["cfg"]
    m = c.mark()
    c.call("/api/boot", {})
    e = c.wait(lambda e: e["type"] == "status" and e["status"] in ("running", "stopped"), a.boot_timeout, m)
    step("boot", e and e["status"] == "running", boot_seconds=e and e.get("boot_seconds"),
         accel=cfg["accel"], gpu=cfg["gpu"])

    time.sleep(20)  # let the desktop settle before the screenshot
    shot = c.call("/api/screenshot", {})["path"]
    step("screenshot", Path(shot).exists(), path=shot)

    for sample in ("button-led-py", "button-led-c"):
        d = ROOT / "samples" / sample
        c.call("/api/project/clear", {})
        for f in sorted(p for p in d.rglob("*") if p.is_file()):
            c.call("/api/project/file", raw=f.read_bytes(), headers={"X-Path": f"{sample}/{f.relative_to(d)}"})
        m = c.mark()
        c.call("/api/project/run", {})
        e = c.wait(lambda e: e["type"] == "proc" and ("Ready" in e.get("line", "") or e.get("state") == "exited"), 1800, m)
        step(f"{sample}:started", e and "Ready" in e.get("line", ""), last=e)
        lat = []
        for press in (0, 1, 0, 1):  # active-low button: 0 = pressed -> LED (27) on
            t = time.time()
            m = c.mark()
            c.call("/api/gpio", {"pin": 17, "level": press})
            want = 1 if press == 0 else 0
            ok = c.wait(lambda e: e["type"] == "gpio" and e["lev"][27] == want and e["fn"][27] == 1, 30, m)
            lat.append(round(time.time() - t, 3))
            step(f"{sample}:button17={press}->led27={want}", ok, seconds=lat[-1])
        if sample == "button-led-py":
            c.call("/api/gpio", {"pin": 17, "level": 0})  # hold pressed for the screenshot
            time.sleep(1)
            res["led_on_screenshot"] = c.call("/api/screenshot", {})["path"]
            c.call("/api/gpio", {"pin": 17, "level": 1})
        c.call("/api/project/stop", {})
        res[f"{sample}_latency_s"] = lat

    m = c.mark()
    t = time.time()
    c.call("/api/stop", {})
    e = c.wait(lambda e: e["type"] == "status" and e["status"] == "stopped", 180, m)
    step("stop", e, seconds=round(time.time() - t), exit_code=e and e.get("exit_code"))
    print(json.dumps(res))


if __name__ == "__main__":
    main()
