# Zero Lab: a Raspberry Pi Zero 2 W on your computer

Zero Lab runs a virtual Raspberry Pi Zero 2 W. You can boot it, use its desktop, wire up virtual buttons, knobs and LEDs to its GPIO pins, and drop in your own code to build and run on the Pi.

## Install (once)

### Mac with Apple Silicon (M1 or newer), macOS 26 or newer
1. Open `Zero-Lab-…-macOS-arm64.dmg` and drag **Zero Lab** onto **Applications**.
2. Double-click **Zero Lab**. The first time, macOS says it can't check the app. Open **System Settings → Privacy & Security**, scroll down, and click **Open Anyway** next to Zero Lab. The app is free software that isn't notarized by Apple.

   If you prefer the Terminal, run `xattr -dr com.apple.quarantine "/Applications/Zero Lab.app"` instead.

This is the fast version: the Pi's CPU runs on your Mac's own cores (Apple Hypervisor), and its graphics use your Mac's GPU (Vulkan through Metal).

### Windows 10/11 (64-bit)
1. Double-click `Zero-Lab-…-windows-x64-setup.exe`. Windows SmartScreen may say "Windows protected your PC": click **More info**, then **Run anyway**. Zero Lab is free software without a paid code-signing certificate.
2. Click through the wizard: it shows the licence, installs into `%LOCALAPPDATA%\Programs\Zero Lab` (no administrator password), and adds **Zero Lab** to the Start menu and your desktop.
3. Leave **Launch Zero Lab** ticked and click **Finish**. Zero Lab opens in its own window. Close the window when you're done: Zero Lab shuts the Pi down and quits completely. (The window comes from Microsoft Edge, which is part of Windows; if you removed Edge, install Edge or Google Chrome.)

Your Pi's disk images and layouts live in `%LOCALAPPDATA%\Zero Lab`. To uninstall, use **Settings → Apps → Installed apps → Zero Lab**; it keeps that data unless you tick **Also remove my Pi data**.

### Linux (Intel/AMD PC: Ubuntu 22.04 or newer, Fedora, Arch, Mint, …)
1. Download `Zero-Lab-…-linux-x86_64.AppImage`.
2. Make it executable: right-click it → **Properties** → turn on **Allow executing file as program** (or run `chmod +x Zero-Lab-*.AppImage` in a terminal).
3. Double-click it. A terminal window opens (closing it stops the Pi) and Zero Lab opens in your browser. The first time, it offers to add Zero Lab to your app menu.

Your images and settings live in `~/.local/share/zero-lab`; the AppImage itself never changes. It needs FUSE's `fusermount` (the `fuse3` package, already installed on Ubuntu, Fedora and most desktops). If double-clicking does nothing, run it from a terminal (`./Zero-Lab-*.AppImage`) to see why; if it says FUSE is missing, install `fuse3` or run `./Zero-Lab-*.AppImage --appimage-extract-and-run`.

**Other computers** (ARM, or a distribution older than Ubuntu 22.04): Zero Lab can be built from source with `linux/setup.sh`; see `docs/BUILDING.md` in the source code.

**How fast is it on Windows and Linux?** On a normal Intel/AMD PC, the Pi's ARM CPU has to be emulated instruction by instruction, because no PC can run ARM code natively. Everything works, but booting and apps are several times slower than on an Apple Silicon Mac.

## First run
1. Under **Disk image**, choose an official Raspberry Pi OS image (Zero Lab downloads it from raspberrypi.com and checks it), or pick an image file you already have.
2. Choose a user name and password for the Pi, then click **Download & set up**. The first boot sets up your user. Watch it in the serial console.
3. Click **Boot**. The Pi's desktop appears in the middle of the window.

## GPIO sandbox (right side)
- Add **Buttons**, **Switches**, **Knobs**, **Sliders**, **LEDs**, **7-segment** displays, an **LCD 16×2** and a **Probe**. Click ⚙ on a widget to choose its pins; pin numbers are BCM GPIO numbers 0–27.
- Inputs drive the Pi's pins, and the Pi's outputs light LEDs. The strip at the top shows every pin: blue = input, orange = output.
- A Button is "active low" by default (it rests at 1 and pressing it gives 0), just like a real button wired with a pull-up. This matches `gpiozero.Button(17)`.
- A Knob drives several pins as a binary number (the first pin is the lowest bit), or, set to **Analog (MCP3008 channel N)** in ⚙, a 0–1023 value on the Pi's emulated MCP3008 ADC (SPI0, CE0). A **Slider** does the same. Read it as on a real Pi: `from gpiozero import MCP3008; MCP3008(channel=0).value` (try `samples/adc-knob-py`).
- Turn a Knob by dragging up or down (one drag covers the whole range; hold Shift for fine steps), with the scroll wheel, the arrow keys, or by typing a value in the box under it.
- Zoom the breadboard with **−** / **+** (or ⌘/Ctrl + scroll). **Pop out** moves the GPIO panel into its own window, so the Pi's screen gets the whole main window; **Put back** returns it.
- A 7-segment's ⚙ **Connection** is either GPIO pins (one digit) or **I2C HT16K33** (a 4-digit backpack at 0x70, with dots and a colon). The **LCD 16×2** is an I2C LCD (PCF8574 backpack at 0x27). Both are on the Pi's `/dev/i2c-1`; write to them with smbus2 (try `samples/seg7-i2c-py` and `samples/lcd-i2c-py`).
- SPI0 and I2C1 are always on, as with `dtparam=spi=on` and `dtparam=i2c_arm=on`, so GPIO 7–11 and 2/3 belong to them.
- Save layouts by name, export them to your Downloads folder, or drop a `.json` layout onto the canvas.

## Your own code
Drop a file, folder or `.zip` on **Your code**, then click **Build & run**. Output appears under **Program output**.
- Python (`main.py` or a single `.py`), C/C++ with a `Makefile` or `CMakeLists.txt`, Rust (`Cargo.toml`), Go (`go.mod`), or a ready-made ARM Linux program.
- To choose the commands yourself, add a `pi-run.json`: `{"build": "make", "run": "./blink"}`.
- Code is built and run **inside the virtual Pi only**, never on your computer.
- **Start on boot** runs the project automatically each time the Pi boots.
- Or pick a ready-made example under **Samples** and press **Load**: its code is staged and its parts appear on the breadboard. Then **Build & run**. With `button-led-py`, press the Button widget and the LED widget lights.

## Licences
Zero Lab is free software under the GNU GPL v2 or later. It includes QEMU (GPL-2.0), a Linux kernel for the Pi (GPL-2.0; its source is the `kernel-source` download next to the app) and other components listed in `THIRD-PARTY.md`. The complete source code is in the **Source code (GPL)** folder (on the Mac disk image) the `linux-x86_64-source` download next to the AppImage, or the `…-windows-x64-sources.zip` download next to the Windows installer, and online at https://github.com/dsellerbrock/zero-lab and https://github.com/dsellerbrock/qemu-raspi-zero2w. Raspberry Pi OS is downloaded from raspberrypi.com under its own licences and is not included. Raspberry Pi is a trademark of Raspberry Pi Ltd. Zero Lab is not affiliated with them.
