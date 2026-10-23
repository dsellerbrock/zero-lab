# Pinned inputs for every Zero Lab build (sourced by mac/, tools/, linux/ scripts and CI).
# A build from a clean git checkout fetches exactly these; nothing comes from the builder's own folders.
# Bump a pin here, once, and every platform follows.

# The QEMU fork: GPIO events, raspi3ap virtio-mmio, HVF 4 KiB granule, Venus, MCP3008 ADC, I2C displays
ZL_QEMU_URL=${ZL_QEMU_URL:-https://github.com/dsellerbrock/qemu-raspi-zero2w.git}
ZL_QEMU_COMMIT=${ZL_QEMU_COMMIT:-4e2db446fa6c9077ccfe964194aa2f530cb23fa3}

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
