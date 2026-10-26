#!/usr/bin/env python3
# T6050 (J714c) USB 2.0 host bring-up probe, over the m1n1 USB proxy.
#
# Validates the USB2-only host path on real M5 Max silicon. It touches ONLY the
# two small USB2 blocks (usb2phy + pipehandler) and the dwc3 core - never the
# 44-window ATC core or the USB3/CIO tunables, which is exactly the part that
# fails probe on this new PHY generation. USB2 needs none of it.
#
# Every MMIO access is wrapped in the proxy exception guard (faults RETURN, they
# do not lock the machine); every poll is iteration- and wall-clock-bounded.
# The proxy's own console port is auto-detected (device mode, HS, link U0) and
# HARD-REFUSED. Operate only on a free port.
#
#   Stage A (default):      survey all three ports (read-only)
#   Stage B/C (--host N):   flip free port N to USB2 host, reset xHCI, read PORTSC
#
# Run from the omacom-m1n1 fork with the proxy live, e.g.:
#   cd forks/omacom-m1n1
#   M1N1DEVICE=/dev/ttyACM1 PYTHONPATH=proxyclient .venv/bin/python \
#       ../../kernel/usb2-host/t6050_usb2_host_probe.py --host 2
#
# A real connect result (PORTSC.CCS=1) needs a USB 2.0 device physically in
# that port first. With nothing plugged in, CCS reads 0 - that is a pass for the
# controller path, not for enumeration.

import sys, time
from m1n1.setup import p, u            # noqa: F401  (builds the proxy as `p`)
from m1n1.proxy import GUARD

# ---- per-port register bases (absolute, from the live ADT) ----------------
PORTS = {
    0: dict(drd=0x2a2280000, usb2phy=0x2a2a90000, pipe=0x2a2a84000),
    1: dict(drd=0x2aa280000, usb2phy=0x2aaa90000, pipe=0x2aaa84000),
    2: dict(drd=0x382280000, usb2phy=0x382a90000, pipe=0x382a84000),
}

# USB2 PHY block
USB2PHY_SIG       = 0x08
USB2PHY_SIG_HOST  = 7 << 12
# pipehandler block
PIPE_MUX_CTRL     = 0x0c
# dwc3 global / device regs (offsets inside drd)
DWC3_GCTL         = 0xc110
GCTL_CORESOFTRESET = 1 << 11
GCTL_PRTCAPDIR_SHIFT = 12
GCTL_PRTCAP_HOST  = 1
DWC3_DCTL         = 0xc704
DCTL_RUN_STOP     = 1 << 31
DWC3_DSTS         = 0xc70c
DSTS_DEVCTRLHLT   = 1 << 22
# xHCI (host) regs, relative to drd (CAPLENGTH is at drd+0)
XHCI_HCSPARAMS1   = 0x04
XHCI_USBCMD_OFF   = 0x00            # from operational base
XHCI_USBCMD_RS    = 1 << 0
XHCI_USBCMD_HCRST = 1 << 1
XHCI_USBSTS_OFF   = 0x04
XHCI_USBSTS_HCH   = 1 << 0
XHCI_USBSTS_CNR   = 1 << 11
XHCI_PORTSC_BASE  = 0x400           # from operational base, port i at +0x10*i
PORTSC_CCS        = 1 << 0
PORTSC_PED        = 1 << 1
PORTSC_PP         = 1 << 9

def guard_on():  p.set_exc_guard(GUARD.RETURN | GUARD.SILENT)
def guard_off(): p.set_exc_guard(GUARD.OFF)

def gread32(addr):
    b = p.get_exc_count(); v = p.read32(addr); a = p.get_exc_count()
    return v, (a != b)

def gwrite32(addr, val):
    b = p.get_exc_count(); p.write32(addr, val); a = p.get_exc_count()
    return (a != b)

def poll(fn, want=True, n=200, delay=0.005):
    """Bounded poll: call fn() -> (bit_set, faulted); stop on match/fault/limit."""
    for i in range(n):
        ok, f = fn()
        if f: return ('fault', i)
        if ok == want: return ('ok', i)
        time.sleep(delay)
    return ('timeout', n)

def survey():
    guard_on(); rows = {}
    for n, r in PORTS.items():
        cap, fc  = gread32(r['drd'] + 0x00)
        gctl, fg = gread32(r['drd'] + DWC3_GCTL)
        dsts, fd = gread32(r['drd'] + DWC3_DSTS)
        prtcap = (gctl >> GCTL_PRTCAPDIR_SHIFT) & 3
        devspd = dsts & 0x7; linkst = (dsts >> 18) & 0xf
        up = not (fc or fg or fd)
        connected = up and prtcap == 2 and devspd == 0 and linkst == 0   # device, HS, U0
        rows[n] = dict(up=up, prtcap=prtcap, caplen=cap & 0xff, connected=connected,
                       devspd=devspd, linkst=linkst)
    guard_off()
    return rows

def stage_a(rows):
    print("\n=== Stage A: survey (read-only) ===")
    for n, s in rows.items():
        tag = "  <-- PROXY console (connected HS/U0) - NEVER touch" if s['connected'] else ""
        role = {1:'host',2:'device',3:'otg'}.get(s['prtcap'], '?')
        print(f"  port{n}: up={s['up']} role={role} caplen={s['caplen']:#x} "
              f"devspd={s['devspd']} linkst={s['linkst']:#x}{tag}")
    proxy = [n for n, s in rows.items() if s['connected']]
    free  = [n for n, s in rows.items() if s['up'] and not s['connected']]
    print(f"  -> proxy port(s): {proxy}   free port(s): {free}")
    return proxy, free

def stage_bc(n, proxy):
    r = PORTS[n]
    print(f"\n=== Stage B/C: flip port {n} to USB2 HOST ===")
    if n in proxy:
        print(f"  REFUSED: port {n} is the proxy console. Pick a free port."); return
    guard_on()
    # B: host SIG on the (already-up) USB2 PHY
    f = gwrite32(r['usb2phy'] + USB2PHY_SIG, 0x01c1000f | USB2PHY_SIG_HOST)
    sig, _ = gread32(r['usb2phy'] + USB2PHY_SIG)
    mux, _ = gread32(r['pipe'] + PIPE_MUX_CTRL)
    print(f"  SIG<-host: wrote(fault={f}) readback SIG={sig:#010x} (host bits {'set' if sig & USB2PHY_SIG_HOST else 'MISSING'}), mux={mux:#06x}")
    # C: stop gadget, core soft reset, set host, reset xHCI
    g, _ = gread32(r['drd'] + DWC3_GCTL)
    gwrite32(r['drd'] + DWC3_DCTL, (gread32(r['drd']+DWC3_DCTL)[0]) & ~DCTL_RUN_STOP)
    st, it = poll(lambda: (bool(gread32(r['drd']+DWC3_DSTS)[0] & DSTS_DEVCTRLHLT),
                           gread32(r['drd']+DWC3_DSTS)[1]))
    print(f"  gadget stop: DEVCTRLHLT {st} after {it}")
    gwrite32(r['drd'] + DWC3_GCTL, g | GCTL_CORESOFTRESET)
    time.sleep(0.01)
    g2 = (g & ~(3 << GCTL_PRTCAPDIR_SHIFT)) | (GCTL_PRTCAP_HOST << GCTL_PRTCAPDIR_SHIFT)
    g2 &= ~GCTL_CORESOFTRESET
    gwrite32(r['drd'] + DWC3_GCTL, g2)
    time.sleep(0.01)
    gctl, _ = gread32(r['drd'] + DWC3_GCTL)
    prtcap = (gctl >> GCTL_PRTCAPDIR_SHIFT) & 3
    print(f"  GCTL={gctl:#010x} prtcap={prtcap} ({'HOST' if prtcap==1 else 'not host'})")
    # xHCI
    cap, _ = gread32(r['drd'] + 0x00); caplen = cap & 0xff
    hcs, _ = gread32(r['drd'] + XHCI_HCSPARAMS1); maxports = (hcs >> 24) & 0xff
    op = r['drd'] + caplen
    print(f"  xHCI: caplen={caplen:#x} HCSPARAMS1={hcs:#010x} maxports={maxports} op={op:#x}")
    cmd, _ = gread32(op + XHCI_USBCMD_OFF)
    gwrite32(op + XHCI_USBCMD_OFF, cmd | XHCI_USBCMD_HCRST)
    st, it = poll(lambda: (not (gread32(op+XHCI_USBCMD_OFF)[0] & XHCI_USBCMD_HCRST),
                           gread32(op+XHCI_USBCMD_OFF)[1]))
    print(f"  HCRST self-clear: {st} after {it}")
    st, it = poll(lambda: (not (gread32(op+XHCI_USBSTS_OFF)[0] & XHCI_USBSTS_CNR),
                           gread32(op+XHCI_USBSTS_OFF)[1]))
    sts, _ = gread32(op + XHCI_USBSTS_OFF)
    print(f"  CNR clear (controller ready): {st} after {it}  USBSTS={sts:#010x}")
    # port power + status
    np = max(maxports, 1) if maxports and maxports < 8 else 2
    for i in range(np):
        pa = op + XHCI_PORTSC_BASE + 0x10 * i
        psc, fpre = gread32(pa)
        gwrite32(pa, psc | PORTSC_PP)
        time.sleep(0.01)
        psc2, _ = gread32(pa)
        print(f"  PORTSC[{i}] @ {pa:#x}: before={psc:#010x} after_PP={psc2:#010x} "
              f"CCS={'1 DEVICE PRESENT' if psc2 & PORTSC_CCS else '0 (nothing plugged in)'} "
              f"PED={(psc2>>1)&1}")
    guard_off()
    print("  (left in host mode; a reboot restores it. Plug a USB2 device into "
          f"port {n} and rerun to see CCS=1.)")

if __name__ == '__main__':
    rows = survey()
    proxy, free = stage_a(rows)
    if '--host' in sys.argv:
        n = int(sys.argv[sys.argv.index('--host') + 1])
        stage_bc(n, proxy)
