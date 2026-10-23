"""Get an official Raspberry Pi OS image and prepare it for QEMU. Nothing licensed ships with Zero Lab.

Layout of an image dir:
  base.img          the image as downloaded (read-only after prep; APFS/reflink clone of local files)
  disk.qcow2        persistent overlay on base.img, grown to 16 GiB (cloud-init grows the root fs)
  kernel8.img, stock.dtb   the image's own kernel (for its version) and device tree
  ssh/id_ed25519    key the app uses to push and run projects
  state.json
"""
import hashlib
import json
import lzma
import os
import platform
import plistlib
import re
import shutil
import struct
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from guest import openssh

BASE = "https://downloads.raspberrypi.com"
CATALOG = [
    {"id": "desktop", "desktop": True, "size": 1364720984,
     "name": "Raspberry Pi OS with desktop (64-bit, 2026-10-06)",
     "url": f"{BASE}/raspios_arm64/images/raspios_arm64-2026-10-06/2026-10-06-raspios-trixie-arm64.img.xz",
     "sha256": "976766570bee2aaf3047dd78649cfe82abb8fe9687b7f15030cd533ba4e9f7a9"},
    {"id": "full", "desktop": True, "size": 2064882780,
     "name": "Raspberry Pi OS with desktop and recommended software (64-bit, 2026-10-06)",
     "url": f"{BASE}/raspios_full_arm64/images/raspios_full_arm64-2026-10-06/2026-10-06-raspios-trixie-arm64-full.img.xz",
     "sha256": "e8c2d5fdbd5de9e97960a15004b7133878e84d9b02aee4745bdf0a2a2d6a8f59"},
    {"id": "lite", "desktop": False, "size": 550466056,
     "name": "Raspberry Pi OS Lite, no desktop (64-bit, 2026-10-06)",
     "url": f"{BASE}/raspios_lite_arm64/images/raspios_lite_arm64-2026-10-06/2026-10-06-raspios-trixie-arm64-lite.img.xz",
     "sha256": "483db18a48da399b5b7022ffae9a07bc6d99daab30e593aedac09b69ff422843"},
]
DISK_SIZE = "16G"
USER_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
BOOT_FILES = {"kernel8.img": "kernel8.img", "bcm2710-rpi-zero-2-w.dtb": "stock.dtb"}
USER_DATA = """#cloud-config
hostname: zerolab
manage_etc_hosts: true
growpart: {{mode: auto, devices: ["/"]}}
resize_rootfs: true
users:
  - name: {user}
    gecos: Zero Lab
    groups: [adm, dialout, cdrom, sudo, audio, video, plugdev, games, users, input, render, netdev, spi, i2c, gpio]
    shell: /bin/bash
    lock_passwd: false
    plain_text_passwd: {password}
    sudo: "ALL=(ALL) NOPASSWD:ALL"
    ssh_authorized_keys: [{pubkey}]
ssh_pwauth: true
"""  # the rest of first-boot setup is guest/provision.sh, which reports on the serial console


def sha256_file(path, progress=None):
    h, done = hashlib.sha256(), 0
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
            done += len(chunk)
            if progress:
                progress(done)
    return h.hexdigest()


def download(entry, dest, progress):
    """Stream the .xz into dest, resuming a partial file; refuse it unless the sha256 is the pinned one."""
    h, done = hashlib.sha256(), 0
    if dest.exists():  # an interrupted download: hash what we have and ask for the rest
        with open(dest, "rb") as f:
            while chunk := f.read(1 << 20):
                h.update(chunk)
                done += len(chunk)
    if done < entry["size"]:
        req = urllib.request.Request(entry["url"], headers={"Range": f"bytes={done}-"} if done else {})
        with urllib.request.urlopen(req, timeout=60) as r:
            if done and r.status != 206:  # server ignored the range: start over
                h, done = hashlib.sha256(), 0
            with open(dest, "ab" if done else "wb") as out:
                while chunk := r.read(1 << 20):
                    h.update(chunk)
                    out.write(chunk)
                    done += len(chunk)
                    progress("download", done, entry["size"])
    if h.hexdigest() != entry["sha256"]:
        dest.unlink()
        raise ValueError("download checksum mismatch; try again")


def set_sparse(f):
    """NTFS leaves skipped ranges unallocated only in files flagged sparse (APFS and ext4 always do)."""
    if os.name == "nt":
        import ctypes  # noqa: PLC0415
        import msvcrt  # noqa: PLC0415
        fsctl_set_sparse = 0x900C4
        ctypes.windll.kernel32.DeviceIoControl(ctypes.c_void_p(msvcrt.get_osfhandle(f.fileno())), fsctl_set_sparse,
                                               None, 0, None, 0, ctypes.byref(ctypes.c_ulong()), None)


def write_sparse(f, out, tick=None):
    """Copy f to out, seeking over all-zero 1 MiB blocks instead of writing them (faster, less disk)."""
    set_sparse(out)
    size, zero = 0, bytes(1 << 20)
    while chunk := f.read(1 << 20):
        if chunk == zero[:len(chunk)]:
            out.seek(len(chunk), 1)
        else:
            out.write(chunk)
        size += len(chunk)
        if tick:
            tick()
    out.truncate(size)


def decompress(src, dest, progress):
    """Unpack .xz -> sparse raw image."""
    total = src.stat().st_size
    with open(src, "rb") as raw, lzma.open(raw) as f, open(dest, "wb") as out:
        write_sparse(f, out, lambda: progress("decompress", raw.tell(), total))


def cached_image(entry, cache, progress):
    """Download and unpack an official image once; later setups clone the clean copy instantly."""
    cache.mkdir(parents=True, exist_ok=True)
    name = Path(entry["url"]).name  # e.g. 2026-10-06-raspios-trixie-arm64.img.xz
    pristine, ok = cache / name.removesuffix(".xz"), cache / (name.removesuffix(".xz") + ".ok")
    if pristine.exists() and ok.exists():
        progress("download", 1, 1)
        progress("decompress", 1, 1)
        return pristine
    xz = cache / name
    download(entry, xz, progress)
    tmp = pristine.with_suffix(".part")
    decompress(xz, tmp, progress)
    tmp.chmod(0o444)
    tmp.rename(pristine)
    ok.write_text(entry["sha256"])
    xz.unlink()  # the unpacked copy is what setups use; the .xz is only needed until then
    return pristine


def clone(src, dest):
    """Copy-on-write where the filesystem supports it (APFS, btrfs/xfs); on Windows a sparse copy."""
    if os.name == "nt":
        with open(src, "rb") as f, open(dest, "wb") as out:
            write_sparse(f, out)
        return
    flag = ["-c"] if platform.system() == "Darwin" else ["--reflink=auto"]
    if subprocess.run(["cp", *flag, str(src), str(dest)]).returncode:
        shutil.copyfile(src, dest)


def bootfs_extent(img):
    """-> (offset, size) in bytes of partition 1 (the FAT boot partition)."""
    with open(img, "rb") as f:
        mbr = f.read(512)
    if mbr[510:512] != b"\x55\xaa":
        raise ValueError("That file is not a Raspberry Pi OS disk image. Choose an official .img or .img.xz file.")
    return (int.from_bytes(mbr[446 + 8:446 + 12], "little") * 512,
            int.from_bytes(mbr[446 + 12:446 + 16], "little") * 512)


def bootfs_offset(img):
    return bootfs_extent(img)[0]


class Fat:
    """Just enough FAT16/FAT32 for the boot partition where hdiutil and mtools are missing (Windows): read a file
    in the root folder, or overwrite one that exists. No creating files, no subfolders."""

    def __init__(self, f, offset):
        self.f = f
        f.seek(offset)
        b = f.read(512)
        bps, self.spc, rsvd, nfats, rootents, tot16 = struct.unpack_from("<HBHBHH", b, 11)
        fatsz = struct.unpack_from("<H", b, 22)[0] or struct.unpack_from("<I", b, 36)[0]
        tot = tot16 or struct.unpack_from("<I", b, 32)[0]
        rootsecs = (rootents * 32 + bps - 1) // bps
        if b[510:512] != b"\x55\xaa" or not bps or not self.spc:
            raise ValueError("the boot partition is not FAT")
        self.csize, self.nfats, self.fatlen = bps * self.spc, nfats, fatsz * bps
        self.fatpos = offset + rsvd * bps
        self.rootpos, self.rootlen = self.fatpos + nfats * self.fatlen, rootents * 32  # FAT16's fixed root folder
        self.datapos = self.rootpos + rootsecs * bps  # cluster 2
        self.nclus = (tot - rsvd - nfats * fatsz - rootsecs) // self.spc
        if self.nclus < 4085:
            raise ValueError("FAT12 is not supported")
        self.fat32 = self.nclus >= 65525
        self.root = struct.unpack_from("<I", b, 44)[0] if self.fat32 else None
        self.fsinfo = offset + struct.unpack_from("<H", b, 48)[0] * bps if self.fat32 else None
        self.eoc = 0x0FFFFFF8 if self.fat32 else 0xFFF8
        f.seek(self.fatpos)
        self.fat = bytearray(f.read(self.fatlen))

    def entry(self, n):
        return struct.unpack_from("<I", self.fat, n * 4)[0] & 0x0FFFFFFF if self.fat32 else \
            struct.unpack_from("<H", self.fat, n * 2)[0]

    def set_entry(self, n, v):
        if self.fat32:  # the top 4 bits are reserved: keep them
            struct.pack_into("<I", self.fat, n * 4, struct.unpack_from("<I", self.fat, n * 4)[0] & 0xF0000000 | v)
        else:
            struct.pack_into("<H", self.fat, n * 2, v)

    def chain(self, c):
        out = []
        while 2 <= c < self.eoc and len(out) <= self.nclus:
            out.append(c)
            c = self.entry(c)
        return out

    def cluster(self, c):
        return self.datapos + (c - 2) * self.csize

    def find(self, name):
        """-> (position of the file's 32-byte entry, entry) in the root folder; long names (VFAT) included."""
        spans = [(self.cluster(c), self.csize) for c in self.chain(self.root)] if self.fat32 \
            else [(self.rootpos, self.rootlen)]
        lfn = []
        for start, length in spans:
            self.f.seek(start)
            buf = self.f.read(length)
            for i in range(0, length, 32):
                e = buf[i:i + 32]
                if e[0] == 0:
                    break
                if e[0] == 0xE5 or (e[11] & 0x08 and e[11] != 0x0F):  # deleted, or the volume label
                    lfn = []
                elif e[11] == 0x0F:  # long-name parts come last part first
                    lfn.insert(0, e[1:11] + e[14:26] + e[28:32])
                else:
                    short = e[:8].decode("latin-1").rstrip() + ("." + e[8:11].decode("latin-1").rstrip()
                                                                 if e[8:11].strip() else "")
                    long = b"".join(lfn).decode("utf-16-le", "replace").split("\0")[0] if lfn else short
                    lfn = []
                    if not e[11] & 0x10 and name.lower() in (long.lower(), short.lower()):
                        return start + i, bytearray(e)
            else:
                continue
            break
        raise FileNotFoundError(f"{name} is not on the boot partition")

    def first(self, e):
        return struct.unpack_from("<H", e, 26)[0] | (struct.unpack_from("<H", e, 20)[0] << 16 if self.fat32 else 0)

    def read(self, name):
        _, e = self.find(name)
        out = bytearray()
        for c in self.chain(self.first(e)):
            self.f.seek(self.cluster(c))
            out += self.f.read(self.csize)
        return bytes(out[:struct.unpack_from("<I", e, 28)[0]])

    def write(self, name, data):
        pos, e = self.find(name)
        for c in self.chain(self.first(e)):
            self.set_entry(c, 0)
        need = -(-len(data) // self.csize)
        unused = [c for c in range(2, self.nclus + 2) if self.entry(c) == 0]  # ponytail: linear scan, fine for 512 MB
        free = unused[:need]
        if len(free) < need:
            raise OSError("the boot partition is full")
        for i, c in enumerate(free):
            self.set_entry(c, free[i + 1] if i + 1 < need else 0x0FFFFFFF if self.fat32 else 0xFFFF)
            self.f.seek(self.cluster(c))
            self.f.write(data[i * self.csize:(i + 1) * self.csize])
        first = free[0] if free else 0
        struct.pack_into("<H", e, 20, first >> 16 if self.fat32 else 0)
        struct.pack_into("<HI", e, 26, first & 0xFFFF, len(data))
        self.f.seek(pos)
        self.f.write(e)
        for i in range(self.nfats):
            self.f.seek(self.fatpos + i * self.fatlen)
            self.f.write(self.fat)
        if self.fsinfo:  # FAT32 keeps a free-cluster count
            self.f.seek(self.fsinfo + 488)
            self.f.write(struct.pack("<I", len(unused) - need))


class BootFS:
    """Read/write files on the image's FAT boot partition: hdiutil on macOS, mtools on Linux, else Fat."""

    def __init__(self, img, whole=False):
        """whole=True: img is the FAT partition itself, not a disk image with an MBR."""
        self.img, self.whole, self.mount, self.dev, self.fat = Path(img), whole, None, None, None

    def __enter__(self):
        if platform.system() == "Darwin":
            out = subprocess.run(["hdiutil", "attach", "-plist", "-nobrowse",
                                  "-imagekey", "diskimage-class=CRawDiskImage", str(self.img)],
                                 capture_output=True, check=True).stdout
            ents = plistlib.loads(out)["system-entities"]
            self.dev = ents[0]["dev-entry"]
            self.mount = next(Path(e["mount-point"]) for e in ents
                              if e.get("mount-point") and (Path(e["mount-point"]) / "config.txt").exists())
        elif not shutil.which("mcopy"):
            self.file = open(self.img, "r+b")
            self.fat = Fat(self.file, 0 if self.whole else bootfs_offset(self.img))
        else:
            self.spec = f"{self.img}@@{0 if self.whole else bootfs_offset(self.img)}"
            # Pi OS FAT geometry trips mtools' sanity check ("not a multiple of sectors per track")
            self.env = {**os.environ, "MTOOLS_SKIP_CHECK": "1"}
        return self

    def __exit__(self, *_):
        if self.fat:
            self.file.close()
        if self.dev:
            subprocess.run(["hdiutil", "detach", self.dev], capture_output=True)

    def get(self, name, dest):
        if self.fat:
            Path(dest).write_bytes(self.fat.read(name))
        elif self.mount:
            shutil.copyfile(self.mount / name, dest)
        else:
            subprocess.run(["mcopy", "-n", "-i", self.spec, f"::{name}", str(dest)], check=True, env=self.env)

    def put(self, name, data):
        if self.fat:
            self.fat.write(name, data)
        elif self.mount:
            (self.mount / name).write_bytes(data)
        else:
            with tempfile.NamedTemporaryFile() as t:
                t.write(data)
                t.flush()
                subprocess.run(["mcopy", "-o", "-i", self.spec, t.name, f"::{name}"], check=True, env=self.env)


def user_data(user, password, pubkey):
    if not USER_RE.match(user):
        raise ValueError("user name: lowercase letters, digits, _ or -, starting with a letter")
    if not password or len(password) > 128:
        raise ValueError("password must be 1-128 characters")
    # JSON strings are valid YAML double-quoted scalars, so quoting is exact.
    return USER_DATA.format(user=user, password=json.dumps(password), pubkey=json.dumps(pubkey))


def prepare(source, imgdir, user, password, qemu_img, progress):
    """Everything up to (not including) the provisioning boot. source: catalog id or local path."""
    imgdir.mkdir(parents=True, exist_ok=True)
    base = imgdir / "base.img"
    entry = next((e for e in CATALOG if e["id"] == source), None)
    if entry:
        cache = imgdir.parent.parent / "cache"
        if not (cache / (Path(entry["url"]).name.removesuffix(".xz") + ".ok")).exists():
            need = entry["size"] * 6  # xz + decompressed image + headroom
            if shutil.disk_usage(imgdir).free < need:
                raise ValueError(f"need about {need >> 30} GB free disk space")
        clone(cached_image(entry, cache, progress), base)
    else:
        src = Path(source).expanduser()
        if not src.is_file():
            raise ValueError(f"no such image file: {src}")
        if src.suffix == ".xz":
            decompress(src, base, progress)
        else:
            clone(src, base)
    base.chmod(0o644)  # a clone keeps its source's 0444 (cache, read-only file): the boot partition must be writable
    progress("prepare", 0, 1)
    bootfs_offset(base)  # fail early, in plain words, on a file that is not a Pi OS image
    ssh = imgdir / "ssh"
    ssh.mkdir(exist_ok=True)
    key = ssh / "id_ed25519"
    key.unlink(missing_ok=True)
    (ssh / "id_ed25519.pub").unlink(missing_ok=True)
    subprocess.run([openssh("ssh-keygen"), "-q", "-t", "ed25519", "-N", "", "-C", "zero-lab", "-f", str(key)], check=True)
    if os.name == "nt":  # Windows OpenSSH refuses a key others can read; ours inherits the data folder's access list
        subprocess.run(["icacls", str(key), "/inheritance:r", "/grant:r", f"{os.environ['USERNAME']}:F"],
                       check=True, capture_output=True)
    with BootFS(base) as fs:
        for name, local in BOOT_FILES.items():
            fs.get(name, imgdir / local)
        fs.put("user-data", user_data(user, password, (ssh / "id_ed25519.pub").read_text().strip()).encode())
    base.chmod(0o444)
    subprocess.run([str(qemu_img), "create", "-q", "-f", "qcow2", "-b", str(base), "-F", "raw",
                    str(imgdir / "disk.qcow2"), DISK_SIZE], check=True)
    state = {"source": source, "user": user, "provisioned": False,
             "desktop": entry["desktop"] if entry else True}
    (imgdir / "state.json").write_text(json.dumps(state))
    progress("prepare", 1, 1)
    return state
