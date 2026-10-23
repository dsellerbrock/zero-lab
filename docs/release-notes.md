Zero Lab: a Raspberry Pi Zero 2 W on your computer. Boot Raspberry Pi OS, wire virtual buttons, knobs, LEDs, 7-segment displays, an LCD and an ADC to its GPIO pins, and run your own code on the Pi.

**macOS (Apple Silicon, macOS 26+):** open the .dmg and drag Zero Lab to Applications. The first time, open System Settings → Privacy & Security and click "Open Anyway" (the app is free software and not notarized).

**Windows 10/11 (64-bit):** run the setup.exe. It installs for you only, no admin rights or WSL needed. Windows SmartScreen may say it doesn't recognise the app: click "More info" → "Run anyway". Uninstall from Settings → Apps; your Pi's disk images are kept unless you tick "Also remove my Pi data".

**Linux (x86_64):** download the .AppImage, make it executable (`chmod +x`, or Properties → Allow executing) and double-click it. Needs fuse3, preinstalled on most desktops; without FUSE, run it with `--appimage-extract-and-run`. On first run it offers to add a menu entry.

Every download here was built from git by CI, then installed and tested end to end (setup, boot, files, every GPIO sample) before this release was published.

Free software under the GNU GPL v2 or later. Source: https://github.com/dsellerbrock/zero-lab and https://github.com/dsellerbrock/qemu-raspi-zero2w. The source archives below hold the complete corresponding source of each download (the dmg also carries its own in "Source code (GPL)"). Raspberry Pi OS is downloaded from raspberrypi.com and is not included; Zero Lab is not affiliated with Raspberry Pi Ltd.
