#!/bin/bash
# Build Zero-Lab-<version>-linux-x86_64.AppImage: one file anyone marks executable and double-clicks
# (no compile, no root). linux/setup.sh stays as the build-from-source fallback.
#
#   tools/make-appimage.sh      on a Linux x86_64 host with podman or docker; the build runs in ubuntu:22.04
#                               (glibc 2.35), so the AppImage runs on that and anything newer.
#
# Needs only this checkout and kernel/kernel8-virtio.img (kernel/build.sh, or CI's `kernel` artifact). Every other
# input comes from a pinned URL: QEMU and virglrenderer at the tools/pins.sh commits, packed by tools/source-bundle.sh
# and built from exactly those tarballs (so the shipped source is the source of the binaries); the rest below (sha256).
# Output in build/appimage/: Zero-Lab-<V>-linux-x86_64.AppImage and Zero-Lab-<V>-linux-x86_64-source.tar
# (that bundle plus the Ubuntu sources of every bundled library).
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
B="$ROOT/build/appimage"
SRC="$B/gpl-sources"
JOBS=${ZL_JOBS:-4}
IMAGE=docker.io/library/ubuntu:22.04@sha256:0a9887931b0e38af2e3487ed39e29436b0535c4f3f52e57745baaf79d1898956
PY_URL=https://github.com/astral-sh/python-build-standalone/releases/download/20251014/cpython-3.12.12+20251014-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz
PY_SHA=c74addcd1b033a6e4d60ead3ab47fcc995569027e01d3061c4a934f363c4a0cf
TOOL_URL=https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage
TOOL_SHA=ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0
RUNTIME_URL=https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-x86_64
RUNTIME_SHA=2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d
# Libraries every Linux desktop has and that must match its GPU driver or glibc: never bundled.
HOST_LIBS='^(ld-linux-x86-64|libc|libm|libdl|libpthread|librt|libresolv|libutil|libanl|libmvec|libGL|libEGL|libGLX|libGLdispatch|libOpenGL|libglapi|libvulkan|libgbm|libdrm|libstdc\+\+|libgcc_s|libz|libexpat)\.so|^(libnss_|libwayland-|libX|libxcb)'

fetch() { # url sha256 dest
  [ -f "$3" ] || curl -fL --retry 3 -o "$3" "$1"
  echo "$2  $3" | sha256sum -c - >/dev/null
}

outside() {
  [ "$(uname -sm)" = "Linux x86_64" ] || { echo "run this on Linux x86_64 (the Mac build is mac/build-bundle.sh)" >&2; exit 2; }
  local engine; engine=$(command -v podman || command -v docker) || { echo "needs podman or docker" >&2; exit 2; }
  [ -f "$ROOT/kernel/kernel8-virtio.img" ] || { echo "kernel/kernel8-virtio.img missing (kernel/build.sh)" >&2; exit 2; }
  mkdir -p "$B"
  "$engine" run --rm -v "$ROOT:/zl" -e ZL_JOBS="$JOBS" "$IMAGE" bash /zl/tools/make-appimage.sh inside
  ls -la "$B"/Zero-Lab-*-linux-x86_64*
}

inside() {
  export DEBIAN_FRONTEND=noninteractive
  ROOT=/zl B=/zl/build/appimage SRC=/zl/build/appimage/gpl-sources
  local W=/work P=/opt/zl A=/work/AppDir V
  sed -i 's/^# deb-src/deb-src/' /etc/apt/sources.list
  apt-get update -qq
  apt-get install -y -qq --no-install-recommends build-essential ninja-build meson pkg-config python3 python3-venv python3-tomli \
    python3-yaml git libglib2.0-dev libpixman-1-dev libslirp-dev libepoxy-dev libdrm-dev libgbm-dev libvulkan-dev \
    libfdt-dev flex bison mtools patchelf curl ca-certificates xz-utils librsvg2-bin dpkg-dev file >/dev/null
  git config --global --add safe.directory '*'  # the checkout is owned by the host user
  rm -rf "$SRC" && "$ROOT/tools/source-bundle.sh" "$SRC" >/dev/null
  V=$(python3 -c 'import plistlib,sys; print(plistlib.load(open(sys.argv[1],"rb"))["CFBundleShortVersionString"])' "$ROOT/mac/Info.plist")

  # virglrenderer (Venus; libvulkan is dlopen'd, so soft mode runs without it) and QEMU, as linux/setup.sh builds them
  mkdir -p "$W/virgl" "$W/qemu" "$W/qemu-build"
  tar -xJf "$SRC"/virglrenderer-*.tar.xz -C "$W/virgl" --strip-components 1
  tar -xJf "$SRC"/qemu-zero-lab-*.tar.xz -C "$W/qemu" --strip-components 1
  meson setup "$W/virgl-build" "$W/virgl" --prefix="$P" --libdir=lib -Dplatforms=egl -Dvenus=true \
    -Dvulkan-dload=true -Dtests=false -Dtracing=none -Dc_args=-Wno-error=pedantic
  ninja -C "$W/virgl-build" -j"$JOBS" install
  (cd "$W/qemu-build" && PKG_CONFIG_PATH="$P/lib/pkgconfig" "$W/qemu/configure" --prefix="$P" \
     --target-list=aarch64-softmmu --enable-slirp --enable-vnc --enable-tools --enable-opengl --enable-virglrenderer \
     --disable-docs --disable-gtk --disable-sdl --disable-guest-agent --disable-capstone)
  ninja -C "$W/qemu-build" -j"$JOBS" install

  # AppDir: app/, qemu/, kernel/, samples/ side by side, as in the Mac bundle (vm.py finds APP.parent/qemu)
  local Q="$A/qemu"
  mkdir -p "$Q/bin" "$Q/lib" "$Q/libexec" "$Q/share/qemu" "$A/bin" "$A/kernel"
  cp "$P/bin/qemu-system-aarch64" "$P/bin/qemu-img" "$Q/bin/"
  cp "$P/libexec/virgl_render_server" "$Q/libexec/"
  cp -R "$P/share/qemu/keymaps" "$Q/share/qemu/"
  cp /usr/bin/mtools "$A/bin/" && ln -s mtools "$A/bin/mcopy"  # image.py edits the boot partition with mcopy
  local exe=("$Q"/bin/* "$Q/libexec/virgl_render_server" "$A/bin/mtools")
  LD_LIBRARY_PATH="$P/lib" ldd "${exe[@]}" | awk '$2 == "=>" && $3 ~ /^\// {print $3}' | sort -u | while read -r so; do
    basename "$so" | grep -Eq "$HOST_LIBS" || cp -L "$so" "$Q/lib/"
  done
  patchelf --set-rpath '$ORIGIN/../lib' "$Q"/bin/* "$Q/libexec/virgl_render_server"
  patchelf --set-rpath '$ORIGIN/../qemu/lib' "$A/bin/mtools"
  for so in "$Q"/lib/*; do patchelf --set-rpath '$ORIGIN' "$so"; done
  cp -R "$ROOT/app" "$ROOT/samples" "$A/" && find "$A" -name __pycache__ -prune -exec rm -rf {} +
  cp "$ROOT/kernel/kernel8-virtio.img" "$A/kernel/"
  fetch "$PY_URL" "$PY_SHA" "$B/python.tar.gz"
  tar -xzf "$B/python.tar.gz" -C "$A"
  rm -rf "$A/python/lib/python3.12/"{test,idlelib,tkinter,ensurepip} "$A/python/lib/"{tcl,tk,itcl,thread}* \
         "$A/python/include" "$A/python/share"
  cp "$ROOT/linux/AppRun" "$A/AppRun" && chmod +x "$A/AppRun"
  rsvg-convert -w 256 -h 256 "$ROOT/app/static/icon.svg" -o "$A/zero-lab.png" && ln -s zero-lab.png "$A/.DirIcon"
  cat > "$A/zero-lab.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Zero Lab
Comment=Raspberry Pi Zero 2 W playground
Exec=zero-lab
Icon=zero-lab
Terminal=true
Categories=Development;Electronics;
EOF
  echo "bundled libraries:"; ls "$Q/lib"
  if ldd "${exe[@]}" | grep -q "not found"; then ldd "${exe[@]}" | grep "not found"; echo "unresolved libraries" >&2; exit 1; fi

  # the AppImage (no FUSE in a container: run appimagetool extracted; pinned runtime, not the latest)
  fetch "$TOOL_URL" "$TOOL_SHA" "$B/appimagetool"
  fetch "$RUNTIME_URL" "$RUNTIME_SHA" "$B/runtime-x86_64"
  chmod +x "$B/appimagetool"
  local out="$B/Zero-Lab-$V-linux-x86_64.AppImage"
  APPIMAGE_EXTRACT_AND_RUN=1 ARCH=x86_64 "$B/appimagetool" --no-appstream --runtime-file "$B/runtime-x86_64" "$A" "$out"

  # complete corresponding source: Zero Lab's bundle plus the Ubuntu source package of every bundled library
  local S="$W/Zero-Lab-$V-linux-x86_64-source" pkgs
  mkdir -p "$S/ubuntu" && cp -R "$SRC/." "$S/"
  pkgs=$(for so in "$Q"/lib/* /usr/bin/mtools; do dpkg -S "*/$(basename "$so")" 2>/dev/null | head -n1 | cut -d: -f1; done \
         | sort -u | xargs dpkg-query -W -f '${source:Package}=${source:Version}\n' | sort -u)
  (cd "$S/ubuntu" && apt-get source -qq --download-only $pkgs)
  printf 'Ubuntu 22.04 source packages of the libraries and tools bundled in the AppImage (qemu/lib, bin/mtools):\n%s\n' \
    "$pkgs" > "$S/ubuntu/README.txt"
  tar -cf "$B/Zero-Lab-$V-linux-x86_64-source.tar" -C "$W" "$(basename "$S")"
  echo "appimage ok: $(du -h "$out" | cut -f1) $out"
}

case "${1:-}" in
  inside) inside ;;
  "") outside ;;
  *) echo "usage: $0" >&2; exit 2 ;;
esac
