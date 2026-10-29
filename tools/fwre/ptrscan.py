import sys
data=open(sys.argv[1],'rb').read()
base=0x284500000
targets={int(t,16) for t in sys.argv[2:]}
# also local form: local = 0x10000000 | (ap-base)
locals_={ (0x10000000 | (t-base)) for t in targets }
allt=targets|locals_
import struct
for i in range(0,len(data)-8):
    v=struct.unpack_from('<Q',data,i)[0]
    if v in allt:
        print(f"file {i:#08x} (ap {base+i:#x}) -> {v:#x}")
