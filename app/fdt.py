"""Minimal flattened device tree (DTB) editor: parse, edit properties, write back.

Enough for the handful of edits Zero Lab makes to the stock Raspberry Pi DTB,
so friends need no dtc/fdtput.
"""
import struct

MAGIC = 0xD00DFEED
BEGIN, END, PROP, NOP, FINISH = 1, 2, 3, 4, 9


class Node:
    def __init__(self, name):
        self.name = name
        self.props = {}      # insertion-ordered: name -> bytes
        self.children = []

    def child(self, name):
        for c in self.children:
            if c.name == name:
                return c
        raise KeyError(name)


class Tree:
    def __init__(self, data):
        (magic, _total, off_struct, off_strings, off_rsv, self.version,
         self.last_comp, self.boot_cpu, size_strings, size_struct) = struct.unpack(">10I", data[:40])
        if magic != MAGIC:
            raise ValueError("not a DTB")
        self.rsvmap = data[off_rsv:off_struct]
        strings = data[off_strings:off_strings + size_strings]
        p, stack, self.root = off_struct, [], None
        while True:
            (tok,) = struct.unpack(">I", data[p:p + 4])
            p += 4
            if tok == BEGIN:
                end = data.index(b"\0", p)
                node = Node(data[p:end].decode())
                p = (end + 4) & ~3
                if stack:
                    stack[-1].children.append(node)
                else:
                    self.root = node
                stack.append(node)
            elif tok == END:
                stack.pop()
            elif tok == PROP:
                length, name_off = struct.unpack(">II", data[p:p + 8])
                p += 8
                name = strings[name_off:strings.index(b"\0", name_off)].decode()
                stack[-1].props[name] = data[p:p + length]
                p = (p + length + 3) & ~3
            elif tok == NOP:
                pass
            elif tok == FINISH:
                break
            else:
                raise ValueError(f"bad token {tok:#x}")

    def node(self, path):
        n = self.root
        for part in path.strip("/").split("/"):
            if part:
                n = n.child(part)
        return n

    def set(self, path, name, value):
        """value: str (NUL-terminated string), bytes, or None to delete."""
        props = self.node(path).props
        if value is None:
            props.pop(name, None)
        else:
            props[name] = value.encode() + b"\0" if isinstance(value, str) else bytes(value)

    def get(self, path, name):
        return self.node(path).props.get(name)

    def to_bytes(self):
        body, strings, offsets = bytearray(), bytearray(), {}

        def emit(node):
            body.extend(struct.pack(">I", BEGIN) + node.name.encode() + b"\0")
            body.extend(b"\0" * (-len(body) % 4))
            for name, value in node.props.items():
                if name not in offsets:
                    offsets[name] = len(strings)
                    strings.extend(name.encode() + b"\0")
                body.extend(struct.pack(">III", PROP, len(value), offsets[name]) + value)
                body.extend(b"\0" * (-len(body) % 4))
            for c in node.children:
                emit(c)
            body.extend(struct.pack(">I", END))

        emit(self.root)
        body.extend(struct.pack(">I", FINISH))
        off_rsv = 40
        off_struct = off_rsv + len(self.rsvmap)
        off_strings = off_struct + len(body)
        total = off_strings + len(strings)
        header = struct.pack(">10I", MAGIC, total, off_struct, off_strings, off_rsv, self.version,
                             self.last_comp, self.boot_cpu, len(strings), len(body))
        return header + self.rsvmap + bytes(body) + bytes(strings)


def qemu_dtb(stock, gpu, root, chosen):
    """Stock bcm2710-rpi-zero-2-w.dtb -> the DTB Zero Lab boots.

    Same edits as raspi-zero2w's raspios-sdhci.dtb + prepare-gpu-dtb.sh virgl mode:
    no watchdog (QEMU lacks it), SD card on SDHCI in PIO mode (the SDHOST path is flaky),
    and virtio-gpu owns the display instead of the firmware framebuffer.
    SPI0 is on (/dev/spidev0.0 reads the emulated MCP3008 ADC), and I2C1 (the emulated
    HT16K33 7-segment backpack at 0x70 and 16x2 LCD at 0x27).
    """
    t = Tree(stock)
    t.set("/soc/watchdog@7e100000", "status", "disabled")
    if root == "sd":
        t.set("/soc/mmc@7e202000", "status", "disabled")
        t.set("/soc/mmc@7e300000", "status", "okay")
        t.set("/soc/mmc@7e300000", "non-removable", b"")
        t.set("/soc/mmc@7e300000", "dmas", None)
        t.set("/soc/mmc@7e300000", "dma-names", None)
        t.set("/soc/mmcnr@7e300000", "status", "disabled")
    t.set("/soc/fb", "status", "disabled")
    # The Pi firmware adds the board revision; without it gpiozero (and pinctrl) won't run. 902120: Zero 2 W 1.0
    if not any(c.name == "system" for c in t.root.children):
        t.root.children.append(Node("system"))
    t.set("/system", "linux,revision", (0x902120).to_bytes(4, "big"))
    # dtparam=spi=on: SPI0 and its spidev@0/@1 children, for the fork's MCP3008 ADC on CE0
    t.set("/soc/spi@7e204000", "status", "okay")
    # dtparam=i2c_arm=on: I2C1 on GPIO2/3 (/dev/i2c-1; setup.sh loads i2c-dev), for the fork's I2C displays
    t.set("/soc/i2c@7e804000", "status", "okay")
    t.set("/chosen", "zl-gpu-mode", gpu)
    for name, value in chosen.items():
        t.set("/chosen", name, value)
    return t.to_bytes()
