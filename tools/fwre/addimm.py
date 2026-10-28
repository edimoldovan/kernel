# addimm.py BIN BASE LO HI: "add Xd, Xn, #imm" (shifted immediates resolved) with imm in [LO, HI),
# and immediates moved into a register (mov) in that range; counts per value
import sys, capstone, collections
from capstone.arm64 import *
data = open(sys.argv[1], 'rb').read(); base = int(sys.argv[2], 16); lo, hi = int(sys.argv[3], 16), int(sys.argv[4], 16)
md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM); md.detail = True; md.skipdata = True
c = collections.defaultdict(list)
for x in md.disasm(data, base):
    if x.mnemonic not in ('add', 'mov', 'sub'): continue
    ops = x.operands
    if x.mnemonic == 'add' and len(ops) == 3 and ops[2].type == ARM64_OP_IMM:
        v = ops[2].imm << (ops[2].shift.value if ops[2].shift.type else 0)
    elif x.mnemonic == 'mov' and len(ops) == 2 and ops[1].type == ARM64_OP_IMM:
        v = ops[1].imm
    else: continue
    if lo <= v < hi: c[v].append(x.address - base)
for v in sorted(c): print(f"{v:#06x} x{len(c[v])} first at {c[v][0]:#x}")
