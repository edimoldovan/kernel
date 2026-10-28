import struct,sys,re
from capstone import *
data=open(sys.argv[1],'rb').read()
def lcs(off):
    nc=struct.unpack_from('<I',data,off+16)[0]; o=off+32; out=[]
    for _ in range(nc):
        c,s=struct.unpack_from('<II',data,o); out.append((c,o,s)); o+=s
    return out
segs=[]
for c,o,s in lcs(0):
    if c==0x80000035:
        va,fo,st,_=struct.unpack_from('<QQII',data,o+8)
        for c2,o2,s2 in lcs(fo):
            if c2==0x19:
                sva,vs,sfo,fs=struct.unpack_from('<QQQQ',data,o2+24); segs.append((sva,vs,sfo))
def v2f(a):
    for sva,vs,sfo in segs:
        if sva<=a<sva+vs: return sfo+(a-sva)
fr=v2f(0xfffffe000cb3fa50); IDXBASE={}
for i in range(44): IDXBASE[i]=struct.unpack_from('<Q',data,fr+i*0x80)[0]&0x3fffffffff
CORE=0x2a3000000
def regname(field,off):
    if (field-0x210)%0x20==0:
        idx=(field-0x210)//0x20
        if 0<=idx<44:
            ab=IDXBASE[idx]+off
            return f"idx{idx} "+(f"core+{ab-CORE:#x}" if CORE<=ab<CORE+0x4c000 else f"{ab:#x}")
    return f"field{field:#x}+{off:#x}"
READ=0xfffffe0009f4063c; WRITE=0xfffffe0009f4064c
md=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN)
LDR=re.compile(r'^(\w+), \[(\w+)(?:, #(0x[0-9a-f]+))?\]$')
def decode(name,a,b):
    code=data[v2f(a):v2f(a)+(b-a)]
    this={'x0'}; fof={}; aof={}; vex={}; out=[]
    for ins in md.disasm(code,a):
        m,ops=ins.mnemonic,ins.op_str; p=ops.split(', ')
        mm=LDR.match(ops)
        if m=='mov' and len(p)==2:
            for d in (fof,aof,vex):
                if p[1] in d: d[p[0]]=d[p[1]]
            if p[1] in this: this.add(p[0])
        elif m=='ldr' and mm:
            dst,bas,off=mm.group(1),mm.group(2),mm.group(3)
            if bas in this and off is not None:
                fof[dst]=int(off,16); aof.pop(dst,None)
        elif m=='add' and len(p)==3 and p[1] in fof and p[2].startswith('#'):
            aof[p[0]]=(fof[p[1]],int(p[2][1:],0))
        elif m in('orr','bic','and','eor') and len(p)>=3:
            o={'orr':'|','bic':'&~','and':'&','eor':'^'}[m]
            x=re.search(r'#(0x[0-9a-f]+|\d+)',p[-1])
            if x: vex[p[0]]=f"{o}{int(x.group(1),0):#x}"
        elif m=='bl':
            t=int(ops.lstrip('#'),16)
            if t==WRITE and 'x0' in aof:
                f,o=aof['x0']; v=vex.get('w1') or vex.get('x1') or ''
                out.append(f"  W {regname(f,o):26} {v}")
            vex.clear()
    print(f"\n### {name}  ({len(out)} writes)")
    print("\n".join(out[:50]))
decode("cmn_init",0xfffffe0009f08874,0xfffffe0009f08e00)
decode("phy_init_partA",0xfffffe0009f227c4,0xfffffe0009f227f8)
decode("rx_powerup",0xfffffe0009f2cbd4,0xfffffe0009f2ce00)
decode("tx_powerup",0xfffffe0009f2c270,0xfffffe0009f2c480)
decode("pwr_up_rxa",0xfffffe0009f007ac,0xfffffe0009f00900)
