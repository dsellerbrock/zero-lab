# Pinned inputs for every Zero Lab build (sourced by mac/, tools/, linux/ scripts and CI).
# A build from a clean git checkout fetches exactly these; nothing comes from the builder's own folders.
# Bump a pin here, once, and every platform follows.

# The QEMU fork: GPIO events, raspi3ap virtio-mmio, HVF 4 KiB granule, Venus, MCP3008 ADC, I2C displays, builds with mingw
ZL_QEMU_URL=${ZL_QEMU_URL:-https://github.com/dsellerbrock/qemu-raspi-zero2w.git}
ZL_QEMU_COMMIT=${ZL_QEMU_COMMIT:-bbcc147dffa6460aa7d4fea710011f4889ce2d99}

# virglrenderer with Venus on macOS, and libepoxy with EGL on macOS (UTM's forks)
ZL_VIRGL_URL=https://github.com/utmapp/virglrenderer.git
ZL_VIRGL_COMMIT=451505ad0aa449290f2c0672da6877d57ee770e5
ZL_EPOXY_URL=https://github.com/utmapp/libepoxy.git
ZL_EPOXY_COMMIT=bf98587477fe68d07b93319ece7b40a7d0e2eabe

# Khronos EGL/GLES/KHR headers (build only, macOS)
ZL_EGL_REGISTRY=https://github.com/KhronosGroup/EGL-Registry/archive/e964211ff5f7c2bcada786954a16d5b813379395.tar.gz
ZL_GL_REGISTRY=https://github.com/KhronosGroup/OpenGL-Registry/archive/6af574a14089ccfee87efe230ebcdd8742859813.tar.gz

# MoltenVK (Vulkan on Metal, macOS): the official release
ZL_MOLTENVK_URL=https://github.com/KhronosGroup/MoltenVK/releases/download/v1.4.2/MoltenVK-macos.tar
ZL_MOLTENVK_SHA=f95765a6229cb7b915990a2890ce12ebe36a730b021545d3d52ae69ce4c4024e

# Clone a git URL at an exact commit into DIR (shallow; works for any reachable commit on GitHub).
zl_checkout() { # url commit dir
  [ "$(git -C "$3" rev-parse HEAD 2>/dev/null)" = "$2" ] && return 0
  rm -rf "$3"; git init -q "$3"
  git -C "$3" fetch -q --depth 1 "$1" "$2" && git -C "$3" checkout -q FETCH_HEAD
}

# Windows installer (tools/make-windows-installer.sh): built in this Fedora image, with the mingw-w64 toolchain,
# the DLLs it ships and NSIS installed from these exact Fedora builds (koji keeps every build at a fixed URL).
ZL_WIN_IMAGE=registry.fedoraproject.org/fedora:44@sha256:6ad1739ac6fb30f72ecc7b62a7ca94871d1cab215e4f5174113941047e0b4ed4
ZL_WIN_PYTHON_URL=https://github.com/astral-sh/python-build-standalone/releases/download/20251014/cpython-3.12.12+20251014-x86_64-pc-windows-msvc-install_only_stripped.tar.gz
ZL_WIN_PYTHON_SHA=3c8b9b10a933909c98b9916297e2093b24a9c2abaa23df1c2622c2bfe052cb94
ZL_KOJI=https://kojipkgs.fedoraproject.org/packages
ZL_WIN_RPMS="
mingw-binutils/2.46.0/1.fc44/x86_64/mingw-binutils-generic-2.46.0-1.fc44.x86_64.rpm 8aa1bc3342379b242f7f8c0bb4c09d2ead8ef7d78ed1b5a7799b5e6db48d9e95
mingw-binutils/2.46.0/1.fc44/x86_64/mingw64-binutils-2.46.0-1.fc44.x86_64.rpm 2b06e3f23b56fa6b568132fb184c941b9a624e94e3addd27241055ba36ba6c1f
mingw-filesystem/152/1.fc44/noarch/mingw-filesystem-base-152-1.fc44.noarch.rpm c939f7298f8a260d0ff150488c538831e5687cd750da5b24d169ceaab97eaf7d
mingw-filesystem/152/1.fc44/noarch/mingw64-filesystem-152-1.fc44.noarch.rpm e6c4cdac724e1d46dad76102c8cb5031767145e5f8f4b5756894088efb97e16a
mingw-headers/13.0.0/3.fc44/noarch/mingw64-headers-13.0.0-3.fc44.noarch.rpm 8b5231ff5b2252c1bf55325ef4684009c49eb7e187aa317d5a392cb147abd396
mingw-crt/13.0.0/3.fc44/noarch/mingw64-crt-13.0.0-3.fc44.noarch.rpm 17694aba5ce0aca7fdee95a0e39ad8923d5551e682612658a7ce0978b0b46493
mingw-winpthreads/13.0.0/3.fc44/noarch/mingw64-winpthreads-13.0.0-3.fc44.noarch.rpm f37e44a4474890e545b9d6b5574ce48ef4d2fbbab7a1a99013a585a949166d9e
mingw-winpthreads/13.0.0/3.fc44/noarch/mingw64-winpthreads-static-13.0.0-3.fc44.noarch.rpm b9e599838aedace85d7126692d557bfc2e81d3e07a49a3eaab6c355a503a5227
mingw-w64-tools/13.0.0/3.fc44/x86_64/mingw-w64-tools-13.0.0-3.fc44.x86_64.rpm 69a3f6c5881db6876e987b466f05a74a603ae8d624f0c6a0ef4845262f8a0d9b
mingw-gcc/16.2.1/1.fc44/x86_64/mingw64-cpp-16.2.1-1.fc44.x86_64.rpm 977d2a1ca0ea8363509fd1988be1f40c1ec5d6808c163c1f9ca8d53c3855a2a8
mingw-gcc/16.2.1/1.fc44/x86_64/mingw64-gcc-16.2.1-1.fc44.x86_64.rpm e70051ff38ca440b8aa4601407b9e0b9ef73d1f55b72288ef9cfd4945e601ad8
mingw-gcc/16.2.1/1.fc44/x86_64/mingw64-libgcc-16.2.1-1.fc44.x86_64.rpm 4ff36de3a5a0ccd2f6c64d5b04bcbc9d9486b1be51f3d64dc930127b2ee7d063
mingw-gcc/16.2.1/1.fc44/x86_64/mingw64-libstdc++-16.2.1-1.fc44.x86_64.rpm aab383cdbece9e085dd0d26433767eac9852dd4a85ca6b6550ce7c10f8f8dba3
mingw-glib2/2.88.3/1.fc44/noarch/mingw64-glib2-2.88.3-1.fc44.noarch.rpm 701dc8c30947e84feb22893d936935026038c85378f33b4204f9ddb8b267ad7c
mingw-gettext/0.26/2.fc44/noarch/mingw64-gettext-0.26-2.fc44.noarch.rpm 4fe8a23d9c04f1266076f3f104444a58918c3a40dda47dcd47d9b5fd76d35a38
mingw-termcap/1.3.1/40.fc44/noarch/mingw64-termcap-1.3.1-40.fc44.noarch.rpm ccd6a41cf8163423346fb3f2c313b044af4b7ae28d83c8835081c87dc20d7332
mingw-win-iconv/0.0.10/4.fc44/noarch/mingw64-win-iconv-0.0.10-4.fc44.noarch.rpm e330efae3611a782e4f542bbe0fc58cea7f04a00d0833ae1c2a4c5c17f94e7bf
mingw-libffi/3.5.2/2.fc44/noarch/mingw64-libffi-3.5.2-2.fc44.noarch.rpm a75bdafb6717c0278d8e848f88bd97d394e0877b00bbada6a0df8ac71823daa7
mingw-pcre2/10.48/1.fc44/noarch/mingw64-pcre2-10.48-1.fc44.noarch.rpm d8c3045b2927c09bc4d7992e6a259c4a4af1eadc5e1d1776096005d2c6ae1716
mingw-zlib/1.3.2/1.fc44/noarch/mingw64-zlib-1.3.2-1.fc44.noarch.rpm 0ab9ad8515050f382208887deb0b178f87754bb11ca58019b7a2fa0868c7f9a2
mingw-pixman/0.46.4/2.fc44/noarch/mingw64-pixman-0.46.4-2.fc44.noarch.rpm c81631ef367694da55a825747b08529845d9e8986d33a4cf807df79e943e1ef7
mingw-nsis/3.11/3.fc44/x86_64/mingw-nsis-base-3.11-3.fc44.x86_64.rpm 34011fab9c67352a48af473bb705f82ca5495b92251ac7d3eb1c3a11c0ea5e30
mingw-nsis/3.11/3.fc44/noarch/mingw32-nsis-3.11-3.fc44.noarch.rpm 3cc8f40409a019d3d45bdf49a8bc41e4b0e8d13ce7f3a6a63478d35d14330c0f
"
# Sources of the LGPL DLLs the installer ships (GLib, libintl) and of NSIS, for the GPL source download
ZL_WIN_SRPMS="
mingw-glib2/2.88.3/1.fc44/src/mingw-glib2-2.88.3-1.fc44.src.rpm af544274b0084ee90baa5f335abf7a157d5a4b7965cfd4c67bf59391fb4dffd2
mingw-gettext/0.26/2.fc44/src/mingw-gettext-0.26-2.fc44.src.rpm 7d39c3b9dd702533121355ecfc7c366f2d5b513cf5495e8ab4425ddc50e6c1bc
mingw-nsis/3.11/3.fc44/src/mingw-nsis-3.11-3.fc44.src.rpm d595bf92545bd98ed8cf9fe50b24a4a509afd0100fdf57817cb3e96dab5eb856
"

# Download $ZL_KOJI/<path> into DIR once and check its sha256, for each "path sha256" line of a list.
zl_fetch_koji() { # list dir
  local p s
  mkdir -p "$2"
  while read -r p s; do
    [ -n "$p" ] || continue
    [ -f "$2/${p##*/}" ] || { curl -fsSL --retry 5 --retry-all-errors -o "$2/${p##*/}.part" "$ZL_KOJI/$p" \
      && mv "$2/${p##*/}.part" "$2/${p##*/}"; }
    echo "$s  $2/${p##*/}" | sha256sum -c --quiet - || { rm -f "$2/${p##*/}"; return 1; }
  done <<< "$1"
}
