# USB4 item 1 — Apple Thunderbolt/USB4 host controller driver

No Linux driver exists for these on any Apple-silicon machine. This is a
from-scratch driver; the notes below are the controller map and the
architecture it needs, as a starting point.

## The controllers (J714c / M5 Max) — "acio,v2", three of them
Each USB-C port has one. Per controller: a main register block, a management
coprocessor (IOP), and an IOMMU (DART).

Port 0 (acio0):
    host regs   0x2a1f00000 size 0x100000, + 0x2a1ac0000 / 0x2a1ac4000 /
                0x2a1ac8000 / 0x2a1e44000 / 0x2a1c80000 (0x4000 each)
    IRQs        1591-1594
    IOP         acio-cpu0  ctrl 0x2a1108000, mbox 0x2a1100000  IRQs 837-840
    DART        dart-acio0 0x2a1a80000 (size 0xc000), + 0x2803f0000  IRQ 1606
Port 1 (acio1): host regs 0x2a9f00000 (+ 0x2a9ac0000 ...), IRQs 1623-1626
Port 2 (acio2): host regs 0x381f00000 (+ 0x381ac0000 ...), IRQs 1655-1658
(port N host base = port0 + N*0x8000000; same sub-window layout.)

## What the driver needs
- The IOP (`acio-cpu`, type `iop,mxwrap-acio`) is a mailbox coprocessor. Linux
  already has a base coprocessor-RPC layer (apple-rtkit) used for other Apple
  coprocessors; this driver builds on it to bring the IOP up and talk to it.
- On top of that: the Apple native-host-interface protocol for this controller
  (ring setup, path/tunnel management), which is new and has to be worked out.
- Thunderbolt/USB4 tunneling (PCIe/DP/USB3 over the link), tied into the Linux
  thunderbolt subsystem.
- The DART (`dart,t8110`) is already supported in Linux.

## Status
Controller map is known (above). The IOP RPC + the host-interface protocol +
tunneling are the work, and it is large — a real driver, not a patch. These
notes are the head start, not a working driver.

## Live note: controller registers are reset-gated
Reading the acio host/IOP registers cold hard-hangs the fabric (worse than a
clean fault - it does not self-recover). The controller's power domain + reset
release must be brought up before any register is readable, the same way the
PHY core needed power + release. The acio power domain is not a plain pmgr
label; it has to be found before a register survey is even possible. This is
part of the driver's init and reinforces that item 1 is full driver work.
