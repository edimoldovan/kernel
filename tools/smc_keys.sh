#!/bin/bash
# smc_keys.sh [0|1]: read the SMC keys D1Vn and D2Vn over the resident m1n1 proxy; with a value,
# write it to both first (as macOS's AppleHPMARM::set4ccLock writes D1Vn; see USB-BRINGUP.md).
# The SMC session is quiesced afterwards, as m1n1's own smc_shutdown does.
set -eu
V=${1:-}
case "$V" in ""|0|1) ;; *) echo "usage: $0 [0|1]"; exit 1 ;; esac
cd /home/ed/dev/omarchy/forks/omacom-m1n1
M1N1DEVICE=$(printf '%s' /dev/serial/by-id/usb-Asahi_Linux_m1n1_uartproxy_*g7cde*-if00) \
PYTHONPATH=proxyclient SMC_VALUE="$V" .venv/bin/python - <<'PY'
import os
from m1n1.setup import *
from m1n1.fw.smc import SMCClient
smc = SMCClient(u, u.adt["arm-io/smc"].get_reg(0)[0], None)
smc.start()
smc.start_ep(0x20)
ep = smc.epmap[0x20]
v = os.environ["SMC_VALUE"]
for key in ("D1Vn", "D2Vn"):
    if v:
        ep.write8(key, int(v))
    print(key, ep.read8(key), flush=True)
smc.stop()
print("quiesced", flush=True)
PY
