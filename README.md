# Zero Lab

A friendly app around an emulated **Raspberry Pi Zero 2 W** (QEMU fork with GPIO edge events). It has VM settings, Boot/Stop, the Pi's screen, a GPIO sandbox (buttons, switches, knobs, LEDs, 7-segment displays, a logic probe), and drop-in code that is built and run inside the Pi.

- **macOS (Apple Silicon, 26+):** `Zero Lab.app` in a `.dmg`. HVF CPU acceleration plus Venus (Vulkan → Metal) GPU.
- **Linux:** `setup.sh` builds the bundled QEMU fork and installs a menu/desktop launcher.
- **Windows:** `setup.ps1` (started from `Install Zero Lab (Windows).cmd`) sets up WSL2 + Ubuntu and runs `setup.sh` there.

Friends' instructions: [docs/FRIENDS.md](docs/FRIENDS.md). Design: `raspi-zero2w/docs/pi-emulator-app-design.md`.

## Layout
```
app/            server.py (stdlib HTTP + SSE + VNC websocket pipe), vm.py (QEMU args, QMP, serial),
                gpio.py (QTest, GPIO registers only), image.py (download, verify, provision), fdt.py (DTB editor),
                guest.py (SSH push/run), guest/ (scripts that run inside the Pi), static/ (UI + vendored noVNC)
mac/            ZeroLab.swift (window), build-bundle.sh (deps → qemu → app → dmg), relocate.py
linux/ windows/ installers
samples/        button-led-py, button-led-c
tools/          source-bundle.sh (GPL sources), make-linux-windows-bundle.sh
tests/          python3 -m unittest discover -s tests
```

## Run from a checkout
```bash
ZL_QEMU_DIR=/path/to/qemu/prefix python3 app/server.py --open
```

## Build the releases
```bash
ZL_QEMU_COMMIT=<fork commit> mac/build-bundle.sh all
```

```bash
ZL_QEMU_COMMIT=<fork commit> tools/make-linux-windows-bundle.sh
```

## Security model
- The UI binds `127.0.0.1` only. Every request must carry a `127.0.0.1`/`localhost` Host header. POSTs, the event stream and the VNC socket also need a per-launch token.
- QTest is restricted to the BCM2835 GPIO registers.
- Dropped code is only packed into a tar on the host. It is unpacked, built and run inside the guest over SSH, which is forwarded on loopback only.

## Licence
GPL-2.0-or-later. Third-party components: [THIRD-PARTY.md](THIRD-PARTY.md).
