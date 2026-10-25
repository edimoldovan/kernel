# Read the GPT (primary LBA 0-5 and the backup) from NVMe namespace 1 over the resident m1n1 proxy. Reads only.
import struct, sys
from m1n1.setup import *
S = sys.argv[1]
ret = p.nvme_init(); print("nvme_init ->", ret)
assert ret == 1
buf = u.memalign(0x4000, 0x4000)
def rd(lba):
    r = p.nvme_read(1, lba, buf); assert r == 1, ("read failed", lba, r)
    return iface.readmem(buf, 4096)
prim = b"".join(rd(l) for l in range(0, 6))
h = prim[4096:4096+92]
sig, rev, hsz, hcrc, _, cur, bak, fu, lu, guid, elba, n, esz, ecrc = struct.unpack("<8sIIIIQQQQ16sQIII", h)
print("sig", sig, "cur", cur, "backup", bak, "usable", fu, lu, "entries at", elba, n, "x", esz)
open(S + "/gpt-primary.bin", "wb").write(prim)
# backup: entries at bak-4 .. bak-1 (4 blocks of 4 KiB), header at bak
back = b"".join(rd(l) for l in range(bak - 4, bak + 1))
open(S + "/gpt-backup.bin", "wb").write(back)
bh = back[4*4096:4*4096+92]
print("backup header sig", bh[:8], "cur", struct.unpack("<Q", bh[24:32])[0], "entries at", struct.unpack("<Q", bh[72:80])[0])
print("done")
