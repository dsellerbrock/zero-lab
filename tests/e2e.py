#!/usr/bin/env python3
"""End-to-end check against a running Zero Lab server (same API the UI uses).

  python3 tests/e2e.py --url http://127.0.0.1:8642 [--provision SOURCE] [--image NAME]
                       [--gpu soft|venus] [--accel auto|tcg|hvf] [--cpus N] [--out DIR]

Steps: (optional) add+provision an image; boot; wait for the desktop; screenshot; GPIO round trip
(widget-style drive -> guest program reads it -> guest drives LED pin -> host sees it) with both
samples; analog knob via the MCP3008 ADC; I2C 7-segment and LCD; stop. Prints one JSON summary line; exit status 0 only if every step passed.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.request
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def png_colours(path):
    """Distinct byte values in a PNG's pixel data (zlib over the IDAT chunks)."""
    b, raw, i = path.read_bytes(), b"", 8
    while i < len(b):
        n = int.from_bytes(b[i:i + 4], "big")
        if b[i + 4:i + 8] == b"IDAT":
            raw += b[i + 8:i + 8 + n]
        i += 12 + n
    return len(set(zlib.decompress(raw)))


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
    ap.add_argument("--cpus", type=int, default=4)  # fewer than the host's cores under TCG, or vCPUs spin on each other
    ap.add_argument("--boot-timeout", type=int, default=3600)
    ap.add_argument("--out", type=Path, default=Path("."))
    a = ap.parse_args()
    c = Client(a.url)
    res = {"steps": {}}

    def step(name, ok, **info):
        res["steps"][name] = {"ok": bool(ok), **info}
        print(f"[{'PASS' if ok else 'FAIL'}] {name} {json.dumps(info)}", flush=True)
        if not ok and name in ("provision", "boot"):  # nothing after these can run; other failures carry on
            print(json.dumps(res))
            c.call("/api/stop", {})
            sys.exit(1)

    if a.provision:
        t0, m = time.time(), c.mark()
        c.call("/api/image/add", {"name": a.image, "source": a.provision, "user": "pi", "password": "zero-lab-e2e"})
        e = c.wait(lambda e: e["type"] == "provision" and e.get("stage") in ("done", "error"), 4 * 3600, m)
        step("provision", e and e["stage"] == "done", seconds=round(time.time() - t0), error=e and e.get("error"))

    c.call("/api/config", {"image": a.image, "gpu": a.gpu, "accel": a.accel, "snapshot": False, "network": True,
                           "display": "app", "ram": 512, "cpus": a.cpus})
    cfg = c.call("/api/state")["cfg"]
    m = c.mark()
    c.call("/api/boot", {})
    e = c.wait(lambda e: e["type"] == "status" and e["status"] in ("running", "stopped"), a.boot_timeout, m)
    step("boot", e and e["status"] == "running", boot_seconds=e and e.get("boot_seconds"),
         accel=cfg["accel"], gpu=cfg["gpu"])

    time.sleep(20)  # let the desktop settle before the screenshot
    shot = c.call("/api/screenshot", {})["path"]
    step("screenshot", png_colours(Path(shot)) > 16, path=shot)  # a black or blank screen has 1-2

    # Files sidebar: copy a file in, list it, copy it back out, compare
    blob = os.urandom(2 * 1024 * 1024)
    home = c.call("/api/fs/home")["path"]
    req = urllib.request.Request(f"{c.url}/api/fs/upload?path={home}/zl-e2e/blob.bin", data=blob, method="POST",
                                 headers={"X-Zero-Lab-Token": c.token})
    urllib.request.urlopen(req, timeout=120).read()
    listed = c.call(f"/api/fs/list?path={home}/zl-e2e")["entries"]
    step("files:upload+list", any(e["name"] == "blob.bin" and e["size"] == len(blob) for e in listed), entries=listed)
    out = c.call("/api/fs/download", {"path": f"{home}/zl-e2e/blob.bin"})["path"]
    same = hashlib.sha256(Path(out).read_bytes()).hexdigest() == hashlib.sha256(blob).hexdigest()
    step("files:download-sha256", same, path=out)
    Path(out).unlink()
    c.call("/api/fs/delete", {"path": f"{home}/zl-e2e"})

    def run_sample(sample):
        d = ROOT / "samples" / sample
        c.call("/api/project/clear", {})
        for f in sorted(p for p in d.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
            c.call("/api/project/file", raw=f.read_bytes(), headers={"X-Path": f"{sample}/{f.relative_to(d)}"})
        m = c.mark()
        c.call("/api/project/run", {})
        e = c.wait(lambda e: e["type"] == "proc" and ("Ready" in e.get("line", "") or e.get("state") == "exited"), 1800, m)
        ok = e and "Ready" in e.get("line", "")
        with c.cond:
            out = [x.get("line") for x in c.events[m:] if x["type"] == "proc" and "line" in x]
        step(f"{sample}:started", ok, last=e, **({} if ok else {"output": out[-25:]}))
        return c.mark()

    def line(prefix, m, timeout=10):
        return c.wait(lambda e: e["type"] == "proc" and e.get("line", "").strip() == prefix, timeout, m)

    def gpio_pins(pred, m, timeout):
        return c.wait(lambda e: e["type"] == "gpio" and pred(e), timeout, m)

    # Button -> LED, in Python and in C (the compiled-language check)
    for sample in ("button-led-py", "button-led-c"):
        run_sample(sample)
        c.call("/api/gpio", {"pin": 17, "level": 1})  # released, as the Button widget idles (pins start at 0)
        time.sleep(0.5)
        lat = []
        for press in (0, 1, 0, 1):  # active-low button: 0 = pressed -> LED (27) on
            t, m = time.time(), c.mark()
            c.call("/api/gpio", {"pin": 17, "level": press})
            want = 1 if press == 0 else 0
            ok = gpio_pins(lambda e: e["lev"][27] == want and e["fn"][27] == 1, m, 30)
            lat.append(round(time.time() - t, 3))
            step(f"{sample}:button17={press}->led27={want}", ok, seconds=lat[-1])
        if sample == "button-led-py":
            c.call("/api/gpio", {"pin": 17, "level": 0})  # hold pressed for the screenshot
            time.sleep(1)
            res["led_on_screenshot"] = c.call("/api/screenshot", {})["path"]
            c.call("/api/gpio", {"pin": 17, "level": 1})
        c.call("/api/project/stop", {})
        res[f"{sample}_latency_s"] = lat

    # Switch: the program reports what the widget sets
    m = run_sample("switch-py")
    for level in (1, 0, 1):
        m = c.mark()
        c.call("/api/gpio", {"pin": 22, "level": level})
        step(f"switch-py:gpio22={level}", line(f"switch={level}", m))
    c.call("/api/project/stop", {})

    # Knob: a 4-bit value across GPIO5, 6, 13, 19 (lowest bit first)
    run_sample("knob-py")
    for value in (5, 15, 0, 9):  # each a change: the program prints knob=0 at start, so 0 first would race
        m = c.mark()
        for i, pin in enumerate((5, 6, 13, 19)):
            c.call("/api/gpio", {"pin": pin, "level": (value >> i) & 1})
        step(f"knob-py:value={value}", line(f"knob={value}", m))
    c.call("/api/project/stop", {})

    # Analog knob: the fork's MCP3008 on SPI0 CE0, read with gpiozero; the program prints adc= at start and on change
    m = c.mark()
    run_sample("adc-knob-py")
    for value in (0, 512, 1023):
        c.call("/api/adc", {"channel": 0, "value": value})
        e = c.wait(lambda e: e["type"] == "proc" and e.get("line", "").startswith("adc=")
                   and abs(float(e["line"].split("=")[1]) - value / 1023) <= 0.02, 10, m)
        step(f"adc-knob-py:ch0={value}", e, line=e and e["line"].strip())
        m = c.mark()
    c.call("/api/project/stop", {})

    # I2C displays: what the guest writes to /dev/i2c-1 is what /api/i2c (the widgets' source) reports
    font = {0x3F: "0", 0x06: "1", 0x5B: "2", 0x4F: "3", 0x66: "4", 0x6D: "5", 0x7D: "6", 0x07: "7", 0x7F: "8", 0x6F: "9"}

    def guest_line(prefix):
        m = c.mark()  # the next line, so the display is checked right after the guest wrote it
        e = c.wait(lambda e: e["type"] == "proc" and e.get("line", "").startswith(prefix), 10, m)
        return e and e["line"].strip()[len(prefix):]

    run_sample("seg7-i2c-py")
    for _ in range(3):
        want, seg = guest_line("count="), c.call("/api/i2c")["seg7"]
        ram = bytes.fromhex(seg["ram"])
        shown = "".join(font.get(ram[a] & 0x7F, "?") for a in (0, 2, 6, 8))
        ok = want and seg["display-on"] and shown in (want, f"{(int(want) + 1) % 10000:04d}")
        step(f"seg7-i2c-py:count={want}", ok, shown=shown)
    c.call("/api/project/stop", {})

    run_sample("lcd-i2c-py")
    for _ in range(3):
        clock, lcd = guest_line("clock="), c.call("/api/i2c")["lcd"]
        rows = bytes.fromhex(lcd["text"]).decode("latin-1")
        ok = clock and lcd["backlight"] and rows == "Hello, Zero Lab!" + clock.ljust(16)
        step(f"lcd-i2c-py:clock={clock}", ok, rows=[rows[:16], rows[16:]])
    c.call("/api/project/stop", {})

    # 7-segment: the guest's segment pins match the digit it announces
    segs, digits = (21, 20, 16, 12, 24, 23, 25), ["1111110", "0110000", "1101101", "1111001", "0110011",
                                                  "1011011", "1011111", "1110000", "1111111", "1111011"]
    m = run_sample("seven-segment-py")
    seen = set()
    end = time.time() + 25
    while len(seen) < 10 and time.time() < end:
        e = c.wait(lambda e: e["type"] == "proc" and e.get("line", "").startswith("digit="), 5, m)
        if not e:
            break
        m = c.mark()
        dgt = int(e["line"].split("=")[1])
        want = digits[dgt]
        pattern = lambda g: "".join(str(g["lev"][p]) for p in segs)  # noqa: E731
        cur = c.pins()  # the guest sets the pins just before it prints the digit
        ok = (cur and pattern(cur) == want) or gpio_pins(lambda g: pattern(g) == want, m, 0.9)
        if ok:
            seen.add(dgt)
    step("seven-segment-py:digits0-9", len(seen) == 10, digits_seen=sorted(seen))
    c.call("/api/project/stop", {})

    # Probe: 2 Hz square wave on GPIO24 = 4 edges a second; count for 5 s, expect 20 +/- 20 %
    run_sample("probe-py")
    m = c.mark()
    time.sleep(5)
    with c.cond:
        levels = [e["lev"][24] for e in c.events[m:] if e["type"] == "gpio"]
    edges = sum(1 for a, b in zip(levels, levels[1:]) if a != b)
    step("probe-py:edges-in-5s", 16 <= edges <= 24, edges=edges)
    c.call("/api/project/stop", {})

    # LED blink: the guest drives GPIO27 on and off by itself
    run_sample("led-blink-py")
    m = c.mark()
    time.sleep(3.2)
    with c.cond:
        levels = [e["lev"][27] for e in c.events[m:] if e["type"] == "gpio"]
    toggles = sum(1 for a, b in zip(levels, levels[1:]) if a != b)
    step("led-blink-py:toggles-in-3s", 4 <= toggles <= 8, toggles=toggles)
    c.call("/api/project/stop", {})

    m = c.mark()
    t = time.time()
    c.call("/api/stop", {})
    e = c.wait(lambda e: e["type"] == "status" and e["status"] == "stopped", 180, m)
    step("stop", e, seconds=round(time.time() - t), exit_code=e and e.get("exit_code"))
    print(json.dumps(res))
    sys.exit(0 if all(v["ok"] for v in res["steps"].values()) else 1)


if __name__ == "__main__":
    main()
