# Zero Lab

A friendly app around an emulated **Raspberry Pi Zero 2 W**. Boot Raspberry Pi OS, use its desktop, wire virtual buttons, switches, knobs, LEDs and 7-segment displays to its GPIO pins, move files in and out, and drop in your own code to build and run on the Pi.

Zero Lab runs on **[qemu-raspi-zero2w](https://github.com/dsellerbrock/qemu-raspi-zero2w)**, our QEMU fork with:
- external GPIO with edge interrupts for the BCM2835;
- virtio-gpu and virtio-blk on the `raspi3ap` board;
- Apple Hypervisor (HVF) support, using a 4 KiB IPA granule;
- Venus (Vulkan) graphics through MoltenVK/Metal.

<!-- screenshots -->

## Get it
- **macOS** (Apple Silicon, 26+): `Zero-Lab-<version>-macOS-arm64.dmg`. CPU runs on HVF; graphics are Venus (Vulkan via Metal).
- **Linux**: `Zero-Lab-<version>-linux-windows.zip`, then `bash setup.sh` (or double-click `Install Zero Lab (Linux).desktop`). It builds the bundled QEMU fork and adds a menu icon.
- **Windows 10/11**: the same zip; double-click `Install Zero Lab (Windows).cmd`. It sets up WSL2 + Ubuntu and runs `setup.sh` there.

Downloads: https://pisim.ellerbrock.dev. Instructions for friends: [docs/FRIENDS.md](docs/FRIENDS.md).

## What's in the window
- **First run.** A checklist shows what the Pi needs (emulator, speed-up, graphics, Raspberry Pi OS, user, disk space), and three steps download and set up the official image. No Pi firmware is needed. Zero Lab ships the Pi OS kernel rebuilt with virtio built in (screen and fast disk; recipe in [kernel/](kernel)), and the device tree comes from the image.
- **The Pi's screen**, through noVNC over QEMU's VNC websocket.
- **GPIO breadboard.** A 40-pin header shown by physical position, plus parts you can drag onto it. Layouts save as JSON in `~/Library/Application Support/Zero Lab/layouts` (Linux: `~/.local/share/zero-lab/layouts`).
- **Files sidebar.** Browse the Pi's file system; drop files in; download files and folders to `~/Downloads`.
- **Your code.** Drop Python, C/C++ (Makefile/CMake), Rust, Go or an ARM binary. It is built and run inside the Pi, never on your computer. The [samples](samples) cover each GPIO part: button-led (Python and C), switch, knob, 7-segment, probe and LED blink.
- **Settings** in a drawer (memory, cores, speed-up, graphics, screen, internet, throw-away mode), each with an explanation.

## Build from source
You need macOS 26+ on Apple Silicon with Xcode command-line tools and Homebrew (`meson ninja pkg-config glib pixman libslirp`), or Linux.

```bash
git clone https://github.com/dsellerbrock/zero-lab.git
```

```bash
cd zero-lab
```

**macOS app and dmg.** The QEMU fork is fetched from GitHub at the pinned commit. virglrenderer and libepoxy sources come from `ZL_VIRGL_SRC` and `ZL_EPOXY_SRC`; MoltenVK comes from `ZL_MOLTENVK`.

```bash
mac/build-bundle.sh all
```

**Linux and Windows zip** (includes all sources):

```bash
tools/make-linux-windows-bundle.sh
```

**Run from a checkout** against any build of the fork:

```bash
ZL_QEMU_DIR=/path/to/qemu/prefix python3 app/server.py --open
```

**Tests:**

```bash
python3 -m unittest discover -s tests
```

`tests/e2e.py` drives a real boot through the same API the UI uses: image setup, boot, Files, and every GPIO sample.

## Layout
```
app/            server.py (stdlib HTTP + SSE + VNC websocket pipe), vm.py (QEMU args, QMP, serial),
                gpio.py (QTest, GPIO registers only), image.py (download, verify, provision), fdt.py (DTB editor),
                guest.py (SSH: code + files), readiness.py, guest/ (scripts that run inside the Pi),
                static/ (UI, vendored noVNC and B612 fonts)
mac/            ZeroLab.swift (window), build-bundle.sh (deps -> qemu -> app -> dmg), relocate.py
linux/ windows/ installers
samples/        one program + layout per GPIO part
kernel/         build.sh + config for the Pi kernel (Pi OS 6.18.50 with virtio built in)
tools/          source-bundle.sh (GPL sources), make-linux-windows-bundle.sh, shoot.sh (screenshots)
```

## Security model
- **Local access.** The UI binds `127.0.0.1` only. Every request needs a `127.0.0.1`/`localhost` Host header. POSTs, the event stream and the VNC socket also need a per-launch token.
- **GPIO.** QTest is restricted to the BCM2835 GPIO registers.
- **Code and files.** Dropped code and files go to the Pi over SSH, which is forwarded on loopback only. Code runs only inside the Pi. The file browser writes on your computer only into `~/Downloads`, never following symlinks or overwriting.

## Licence and source
Zero Lab is GPL-2.0-or-later.
- **Source.** This repo and [qemu-raspi-zero2w](https://github.com/dsellerbrock/qemu-raspi-zero2w). The Pi kernel's source is a separate release asset (`…-kernel-source.tar`), or run `kernel/build.sh source`. Every release also carries the exact sources it was built from: the "Source code (GPL)" folder on the dmg and `sources/` in the zip.
- **Third-party components.** [THIRD-PARTY.md](THIRD-PARTY.md).
- **Raspberry Pi OS** is downloaded from raspberrypi.com and is not included. "Raspberry Pi" is a trademark of Raspberry Pi Ltd. Zero Lab is not affiliated with Raspberry Pi Ltd.
