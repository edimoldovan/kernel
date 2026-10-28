# disas.py BIN BASE START END: disassemble BIN (loaded at hex BASE) from offset START to END
import sys, capstone
data = open(sys.argv[1], 'rb').read(); base = int(sys.argv[2], 16); a, b = int(sys.argv[3], 16), int(sys.argv[4], 16)
md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM); md.skipdata = True
for x in md.disasm(data[a:b], base + a):
    print(f"{x.address - base:06x}: {x.mnemonic:8s} {x.op_str}")
