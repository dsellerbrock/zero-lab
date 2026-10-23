# Third-party components

Zero Lab's own code is GPL-2.0-or-later (see LICENSE); its source is https://github.com/dsellerbrock/zero-lab. The binaries it ships contain:

| Component | Version | Licence | Where | Source |
|---|---|---|---|---|
| QEMU fork [qemu-raspi-zero2w](https://github.com/dsellerbrock/qemu-raspi-zero2w) (GPIO events, raspi3ap virtio-mmio, HVF 4 KiB granule, Venus) | d4fa079b | GPL-2.0 | all | `qemu-zero-lab-<commit>.tar.xz` in the source folder, and https://github.com/dsellerbrock/qemu-raspi-zero2w |
| Linux kernel, Raspberry Pi OS rpi-v8 with virtio built in (`kernel/kernel8-virtio.img`) | 6.18.50-1+rpt1 | GPL-2.0 | all | release asset `Zero-Lab-<version>-kernel-source.tar` (the Debian source package from archive.raspberrypi.com plus `kernel/config` and `kernel/build.sh`) |
| virglrenderer (Venus) | pinned commit | MIT | all | `virglrenderer-<commit>.tar.xz` |
| libepoxy | pinned commit | MIT | macOS | `libepoxy-<commit>.tar.xz` |
| GLib | 2.90.1 | LGPL-2.1-or-later | macOS (dynamic library, replaceable) | `glib-2.90.1.tar.xz` |
| gettext libintl | 1.0 | LGPL-2.1-or-later | macOS (dynamic library, replaceable) | `gettext-1.0.tar.gz` |
| PCRE2 | 10.49 | BSD-3-Clause | macOS | https://github.com/PCRE2Project/pcre2/releases/tag/pcre2-10.49 |
| pixman | 0.46.4 | MIT | macOS | https://cairographics.org/releases/pixman-0.46.4.tar.gz |
| libslirp | 4.9.5 | BSD-3-Clause | macOS | https://gitlab.freedesktop.org/slirp/libslirp |
| MoltenVK | prebuilt | Apache-2.0 | macOS | https://github.com/KhronosGroup/MoltenVK |
| CPython (python-build-standalone) | 3.12.12 | PSF-2.0 (+ bundled lib licences) | macOS | https://github.com/astral-sh/python-build-standalone |
| B612 and B612 Mono fonts (latin subset, woff2) | Google Fonts build of 1.008 | SIL OFL 1.1 | all | `app/static/fonts/` (licence: `app/static/fonts/OFL.txt`), https://github.com/polarsys/b612 |
| noVNC | 1.7.0 | MPL-2.0 (core), MIT (pako) | all | shipped as source in `app/static/novnc/` (licence: `app/static/novnc/LICENSE.txt`) |

On Linux and Windows (WSL), QEMU and virglrenderer are built from the bundled sources on your machine, and the other libraries come from your distribution.

Raspberry Pi OS itself is not included. Zero Lab downloads it from raspberrypi.com, where it is offered under its own licences. "Raspberry Pi" is a trademark of Raspberry Pi Ltd. Zero Lab is not affiliated with Raspberry Pi Ltd.
