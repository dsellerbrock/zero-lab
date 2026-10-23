#!/bin/bash
# Put the complete corresponding source for everything Zero Lab ships into DIR (GPL/LGPL).
#   tools/source-bundle.sh DIR
# Env: ZL_QEMU_REPO, ZL_QEMU_COMMIT (QEMU fork), ZL_VIRGL_SRC, ZL_EPOXY_SRC (git checkouts).
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PROJECTS=$(dirname "$ROOT")
OUT=$(mkdir -p "$1" && cd "$1" && pwd)
CACHE="$ROOT/build/sources"; mkdir -p "$CACHE"
QEMU_REPO=${ZL_QEMU_REPO:-$PROJECTS/qemu-gpio-a6}
[ -d "$QEMU_REPO/.git" ] || [ -n "${ZL_QEMU_REPO:-}" ] || QEMU_REPO=https://github.com/dsellerbrock/qemu-raspi-zero2w.git
ZL_QEMU_COMMIT=${ZL_QEMU_COMMIT:-d4fa079b1e73a95a414b71e3e9e7fdad8d10ac0b}  # qemu-raspi-zero2w d4fa079b
VIRGL_SRC=${ZL_VIRGL_SRC:-$PROJECTS/a6-virgl-stack/sources/virglrenderer}
EPOXY_SRC=${ZL_EPOXY_SRC:-$PROJECTS/a6-virgl-stack/sources/libepoxy}

short=${ZL_QEMU_COMMIT:0:12}
q="$CACHE/qemu-zero-lab-$short.tar.xz"
if [ ! -f "$q" ]; then
  # QEMU's own script: the tree at the commit plus the meson subprojects it builds with.
  tmp=$(mktemp -d); git clone -q --no-checkout "$QEMU_REPO" "$tmp/qemu"
  git -C "$tmp/qemu" checkout -q "$ZL_QEMU_COMMIT"
  full=$(git -C "$tmp/qemu" rev-parse HEAD)
  touch "$tmp/qemu.tar"  # the script realpath()s its output first; BSD realpath needs it to exist
  (cd "$tmp/qemu" && scripts/archive-source.sh "$tmp/qemu.tar")
  # archive-source.sh writes paths without a top-level directory; add one, as release tarballs have
  mkdir "$tmp/qemu-zero-lab-$short" && tar -xf "$tmp/qemu.tar" -C "$tmp/qemu-zero-lab-$short"
  tar -C "$tmp" -cf - "qemu-zero-lab-$short" | xz -T3 -9 > "$q"; rm -rf "$tmp"
fi
cp "$q" "$OUT/"
for pair in "virglrenderer:$VIRGL_SRC" "libepoxy:$EPOXY_SRC"; do
  name=${pair%%:*} src=${pair#*:} rev=$(git -C "$src" rev-parse --short=12 HEAD)
  git -C "$src" archive --prefix="$name-$rev/" HEAD | xz -T3 -9 > "$OUT/$name-$rev.tar.xz"
done
git -C "$ROOT" archive --prefix=zero-lab/ HEAD | xz -9 > "$OUT/zero-lab-$(git -C "$ROOT" rev-parse --short=12 HEAD).tar.xz"
# LGPL libraries linked into the macOS QEMU (exact upstream releases Homebrew built from)
while read -r url sha; do
  f="$CACHE/$(basename "$url")"
  [ -f "$f" ] || curl -fsL --retry 3 -o "$f" "$url"
  echo "$sha  $f" | shasum -a 256 -c - >/dev/null
  cp "$f" "$OUT/"
done <<'LIST'
https://download.gnome.org/sources/glib/2.90/glib-2.90.1.tar.xz 93c941aa17d5eb1d53fe838365f29a8b4e539c222a256d974ec8f30fc413e396
https://ftpmirror.gnu.org/gettext/gettext-1.0.tar.gz 85d99b79c981a404874c02e0342176cf75c7698e2b51fe41031cf6526d974f1a
LIST
cp "$ROOT/LICENSE" "$ROOT/THIRD-PARTY.md" "$OUT/"
cat > "$OUT/README.txt" <<TXT
Complete corresponding source for Zero Lab binaries.
QEMU (GPL-2.0): qemu-zero-lab-$short.tar.xz is the fork at commit $ZL_QEMU_COMMIT
(https://github.com/dsellerbrock/qemu-raspi-zero2w),
made with QEMU's scripts/archive-source.sh. Build: see zero-lab/mac/build-bundle.sh (macOS) or linux/setup.sh.
Linux kernel (GPL-2.0): kernel/kernel8-virtio.img is Raspberry Pi OS's linux 6.18.50-1+rpt1 built with
zero-lab/kernel/config by zero-lab/kernel/build.sh. Its source is the release asset
Zero-Lab-<version>-kernel-source.tar, and `kernel/build.sh source` fetches the same files (checked)
from https://archive.raspberrypi.com/debian/pool/main/l/linux/.
Licences and versions of everything else: THIRD-PARTY.md.
TXT
ls -la "$OUT"
