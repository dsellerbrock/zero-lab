#!/bin/bash
# Assemble Zero-Lab-<version>-linux-windows.zip: installers, app, samples, icons, full sources.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
V=$(python3 -c 'import plistlib,sys; print(plistlib.load(open(sys.argv[1],"rb"))["CFBundleShortVersionString"])' "$ROOT/mac/Info.plist")
NAME="Zero-Lab-$V-linux-windows"
S="$ROOT/build/$NAME"
rm -rf "$S" && mkdir -p "$S/zero-lab"
cp "$ROOT/linux/setup.sh" "$ROOT/windows/setup.ps1" "$ROOT/windows/Install Zero Lab (Windows).cmd" \
   "$ROOT/linux/Install Zero Lab (Linux).desktop" "$S/"
cp "$ROOT/docs/FRIENDS.md" "$S/Read me first.md"
rsync -a --exclude __pycache__ --exclude src "$ROOT/app" "$ROOT/samples" "$ROOT/kernel" "$S/zero-lab/"
rsvg-convert -w 256 -h 256 "$ROOT/app/static/icon.svg" -o "$S/zero-lab/icon.png"
"$(command -v magick || command -v convert)" -background none "$ROOT/app/static/icon.svg" -define icon:auto-resize=256,64,48,32,16 "$S/zero-lab/icon.ico"
"$ROOT/tools/source-bundle.sh" "$S/sources" >/dev/null
chmod +x "$S/setup.sh" "$S/Install Zero Lab (Linux).desktop"
(cd "$ROOT/build" && rm -f "$NAME.zip" && zip -qry "$NAME.zip" "$NAME")
# the Pi kernel's GPL source: a separate release asset (157 MB)
"$ROOT/kernel/build.sh" source
tar -cf "$ROOT/build/Zero-Lab-$V-kernel-source.tar" -C "$ROOT" kernel/src kernel/build.sh kernel/config
echo "bundle ok: $(du -h "$ROOT/build/$NAME.zip" | cut -f1) $ROOT/build/$NAME.zip"
