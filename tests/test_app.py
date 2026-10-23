"""Unit checks: python3 -m unittest discover -s tests"""
import http.client
import json
import os
import socket
import struct
import sys
import tarfile
import io
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import fdt  # noqa: E402
import gpio  # noqa: E402
import guest  # noqa: E402
import image  # noqa: E402
import server  # noqa: E402
import readiness  # noqa: E402
import vm  # noqa: E402


def tiny_dtb():
    """/ { chosen {}; soc { watchdog@7e100000 {status="okay"}; fb {}; mmc@7e202000 {}; mmc@7e300000 {dmas;dma-names}; mmcnr@7e300000 {} } }"""
    strings, body = bytearray(), bytearray()

    def s(name):
        i = strings.find(name.encode() + b"\0")
        if i < 0:
            i = len(strings)
            strings.extend(name.encode() + b"\0")
        return i

    def begin(n):
        body.extend(struct.pack(">I", 1) + n.encode() + b"\0")
        body.extend(b"\0" * (-len(body) % 4))

    def prop(n, v):
        body.extend(struct.pack(">III", 3, len(v), s(n)) + v)
        body.extend(b"\0" * (-len(body) % 4))

    end = lambda: body.extend(struct.pack(">I", 2))  # noqa: E731
    begin("")
    begin("chosen"); end()
    begin("soc")
    begin("watchdog@7e100000"); prop("status", b"okay\0"); end()
    begin("fb"); end()
    begin("mmc@7e202000"); prop("status", b"okay\0"); end()
    begin("mmc@7e300000"); prop("dmas", b"\0\0\0\x0b"); prop("dma-names", b"rx-tx\0"); prop("status", b"disabled\0"); end()
    begin("mmcnr@7e300000"); prop("status", b"okay\0"); end()
    end(); end()
    body.extend(struct.pack(">I", 9))
    rsv = b"\0" * 16
    off_struct = 40 + len(rsv)
    off_strings = off_struct + len(body)
    hdr = struct.pack(">10I", fdt.MAGIC, off_strings + len(strings), off_struct, off_strings, 40, 17, 16, 0,
                      len(strings), len(body))
    return hdr + rsv + bytes(body) + bytes(strings)


class FdtTest(unittest.TestCase):
    def test_roundtrip_and_edits(self):
        raw = tiny_dtb()
        self.assertEqual(fdt.Tree(raw).to_bytes(), raw)
        t = fdt.Tree(fdt.qemu_dtb(raw, "venus", "sd", {"zl-user": "pi"}))
        self.assertEqual(t.get("/soc/watchdog@7e100000", "status"), b"disabled\0")
        self.assertEqual(t.get("/soc/mmc@7e202000", "status"), b"disabled\0")
        self.assertEqual(t.get("/soc/mmc@7e300000", "status"), b"okay\0")
        self.assertIsNone(t.get("/soc/mmc@7e300000", "dmas"))
        self.assertEqual(t.get("/soc/mmc@7e300000", "non-removable"), b"")
        self.assertEqual(t.get("/chosen", "zl-gpu-mode"), b"venus\0")
        self.assertEqual(t.get("/chosen", "zl-user"), b"pi\0")
        v = fdt.Tree(fdt.qemu_dtb(raw, "soft", "virtio", {}))
        self.assertEqual(v.get("/soc/mmc@7e202000", "status"), b"okay\0")  # SD untouched for virtio root


class FakeQTest(threading.Thread):
    """Answers readl from a register dict and records writel."""

    def __init__(self, path, regs):
        super().__init__(daemon=True)
        self.regs, self.writes = regs, []
        self.srv = socket.socket(socket.AF_UNIX)
        self.srv.bind(path)
        self.srv.listen(1)

    def run(self):
        c, _ = self.srv.accept()
        f = c.makefile("rw")
        for line in f:
            op, addr, *val = line.split()
            if op == "readl":
                f.write(f"IRQ raise 1\nOK {self.regs.get(int(addr, 0), 0):#x}\n")
            else:
                self.writes.append((int(addr, 0), int(val[0], 0)))
                f.write("OK\n")
            f.flush()


class GpioTest(unittest.TestCase):
    def test_decode(self):
        fsel = [0] * 6
        fsel[1] = 1 << (3 * 7)  # GPIO17 output
        st = gpio.decode(fsel, 1 << 17 | 1 << 4, 1 << 1)
        self.assertEqual(st[17], (1, 1))
        self.assertEqual(st[4], (0, 1))
        self.assertEqual(st[33], (0, 1))

    def test_whitelist_and_drive(self):
        d = tempfile.mkdtemp(prefix="zlt-")
        path = os.path.join(d, "q.sock")
        regs = {gpio.GPFSEL[2]: 1 << (3 * 7)}  # GPIO27 output
        fake = FakeQTest(path, regs)
        fake.start()
        g = gpio.Gpio(gpio.QTest(path), lambda s: None, hz=5)
        with self.assertRaises(PermissionError):
            g.qt.readl(0x3F000000)
        with self.assertRaises(PermissionError):
            g.qt.writel(gpio.GPFSEL[0], 1)
        g.drive(17, 1)
        g.drive(17, 0)
        with self.assertRaises(PermissionError):
            g.drive(27, 1)  # guest output
        with self.assertRaises(ValueError):
            g.drive(40, 1)
        self.assertEqual(fake.writes, [(gpio.GPSET[0], 1 << 17), (gpio.GPCLR[0], 1 << 17)])
        g.stop()


class GuestTest(unittest.TestCase):
    def test_safe_names(self):
        self.assertEqual(guest.safe_name("proj/src/main.c"), "proj/src/main.c")
        self.assertEqual(guest.safe_name("./a\\b.py"), "a/b.py")
        for bad in ("../x", "/etc/passwd", "a/../../b", "", "."):
            self.assertIsNone(guest.safe_name(bad), bad)

    def test_pack(self):
        t = tarfile.open(fileobj=io.BytesIO(guest.pack([("p/main.py", b"print(1)")])))
        self.assertEqual(t.getnames(), ["p/main.py"])
        with self.assertRaises(ValueError):
            guest.pack([("../evil", b"")])


class ImageTest(unittest.TestCase):
    def test_user_data(self):
        ud = image.user_data("pi", 'p"a\\ss: #x', "ssh-ed25519 AAAA zero-lab")
        self.assertIn('plain_text_passwd: "p\\"a\\\\ss: #x"', ud)
        for bad in ("Root", "1pi", "a b", ""):
            with self.assertRaises(ValueError):
                image.user_data(bad, "x", "k")
        with self.assertRaises(ValueError):
            image.user_data("pi", "", "k")

    def test_bootfs_offset_and_partuuid(self):
        mbr = bytearray(512)
        mbr[440:444] = (0x719289EB).to_bytes(4, "little")
        mbr[446 + 8:446 + 12] = (8192).to_bytes(4, "little")
        mbr[510:512] = b"\x55\xaa"
        with tempfile.NamedTemporaryFile() as f:
            f.write(mbr)
            f.flush()
            self.assertEqual(image.bootfs_offset(f.name), 8192 * 512)
            self.assertEqual(vm.img_partuuid(f.name), "719289eb-02")


class VmTest(unittest.TestCase):
    def test_resolve_and_argv(self):
        h = {"accels": ["hvf", "tcg"], "gpus": ["venus", "soft"]}
        c = vm.resolve({"ram": 9999, "gpu": "virgl", "accel": "auto"}, h)
        self.assertEqual((c["ram"], c["gpu"], c["accel"]), (1024, "venus", "hvf"))
        d = Path(tempfile.mkdtemp())
        mbr = bytearray(512)
        mbr[510:512] = b"\x55\xaa"
        (d / "base.img").write_bytes(mbr)
        (d / "initramfs-virtio").write_bytes(b"x")
        a = vm.build_argv("qemu", c, d, d, {"ssh": 2222, "ws": 5701, "vnc": 5999})
        s = " ".join(a)
        self.assertIn("-accel hvf", s)
        self.assertIn("venus=on", s)
        self.assertIn("virtio-blk-device", s)
        self.assertIn("hostfwd=tcp:127.0.0.1:2222-:22", s)
        self.assertIn("-vnc 127.0.0.1:99,websocket=127.0.0.1:5701", s)
        self.assertNotIn("restrict=on", s)
        # launcher parity (raspi-zero2w 5fbae66, 053bc65)
        for want in ("systemd.mask=NetworkManager-wait-online.service", "systemd.mask=systemd-networkd-wait-online.service",
                     "systemd.mask=wayvnc.service", "dwc_otg.fiq_enable=0", "dwc_otg.fiq_fsm_enable=0",
                     "bus=virtio-mmio-bus.0", "virtio-blk-device,bus=virtio-mmio-bus.1", "cache=writeback",
                     "snapshot=off", "root=PARTUUID="):
            self.assertIn(want, s)
        self.assertNotIn("rpi-resize-swap-file", s)  # virtio root keeps Pi OS swap (zram)
        soft = " ".join(vm.build_argv("qemu", {**c, "gpu": "soft"}, d, d, {"ssh": 1, "ws": 2, "vnc": 5901}))
        self.assertIn("virtio-gpu-device,bus=virtio-mmio-bus.0", soft)
        p = " ".join(vm.build_argv("qemu", {**c, "network": False}, d, d, {"ssh": 1, "ws": 2, "vnc": 5901}, "provision"))
        self.assertIn("if=sd", p)
        self.assertIn("restrict=on", p)
        self.assertIn("virtio-gpu-device", p)


class ReadinessTest(unittest.TestCase):
    HOST_FAST = {"accels": ["hvf", "tcg"], "gpus": ["venus", "soft"]}
    HOST_SLOW = {"accels": ["tcg"], "gpus": ["soft"]}
    IMG = {"name": "desktop", "label": "Raspberry Pi OS with desktop", "provisioned": True, "boot_files": True, "user": "pi"}

    def rows(self, r):
        return {x["id"]: x for x in r["rows"]}

    def test_nothing_yet(self):
        r = readiness.check(self.HOST_FAST, (True, "QEMU 11.1"), [], None, None, 100 * readiness.GB, image.CATALOG)
        rows = self.rows(r)
        self.assertFalse(r["ready"])
        self.assertEqual(rows["image"]["state"], "missing")
        self.assertEqual(rows["image"]["fix"]["action"], "download")
        self.assertEqual(rows["kernel"]["state"], "waiting")
        self.assertIn("Nothing to download", rows["kernel"]["detail"])
        self.assertEqual(rows["user"]["state"], "waiting")

    def test_all_green(self):
        r = readiness.check(self.HOST_FAST, (True, "QEMU 11.1"), [self.IMG], "desktop", None, 100 * readiness.GB, image.CATALOG)
        self.assertTrue(r["ready"])
        self.assertEqual(r["level"], "ok")

    def test_slow_host_still_ready(self):
        r = readiness.check(self.HOST_SLOW, (True, "QEMU 11.1"), [self.IMG], "desktop", None, 100 * readiness.GB, image.CATALOG)
        self.assertTrue(r["ready"])
        self.assertEqual(r["level"], "warn")
        self.assertEqual(self.rows(r)["accel"]["state"], "warn")

    def test_blockers(self):
        broken = readiness.check(self.HOST_FAST, (False, "no binary"), [self.IMG], "desktop", None, 100 * readiness.GB, image.CATALOG)
        self.assertFalse(broken["ready"])
        full = readiness.check(self.HOST_FAST, (True, "QEMU"), [self.IMG], "desktop", None, 1 * readiness.GB, image.CATALOG)
        self.assertEqual(self.rows(full)["disk"]["state"], "missing")
        self.assertFalse(full["ready"])
        busy = readiness.check(self.HOST_FAST, (True, "QEMU"), [], None, "setting up desktop", 100 * readiness.GB, image.CATALOG)
        self.assertEqual(self.rows(busy)["image"]["state"], "waiting")
        self.assertFalse(busy["ready"])

    def test_qemu_probe_reports_failure(self):
        ok, text = readiness.qemu_probe(lambda: ("/nonexistent/qemu", None, None), lambda d: dict(os.environ))
        self.assertFalse(ok)
        self.assertTrue(text)


class CacheTest(unittest.TestCase):
    def test_sparse_decompress(self):
        import lzma
        d = Path(tempfile.mkdtemp())
        data = b"boot" + bytes(5 << 20) + b"root"
        (d / "a.img.xz").write_bytes(lzma.compress(data))
        image.decompress(d / "a.img.xz", d / "a.img", lambda *a: None)
        self.assertEqual((d / "a.img").read_bytes(), data)

    def test_download_resumes_and_cache_is_reused(self):
        import functools
        import hashlib
        import http.server
        import lzma
        payload = lzma.compress(b"pi" + bytes(1 << 20))
        hits = []

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                start = int(self.headers.get("Range", "bytes=0-")[6:-1] or 0)
                hits.append(start)
                self.send_response(206 if start else 200)
                self.end_headers()
                self.wfile.write(payload[start:])

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        entry = {"url": f"http://127.0.0.1:{srv.server_address[1]}/t.img.xz", "size": len(payload),
                 "sha256": hashlib.sha256(payload).hexdigest()}
        cache = Path(tempfile.mkdtemp())
        (cache / "t.img.xz").write_bytes(payload[:100])  # an interrupted download
        p = image.cached_image(entry, cache, lambda *a: None)
        self.assertEqual(hits, [100])
        self.assertEqual(p.read_bytes()[:2], b"pi")
        self.assertFalse((cache / "t.img.xz").exists())
        image.cached_image(entry, cache, lambda *a: None)  # second setup: no network at all
        self.assertEqual(hits, [100])
        srv.shutdown()


class SerialTest(unittest.TestCase):
    def test_colour_codes_split_across_chunks(self):
        out, carry = vm.clean_serial("", "Welcome to \x1b[1mDebian\x1b[0;3")
        self.assertEqual((out, carry), ("Welcome to Debian", "\x1b[0;3"))
        out, carry = vm.clean_serial(carry, "2m  OK  \x1b[0m]\r\n")
        self.assertEqual((out, carry), ("  OK  ]\n", ""))


class PngTest(unittest.TestCase):
    def test_ppm_to_png(self):
        import zlib
        d = Path(tempfile.mkdtemp())
        (d / "a.ppm").write_bytes(b"P6\n# QEMU\n2 1\n255\n" + bytes([255, 0, 0, 0, 255, 0]))
        vm.ppm_to_png(d / "a.ppm", d / "a.png")
        png = (d / "a.png").read_bytes()
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", png[16:24]), (2, 1))
        idat = png[png.index(b"IDAT") + 4:png.index(b"IEND") - 8]
        self.assertEqual(zlib.decompress(idat), b"\0" + bytes([255, 0, 0, 0, 255, 0]))


class FilesTest(unittest.TestCase):
    def test_guest_path(self):
        self.assertEqual(guest.guest_path("/home/pi/../pi/x"), "/home/pi/x")
        self.assertEqual(guest.guest_path("/"), "/")
        for bad in ("home/pi", "", "/a\nb", "/a\0b", None):
            with self.assertRaises(ValueError):
                guest.guest_path(bad)

    def test_download_names(self):
        self.assertEqual(guest.download_name("/home/pi/notes.txt"), "notes.txt")
        self.assertEqual(guest.download_name("/home/pi/proj/", folder=True), "proj.tar.gz")
        self.assertEqual(guest.download_name("/"), "pi-root")
        self.assertEqual(guest.download_name('/x/a:b*?.txt'), "ab.txt")

    def test_open_exclusive_never_follows_or_overwrites(self):
        d = Path(tempfile.mkdtemp())
        outside = Path(tempfile.mkdtemp()) / "target"
        (d / "a.txt").write_text("keep")
        os.symlink(outside, d / "b.txt")
        f, p = guest.open_exclusive(str(d), "a.txt")
        f.close()
        self.assertEqual(Path(p).name, "a (2).txt")
        self.assertEqual((d / "a.txt").read_text(), "keep")
        f, p = guest.open_exclusive(str(d), "b.txt")
        f.close()
        self.assertEqual(Path(p).name, "b (2).txt")
        self.assertFalse(outside.exists())


class FakeFiles:
    def __init__(self):
        self.put_bytes, self.calls = b"", []

    def list(self, path, hidden=False):
        return {"path": path, "entries": [{"name": "a", "dir": True, "link": False, "size": 0, "mtime": 0}]}

    def home(self):
        return "/home/pi"

    def put(self, path, reader, length, overwrite=False):
        if path.endswith("exists.txt") and not overwrite:
            reader.read(length)
            raise FileExistsError(path)
        self.put_bytes = reader.read(length)
        self.calls.append(("put", path))

    def get(self, path, downloads):
        self.calls.append(("get", path, str(downloads)))
        return str(downloads / "x")

    def __getattr__(self, name):  # mkdir, rename, delete, terminal
        return lambda *a: self.calls.append((name, *a))


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = server.App(Path(tempfile.mkdtemp()))
        srv = server.ThreadingHTTPServer(("127.0.0.1", 0), None)
        cls.port = srv.server_address[1]
        srv.RequestHandlerClass = server.make_handler(cls.app, "tok", cls.port)
        threading.Thread(target=srv.serve_forever, daemon=True).start()

    def req(self, method, path, host=None, token=None, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port)
        h = {"Host": host or f"127.0.0.1:{self.port}"}
        if token:
            h["X-Zero-Lab-Token"] = token
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
        r = c.getresponse()
        out = r.status, r.read()
        c.close()
        return out

    def test_guards(self):
        self.assertEqual(self.req("GET", "/", host="evil.example:80")[0], 403)
        self.assertEqual(self.req("GET", "/api/state")[0], 403)
        self.assertEqual(self.req("POST", "/api/config", body={})[0], 403)
        self.assertEqual(self.req("POST", "/api/config", token="nope", body={})[0], 403)
        code, body = self.req("GET", "/api/state", token="tok")
        self.assertEqual(code, 200)
        self.assertIn("catalog", json.loads(body))
        code, body = self.req("GET", "/")
        self.assertEqual(code, 200)
        self.assertIn(b'"tok"', body)
        self.assertEqual(self.req("GET", "/static/../server.py")[0], 404)

    def test_settings_locked_while_running(self):
        class Running:
            def poll(self):
                return None
        self.app.vm.proc = Running()
        try:
            code, body = self.req("POST", "/api/config", token="tok", body={"ram": 256})
            self.assertEqual(code, 400)
            self.assertIn(b"Stop the Pi", body)
        finally:
            self.app.vm.proc = None
        self.assertEqual(self.req("POST", "/api/config", token="tok", body={"ram": 256})[0], 200)

    def test_readiness_endpoint(self):
        code, body = self.req("GET", "/api/readiness", token="tok")
        self.assertEqual(code, 200)
        r = json.loads(body)
        self.assertEqual({x["id"] for x in r["rows"]}, {"qemu", "accel", "gpu", "image", "kernel", "user", "disk"})
        self.assertFalse(r["ready"])  # empty data dir: no image
        self.assertEqual(self.req("GET", "/api/readiness")[0], 403)

    def test_files_need_running_pi(self):
        code, body = self.req("GET", "/api/fs/list?path=/home/pi", token="tok")
        self.assertEqual(code, 400)
        self.assertIn(b"Boot the Pi", body)

    def test_files_endpoints(self):
        fake = FakeFiles()
        self.app.fs = lambda: fake
        try:
            self.assertEqual(json.loads(self.req("GET", "/api/fs/list?path=/home/pi", token="tok")[1])["entries"][0]["name"], "a")
            self.assertEqual(self.req("GET", "/api/fs/list?path=/home/pi")[0], 403)
            payload = os.urandom(3 * 1024 * 1024)  # streamed in chunks
            c = http.client.HTTPConnection("127.0.0.1", self.port)
            c.request("POST", "/api/fs/upload?path=/home/pi/blob.bin", body=payload,
                      headers={"Host": f"127.0.0.1:{self.port}", "X-Zero-Lab-Token": "tok"})
            self.assertEqual(c.getresponse().status, 200)
            c.close()
            self.assertEqual(fake.put_bytes, payload)
            c = http.client.HTTPConnection("127.0.0.1", self.port)
            c.request("POST", "/api/fs/upload?path=/home/pi/exists.txt", body=b"x",
                      headers={"Host": f"127.0.0.1:{self.port}", "X-Zero-Lab-Token": "tok"})
            self.assertEqual(c.getresponse().status, 409)
            c.close()
            self.assertEqual(self.req("POST", "/api/fs/upload?path=/x", body={})[0], 403)  # no token
            code, body = self.req("POST", "/api/fs/download", token="tok", body={"path": "/home/pi/a"})
            self.assertEqual(code, 200)
            self.assertEqual(fake.calls[-1][2], str(self.app.downloads))
            for ep, b in (("mkdir", {"path": "/home/pi/n"}), ("rename", {"path": "/home/pi/a", "name": "b"}),
                          ("delete", {"path": "/home/pi/b"}), ("terminal", {"path": "/home/pi"})):
                self.assertEqual(self.req("POST", f"/api/fs/{ep}", token="tok", body=b)[0], 200)
        finally:
            del self.app.fs

    def test_reveal_only_known_places(self):
        self.assertEqual(self.req("POST", "/api/reveal", token="tok", body={"what": "/etc/passwd"})[0], 400)

    def test_layout_names(self):
        self.assertEqual(self.req("POST", "/api/layout/save", token="tok", body={"name": "../x", "layout": {}})[0], 400)
        self.assertEqual(self.req("POST", "/api/layout/save", token="tok", body={"name": "ok", "layout": {"version": 1}})[0], 200)
        self.assertEqual(self.req("GET", "/api/layout?name=ok", token="tok")[0], 200)

    def test_upload_staging(self):
        s, _ = self.req("POST", "/api/project/clear", token="tok", body={})
        self.assertEqual(s, 200)
        c = http.client.HTTPConnection("127.0.0.1", self.port)
        c.request("POST", "/api/project/file", body=b"x",
                  headers={"Host": f"127.0.0.1:{self.port}", "X-Zero-Lab-Token": "tok", "X-Path": "../../etc/x"})
        self.assertEqual(c.getresponse().status, 400)
        c.close()


if __name__ == "__main__":
    unittest.main()
