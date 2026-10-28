#!/bin/bash
# gpu_probe.sh: over the resident m1n1 proxy, read what GPU.md steps 1 and 2 need. From the ADT:
# the sgx registers and the GFX/GFX1 firmware segments and UUIDs. From memory: the firmware
# segments iBoot preloaded, saved to /home/ed/dev/omarchy/firmware/gpu/ (Apple's, kept out of git)
# and searched for the G17 interface version. With the sgx power domain on: the ID registers.
set -eu
cd /home/ed/dev/omarchy/forks/omacom-m1n1
M1N1DEVICE=$(printf '%s' /dev/serial/by-id/usb-Asahi_Linux_m1n1_uartproxy_*g7cde*-if00) \
PYTHONPATH=proxyclient .venv/bin/python - <<'PY'
import os, re, struct
from m1n1.setup import *

OUT = "/home/ed/dev/omarchy/firmware/gpu"
IFACE = bytes.fromhex("c004960322a38a0c")  # g17/fw/initdata.rs INTERFACE_VERSION, little endian
os.makedirs(OUT, exist_ok=True)

def prop(node, name):
    try:
        return getattr(node, name.replace("-", "_"))
    except Exception:
        return None

sgx = u.adt["arm-io/sgx"]
regs = [sgx.get_reg(i) for i in range(len(sgx.reg))]
for i, (a, s) in enumerate(regs):
    print(f"sgx reg {i}: {a:#x} size {s:#x}", flush=True)

for asc in ("gfx-asc", "gfx1-asc"):
    node = u.adt["arm-io/" + asc]
    for i, (a, s) in enumerate(node.get_reg(j) for j in range(len(node.reg))):
        print(f"{asc} reg {i}: {a:#x} size {s:#x}", flush=True)
    nub = [c for c in node if c.name.startswith("iop-")][0]
    print(f"{asc} {nub.name} firmware {prop(nub, 'firmware-name')} uuid {prop(nub, 'uuid')}", flush=True)
    names = (prop(node, "segment-names") or "").split(";")
    raw = prop(node, "segment-ranges")
    if not isinstance(raw, (bytes, bytearray)):
        raw = bytes(raw) if raw is not None else b""
    for n in range(len(raw) // 32):
        phys, iova, remap, size, unk = struct.unpack_from("<QQQII", raw, n * 32)
        name = names[n] if n < len(names) else f"seg{n}"
        print(f"{asc} {name}: phys {phys:#x} iova {iova:#x} remap {remap:#x} size {size:#x}", flush=True)
        try:
            data = iface.readmem(phys, size)
        except Exception as e:
            print(f"  read failed: {e}", flush=True)
            continue
        path = f"{OUT}/{asc}{name}.bin"
        open(path, "wb").write(data)
        hits = [m.start() for m in re.finditer(re.escape(IFACE), data)]
        vers = sorted(set(re.findall(rb"(?:RTKit|AGX|iBoot)[A-Za-z0-9_.~\-]{4,60}", data)))[:8]
        print(f"  saved {path}; interface version at {[hex(h) for h in hits]}", flush=True)
        for v in vers:
            print(f"  string {v.decode(errors='replace')}", flush=True)

p.pmgr_adt_power_enable("/arm-io/sgx")
base = regs[0][0]
for name, off in (("ID_VERSION", 0xd04000), ("ID_UNK08", 0xd04008), ("ID_COUNTS_1", 0xd04010),
                  ("ID_COUNTS_2", 0xd04014), ("ID_UNK18", 0xd04018), ("ID_CLUSTERS", 0xd0401c),
                  ("CORE_MASK_0", 0xd01500), ("CORE_MASK_1", 0xd01514),
                  ("CORE_MASKS_G14X", 0xe01500), ("G17_CORE_POWER", 0xe01000)):
    try:
        v = p.read32(base + off)
        print(f"{name} ({base + off:#x}) = {v:#010x}", flush=True)
    except Exception as e:
        print(f"{name} ({base + off:#x}) read failed: {e}", flush=True)
print("done", flush=True)
PY
