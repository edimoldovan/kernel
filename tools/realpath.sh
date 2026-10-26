#!/bin/bash
# Watches the real boot path after a reboot: stage 1 proxy window appears, then goes away when stage 2 takes over; snaps frames every 10 s.
S=${S:-/tmp/claude-1000/-home-ed--config-Claude-scratch-workspaces-c48635fb-e084-493c-9b70-699cbd56303e-d16a61b1-68f1-41ba-b01f-da77d91e9dc6-scratch-2026-10-22-01d1d1/1f4a45c6-e24d-450d-8d31-b0ff98558e83/scratchpad}
K=/home/ed/dev/omarchy/kernel; TAG=$1
seen=0; gone=0; for i in $(seq 1 600); do if ls /dev/serial/by-id/ 2>/dev/null | grep -q g7cde; then seen=1; elif [ $seen = 1 ]; then gone=1; break; fi; sleep 1; done
[ $gone = 1 ] || { echo "stage 1 proxy did not go away (seen=$seen)"; exit 1; }
echo "$(date +%H:%M:%S) stage 1 proxy gone, stage 2 running"
for n in $(seq -w 1 16); do sleep 10; $S/cam/snap.sh $TAG-$n >/dev/null 2>&1; done
echo "$(date +%H:%M:%S) $TAG: real path (stage 1 -> ESP stage 2 -> kernel -> disk root), frames $TAG-01..16" | tee -a $K/log/boots.log
