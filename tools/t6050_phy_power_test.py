# T6050 port 1 (left-front): Type-C PHY power-up versus the USB2 host, over the stage 1 proxy.
# usage (from forks/omacom-m1n1, M1N1DEVICE=/dev/serial/by-id/...g7cde*-if00):
#   PYTHONPATH=proxyclient .venv/bin/python t6050_phy_power_test.py STEP...
# Steps run in order: read flip flipnophy flipu3s diag pd pd:<domain> cio small big unclamp
# apb phyrst pwrread coreread core:LO-HI cmn tunables lanes:normal|swapped pipeusb3
# sswatch warm wmap:LO-HI set:OFF=VAL,... sweep sweep2 sweep3 wake pllstart pllstart2 muxmap hcreset sweep4 u3loop u3doc dwc3rst pwrdump pclk:SEL pclkvar probe dump:NAME[:SKIP] retune:fabric|axi2af|cfg glue reboot. The watchdog (90 s) is armed for the whole run.
import sys, time
from m1n1.setup import p, u  # noqa: F401
from m1n1.proxy import GUARD

WDT = 0x28836c000                  # COUNT +0x10, ALARM +0x14, CTL +0x1c
import os
WDT_ALARM = 24000000 * int(os.environ.get("WDT_SECS", "90"))

PMGR = 0                           # domain entries below are absolute
PMGR0, PMGR2 = 0x280600000, 0x288300000
DOMAINS = [("atc1_common", PMGR0 + 0x210), ("auss", PMGR0 + 0x248), ("atc1_cio", PMGR0 + 0x290),
           ("atc1_cio_usb", PMGR0 + 0x358), ("atc1_cio_auss", PMGR0 + 0x360)]
WATCH = [("atc1_pcie", PMGR0 + 0x298), ("atc1_cio_pcie", PMGR0 + 0x350),
         ("atc1_usb_aon", PMGR2 + 0x160), ("atc1_usb", PMGR2 + 0x168),
         ("atc1_phymxwrap", PMGR2 + 0x170)]

# port 1 (left-front): ADT usb-drd1, atc-phy1 reg[0], pipe handler, reg[2], reg[39]
DRD, USB2PHY, PIPE = 0x2aa280000, 0x2aaa90000, 0x2aaa84000
CORE, PWR = 0x2ab000000, 0x2ab200000
PCTL = 0x2aaa80000                 # usb-drd1 reg[5], AUSBC_PWR_CTRL (TXDETRX lock)
MXW = 0x2ab140000                  # atc-phy1 reg[38], MxWrap of the PHY CPU (mailbox at +0x8000)
PORTS_PROXY_CHECK = {1: DRD, 2: 0x382280000}

def pet():
    p.write32(WDT + 0x10, 0)

def arm():
    p.write32(WDT + 0x14, WDT_ALARM); p.write32(WDT + 0x10, 0); p.write32(WDT + 0x1c, 4)

def disarm():
    p.write32(WDT + 0x1c, 0)

def rd(a):
    b = p.get_exc_count(); v = p.read32(a)
    return v, p.get_exc_count() != b

def wr(a, v):
    b = p.get_exc_count(); p.write32(a, v)
    return p.get_exc_count() != b

def rmw(a, clear, set_):
    v, f = rd(a)
    if f:
        return True
    return wr(a, (v & ~clear) | set_)

def poll(a, mask, want, ms):
    end = time.time() + ms / 1000
    while True:
        v, f = rd(a)
        if f:
            return "fault", v
        if (v & mask) == want:
            return "ok", v
        if time.time() > end:
            return "timeout", v
        time.sleep(0.001)

def phy_cpu_wake(secs=3):
    # AppleT6050TypeCPhy::runFirmware: MxWrap IDLE_CTRL (+0x40) bit 0, then power the PHY CPU up.
    # iBoot pre-loads its RTKit firmware; wake it as m1n1 StandardASC.start() does (SetIOPPower
    # 0x220, then HELLO / EPMAP), with the MxWrap run bit (+0x28 bit 4) in place of ASC +0x44.
    # AppleMxWrap::_runCPU writes +0x28 = 0x10 (no RMW); AppleMxWrapACIO::_runCPU uses the
    # function-reconfig_req_interrupt platform function instead, absent on acio-phy-cpu1.
    # +0x44 bit 1 = idle (_isIdle). The firmware initialises the mailboxes itself.
    from m1n1.fw.asc import StandardASC
    from m1n1.fw.asc.mgmt import Mgmt_SetIOPPower, Mgmt_Ping
    rmw(MXW + 0x40, 0, 1)
    time.sleep(0.01)
    cpu = StandardASC(u, MXW)
    cpu.verbose = 3
    cpu.allow_phys = True
    print(f"  PHY CPU before: ctrl {rd(MXW + 0x28)[0]:#x} stat {rd(MXW + 0x44)[0]:#x} "
          f"outbox {rd(MXW + 0x8114)[0]:#x}", flush=True)
    # Run 41: after +0x28 = 0x10 the firmware sends HELLO (v12) and answers Ping. Boot it the
    # m1n1 way: HELLO -> ack, EPMAP -> ack + start system endpoints + AP power on, then IOP power.
    wr(MXW + 0x28, 0x10)
    def pump(cond, t):
        end = time.time() + t
        while not cond() and time.time() < end:
            if cpu.work():
                time.sleep(0.002)
        return cond()
    try:
        ap = pump(lambda: cpu.mgmt.ap_power_state == 0x20, secs)
        cpu.mgmt.send(Mgmt_SetIOPPower(STATE=0x220))
        iop = pump(lambda: cpu.mgmt.iop_power_state == 0x20, secs)
        res = f"ap {'on' if ap else 'TIMEOUT'} iop {'on' if iop else 'TIMEOUT'}"
    except Exception as e:
        res = f"{type(e).__name__}: {e}"
    pump(lambda: False, 1)                      # print whatever else it sends
    print(f"  PHY CPU boot: {res}; eps {[hex(e) for e in cpu.eps]} iop {cpu.mgmt.iop_power_state:#x} "
          f"ap {cpu.mgmt.ap_power_state:#x} stat {rd(MXW + 0x44)[0]:#x}", flush=True)
    return cpu

def is_proxy(drd):
    gctl, _ = rd(drd + 0xc110); dsts, _ = rd(drd + 0xc70c)
    return (gctl >> 12) & 3 == 2 and dsts & 7 == 0 and (dsts >> 18) & 0xf == 0

def step_read():
    for name, off in DOMAINS + WATCH:
        v, f = rd(PMGR + off)
        print(f"  {name:14} {PMGR + off:#x} = {v:#010x} target {v & 0xf:#x} actual {(v >> 4) & 0xf:#x}{' FAULT' if f else ''}")

def flip_once(u3_suspend=False, phy=True):
    if phy:
        wr(USB2PHY + 0x08, 0x01c1000f)
        wr(USB2PHY + 0x04, 0x3)
        rmw(USB2PHY + 0x04, 0x1, 0)
        rmw(USB2PHY + 0x04, 0x2, 0)
        wr(USB2PHY + 0x1c, 0x008c0813)
        wr(USB2PHY + 0x00, 2)
        wr(PIPE + 0x0c, 0x22)
        wr(PIPE + 0x1c, 1)
        wr(PIPE + 0x20, 0x9332)
    wr(USB2PHY + 0x08, 0x01c1000f | (7 << 12))
    rmw(DRD + 0xc704, 1 << 31, 0)
    poll(DRD + 0xc70c, 1 << 22, 1 << 22, 10)
    rmw(DRD + 0xc110, 0, 1 << 11)
    time.sleep(0.01)
    rmw(DRD + 0xc110, (3 << 12) | (1 << 11), 1 << 12)
    time.sleep(0.01)
    rmw(PIPE + 0x04, (1 << 1) | (1 << 2), 0)
    rmw(PIPE + 0x00, 0, (1 << 0) | (1 << 2))
    rmw(DRD + 0xc200, 1 << 6, 0)
    rmw(DRD + 0xc2c0, 1 << 17, (1 << 17) if u3_suspend else 0)

def step_flip(u3_suspend=False, phy=True):
    """The t6050-usb2 driver's phy_init, then the xHCI reset as xhci-plat does it."""
    for attempt, ms in enumerate((50, 100, 100), 1):
        flip_once(u3_suspend, phy)
        st, v = poll(DRD + 0x420, 1, 1, ms)
        print(f"  flip {attempt}: PORTSC {v:#010x} CCS {st}")
        if st == "ok":
            break
    gctl, _ = rd(DRD + 0xc110)
    print(f"  GCTL {gctl:#010x} prtcap {(gctl >> 12) & 3}")
    op = DRD + 0x20
    cmd, _ = rd(op)
    wr(op, cmd | 2)
    st, v = poll(op, 2, 0, 1000)
    print(f"  HCRST self-clear: {st} USBCMD {v:#010x}")
    st, v = poll(op + 4, 1 << 11, 0, 1000)
    print(f"  CNR clear: {st} USBSTS {v:#010x}")
    for i in range(2):
        a = op + 0x400 + 0x10 * i
        v, _ = rd(a)
        wr(a, v | (1 << 9))
        time.sleep(0.05)
        v2, f = rd(a)
        print(f"  PORTSC[{i}] {v:#010x} -> after PP {v2:#010x} CCS {v2 & 1} PED {(v2 >> 1) & 1} speed {(v2 >> 10) & 0xf}{' FAULT' if f else ''}")

def step_cio():
    """CIO power-on in the open-source atc.c order: PMGR domains parent first, then
    the PHY power control (sleep small, sleep big, clamp off, APB reset, PHY reset)."""
    for name, off in DOMAINS:
        a = PMGR + off
        v, f = rd(a)
        if (v >> 4) & 0xf == 0xf:
            print(f"  {name:14} already on ({v:#010x})")
            continue
        wr(a, (v & ~(0xf | 0x300)) | 0xf)
        st, v = poll(a, 0xf0, 0xf0, 100)
        print(f"  {name:14} on: {st} ({v:#010x})")
        if st != "ok":
            return False
        pet()
    for label, off in (("ctrl", 0), ("stat", 4), ("misc", 8)):
        v, f = rd(PWR + off)
        print(f"  power {label} {PWR + off:#x} = {v:#010x}{' FAULT' if f else ''}")
        if f:
            return False
    for bit, name in ((0, "sleep small"), (1, "sleep big")):
        rmw(PWR, 0, 1 << bit)
        st, v = poll(PWR + 4, 1 << bit, 1 << bit, 100)
        print(f"  set {name}: stat {st} ({v:#010x})")
    rmw(PWR, 1 << 2, 0)
    rmw(PWR, 0, 1 << 3)
    if not os.environ.get("NORESET"):    # macOS releases PHY reset (bit 4) later, in partC
        rmw(PWR, 0, 1 << 4)
    for label, off in (("ctrl", 0), ("stat", 4), ("misc", 8)):
        v, f = rd(PWR + off)
        print(f"  power {label} = {v:#010x}{' FAULT' if f else ''}")
    v, f = rd(CORE + 0xc)
    print(f"  core+0xc = {v:#010x}{' FAULT' if f else ''}")
    return True

steps = sys.argv[1:] or ["read"]
if is_proxy(DRD) and not os.environ.get("FORCE_PORT1"):
    sys.exit("port 1 looks like the proxy port (device, HS, U0); refusing")
if not is_proxy(PORTS_PROXY_CHECK[2]):
    print("note: port 2 does not look like the proxy port")
p.set_exc_guard(GUARD.RETURN | GUARD.SILENT)
arm()
try:
    for s in steps:
        print(f"== {s}")
        pet()
        if s == "read":
            step_read()
        elif s == "flip":
            step_flip()
        elif s == "cio":
            if not step_cio():
                print("  stopped: cio power-on did not complete")
                break
        elif s == "pd":
            for name, off in DOMAINS:
                a = PMGR + off
                v, f = rd(a)
                wr(a, (v & ~(0xf | 0x300)) | 0xf)
                st, v = poll(a, 0xf0, 0xf0, 100)
                print(f"  {name:14} on: {st} ({v:#010x})")
        elif s == "pwrread":
            for label, off in (("ctrl", 0), ("stat", 4), ("misc", 8)):
                v, f = rd(PWR + off)
                print(f"  power {label} {PWR + off:#x} = {v:#010x}{' FAULT' if f else ''}")
        elif s == "coreread":
            for off in (0x0, 0x4, 0x8, 0xc, 0xa00, 0x804):
                v, f = rd(CORE + off)
                print(f"  core+{off:#x} = {v:#010x}{' FAULT' if f else ''}")
        elif s.startswith("core:"):
            lo, hi = (int(x, 16) for x in s[5:].split("-"))
            for off in range(lo, hi, 0x10):
                vals = []
                for o in range(off, min(off + 0x10, hi), 4):
                    v, f = rd(CORE + o)
                    vals.append(f"{v:#010x}{'!' if f else ''}")
                print(f"  core+{off:#06x}: " + " ".join(vals))
        elif s == "tunables":
            # values from the ADT node; window = ADT reg index (fabric 40, axi2af 41,
            # common cfg 43, AUS40CMN 5, AUSPLL 8, as in t6050-usb3-usb4-bringup.md)
            import struct as _st
            node = u.adt["/arm-io/atc-phy1"]
            for prop, idx in (("tunable_ATC_COMMON_CFG", 43), ("tunable_ATC_FABRIC", 40),
                              ("tunable_ATC0AXI2AF", 41), ("tunable_AUS40CMN_SHM", 5),
                              ("tunable_AUSPLL_CORE", 8)):
                raw = bytes(node._properties[prop])
                base = node.get_reg(idx)[0]
                faults = 0
                for j in range(0, len(raw), 12):
                    ofs, mask, val = _st.unpack_from("<III", raw, j)
                    faults += rmw(base + (ofs & 0xffffff), mask, val & mask)
                print(f"  {prop:24} reg[{idx}] {base:#x}: {len(raw) // 12} entries, {faults} faults")
                pet()
        elif s.startswith("lanes:"):
            swapped = s == "lanes:swapped"
            lane = (0x2 | 0x2 << 3 | 0x1 << 6 | 0x1 << 9) if swapped else (0x1 | 0x1 << 3 | 0x2 << 6 | 0x2 << 9)
            xbar = (0x11 if swapped else 0x10) | (0x008 << 5)
            rmw(CORE + 0x60, 0xfff, lane)
            rmw(CORE + 0x64, 0x3ffff, xbar)
            rmw(PWR + 0x8, 1 << 2, (1 << 2) if swapped else 0)
            for o in (0x60, 0x64):
                v, f = rd(CORE + o)
                print(f"  core+{o:#x} = {v:#010x}{' FAULT' if f else ''}")
            v, _ = rd(PWR + 0x8)
            print(f"  power misc = {v:#010x}")
        elif s == "pipeusb3":
            rmw(PIPE + 0x4, (1 << 1) | (1 << 2), 0)
            rmw(PIPE + 0x0, 0, (1 << 0) | (1 << 2))
            rmw(PIPE + 0x10, 0, 1)
            st, v = poll(PIPE + 0x14, 1, 1, 10)
            print(f"  lock ack: {st} ({v:#x})")
            # MUX_CTRL fields on T6050: clock [6:4], data [1:0] (bits 3:2 not implemented)
            rmw(PIPE + 0xc, 0x70, 0)
            time.sleep(0.001)
            rmw(PIPE + 0xc, 0x3, 0)
            time.sleep(0.001)
            rmw(PIPE + 0xc, 0x70, 1 << 4)
            time.sleep(0.001)
            rmw(PIPE + 0x20, (0xf | (1 << 12)), 3)
            rmw(PIPE + 0x0, (1 << 0) | (1 << 2), 0)
            rmw(PIPE + 0x10, 1, 0)
            st, v = poll(PIPE + 0x14, 1, 0, 10)
            print(f"  unlock ack: {st} ({v:#x})")
            for o in (0x0, 0x4, 0xc, 0x10, 0x14, 0x20):
                v, _ = rd(PIPE + o)
                print(f"  pipe+{o:#x} = {v:#010x}")
        elif s in ("sswatch", "warm"):
            a = DRD + 0x20 + 0x410
            if s == "warm":
                v, _ = rd(a)
                wr(a, (v & (0x40003c09 | 0x0e00c3e0)) | (1 << 31))
            last = None
            end = time.time() + 1.5
            while time.time() < end:
                v, f = rd(a)
                if v != last:
                    print(f"  PORTSC[1] {v:#010x} CCS {v & 1} PED {(v >> 1) & 1} PLS {(v >> 5) & 0xf} speed {(v >> 10) & 0xf}{' FAULT' if f else ''}")
                    last = v
                time.sleep(0.005)
        elif s.startswith("wmap:"):
            # per register: write all-ones, read; write zero, read; restore. Prints
            # as it goes so a hang shows the last register touched.
            lo, hi = (int(x, 16) for x in s[5:].split("-"))
            for n, off in enumerate(range(lo, hi, 4)):
                if n % 16 == 0:
                    pet()
                a = CORE + off
                v, f = rd(a)
                if f:
                    print(f"  core+{off:#05x} read FAULT", flush=True)
                    continue
                wr(a, 0xffffffff); r1, _ = rd(a)
                wr(a, 0); r0, _ = rd(a)
                wr(a, v); r2, _ = rd(a)
                w = r1 & ~r0
                if w or r2 != v or r1 != v or r0 != v:
                    print(f"  core+{off:#05x} orig {v:#010x} ones {r1:#010x} zero {r0:#010x} "
                          f"writable {w:#010x}{'  RESTORE-MISMATCH ' + hex(r2) if r2 != v else ''}", flush=True)
        elif s.startswith("set:"):
            # set:OFF=VAL[,OFF=VAL...] plain writes to core offsets, read back
            for item in s[4:].split(","):
                o, v = (int(x, 16) for x in item.split("="))
                f = wr(CORE + o, v)
                r, _ = rd(CORE + o)
                print(f"  core+{o:#05x} <- {v:#010x} reads {r:#010x}{' FAULT' if f else ''}")
            v, _ = rd(CORE + 0x7044)
            print(f"  core+0x7044 = {v:#010x} (bit 3 {(v >> 3) & 1})")
        elif s == "sweep":
            # lane-mode candidate 0x170 x crossbar candidates; oracles: PLL lock
            # (core+0x7044 bit 3), pipe mux accepting the USB3 clock, USB3 port PLS.
            port = DRD + 0x20 + 0x410
            lanes = [0x9249, 0x0, 0x36db, 0x12489, 0x12492]
            xbars = [(0x38, v) for v in (0x110, 0x10, 0xa, 0x111)] + \
                    [(0x13c, v) for v in (0x110, 0x10, 0xa, 0x111)] + \
                    [(0x64, v) for v in range(16)]
            lane0, _ = rd(CORE + 0x170)
            hits = 0
            for lane in lanes:
                for xo, xv in xbars:
                    pet()
                    x0, _ = rd(CORE + xo)
                    wr(CORE + 0x170, lane); wr(CORE + xo, xv)
                    time.sleep(0.003)
                    pll, _ = rd(CORE + 0x7044)
                    pll2, _ = rd(CORE + 0x7034)
                    wr(PIPE + 0xc, 0x02); wr(PIPE + 0xc, 0x00); wr(PIPE + 0xc, 0x08)
                    time.sleep(0.001)
                    mux, _ = rd(PIPE + 0xc)
                    pls = (rd(port)[0] >> 5) & 0xf
                    wr(PIPE + 0xc, 0x00); wr(PIPE + 0xc, 0x02); wr(PIPE + 0xc, 0x22)
                    wr(CORE + xo, x0)
                    if pll or (pll2 & ~8) or mux & 0x38 or pls != 5:
                        hits += 1
                        print(f"  HIT lane {lane:#07x} core+{xo:#x}={xv:#x}: 7044 {pll:#x} 7034 {pll2:#x} mux {mux:#x} PLS {pls}", flush=True)
            wr(CORE + 0x170, lane0)
            mux, _ = rd(PIPE + 0xc)
            print(f"  {len(lanes) * len(xbars)} combinations, {hits} hits; mux back to {mux:#x}")
        elif s == "pllstart":
            # atc.c AUSPLL start (t8122 TOP 0x2000 / CORE 0x2200) at T6050 TOP 0x3000 / CORE 0x3200
            regs = (0x3000, 0x3080, 0x3084, 0x3088, 0x3200, 0x3208, 0x3214, 0x3220, 0x3224, 0x7044)
            def dump(tag):
                vals = []
                for o in regs:
                    v, f = rd(CORE + o)
                    vals.append(f"{o:#x}={v:#x}{'!' if f else ''}")
                print(f"  {tag}: " + " ".join(vals), flush=True)
            dump("before")
            rmw(CORE + 0x3214, 0, 1)
            rmw(CORE + 0x3200, 0, (1 << 2) | (1 << 4) | (1 << 6))
            v, _ = rd(CORE + 0x3000)
            wr(CORE + 0x3000, (v & ~(0x1ffffff << 3)) | 1 | (1 << 28))
            st, v = poll(CORE + 0x3000, 2, 2, 10)
            print(f"  APB command 0 ack: {st} ({v:#x})")
            rmw(CORE + 0x3000, 1, 0)
            st, v = poll(CORE + 0x7044, 8, 8, 10)
            print(f"  AUSPLL lock: {st} ({v:#x})")
            dump("after")
        elif s == "wake":
            # atcphy_wake_common_t8122 with ACIOPHY_CFG0 at core+0xc (t8122 +0x8);
            # bias at +0xa00, RCAL done at +0x804 bit 0; left awake
            for clr, set_ in ((0, 1 << 2), (0, 1 << 3), (0, 1 << 0), (0, 1 << 1), (1 << 4, 0), (0, 1 << 5)):
                rmw(CORE + 0xc, clr, set_)
                time.sleep(0.0001)
            rmw(CORE + 0xa00, 0, 1 << 1)
            st, v = poll(CORE + 0x804, 1, 1, 10)
            c, _ = rd(CORE + 0xc)
            print(f"  CFG0 core+0xc = {c:#010x}; RCAL done: {st} ({v:#x})")
        elif s == "pllstart2":
            # t8122 tunnel PLL start (atc_t8122_tunnel_start) with the AUSPLL at +0x1000;
            # frequency descriptor left at its current value
            def show(tag):
                vals = []
                for o in (0x3000, 0x3200, 0x3218, 0x3234, 0x7034, 0x7044):
                    v, _ = rd(CORE + o)
                    vals.append(f"{o:#x}={v:#x}")
                print(f"  {tag}: " + " ".join(vals), flush=True)
            show("before")
            rmw(CORE + 0x3234, 0x3, 0)
            rmw(CORE + 0x3218, 0, 1)
            rmw(CORE + 0x3200, 0, (1 << 3) | (1 << 11))
            rmw(CORE + 0x3000, ~0xe0000006 & 0xffffffff, 0x10000001)
            st, v = poll(CORE + 0x3000, 2, 2, 10)
            print(f"  APB 0x10000001 ack: {st} ({v:#x})")
            st1, v1 = poll(CORE + 0x7034, 8, 8, 10)
            v2, _ = rd(CORE + 0x7044)
            print(f"  lock 0x7034: {st1} ({v1:#x}); 0x7044 = {v2:#x}")
            rmw(CORE + 0x3000, ~0xe0000006 & 0xffffffff, 0x10010000)
            st, v = poll(CORE + 0x3000, 2, 0, 10)
            print(f"  APB 0x10010000 ack low: {st} ({v:#x})")
            show("after")
        elif s == "muxmap":
            # which PIPEHANDLER_MUX_CTRL values stick; restored to dummy (0x22) after
            res = {}
            for v in range(0x80):
                wr(PIPE + 0xc, v)
                time.sleep(0.0005)
                r, _ = rd(PIPE + 0xc)
                res[v] = r
            wr(PIPE + 0xc, 0x02); wr(PIPE + 0xc, 0x22)
            ok = [f"{v:#x}" for v, r in res.items() if r == v]
            print(f"  values that stick: {' '.join(ok)}")
            other = [f"{v:#x}->{r:#x}" for v, r in res.items() if r != v]
            print(f"  others: {' '.join(other[:40])}{' ...' if len(other) > 40 else ''}")
            r, _ = rd(PIPE + 0xc)
            print(f"  mux now {r:#x}")
        elif s == "hcreset":
            # dwc3 core soft reset + host + xHCI reset; pipe handler left as it is
            rmw(DRD + 0xc110, 0, 1 << 11)
            time.sleep(0.01)
            rmw(DRD + 0xc110, (3 << 12) | (1 << 11), 1 << 12)
            time.sleep(0.01)
            rmw(DRD + 0xc200, 1 << 6, 0)
            rmw(DRD + 0xc2c0, 1 << 17, 0)
            op = DRD + 0x20
            cmd, _ = rd(op)
            wr(op, cmd | 2)
            st, v = poll(op, 2, 0, 1000)
            st2, v2 = poll(op + 4, 1 << 11, 0, 1000)
            print(f"  HCRST {st}, CNR clear {st2} (USBSTS {v2:#x})")
            for i in range(2):
                a = op + 0x400 + 0x10 * i
                v, _ = rd(a)
                wr(a, (v & (0x40003c09 | 0x0e00c3e0)) | (1 << 9))
            last = None
            end = time.time() + 2
            while time.time() < end:
                v, _ = rd(op + 0x410)
                if v != last:
                    print(f"  PORTSC[1] {v:#010x} CCS {v & 1} PLS {(v >> 5) & 0xf} speed {(v >> 10) & 0xf}")
                    last = v
                time.sleep(0.005)
            g, _ = rd(DRD + 0xc118)
            print(f"  GSTS {g:#x}")
        elif s == "sweep2":
            # PIPE on USB3 (mux 0x10): does the controller reset complete (CNR clears)
            # for a lane-mode / crossbar candidate? Candidates restored after each try.
            op = DRD + 0x20
            lanes = [0x9249, 0x0, 0x36db, 0x12489, 0x12492]
            xbars = [(0x38, v) for v in (0x110, 0x10, 0xa, 0x111)] + \
                    [(0x13c, v) for v in (0x110, 0x10, 0xa, 0x111)] + \
                    [(0x64, v) for v in range(16)]
            lane0, _ = rd(CORE + 0x170)
            hits = 0
            for lane in lanes:
                for xo, xv in xbars:
                    pet()
                    x0, _ = rd(CORE + xo)
                    wr(CORE + 0x170, lane); wr(CORE + xo, xv)
                    time.sleep(0.003)
                    rmw(DRD + 0xc110, 0, 1 << 11)
                    time.sleep(0.002)
                    rmw(DRD + 0xc110, (3 << 12) | (1 << 11), 1 << 12)
                    time.sleep(0.002)
                    cmd, _ = rd(op)
                    wr(op, cmd | 2)
                    poll(op, 2, 0, 50)
                    st, v = poll(op + 4, 1 << 11, 0, 50)
                    pls = (rd(op + 0x410)[0] >> 5) & 0xf
                    wr(CORE + xo, x0)
                    if st == "ok" or pls != 5:
                        hits += 1
                        print(f"  HIT lane {lane:#07x} core+{xo:#x}={xv:#x}: CNR {st} USBSTS {v:#x} PLS {pls}", flush=True)
            wr(CORE + 0x170, lane0)
            print(f"  {len(lanes) * len(xbars)} combinations, {hits} hits")
        elif s == "sweep3":
            # lane power candidates core+0x10 (RX, 9 bits) and core+0x120 (TX) with
            # lane-mode candidate 0x170; oracle: controller reset completes on USB3 PIPE
            op = DRD + 0x20
            r10, _ = rd(CORE + 0x10); r120, _ = rd(CORE + 0x120); r170, _ = rd(CORE + 0x170)
            v10s = [0x1ff, 0x1, 0x3, 0x7, 0xf, 0x3f, 0xff, 0x155, 0xaa]
            v120s = [r120, 0x1fffffff, 0x0, r120 | 0xfff, r120 & ~0xfff]
            hits = 0
            for v170 in (r170, 0x9249):
                for v10 in v10s:
                    for v120 in v120s:
                        pet()
                        wr(CORE + 0x170, v170); wr(CORE + 0x10, v10); wr(CORE + 0x120, v120)
                        time.sleep(0.003)
                        rmw(DRD + 0xc110, 0, 1 << 11)
                        time.sleep(0.002)
                        rmw(DRD + 0xc110, (3 << 12) | (1 << 11), 1 << 12)
                        time.sleep(0.002)
                        cmd, _ = rd(op)
                        wr(op, cmd | 2)
                        poll(op, 2, 0, 50)
                        st, v = poll(op + 4, 1 << 11, 0, 50)
                        pls = (rd(op + 0x410)[0] >> 5) & 0xf
                        if st == "ok" or pls != 5:
                            hits += 1
                            print(f"  HIT 0x170={v170:#x} 0x10={v10:#x} 0x120={v120:#x}: CNR {st} USBSTS {v:#x} PLS {pls}", flush=True)
            wr(CORE + 0x170, r170); wr(CORE + 0x10, r10); wr(CORE + 0x120, r120)
            print(f"  {2 * len(v10s) * len(v120s)} combinations, {hits} hits")
        elif s == "sweep4":
            # lane mode at core+0x6c (bits [4:2], [7:5]) x orientation, PCS enable at
            # core+0x29004 bit 0, PIPE on USB3; oracle: controller reset completes
            op = DRD + 0x20
            l0, _ = rd(CORE + 0x6c); p0, _ = rd(CORE + 0x29004); m0, _ = rd(PWR + 0x8)
            print(f"  start: core+0x6c {l0:#x} core+0x29004 {p0:#x} misc {m0:#x}")
            hits = 0
            for a in (2, 7):
                for b in (2, 7):
                    for swap in (0, 1):
                        pet()
                        wr(CORE + 0x6c, (l0 & ~0xfc) | (a << 2) | (b << 5))
                        rmw(PWR + 0x8, 1 << 2, swap << 2)
                        rmw(CORE + 0x29004, 0, 1)
                        rmw(PIPE + 0xc, 0x70, 0); rmw(PIPE + 0xc, 0x3, 0); rmw(PIPE + 0xc, 0x70, 1 << 4)
                        time.sleep(0.003)
                        rmw(DRD + 0xc110, 0, 1 << 11)
                        time.sleep(0.002)
                        rmw(DRD + 0xc110, (3 << 12) | (1 << 11), 1 << 12)
                        time.sleep(0.002)
                        cmd, _ = rd(op)
                        wr(op, cmd | 2)
                        poll(op, 2, 0, 50)
                        st, v = poll(op + 4, 1 << 11, 0, 100)
                        pv, _ = rd(op + 0x410)
                        r6c, _ = rd(CORE + 0x6c); r29, _ = rd(CORE + 0x29004)
                        print(f"  [4:2]={a} [7:5]={b} swap {swap}: 0x6c {r6c:#x} 0x29004 {r29:#x} CNR {st} "
                              f"USBSTS {v:#x} PORTSC[1] {pv:#x} PLS {(pv >> 5) & 0xf}", flush=True)
                        if st == "ok":
                            hits += 1
                        wr(CORE + 0x29004, p0)
                        wr(CORE + 0x6c, l0)
                        wr(PWR + 0x8, m0)
            print(f"  8 combinations, {hits} with CNR clear")
        elif s == "u3loop":
            # dwc3-apple order: PHY ready -> dwc3 core reset + glue CIO regs + host +
            # SUSPHY on -> PIPE to USB3 under the lock -> xHCI reset; per lane mode/orientation
            op = DRD + 0x20
            l0, _ = rd(CORE + 0x6c); p0, _ = rd(CORE + 0x29004); m0, _ = rd(PWR + 0x8)
            for a in (2, 7):
                for b in (2, 7):
                    for swap in (0, 1):
                        pet()
                        wr(CORE + 0x6c, (l0 & ~0xfc) | (a << 2) | (b << 5))
                        rmw(PWR + 0x8, 1 << 2, swap << 2)
                        rmw(CORE + 0x29004, 0, 1)
                        # dwc3 core soft reset, glue CIO settings, host, SUSPHY on
                        rmw(DRD + 0xc704, 1 << 31, 0)
                        rmw(DRD + 0xc110, 0, 1 << 11)
                        time.sleep(0.005)
                        rmw(DRD + 0xc110, (3 << 12) | (1 << 11), 1 << 12)
                        time.sleep(0.005)
                        wr(DRD + 0xcd38, 0x0f800f80)
                        wr(DRD + 0xcd3c, 0x0fc00fc0)
                        rmw(DRD + 0xcd40, 0xffffff, (0x14 << 16) | (0xa << 8) | 0x10)
                        rmw(DRD + 0xc200, 0, 1 << 6)
                        rmw(DRD + 0xc2c0, 0, 1 << 17)
                        # PIPE to USB3 under the lock (T6050 mux: clock [6:4], data [1:0])
                        rmw(PIPE + 0x4, (1 << 1) | (1 << 2), 0)
                        rmw(PIPE + 0x0, 0, (1 << 0) | (1 << 2))
                        rmw(PIPE + 0x10, 0, 1)
                        lk, _ = poll(PIPE + 0x14, 1, 1, 10)
                        rmw(PIPE + 0xc, 0x70, 0); rmw(PIPE + 0xc, 0x3, 0); rmw(PIPE + 0xc, 0x70, 1 << 4)
                        rmw(PIPE + 0x20, (0xf | (1 << 12)), 3)
                        rmw(PIPE + 0x0, (1 << 0) | (1 << 2), 0)
                        rmw(PIPE + 0x10, 1, 0)
                        ul, _ = poll(PIPE + 0x14, 1, 0, 10)
                        mux, _ = rd(PIPE + 0xc)
                        # xHCI reset and port power
                        cmd, _ = rd(op)
                        wr(op, cmd | 2)
                        poll(op, 2, 0, 100)
                        cnr, sts = poll(op + 4, 1 << 11, 0, 200)
                        for i in range(2):
                            pa = op + 0x400 + 0x10 * i
                            v, _ = rd(pa)
                            wr(pa, (v & (0x40003c09 | 0x0e00c3e0)) | (1 << 9))
                        time.sleep(0.3)
                        p0r, _ = rd(op + 0x400); p1r, _ = rd(op + 0x410)
                        print(f"  [4:2]={a} [7:5]={b} swap {swap}: lock {lk} unlock {ul} mux {mux:#x} "
                              f"CNR {cnr} ({sts:#x}) PORTSC0 {p0r:#x} PORTSC1 {p1r:#x} "
                              f"PLS1 {(p1r >> 5) & 0xf} speed1 {(p1r >> 10) & 0xf}", flush=True)
                        # PIPE back to the dummy backend for the next try
                        rmw(PIPE + 0x4, (1 << 1) | (1 << 2), 0)
                        rmw(PIPE + 0x0, 0, (1 << 0) | (1 << 2))
                        rmw(PIPE + 0xc, 0x70, 0); rmw(PIPE + 0xc, 0x3, 2); rmw(PIPE + 0xc, 0x70, 2 << 4)
                        rmw(PIPE + 0x20, 0xf, 2); rmw(PIPE + 0x20, 0, 1 << 12)
                        wr(CORE + 0x29004, p0); wr(CORE + 0x6c, l0); wr(PWR + 0x8, m0)
        elif s == "dwc3rst":
            # atcphy_dwc3_reset_assert/deassert: pipe handler AON_GEN RESET_N bit 0, FORCE_CLAMP_EN bit 4
            rmw(PIPE + 0x1c, 1, 1 << 4)
            time.sleep(0.01)
            v, _ = rd(PIPE + 0x1c)
            print(f"  asserted: AON_GEN {v:#x}")
            rmw(PIPE + 0x1c, 1 << 4, 1)
            time.sleep(0.01)
            v, _ = rd(PIPE + 0x1c)
            print(f"  deasserted: AON_GEN {v:#x}")
        elif s == "pwrdump":
            vals = []
            for o in range(0, 0x30, 4):
                v, f = rd(PWR + o)
                vals.append(f"+{o:#x}={v:#x}{'!' if f else ''}")
            print("  power block " + " ".join(vals))
        elif s.startswith("pclk:"):
            # pipe-clock switch (bring-up doc step 7): PWR+0x14 clear 0x2039, set sel << 3; status PWR+0x18
            sel = int(s[5:], 16)
            v14, _ = rd(PWR + 0x14); v18, _ = rd(PWR + 0x18)
            wr(PWR + 0x14, (v14 & ~0x2039) | (sel << 3))
            seen = [v18]
            end = time.time() + 0.05
            while time.time() < end:
                v, _ = rd(PWR + 0x18)
                if v != seen[-1]:
                    seen.append(v)
                time.sleep(0.0005)
            n14, _ = rd(PWR + 0x14)
            print(f"  pclk sel {sel:#x}: +0x14 {v14:#x} -> {n14:#x}; +0x18 " + " -> ".join(hex(x) for x in seen))
        elif s == "u3doc":
            # bring-up doc order (steps 4, 7, 8, 9) after USB2 + CIO + PLL are up
            op = DRD + 0x20
            l0, _ = rd(CORE + 0x6c); p0, _ = rd(CORE + 0x29004); m0, _ = rd(PWR + 0x8)
            c14, _ = rd(PWR + 0x14)
            for sel in (2, 7):
                for a, b in ((2, 2), (2, 7), (7, 2), (7, 7)):
                    for swap in (0, 1):
                        pet()
                        wr(CORE + 0x6c, (l0 & ~0xfc) | (a << 2) | (b << 5))
                        rmw(PWR + 0x8, 1 << 2, swap << 2)
                        wr(PWR + 0x14, (c14 & ~0x2039) | (sel << 3))
                        time.sleep(0.002)
                        s18, _ = rd(PWR + 0x18)
                        rmw(CORE + 0x29004, 0, 1)
                        r110, _ = rd(CORE + 0x29110)
                        rmw(DRD + 0xc704, 1 << 31, 0)
                        rmw(DRD + 0xc110, 0, 1 << 11)
                        time.sleep(0.005)
                        rmw(DRD + 0xc110, (3 << 12) | (1 << 11), 1 << 12)
                        time.sleep(0.005)
                        wr(DRD + 0xcd38, 0x0f800f80)
                        wr(DRD + 0xcd3c, 0x0fc00fc0)
                        rmw(DRD + 0xcd40, 0xffffff, (0x14 << 16) | (0xa << 8) | 0x10)
                        rmw(DRD + 0xc200, 0, 1 << 6)
                        rmw(DRD + 0xc2c0, 0, 1 << 17)
                        rmw(PIPE + 0x4, (1 << 1) | (1 << 2), 0)
                        rmw(PIPE + 0x0, 0, (1 << 0) | (1 << 2))
                        rmw(PIPE + 0x10, 0, 1)
                        lk, _ = poll(PIPE + 0x14, 1, 1, 10)
                        rmw(PIPE + 0xc, 0x70, 0); rmw(PIPE + 0xc, 0x3, 0); rmw(PIPE + 0xc, 0x70, 1 << 4)
                        rmw(PIPE + 0x20, (0xf | (1 << 12)), 3)
                        rmw(PIPE + 0x0, (1 << 0) | (1 << 2), 0)
                        rmw(PIPE + 0x10, 1, 0)
                        poll(PIPE + 0x14, 1, 0, 10)
                        cmd, _ = rd(op)
                        wr(op, cmd | 2)
                        poll(op, 2, 0, 100)
                        cnr, sts = poll(op + 4, 1 << 11, 0, 200)
                        for i in range(2):
                            pa = op + 0x400 + 0x10 * i
                            v, _ = rd(pa)
                            wr(pa, (v & (0x40003c09 | 0x0e00c3e0)) | (1 << 9))
                        time.sleep(0.3)
                        q0, _ = rd(op + 0x400); q1, _ = rd(op + 0x410)
                        print(f"  sel {sel} [4:2]={a} [7:5]={b} swap {swap}: +0x18 {s18:#x} 0x29110 {r110:#x} "
                              f"lock {lk} CNR {cnr} ({sts:#x}) PORTSC0 {q0:#x} PORTSC1 {q1:#x} "
                              f"PLS1 {(q1 >> 5) & 0xf} speed1 {(q1 >> 10) & 0xf}", flush=True)
                        rmw(PIPE + 0x4, (1 << 1) | (1 << 2), 0)
                        rmw(PIPE + 0x0, 0, (1 << 0) | (1 << 2))
                        rmw(PIPE + 0xc, 0x70, 0); rmw(PIPE + 0xc, 0x3, 2); rmw(PIPE + 0xc, 0x70, 2 << 4)
                        rmw(PIPE + 0x20, 0xf, 2); rmw(PIPE + 0x20, 0, 1 << 12)
                        wr(CORE + 0x29004, p0); wr(CORE + 0x6c, l0); wr(PWR + 0x8, m0)
                        wr(PWR + 0x14, c14)
        elif s == "tunx":
            # the every-mode per-lane tunables + LIOA the `tunables` step omits:
            # RX_EQ_DFLT (reg 18/27) and RX_CFG_TX_OF_RXCLK (reg 20/29, lane TX
            # clocking), plus ATC0AXI2AF_LIOA (reg 42). CIO-off.
            import struct as _st
            node = u.adt["/arm-io/atc-phy1"]
            for prop, idx in (("tunable_ATC0AXI2AF_LIOA", 42),
                              ("tunable_LN0_RX_EQ_DFLT", 18), ("tunable_LN0_RX_CFG_TX_OF_RXCLK", 20),
                              ("tunable_LN1_RX_EQ_DFLT", 27), ("tunable_LN1_RX_CFG_TX_OF_RXCLK", 29)):
                raw = bytes(node._properties[prop])
                base = node.get_reg(idx)[0]
                faults = 0
                for j in range(0, len(raw), 12):
                    ofs, mask, val = _st.unpack_from("<III", raw, j)
                    faults += rmw(base + (ofs & 0xffffff), mask, val & mask)
                print(f"  {prop:30} reg[{idx}] {base:#x}: {len(raw) // 12} entries, {faults} faults")
                pet()
        elif s == "u3clean":
            # CIO-OFF USB3 attempt: lane mode core+0x6c [4:2]/[7:5], PIPE to USB3,
            # dwc3 reset + HCRST. Never touches core+0x29000 (PCS, CIO domain) or
            # PWR+0x14 (DP switch). Oracle: does CNR clear with the mux on USB3?
            op = DRD + 0x20
            l0, _ = rd(CORE + 0x6c); m0, _ = rd(PWR + 0x8)
            bsid, _ = rd(DRD + 0xc120); bcap, _ = rd(DRD + 0x0)
            bgsts, _ = rd(DRD + 0xc118); bsts, _ = rd(op + 4)
            print(f"  start: core+0x6c {l0:#x} misc {m0:#x}")
            print(f"  baseline(dummy): SID {bsid:#x} CAPLEN {bcap:#x} GSTS {bgsts:#x} "
                  f"USBSTS {bsts:#x} HCH {bsts & 1}")
            hits = 0
            for a in (2, 7):
                for b in (2,):
                    for swap in (0,):
                        pet()
                        wr(CORE + 0x6c, (l0 & ~0xfc) | (a << 2) | (b << 5))
                        rmw(PWR + 0x8, 1 << 2, swap << 2)
                        time.sleep(0.003)
                        rmw(DRD + 0xc704, 1 << 31, 0)
                        rmw(DRD + 0xc110, 0, 1 << 11)
                        time.sleep(0.005)
                        rmw(DRD + 0xc110, (3 << 12) | (1 << 11), 1 << 12)
                        time.sleep(0.005)
                        wr(DRD + 0xcd38, 0x0f800f80)
                        wr(DRD + 0xcd3c, 0x0fc00fc0)
                        rmw(DRD + 0xcd40, 0xffffff, (0x14 << 16) | (0xa << 8) | 0x10)
                        rmw(DRD + 0xc200, 0, 1 << 6)
                        rmw(DRD + 0xc2c0, 0, 1 << 17)
                        rmw(PIPE + 0x4, (1 << 1) | (1 << 2), 0)
                        rmw(PIPE + 0x0, 0, (1 << 0) | (1 << 2))
                        rmw(PIPE + 0x10, 0, 1)
                        lk, _ = poll(PIPE + 0x14, 1, 1, 10)
                        rmw(PIPE + 0xc, 0x70, 0); rmw(PIPE + 0xc, 0x3, 0); rmw(PIPE + 0xc, 0x70, 1 << 4)
                        rmw(PIPE + 0x0, (1 << 0) | (1 << 2), 0)
                        rmw(PIPE + 0x10, 1, 0)
                        poll(PIPE + 0x14, 1, 0, 10)
                        cmd, _ = rd(op)
                        wr(op, cmd | 2)
                        poll(op, 2, 0, 100)
                        cnr, sts = poll(op + 4, 1 << 11, 0, 200)
                        sid, _ = rd(DRD + 0xc120); cap, _ = rd(DRD + 0x0)
                        gsts, _ = rd(DRD + 0xc118)
                        pv, _ = rd(op + 0x410)
                        mux, _ = rd(PIPE + 0xc)
                        alive = sid != 0 and cap != 0
                        print(f"  [4:2]={a} [7:5]={b} swap {swap}: lock {lk} mux {mux:#x} "
                              f"SID {sid:#x} CAPLEN {cap:#x} GSTS {gsts:#x} USBSTS {sts:#x} "
                              f"HCH {sts & 1} CNRpoll {cnr} {'ALIVE' if alive else 'DEAD(zero-read)'} "
                              f"PORTSC1 {pv:#x}", flush=True)
                        if cnr == "ok":
                            hits += 1
                        rmw(PIPE + 0x4, (1 << 1) | (1 << 2), 0)
                        rmw(PIPE + 0x0, 0, (1 << 0) | (1 << 2))
                        rmw(PIPE + 0xc, 0x70, 0); rmw(PIPE + 0xc, 0x3, 2); rmw(PIPE + 0xc, 0x70, 2 << 4)
                        wr(CORE + 0x6c, l0); wr(PWR + 0x8, m0)
            print(f"  8 combinations, {hits} with CNR clear")
        elif s == "u3stage":
            # one orientation, staged: read SID (drd+0xc120) / CAPLEN (drd+0x0) /
            # GSTS / USBSTS after each write group to find which one kills the
            # dwc3 register interface. SID+CAPLEN non-zero == controller alive.
            op = DRD + 0x20
            def chk(tag):
                sid, _ = rd(DRD + 0xc120); cap, _ = rd(DRD + 0x0)
                gsts, _ = rd(DRD + 0xc118); sts, _ = rd(op + 4)
                print(f"  {tag:20} SID {sid:#010x} CAP {cap:#010x} GSTS {gsts:#x} "
                      f"USBSTS {sts:#x} {'ALIVE' if sid and cap else 'DEAD'}", flush=True)
            l0, _ = rd(CORE + 0x6c); m0, _ = rd(PWR + 0x8)
            chk("baseline")
            wr(CORE + 0x6c, (l0 & ~0xfc) | (2 << 2) | (2 << 5)); rmw(PWR + 0x8, 1 << 2, 0)
            chk("lane mode")
            rmw(DRD + 0xc704, 1 << 31, 0)
            rmw(DRD + 0xc110, 0, 1 << 11); time.sleep(0.005)
            rmw(DRD + 0xc110, (3 << 12) | (1 << 11), 1 << 12); time.sleep(0.005)
            chk("core reset+host")
            wr(DRD + 0xcd38, 0x0f800f80); wr(DRD + 0xcd3c, 0x0fc00fc0)
            rmw(DRD + 0xcd40, 0xffffff, (0x14 << 16) | (0xa << 8) | 0x10)
            chk("glue writes")
            rmw(DRD + 0xc200, 0, 1 << 6); rmw(DRD + 0xc2c0, 0, 1 << 17)
            chk("c200/c2c0")
            rmw(PIPE + 0x4, (1 << 1) | (1 << 2), 0)
            rmw(PIPE + 0x0, 0, (1 << 0) | (1 << 2))
            rmw(PIPE + 0x10, 0, 1)
            lk, _ = poll(PIPE + 0x14, 1, 1, 10)
            chk(f"pipe lock {lk}")
            rmw(PIPE + 0xc, 0x70, 0); rmw(PIPE + 0xc, 0x3, 0); rmw(PIPE + 0xc, 0x70, 1 << 4)
            mux, _ = rd(PIPE + 0xc)
            chk(f"mux USB3 {mux:#x}")
            rmw(PIPE + 0x0, (1 << 0) | (1 << 2), 0); rmw(PIPE + 0x10, 1, 0)
            poll(PIPE + 0x14, 1, 0, 10)
            chk("unlock")
            cmd, _ = rd(op); wr(op, cmd | 2); poll(op, 2, 0, 100)
            chk("HCRST")
            rmw(PIPE + 0xc, 0x70, 0); rmw(PIPE + 0xc, 0x3, 2); rmw(PIPE + 0xc, 0x70, 2 << 4)
            wr(CORE + 0x6c, l0); wr(PWR + 0x8, m0)
        elif s == "u3bist":
            # Full USB3-host pipehandler path incl the BIST MAC lane power-up /
            # PIPE-reset release (atcphy_configure_pipehandler_usb3_host_t8122),
            # CIO ON. BIST block base reg[35] = core+0x29000. Oracle: SID
            # (drd+0xc120) / CAPLEN (drd+0x0) non-zero == controller alive.
            op = DRD + 0x20
            BB = CORE + 0x29000
            def snap(tag):
                b7 = " ".join(f"{o:#x}:{(rd(BB+o)[0]>>7)&1}" for o in (0x80, 0x100, 0x104, 0x108))
                print(f"  [{tag}] STATUS2bit7 {b7} | c120 {rd(CORE+0x120)[0]:#x} c10 {rd(CORE+0x10)[0]:#x}")
            def chk(tag):
                sid, _ = rd(DRD + 0xc120); cap, _ = rd(DRD + 0x0)
                g28, _ = rd(DRD + 0xcd28); sts, _ = rd(op + 4)
                print(f"  {tag:16} SID {sid:#010x} CAP {cap:#010x} glue {g28:#010x} "
                      f"USBSTS {sts:#x} {'ALIVE' if sid and cap else 'DEAD'}", flush=True)
            for off in (0x0, 0x4, 0x80, 0x88, 0x8c):
                v, f = rd(BB + off)
                print(f"  BIST+{off:#04x} = {v:#010x}{' FAULT' if f else ''}")
            # host mode WITHOUT a GCTL CoreSoftReset (bit 11) - the reset gates the
            # SS glue when CIO is on; the controller is already ready here.
            # host mode (prtcap), NO GCTL CoreSoftReset: with CIO on the reset zeroes the Apple
            # glue and wedges the controller in CNR (glue cannot be restored while CNR=1). Also
            # NO SUSPHY-clear: it zeroed the glue with no benefit. Best stable state = controller
            # runs on the pipe, glue 0x886, LTSSM 0x9cc20026, PLS 5 (not trained).
            rmw(DRD + 0xc110, 3 << 12, 1 << 12)
            l0, _ = rd(CORE + 0x6c)
            wr(CORE + 0x6c, (l0 & ~0xfc) | (2 << 2) | (2 << 5))
            chk("baseline")
            # Lanes FIRST (atcphy_configure_lanes runs before configure_pipehandler):
            # enable both lanes' TX clock, wake the lanes, rm_ovrd to hand the clock
            # tree to the FSM. The BIST dance below needs the lanes up - STATUS2 at
            # +0x104 only acks with the lanes powered (probe-confirmed).
            def ltdist(ms=300):
                s = set(); t = time.time() + ms / 1000
                while time.time() < t:
                    s.add(rd(DRD + 0xc164)[0]); time.sleep(0.003)
                return len(s)
            if os.environ.get("NOLANES"):
                # macOS USB3 (aciophy_slpctrl_init, mode 4): cmn_rm_ovrd, then txrx_rm_ovrd on the
                # active lane only; tx/rx_powerup and the TX SHM clocks are DisplayPort-only.
                ln = 1 if os.environ.get("SWAP") else 0
                rmw(CORE + 0xc, (1 << 1) | (1 << 3) | (1 << 5), 0)
                for reg, bits in ((0x10, (2, 6)), (0xc, (16, 8, 12)), (0x120, (6, 2, 10))):
                    for b in bits:
                        rmw(CORE + reg, 1 << (b + ln), 0)
            else:
                for TXSHM in (CORE + 0xd000, CORE + 0x1d000):   # both lanes' TX SHM clock
                    rmw(TXSHM + 0x24, 0, (1 << 13) | (1 << 12) | (1 << 15) | (1 << 14))
                    rmw(TXSHM + 0x24, (1 << 9) | (1 << 8) | (1 << 11) | (1 << 10), 0)
                    rmw(TXSHM + 0x00, 0, (1 << 6) | (1 << 3) | (1 << 2))
                    rmw(TXSHM + 0x00, 1 << 5, 1 << 4)
                    rmw(TXSHM + 0x04, 0, (1 << 9) | (1 << 8) | (1 << 23) | (1 << 22))
                    rmw(TXSHM + 0x04, 1 << 11, 1 << 10)
                # Lane TX/RX power-up on c120/c10. BOTH lanes are BIT FIELDS of the SAME reg (not
                # a +0x10000 stride). aciophy_tx_powerup/rx_powerup: step1 = OR bit(4+lane),
                # step2 = OR bit(6+lane); no poll (seqdec "bit0 wait" was a logging-gate misread).
                # Both lanes -> bits 4-7. First unclamp the low override bits + release the common
                # block (CFG0 core+0xc) to the FSM; u3bist was MISSING step2 (bits 6,7).
                rmw(CORE + 0x120, 0xfff, 0xcff)   # TX unclamp/awake (low override bits)
                rmw(CORE + 0x10, 0xfff, 0xcff)    # RX unclamp/awake
                rmw(CORE + 0xc, (1 << 1) | (1 << 3) | (1 << 5), 0)  # cmn rm_ovrd -> FSM
                rmw(CORE + 0x120, 0xccc, 0); rmw(CORE + 0x10, 0xccc, 0)   # tx/rx rm_ovrd -> FSM
                for lane in (0, 1):               # tx/rx_powerup: step1 bit(4+lane), step2 bit(6+lane)
                    rmw(CORE + 0x120, 0, 1 << (4 + lane)); rmw(CORE + 0x120, 0, 1 << (6 + lane))
                    rmw(CORE + 0x10, 0, 1 << (4 + lane)); rmw(CORE + 0x10, 0, 1 << (6 + lane))
            print(f"  lanes up: c120 {rd(CORE + 0x120)[0]:#x} c10 {rd(CORE + 0x10)[0]:#x} "
                  f"PLL {rd(CORE + 0x7034)[0] & 8:#x}")
            chk("lanes up")
            # atc.c "take the USB3 PHY out of reset" AFTER configure_lanes, via the REAL
            # ATCPHY_POWER_CTRL = core+0x20000 (not the reg[39] 0x2ab200000 block the harness
            # uses). Take it to the working "on + out-of-reset" value 0x1b (sleep_small b0,
            # sleep_big b1, apb_reset_n b3, phy_reset_n b4; clamp b2 off). atc.c does NOT poll
            # its status. Never done in-sequence after lanes before. Skip with NOPHYPWR=1.
            if not os.environ.get("NOPHYPWR"):
                pcb = rd(CORE + 0x20000)[0]; rmw(CORE + 0x20000, 0x1f, 0x1b)
                print(f"  phy_reset_n: core+0x20000 {pcb:#x} -> {rd(CORE + 0x20000)[0]:#x} "
                      f"stat {rd(CORE + 0x20004)[0]:#x}")
            # Start the PHY management core (acio-phy-cpu) - NEVER started before. The pipe
            # FSM / PhyStatus likely needs it running. phymxwrap domain already on (0x3ff).
            # port1 ctrl 0x2ab140000 = CORE+0x140040; read ctrl+0x40, OR bit0 (NOTES: 0xa0002
            # -> 0xa0003). Skip with NOMC=1.
            if not os.environ.get("NOMC"):
                MC = CORE + 0x140040
                mcv, _ = rd(MC); wr(MC, mcv | 1); mcv2, _ = rd(MC)
                print(f"  mgmt core {MC:#x}: {mcv:#x} -> {mcv2:#x}{'  STARTED' if mcv2 & 1 else '  no-take'}")
            # USB3_DP routing (T6050: lane-mode core+0x6c, crossbar core+0x78; t8122's
            # 0x60/0x64 are dead here). lane0/lane1 = USB3(2)/DP(7); swapped flips them.
            # crossbar PROTOCOL[4:0] = 0x10 (USB3_DP) / 0x11 swapped, DP_SINGLE_PMA[16:5] =
            # 0x008. MISC LANE_SWAP = core+0x20008 bit2. SWAP env flips orientation.
            SWAP = os.environ.get("SWAP")
            if os.environ.get("MACXBAR"):
                # AppleT6050TypeCPhy::aciophy_xbar_config, mode 4: normal = lane0 1 / lane1 2
                # (0x44), clear bits 23, 25; flipped = lane0 2 / lane1 1 (0x28), clear bits 22, 24;
                # [1:0] = 2. The lane swap itself is reg[39]+0x8 bit 1 (partC).
                if SWAP:
                    rmw(CORE + 0x6c, 0xfc | (1 << 22) | (1 << 24), 0x28)
                else:
                    rmw(CORE + 0x6c, 0xfc | (1 << 23) | (1 << 25), 0x44)
                rmw(CORE + 0x78, 0x1ffff, 0x111 if SWAP else 0x110)
                rmw(CORE + 0x6c, 3, 2)
            else:
                lm = ((7 << 2) | (2 << 5)) if SWAP else ((2 << 2) | (7 << 5))  # [4:2]=lane0,[7:5]=lane1
                rmw(CORE + 0x6c, 0xfc, lm)
                rmw(CORE + 0x78, 0x1ffff, (0x11 if SWAP else 0x10) | (0x008 << 5))
                sw = (1 << 2) if SWAP else 0
                rmw(CORE + 0x20008, 1 << 2, sw)      # ATCPHY_MISC LANE_SWAP (atc.c offset)
                rmw(PWR + 0x8, 1 << 2, sw)           # harness lanes: step's LANE_SWAP location
            print(f"  route: 6c {rd(CORE + 0x6c)[0]:#x} 78 {rd(CORE + 0x78)[0]:#x} "
                  f"misc20008 {rd(CORE + 0x20008)[0]:#x} pwr8 {rd(PWR + 0x8)[0]:#x}")
            def pipe_lock():
                # host USB3 pipehandler: disable link detection, then lock
                rmw(PIPE + 0x4, (1 << 1) | (1 << 2), 0)
                rmw(PIPE + 0x0, 0, 1 << 0)
                rmw(PIPE + 0x0, 0, 1 << 2)
                rmw(PIPE + 0x10, 0, 1)
                lk, _ = poll(PIPE + 0x14, 1, 1, 10)
                chk(f"lock {lk}")
                if rd(PCTL + 0x18)[0] & 1:   # txdeton ran: macOS waits for the TXDETRX ack here
                    ta, tv = poll(PCTL + 0x1c, 1, 1, 50)
                    print(f"  TXDETRX ack {ta} ({tv:#x})")
            # MACORDER: setUSB3Mode runs the whole PHY setPowerLevel (BIST + firmware) before the
            # PIPE overrides/lock; Linux does the BIST under the lock.
            MACORDER = os.environ.get("MACORDER")
            if not MACORDER:
                pipe_lock()
            # --- BIST MAC dance, T6050 offsets: CFG1 +0x4 (CLOCK_EN b0, USB_EN b3),
            # CFG2 +0x8 (PHY_STATUS_RE b5), STATUS2 +0x104 (b7, probe-confirmed), CFG_OV1
            # +0x10c, CFG_OV2 +0x110. Follows atcphy_configure_pipehandler_usb3_host_t8122.
            if os.environ.get("MACBIST"):
                # AppleT6050TypeCPhy::aciophy_phy_init_partC (mode 4) with its T6050 bits: CFG1 =
                # BIST+0x4 (CLOCK_EN b0, USB_EN b3), STATUS2 = +0x104 bit 8, OV1 +0x10c (PWR_DOWN_OV
                # [28:25], PIPE_RESET_N_OV b20), OV2 +0x110. runFirmware + UC_TNBL_DONE and the PHY
                # reset release (reg[39] bit 4, run with NORESET) sit between the two halves.
                C1, ST2, OV1, OV2 = BB + 0x4, BB + 0x104, BB + 0x10c, BB + 0x110
                def usben():
                    rmw(C1, 0, 1 << 3); rmw(C1, 1 << 3, 0)
                def st2(tag, want):
                    st, v = poll(ST2, 1 << 8, want << 8, 1000)
                    print(f"  [{tag}] STATUS2 bit8 -> {want}: {st} ({v:#x})")
                    return st
                rmw(C1, 0, 1)
                rmw(OV1, 0x1e100000, 2 << 25)
                usben()
                rmw(OV2, 0x660, 0x220)
                usben()
                rmw(PWR + 0x8, 1 << 1, (1 << 1) if SWAP else 0)      # CFG_S2R_USB_LN_SWAP
                time.sleep(0.01)
                if os.environ.get("FWWAKE"):
                    phy_cpu_wake()
                elif os.environ.get("FWRUN"):
                    rmw(MXW + 0x28, 0, 1 << 4)                       # MxWrap CPU_CTRL RUN
                time.sleep(0.005)
                tn, tv = poll(CORE + 0x260, 1 << 10, 1 << 10, 1000)
                print(f"  UC_TNBL_DONE {tn} ({tv:#x}) mxwrap ctrl {rd(MXW + 0x28)[0]:#x} "
                      f"stat {rd(MXW + 0x44)[0]:#x}")
                rmw(PWR, 0, 1 << 4)                                  # deassert_aciophy_reset
                time.sleep(0.1)
                rmw(OV1, 0, 1 << 20); usben(); s1 = st2("s1", 0)
                rmw(OV1, 0x1e000000, 3 << 25); usben(); s2 = st2("s2 rise", 1); s3 = st2("s2 fall", 0)
                rmw(OV2, 0x660, 0); usben()
                rmw(PIPE + 0x20, 0xf, 3); rmw(PIPE + 0x20, 1 << 12, 0)   # clear_nonselected
                print(f"  BIST(mac): s1 {s1} rise {s2} fall {s3}; C1 {rd(C1)[0]:#x} OV1 {rd(OV1)[0]:#x} "
                      f"OV2 {rd(OV2)[0]:#x} PWR {rd(PWR)[0]:#x}")
            else:
                C1, C2, ST2, OV1, OV2 = BB + 0x0, BB + 0x4, BB + 0x104, BB + 0x10c, BB + 0x110
                CLKEN, USBEN, STRE, ST2B = 1 << 0, 1 << 2, 1 << 2, 1 << 7
                rmw(C1, 0, CLKEN)
                wr(OV1, 0x100000 | (2 << 25))               # CFG_OV1 PIPE_RESET_N_OV | PWR_DOWN_OV=2
                wr(OV2, 0x200 | 0x20)                       # CFG_OV2 RESET_N_OV | PWR_DOWN_OV
                rmw(C1, 0, USBEN); e1, _ = poll(C1, USBEN, USBEN, 10); snap("en1")
                rmw(C1, USBEN, 0); s1, _ = poll(ST2, ST2B, 0, 10)
                rmw(C2, 0, STRE); time.sleep(0.01); rmw(C2, STRE, 0)
                rmw(OV1, 3 << 25, 3 << 25)                  # CFG_OV1 PWR_DOWN_OV = 3
                time.sleep(0.01)
                rmw(C1, 0, USBEN); e2, _ = poll(C1, USBEN, USBEN, 10); snap("en2")
                rmw(C1, USBEN, 0); s2, _ = poll(ST2, ST2B, 0, 10)
                rmw(C2, 0, STRE); time.sleep(0.01); rmw(C2, STRE, 0)
                rmw(PIPE + 0x20, 0xf, 3); rmw(PIPE + 0x20, 1 << 12, 0)   # clear_nonselected
                rmw(OV2, 0x200 | 0x20, 0)                    # release CFG_OV2 RESET_N_OV | PWR_DOWN_OV
                rmw(C1, 0, USBEN); e3, _ = poll(C1, USBEN, USBEN, 10); snap("en3")
                rmw(C1, USBEN, 0); rmw(C1, CLKEN, 0)
                print(f"  BIST polls: USB_EN e1 {e1} e2 {e2} e3 {e3}; STATUS2 s1 {s1} s2 {s2}")
            chk("after BIST")
            if MACORDER:
                pipe_lock()
            # mux to USB3 (T8142: clk [6:4]=1, data [1:0]=0). NOSWITCH=1 leaves it at 0x22 (the
            # USB2-working "dummy" clock) so the controller stays clocked while the PHY comes up.
            if not os.environ.get("NOSWITCH"):
                rmw(PIPE + 0xc, 0x70, 0); rmw(PIPE + 0xc, 0x3, 0); rmw(PIPE + 0xc, 0x70, 1 << 4)
            mux, _ = rd(PIPE + 0xc)
            rmw(PIPE + 0x0, 1 << 0, 0); rmw(PIPE + 0x0, 1 << 2, 0)
            rmw(PIPE + 0x10, 1, 0); ul, _ = poll(PIPE + 0x14, 1, 0, 10)
            chk(f"mux {mux:#x} ul {ul}")
            if rd(PCTL + 0x18)[0] & 1:   # macOS releases the TXDETRX lock after the PIPE unlock
                rmw(PCTL + 0x18, 1, 0); tr, tv = poll(PCTL + 0x1c, 1, 0, 50)
                print(f"  TXDETRX release {tr} ({tv:#x})")
            # Start the controller, then drive a DIRECTED link-state change to
            # RxDetect (PLS=5 + LWS) - NO WPR. A warm reset pins PR=1 and holds the
            # SS LTSSM in reset, masking the real state; a directed PLS keeps the
            # port observable. NO HCRST (keeps the controller alive).
            op0 = op + 0x400; op1 = op + 0x410
            def dec1(v):
                return (f"{v:#010x} PR {(v>>4)&1} PLS {(v>>5)&0xf} CCS {v&1} "
                        f"PED {(v>>1)&1} PP {(v>>9)&1} WRC {(v>>19)&1} PRC {(v>>21)&1} spd {(v>>10)&0xf}")
            def gdbg():  # GDBGLTSSM: LTSSM state [25:22], RXELECIDLE b17, TXDETRXLOOPBACK b24
                g, _ = rd(DRD + 0xc164)
                return f"{g:#010x} ltssm {(g>>22)&0xf:#x} rxei {(g>>17)&1} txdet {(g>>24)&1}"
            if os.environ.get("HCRST_AFTER"):
                # xHCI reset with CIO on and the PIPE on USB3. Earlier (no pipe clock) this wedged in
                # CNR; completing now means the controller runs on the USB3 PHY's clock.
                g0 = [rd(DRD + o)[0] for o in (0xcd28, 0xcd2c, 0xcd40, 0xcd44)]
                wr(op, rd(op)[0] | 2)
                hr, hv = poll(op, 2, 0, 2000); cr, cv = poll(op + 4, 1 << 11, 0, 2000)
                g1 = [rd(DRD + o)[0] for o in (0xcd28, 0xcd2c, 0xcd40, 0xcd44)]
                print(f"  HCRST after PHY: HCRST {hr} ({hv:#x}) CNR {cr} ({cv:#x}) glue {[hex(v) for v in g1]}", flush=True)
                if g1 != g0:
                    for o, v in zip((0xcd28, 0xcd2c, 0xcd40, 0xcd44), g0):
                        wr(DRD + o, v)
                    print(f"  glue restored -> {[hex(rd(DRD + o)[0]) for o in (0xcd28, 0xcd2c, 0xcd40, 0xcd44)]}")
                rmw(DRD + 0xc110, 3 << 12, 1 << 12)   # host prtcap
            cmd, _ = rd(op); wr(op, cmd | 1)                     # Run/Stop
            for pa in (op0, op1):
                v, _ = rd(pa); wr(pa, (v & (0x40003c09 | 0x0e00c3e0)) | (1 << 9))  # port power
            # controller ring state (expected all 0 - running with no event ring can wedge
            # the warm-reset completion, a PR-stuck cause unrelated to the PHY)
            rts = rd(DRD + 0x18)[0] & ~0x1f
            print(f"  CTLR: USBCMD {rd(op)[0]:#x} USBSTS {rd(op+4)[0]:#x} CRCR {rd(op+0x18)[0]:#x} "
                  f"DCBAAP {rd(op+0x30)[0]:#x} CONFIG {rd(op+0x38)[0]:#x} "
                  f"ERSTSZ {rd(DRD+rts+0x28)[0]:#x} ERSTBA {rd(DRD+rts+0x30)[0]:#x}")
            print(f"  base PORTSC1 {dec1(rd(op1)[0])} | GDBG {gdbg()}")
            time.sleep(0.1)
            print(f"  base+100ms   {dec1(rd(op1)[0])} | GDBG {gdbg()}")
            if os.environ.get("U2RESET"):
                # The stick has run USB2 since boot, so its SS side sits in SS.Disabled with the
                # receiver terminations off; a USB 2.0 bus reset sends it back to Rx.Detect.
                v0, _ = rd(op0)
                wr(op0, (v0 & (0x200 | 0xc000 | 0x0e000000)) | (1 << 4))
                print(f"  USB2 port reset issued: PORTSC0 {v0:#x} -> {rd(op0)[0]:#x}", flush=True)
            cur, _ = rd(op1)                                     # WPR (warm reset, bit31)
            if not os.environ.get("NOSWITCH") and not os.environ.get("U2RESET"):
                wr(op1, (cur & (0x200 | 0xc000 | 0x0e000000)) | (1 << 31))  # the controller's own PR
            last = None; end = time.time() + 6
            while time.time() < end:
                v0, _ = rd(op0); v1, _ = rd(op1); g = gdbg()
                if (v0, v1, g) != last:
                    print(f"  USB2 PORTSC0 {v0:#06x} CCS {v0 & 1} | SS {dec1(v1)} | GDBG {g}")
                    last = (v0, v1, g)
                time.sleep(0.01)
            chk("after watch")
            print(f"  PIPE  GUSB3PIPECTL {rd(DRD+0xc2c0)[0]:#x} GUSB2PHYCFG {rd(DRD+0xc200)[0]:#x} "
                  f"GCTL {rd(DRD+0xc110)[0]:#x} GSTS {rd(DRD+0xc118)[0]:#x}")
            print(f"  PCS   CFG1 {rd(CORE+0x29000)[0]:#x} CFG2 {rd(CORE+0x29004)[0]:#x} "
                  f"STATUS2 {rd(CORE+0x29080)[0]:#x} CFG_OV1 {rd(CORE+0x29088)[0]:#x} CFG_OV2 {rd(CORE+0x2908c)[0]:#x}")
            print(f"  LANE  TXpwr(c120) {rd(CORE+0x120)[0]:#x} RXpwr(c10) {rd(CORE+0x10)[0]:#x} "
                  f"CFG0(c) {rd(CORE+0xc)[0]:#x} lanemode(6c) {rd(CORE+0x6c)[0]:#x} PLLlock {rd(CORE+0x7034)[0]&8:#x}")
            print(f"  PORTSC1 {dec1(rd(op1)[0])} glue cd28 {rd(DRD+0xcd28)[0]:#x} "
                  f"cd40 {rd(DRD+0xcd40)[0]:#x} cd44 {rd(DRD+0xcd44)[0]:#x}")
            # host LSP debug sweep: is the SS LTSSM live (changing) or truly frozen? GDBGLTSSM
            # may be a stale view; the live host link-state is GDBGLSP after a GDBGLSPMUX
            # host-select (+ENDBC). Sweep selects, read GDBGLSP twice 4ms apart, flag changers.
            live = []
            for sel in range(0, 24):
                wr(DRD + 0xc170, (sel & 0x3fff) | (1 << 15))   # HOSTSELECT(sel) | ENDBC
                x = rd(DRD + 0xc174)[0]; time.sleep(0.004); y = rd(DRD + 0xc174)[0]
                if x or y:
                    print(f"  LSP sel {sel}: {x:#010x} / {y:#010x}{'  LIVE' if x != y else ''}")
                    if x != y:
                        live.append(sel)
            print(f"  LSP live sels: {live}  GDBGLTSSM {rd(DRD+0xc164)[0]:#x}")
            print(f"  pipehandler: mux(+0xc) {rd(PIPE+0xc)[0]:#x} nonsel(+0x20) {rd(PIPE+0x20)[0]:#x}")
            print(f"  UC_CTRL core+0x260 {rd(CORE + 0x260)[0]:#x}", flush=True)
            if os.environ.get("MBOX"):   # last: an unpowered mailbox read can hang the SoC
                print(f"  PHY CPU mailbox INBOX_CTRL {rd(MXW + 0x8110)[0]:#x} "
                      f"OUTBOX_CTRL {rd(MXW + 0x8114)[0]:#x}", flush=True)
            wr(CORE + 0x6c, l0)
        elif s == "fwstart":
            phy_cpu_wake()
            tn, tv = poll(CORE + 0x260, 1 << 10, 1 << 10, 1000)
            print(f"  UC_TNBL_DONE {tn} ({tv:#x})")
        elif s == "txdeton":
            # AppleT8150USBXHCI::setUSB3Mode takes the TXDETRX lock (AUSBC_PWR_CTRL, usb-drd reg[5],
            # REQ +0x18 / ACK +0x1c bit 0) before the PHY setPowerLevel; u3bist waits for its ack
            # after the PIPE lock and releases it after the PIPE unlock.
            rmw(PCTL + 0x18, 0, 1); ta, tv = poll(PCTL + 0x1c, 1, 1, 50)
            print(f"  TXDETRX req set, ack {ta} ({tv:#x})")
        elif s in ("tunread", "tunapply"):
            # The usb-drd1 controller tunables (never applied by this harness). Window = the
            # slot AppleT8150USBXHCI::applyAllTunables passes: ADT usb-drd reg index, slot 0
            # read at the dwc3 globals (core+0xc100). DRD_CIO_REGS = the Apple glue (core+0xcd00).
            # tunread: port 1 and port 2 values, read only. tunapply: write them on port 1.
            import struct as _st
            node = u.adt["/arm-io/usb-drd1"]
            TUN = [("tunable_DRD_USB31_DBG_DEFAULT", None), ("tunable_DRD_USB31_GBL_DEFAULT", None),
                   ("tunable_DRD_USB31_GBL_HOST", None), ("tunable_DRD_USB31_CFG_HOST", 1),
                   ("tunable_LINK_REGS_DEFAULT", 7), ("tunable_AUSBC_DEBUG_DEFAULT", 8),
                   ("tunable_BULK_FABRIC_DEFAULT", 6), ("tunable_PIPE_HANDLER_DEFAULT", 3),
                   ("tunable_DRD_CIO_REGS_DEFAULT", "cio")]
            P2 = 0x382280000 - DRD
            for prop, idx in TUN:
                raw = bytes(node._properties[prop])
                base = DRD + 0xc100 if idx is None else DRD + 0xcd00 if idx == "cio" else node.get_reg(idx)[0]
                for j in range(0, len(raw), 12):
                    ofs, mask, val = _st.unpack_from("<III", raw, j)
                    a = base + (ofs & 0xffffff)
                    v1, f1 = rd(a)
                    v2, f2 = rd(a + P2) if s == "tunread" else (0, False)
                    line = (f"  {prop[8:]:22} {a:#012x} want {val:#010x}/{mask:#010x} "
                            f"p1 {v1:#010x}{'F' if f1 else ''} {'ok' if (v1 & mask) == val else 'DIFF'}")
                    if s == "tunread":
                        line += f"  p2 {v2:#010x}{'F' if f2 else ''} {'ok' if (v2 & mask) == val else 'DIFF'}"
                    else:
                        rmw(a, mask, val & mask); line += f"  -> {rd(a)[0]:#010x}"
                    print(line, flush=True)
                pet()
        elif s == "ackprobe":
            # Is the USB3 PIPE clock running? The controller answers the pipehandler LOCK_REQ
            # through the selected PIPE backend (atc.c: "stopped parking cannot clock the
            # ACK"). Toggle LOCK_REQ under each mux: dummy 0x22 (clocked, positive control),
            # clock OFF 0x00 (negative control), USB3 0x10 (the question). Run after u3bist.
            rmw(CORE + 0x6c, 0xfc, (2 << 2) | (7 << 5))
            m0 = rd(PIPE + 0xc)[0]
            def setmux(v):
                rmw(PIPE + 0xc, 0x70, 0); rmw(PIPE + 0xc, 0x3, v & 3); rmw(PIPE + 0xc, 0x70, v & 0x70)
            for name, v in (("usb3", 0x10), ("dummy", 0x22), ("clkoff", 0x00), ("dummy", 0x22), ("usb3", 0x10)):
                setmux(v); time.sleep(0.01)
                a0 = rd(PIPE + 0x14)[0]
                # the same link-detect overrides u3bist sets before its (acked) lock
                rmw(PIPE + 0x4, (1 << 1) | (1 << 2), 0); rmw(PIPE + 0x0, 0, (1 << 0) | (1 << 2))
                rmw(PIPE + 0x10, 0, 1); lk, la = poll(PIPE + 0x14, 1, 1, 20)
                rmw(PIPE + 0x10, 1, 0); ul, ua = poll(PIPE + 0x14, 1, 0, 20)
                rmw(PIPE + 0x0, (1 << 0) | (1 << 2), 0)
                print(f"  mux {rd(PIPE + 0xc)[0]:#04x} ({name:6}) ack before {a0:#x} lock {lk} ({la:#x}) "
                      f"unlock {ul} ({ua:#x}) GDBG {rd(DRD + 0xc164)[0]:#010x}", flush=True)
            setmux(m0)
        elif s == "phypwr":
            # the driver's atcphy_power_on at ATCPHY_POWER_CTRL = core+0x20000
            # (reg[32]) - the USB3 PHY power/reset block, distinct from the reg[39]
            # reset controller at 0x2ab200000 used elsewhere. This releases the
            # per-lane USB3 PHY's OWN reset (PHY_RESET_N bit4), never done before.
            PC = CORE + 0x20000; PS = CORE + 0x20004; MISC = CORE + 0x20008
            v, _ = rd(PC); vm, _ = rd(MISC)
            print(f"  before: ctrl core+0x20000 = {v:#010x} stat {rd(PS)[0]:#010x} misc {vm:#010x}")
            rmw(MISC, 0, 1 << 0)                          # ATCPHY_MISC RESET_N
            rmw(PC, 0, 1 << 0); ss, _ = poll(PS, 1 << 0, 1 << 0, 100)   # sleep small + stat
            rmw(PC, 0, 1 << 1); sb, _ = poll(PS, 1 << 1, 1 << 1, 100)   # sleep big + stat
            rmw(PC, 1 << 2, 0)                            # clamp off
            rmw(PC, 0, 1 << 3)                            # APB reset N
            rmw(PC, 0, 1 << 4)                            # PHY reset N (USB3 PHY out of reset)
            v, _ = rd(PC)
            print(f"  after: ctrl = {v:#010x} stat {rd(PS)[0]:#010x} (small {ss} big {sb})")
        elif s == "gluewr":
            # restore the dwc3-apple glue (drd+0xcd00) that the core-soft-reset
            # zeroed; it holds the pipe/ref-clock enables and m1n1 never rewrites
            # it. Report whether the writes stick (expected to stick CIO-off).
            for off, val in ((0xcd28, 0x886), (0xcd2c, 0x886), (0xcd40, 0x3c20060c), (0xcd44, 0x0002000b)):
                wr(DRD + off, val); v, _ = rd(DRD + off)
                print(f"  glue drd+{off:#x} <= {val:#010x} reads {v:#010x} {'OK' if v == val else 'IGNORED'}")
            # now power each CIO sub-domain and see which one zeroes the glue
            for name, off in (("atc1_cio", 0x280600290), ("atc1_cio_usb", 0x280600358), ("atc1_cio_auss", 0x280600360)):
                v, _ = rd(off); wr(off, (v & ~(0xf | 0x300)) | 0xf); poll(off, 0xf0, 0xf0, 100)
                g, _ = rd(DRD + 0xcd28)
                print(f"  after +{name:14}: glue cd28 = {g:#010x} {'(alive)' if g else '(ZEROED)'}")
        elif s == "u3after":
            # NEW ORDER: run after `flip` (USB2 host up, dwc3 core-soft-reset done
            # CIO OFF so the glue is configured + SS block init'd) AND after CIO
            # domains are powered. Do BIST dance + lane + mux to USB3 with NO
            # further dwc3 reset (which would gate the glue once CIO is on).
            op = DRD + 0x20; BB = CORE + 0x29000
            def chk(t):
                sid, _ = rd(DRD + 0xc120); cap, _ = rd(DRD + 0x0); g, _ = rd(DRD + 0xcd28); sts, _ = rd(op + 4)
                print(f"  {t:14} SID {sid:#010x} CAP {cap:#010x} glue {g:#010x} USBSTS {sts:#x} {'ALIVE' if sid and cap else 'DEAD'}")
            def ltd(ms=500):
                s = set(); t = time.time() + ms / 1000
                while time.time() < t:
                    s.add(rd(DRD + 0xc164)[0]); time.sleep(0.003)
                return len(s)
            chk("cio-on")
            l0, _ = rd(CORE + 0x6c); wr(CORE + 0x6c, (l0 & ~0xfc) | (2 << 2) | (2 << 5))
            rmw(PIPE + 0x4, (1 << 1) | (1 << 2), 0); rmw(PIPE + 0x0, 0, 1 << 0); rmw(PIPE + 0x0, 0, 1 << 2)
            rmw(PIPE + 0x10, 0, 1); lk, _ = poll(PIPE + 0x14, 1, 1, 10)
            rmw(BB + 0x0, 0, 1 << 0); rmw(BB + 0x88, 0, 0x100000 | (2 << 25)); rmw(BB + 0x8c, 0, 0x200 | 0x20)
            rmw(BB + 0x0, 0, 1 << 2); poll(BB + 0x0, 1 << 2, 1 << 2, 10); rmw(BB + 0x0, 1 << 2, 0); poll(BB + 0x80, 1 << 7, 0, 10)
            rmw(BB + 0x4, 0, 1 << 2); rmw(BB + 0x4, 1 << 2, 0)
            rmw(BB + 0x88, 3 << 25, 3 << 25)
            rmw(BB + 0x0, 0, 1 << 2); poll(BB + 0x0, 1 << 2, 1 << 2, 10); rmw(BB + 0x0, 1 << 2, 0); poll(BB + 0x80, 1 << 7, 0, 10)
            rmw(BB + 0x4, 0, 1 << 2); rmw(BB + 0x4, 1 << 2, 0)
            rmw(PIPE + 0x20, 0xf, 3); rmw(PIPE + 0x20, 1 << 12, 0)
            rmw(BB + 0x8c, 0x200 | 0x20, 0)
            rmw(BB + 0x0, 0, 1 << 2); poll(BB + 0x0, 1 << 2, 1 << 2, 10); rmw(BB + 0x0, 1 << 2, 0); rmw(BB + 0x0, 1 << 0, 0)
            chk(f"after BIST lk {lk}")
            rmw(PIPE + 0xc, 0x70, 0); rmw(PIPE + 0xc, 0x3, 0); rmw(PIPE + 0xc, 0x70, 1 << 4)
            rmw(PIPE + 0x0, 1 << 0, 0); rmw(PIPE + 0x0, 1 << 2, 0)
            rmw(PIPE + 0x10, 1, 0); poll(PIPE + 0x14, 1, 0, 10)
            mux, _ = rd(PIPE + 0xc)
            chk(f"mux {mux:#x}")
            print(f"  LTSSM distinct {ltd(1500)} ({'LIVE' if False else '?'}); PORTSC1 {rd(op + 0x410)[0]:#010x}")
        elif s == "pclkvar":
            # select 2 / 7 with bit 0, bit 13, both; watch PWR+0x18 for 50 ms each
            c14, _ = rd(PWR + 0x14)
            for sel in (2, 7):
                for extra in (0x1, 0x2000, 0x2001):
                    pet()
                    wr(PWR + 0x14, (c14 & ~0x2039) | (sel << 3))
                    time.sleep(0.001)
                    wr(PWR + 0x14, (c14 & ~0x2039) | (sel << 3) | extra)
                    seen = []
                    end = time.time() + 0.05
                    while time.time() < end:
                        v, _ = rd(PWR + 0x18)
                        if not seen or v != seen[-1]:
                            seen.append(v)
                        time.sleep(0.0005)
                    n14, _ = rd(PWR + 0x14)
                    print(f"  sel {sel} + {extra:#x}: +0x14 {n14:#x}; +0x18 " + " -> ".join(hex(x) for x in seen), flush=True)
                    wr(PWR + 0x14, c14)
                    time.sleep(0.002)
        elif s.startswith("probe") or s.startswith("dump:"):
            # atc-phy1 ADT windows plus the controller side; SKIP=i,j env leaves windows out.
            # probe: first word of each window; dump:NAME: words up to the next window
            # (max 0x1000 bytes) into dump-NAME.json next to this script.
            import json, os as _os
            node = u.adt["/arm-io/atc-phy1"]
            bases = sorted(node.get_reg(i)[0] for i in range(len(node.reg)))
            parts = s.split(":")
            skip_s = parts[2] if len(parts) > 2 else _os.environ.get("SKIP", "")
            skip = {int(x) for x in skip_s.split(",") if x and x != "-"}
            wins = []
            for i in range(len(node.reg)):
                if i in skip:
                    continue
                b = node.get_reg(i)[0]
                nxt = [x for x in bases if x > b]
                ln = min(0x1000, (nxt[0] - b) if nxt else 0x1000)
                wins.append((f"reg{i}", b, ln))
            wins += [("dwc3", DRD + 0xc100, 0x700), ("glue", DRD + 0xcd00, 0x100)]
            out = {}
            for name, b, ln in wins:
                pet()
                print(f"  {name} {b:#x} +{ln:#x}", flush=True)
                n = 1 if s.startswith("probe") else ln // 4
                for k in range(n):
                    v, f = rd(b + 4 * k)
                    out[f"{b + 4 * k:#x}"] = None if f else v
            if s.startswith("dump:"):
                path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), f"dump-{parts[1]}.json")
                json.dump(out, open(path, "w"))
                print(f"  {len(out)} words -> {path}")
            else:
                print("  probe done")
        elif s.startswith("retune:"):
            # re-apply one ADT tunable after a power-domain change: retune:fabric|axi2af|cfg
            import struct as _st
            node = u.adt["/arm-io/atc-phy1"]
            prop, idx = {"fabric": ("tunable_ATC_FABRIC", 40), "axi2af": ("tunable_ATC0AXI2AF", 41),
                         "cfg": ("tunable_ATC_COMMON_CFG", 43)}[s[7:]]
            raw = bytes(node._properties[prop]); base = node.get_reg(idx)[0]
            faults = 0
            for j in range(0, len(raw), 12):
                ofs, mask, val = _st.unpack_from("<III", raw, j)
                faults += rmw(base + (ofs & 0xffffff), mask, val & mask)
            v, _ = rd(base)
            print(f"  {prop} reapplied: {len(raw) // 12} entries, {faults} faults; first word {v:#x}")
            g, _ = rd(DRD + 0xc118)
            print(f"  GSTS {g:#x}")
        elif s == "glue":
            # glue values seen with CIO off (dump A)
            for o, v in ((0xcd28, 0x886), (0xcd2c, 0x886), (0xcd40, 0x3c20060c), (0xcd44, 0x2000b)):
                wr(DRD + o, v)
                r, _ = rd(DRD + o)
                print(f"  drd+{o:#x} <- {v:#x} reads {r:#x}")
            g, _ = rd(DRD + 0xc118)
            print(f"  GSTS {g:#x}")
        elif s == "cmn":
            # common-block init as recorded in t6050-usb3-usb4-bringup.md
            seq = [(0xc, 0, 1 << 2), (0xc, 0, 1 << 3), (0xc, 0, 1 << 0), (0xc, 0, 1 << 1),
                   (0xc, 1 << 4, 0), (0xc, 0, 1 << 5), (0xa00, 0, 1 << 1), ("r", 0x804),
                   (0xa00, 1 << 1, 0), (0xc, 0, 1 << 4), (0xc, 1 << 0, 0), (0xc, 1 << 2, 0)]
            for e in seq:
                if e[0] == "r":
                    v, f = rd(CORE + e[1])
                    print(f"  read core+{e[1]:#x} = {v:#010x}{' FAULT' if f else ''}")
                    continue
                off, clr, st_ = e
                f = rmw(CORE + off, clr, st_)
                v, _ = rd(CORE + off)
                print(f"  core+{off:#x} clear {clr:#x} set {st_:#x} -> {v:#010x}{' FAULT' if f else ''}")
                time.sleep(0.001)
        elif s == "flipnophy":
            step_flip(False, False)
        elif s == "flipu3s":
            step_flip(True)
        elif s == "diag":
            regs = [("pipe", PIPE, (0x0, 0x4, 0x8, 0xc, 0x10, 0x14, 0x18, 0x1c, 0x20, 0x24)),
                    ("usb2phy", USB2PHY, (0x0, 0x4, 0x8, 0xc, 0x10, 0x14, 0x18, 0x1c)),
                    ("dwc3", DRD, (0xc110, 0xc118, 0xc200, 0xc2c0, 0xc70c))]
            for blk, base, offs in regs:
                vals = []
                for o in offs:
                    v, f = rd(base + o)
                    vals.append(f"+{o:#x}={v:#010x}{'!' if f else ''}")
                print(f"  {blk:8} " + " ".join(vals))
        elif s.startswith("pd:"):
            name = s[3:]
            off = dict(DOMAINS + WATCH)[name]
            a = PMGR + off
            v, f = rd(a)
            wr(a, (v & ~(0xf | 0x300)) | 0xf)
            st, v = poll(a, 0xf0, 0xf0, 100)
            print(f"  {name:14} on: {st} ({v:#010x})")
        elif s in ("small", "big"):
            bit = 0 if s == "small" else 1
            rmw(PWR, 0, 1 << bit)
            st, v = poll(PWR + 4, 1 << bit, 1 << bit, 100)
            print(f"  sleep {s}: stat {st} ({v:#010x})")
        elif s in ("unclamp", "apb", "phyrst"):
            if s == "unclamp":
                rmw(PWR, 1 << 2, 0)
            else:
                rmw(PWR, 0, 1 << (3 if s == "apb" else 4))
            v, f = rd(PWR)
            print(f"  power ctrl = {v:#010x}{' FAULT' if f else ''}")
        elif s == "clkdump":
            # dump the controller clock-select candidates (pipehandler + dwc3 glue + usb2phy)
            # so CIO-off vs CIO-on can be diffed - whatever CIO flips gates the reset clock.
            for nm, a in (("pipe OVERRIDE", PIPE + 0x0), ("pipe OVR_VAL", PIPE + 0x4),
                          ("pipe MUX_CTRL", PIPE + 0xc), ("pipe LOCK_REQ", PIPE + 0x10),
                          ("pipe LOCK_ACK", PIPE + 0x14), ("pipe AON_GEN", PIPE + 0x18),
                          ("pipe NONSEL", PIPE + 0x20), ("glue cd28", DRD + 0xcd28),
                          ("glue cd2c", DRD + 0xcd2c), ("glue cd40", DRD + 0xcd40),
                          ("glue cd44", DRD + 0xcd44), ("usb2phy+0x0", USB2PHY + 0x0),
                          ("usb2phy+0x8", USB2PHY + 0x8)):
                v, f = rd(a)
                print(f"  {nm:14} {a:#x} = {v:#010x}{' FAULT' if f else ''}")
            op = DRD + 0x20
            print(f"  CTLR SID {rd(DRD+0xc120)[0]:#x} CAP {rd(DRD+0x0)[0]:#x} "
                  f"USBCMD {rd(op)[0]:#x} USBSTS {rd(op+4)[0]:#x} (CNR {(rd(op+4)[0]>>11)&1})")
        elif s == "xhcirst":
            # Feasibility gate for the real-host path: does the xHCI-level HCRST (USBCMD b1)
            # clear CNR (USBSTS b11) on a freshly-powered controller? HCRST self-clears when
            # the reset completes (gated by clocks). Watch the glue across it too.
            op = DRD + 0x20
            print(f"  pre:  USBCMD {rd(op)[0]:#x} USBSTS {rd(op+4)[0]:#x} "
                  f"glue {rd(DRD+0xcd28)[0]:#x} SID {rd(DRD+0xc120)[0]:#x}")
            rmw(op, 0, 1 << 1)                                  # HCRST
            sr, vr = poll(op, 1 << 1, 0, 1000)                  # self-clear of HCRST
            sc, vc = poll(op + 4, 1 << 11, 0, 1000)             # CNR clear
            print(f"  HCRST self-clear {sr} (USBCMD {vr:#x}); CNR clear {sc} (USBSTS {vc:#x})")
            print(f"  post: glue {rd(DRD+0xcd28)[0]:#x} SID {rd(DRD+0xc120)[0]:#x} "
                  f"CAP {rd(DRD+0x0)[0]:#x} HCSPARAMS1 {rd(DRD+0x4)[0]:#x}")
        elif s == "reboot":
            disarm()
            p.reboot()
            break
finally:
    try:
        disarm()
        p.set_exc_guard(GUARD.OFF)
    except Exception:
        pass
