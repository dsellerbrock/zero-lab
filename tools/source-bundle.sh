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
: "${ZL_QEMU_COMMIT:?set ZL_QEMU_COMMIT}"
VIRGL_SRC=${ZL_VIRGL_SRC:-$PROJECTS/a6-virgl-stack/sources/virglrenderer}
EPOXY_SRC=${ZL_EPOXY_SRC:-$PROJECTS/a6-virgl-stack/sources/libepoxy}

short=$(git -C "$QEMU_REPO" rev-parse --short=12 "$ZL_QEMU_COMMIT")
q="$CACHE/qemu-zero-lab-$short.tar.xz"
if [ ! -f "$q" ]; then
  # QEMU's own script: the tree at the commit plus the meson subprojects it builds with.
  tmp=$(mktemp -d); git clone -q --no-checkout "$QEMU_REPO" "$tmp/qemu"
  git -C "$tmp/qemu" checkout -q "$ZL_QEMU_COMMIT"
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
rm -rf "$OUT/patches" && cp -R "$ROOT/patches" "$OUT/patches"  # applied on top of the QEMU tarball by setup.sh
cat > "$OUT/README.txt" <<TXT
Complete corresponding source for Zero Lab binaries.
QEMU (GPL-2.0): qemu-zero-lab-$short.tar.xz is the fork at commit $(git -C "$QEMU_REPO" rev-parse "$ZL_QEMU_COMMIT"),
made with QEMU's scripts/archive-source.sh. Build: see zero-lab/mac/build-bundle.sh (macOS) or linux/setup.sh.
Licences and versions of everything else: THIRD-PARTY.md.
TXT
ls -la "$OUT"
