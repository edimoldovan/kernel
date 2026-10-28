import struct,sys,re
from capstone import *
data=open(sys.argv[1],'rb').read()
def lcs(off):
    nc=struct.unpack_from('<I',data,off+16)[0]; o=off+32; out=[]
    for _ in range(nc):
        c,s=struct.unpack_from('<II',data,o); out.append((c,o,s)); o+=s
    return out
segs=[]; syms={}
for c,o,s in lcs(0):
    if c==0x80000035:
        va,fo,stro,_=struct.unpack_from('<QQII',data,o+8)
        for c2,o2,s2 in lcs(fo):
            if c2==0x19:
                sva,vs,sfo,fs=struct.unpack_from('<QQQQ',data,o2+24); segs.append((sva,vs,sfo))
            elif c2==0x2:
                so,ns,stro2,ss=struct.unpack_from('<IIII',data,o2+8)
                for i in range(ns):
                    strx,nt,nse,nd,nv=struct.unpack_from('<IBBHQ',data,so+16*i)
                    if nv: syms.setdefault(nv,data[stro2+strx:data.index(b'\0',stro2+strx)].decode('latin1'))
def v2f(a):
    for sva,vs,sfo in segs:
        if sva<=a<sva+vs: return sfo+(a-sva)
def cstr(a):
    f=v2f(a)
    if not f: return None
    e=data.find(b'\0',f,f+80); s=data[f:e]
    return s.decode('latin1') if s and all(32<=c<127 for c in s) else None
symaddrs=sorted(syms)
import bisect
def func_of(a):
    i=bisect.bisect_right(symaddrs,a)-1
    if i>=0:
        nm=syms[symaddrs[i]]
        m=re.search(r'AppleT6050TypeCPhy(\d+)([A-Za-z0-9_]+)',nm)
        if m: return m.group(2)[:int(m.group(1))]
    return '?'
md=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN)
start=0xfffffe0009f00000; end=0xfffffe0009f40000
code=data[v2f(start):v2f(start)+(end-start)]
regs={}; last_tun=None; last_idx=None; aa0=False
seen=[]
for ins in md.disasm(code,start):
    m,ops=ins.mnemonic,ins.op_str
    if m=='adrp':
        r,imm=ops.split(', '); regs[r]=int(imm.lstrip('#'),16)
    elif m=='add':
        p=ops.split(', ')
        if len(p)==3 and p[1] in regs and p[2].startswith('#'):
            a=regs[p[1]]+int(p[2][1:],0); regs[p[0]]=a
            s=cstr(a)
            if s and s.startswith('tunable_'): last_tun=s
    elif m in('mov','movz') and re.match(r'w1, #',ops):
        last_idx=int(ops.split('#')[1],0)
    elif m=='ldr' and '#0xaa0]' in ops:
        aa0=True
    elif m in('blraa','blr') and aa0:
        seen.append((ins.address,func_of(ins.address),last_tun,last_idx)); aa0=False
    elif m=='bl' and ops.lstrip('#').startswith('0xfffffe0009f3c2e0'):
        seen.append((ins.address,func_of(ins.address),last_tun,last_idx))
print("addr            function                 tunable                        idx")
for a,fn,t,i in seen:
    print(f"{a:x}  {fn:22}  {str(t):30}  {i}")
