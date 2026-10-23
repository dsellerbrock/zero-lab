#!/bin/bash
# Build Zero Lab from source on Linux (the release download is the AppImage; see docs/BUILDING.md).
# Builds the bundled QEMU fork + virglrenderer from source, installs the app, adds a menu icon.
#   bash setup.sh            install or update
#   bash setup.sh --check    only report what this machine supports
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
SRC="$HERE/sources"
DEST=${ZL_PREFIX:-$HOME/.local/share/zero-lab}
WORK=${ZL_WORK:-$HOME/.cache/zero-lab-build}
JOBS=${ZL_JOBS:-$(nproc)}
IS_WSL=0; grep -qi microsoft /proc/version 2>/dev/null && IS_WSL=1
# Build steps log to a file; on failure show its tail so friends can send it to you.
logged() { "$@" >> "$WORK/build.log" 2>&1 || { tail -n 40 "$WORK/build.log"; die "build step failed: $* (full log: $WORK/build.log)"; }; }
say() { printf '\033[1;35m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31mError:\033[0m %s\n' "$*" >&2; exit 1; }

check() {
  say "Machine: $(uname -m), $(. /etc/os-release && echo "$PRETTY_NAME")$( [ $IS_WSL = 1 ] && echo ' (WSL)')"
  case "$(uname -m)" in
    aarch64|arm64) say "CPU: ARM. The Pi runs under TCG for now (KVM for this board is not supported yet)." ;;
    *) say "CPU: $(uname -m). An x86 CPU cannot run Pi (ARM) code natively, so the CPU is emulated (TCG)." ;;
  esac
  if [ -e /dev/dri/renderD128 ]; then
    say "GPU: render node found; Venus/virgl GPU modes will be offered (Software is the safe default)."
  else
    say "GPU: no render node; the Pi's screen is drawn in software."
  fi
}

install_packages() {
  local sudo=""; [ "$(id -u)" = 0 ] || { sudo=sudo; sudo -v || die "Zero Lab needs your password to install build tools"; }
  mkdir -p "$WORK"
  if command -v apt-get >/dev/null; then
    say "Installing build tools with apt (you may be asked for your password)"
    logged $sudo apt-get update
    # noninteractive: a package asking a question (tzdata, keyboard) would otherwise stall a hidden prompt
    logged $sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y build-essential ninja-build meson \
      pkg-config python3 python3-venv python3-tomli libglib2.0-dev libpixman-1-dev libslirp-dev libepoxy-dev libdrm-dev \
      libgbm-dev libvulkan-dev libfdt-dev flex bison mtools xz-utils openssh-client curl
  elif command -v dnf >/dev/null; then
    say "Installing build tools with dnf (you may be asked for your password)"
    logged $sudo dnf install -y gcc gcc-c++ make ninja-build meson pkgconf-pkg-config python3 glib2-devel \
      pixman-devel libslirp-devel libepoxy-devel libdrm-devel mesa-libgbm-devel vulkan-loader-devel \
      libfdt-devel flex bison mtools xz openssh-clients curl
  elif command -v pacman >/dev/null; then
    say "Installing build tools with pacman (you may be asked for your password)"
    logged $sudo pacman -S --needed --noconfirm base-devel ninja meson pkgconf python glib2 pixman libslirp \
      libepoxy libdrm mesa vulkan-icd-loader vulkan-headers dtc flex bison mtools xz openssh curl
  else
    die "unsupported distribution: install QEMU build dependencies, mtools and ssh, then rerun"
  fi
}

build() {
  local q v
  q=$(ls "$SRC"/qemu-zero-lab-*.tar.xz 2>/dev/null | head -n1); v=$(ls "$SRC"/virglrenderer-*.tar.xz 2>/dev/null | head -n1)
  [ -n "$q" ] && [ -n "$v" ] || die "sources/ is missing the QEMU or virglrenderer tarball"
  local stamp; stamp="$(basename "$q")+$(basename "$v")"
  if [ -x "$DEST/qemu/bin/qemu-system-aarch64" ] && [ "$(cat "$DEST/qemu/.built-from" 2>/dev/null)" = "$stamp" ]; then
    say "QEMU already built from these sources"; return
  fi
  rm -rf "$WORK"; mkdir -p "$WORK/qemu" "$WORK/virgl"
  say "Unpacking sources"
  tar -xJf "$q" -C "$WORK/qemu" --strip-components 1
  tar -xJf "$v" -C "$WORK/virgl" --strip-components 1
  say "Building virglrenderer with Venus ($JOBS jobs)"
  # The pinned virglrenderer has one GCC-only pedantic error (declaration after a case label).
  logged meson setup "$WORK/virgl-build" "$WORK/virgl" --prefix="$DEST/qemu" --libdir=lib \
    -Dvenus=true -Dtests=false -Dtracing=none -Dc_args=-Wno-error=pedantic
  logged ninja -C "$WORK/virgl-build" -j"$JOBS" install
  say "Building QEMU (this takes a while: 10-40 minutes)"
  mkdir -p "$WORK/qemu-build"
  (cd "$WORK/qemu-build" && PKG_CONFIG_PATH="$DEST/qemu/lib/pkgconfig" logged "$WORK/qemu/configure" \
     --prefix="$DEST/qemu" --extra-ldflags="-Wl,-rpath,$DEST/qemu/lib" --target-list=aarch64-softmmu --enable-slirp --enable-vnc --enable-tools \
     --enable-opengl --enable-virglrenderer --disable-docs --disable-gtk --disable-sdl \
     --disable-guest-agent --disable-capstone)
  logged ninja -C "$WORK/qemu-build" -j"$JOBS" install
  echo "$stamp" > "$DEST/qemu/.built-from"
  rm -rf "$WORK"
  say "QEMU: $(LD_LIBRARY_PATH="$DEST/qemu/lib" "$DEST/qemu/bin/qemu-system-aarch64" --version | head -n1)"
}

install_app() {
  say "Installing Zero Lab into $DEST"
  rm -rf "$DEST/app"; cp -R "$HERE/zero-lab/app" "$DEST/app"
  cp "$HERE/zero-lab/icon.png" "$DEST/icon.png"
  rm -rf "$DEST/samples"; cp -R "$HERE/zero-lab/samples" "$DEST/samples"
  rm -rf "$DEST/kernel"; cp -R "$HERE/zero-lab/kernel" "$DEST/kernel"
  mkdir -p "$HOME/.local/bin"
  cat > "$HOME/.local/bin/zero-lab" <<EOF
#!/bin/sh
# Start Zero Lab (Ctrl-C or closing this window stops the Pi cleanly).
export ZL_QEMU_DIR="$DEST/qemu"
exec python3 "$DEST/app/server.py" "\$@"
EOF
  chmod +x "$HOME/.local/bin/zero-lab"
  if [ $IS_WSL = 0 ]; then
    local apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
    mkdir -p "$apps"
    cat > "$apps/zero-lab.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Zero Lab
Comment=Raspberry Pi Zero 2 W playground
Exec=$HOME/.local/bin/zero-lab --open
Icon=$DEST/icon.png
Terminal=true
Categories=Development;Electronics;
EOF
    chmod +x "$apps/zero-lab.desktop"
    local desk; desk=$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")
    if [ -d "$desk" ]; then
      cp "$apps/zero-lab.desktop" "$desk/"
      chmod +x "$desk/zero-lab.desktop"
      gio set "$desk/zero-lab.desktop" metadata::trusted true 2>/dev/null || true
    fi
    say "Done! Double-click \"Zero Lab\" in your app menu or on your desktop."
  else
    say "Done! Use the Zero Lab shortcut on your Windows desktop."
  fi
}

[ "${1:-}" = "--check" ] && { check; exit 0; }
check
install_packages
build
install_app
