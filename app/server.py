#!/usr/bin/env python3
"""Zero Lab: local web app for an emulated Raspberry Pi Zero 2 W (QEMU fork with GPIO events).

Binds 127.0.0.1 only. Every request must carry Host 127.0.0.1/localhost (blocks DNS rebinding);
every POST, the event stream and the VNC socket need the per-launch token (blocks other websites).
"""
import argparse
import json
import os
import platform
import queue
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import gpio
import guest
import image
import readiness
import vm as vmod

APP = Path(__file__).resolve().parent
STATIC = APP / "static"
TYPES = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml",
         ".png": "image/png", ".json": "application/json", ".ico": "image/x-icon"}


def default_data_dir():
    if platform.system() == "Darwin":
        return Path.home() / "Library/Application Support/Zero Lab"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "zero-lab"


class Hub:
    """Fan-out of events to SSE clients, plus the snapshot a new client needs."""

    def __init__(self):
        self.clients, self.lock = set(), threading.Lock()
        self.serial = ""
        self.last = {}

    def emit(self, kind, **data):
        msg = {"type": kind, **data}
        if kind == "serial":
            self.serial = (self.serial + data["data"])[-65536:]
        elif kind == "provision" and data.get("stage") in ("done", "error"):
            self.last.pop("provision", None)  # a finished setup is not news to the next page load
        elif kind != "proc" or "state" in data:
            self.last[kind] = msg
        line = json.dumps(msg)
        with self.lock:
            for q in self.clients:
                q.put(line)

    def snapshot(self):
        return [json.dumps(m) for m in self.last.values()] + \
            [json.dumps({"type": "serial", "data": self.serial})]


class App:
    def __init__(self, data):
        self.data = data
        (data / "images").mkdir(parents=True, exist_ok=True)
        (data / "layouts").mkdir(exist_ok=True)
        self.hub = Hub()
        self.host = vmod.host()
        self.vm = vmod.VM(self.on_vm_event)
        self.gpio = None
        self.guest = None
        self.files = []          # staged project files: (relpath, bytes)
        self.markers = {}        # marker name -> threading.Event
        self.busy = None         # name of a running background job
        self.cfg = self.load_cfg()
        self.saved_at = None

    # ---------- config / state ----------
    def load_cfg(self):
        try:
            return json.loads((self.data / "config.json").read_text())
        except (OSError, ValueError):
            return dict(vmod.DEFAULTS)

    def save_cfg(self, cfg):
        if self.vm.proc and self.vm.proc.poll() is None:
            raise RuntimeError("Stop the Pi to change its settings")
        allowed = set(vmod.DEFAULTS) | {"image"}
        self.cfg = {k: v for k, v in {**self.cfg, **cfg}.items() if k in allowed}
        (self.data / "config.json").write_text(json.dumps(self.cfg))
        self.saved_at = time.time()

    def images(self):
        out = []
        for d in sorted((self.data / "images").iterdir()):
            try:
                st = json.loads((d / "state.json").read_text())
            except (OSError, ValueError):
                st = {"provisioned": False, "broken": True}
            entry = next((e for e in image.CATALOG if e["id"] == st.get("source")), None)
            label = entry["name"] if entry else Path(st.get("source", d.name)).name
            boot = all((d / f).exists() for f in ("kernel8.img", "stock.dtb"))
            out.append({"name": d.name, "label": label, "boot_files": boot, **st})
        return out

    def readiness(self):
        if not hasattr(self, "_qemu"):  # QEMU doesn't change while the app runs; probe once
            self._qemu = readiness.qemu_probe(vmod.qemu_paths, vmod.qemu_env)
        return readiness.check(self.host, self._qemu, self.images(), self.cfg.get("image"), self.busy,
                               shutil.disk_usage(self.data).free, image.CATALOG)

    def paths(self):
        return {"home": str(Path.home()), "data": str(self.data), "layouts": str(self.data / "layouts"),
                "config": str(self.data / "config.json"), "downloads": str(Path.home() / "Downloads")}

    def reveal(self, what):
        """Show one of Zero Lab's own folders/files in the system file manager (never arbitrary paths)."""
        path = Path(self.paths()[what])
        target = path if path.exists() else path.parent
        if platform.system() == "Darwin":
            subprocess.run(["open", "-R", str(target)], check=False)
        elif "microsoft" in platform.release().lower():
            win = subprocess.run(["wslpath", "-w", str(target)], capture_output=True, text=True).stdout.strip()
            subprocess.run(["explorer.exe", f"/select,{win}"], check=False)
        else:
            subprocess.run(["xdg-open", str(target if target.is_dir() else target.parent)], check=False)

    def state(self):
        return {"host": self.host, "cfg": vmod.resolve(self.cfg, self.host), "images": self.images(),
                "paths": self.paths(), "saved_at": self.saved_at,
                "catalog": image.CATALOG, "status": self.vm.status, "busy": self.busy,
                "layouts": sorted(p.stem for p in (self.data / "layouts").glob("*.json")),
                "staged": [r for r, _ in self.files]}

    # ---------- VM ----------
    def on_vm_event(self, kind, **data):
        if kind == "marker":
            self.markers.setdefault(data["name"], threading.Event()).set()
        if kind == "status" and data["status"] == "stopped":
            if self.gpio:
                self.gpio.stop()
                self.gpio = None
        if kind == "status" and data["status"] in ("booting", "running"):
            data["ws_port"] = self.vm.ports["ws"]
        self.hub.emit(kind, **data)

    def imgdir(self, name):
        d = self.data / "images" / name
        if not (d / "state.json").exists() or "/" in name or name.startswith("."):
            raise ValueError(f"unknown image {name!r}")
        return d

    def boot(self):
        if self.busy:
            raise RuntimeError(f"busy: {self.busy}")
        name = self.cfg.get("image") or next((i["name"] for i in self.images() if i.get("provisioned")), None)
        if not name:
            raise ValueError("add a Raspberry Pi OS image first")
        d = self.imgdir(name)
        st = json.loads((d / "state.json").read_text())
        if not st.get("provisioned"):
            raise ValueError("this image is not set up yet")
        r = self.readiness()
        if not r["ready"]:
            raise ValueError("Not ready to boot: " + ", ".join(x["title"] for x in r["rows"] if x["required"] and x["state"] != "ok"))
        cfg = vmod.resolve(self.cfg, self.host)
        self.markers.clear()
        self.vm.start(cfg, d, "desktop", (APP / "guest/setup.sh").read_text(), {"zl-user": st["user"]},
                      ready=vmod.READY_MARK if st.get("desktop", True) else "ZL_SETUP_DONE")
        self.guest = guest.Guest(d / "ssh/id_ed25519", self.vm.ports["ssh"], st["user"])
        threading.Thread(target=self.attach_gpio, daemon=True).start()

    def attach_gpio(self):
        if vmod.wait_for(self.vm.run / "qtest.sock", self.vm.proc, 30):
            self.gpio = gpio.Gpio(gpio.QTest(str(self.vm.run / "qtest.sock")), self.on_pins)

    def on_pins(self, state):
        self.hub.emit("gpio", fn=[f for f, _ in state[:gpio.HEADER_PINS]],
                      lev=[lv for _, lv in state[:gpio.HEADER_PINS]])

    def stop(self):
        g = self.guest
        self.vm.stop(poweroff=g.poweroff if g and self.vm.status == "running" else None)

    # ---------- image provisioning ----------
    def add_image(self, name, source, user, password):
        if self.busy or (self.vm.proc and self.vm.proc.poll() is None):
            raise RuntimeError("stop the VM first")
        if not name or not name.replace("-", "").replace("_", "").isalnum():
            raise ValueError("image name: letters, digits, - and _")
        d = self.data / "images" / name
        if d.exists():
            raise ValueError("an image with that name exists")
        image.user_data(user, password, "x")  # validate before a long download
        self.busy = f"setting up {name}"
        threading.Thread(target=self._provision, args=(d, source, user, password), daemon=True).start()

    def _provision(self, d, source, user, password):
        def progress(stage, done, total):
            self.hub.emit("provision", stage=stage, done=done, total=total)
        try:
            _, qemu_img, _ = vmod.qemu_paths()
            st = image.prepare(source, d, user, password, qemu_img, progress)
            progress("first-boot", 0, 1)
            self.markers.clear()
            cfg = vmod.resolve({**self.cfg, "gpu": "soft", "snapshot": False, "network": True,
                                "ram": max(512, int(self.cfg.get("ram", 512)))}, self.host)
            self.vm.start(cfg, d, "provision")
            if not self.markers.setdefault("ZL_PROVISIONED", threading.Event()).wait(3 * 3600):
                raise TimeoutError("first boot did not finish")
            g = guest.Guest(d / "ssh/id_ed25519", self.vm.ports["ssh"], user)
            for _ in range(30):
                try:
                    g.sh("true")
                    break
                except (RuntimeError, subprocess.TimeoutExpired):
                    time.sleep(2)
            # Boot root over virtio-blk from now on if the rebuilt initramfs has the driver.
            if g.sh("lsinitramfs /boot/firmware/initramfs8 | grep -c 'virtio_blk' || true").strip() not in (b"", b"0"):
                (d / "initramfs-virtio").write_bytes(g.sh("cat /boot/firmware/initramfs8", timeout=120))
            self.vm.stop(poweroff=g.poweroff, timeout=120)
            st["provisioned"] = True
            (d / "state.json").write_text(json.dumps(st))
            progress("done", 1, 1)
        except Exception as e:  # noqa: BLE001 - report any failure to the UI
            self.vm.stop()
            shutil.rmtree(d, ignore_errors=True)  # a half-made image is useless; the user retries
            self.hub.emit("provision", stage="error", error=str(e))
        finally:
            self.busy = None
            self.hub.emit("images", images=self.images())

    def delete_image(self, name):
        if self.vm.proc and self.vm.proc.poll() is None:
            raise RuntimeError("stop the VM first")
        d = self.imgdir(name)
        for f in d.rglob("*"):
            f.chmod(0o644) if f.is_file() else None
        shutil.rmtree(d)

    # ---------- layouts ----------
    def layout_path(self, name):
        if not name or "/" in name or name.startswith(".") or len(name) > 64:
            raise ValueError("bad layout name")
        return self.data / "layouts" / f"{name}.json"


def make_handler(app, token, port):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_):
            pass

        def reply(self, code, body=b"", ctype="application/json"):
            if isinstance(body, (dict, list)):
                body = json.dumps(body).encode()
            elif isinstance(body, str):
                body = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def guard(self, need_token):
            if self.headers.get("Host") not in allowed_hosts:
                self.reply(403, {"error": "bad host"})
                return False
            q = parse_qs(urlparse(self.path).query)
            if need_token and not secrets.compare_digest(
                    self.headers.get("X-Zero-Lab-Token") or q.get("t", [""])[0], token):
                self.reply(403, {"error": "bad token"})
                return False
            return True

        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                if self.guard(False):
                    html = (STATIC / "index.html").read_text().replace("{{TOKEN}}", token)
                    self.reply(200, html, "text/html")
            elif path.startswith("/static/"):
                if not self.guard(False):
                    return
                f = (STATIC / path[len("/static/"):]).resolve()
                if STATIC not in f.parents or not f.is_file():
                    return self.reply(404, {"error": "not found"})
                self.reply(200, f.read_bytes(), TYPES.get(f.suffix, "application/octet-stream"))
            elif path == "/api/state":
                if self.guard(True):
                    self.reply(200, app.state())
            elif path == "/api/readiness":
                if self.guard(True):
                    self.reply(200, app.readiness())
            elif path == "/api/events":
                if self.guard(True):
                    self.events()
            elif path == "/api/layout":
                if self.guard(True):
                    try:
                        name = parse_qs(urlparse(self.path).query).get("name", [""])[0]
                        self.reply(200, app.layout_path(name).read_bytes())
                    except (ValueError, OSError) as e:
                        self.reply(404, {"error": str(e)})
            elif path == "/vnc":
                if self.guard(True):
                    self.vnc()
            else:
                self.reply(404, {"error": "not found"})

        def events(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            q = queue.Queue()
            with app.hub.lock:
                app.hub.clients.add(q)
            try:
                for line in app.hub.snapshot():
                    self.wfile.write(f"data: {line}\n\n".encode())
                self.wfile.flush()
                while True:
                    try:
                        self.wfile.write(f"data: {q.get(timeout=15)}\n\n".encode())
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
            except OSError:
                pass
            finally:
                with app.hub.lock:
                    app.hub.clients.discard(q)
                self.close_connection = True

        def vnc(self):
            """Hand the WebSocket upgrade to QEMU's own VNC websocket listener and pipe bytes."""
            if not app.vm.ports or app.vm.status == "stopped":
                return self.reply(409, {"error": "VM is not running"})
            try:
                up = socket.create_connection(("127.0.0.1", app.vm.ports["ws"]), timeout=5)
            except OSError:
                return self.reply(502, {"error": "display not ready"})
            up.settimeout(None)
            head = "GET / HTTP/1.1\r\n" + "".join(
                f"{k}: {v}\r\n" for k, v in self.headers.items() if k.lower() != "host"
            ) + f"Host: 127.0.0.1:{app.vm.ports['ws']}\r\n\r\n"
            up.sendall(head.encode())
            down = self.connection

            def pipe(a, b):
                try:
                    while data := a.recv(65536):
                        b.sendall(data)
                except OSError:
                    pass
                for s in (a, b):
                    try:
                        s.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass

            t = threading.Thread(target=pipe, args=(up, down), daemon=True)
            t.start()
            pipe(down, up)
            t.join()
            up.close()
            self.close_connection = True

        def do_POST(self):
            if not self.guard(True):
                return
            path = urlparse(self.path).path
            length = int(self.headers.get("Content-Length") or 0)
            if length > guest.MAX_UPLOAD:
                return self.reply(413, {"error": "too large"})
            raw = self.rfile.read(length)
            try:
                if path == "/api/project/file":
                    rel = self.headers.get("X-Path", "")
                    if guest.safe_name(rel) is None:
                        raise ValueError(f"bad file name: {rel!r}")
                    if sum(len(b) for _, b in app.files) + len(raw) > guest.MAX_UPLOAD:
                        raise ValueError("project is larger than 50 MB")
                    app.files.append((rel, raw))
                    return self.reply(200, {"staged": [r for r, _ in app.files]})
                body = json.loads(raw or b"{}")
                self.reply(200, self.post(path, body) or {"ok": True})
            except (ValueError, KeyError, PermissionError, RuntimeError, FileNotFoundError,
                    subprocess.TimeoutExpired) as e:
                self.reply(400 if not isinstance(e, PermissionError) else 409, {"error": str(e)})

        def post(self, path, b):
            if path == "/api/config":
                app.save_cfg(b)
                return app.state()
            if path == "/api/boot":
                app.boot()
            elif path == "/api/stop":
                threading.Thread(target=app.stop, daemon=True).start()
            elif path == "/api/gpio":
                if not app.gpio:
                    raise RuntimeError("VM is not running")
                app.gpio.drive(int(b["pin"]), 1 if b["level"] else 0)
            elif path == "/api/serial":
                app.vm.serial_write(str(b["text"]))
            elif path == "/api/image/add":
                app.add_image(b["name"], b["source"], b["user"], b["password"])
            elif path == "/api/image/delete":
                app.delete_image(b["name"])
            elif path == "/api/project/clear":
                app.files = []
            elif path in ("/api/project/run", "/api/project/stop", "/api/project/autostart"):
                if not app.guest or app.vm.status != "running":
                    raise RuntimeError("boot the VM first")
                if path.endswith("/run"):
                    if not app.files:
                        raise ValueError("drop a project first")
                    app.guest.stop_program()
                    app.guest.push(guest.pack(app.files))
                    app.guest.run(app.hub.emit)
                elif path.endswith("/stop"):
                    app.guest.stop_program()
                else:
                    app.guest.autostart(bool(b.get("on")))
            elif path == "/api/layout/save":
                app.layout_path(b["name"]).write_text(json.dumps(b["layout"]))
                return {"layouts": app.state()["layouts"]}
            elif path == "/api/layout/export":
                out = Path.home() / "Downloads" / f"{b['name']}.zerolab.json"
                out.write_bytes(app.layout_path(b["name"]).read_bytes())
                return {"path": str(out)}
            elif path == "/api/reveal":
                if b.get("what") not in app.paths() or b["what"] == "home":
                    raise ValueError("unknown location")
                app.reveal(b["what"])
            elif path == "/api/screenshot":
                out = app.vm.run / f"screen-{int(time.time())}.png"
                app.vm.qmp("screendump", filename=str(out), format="png")
                return {"path": str(out)}
            else:
                raise KeyError(path)

    return H


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--data", type=Path, default=default_data_dir())
    ap.add_argument("--open", action="store_true", help="open the UI in the default browser")
    ap.add_argument("--watch-stdin", action="store_true", help="exit when stdin closes (app wrapper)")
    args = ap.parse_args()

    app = App(args.data)
    token = secrets.token_urlsafe(24)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), None)
    port = srv.server_address[1]
    srv.RequestHandlerClass = make_handler(app, token, port)
    srv.daemon_threads = True
    url = f"http://127.0.0.1:{port}/"
    print(f"ZL_URL {url}", flush=True)

    def shutdown():
        app.stop()
        srv.shutdown()

    # Closing the terminal / WSL console window (SIGHUP) or a kill (SIGTERM) still stops the Pi cleanly.
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: threading.Thread(target=shutdown, daemon=True).start())
    if args.watch_stdin:
        threading.Thread(target=lambda: (sys.stdin.buffer.read(), shutdown()), daemon=True).start()
    if args.open:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        app.stop()


if __name__ == "__main__":
    main()
