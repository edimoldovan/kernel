# T6050 port 1 (left-front): Type-C PHY power-up versus the USB2 host, over the stage 1 proxy.
# usage (from forks/omacom-m1n1, M1N1DEVICE=/dev/serial/by-id/...g7cde*-if00):
#   PYTHONPATH=proxyclient .venv/bin/python t6050_phy_power_test.py STEP...
# Steps run in order: read flip flipnophy flipu3s diag pd pd:<domain> cio small big unclamp
# apb phyrst pwrread coreread cmn reboot. The watchdog (90 s) is armed for the whole run.
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
