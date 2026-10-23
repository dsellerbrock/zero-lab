#!/bin/bash
# Build "Zero Lab.app" and "Zero Lab.dmg" for Apple Silicon, macOS 26+.
#
#   mac/build-bundle.sh deps      pcre2, libepoxy, virglrenderer (Venus) built for macOS 26
#   mac/build-bundle.sh qemu      the QEMU fork at $ZL_QEMU_COMMIT, minimal config
#   mac/build-bundle.sh app       assemble + relocate + sign the .app
#   mac/build-bundle.sh dmg       the .dmg (includes the GPL source tarballs)
#   mac/build-bundle.sh all
#
# Everything is fetched at the versions pinned in tools/pins.sh, so this builds from a clean git clone.
# Needs: macOS 26+ on Apple Silicon, Xcode command-line tools, Homebrew `meson ninja pkg-config glib pixman libslirp
# librsvg`, and kernel/kernel8-virtio.img (kernel/build.sh, or the CI kernel job).
# Overrides (env, optional): ZL_QEMU_REPO (a local clone of the fork), ZL_VIRGL_SRC, ZL_EPOXY_SRC, ZL_MOLTENVK.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
. "$ROOT/tools/pins.sh"
B="$ROOT/build/mac"
DEPS="$B/deps"
SRC="$B/src"
export MACOSX_DEPLOYMENT_TARGET=26.0
JOBS=${ZL_JOBS:-3}
QEMU_REPO=${ZL_QEMU_REPO:-$ZL_QEMU_URL}
VIRGL_SRC=${ZL_VIRGL_SRC:-$SRC/virglrenderer}
EPOXY_SRC=${ZL_EPOXY_SRC:-$SRC/libepoxy}
KHRONOS_INCLUDE="$SRC/khronos/include"  # EGL/GLES/KHR headers (build only)
MOLTENVK=${ZL_MOLTENVK:-$SRC/MoltenVK/libMoltenVK.dylib}
PCRE2_URL=https://github.com/PCRE2Project/pcre2/releases/download/pcre2-10.49/pcre2-10.49.tar.bz2
PCRE2_SHA=53c156e1ba416a20da8e65395daa132da0d80e76910424caca3fcdae7831d384
PY_URL=https://github.com/astral-sh/python-build-standalone/releases/download/20251014/cpython-3.12.12+20251014-aarch64-apple-darwin-install_only_stripped.tar.gz
PY_SHA=84cb7acbf75264982c8bdd818bfa1ff0f1eb76007b48a5f3e01d28633b46afdf
APP="$B/Zero Lab.app"
mkdir -p "$B" "$DEPS"
export PKG_CONFIG_PATH="$DEPS/lib/pkgconfig:$(brew --prefix)/lib/pkgconfig"

fetch() { # url sha256 dest
  [ -f "$3" ] || curl -fL --retry 3 -o "$3" "$1"
  if [ -n "$2" ]; then echo "$2  $3" | shasum -a 256 -c - >/dev/null; fi
}

msetup() { # builddir srcdir args...
  local b=$1 src=$2; shift 2
  if [ -d "$b/meson-private" ]; then meson setup --reconfigure "$b" "$src" "$@"; else meson setup "$b" "$src" "$@"; fi
}

die() { echo "Error: $*" >&2; exit 1; }

sources() {  # the pinned inputs that don't come from Homebrew
  for f in meson ninja pkg-config glib pixman libslirp librsvg; do
    brew list --versions "$f" >/dev/null 2>&1 || die "missing Homebrew package $f: brew install meson ninja pkg-config glib pixman libslirp librsvg"
  done
  mkdir -p "$SRC"
  [ -n "${ZL_VIRGL_SRC:-}" ] || zl_checkout "$ZL_VIRGL_URL" "$ZL_VIRGL_COMMIT" "$VIRGL_SRC"
  [ -n "${ZL_EPOXY_SRC:-}" ] || zl_checkout "$ZL_EPOXY_URL" "$ZL_EPOXY_COMMIT" "$EPOXY_SRC"
  if [ ! -f "$KHRONOS_INCLUDE/KHR/khrplatform.h" ]; then
    rm -rf "$SRC/khronos" && mkdir -p "$SRC/khronos/egl" "$SRC/khronos/gl" "$KHRONOS_INCLUDE"
    curl -fsL --retry 3 "$ZL_EGL_REGISTRY" | tar -xz -C "$SRC/khronos/egl" --strip-components 1
    curl -fsL --retry 3 "$ZL_GL_REGISTRY" | tar -xz -C "$SRC/khronos/gl" --strip-components 1
    cp -R "$SRC/khronos/egl/api/EGL" "$SRC/khronos/egl/api/KHR" "$SRC/khronos/gl/api/GLES2" "$SRC/khronos/gl/api/GLES3" "$KHRONOS_INCLUDE/"
  fi
  if [ -z "${ZL_MOLTENVK:-}" ] && [ ! -f "$MOLTENVK" ]; then
    fetch "$ZL_MOLTENVK_URL" "$ZL_MOLTENVK_SHA" "$SRC/MoltenVK-macos.tar"
    mkdir -p "$SRC/MoltenVK" && tar -xOf "$SRC/MoltenVK-macos.tar" MoltenVK/MoltenVK/dynamic/dylib/macOS/libMoltenVK.dylib > "$MOLTENVK"
  fi
}

deps() {
  sources
  # virglrenderer's generators need PyYAML
  [ -x "$B/venv/bin/python3" ] || { python3 -m venv "$B/venv" && "$B/venv/bin/pip" -q install pyyaml==6.0.3; }
  export PATH="$B/venv/bin:$PATH"
  fetch "$PCRE2_URL" "$PCRE2_SHA" "$B/pcre2.tar.bz2"
  rm -rf "$B/pcre2-src" && mkdir "$B/pcre2-src" && tar -xjf "$B/pcre2.tar.bz2" -C "$B/pcre2-src" --strip-components 1
  (cd "$B/pcre2-src" && ./configure -q --prefix="$DEPS" --disable-static --enable-jit && make -j$JOBS -s install)

  mkdir -p "$DEPS/include" && cp -R "$KHRONOS_INCLUDE"/{EGL,GLES2,GLES3,KHR} "$DEPS/include/"
  msetup "$B/epoxy-build" "$EPOXY_SRC" -Dc_args="-I$DEPS/include" --prefix="$DEPS" --libdir=lib \
    -Dtests=false -Ddocs=false -Dx11=false -Degl=yes -Dglx=no
  ninja -C "$B/epoxy-build" -j$JOBS install

  msetup "$B/virgl-build" "$VIRGL_SRC" --prefix="$DEPS" --libdir=lib \
    -Dplatforms=egl -Dvenus=true -Dvulkan-dload=true -Dtests=false -Dtracing=none -Dc_args="-I$DEPS/include"
  ninja -C "$B/virgl-build" -j$JOBS install
  echo "deps ok: $(ls "$DEPS/lib"/*.dylib | wc -l) dylibs"
}

qemu() {
  if [ -d "$QEMU_REPO/.git" ]; then ZL_QEMU_COMMIT=$(git -C "$QEMU_REPO" rev-parse --verify "$ZL_QEMU_COMMIT^{commit}"); fi
  # A clean checkout at the pinned commit (shallow), never the live working tree another session is editing.
  zl_checkout "$QEMU_REPO" "$ZL_QEMU_COMMIT" "$B/qemu-src"
  git -C "$B/qemu-src" clean -qfdx
  mkdir -p "$B/qemu-build"
  (cd "$B/qemu-build" && "$B/qemu-src/configure" --prefix="$B/qemu-install" \
      --target-list=aarch64-softmmu --enable-hvf --enable-cocoa --enable-vnc --enable-slirp \
      --enable-opengl --enable-virglrenderer --enable-tools \
      --disable-sdl --disable-gtk --disable-gnutls --disable-nettle --disable-gcrypt --disable-curl \
      --disable-libssh --disable-libusb --disable-usb-redir --disable-vnc-jpeg --disable-png \
      --disable-vnc-sasl --disable-zstd --disable-capstone --disable-docs --disable-guest-agent \
      --disable-spice --disable-curses --disable-coreaudio --disable-dbus-display --disable-vmnet \
      --disable-libudev --disable-bzip2 --disable-lzo --disable-snappy --disable-linux-io-uring --disable-pvg \
      | tail -n 40)
  # Call ninja directly: macOS make 3.81 passes -j in a form ninja ignores (it would use every core).
  ninja -C "$B/qemu-build" -j$JOBS install >/dev/null
  echo "qemu ok: $("$B/qemu-install/bin/qemu-system-aarch64" --version | head -1)"
}

app() {
  local R="$APP/Contents/Resources" Q="$APP/Contents/Resources/qemu"
  sources
  [ -f "$ROOT/kernel/kernel8-virtio.img" ] || die "kernel/kernel8-virtio.img is missing: build it with kernel/build.sh (needs Docker) or take it from the CI kernel job"
  rm -rf "$APP"
  mkdir -p "$APP/Contents/MacOS" "$Q/bin" "$Q/lib" "$Q/libexec" "$Q/share"
  cp "$ROOT/mac/Info.plist" "$APP/Contents/"
  # icon
  local IS="$B/icon.iconset"; rm -rf "$IS"; mkdir "$IS"
  for s in 16 32 128 256 512; do
    rsvg-convert -w $s -h $s "$ROOT/app/static/icon.svg" -o "$IS/icon_${s}x${s}.png"
    rsvg-convert -w $((s*2)) -h $((s*2)) "$ROOT/app/static/icon.svg" -o "$IS/icon_${s}x${s}@2x.png"
  done
  iconutil -c icns "$IS" -o "$R/AppIcon.icns"
  # wrapper
  swiftc -O -target arm64-apple-macos26.0 "$ROOT/mac/ZeroLab.swift" -o "$APP/Contents/MacOS/Zero Lab"
  # app code
  rsync -a --exclude __pycache__ "$ROOT/app/" "$R/app/"
  rsync -a --exclude __pycache__ "$ROOT/samples/" "$R/samples/"
  # the Pi kernel (kernel/build.sh)
  mkdir -p "$R/kernel" && cp "$ROOT/kernel/kernel8-virtio.img" "$R/kernel/"
  # python (relocatable CPython build; PSF licence)
  fetch "$PY_URL" "$PY_SHA" "$B/python.tar.gz"
  tar -xzf "$B/python.tar.gz" -C "$R"
  rm -rf "$R/python/lib/python3.12/test" "$R/python/lib/python3.12/idlelib" "$R/python/lib/python3.12/tkinter" \
         "$R/python/lib/python3.12/ensurepip" "$R/python/lib/tcl"* "$R/python/lib/tk"* "$R/python/lib/itcl"* \
         "$R/python/lib/thread"* "$R/python/include" "$R/python/share"
  # qemu + the libraries it loads (linked or dlopen'd)
  cp "$B/qemu-install/bin/qemu-system-aarch64" "$B/qemu-install/bin/qemu-img" "$Q/bin/"
  cp "$DEPS/libexec/virgl_render_server" "$Q/libexec/"
  cp "$MOLTENVK" "$Q/lib/libMoltenVK.dylib"
  lipo "$Q/lib/libMoltenVK.dylib" -thin arm64 -output "$Q/lib/libMoltenVK.dylib" 2>/dev/null || true
  # firmware/keymaps QEMU looks up at runtime (only what raspi3ap + VNC need)
  mkdir -p "$Q/share/qemu" && cp -R "$B/qemu-install/share/qemu/keymaps" "$Q/share/qemu/"
  python3 "$ROOT/mac/relocate.py" "$Q" "$DEPS/lib"
  # sign inside-out: libraries, helpers, then QEMU with the hypervisor entitlement, then the app
  find "$R" -type f \( -name '*.dylib' -o -name '*.so' \) -exec codesign -f -s - {} \; 2>/dev/null
  codesign -f -s - "$Q/libexec/virgl_render_server" "$Q/bin/qemu-img" "$R/python/bin/python3.12"
  codesign -f -s - --entitlements "$ROOT/mac/qemu.entitlements" "$Q/bin/qemu-system-aarch64"
  codesign -f -s - "$APP"
  echo "app ok: $(du -sh "$APP" | cut -f1)"
}

dmg() {
  local S="$B/dmg-stage" V
  V=$(python3 -c 'import plistlib,sys; print(plistlib.load(open(sys.argv[1],"rb"))["CFBundleShortVersionString"])' "$ROOT/mac/Info.plist")
  rm -rf "$S" && mkdir -p "$S/Source code (GPL)"
  cp -R "$APP" "$S/"
  ln -s /Applications "$S/Applications"
  cp "$ROOT/docs/GETTING-STARTED.md" "$S/Read me first.md"
  "$ROOT/tools/source-bundle.sh" "$S/Source code (GPL)"
  rm -f "$B/Zero-Lab-$V-macOS-arm64.dmg"
  hdiutil create -quiet -volname "Zero Lab" -srcfolder "$S" -fs APFS -format ULFO "$B/Zero-Lab-$V-macOS-arm64.dmg"
  echo "dmg ok: $(du -h "$B/Zero-Lab-$V-macOS-arm64.dmg" | cut -f1)"
}

case "${1:-all}" in
  deps|qemu|app|dmg) "$1" ;;
  all) deps; qemu; app; dmg ;;
  *) echo "usage: $0 deps|qemu|app|dmg|all" >&2; exit 2 ;;
esac
