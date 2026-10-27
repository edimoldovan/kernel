# T6050 port 1 (left-front): Type-C PHY power-up versus the USB2 host, over the stage 1 proxy.
# usage (from forks/omacom-m1n1, M1N1DEVICE=/dev/serial/by-id/...g7cde*-if00):
#   PYTHONPATH=proxyclient .venv/bin/python t6050_phy_power_test.py STEP...
# Steps run in order: read flip flipnophy flipu3s diag pd pd:<domain> cio small big unclamp
# apb phyrst pwrread coreread core:LO-HI cmn tunables lanes:normal|swapped pipeusb3
# sswatch warm wmap:LO-HI set:OFF=VAL,... sweep sweep2 sweep3 wake pllstart pllstart2 muxmap hcreset reboot. The watchdog (90 s) is armed for the whole run.
import sys, time
from m1n1.setup import p, u  # noqa: F401
from m1n1.proxy import GUARD

WDT = 0x28836c000                  # COUNT +0x10, ALARM +0x14, CTL +0x1c
WDT_ALARM = 24000000 * 90          # 90 s at 24 MHz

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
    rmw(PWR, 0, 1 << 4)
    for label, off in (("ctrl", 0), ("stat", 4), ("misc", 8)):
        v, f = rd(PWR + off)
        print(f"  power {label} = {v:#010x}{' FAULT' if f else ''}")
    v, f = rd(CORE + 0xc)
    print(f"  core+0xc = {v:#010x}{' FAULT' if f else ''}")
    return True

steps = sys.argv[1:] or ["read"]
if is_proxy(DRD):
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
