#!/bin/bash
# usage: bootloop.sh <tag> <runs> <kernel> <dtb> <initramfs> <note>
S=${S:-/tmp/claude-1000/-home-ed--config-Claude-scratch-workspaces-c48635fb-e084-493c-9b70-699cbd56303e-d16a61b1-68f1-41ba-b01f-da77d91e9dc6-scratch-2026-10-22-01d1d1/1f4a45c6-e24d-450d-8d31-b0ff98558e83/scratchpad}
K=/home/ed/dev/omarchy/kernel; M=/home/ed/dev/omarchy/forks/omacom-m1n1
TAG=$1; RUNS=$2; KERNEL=$3; DTB=$4; IRD=$5; NOTE=$6
ARGS='maxcpus=1 console=tty0 fbcon=font:TER16x32 t6050_wdt=170 t6050_peek=0x2a2280420,0x2a2280024,0x382280420,0x382280024 dyndbg="file drivers/usb/host/xhci-hub.c +p"'
cd $M
for run in $(seq 1 $RUNS); do
  OLD=; for i in $(seq 1 900); do OLD=$(ls /dev/serial/by-id/usb-Asahi_Linux_m1n1_uartproxy_*g7cde*-if00 2>/dev/null | head -1); [ -n "$OLD" ] && break; sleep 2; done
  [ -n "$OLD" ] || { echo "resident proxy not present"; exit 1; }
  sleep 5
  NEW=
  for try in 1 2 3; do
    M1N1DEVICE=$OLD PYTHONPATH=$M/proxyclient timeout 120 .venv/bin/python $M/proxyclient/tools/chainload.py $S/m1n1-dev.macho > $K/log/last-chainload.log 2>&1
    for i in $(seq 1 60); do NEW=$(ls /dev/serial/by-id/usb-Asahi_Linux_m1n1_uartproxy_*-if00 2>/dev/null | grep -v g7cde | head -1); [ -n "$NEW" ] && break; sleep 1; done
    [ -n "$NEW" ] && break
    echo "$(date +%H:%M:%S) chainload $try: no dev proxy appeared"
    OLD=; for i in $(seq 1 300); do OLD=$(ls /dev/serial/by-id/usb-Asahi_Linux_m1n1_uartproxy_*g7cde*-if00 2>/dev/null | head -1); [ -n "$OLD" ] && break; sleep 2; done
    [ -n "$OLD" ] || { echo "resident proxy not present"; exit 1; }
    sleep 5
  done
  [ -n "$NEW" ] || { echo "no dev proxy after 3 chainloads"; exit 1; }
  sleep 3; t0=$(date +%s)
  (M1N1DEVICE=$NEW PYTHONPATH=$M/proxyclient timeout 300 .venv/bin/python $M/proxyclient/tools/linux.py -b "$ARGS" $KERNEL $DTB $IRD > $K/log/last-linux-$TAG$run.log 2>&1 &)
  for n in $(seq -w 1 20); do sleep 10; $S/cam/snap.sh $TAG$run-$n >/dev/null 2>&1; if ls /dev/serial/by-id/ 2>/dev/null | grep -q g7cde && [ $n -gt 4 ]; then echo "run $run: resident proxy back at frame $n, $(( $(date +%s) - t0 )) s"; break; fi; done
  echo "$(date +%H:%M:%S) $TAG$run: $NOTE; frames $TAG$run-01..$n" | tee -a $K/log/boots.log
  sleep 5
done
