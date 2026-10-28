#!/bin/bash
# net_boots.sh TAG COUNT: COUNT network-report boots of the built kernel (see TEST-LOOP.md).
# Each boot: wait for the resident proxy, start net_recv.py, boot_t6050.sh with the network
# initramfs, wait for the report. Reports in log/net-TAG<n>.txt, one summary line per boot.
# Env: IMG, DTB, IRD, WDT (default 170), EXTRA (default "pd_ignore_unused printk.time=1").
set -u
TAG=$1; COUNT=$2
T=$(cd "$(dirname "$0")" && pwd); K=$(dirname "$T")
B=/tmp/opencode/aurora-build-j714c/arch/arm64/boot
export IMG=${IMG:-$B/Image.gz} DTB=${DTB:-$B/dts/apple/t6050-j714c.dtb}
export IRD=${IRD:-$K/boot/initramfs-net.cpio.gz} WDT=${WDT:-170} EXTRA=${EXTRA:-"pd_ignore_unused printk.time=1"}
for i in $(seq 1 "$COUNT"); do
  for w in $(seq 1 60); do ls /dev/serial/by-id/ | grep -q g7cde && break; sleep 2; done
  R=$K/log/net-$TAG$i.txt; rm -f "$R"
  timeout 420 python3 "$T/net_recv.py" "$R" 400 > "$K/log/net-$TAG$i.recv" 2>&1 &
  r=$!
  "$T/boot_t6050.sh" "net-$TAG$i"
  wait $r
  echo "$TAG$i: $(cat "$K/log/net-$TAG$i.recv") | $(grep -h '^--- usb [0-9]-1:' "$R" 2>/dev/null | tr '\n' ' ')"
done
