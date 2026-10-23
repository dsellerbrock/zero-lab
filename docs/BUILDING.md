# Building Zero Lab

Every download is built from this repository alone. Every input comes from a pinned URL and commit (or a release with a sha256) in [`tools/pins.sh`](../tools/pins.sh), so nothing depends on the builder's own folders. You can build three ways:

- **CI.** GitHub → Actions → **Build installers** → *Run workflow*, or push a tag `v*`. Each download appears as an artifact of the run ([`.github/workflows/build.yml`](../.github/workflows/build.yml)).
- **By hand**, with the per-platform commands below.
- **One piece at a time.** Each script has steps, e.g. `mac/build-bundle.sh deps|qemu|app|dmg`.

## What gets built

| Download | Built on | Command |
|---|---|---|
| `Zero-Lab-<v>-macOS-arm64.dmg` | macOS 26+, Apple Silicon | `mac/build-bundle.sh all` |
| `Zero-Lab-<v>-linux-windows.zip` (WSL / build-from-source fallback) | Linux or macOS | `tools/make-linux-windows-bundle.sh` |
| `Zero-Lab-<v>-kernel-source.tar` (GPL source of the Pi kernel) | anywhere | made by the zip step (`kernel/build.sh source`) |
| The Pi kernel `kernel/kernel8-virtio.img` (an input to all of the above) | Linux or macOS with Docker | `kernel/build.sh` |

`<v>` is `CFBundleShortVersionString` in `mac/Info.plist`.

## 1. The Pi kernel (once, or when `kernel/config` changes)

Zero Lab boots Raspberry Pi OS's own kernel (linux 6.18.50-1+rpt1), rebuilt with virtio-mmio, virtio-blk and virtio-gpu built in. Requirements: Docker or colima. On an x86 host it cross-compiles; on arm64 it builds natively.

```bash
ZL_JOBS=4 kernel/build.sh
```

This fetches the Debian source package from archive.raspberrypi.com, checks its sha256, builds in `debian:trixie`, and writes `kernel/kernel8-virtio.img`. The binary is gitignored. CI builds it in the `kernel` job and caches it.

## 2. macOS app and dmg

Requirements: macOS 26+ on Apple Silicon, the Xcode command-line tools (macOS 26 SDK) and Homebrew.

```bash
brew install meson ninja pkg-config glib pixman libslirp librsvg
```

```bash
ZL_JOBS=3 mac/build-bundle.sh all
```

The steps:
1. `deps` builds PCRE2, libepoxy and virglrenderer (with Venus), fetching UTM's forks by commit, plus the Khronos EGL/GLES headers.
2. `qemu` builds the QEMU fork at `ZL_QEMU_COMMIT` (a shallow fetch).
3. `app` assembles `build/mac/Zero Lab.app` with python-build-standalone, QEMU, MoltenVK 1.4.2 (the official release), the kernel and the samples. It then relocates and ad-hoc signs everything, giving QEMU the hypervisor entitlement.
4. `dmg` makes `build/mac/Zero-Lab-<v>-macOS-arm64.dmg`: the app, an Applications link, "Read me first", and the complete GPL source.

To build against a local checkout of the fork while developing it, set `ZL_QEMU_REPO=/path/to/clone`.

## 3. Linux / Windows-WSL zip

Requirements:
- Linux: `apt install librsvg2-bin imagemagick xz-utils zip git`.
- macOS: `brew install librsvg imagemagick`.

```bash
tools/make-linux-windows-bundle.sh
```

This writes `build/Zero-Lab-<v>-linux-windows.zip` (the installers, app, samples, kernel and all sources) and `build/Zero-Lab-<v>-kernel-source.tar`. On a friend's machine, `setup.sh` (Linux) or `setup.ps1` (Windows, via WSL2) builds QEMU from the bundled sources.

## GPL sources

`tools/source-bundle.sh DIR` collects the complete corresponding source:
- the QEMU fork at the pin (via QEMU's `archive-source.sh`);
- virglrenderer and libepoxy at their pins;
- this repository at HEAD;
- on macOS, the glib and gettext sources of the exact versions Homebrew installed, checked against the publishers' checksums.

`VERSIONS.txt` records every version used. The dmg and the zip both include this folder. The kernel's source is its own release asset because it's 157 MB.

## Testing a build

Unit tests (any platform):

```bash
python3 -m unittest discover -s tests
```

The end-to-end test drives a real Pi through the same API the UI uses: setup, boot, screenshot, Files, and every sample including the ADC and the I2C displays. It needs a running engine; use a separate HOME so it doesn't touch your own Zero Lab data:

```bash
HOME=/tmp/zl-test ZL_QEMU_DIR="build/mac/Zero Lab.app/Contents/Resources/qemu" python3 app/server.py --port 8660 &
```

```bash
python3 tests/e2e.py --url http://127.0.0.1:8660 --provision desktop --image e2e --gpu venus
```

On Linux or WSL, use `--gpu soft --accel tcg`. GitHub's macOS runners can't use the Apple Hypervisor, so the e2e runs on real machines before a release, not in CI.

## Releasing

1. Bump `CFBundleShortVersionString` in `mac/Info.plist`. Bump pins in `tools/pins.sh` if needed.
2. Push a tag `v<version>`; CI builds every download.
3. Run the e2e on a Mac, on Linux, and on Windows against the CI artifacts.
4. Create a **draft** release with the artifacts. A person reviews it and publishes it.

```bash
gh release create v<version> --repo dsellerbrock/pisim --draft --title "Zero Lab <version>" <files>
```

## Bumping a pin

- **QEMU fork:** push the commit to github.com/dsellerbrock/qemu-raspi-zero2w first, then set `ZL_QEMU_COMMIT` in `tools/pins.sh`.
- **virglrenderer, libepoxy, Khronos headers:** change the commit.
- **MoltenVK:** change the release URL and its sha256 together.

Every platform's build reads the same file.
