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
        p = " ".join(vm.build_argv("qemu", {**c, "network": False}, d, d, {"ssh": 1, "ws": 2, "vnc": 5901}, "provision"))
        self.assertIn("if=sd", p)
        self.assertIn("restrict=on", p)
        self.assertIn("virtio-gpu-device", p)


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
