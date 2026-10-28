# T6050 USB-C PHY register reference (Linux atcphy driver)

Hardware documentation for the Apple Type-C PHY on the M5 Max (T6050, board
J714c), written to support the mainline/Asahi-style Linux `phy-apple-atc`
driver on a machine the author owns. This is interoperability documentation:
it records the PHY's register layout and the settings it needs so the open
Linux driver can bring the USB-C ports up. Nothing here concerns a security
mechanism; the PHY is an ordinary on-chip hardware block and these are its
documented register values, cross-checked against the platform's own driver.

The values below are authoritative for T6050 and supersede the t8142-by-analogy
guesses in the earlier loader table and device tree.

## Register-window model

The PHY exposes its sub-blocks as a set of indexed register windows. A tuning
group is written to one window: each entry is `(offset, mask, value)` applied
as a read-modify-write at `window_base + offset`. The window index equals the
device-tree `atc-phy` reg index, so index N is ADT reg[N]. The 44 windows for
port 0 (addresses are physical):

| idx | base | idx | base |
|---|---|---|---|
| 0 | 0x2a2a90000 (usb2phy) | 8 | 0x2a3003200 |
| 1 | 0x2a2800000 | 10 | 0x2a3003a00 |
| 2 | 0x2a3000000 (core) | 16 | 0x2a3009000 (lane0) |
| 3 | 0x2a3000400 | 18 | 0x2a300b000 |
| 5 | 0x2a3000a00 | 20 | 0x2a300d000 |
| 25 | 0x2a3019000 (lane1) | 40 | 0x2a3244000 |
| 27 | 0x2a301b000 | 41 | 0x2a0000000 |
| 29 | 0x2a301d000 | 42 | 0x2a0020000 |
| | | 43 | 0x2a3250000 |

Ports 1/2/3 are the same windows at +0x800000 / +0xe0000000 / +0xe0800000.

## Tuning-group register map

Every `(register, mask, value)` entry is in `t6050-phy-tunable-map.txt`.
Summary of where each group lands:

| group | idx | absolute base | note |
|---|---|---|---|
| USB2PHY DFLT/HOST/DEV | 0 | 0x2a2a90000 | USB2 (already working) |
| AXI2AF (+WR_DIS,+LOCK) | 41 | 0x2a0000000 | 75 entries |
| AXI2AF_LIOA | 42 | 0x2a0020000 | |
| FABRIC | 40 | 0x2a3244000 | 65 entries |
| COMMON_CFG | 43 | 0x2a3250000 | 1 enable bit |
| AUS40CMN_SHM | 5 | 0x2a3000a00 | |
| AUSPLL_CORE | 8 | 0x2a3003200 | the USB3 PLL |
| CIO4PLL_CORE | 10 | 0x2a3003a00 | the USB4/TBT PLL |
| LN0/1_RX_TOP_CIO | 16/25 | 0x2a3009000 / 0x2a3019000 | |
| LN0/1_RX_EQ | 18/27 | 0x2a300b000 / 0x2a301b000 | |
| LN0/1_RX_CFG_TX_OF_RXCLK | 20/29 | 0x2a300d000 / 0x2a301d000 | |
| UC_REGS_CIO | 3 | 0x2a3000400 | empty in J714c |

### Corrections this forces on the earlier drafts
- **PLL offsets were wrong by 0x1000.** AUSPLL is core+0x3200 (not 0x2200),
  CIO4PLL is core+0x3a00 (not 0x2a00). The t8142 analogy does not hold.
- **Lane layout differs from t8142.** lane0 at core+0x9000/0xb000/0xd000,
  lane1 at core+0x19000/0x1b000/0x1d000 (not 0x10000/0x11000/0x12000).
- **Four groups target blocks the Linux device tree does not map:**
  AXI2AF -> 0x2a0000000, LIOA -> 0x2a0020000, FABRIC -> 0x2a3244000,
  COMMON_CFG -> 0x2a3250000. None are inside the dtsi "core" (0x2a3000000,
  size 0x4c000) or "axi2af" (0x2a2800000) windows. The dtsi reg windows and
  the driver's region mapping need rework for T6050; a tuning table alone is
  not enough. The earlier loader-table offsets are superseded by the map above.

## Which groups each mode applies
- Every mode (global set): AXI2AF (+WR_DIS, +LOCK_LOCK), FABRIC, COMMON_CFG,
  AXI2AF_LIOA, and per-lane RX_CFG_TX_OF_RXCLK + RX_EQ.
- USB3 adds: AUS40CMN_SHM, AUSPLL_CORE.
- USB4/Thunderbolt adds: AUSPLL_CORE, AUS40CMN_SHM, CIO4PLL_CORE, UC_REGS_CIO,
  LN0/1_RX_TOP_CIO, LN0/1_RX_EQ_CIO.
- USB2: USB2PHY_DFLT then DEV or HOST, at idx 0.

## Bring-up sequence

All register traffic is 32-bit MMIO read-modify-write on `window_base + offset`.
A stage caches a window base in a driver field and adds an offset; the field
maps to a window index by `idx = (field - 0x210) / 0x20`, and idx is the ADT
reg index (e.g. field 0x250 -> idx 2 -> core 0x2a3000000). `decode-stage.py`
(saved here) prints a stage's writes as `idxN core+off op val`.

Stages (addresses are offsets into the driver, as breadcrumbs for the next
analysis pass):
- common-block init, PHY init (parts A/B/C), power-up reset, reset release,
  efuse load
- the tuning-group appliers (the maps above)
- crossbar config, lane-mode select, lane RX power-up, lane TX power-up
- controller-to-PHY pipe interface setup
- USB4/Thunderbolt only: load the PHY management-core firmware, with its
  reset-assert / reset-release / idle steps

### Decoded so far
- common-block init: core+0xc |= 0x4, |= 0x8, |= 0x1, |= 0x2 (enable/reset
  bits 0-3), then the AUS40CMN_SHM group.
- lane RX power-up: writes core+0x10.
- lane TX power-up: writes core+0x120.
- PLL lock is read on core+0x7044, bit 3 (the same AUSPLL lock bit the Linux
  driver already uses for other generations).
- USB4/Thunderbolt firmware load happens in PHY init part C.

### What remains
A systematic pass with `decode-stage.py` extended to also capture reads,
poll loops (read-until-bit), and the conditional structure, run over every
stage, plus the stage ordering. The register model, the MMIO primitives, the
window map, and all tuning values are in hand, so this is mechanical extraction.

## Linux wiring (patches, compile-tested, not yet boot-tested)

The register data above is now wired into two patches. Both apply cleanly and
compile (the loader object; the driver object and the device tree):

- `t6050-usb4-m1n1-tunables-v2.patch` (loader) - adds the T6050 tunable table
  with the correct offsets from the map above, a compat branch, and the fuse
  entry. Supersedes v1, whose offsets were guessed from the t8142 layout and
  are wrong (PLLs off by 0x1000, wrong lane stride, wrong axi2af window).
- `t6050-usb4-linux-phy.patch` (driver + device tree) - repoints the device
  tree "axi2af" window to 0x2a0000000 (where the AXI2AF tuning lives) and
  extends "core" to 0x254000 so FABRIC (+0x244000) and COMMON_CFG (+0x250000)
  fall inside it. That span overlaps the DisplayPort window (0x2a3050000), so
  the DisplayPort window is dropped for the USB-only port and the driver is
  taught to treat it as optional (one line in the resource loop).

This is the data-and-wiring foundation for USB3 SuperSpeed: the driver's
existing USB3 PLL path now has the correct tuning values at the correct
registers, and the regions it reads are mapped. Still required before USB3
links, and testable only on hardware:
- the exact init ordering for this PLL generation (the sequence work),
- a boot test (the PLL offsets and the region rework are unverified on silicon),
- note that DisplayPort alt-mode is disabled by this wiring.

Not addressed here (separate, large drivers): the PHY's embedded-controller
firmware load for USB4, and the Thunderbolt host controllers (no Apple-silicon
driver exists in Linux yet). USB4/Thunderbolt needs both.

## Init sequence - decoded (partial, from the stage functions)

Each stage is read-modify-write + poll. Decoded so far (seqdec.py):
- common-block init: core+0xc, set bit 2, bit 3, bit 0, bit 1 in turn, each
  followed by a readback/poll - the common-block enable handshake.
- lane RX power-up: core+0x10 RMW + poll (x2).
- lane TX power-up: core+0x120 RMW + poll (x2).
- PLL lock: read core+0x7044, bit 3.

Remaining to finish the USB3 sequence: a clean decode of every stage (exact
poll bits and write values), the stage dispatch order, and translation into the
driver's SuperSpeed path. This is iterative and needs a boot to validate PLL
lock and timing - it cannot be fully settled offline.

## Honest scope of the full USB4 stack
- USB2: works today.
- USB3: data + region wiring done and compiling; init sequence partial (above).
  Finishing it is hardware-iterative.
- USB4 PHY management-core firmware: located (loaded in PHY init part C); needs
  the firmware image, the load protocol, and a driver. Substantial.
- USB4/Thunderbolt host controllers (acio): no Apple-silicon driver exists in
  Linux on any chip. From-scratch major driver (native host interface, DMA
  rings, tunneling). Not producible as working code from here.
- Type-C PD controller: adaptable from the existing tps6598x driver, but alone
  leaves the ports at USB2.

## Autonomous control (mac_ctl.py) + live-confirmed reset/power step

`mac_ctl.py` (saved here) gives unattended control of the board over the proxy:
scan-and-connect across /dev/ttyACM*, clean reboot, watchdog force-reboot
(wdt base 0x28836c000), a pre-poke watchdog backstop, and reconnect-after-reboot.
Tested: it rebooted the board and reconnected on its own (the proxy came back on
a different ttyACM, which the scan handles). m1n1 also reboots itself on an
unhandled exception, so a bad access self-recovers. No human needed to power-cycle.

Live-confirmed on free port 0 (proxy was on port 2):
1. Power the domains - all were OFF (firmware does not pre-power them):
   atc0_common 0x280600208, atc0_cio 0x280600280, atc0_cio_usb 0x280600340,
   atc0_cio_auss 0x280600348 (write target 0xf in [3:0], poll actual 0xf in [7:4]).
2. Deassert the ATC reset at the reset controller **0x2a3200000** (window idx 39):
   set bit 3 (APB reset release) then bit 4 (main reset release); it read 0x4 and
   went to 0x1c. (assert = clear those bits.)
3. The core at **0x2a3000000 is then reachable** - AUSPLL (core+0x3200), CIO4PLL
   (core+0x3a00), lock (core+0x7044) and cmn ctl (core+0xc) all read cleanly
   (all zero = blocks reset, ready for bring-up). Before this step the core
   SError'd; this is the gate that was failing.

This is why powering the CIO domains alone (as the kernel did) timed out: the
reset was never released. Power + reset-deassert is the prerequisite, now proven.

### Next (now safely iterable live, with autonomous recovery)
4. common-block enable (core+0xc bits, with polls), 5. apply the tunables at
their core offsets, 6. the AUSPLL enable sequence, 7. poll lock at core+0x7044
bit 3. Each step can be tried on the cable and any hang self-recovers.
