# checks.py BIN BASE LO HI: loads at a displacement in [LO, HI) followed within 4 instructions by a
# compare or test of the loaded register against an immediate. Prints "address +disp cmp imm".
import sys, capstone
from capstone.arm64 import *
data = open(sys.argv[1], 'rb').read(); base = int(sys.argv[2], 16); lo, hi = int(sys.argv[3], 16), int(sys.argv[4], 16)
md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM); md.detail = True; md.skipdata = True
ins = [x for x in md.disasm(data, base)]
for i, x in enumerate(ins):
    if x.mnemonic not in ('ldr', 'ldrb', 'ldrh', 'ldrsw'): continue
    ops = x.operands
    if len(ops) != 2 or ops[1].type != ARM64_OP_MEM or not lo <= ops[1].mem.disp < hi: continue
    r = md.reg_name(ops[0].reg)[1:]
    for y in ins[i + 1:i + 5]:
        if y.mnemonic in ('.byte',): break
        if y.mnemonic in ('cmp', 'tst', 'cbz', 'cbnz', 'tbz', 'tbnz', 'ccmp') and y.op_str.split(',')[0][1:] == r:
            print(f"{x.address - base:06x} +{ops[1].mem.disp:#06x} {y.mnemonic} {y.op_str}")
            break
