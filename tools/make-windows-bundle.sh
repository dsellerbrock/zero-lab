#!/bin/bash
# Build Zero-Lab-<version>-windows-x64.zip for Windows 10/11 x64: unzip, double-click "Zero Lab.cmd". No WSL.
# The Pi's CPU is emulated (TCG) and its screen drawn in software, as under WSL; only the install gets simpler.
#
#   tools/make-windows-bundle.sh qemu   the QEMU fork at $ZL_QEMU_COMMIT + windows/qemu-mingw.patch, and its DLLs
#   tools/make-windows-bundle.sh zip    + Python, app, samples, kernel, sources -> build/Zero-Lab-<v>-windows-x64.zip
#   tools/make-windows-bundle.sh all
#
# Runs on Fedora (a container or a WSL distro), which packages the mingw-w64 toolchain and libraries:
#   dnf install mingw64-gcc mingw64-glib2 mingw64-pixman mingw64-pkg-config git python3 meson ninja-build \
#     bison flex make diffutils findutils tar xz bzip2 perl curl 'dnf-command(download)'
# Env: ZL_QEMU_REPO, ZL_QEMU_COMMIT (tools/qemu-pin.sh), ZL_JOBS (default 4).
# Needs kernel/kernel8-virtio.img (kernel/build.sh).
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
B="$ROOT/build/windows"
JOBS=${ZL_JOBS:-4}
. "$ROOT/tools/qemu-pin.sh"  # ZL_QEMU_COMMIT
QEMU_REPO=${ZL_QEMU_REPO:-https://github.com/dsellerbrock/qemu-raspi-zero2w.git}
SYSROOT=/usr/x86_64-w64-mingw32/sys-root/mingw/bin
PY_URL=https://github.com/astral-sh/python-build-standalone/releases/download/20251014/cpython-3.12.12+20251014-x86_64-pc-windows-msvc-install_only_stripped.tar.gz
PY_SHA=3c8b9b10a933909c98b9916297e2093b24a9c2abaa23df1c2622c2bfe052cb94
V=$(python3 -c 'import plistlib,sys; print(plistlib.load(open(sys.argv[1],"rb"))["CFBundleShortVersionString"])' "$ROOT/mac/Info.plist")
NAME="Zero-Lab-$V-windows-x64"
mkdir -p "$B"

qemu() {
  # A shallow clone at the pinned commit, never a working tree another session is editing.
  [ -d "$B/qemu-src/.git" ] || git init -q "$B/qemu-src"
  git -C "$B/qemu-src" fetch -q --depth 1 "$QEMU_REPO" "$ZL_QEMU_COMMIT"
  git -C "$B/qemu-src" checkout -q -f "$ZL_QEMU_COMMIT"
  git -C "$B/qemu-src" clean -qfdx
  git -C "$B/qemu-src" apply "$ROOT/windows/qemu-mingw.patch"
  rm -rf "$B/qemu-build" && mkdir -p "$B/qemu-build"
  # libslirp and libfdt come from QEMU's meson subprojects (Fedora has no mingw libslirp).
  (cd "$B/qemu-build" && "$B/qemu-src/configure" --cross-prefix=x86_64-w64-mingw32- \
      --target-list=aarch64-softmmu --enable-slirp --enable-vnc --enable-tools --disable-werror \
      --disable-docs --disable-gtk --disable-sdl --disable-opengl --disable-virglrenderer --disable-capstone \
      --disable-guest-agent --disable-gnutls --disable-nettle --disable-gcrypt --disable-curl --disable-libssh \
      --disable-vnc-jpeg --disable-png --disable-vnc-sasl --disable-zstd --disable-bzip2 --disable-lzo \
      --disable-snappy --disable-spice --disable-libusb --disable-usb-redir --disable-dbus-display --disable-rust \
      --disable-curses --disable-dsound --disable-sdl-image --disable-qga-vss --disable-hvf --disable-whpx \
      > configure.log) || { tail -n 30 "$B/qemu-build/configure.log"; exit 1; }
  # Only the two programs: the default target also builds qtests, some of which are POSIX-only.
  ninja -C "$B/qemu-build" -j"$JOBS" qemu-system-aarch64.exe qemu-img.exe > "$B/qemu-build/ninja.log" \
    || { tail -n 30 "$B/qemu-build/ninja.log"; exit 1; }
  # QEMU on Windows looks for its data in share/ next to the exe; VNC needs the en-us keymap.
  local Q="$B/qemu" d
  rm -rf "$Q" && mkdir -p "$Q/share/keymaps"
  cp "$B/qemu-build/qemu-system-aarch64.exe" "$B/qemu-build/qemu-img.exe" \
     "$B/qemu-build/subprojects/slirp/libslirp-0.dll" "$Q/"
  find "$B/qemu-src/pc-bios/keymaps" -type f ! -name meson.build -exec cp {} "$Q/share/keymaps/" \;
  # The DLLs they load, recursively, from the mingw sysroot (Windows' own DLLs are left out).
  local todo="$Q/qemu-system-aarch64.exe $Q/qemu-img.exe $Q/libslirp-0.dll"
  : > "$B/dll-sources.txt"
  while [ -n "$todo" ]; do
    set -- $todo; local f=$1; shift; todo="$*"
    for d in $(x86_64-w64-mingw32-objdump -p "$f" | sed -n 's/.*DLL Name: //p'); do
      if [ -f "$SYSROOT/$d" ] && [ ! -f "$Q/$d" ]; then
        cp "$SYSROOT/$d" "$Q/"
        todo="$todo $Q/$d"
        echo "$d $(rpm -qf --qf '%{SOURCERPM}' "$SYSROOT/$d")" >> "$B/dll-sources.txt"
      fi
    done
  done
  x86_64-w64-mingw32-strip "$Q"/*.exe "$Q"/*.dll
  echo "qemu ok: $(ls "$Q"/*.dll | wc -l) DLLs, $(du -sh "$Q" | cut -f1)"
}

zip_() {
  local S="$B/$NAME" Z="$B/$NAME/zero-lab" P
  [ -f "$B/qemu/qemu-system-aarch64.exe" ] || { echo "run '$0 qemu' first" >&2; exit 1; }
  [ -f "$ROOT/kernel/kernel8-virtio.img" ] || { echo "kernel/kernel8-virtio.img is missing (kernel/build.sh)" >&2; exit 1; }
  rm -rf "$S" && mkdir -p "$Z"
  cp "$ROOT/windows/Zero Lab.cmd" "$S/"
  cp "$ROOT/docs/FRIENDS.md" "$S/Read me first.md"
  cp -R "$ROOT/app" "$ROOT/samples" "$Z/"
  mkdir -p "$Z/kernel" && cp "$ROOT/kernel/kernel8-virtio.img" "$Z/kernel/"
  cp -R "$B/qemu" "$Z/qemu"
  find "$Z" -name __pycache__ -prune -exec rm -rf {} +
  # Python (relocatable CPython for Windows; PSF licence)
  [ -f "$B/python.tar.gz" ] || curl -fL --retry 3 -o "$B/python.tar.gz" "$PY_URL"
  echo "$PY_SHA  $B/python.tar.gz" | sha256sum -c - >/dev/null
  tar -xzf "$B/python.tar.gz" -C "$Z"
  P="$Z/python"
  rm -rf "$P/Lib/test" "$P/Lib/idlelib" "$P/Lib/tkinter" "$P/Lib/turtledemo" "$P/Lib/ensurepip" "$P/tcl" \
         "$P/include" "$P/libs" "$P"/DLLs/_tkinter.pyd "$P"/DLLs/tcl*.dll "$P"/DLLs/tk*.dll
  # Complete corresponding source: the QEMU fork (+ patch, inside the Zero Lab tarball), the meson subprojects
  # linked into it, and the Fedora source packages of the LGPL DLLs (GLib, gettext's libintl).
  ZL_QEMU_REPO="$B/qemu-src" "$ROOT/tools/source-bundle.sh" "$S/Source code (GPL)" windows >/dev/null
  tar -C "$B/qemu-src" -cJf "$S/Source code (GPL)/qemu-subprojects-slirp-dtc.tar.xz" subprojects/slirp subprojects/dtc
  (cd "$S/Source code (GPL)" && dnf -q download --source mingw-glib2 mingw-gettext)
  cp "$B/dll-sources.txt" "$S/Source code (GPL)/windows-dlls.txt"
  cat >> "$S/Source code (GPL)/README.txt" <<TXT

Windows zip: QEMU is the same fork with zero-lab/windows/qemu-mingw.patch applied, cross-built with
Fedora's mingw-w64 by zero-lab/tools/make-windows-bundle.sh; libslirp and libfdt are QEMU's meson
subprojects (qemu-subprojects-slirp-dtc.tar.xz). windows-dlls.txt lists each bundled DLL and the Fedora
source package it comes from; the LGPL ones (GLib, libintl) are included here as .src.rpm files.
TXT
  (cd "$B" && rm -f "$NAME.zip" && python3 -c 'import shutil,sys; shutil.make_archive(*sys.argv[1:])' "$NAME" zip . "$NAME")
  echo "zip ok: $(du -h "$B/$NAME.zip" | cut -f1) $B/$NAME.zip"
}

case "${1:-all}" in
  qemu) qemu ;;
  zip) zip_ ;;
  all) qemu; zip_ ;;
  *) echo "usage: $0 qemu|zip|all" >&2; exit 2 ;;
esac
