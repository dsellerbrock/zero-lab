"""QEMU process: argument builder, QMP, serial console, lifecycle."""
import base64
import codecs
import gzip
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import fdt

APP = Path(__file__).resolve().parent
DEFAULTS = {"ram": 512, "cpus": 4, "accel": "auto", "gpu": "auto", "snapshot": False,
            "network": True, "display": "app"}
GPUS = ("venus", "virgl", "soft")
READY_MARK = "ZL_DESKTOP_READY"
ANSI = re.compile(r"\x1b\[[0-9;:?]*[A-Za-z]|\x1b[()][A-Za-z0-9]|\r")
ANSI_TAIL = re.compile(r"\x1b(\[[0-9;:?]*|[()])?$")  # an escape sequence cut off at the end of a chunk


def clean_serial(carry, text):
    """-> (printable text, carry). Strips colour/cursor codes, holding back a sequence split across chunks."""
    text = carry + text
    m = ANSI_TAIL.search(text)
    carry = text[m.start():] if m else ""
    if m:
        text = text[:m.start()]
    return ANSI.sub("", text), carry


def host():
    """What this machine can do. Acceleration only exists for ARM guests on ARM hosts."""
    system, arch = platform.system(), platform.machine().lower()
    mac_ver = int(platform.mac_ver()[0].split(".")[0] or 0) if system == "Darwin" else 0
    accels = ["tcg"]
    if system == "Darwin" and arch == "arm64":
        import readiness  # noqa: PLC0415 - small module, avoids a cycle
        if readiness.hvf_supported():
            accels.insert(0, "hvf")
    if system == "Darwin":
        # Venus needs HVF's 4 KiB IPA granule (macOS 26+) or TCG; virgl needs ANGLE (not bundled).
        gpus = ["venus", "soft"] if mac_ver >= 26 or arch != "arm64" else ["soft"]
    else:
        gpus = ["soft"] + (["venus", "virgl"] if os.path.exists("/dev/dri/renderD128") else [])
    displays = ["app", "window"] if system == "Darwin" else ["app"]  # Linux build has no SDL/GTK
    return {"system": system, "arch": arch, "macos": mac_ver, "accels": accels, "gpus": gpus,
            "displays": displays}


def resolve(cfg, h):
    """Fill 'auto' choices from the host probe."""
    cfg = {**DEFAULTS, **cfg}
    if cfg["accel"] not in h["accels"]:
        cfg["accel"] = h["accels"][0]
    if cfg["gpu"] not in h["gpus"]:
        cfg["gpu"] = h["gpus"][0]
    if cfg["display"] not in h.get("displays", ["app"]):
        cfg["display"] = "app"
    cfg["ram"] = max(256, min(1024, int(cfg["ram"])))
    cfg["cpus"] = max(1, min(4, int(cfg["cpus"])))
    return cfg


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def qemu_paths():
    """Bundled QEMU (macOS .app or Linux setup) unless ZL_QEMU_DIR overrides it."""
    for d in (os.environ.get("ZL_QEMU_DIR"), APP.parent / "qemu",
              Path.home() / ".local/share/zero-lab/qemu"):
        if d and (Path(d) / "bin/qemu-system-aarch64").exists():
            d = Path(d)
            return d / "bin/qemu-system-aarch64", d / "bin/qemu-img", d
    q = shutil.which("qemu-system-aarch64")
    if not q:
        raise FileNotFoundError("QEMU not found; run the Zero Lab setup first")
    return Path(q), Path(shutil.which("qemu-img") or "qemu-img"), None


def qemu_env(qdir):
    env = dict(os.environ)
    if qdir:
        lib = str(qdir / "lib")
        key = "DYLD_LIBRARY_PATH" if platform.system() == "Darwin" else "LD_LIBRARY_PATH"
        env[key] = lib + (":" + env[key] if env.get(key) else "")
        server = qdir / "libexec/virgl_render_server"
        if server.exists():
            env["RENDER_SERVER_EXEC_PATH"] = str(server)
    return env


def build_argv(qemu, cfg, img, run, ports, mode="desktop"):
    """mode: 'desktop' (normal use) or 'provision' (first boot, headless, SD root).

    Mirrors raspi-zero2w/start-pi.sh --desktop; see that script for the why of each flag.
    """
    virtio_root = mode == "desktop" and (img / "initramfs-virtio").exists()
    append = [f"root=PARTUUID={img_partuuid(img / 'base.img')}", "rootfstype=ext4", "rw", "rootwait",
              "console=tty1", "console=ttyAMA1,115200",
              # QEMU's DWC2 enumerates reliably with the FIQ off
              "dwc_otg.fiq_fsm_enable=0", "dwc_otg.fiq_enable=0"]
    # wayvnc restart-loops without a GPU session, and the network wait times out under QEMU user-net.
    append += ["systemd.mask=wayvnc.service", "systemd.mask=wayvnc-control.service",
               "systemd.mask=vncserver-virtuald.service", "systemd.mask=systemd-networkd-wait-online.service",
               # raspi-zero2w 053bc65: a slow DHCP lease otherwise holds the desktop back to 84-107 s
               "systemd.mask=NetworkManager-wait-online.service",
               # no EEPROM in QEMU, and fstrim over the SD path costs minutes on first boot
               "systemd.mask=rpi-eeprom-update.service", "systemd.mask=fstrim.service", "systemd.mask=fstrim.timer"]
    # The setup script (desktop) or first-boot script (provision) travels in the DTB and runs as root.
    append += ["systemd.unit=kernel-command-line.target",
               # as raspi-zero2w/start-pi.sh does: base64 -i skips the property's trailing NUL. (An earlier
               # `tr -d \\000` reached tr as `\\000` and deleted every 0 in the base64, so nothing ran.)
               "systemd.run=\"/bin/sh -c 'base64 -di /proc/device-tree/chosen/zl-setup | gzip -dc | /bin/sh'\"",
               "systemd.run_success_action=none", "systemd.run_failure_action=none"]
    if mode == "desktop":
        append += ["systemd.show_status=false"]
    else:
        # Same first-boot masks as raspi-zero2w/start-pi.sh PI_FIRSTBOOT_WAIT: Plymouth holds the console
        # (and getty waits on plymouth-quit-wait); the apt/man-db timers only slow the first boot down.
        append += ["systemd.mask=plymouth-start.service",
                   "systemd.mask=plymouth-quit.service", "systemd.mask=plymouth-quit-wait.service",
                   "systemd.mask=apt-daily.timer", "systemd.mask=apt-daily-upgrade.timer", "systemd.mask=man-db.timer"]

    disk = f"file={img / 'disk.qcow2'},format=qcow2,snapshot={'on' if cfg['snapshot'] else 'off'}"
    argv = [str(qemu), "-name", "Zero Lab", "-M", "raspi3ap", "-m", f"{cfg['ram']}M",
            "-smp", str(cfg["cpus"]), "-kernel", str(img / "kernel8.img"),
            "-dtb", str(run / "boot.dtb"),
            "-chardev", f"socket,id=uart,path={run / 'serial.sock'},server=on,wait=off,logfile={run / 'serial.log'}",
            "-serial", "chardev:uart",
            "-monitor", "none", "-qmp", f"unix:{run / 'qmp.sock'},server=on,wait=off",
            "-qtest", f"unix:{run / 'qtest.sock'},server=on,wait=off",
            "-usb", "-device", "usb-kbd", "-device", "usb-tablet"]
    argv += ["-accel", "hvf"] if cfg["accel"] == "hvf" else ["-accel", "tcg,thread=multi"]
    if virtio_root:
        argv += ["-initrd", str(img / "initramfs-virtio"),
                 "-drive", f"if=none,id=root,cache=writeback,{disk}",
                 "-device", "virtio-blk-device,bus=virtio-mmio-bus.1,drive=root"]
    else:
        argv += ["-drive", f"if=sd,{disk}"]
    net = f"user,id=net0,hostfwd=tcp:127.0.0.1:{ports['ssh']}-:22"
    if not cfg["network"]:
        net += ",restrict=on"  # no internet; the SSH forward still works
    argv += ["-netdev", net, "-device", "usb-net,netdev=net0"]

    gpu = cfg["gpu"] if mode == "desktop" else "soft"
    if gpu == "venus":
        argv += ["-device", "virtio-gpu-gl-device,bus=virtio-mmio-bus.0,id=gpu0,blob=on,hostmem=256M,venus=on"]
    elif gpu == "virgl":
        argv += ["-device", "virtio-gpu-gl-device,bus=virtio-mmio-bus.0,id=gpu0,blob=on,hostmem=256M"]
    else:
        argv += ["-device", "virtio-gpu-device,bus=virtio-mmio-bus.0,id=gpu0"]
    if cfg["display"] == "window" and mode == "desktop":
        argv += ["-display", "cocoa" if platform.system() == "Darwin" else "sdl"]
    else:
        argv += ["-display", "egl-headless" if gpu == "virgl" else "none"]
        argv += ["-vnc", f"127.0.0.1:{ports['vnc'] - 5900},websocket=127.0.0.1:{ports['ws']}"
                 + (",display=gpu0" if gpu == "virgl" else "")]
    argv += ["-append", " ".join(append), "-no-reboot"]
    return argv


def ppm_to_png(ppm, png):
    """QEMU's screendump writes PPM everywhere (PNG needs libpng, which our builds leave out)."""
    import struct
    import zlib
    data = Path(ppm).read_bytes()
    parts, pos = [], 0
    while len(parts) < 4:  # magic, width, height, maxval; skip whitespace and comments
        while data[pos:pos + 1].isspace():
            pos += 1
        if data[pos:pos + 1] == b"#":
            pos = data.index(b"\n", pos)
            continue
        end = pos
        while not data[end:end + 1].isspace():
            end += 1
        parts.append(data[pos:end])
        pos = end
    w, h = int(parts[1]), int(parts[2])
    pix = data[pos + 1:pos + 1 + w * h * 3]
    raw = b"".join(b"\0" + pix[y * w * 3:(y + 1) * w * 3] for y in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))  # noqa: E731
    Path(png).write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                          + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def img_partuuid(base):
    """Raspberry Pi OS roots by PARTUUID = <MBR disk signature>-02."""
    with open(base, "rb") as f:
        f.seek(440)
        return f"{int.from_bytes(f.read(4), 'little'):08x}-02"


class QMP:
    def __init__(self, path, timeout=10):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        self.sock.connect(str(path))
        self.f = self.sock.makefile("rw", encoding="utf-8")
        json.loads(self.f.readline())  # greeting
        self.cmd("qmp_capabilities")

    def cmd(self, name, **args):
        self.f.write(json.dumps({"execute": name, "arguments": args}) + "\n")
        self.f.flush()
        while True:
            msg = json.loads(self.f.readline())
            if "return" in msg:
                return msg["return"]
            if "error" in msg:
                raise RuntimeError(msg["error"].get("desc"))

    def close(self):
        self.sock.close()


def wait_for(path, proc, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        if Path(path).exists():
            return True
        if proc.poll() is not None:
            return False
        time.sleep(0.1)
    return False


class VM:
    """One QEMU at a time. emit(type, **data) publishes events to the UI."""

    def __init__(self, emit):
        self.emit = emit
        self.proc = None
        self.run = None
        self.ports = None
        self.status = "stopped"
        self.started = None
        self.serial = None
        self.cfg = None
        self.mode = self.img = None
        self.lock = threading.Lock()

    def set_status(self, status, **extra):
        self.status = status
        self.emit("status", status=status, **extra)

    def start(self, cfg, img, mode="desktop", setup_script=None, chosen=None, ready=READY_MARK):
        with self.lock:
            if self.proc and self.proc.poll() is None:
                raise RuntimeError("VM already running")
            qemu, _, qdir = qemu_paths()
            self.cfg, self.ready, self.seen, self.mode, self.img = cfg, ready, set(), mode, img
            # Short socket dir: AF_UNIX paths are limited to ~104 bytes on macOS.
            self.run = Path(tempfile.mkdtemp(prefix="zl-"))
            self.ports = {"ssh": free_port(), "ws": free_port(), "vnc": free_port()}
            props = {"zl-epoch": str(int(time.time())), **(chosen or {})}  # the Pi has no RTC
            if setup_script:
                props["zl-setup"] = base64.b64encode(gzip.compress(setup_script.encode(), mtime=0)).decode()
            gpu = cfg["gpu"] if mode == "desktop" else "soft"
            root = "virtio" if mode == "desktop" and (img / "initramfs-virtio").exists() else "sd"
            (self.run / "boot.dtb").write_bytes(
                fdt.qemu_dtb((img / "stock.dtb").read_bytes(), gpu, root, props))
            argv = build_argv(qemu, cfg, img, self.run, self.ports, mode)
            (self.run / "argv.json").write_text(json.dumps(argv, indent=1))
            log = open(self.run / "qemu.log", "wb")
            self.proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                         env=qemu_env(qdir), start_new_session=True)
            self.started = time.time()
            self.set_status("booting", mode=mode, cfg=cfg)
        if not wait_for(self.run / "serial.sock", self.proc):
            self.set_status("stopped", error=self.log_tail())
            raise RuntimeError("QEMU did not start:\n" + self.log_tail())
        threading.Thread(target=self._serial_reader, daemon=True).start()
        threading.Thread(target=self._reaper, daemon=True).start()

    def log_tail(self):
        try:
            return (self.run / "qemu.log").read_text(errors="replace")[-2000:]
        except OSError:
            return ""

    def _serial_reader(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(str(self.run / "serial.sock"))
        self.serial = s
        buf, carry = "", ""
        decode = codecs.getincrementaldecoder("utf-8")("replace").decode  # characters split across reads
        while True:
            try:
                data = s.recv(4096)
            except OSError:
                break
            if not data:
                break
            text, carry = clean_serial(carry, decode(data))
            if text:
                self.emit("serial", data=text)
            buf = (buf + text)[-4096:]
            if self.ready in buf and self.status == "booting":
                buf = ""
                self.set_status("running", boot_seconds=round(time.time() - self.started, 1))
            if "reboot: Power down" in buf or "System halted" in buf:
                buf = ""
                try:  # raspi has no power controller: QEMU keeps running after guest poweroff
                    self.qmp("quit")
                except (OSError, RuntimeError):
                    pass
            for mark in re.findall(r"ZL_[A-Z_]+", buf):
                if mark not in self.seen:
                    self.seen.add(mark)
                    self.emit("marker", name=mark)

    def serial_write(self, text):
        if self.serial:
            self.serial.sendall(text.encode())

    def _reaper(self):
        code = self.proc.wait()
        if self.serial:
            self.serial.close()
            self.serial = None
        self.set_status("stopped", exit_code=code)

    def qmp(self, name, **args):
        q = QMP(self.run / "qmp.sock")
        try:
            return q.cmd(name, **args)
        finally:
            q.close()

    def stop(self, poweroff=None, timeout=45):
        """poweroff(): asks the guest to shut down (over SSH); the serial reader quits QEMU
        on "Power down". Without it, or if the guest hangs, QEMU is quit directly."""
        if not self.proc or self.proc.poll() is not None:
            return
        self.set_status("stopping")
        if poweroff:
            try:
                poweroff()
            except Exception:  # noqa: BLE001 - any failure falls through to quit
                timeout = 0
        else:
            timeout = 0
        try:
            self.proc.wait(timeout)
        except subprocess.TimeoutExpired:
            try:
                self.qmp("quit")
            except (OSError, RuntimeError):
                self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
