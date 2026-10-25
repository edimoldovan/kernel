#!/bin/bash
# Chainload the built m1n1, boot the built kernel over its proxy, then time
# the watchdog reset: the reset-to-proxy time, minus OFFSET (reboot.py
# calibration), tells the last milestone reached in 20 s steps.
set -u
M=/home/ed/dev/omarchy/forks/omacom-m1n1; F=$M; L=$(dirname "$0"); K=$(dirname "$L"); OFFSET=${OFFSET:-11}
IMG=${IMG:-$K/boot/Image.gz}
DTB=${DTB:-$K/boot/t6050-j714c.dtb}
IRD=${IRD:-$K/boot/initramfs.cpio.gz}
TAG=${1:-run}; LOG=$K/log/boots.log; stamp=$(date +%H:%M:%S)
cd $M
OLD=$(ls /dev/serial/by-id/usb-Asahi_Linux_m1n1_uartproxy_*g7cde*-if00 2>/dev/null | head -1)
[ -n "$OLD" ] || { echo "$stamp $TAG: resident proxy absent" | tee -a $LOG; exit 2; }
M1N1DEVICE=$OLD PYTHONPATH=$F/proxyclient timeout 120 .venv/bin/python $F/proxyclient/tools/chainload.py ${M1N1_MACHO:-build/m1n1.macho} > $K/log/last-chainload.log 2>&1
NEW=; for i in $(seq 1 60); do NEW=$(ls /dev/serial/by-id/usb-Asahi_Linux_m1n1_uartproxy_*-if00 2>/dev/null | grep -v g7cde | head -1); [ -n "$NEW" ] && break; sleep 1; done
[ -n "$NEW" ] || { echo "$stamp $TAG: chainloaded proxy never appeared" | tee -a $LOG; exit 3; }
sleep 3
M1N1DEVICE=$NEW PYTHONPATH=$F/proxyclient timeout 240 .venv/bin/python $F/proxyclient/tools/linux.py -b "maxcpus=1 console=tty0 t6050_wdt=${WDT:-150} ${EXTRA:-}" $IMG $DTB $IRD > $K/log/last-linux.log 2>&1
t0=$(date +%s)
grep -q 'Preparing to boot kernel' $K/log/last-linux.log || { echo "$stamp $TAG: no handoff, see last-linux.log" | tee -a $LOG; grep -E 'SError|Traceback|Error' $L/last-linux.log | head -3; exit 4; }
back=; for i in $(seq 1 280); do ls /dev/serial/by-id/ 2>/dev/null | grep -q m1n1 && { back=$i; break; }; sleep 1; done
if [ -z "$back" ]; then echo "$stamp $TAG: handoff ok, no watchdog reset in 280 s" | tee -a $LOG; exit 5; fi
dt=$((back - OFFSET)); m=$(( (dt + 10) / 20 ))
case $m in
  2) w="kernel never reached the end of the simplefb probe";; 3) w="genpds ok; fb_alloc_cmap or register_framebuffer failed (60 s)";; 4) w="simplefb registered, fbcon has the panel (80 s)";; *) w="unmapped";;
esac
echo "$stamp $TAG: handoff ok, proxy back after ${back}s (offset $OFFSET, net ${dt}s) -> $w" | tee -a $LOG
