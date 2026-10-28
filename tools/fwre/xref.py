# xref.py TEXT_BIN BASE TARGET...: code addresses whose ADRP+ADD (or ADRP+LDR) pair forms a target address
import sys, capstone
from capstone.arm64 import *
data = open(sys.argv[1], 'rb').read(); base = int(sys.argv[2], 16)
targets = {int(t, 16) for t in sys.argv[3:]}
md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM); md.detail = True; md.skipdata = True
ins = list(md.disasm(data, base))
for i, x in enumerate(ins):
    if x.mnemonic != 'adrp': continue
    reg = x.operands[0].reg; page = x.operands[1].imm
    for y in ins[i+1:i+8]:
        if y.mnemonic in ('add', 'ldr', 'ldrb', 'ldrh') and len(y.operands) >= 2:
            ops = y.operands
            if y.mnemonic == 'add' and ops[1].type == ARM64_OP_REG and ops[1].reg == reg and ops[2].type == ARM64_OP_IMM:
                a = (page + ops[2].imm) & 0xffffffffffffffff
            elif y.mnemonic != 'add' and ops[1].type == ARM64_OP_MEM and ops[1].mem.base == reg:
                a = (page + ops[1].mem.disp) & 0xffffffffffffffff
            else: continue
            if a in targets: print(f"{x.address:#x}: -> {a:#x}")
