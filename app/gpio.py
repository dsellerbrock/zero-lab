"""GPIO over QEMU's QTest socket, restricted to the BCM2835 GPIO block.

QTest can read/write any guest memory, so this module only ever touches the
GPIO registers below. The fork's bcm2835_gpio model raises edge interrupts when
GPSET/GPCLR change a level, so guest gpiozero/libgpiod edge waits work.
"""
import socket
import threading
import time

BASE = 0x3F200000
GPFSEL = [BASE + 4 * i for i in range(6)]      # 3 bits per pin, 10 pins per register
GPSET = (BASE + 0x1C, BASE + 0x20)
GPCLR = (BASE + 0x28, BASE + 0x2C)
GPLEV = (BASE + 0x34, BASE + 0x38)
ALLOWED = set(GPFSEL) | set(GPSET) | set(GPCLR) | set(GPLEV)
PINS = 54
HEADER_PINS = 28  # BCM 0-27 are on the 40-pin header


class QTest:
    def __init__(self, path, timeout=5):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        self.sock.connect(path)
        self.reader = self.sock.makefile("r", encoding="ascii", newline="\n")
        self.lock = threading.Lock()

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    def _cmd(self, text):
        with self.lock:
            self.sock.sendall((text + "\n").encode("ascii"))
            while True:
                line = self.reader.readline()
                if not line:
                    raise ConnectionError("QTest socket closed")
                if line.startswith("OK"):
                    return line.split()
                if line.startswith("FAIL"):
                    raise RuntimeError(line.strip())
                # anything else (e.g. "IRQ raise ...") is async noise; skip it

    def readl(self, addr):
        if addr not in ALLOWED:
            raise PermissionError(f"QTest read outside GPIO block: {addr:#x}")
        return int(self._cmd(f"readl {addr:#x}")[1], 0)

    def writel(self, addr, value):
        if addr not in ALLOWED or addr in GPFSEL or addr in GPLEV:
            raise PermissionError(f"QTest write not allowed: {addr:#x}")
        self._cmd(f"writel {addr:#x} {value:#x}")


def decode(fsel_regs, lev0, lev1):
    """-> list of (function, level) per pin; function 0=input, 1=output, 2..7=alt."""
    out = []
    for pin in range(PINS):
        fn = (fsel_regs[pin // 10] >> (3 * (pin % 10))) & 7
        lev = (lev1 >> (pin - 32)) & 1 if pin >= 32 else (lev0 >> pin) & 1
        out.append((fn, lev))
    return out


class Gpio:
    """Polls pin state and lets the UI drive input pins."""

    def __init__(self, qtest, on_change, hz=30):
        self.qt, self.on_change, self.period = qtest, on_change, 1 / hz
        self.state = None
        self.stopped = threading.Event()
        threading.Thread(target=self._poll, daemon=True).start()

    def _read(self):
        fsel = [self.qt.readl(a) for a in GPFSEL]
        return decode(fsel, self.qt.readl(GPLEV[0]), self.qt.readl(GPLEV[1]))

    def _poll(self):
        while not self.stopped.is_set():
            try:
                state = self._read()
            except (OSError, ConnectionError, RuntimeError):
                break
            if state != self.state:
                self.state = state
                self.on_change(state)
            time.sleep(self.period)

    def drive(self, pin, level):
        """Drive an input pin from a widget. Refuses pins the guest uses as outputs/alt."""
        if not 0 <= pin < HEADER_PINS:
            raise ValueError("pin must be BCM 0-27")
        fn = self._read()[pin][0]
        if fn != 0:
            raise PermissionError(f"GPIO{pin} is not an input in the guest (function {fn})")
        bank, bit = pin // 32, 1 << (pin % 32)
        self.qt.writel((GPSET if level else GPCLR)[bank], bit)

    def stop(self):
        self.stopped.set()
        self.qt.close()
