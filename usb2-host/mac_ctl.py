#!/usr/bin/env python3
# Autonomous control + recovery for the J714c over the m1n1 USB proxy.
# No human needed to power-cycle: m1n1 is the boot object, so a reboot (clean,
# or watchdog-forced, or m1n1's own reboot-on-exception) re-enumerates the USB
# proxy, and connect() finds it again on whichever /dev/ttyACM* it lands on.
import sys, time, glob
sys.path.insert(0, '/home/ed/dev/omarchy/forks/omacom-m1n1/proxyclient')
from m1n1.proxy import UartInterface, M1N1Proxy

WDT = 0x28836c000           # /arm-io/wdt reg0 (J714c); COUNT+0x10 ALARM+0x14 CTL+0x1c

def _devs():
    return sorted(glob.glob('/dev/ttyACM*'))

def connect(timeout=180):
    """Scan ttyACM* for a live m1n1 proxy. Returns (iface, p, dev) or None."""
    end = time.time() + timeout
    while time.time() < end:
        for dev in _devs():
            try:
                iface = UartInterface(dev)
                p = M1N1Proxy(iface)
                p.nop()
                return iface, p, dev
            except Exception:
                try: iface.close()
                except Exception: pass
        time.sleep(2)
    return None

def reboot_clean(p):
    try: p.reboot()
    except Exception: pass

def wdt_force(p):
    """m1n1 wdt_reboot(): short-fuse watchdog -> HW reboot. Use when the proxy
    still takes writes but a clean reboot won't stick."""
    try:
        p.write32(WDT+0x14, 0x100000); p.write32(WDT+0x10, 0); p.write32(WDT+0x1c, 4)
    except Exception: pass

def wdt_arm(p, alarm=0x8000000):
    """Backstop before a risky poke: if the proxy hard-hangs (can't run its own
    reboot-on-exception), the watchdog fires after ~alarm ticks and reboots."""
    p.write32(WDT+0x14, alarm); p.write32(WDT+0x10, 0); p.write32(WDT+0x1c, 4)
def wdt_disarm(p):
    p.write32(WDT+0x1c, 0)

def reset_and_reconnect(reconnect_timeout=180):
    c = connect(15)
    if c: reboot_clean(c[1])
    time.sleep(5)
    return connect(reconnect_timeout)

if __name__ == '__main__':
    print("connecting..."); c = connect(30)
    assert c, "no live proxy to start"
    iface, p, dev = c; print(f"live on {dev}")
    print("issuing clean reboot + reconnect (expect ~60-90s)...")
    reboot_clean(p); time.sleep(5)
    c2 = connect(180)
    if c2:
        print(f"RECONNECTED on {c2[2]} after reboot; drd2={c2[1].read32(0x382280000):#x}")
        print("AUTONOMOUS RESET OK")
    else:
        print("FAILED to reconnect")
