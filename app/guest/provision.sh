#!/bin/sh
# Runs as root once, on the Pi's first boot (kernel cmdline systemd.run, script from the DTB).
# cloud-init has already been given the user and SSH key (user-data on the boot partition); this does the
# rest without needing the network, then powers off. The host reads markers on the serial console.
exec >/dev/console 2>&1
# Markers go through the kernel log: the Zero 2 W's Bluetooth claims the serial UART, which swallows plain
# writes to /dev/ttyAMA1, but kernel messages always reach the console (raspi-zero2w network-probe.sh does this).
mark() { printf '<4>%s\n' "$*" > /dev/kmsg 2>/dev/null || echo "$*"; }
mark ZL_PROVISION_BEGIN
date -u -s "@$(tr -d '\000' < /proc/device-tree/chosen/zl-epoch)" >/dev/null 2>&1 || true
systemctl start --no-block multi-user.target
cloud-init status --wait >/dev/null 2>&1 || true
USER_NAME=$(tr -d '\000' < /proc/device-tree/chosen/zl-user)
if id "$USER_NAME" >/dev/null 2>&1; then mark ZL_USER_READY; else mark "ZL_PROVISION_FAIL user $USER_NAME missing"; fi

# QEMU's USB Ethernet needs an explicit DHCP profile (as raspi-zero2w network-probe.sh does).
mkdir -p /etc/NetworkManager/system-connections
cat > /etc/NetworkManager/system-connections/zero-lab-usb.nmconnection <<'PROFILE'
[connection]
id=zero-lab-usb
type=ethernet
autoconnect=true
autoconnect-priority=100
[ipv4]
method=auto
[ipv6]
method=auto
PROFILE
chmod 600 /etc/NetworkManager/system-connections/zero-lab-usb.nmconnection
systemctl enable ssh >/dev/null 2>&1 && mark ZL_SSH_ENABLED
raspi-config nonint do_boot_behaviour B4 && mark ZL_AUTOLOGIN

# The stock kernel has virtio as modules only: put them in the initramfs so later boots use virtio-blk root.
for m in virtio_mmio virtio_blk virtio_gpu; do grep -qx "$m" /etc/initramfs-tools/modules || echo "$m" >> /etc/initramfs-tools/modules; done
grep -q '^COMPRESSLEVEL=' /etc/initramfs-tools/initramfs.conf || echo 'COMPRESSLEVEL=3' >> /etc/initramfs-tools/initramfs.conf
mark ZL_INITRAMFS_BEGIN
update-initramfs -u -k "$(uname -r)" > /run/zl-initramfs.log 2>&1 || mark "ZL_PROVISION_WARN initramfs: $(tail -n 2 /run/zl-initramfs.log | tr '\n' ' ')"
lsinitramfs /boot/firmware/initramfs8 2>/dev/null | grep -q 'virtio_blk' && mark ZL_VIRTIO_INITRAMFS_OK
sync
mark ZL_PROVISIONED
systemctl poweroff
