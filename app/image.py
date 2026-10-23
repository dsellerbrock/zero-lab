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
import subprocess
import tempfile
import urllib.request
from pathlib import Path

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


def decompress(src, dest, progress):
    """Unpack .xz -> sparse raw image: all-zero blocks are skipped, not written (faster, less disk)."""
    total, size = src.stat().st_size, 0
    zero = bytes(1 << 20)
    with open(src, "rb") as raw, lzma.open(raw) as f, open(dest, "wb") as out:
        while chunk := f.read(1 << 20):
            if chunk == zero[:len(chunk)]:
                out.seek(len(chunk), 1)
            else:
                out.write(chunk)
            size += len(chunk)
            progress("decompress", raw.tell(), total)
        out.truncate(size)


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
    """Copy-on-write where the filesystem supports it (APFS, btrfs/xfs), plain copy otherwise."""
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


class BootFS:
    """Read/write files on the image's FAT boot partition: hdiutil on macOS, mtools on Linux."""

    def __init__(self, img, whole=False):
        """whole=True: img is the FAT partition itself, not a disk image with an MBR."""
        self.img, self.whole, self.mount, self.dev = Path(img), whole, None, None

    def __enter__(self):
        if platform.system() == "Darwin":
            out = subprocess.run(["hdiutil", "attach", "-plist", "-nobrowse",
                                  "-imagekey", "diskimage-class=CRawDiskImage", str(self.img)],
                                 capture_output=True, check=True).stdout
            ents = plistlib.loads(out)["system-entities"]
            self.dev = ents[0]["dev-entry"]
            self.mount = next(Path(e["mount-point"]) for e in ents
                              if e.get("mount-point") and (Path(e["mount-point"]) / "config.txt").exists())
        else:
            self.spec = f"{self.img}@@{0 if self.whole else bootfs_offset(self.img)}"
            # Pi OS FAT geometry trips mtools' sanity check ("not a multiple of sectors per track")
            self.env = {**os.environ, "MTOOLS_SKIP_CHECK": "1"}
        return self

    def __exit__(self, *_):
        if self.dev:
            subprocess.run(["hdiutil", "detach", self.dev], capture_output=True)

    def get(self, name, dest):
        if self.mount:
            shutil.copyfile(self.mount / name, dest)
        else:
            subprocess.run(["mcopy", "-n", "-i", self.spec, f"::{name}", str(dest)], check=True, env=self.env)

    def put(self, name, data):
        if self.mount:
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
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "zero-lab", "-f", str(key)], check=True)
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
