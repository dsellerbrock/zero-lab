#!/bin/bash
# Put the complete corresponding source for everything Zero Lab ships into DIR (GPL/LGPL).
#   tools/source-bundle.sh DIR
# Versions come from tools/pins.sh (and, for the macOS LGPL libraries, from what Homebrew installed),
# so this works from a clean clone. Env (optional): ZL_QEMU_REPO, a local clone of the fork.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
. "$ROOT/tools/pins.sh"
OUT=$(mkdir -p "$1" && cd "$1" && pwd)
CACHE="$ROOT/build/sources"; mkdir -p "$CACHE"
QEMU_REPO=${ZL_QEMU_REPO:-$ZL_QEMU_URL}

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
for pin in "virglrenderer $ZL_VIRGL_URL $ZL_VIRGL_COMMIT" "libepoxy $ZL_EPOXY_URL $ZL_EPOXY_COMMIT"; do
  set -- $pin; src="$CACHE/$1"; zl_checkout "$2" "$3" "$src"
  git -C "$src" archive --prefix="$1-${3:0:12}/" HEAD | xz -T3 -9 > "$OUT/$1-${3:0:12}.tar.xz"
done
git -C "$ROOT" archive --prefix=zero-lab/ HEAD | xz -9 > "$OUT/zero-lab-$(git -C "$ROOT" rev-parse --short=12 HEAD).tar.xz"
# LGPL libraries the macOS app bundles from Homebrew: the source of exactly the installed version
if command -v brew >/dev/null; then
  gv=$(brew list --versions glib | cut -d" " -f2); tv=$(brew list --versions gettext | cut -d" " -f2)
  g="https://download.gnome.org/sources/glib/${gv%.*}/glib-$gv.tar.xz"
  t="https://ftpmirror.gnu.org/gettext/gettext-$tv.tar.gz"
  gsha=$(curl -fsL "https://download.gnome.org/sources/glib/${gv%.*}/glib-$gv.sha256sum" | grep "glib-$gv.tar.xz" | cut -d" " -f1)
  tsha=$(brew info --json=v2 gettext | python3 -c "import json,sys; f=json.load(sys.stdin)['formulae'][0]; print(f['urls']['stable']['checksum'] if f['versions']['stable']=='$tv' else '')")
  for pair in "$g $gsha" "$t $tsha"; do
    set -- $pair; f="$CACHE/$(basename "$1")"
    [ -n "${2:-}" ] || { echo "no checksum for $1" >&2; exit 1; }
    [ -f "$f" ] || curl -fsL --retry 3 -o "$f" "$1"
    echo "$2  $f" | shasum -a 256 -c - >/dev/null
    cp "$f" "$OUT/"
  done
  { echo "Built with (Homebrew):"; brew list --versions glib gettext pixman libslirp; } > "$OUT/VERSIONS.txt"
fi
{ echo "Pinned (tools/pins.sh): QEMU fork $ZL_QEMU_COMMIT, virglrenderer $ZL_VIRGL_COMMIT, libepoxy $ZL_EPOXY_COMMIT, MoltenVK ${ZL_MOLTENVK_URL##*/download/}"; } >> "$OUT/VERSIONS.txt"
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
