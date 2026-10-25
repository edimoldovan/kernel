#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

import struct
from construct import *
from copy import deepcopy
from m1n1.setup import *
from m1n1.shell import run_shell
from m1n1.fw.asc import StandardASC, ASCDummyEndpoint
import time
from m1n1.fw.asc.base import ASCBaseEndpoint, msg_handler
from m1n1.utils import *
from m1n1.hw.dart import DART

def round_up(x, y): return ((x + (y - 1)) & (-y))
def round_down(x, y): return (x - (x % y))

AOPBootargsItem = Struct(
    "key" / PaddedString(4, "utf8"),
    "size" / Int32ul,
)

class AOPBootargs:
    def __init__(self, bytes_):
        self.blob = bytearray(bytes_)
        self.index = self.build_index(self.blob)

    def build_index(self, blob):
        off = 0
        fields = []
        while off < len(blob):
            item = AOPBootargsItem.parse(blob[off:off+AOPBootargsItem.sizeof()])
            off += AOPBootargsItem.sizeof()
            fields.append((item.key, (off, item.size)))
            off += item.size
        if off > len(blob):
            raise ValueError('blob overran during parsing')
        return dict(fields)

    def items(self):
        for key, span in self.index.items():
            off, length = span
            yield key, self.blob[off:off + length]

    def __getitem__(self, key):
        off, length = self.index[key]
        return bytes(self.blob[off:off + length])

    def __setitem__(self, key, value):
        off, length = self.index[key]
        if type(value) is int:
            value = int.to_bytes(value, length, byteorder='little')
        elif type(value) is str:
            value = value.encode('ascii')
        if len(value) > length:
            raise ValueError(f'field {key:s} overflown')
        self.blob[off:off + length] = value

    def update(self, keyvals):
        for key, val in keyvals.items():
            self[key] = val

    def keys(self):
        return self.index.keys()

    def dump(self, logger):
        for key, val in self.items():
            logger(f"{key:4s} = {val}")

    def dump_diff(self, other, logger):
        assert self.index == other.index
        for key in self.keys():
            if self[key] != other[key]:
                logger(f"\t{key:4s} = {self[key]} -> {other[key]}")

    def to_bytes(self):
        return bytes(self.blob)

class AOPBase:
    def __init__(self, u):
        self.u = u
        self.nub_base = u.adt["/arm-io/pmp0/iop-pmp0-nub"].region_base

    @property
    def _bootargs_span(self):
        """
        [cpu1] MMIO: R.4   0x24ac0022c (aop[2], offset 0x22c) = 0xaffd8 // offset
        [cpu1] MMIO: R.4   0x24ac00230 (aop[2], offset 0x230) = 0x2ae // size
        [cpu1] MMIO: R.4   0x24ac00234 (aop[2], offset 0x234) = 0x82000 // va? low
        [cpu1] MMIO: R.4   0x24ac00238 (aop[2], offset 0x238) = 0x0 // va? high
        [cpu1] MMIO: R.4   0x24ac0023c (aop[2], offset 0x23c) = 0x4ac82000 // phys low
        [cpu1] MMIO: R.4   0x24ac00240 (aop[2], offset 0x240) = 0x2 // phys high
        [cpu1] MMIO: W.4   0x24acaffd8 (aop[2], offset 0xaffd8) = 0x53544b47 // start of bootargs
        [cpu1] MMIO: W.4   0x24acaffdc (aop[2], offset 0xaffdc) = 0x8
        [cpu1] MMIO: W.4   0x24acaffe0 (aop[2], offset 0xaffe0) = 0x73eed2a3
        ...
        [cpu1] MMIO: W.4   0x24acb0280 (aop[2], offset 0xb0280) = 0x10000
        [cpu1] MMIO: W.4   0x24acb0284 (aop[2], offset 0xb0284) = 0x0 // end of bootargs
        """
        offset = self.u.proxy.read32(self.nub_base + 0x22c) # 0x224 in 12.3
        size = self.u.proxy.read32(self.nub_base + 0x230) # 0x228 in 12.3
        return (self.nub_base + offset, size)

    def read_bootargs(self):
        addr, size = self._bootargs_span
        blob = self.u.proxy.iface.readmem(addr, size)
        return AOPBootargs(blob)

    def write_bootargs(self, args):
        base, _ = self._bootargs_span
        self.u.proxy.iface.writemem(base, args.to_bytes())

    def update_bootargs(self, keyval, logger=print):
        args = self.read_bootargs()
        old = deepcopy(args)
        args.update(keyval)
        self.write_bootargs(args)
        old.dump_diff(args, logger)

class PMPMessage(Register64):
    TYPE = 56, 48

class PMPMessage_IOVATableAck(PMPMessage):
    TYPE = 56, 48, Constant(0x11)
    IOVA = 47, 0

class PMPMessage_Malloc(PMPMessage):
    TYPE = 56, 48, Constant(0x12)
    SIZE = 23, 0

class PMPMessage_MallocAck(PMPMessage):
    TYPE = 56, 48, Constant(0x13)
    IOVA = 47, 0

class PMPMessage_Free(PMPMessage):
    TYPE = 56, 48, Constant(0x14)
    IOVA = 47, 0

class PMPMessage_SetBuf(PMPMessage):
    TYPE = 56, 48, Constant(0x30)
    IOVA = 47, 0

class PMPMessage_Advertise(PMPMessage):
    TYPE = 56, 48, Constant(0x32)
    IOVA = 47, 0

class PMPMessage_AdvertiseAck(PMPMessage):
    TYPE = 56, 48, Constant(0x33)
    INDEX = 47, 32
    SIZE = 31, 0

class PMPMessage_SetVal(PMPMessage):
    TYPE = 56, 48, Constant(0x34)
    INDEX = 15, 0

class PMPMessage_SetValAck(PMPMessage):
    TYPE = 56, 48, Constant(0x35)
    SIZE = 31, 0

class PMPEp(ASCBaseEndpoint):
    def handle_msg(self, msg0, msg1):
        try:
            return super().handle_msg(msg0, msg1)
        except Exception as e:
            self.log(f"unhandled message {msg0:#x}: {e.__class__.__name__}: {e}")
            return True
    BASE_MESSAGE = PMPMessage
    SHORT = "pmp"
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.allocs = {}
        self.ioregs = []

    @msg_handler(0x10, PMPMessage)
    def GetIOVATable(self, msg):
        self.log(f'IovaTable: {msg}')
        table_dva = 0
        if u.adt['/arm-io'].compatible[0][:11] in ['arm-io,t600']:
            table, table_dva = self.asc.ioalloc(512)
            self.asc.iowrite(table_dva, b'\0' * 512)
            pio_base = u.adt["/arm-io/dart-pmp0"].pio_vm_base
            granularity = u.adt["/arm-io/dart-pmp0"].pio_granularity
            i = 0
            for j in range(4, len(u.adt["/arm-io/pmp0"].reg)):
                host_addr, size = u.adt["/arm-io/pmp0"].get_reg(j)
                self.asc.dart.iomap_at(0, pio_base, host_addr, size)
                self.asc.dart.invalidate_streams(1)
                self.asc.iowrite(table_dva + 24 * i, struct.pack("<QQQ", host_addr, pio_base, size))
                pio_base += granularity
                i += 1
        self.send(PMPMessage_IOVATableAck(IOVA=table_dva))
    @msg_handler(0x12, PMPMessage_Malloc)
    def Malloc(self, msg):
        self.log(f'Malloc: {msg}')
        addr, dva = self.asc.ioalloc(msg.SIZE)
        self.allocs[dva] = addr
        self.send(PMPMessage_MallocAck(IOVA=dva))
    @msg_handler(0x14, PMPMessage_Free)
    def Free(self, msg):
        self.log(f'Free: {msg}')
        #i dont think we can
        self.send(PMPMessage(TYPE=0x15))

    @msg_handler(0x30, PMPMessage_SetBuf)
    def SetBuf(self, msg):
        self.log(f'SetBuf: {msg}')
        self.buf_ptr, _ = struct.unpack("<QQ", self.asc.ioread(msg.IOVA, 16))
        self.send(PMPMessage(TYPE=0x31))
    @msg_handler(0x32, PMPMessage_Advertise)
    def Advertise(self, msg):
        self.log(f'Advertise: {msg}')
        data = self.asc.ioread(msg.IOVA, 0x50)
        name = data[:0x30] + b'\0'
        size = struct.unpack("<I", data[0x40:0x44])[0]
        if size == 0:
            i = 0
            print(name)
            while name[i] != 0:
                i += 1
            name = name[:i].decode()
            self.log(f"Reading prop {name}")
            data = getattr(u.adt["/arm-io/pmp0/iop-pmp0-nub"], name, None)
            if data is None:
                self.log("unknown property")
                size = 0
            else:
                if isinstance(data, int):
                    if data > 0xffffffff:
                        data = struct.pack("<Q", data)
                    else:
                        data = struct.pack("<I", data)
                self.asc.iowrite(self.buf_ptr, data)
                size = len(data)
        self.ioregs.append(size)
        index = len(self.ioregs)
        self.send(PMPMessage_AdvertiseAck(INDEX=index, SIZE=size))

    @msg_handler(0x34, PMPMessage_SetVal)
    def SetVal(self, msg):
        self.log(f'SetVal: {msg}')
        self.send(PMPMessage_SetValAck(SIZE=self.ioregs[msg.INDEX]))


class BufMessage(Register64):
    TYPE = 63, 52
    SIZE = 51, 44
    DVA  = 43, 0

class BufferServingEp(ASCBaseEndpoint):
    """System endpoint 7 (TraceKit): serve its buffer request, log anything else."""
    BASE_MESSAGE = BufMessage
    SHORT = "ep7"
    def handle_msg(self, msg0, msg1):
        msg = BufMessage(msg0)
        if msg.TYPE == 1 and msg.DVA == 0:
            size = msg.SIZE * 0x4000
            paddr, dva = self.asc.ioalloc(size)
            self.log(f"buffer request {size:#x} -> {paddr:#x} / {dva:#x}")
            self.send(BufMessage(TYPE=1, SIZE=msg.SIZE, DVA=dva))
            return True
        self.log(f"ignored message {msg0:#x}")
        return True

class PMPClient(StandardASC, AOPBase):
    ENDPOINTS = {0x7: BufferServingEp, 0x20: PMPEp}  # this firmware also advertises system endpoint 7
    def __init__(self, u, dev_path, dart=None):
        node = u.adt[dev_path]
        asc_base = node.get_reg(0)[0]
        AOPBase.__init__(self, u)
        super().__init__(u, asc_base, dart)
        self.dart = dart

pmp_ptd_range = u.adt['/arm-io/pmp0/iop-pmp0-nub'].ptd_range
pmp_ptd_range_map = {}
for i in range(len(pmp_ptd_range) // 32):
    id, offset, _, name = struct.unpack('<II8s16s', pmp_ptd_range[i*32:(i+1)*32])
    pmp_ptd_range_map[name.strip(b'\x00')] = offset

pmp_bits = {dev.name: dev.id1 - 1 for dev in u.adt['/arm-io/pmgr'].devices if dev.id1 != 0}

if u.adt['/arm-io'].compatible[0].startswith('arm-io,t8103'):
    print("you have a pmp v1, this script is for v2 only")
    exit(1)
elif u.adt['/arm-io'].compatible[0].startswith(('arm-io,t600', 'arm-io,t602')):
    pmp_base = 0x28e3c0000
    enable_devices=['DISP0_FE']
elif u.adt['/arm-io'].compatible[0].startswith('arm-io,t8112'):
    pmp_base = 0x23b3c0000
    enable_devices=['DISP0_SYS']
elif u.adt['/arm-io'].compatible[0].startswith('arm-io,t8122'):
    # untested
    pmp_base = 0x2d03c0000
    enable_devices=['DISP_SYS']
elif u.adt['/arm-io'].compatible[0].startswith('arm-io,t6030'):
    # untested
    pmp_base = 0x3503c0000
    enable_devices=['DISP_SYS']
elif u.adt['/arm-io'].compatible[0].startswith(('arm-io,t6031', 'arm-io,t6034')):
    pmp_base = 0x2903c0000
    enable_devices=['DISP_FE']
elif u.adt['/arm-io'].compatible[0].startswith('arm-io,t6050'):
    pmp_base = 0x284240000
    enable_devices=['DISP_FE']
else:
    print("FIXME: put the correct pmgr PMS_PTS_PTD reg for your machine here")
    exit(1)

tgt_wr = pmp_ptd_range_map[b'SOC-DEV-PS-REQ'] * 8 + 0x10000
enable_val = 0
for dev in enable_devices:
    enable_val |= 1 << pmp_bits[dev]
p.write64(pmp_base + tgt_wr, enable_val)


dart = DART.from_adt(u, "/arm-io/dart-pmp0")
dart.verbose = 1
dart.initialize()

pmp = PMPClient(u, "/arm-io/pmp0", dart)
pmp.verbose = 4
_orig_start_ep = pmp.start_ep
def _start_ep_skip7(epno):
    if epno == 0x7:
        print("not starting system endpoint 0x7 (Linux does not start it either)")
        return
    return _orig_start_ep(epno)
pmp.start_ep = _start_ep_skip7
if pmp.is_running():
    print("PMP already running (from an earlier attempt): halting it so it boots fresh")
    pmp.shutdown(); time.sleep(0.5)
    print("  CPU_STATUS now", hex(p.read32(pmp.asc.base + 0x48)) if hasattr(pmp.asc, 'base') else '?')
bootargs = {
    'BDID'[::-1]: u.adt['/chosen'].board_id,
    'DVID'[::-1]: u.adt['/chosen'].dram_vendor_id,
}
if u.adt['/arm-io'].compatible[0][:11] in ['arm-io,t600']:
    bootargs['DCAP'[::-1]] = u.adt["/arm-io/pmp0/iop-pmp0-nub"].dram_capacity
pmp.update_bootargs(bootargs)
_path = p.malloc(64); iface.writemem(_path, b"/arm-io/dart-pmp0\0")
print("dapf_init(dart-pmp0, 1) ->", p.request(p.P_DAPF_INIT, _path, 1))

pmp.boot()
pmp.mgmt.start()
try:
    pmp.mgmt.wait_boot(30)
    print("power states reached")
except Exception as e:
    print("power-state wait:", e.__class__.__name__, "- iop", hex(pmp.mgmt.iop_power_state), "ap", hex(pmp.mgmt.ap_power_state), "- continuing")
pmp.start_ep(0x20)
pmp.work_for(15)
print("after ep 0x20: iop", hex(pmp.mgmt.iop_power_state), "ap", hex(pmp.mgmt.ap_power_state))

print("PHASE A done: PMP booted and served; status/ack words:")
req = pmp_base + pmp_ptd_range_map[b'SOC-DEV-PS-REQ'] * 8 + 0x10000
ack = pmp_base + pmp_ptd_range_map[b'SOC-DEV-PS-ACK'] * 8 + 0x10000
print(f"  REQ@{req:#x} = {p.read64(req):#x}  ACK@{ack:#x} = {p.read64(ack):#x}")
cpu_devs = ['MCPM0', 'MCPM1', 'PCPM']
cpu_mask = 0
for dev in cpu_devs:
    cpu_mask |= 1 << pmp_bits[dev]
print(f"PHASE B: requesting power for {cpu_devs} -> bits {cpu_mask:#x}")
p.write64(req, enable_val | cpu_mask)
pmp.work_for(3)
print(f"  REQ = {p.read64(req):#x}  ACK = {p.read64(ack):#x}")
print("PHASE C: smp_start_secondaries on the resident loader")
try:
    p.smp_start_secondaries()
except Exception as e:
    print("  smp_start_secondaries raised", e.__class__.__name__)
alive = [i for i in range(18) if p.smp_is_alive(i)]
print("ALIVE:", alive)
sb = 0x280600000 + 0x88000
print("start block +0/+4:", hex(p.read32(sb)), hex(p.read32(sb + 4)))
pmp.work_for(2)
print("DONE")
