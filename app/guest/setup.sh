#!/bin/sh
# Runs as root on every Zero Lab desktop boot (kernel cmdline systemd.run, script from the DTB).
# Trimmed from raspi-zero2w/desktop-input-setup.sh: input seat rule, compositor renderer, ready marker.
exec >/dev/console 2>&1
# Markers go through the kernel log: the Zero 2 W's Bluetooth claims the serial UART, which swallows plain
# writes to /dev/ttyAMA1, but kernel messages always reach the console (raspi-zero2w network-probe.sh does this).
mark() { printf '<2>%s\n' "$*" > /dev/kmsg 2>/dev/null; echo "$*"; }  # <2>: Pi OS sets kernel.printk = 3 4 1 3
mark ZL_SETUP_BEGIN
# The Pi has no clock battery: take the host's time so TLS, apt and make work.
date -u -s "@$(tr -d '\000' < /proc/device-tree/chosen/zl-epoch)" >/dev/null 2>&1 || true

GPU_MODE=$(tr -d '\000' < /proc/device-tree/chosen/zl-gpu-mode 2>/dev/null || echo soft)
USER_NAME=$(tr -d '\000' < /proc/device-tree/chosen/zl-user 2>/dev/null || echo pi)
case "$GPU_MODE" in
  virgl) WLR_RENDERER=gles2; MESA_DRIVER=virtio_gpu ;;
  *) WLR_RENDERER=pixman; MESA_DRIVER= ;;  # venus (Vulkan for apps) and soft: compositor in pixman
esac

# QEMU's USB keyboard/tablet must join seat0 or the Wayland compositor ignores them.
printf '%s\n' 'SUBSYSTEM=="input", KERNEL=="event*", ENV{ID_VENDOR_ID}=="0627", ENV{ID_MODEL_ID}=="0001", ENV{ID_SEAT}="seat0", TAG+="seat", GROUP="input", MODE="0660"' \
  > /etc/udev/rules.d/99-qemu-hid-seat.rules
udevadm control --reload-rules
udevadm trigger --action=add --subsystem-match=input
udevadm settle --timeout=10 || true

HOME_DIR=$(getent passwd "$USER_NAME" | cut -d: -f6)
ENV_FILE="$HOME_DIR/.config/labwc/environment"
mkdir -p "$(dirname "$ENV_FILE")"
touch "$ENV_FILE"
set_env() {
  sed -i "/^$1=/d" "$ENV_FILE"
  [ -n "$2" ] && printf '%s=%s\n' "$1" "$2" >> "$ENV_FILE"
}
set_env WLR_NO_HARDWARE_CURSORS 1
set_env WLR_DRM_NO_MODIFIERS 1
set_env WLR_RENDERER "$WLR_RENDERER"
set_env MESA_LOADER_DRIVER_OVERRIDE "$MESA_DRIVER"
chown -R "$USER_NAME:$USER_NAME" "$HOME_DIR/.config"
if [ -f /usr/bin/labwc-pi ]; then
  sed -i '/^export WLR_RENDERER=/d' /usr/bin/labwc-pi
  sed -i "/^exec .*labwc/ i\\export WLR_RENDERER=$WLR_RENDERER" /usr/bin/labwc-pi
  grep -q '^export WLR_NO_HARDWARE_CURSORS=1$' /usr/bin/labwc-pi ||
    sed -i '/^exec .*labwc/ i\export WLR_NO_HARDWARE_CURSORS=1' /usr/bin/labwc-pi
fi

# /dev/i2c-1 for the emulated I2C displays (dtparam=i2c_arm=on needs i2c-dev, as raspi-config adds to /etc/modules)
modprobe i2c-dev 2>/dev/null || true

systemctl start ssh 2>/dev/null && mark ZL_SSH_READY

# Tell the app when the desktop panel and file manager are up (boot-time measurement).
systemd-run --quiet --no-block --unit=zl-ready-watch.service /bin/sh -c '
  i=0
  while [ $i -lt 900 ]; do
    if pgrep -x wf-panel-pi >/dev/null && pgrep -x pcmanfm >/dev/null; then
      printf "<2>ZL_DESKTOP_READY\\n" > /dev/kmsg; exit 0
    fi
    i=$((i + 1)); sleep 1
  done'

systemctl start --no-block graphical.target
mark ZL_SETUP_DONE
