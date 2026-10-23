# Zero Lab: a Raspberry Pi Zero 2 W on your computer

Zero Lab runs a virtual Raspberry Pi Zero 2 W. You can boot it, use its desktop, wire up virtual buttons, knobs and LEDs to its GPIO pins, and drop in your own code to build and run on the Pi.

## Install (once)

### Mac with Apple Silicon (M1 or newer), macOS 26 or newer
1. Open `Zero-Lab-…-macOS-arm64.dmg` and drag **Zero Lab** onto **Applications**.
2. Double-click **Zero Lab**. The first time, macOS says it can't check the app. Open **System Settings → Privacy & Security**, scroll down, and click **Open Anyway** next to Zero Lab. The app is free software that isn't notarized by Apple.

   If you prefer the Terminal, run `xattr -dr com.apple.quarantine "/Applications/Zero Lab.app"` instead.

This is the fast version: the Pi's CPU runs on your Mac's own cores (Apple Hypervisor), and its graphics use your Mac's GPU (Vulkan through Metal).

### Windows 10/11 (64-bit)
1. Right-click `Zero-Lab-…-windows-x64.zip` and choose **Extract All…**. Zero Lab can't run from inside the zip.
2. In the extracted folder, double-click **Zero Lab** (`Zero Lab.cmd`). If Windows says it protected your PC, click **More info → Run anyway**: Zero Lab is free software without a paid code-signing certificate.
3. It opens in your web browser. Closing the small black window stops the Pi.

Nothing is installed: Zero Lab keeps its disk images and settings in `%LOCALAPPDATA%\Zero Lab`. To remove it, delete the folder you extracted and that one.

If it won't start on your PC, the older installer still works: unzip `Zero-Lab-…-linux-windows.zip` and double-click **Install Zero Lab (Windows).cmd**. It sets up WSL2 and Ubuntu (Windows asks for permission and may need a restart; afterwards, double-click it again), then builds Zero Lab in 10–40 minutes.

### Linux (Debian/Ubuntu, Fedora, Arch)
1. Unzip `Zero-Lab-…-linux-windows.zip`.
2. Double-click **Install Zero Lab (Linux).desktop**. GNOME may ask you to "Allow Launching" first. If double-clicking only opens a text editor, open a terminal in the folder and run `bash setup.sh`. It asks for your password to install build tools, then builds Zero Lab (10–40 minutes).
3. Then start **Zero Lab** from your app menu or desktop.

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
Zero Lab is free software under the GNU GPL v2 or later. It includes QEMU (GPL-2.0), a Linux kernel for the Pi (GPL-2.0; its source is the `kernel-source` download next to the app) and other components listed in `THIRD-PARTY.md`. The complete source code is in the **Source code (GPL)** folder (on the Mac disk image) or the `sources` / **Source code (GPL)** folder (in the zips), and online at https://github.com/dsellerbrock/zero-lab and https://github.com/dsellerbrock/qemu-raspi-zero2w. Raspberry Pi OS is downloaded from raspberrypi.com under its own licences and is not included. Raspberry Pi is a trademark of Raspberry Pi Ltd. Zero Lab is not affiliated with them.
