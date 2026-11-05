#!/bin/bash
# Boot the built kernel over the resident m1n1 proxy, then time the watchdog
# reset: the reset-to-proxy time, minus OFFSET (reboot.py calibration), tells
# the last milestone reached in 20 s steps. M1N1_MACHO=<file> chainloads that
# m1n1 first; core start after a chainload is untested on T6050.
set -u
M=/home/ed/dev/omarchy/forks/omacom-m1n1; L=$(dirname "$0"); K=$(dirname "$L"); OFFSET=${OFFSET:-11}
IMG=${IMG:-$K/boot/Image.gz}
DTB=${DTB:-$K/boot/t6050-j714c.dtb}
IRD=${IRD:-$K/boot/initramfs.cpio.gz}
TAG=${1:-run}; LOG=$K/log/boots.log; stamp=$(date +%H:%M:%S)
proxy() { ls /dev/serial/by-id/usb-Asahi_Linux_m1n1_uartproxy_*-if00 2>/dev/null | head -1; }
cd $M
DEV=$(proxy)
[ -n "$DEV" ] || { echo "$stamp $TAG: resident proxy absent" | tee -a $LOG; exit 2; }
if [ -n "${M1N1_MACHO:-}" ]; then
  M1N1DEVICE=$DEV PYTHONPATH=$M/proxyclient timeout 120 .venv/bin/python $M/proxyclient/tools/chainload.py $M1N1_MACHO > $K/log/last-chainload.log 2>&1
  for i in $(seq 1 20); do [ -e "$DEV" ] || break; sleep 1; done
  DEV=; for i in $(seq 1 60); do DEV=$(proxy); [ -n "$DEV" ] && break; sleep 1; done
  [ -n "$DEV" ] || { echo "$stamp $TAG: chainloaded proxy never appeared" | tee -a $LOG; exit 3; }
  sleep 3
fi
M1N1DEVICE=$DEV PYTHONPATH=$M/proxyclient timeout 240 .venv/bin/python $M/proxyclient/tools/linux.py -b "console=tty0 t6050_wdt=${WDT:-150} ${EXTRA:-}" $IMG $DTB $IRD > $K/log/last-linux.log 2>&1
grep -q 'Preparing to boot kernel' $K/log/last-linux.log || { echo "$stamp $TAG: no handoff, see last-linux.log" | tee -a $LOG; grep -E 'SError|Traceback|Error|mismatch' $K/log/last-linux.log | head -3; exit 4; }
for i in $(seq 1 20); do [ -e "$DEV" ] || break; sleep 1; done
back=; for i in $(seq 1 280); do [ -n "$(proxy)" ] && { back=$i; break; }; sleep 1; done
if [ -z "$back" ]; then echo "$stamp $TAG: handoff ok, no watchdog reset in 280 s" | tee -a $LOG; exit 5; fi
dt=$((back - OFFSET)); m=$(( (dt + 10) / 20 ))
case $m in
  2) w="kernel never reached the end of the simplefb probe";; 3) w="genpds ok; fb_alloc_cmap or register_framebuffer failed (60 s)";; 4) w="simplefb registered, fbcon has the panel (80 s)";; *) w="unmapped";;
esac
echo "$stamp $TAG: handoff ok, proxy back after ${back}s (offset $OFFSET, net ${dt}s) -> $w" | tee -a $LOG
