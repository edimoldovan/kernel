# branches.py BIN BASE TARGET...: branch instructions whose target is one of the hex TARGETs
import sys, capstone
data = open(sys.argv[1], 'rb').read(); base = int(sys.argv[2], 16); tgt = {int(t, 16) for t in sys.argv[3:]}
md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM); md.skipdata = True
for x in md.disasm(data, base):
    if x.mnemonic.startswith(('b', 'cb', 'tb')) and '#' in x.op_str:
        try: t = int(x.op_str.split('#')[-1], 16) & 0xffffffffffffffff
        except ValueError: continue
        if t in tgt: print(f"{x.address - base:06x}: {x.mnemonic} {x.op_str}")
