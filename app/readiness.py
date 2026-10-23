"""What the Pi needs before it can boot, as a checklist of real probes (the UI's stop light).

Each row: id, title, state ("ok" | "warn" | "missing" | "waiting"), detail (plain words),
required (blocks Boot unless ok), fix (an action the UI can offer, or None).
"""
import os
import subprocess

GB = 1 << 30


def qemu_probe(paths_fn, env_fn):
    """-> (ok, text). Runs the QEMU we would boot with, so a broken install shows up here."""
    try:
        qemu, _, qdir = paths_fn()
        out = subprocess.run([str(qemu), "--version"], capture_output=True, text=True, timeout=10, env=env_fn(qdir))
        if out.returncode == 0:
            ver = out.stdout.splitlines()[0].replace("QEMU emulator version ", "QEMU ")
            return True, f"{ver}, included with Zero Lab" if qdir else ver
        return False, (out.stderr or out.stdout).strip().splitlines()[-1][:200]
    except (OSError, IndexError, subprocess.TimeoutExpired) as e:
        return False, str(e)


def check(host, qemu, images, active, busy, free_bytes, catalog, kernel=(None, None)):
    """host: vm.host(); qemu: (ok, text); images: App.images(); active: name of the image to boot or None;
    busy: provisioning message or None; free_bytes: free space where images live."""
    rows = []

    def row(id, title, state, detail, required, fix=None, short=None):
        rows.append({"id": id, "title": title, "state": state, "detail": detail, "required": required, "fix": fix,
                     "short": short or {"ok": "Ready", "warn": "Works, slower", "missing": "Needed", "waiting": "Later"}[state]})

    ok, text = qemu
    row("qemu", "Emulator (QEMU)", "ok" if ok else "missing",
        text if ok else f"Not working: {text}. Reinstall Zero Lab or run its setup again.", True,
        short="Included" if ok else "Broken")

    if "hvf" in host["accels"]:
        row("accel", "Speed-up", "ok", "Apple's hypervisor runs the Pi's CPU on your Mac's own cores.", False,
            short="Fast (HVF)")
    else:
        row("accel", "Speed-up", "warn",
            "Not available here, so the Pi's CPU is emulated. Everything works, just several times slower.", False,
            short="Emulated, slower")

    if "venus" in host["gpus"]:
        row("gpu", "Graphics", "ok", "The Pi's 3D graphics run on your computer's GPU.", False, short="On your GPU")
    else:
        row("gpu", "Graphics", "warn", "Drawn in software. The desktop works; 3D apps are slow.", False,
            short="Software")

    img = next((i for i in images if i["name"] == active), None) or next((i for i in images if i.get("provisioned")), None)
    desktop = next(e for e in catalog if e["id"] == "desktop")
    if img and img.get("provisioned"):
        row("image", "Raspberry Pi OS", "ok", f"{img['label']}.", True)
    elif busy:
        row("image", "Raspberry Pi OS", "waiting", "Being set up now: download, unpack, then the first boot.", True,
            short="Setting up")
    else:
        row("image", "Raspberry Pi OS", "missing",
            "No disk image yet. Zero Lab downloads the official one and checks it, or uses a file you have.", True,
            {"action": "download", "label": f"Download ({desktop['size'] / 1e9:.1f} GB)",
             "alt": {"action": "choose", "label": "Choose file"}})

    # Kernel: Zero Lab ships the Pi OS kernel rebuilt with virtio (screen + fast disk); the device tree comes
    # from the image. Its version must match the image's so the image's own modules load.
    kpath, kver = kernel
    iver = img.get("kernel_version") if img else None
    if not kpath:
        row("kernel", "Kernel and device tree", "missing",
            "Zero Lab's Pi kernel is missing from this install. Reinstall Zero Lab.", True, short="Missing")
    elif iver and kver and iver != kver:
        row("kernel", "Kernel and device tree", "warn",
            f"This image's kernel is {iver}; Zero Lab's is {kver}. Use the official 2026-10-06 image for a working desktop.",
            False, short="Version differs")
    else:
        row("kernel", "Kernel and device tree", "ok",
            f"Included with Zero Lab ({kver}, with virtio for the screen and fast disk); the device tree comes from"
            " the Pi OS image. Nothing to download separately.", True, short="Included")

    if img and img.get("provisioned"):
        row("user", "Your Pi user", "ok", f"Set up on first boot (user “{img.get('user', 'pi')}”).", True)
    elif busy:
        row("user", "Your Pi user", "waiting", "Created during the first boot, after the download.", True,
            short="First boot")
    else:
        row("user", "Your Pi user", "waiting", "You choose a name and password; the first boot creates it.", True,
            short="Step 2 below")

    need = (desktop["size"] * 6 if not img else 2 * GB)
    free_gb = free_bytes / GB
    if free_bytes < need:
        row("disk", "Disk space", "missing", f"{free_gb:.0f} GB free; Zero Lab needs about {need / GB:.0f} GB.", True,
            {"action": "reveal", "label": "Show Zero Lab's folder"}, short=f"{free_gb:.0f} GB free")
    elif free_bytes < 2 * need:
        row("disk", "Disk space", "warn", f"{free_gb:.0f} GB free. Enough, but getting low.", False,
            short=f"{free_gb:.0f} GB free")
    else:
        row("disk", "Disk space", "ok", f"Plenty: Zero Lab needs about {need / GB:.0f} GB{' for the image' if not img else ' to keep running'}.",
            False, short=f"{free_gb:.0f} GB free")

    ready = all(r["state"] == "ok" for r in rows if r["required"])
    return {"ready": ready, "rows": rows,
            "level": "ok" if ready and all(r["state"] == "ok" for r in rows)
            else "warn" if ready else "missing"}


def hvf_supported():
    """macOS reports whether Hypervisor.framework can run guests on this machine."""
    try:
        return subprocess.run(["sysctl", "-n", "kern.hv_support"], capture_output=True, text=True,
                              timeout=5).stdout.strip() == "1"
    except OSError:
        return os.path.exists("/System/Library/Frameworks/Hypervisor.framework")
