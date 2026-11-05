#!/bin/bash
# omarchy_boot.sh TAG: boot the full Omarchy root (read-write) on the J714c over the resident m1n1
# proxy and wait until SSH answers. If the Mac is running Linux instead of the proxy, it is
# rebooted over SSH first (needs /etc/sudoers.d/ed-reboot on the Mac, see OMARCHY-LOGIN.md).
# Log: log/last-linux-TAG.log. Env: IMG, DTB, IRD, EXTRA (added to the kernel command line).
set -u
K=$(cd "$(dirname "$0")/.." && pwd); M=/home/ed/dev/omarchy/forks/omacom-m1n1
B=/tmp/opencode/aurora-build-j714c-swap/arch/arm64/boot
IMG=${IMG:-$B/Image.gz}; DTB=${DTB:-$B/dts/apple/t6050-j714c.dtb}; IRD=${IRD:-$K/boot/initramfs-rw.cpio.gz}
TAG=$1
SSH="ssh -o BatchMode=yes -o ConnectTimeout=4 ed@192.168.188.39"
proxy() { ls /dev/serial/by-id/usb-Asahi_Linux_m1n1_uartproxy_*-if00 2>/dev/null | head -1; }
[ -n "$(proxy)" ] || $SSH 'sudo -n systemctl reboot' 2>&1 | grep -v 'closed by remote'
D=; for i in $(seq 1 90); do D=$(proxy); [ -n "$D" ] && break; sleep 2; done
[ -n "$D" ] || { echo "$TAG: no proxy"; exit 1; }
sleep 3
# The asahi driver stays off until the GPU runs jobs: with it, Mesa stops on renderD128 and
# the SDDM greeter never comes up (TEST-LOOP.md).
cd $M && M1N1DEVICE=$D PYTHONPATH=$M/proxyclient timeout 240 .venv/bin/python proxyclient/tools/linux.py \
  -b "console=tty0 pd_ignore_unused printk.time=1 initcall_blacklist=__asahi_init ${EXTRA:-}" \
  $IMG $DTB $IRD > $K/log/last-linux-$TAG.log 2>&1
grep -q 'Preparing to boot kernel' $K/log/last-linux-$TAG.log || { echo "$TAG: no handoff, see log/last-linux-$TAG.log"; exit 1; }
for i in $(seq 1 50); do $SSH true 2>/dev/null && { echo "$TAG: ssh up"; exit 0; }; sleep 3; done
echo "$TAG: no ssh"; exit 1
