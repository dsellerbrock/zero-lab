#!/bin/bash
# Build Zero Lab's Pi kernel (kernel8-virtio.img): the Raspberry Pi OS rpi-v8 kernel, same source and
# version, with virtio-mmio, virtio-blk and virtio-gpu built in (`config` here is the complete .config).
#
#   kernel/build.sh           fetch the source (checked), build in a Debian container (docker or colima)
#   kernel/build.sh source    only fetch the source into kernel/src (this is the GPL source for the binary)
set -euo pipefail
K=$(cd "$(dirname "$0")" && pwd)
POOL=https://archive.raspberrypi.com/debian/pool/main/l/linux
SRC="d2fc041dab4e11d9645e3ba53be058faa52b8ce28a8a97c889bb2cacee170461 linux_6.18.50.orig.tar.xz
98c2e147fda1eac197a221e6fb824e794c04830112d306f32c836433833e355e linux_6.18.50-1+rpt1.debian.tar.xz
3d49184a38ee5c6dab095ef583c6397e3cb2149ceb102d58f81950969f03b252 linux_6.18.50-1+rpt1.dsc"
mkdir -p "$K/src"
while read -r sum f; do
  [ -f "$K/src/$f" ] || curl -fL --retry 3 -o "$K/src/$f" "$POOL/$f"
  echo "$sum  $K/src/$f" | shasum -a 256 -c --quiet
done <<< "$SRC"
[ "${1:-}" = source ] && exit 0

docker run --rm -v "$K:/k" debian:trixie bash -euc '
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  cross=; [ "$(uname -m)" = aarch64 ] || cross=gcc-aarch64-linux-gnu
  apt-get install -y -qq --no-install-recommends build-essential bc bison flex libssl-dev libelf-dev \
    dpkg-dev xz-utils python3 kmod cpio $cross >/dev/null
  [ -n "$cross" ] && export CROSS_COMPILE=aarch64-linux-gnu-
  cd /tmp && dpkg-source --no-check -x /k/src/linux_6.18.50-1+rpt1.dsc linux >/dev/null && cd linux
  cp /k/config .config
  make ARCH=arm64 olddefconfig >/dev/null
  make ARCH=arm64 -j3 Image 2>&1 | tail -2
  cp arch/arm64/boot/Image /k/kernel8-virtio.img
  strings /k/kernel8-virtio.img | grep -m1 "Linux version"'
