# reads.py BIN BASE START END REG TAG [PTR_OFF TAG2 ...]: memory accesses relative to a structure
# pointer in a function. REG holds the TAG structure's address at START; a load of a pointer from
# TAG + PTR_OFF gives the TAG2 structure. Straight-line tracking (no control flow): a register
# keeps its (structure, offset) until it is written with anything else. Prints
# "TAG +offset size load|store address".
import sys, capstone
from capstone.arm64 import *

data = open(sys.argv[1], 'rb').read(); base = int(sys.argv[2], 16)
start, end = int(sys.argv[3], 16), int(sys.argv[4], 16)
md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM); md.detail = True; md.skipdata = True
reg0, tag0 = sys.argv[5], sys.argv[6]
ptrs = {(tag0, int(sys.argv[i], 16)): sys.argv[i + 1] for i in range(7, len(sys.argv), 2)}

def canon(r):  # w8 and x8 are one register
    n = md.reg_name(r)
    return 'x' + n[1:] if n[0] in 'wx' and n[1:].isdigit() else n

track = {reg0: (tag0, 0)}; consts = {}
SIZES = {'ldrb': 1, 'ldrsb': 1, 'strb': 1, 'ldrh': 2, 'ldrsh': 2, 'strh': 2, 'ldrsw': 4}
out = set()
for x in md.disasm(data[start:end], base + start):
    if x.mnemonic == '.byte':
        continue
    ops = x.operands
    m = x.mnemonic
    mem = [o for o in ops if o.type == ARM64_OP_MEM]
    if mem and (m.startswith(('ld', 'st'))):
        o = mem[0]; b = canon(o.mem.base) if o.mem.base else None
        regs = [o2 for o2 in ops if o2.type == ARM64_OP_REG]
        width = SIZES.get(m)
        if width is None:
            n = md.reg_name(regs[0].reg) if regs else 'x'
            width = 16 if n[0] == 'q' else 8 if n[0] in 'xd' else 4
        if m in ('ldp', 'stp', 'ldnp', 'stnp'):
            width *= 2
        if b in track and o.mem.index == 0:
            tag, off = track[b]
            a = off + o.mem.disp
            out.add((tag, a, width, 'load' if m.startswith('ld') else 'store', x.address - base))
            if m == 'ldr' and regs and (tag, a) in ptrs:
                track[canon(regs[0].reg)] = (ptrs[(tag, a)], 0)
                continue
        if m.startswith('ld'):
            for r in regs:
                track.pop(canon(r.reg), None); consts.pop(canon(r.reg), None)
        continue
    if not ops or ops[0].type != ARM64_OP_REG:
        continue
    d = canon(ops[0].reg)
    if m == 'mov' and len(ops) == 2 and ops[1].type == ARM64_OP_IMM:
        track.pop(d, None); consts[d] = ops[1].imm; continue
    if m == 'mov' and len(ops) == 2 and ops[1].type == ARM64_OP_REG and canon(ops[1].reg) in track:
        track[d] = track[canon(ops[1].reg)]; consts.pop(d, None); continue
    if m == 'add' and len(ops) == 3 and ops[1].type == ARM64_OP_REG and canon(ops[1].reg) in track:
        tag, off = track[canon(ops[1].reg)]
        if ops[2].type == ARM64_OP_IMM:
            sh = ops[2].shift.value if ops[2].shift.type else 0
            track[d] = (tag, off + (ops[2].imm << sh)); consts.pop(d, None); continue
        if ops[2].type == ARM64_OP_REG and canon(ops[2].reg) in consts:
            track[d] = (tag, off + consts[canon(ops[2].reg)]); consts.pop(d, None); continue
    track.pop(d, None); consts.pop(d, None)

for tag, a, w, kind, at in sorted(out):
    print(f"{tag} +{a:#06x} {w} {kind} {at:#x}")
