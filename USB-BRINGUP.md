# USB host bring-up on T6050 (M5 Max, J714c)

Goal: a working USB **host** port on the single-core Linux boot, for an external
keyboard / mouse / storage stick, without the tethered proxy. Source: the live
ADT (`j714c/dumps/j714c.adt`) and the macOS drivers in the kernelcache
(`kernelcache.mac17j.bin`). Nothing here is tested on hardware yet.

## Why USB doesn't work today

The USB **controller** is standard and already supported: `usb-drd,t6050`
(fallback `usb-drd,t8142`) is a dwc3 dual-role controller, and its IOMMU is
`dart,t8110`, a known DART. The blocker is the **Type-C PHY** in front of it,
`atc-phy,t6050` (fallback `atc-phy,t6040`), a new hardware generation with no
Linux driver. All three USB-C data ports go through this PHY, so until it
initialises, no port enumerates anything.

Scale of the new PHY (why the full driver is days-to-weeks RE): the ADT
describes it with **44 register windows** (vs ~5 on older gens) and new
calibration tables - `CIO4PLL_CORE`, `AUSPLL_CORE`, `AUS40CMN_SHM`, per-lane
RX/EQ blocks - consistent with a Thunderbolt-5-class PHY. Linux's `atc.c` only
knows the M1 generation (t8103/t600x, with `t8103_usb3_workaround` etc.), and
`dwc3-apple.c` lists only `apple,t8103-dwc3`. Feeding the driver the M5-Air
(t8142) description stalls at the first missing table and the controller never
starts.

## The bounded path: USB 2.0 only

USB 2.0 uses only the D+/D- pair, driven by a **small USB2 PHY block**, not the
high-speed superspeed/CIO lanes. Its entire init, from the ADT, is three
register writes:

```
tunable_USB2PHY_DFLT : off 0x20000008 val 0x00007003 mask 0x00000003
                       off 0x20000018 val 0x00000703 mask 0x00000103
tunable_USB2PHY_HOST : off 0x20000008 val 0x00007003 mask 0x00007003
tunable_USB2PHY_DEV  : off 0x20000008 val 0x00007003 mask 0x00000003
```

Contrast the high-speed PHY tables we would otherwise need: `CIO4PLL_CORE` (4
triples), `AUSPLL_CORE` (6 triples), plus the 44 windows and the per-lane RX/EQ
blocks. The USB2-only path skips all of that.

macOS supports this split directly: `AppleTypeCPhy` has a dedicated USB2
interface - `AppleTypeCPhy::createTypeCPhyUSB2Interface` and
`AppleTypeCPhyUSBInterface::usb2PhyPortReset(bool)` - separate from the USB3/CIO
path. So USB 2.0 is a first-class, self-contained sub-block, not a degraded
mode of the full PHY.

dwc3 runs USB2-only cleanly (it falls back to HighSpeed when no superspeed PHY
comes up). A USB-2 keyboard/mouse and most flash sticks work at 480 Mbps.

### Concrete steps
1. Add `usb-drd,t6050` (and `usb-drd,t8142`) to `dwc3-apple.c`'s OF table with
   per-chip data; the controller tunables are ADT-provided
   (`tunable_DRD_USB31_GBL_HOST`, `_CFG_HOST`, `LINK_REGS`, `PIPE_HANDLER`...).
2. Add a minimal `atc-phy,t6050` PHY driver (or extend `atc.c`) that implements
   **only** `PHY_MODE_USB2`: apply the three USB2 PHY tunables above and do the
   USB2 port reset (mirror `usb2PhyPortReset`), and report USB3/CIO/DP as
   unsupported so dwc3 proceeds in HighSpeed.
3. Set up the `dart,t8110` (`dart-usb0`) for the controller - the existing
   t8110 DART support covers it.
4. Boot with one USB-C port, confirm a USB-2 device enumerates.

## Hardware map (port 0 = `/arm-io/usb-drd0` + `/arm-io/atc-phy0`)

| Block | compatible | base(s) |
|---|---|---|
| USB controller (dwc3) | usb-drd,t6050 / t8142 | core 0x2a2280000 (0x11800), + 9 windows; IRQs 1419-1422 |
| Type-C PHY | atc-phy,t6050 / t6040 | 44 windows; USB2 PHY + AUSPLL at 0x2a0000000/0x2a0020000; main at 0x2a3040000 |
| IOMMU | dart,t8110 | 0x2a2f00000 (0xc000), 0x2a2f80000 |
| xHCI / AUSS | usb-auss,t6050 | 0x3953f0000; tunable_XHCI_CAPABILITY |

Three USB-C data ports: usb-drd0/1/2 + atc-phy0/1/2 + dart-usb0/1/2. atc-phy3 is
port-type 6 (the fixed HDMI/DP lane, `dp2hdmi-gpio0`), not a USB data port.

## macOS driver (RE target for the full PHY)
- `AppleT6050TypeCPhy` : AppleTypeCPhy  - the per-chip PHY driver.
- `AppleTypeCPhyCIO80PhyMBI` - the Converged-IO (Thunderbolt) 80G PHY block.
- Interfaces: `AppleTypeCPhyUSBInterface`, `AppleTypeCPhyCIOInterface`,
  `AppleTypeCPhyDisplayPortInterface`; mode enum `tACIOPhyMode`.
- Entry: `AppleTypeCPhy::start`; USB2: `createTypeCPhyUSB2Interface`,
  `usb2PhyPortReset`.

## Full USB3 / Thunderbolt path (deferred)
Reverse-engineer `AppleT6050TypeCPhy` + `AppleTypeCPhyCIO80PhyMBI` for the
superspeed/CIO lane bring-up: the CIO4PLL/AUSPLL PLL setup, the per-lane RX/EQ
calibration, and the dwc3<->PHY PIPE handshake `dwc3-apple.c` documents. This is
the days-to-weeks part; the `acio,v2` Thunderbolt controllers are beyond even
that. USB 2.0 above is the path that pays off now.

## Live probe results (2026-10-26, over the m1n1 USB proxy on /dev/ttyACM1)

Correction to the section above: the Linux PHY driver is **not** M1-only. The
aurora `atc.c` already supports the T8122/T8140/T8142 generations, with USB2
host SIG handling (`USB2PHY_SIG_HOST = 7<<12`) and the DUMMY pipehandler mux.
A port-0 device tree already exists, committed as
`t6050-j714c-usb.dtsi` ("not included yet"), wiring `apple,t6050-dwc3`
(falls back to `apple,t8103-dwc3`, which binds) and `apple,t6050-atcphy`
(falls back to `apple,t8142-atcphy`, which binds). Its header records why it
is shelved: the full T8142 description makes the PHY probe demand USB3/CIO
tunables (AUS40CMN, CIO4PLL, LN0/1_RX...) that this new PHY generation does
not ship, so the controller never binds.

What the live silicon shows (Stage A of `t6050_usb2_host_probe.py`):

| port | dwc3 role now | xHCI CAPLENGTH | pipehandler mux | DSTS | free? |
|---|---|---|---|---|---|
| 0 | device | 0x20 | 0x22 (DUMMY) | FS, link 0x3 (idle) | FREE |
| 1 | device | 0x20 | 0x22 (DUMMY) | HS, link 0x0 (U0) | **PROXY console - do not touch** |
| 2 | device | 0x20 | 0x22 (DUMMY) | FS, link 0x3 (idle) | FREE |

So m1n1 has all three T6050 USB-C ports up in **USB 2.0** right now, with the
SS pipe routed to the dummy PHY and **none** of the USB3/CIO tunables. This is
the direct proof that the USB2-only path is valid on M5 Max silicon: the PHY
work is just the two small blocks `usb2phy` (0x2a2a90000) and `pipehandler`
(0x2a2a84000), exactly what m1n1's `usb_phy_bringup()` touches.

The remaining unknown for a working **host** port: host mode must SOURCE VBUS
to the attached device, which is controlled by the Type-C PD chip
(`hpm0`, `apple,sn201202x` on SPMI), not by the PHY. A self-powered device
(powered hub) would enumerate without it; a bus-powered keyboard needs the PD
path. So the device tree's hpm/typec/role-switch nodes are load-bearing for
host VBUS and should not be stripped.

Proxy port = **1**. Free ports for a host test = **0 or 2**.

## Verdict: USB 2.0 host works on T6050 (host flip proven on the cable)

Flipping free port 2 to USB2 host over the proxy (Stage B/C of the probe):

```
SIG<-host:  SIG=0x01d0700f (host bits set), mux=0x0022 (DUMMY)
GCTL=0x30c11004 prtcap=1 (HOST)
xHCI: caplen=0x20 HCSPARAMS1=0x0200047f maxports=2
HCRST self-clear: ok   CNR clear (controller ready): ok   USBSTS=0x00000011
PORTSC[0] before reset: CCS=1 device present, FS
PORTSC[0] after  reset: 0x00200e03  CCS=1 PED=1 PLS=0(U0) speed=HS
```

A real high-speed device trained to HS and the port enabled on reset - that is
enumeration at the controller level, not a phantom. The USB2-only path drives
only usb2phy + pipehandler and needs none of the CIO tunables.

### The code (new files, nothing overwritten)
- `kernel/usb2-host/t6050-usb2-host.patch` - adds an `atcphy_hw_t6050` PHY
  generation (T8122 core, **T8103** pipehandler mux fields per the live 0x22,
  `optional_tunables = true`) + match entry, and `#include`s the existing
  `t6050-j714c-usb.dtsi`. `git apply --check` passes. dwc3 binds via its
  `apple,t8103-dwc3` fallback, no controller change.
- `kernel/usb2-host/t6050_usb2_host_probe.py` - the cable test. Stage A surveys
  all ports; `--host N` flips a free port to host and reads PORTSC. Auto-detects
  and refuses the proxy port (port 1).

### To finish (Ed's hardware)
1. `cd forks/linux-aurora && git apply kernel/usb2-host/t6050-usb2-host.patch`
2. Build the kernel + DTB, boot it over m1n1, USB2 device in port 0 or 2.
3. Expect the atcphy to probe ("SuperSpeed tunables missing, USB2 only") and the
   device to enumerate. Then replicate port 0's dtsi block for ports 1 and 2.

Open point: `has_usb4 = true` is kept from the t8142 base; a USB3/USB4/TBT
device would reach a path that wants the absent CIO tunables. USB2 devices are
unaffected. Revisit if SS devices misbehave.

## Result (2026-10-26 evening): USB 2.0 host works on ports 0 and 2

Update 2026-10-27 00:31: port 1 works too (linux-aurora `t6050-j714c-usb2.dtsi`,
usb-drd1 0x2aa280000, AIC 1451). Port map on J714c: left-back = port 0,
left-front = port 1, right = port 2 (matches the ADT hpm port-location). A
stick enumerates on every port at boot and when plugged in after login. One
failure seen: hot-plug into the port that had carried the proxy during that
boot (once, cause not isolated).

The kernel PHY patch above resets the SoC early; the route that works keeps
the PHY out of the kernel:

- Loader (omacom-m1n1 `src/usb.c`, `usb_t6050_host_prep`, called from
  `main.c` after `usb_iodev_shutdown`): for every port, port bring-up as for
  the proxy, usb2phy host bits (`USB2PHY_SIG` = 0x01c1000f | HOST), gadget
  stopped, core soft reset, port capability host, PIPE parked through the
  pipe handler (0x00 |= 5, 0x04 &= ~6), PHY auto-suspend off. Then PORTSC
  (op base + 0x400) is polled for CCS; without it the bring-up and flip are
  redone, three attempts in all (windows 50, 100, 100 ms). A port without a
  device stays in host mode after the last attempt. Measured in four
  recorded boots: the first flip never shows the plugged stick (not within
  1.5 s either, the port reads 0x2a0 until the kernel), the second cycle
  shows it at the first poll. Why the first cycle fails is open; candidates
  are the eUSB2 repeater (reset out of band by the PD chip, see
  dwc3-apple.c) and Apple's host tunables (usb-drd2
  tunable_DRD_USB31_GBL_HOST/CFG_HOST, atc-phy2 tunable_USB2PHY_DFLT
  register 0x18), which the loader does not apply.
- Record: `usb_t6050_host_record` (after `display_shutdown`) writes
  `/chosen/apple,t6050-usbprep`, four u32 per port: attempts, PORTSC after
  the prep, PORTSC before the jump, ms until CCS. `kboot_set_chosen_u32s`
  reopens the packed tree from a copy. The kernel prints it at
  subsys_initcall with `t6050_peek=` set (pmgr-pwrstate.c).
- Kernel: `t6050-j714c-usb2.dtsi` describes usb-drd0 (0x2a2280000, AIC 1419)
  and usb-drd2 (0x382280000, AIC 1483) as `generic-xhci` with their two
  DARTs each (ps_atc0_usb / ps_atc2_usb). `ps_atc0-3_cio` and
  `ps_atc3_common` are `apple,firmware-owned` in `t6050-pmgr.dtsi`: the
  kernel's power-on of those domains made the xHCI reset time out.
- Observed: PORTSC 0x206e1 at kernel entry, high-speed enumeration of a
  USB 2.0 stick (usb-storage, sda) on port 2, ~72 interrupts on AIC 1483 per
  boot; port 0 up with no device; 9 boots in a row (2026-10-26 19:00-19:35).
- Port 1 (the proxy cable) is flipped too; the proxy is over by then.

Not touched by this route: USB 3 and USB4 (the T6050 Type-C PHY generation,
see USB4-SCOPE.md), hot-plug after boot (untested), the PD controllers
(VBUS is sourced by their firmware).

## The kernel sets up the ports itself (2026-10-27 00:55)

linux-aurora `drivers/phy/apple/t6050-usb2.c` (`apple,t6050-usb2-phy`,
`CONFIG_PHY_APPLE_T6050_USB2`) does the loader's host prep in `phy_init()`,
which xhci-plat calls before its host controller reset. Windows per port:
usb2phy = atc-phyN reg 0, pipe handler = usb-drdN reg 3, core = usb-drdN
reg 0. Each `generic-xhci` node in `t6050-j714c-usb2.dtsi` has
`phys = <&usb2phy_N>`. A port is flipped up to three times until PORTSC
shows a connection; the driver logs "USB 2.0 host mode, PORTSC ... after N
flip(s)".

Checked on J714c (stick in port 1, proxy cable in port 2):

| Loader | Record | Port 0 | Port 1 | Port 2 |
|---|---|---|---|---|
| prep skipped (`-DT6050_NO_HOST_PREP`), ports 0+1 | zeros | 0x2a0 | stick, sda | not described |
| prep skipped, all ports | zeros | 0x2a0 after 3 flips | 0x206e1 after 1 flip, sda | 0x2a0 after 3 flips, binds |
| prep done (EFI stage 2 behaviour) | port 1 CCS | 0x2a0 after 3 flips | 0x206e1 after 1 flip, sda | 0x2a0 after 3 flips |

The kernel's first flip finds a device present at power-on; the loader's
first flip never did. Port 2, the port that carried the proxy, binds without
the earlier xHCI reset timeout. Not checked yet: hot-plug into the proxy
port with this driver, and the EFI partition still carries the older kernel.

## SuperSpeed side: atcN_cio breaks the xHCI; the PHY does not need it (2026-10-27 09:57)

Port 1 (left-front, stick plugged in, proxy cable on port 2), over the stage 1
proxy with `tools/t6050_phy_power_test.py`. After each step the port is flipped
to USB2 host the way `t6050-usb2.c` does it, then HCRST, CNR and PORTSC are read.

| step | PHY power ctrl / stat | USB2 host |
|---|---|---|
| none (control) | 0x04 / 0x100 | CCS on flip 1, CNR clears |
| `auss` on (pmgr0 +0x248) | - | works |
| `atc1_cio` on (pmgr0 +0x290) | - | **CNR stuck (USBSTS 0x801), no CCS, GSTS CSR timeout** |
| + `atc1_cio_usb`, `atc1_cio_auss` | - | still broken |
| no CIO; sleep small, sleep big | 0x07 / 0x103 | works |
| no CIO; unclamp, APB reset, PHY reset | 0x1b / 0x103 | works |
| no CIO; common init on core+0xc / +0xa00 | core+0xc 0x1003f33a, +0x804 0x19 | works |

- `atc1_cio` alone breaks the controller reset. The pipe handler, usb2phy and
  dwc3 PHY config registers do not change when it powers on; leaving the USB2
  PHY untouched or letting the USB3 PIPE suspend does not help.
- The PHY power control is atc-phy1 reg[39] (0x2ab200000; port 0 0x2a3200000),
  readable with only `atc1_common` / `atc1_usb_aon` / `atc1_usb` on. Its bits
  match `ATCPHY_POWER_CTRL` in atc.c (sleep small 0, sleep big 1, clamp 2, APB
  reset 3, PHY reset 4), and STAT at +4 acks the sleep bits (0x100 -> 0x103).
- With `atc1_cio` off the PHY wakes, the core (atc-phy1 reg[2], 0x2ab000000) is
  reachable and the common block initialises, and USB2 keeps working throughout.
  This matches t8103/t8112/t8122, where the PHY sits in `ps_atcN_usb` and
  `ps_atcN_cio` belongs to the CIO (USB4) side.
- Port 1 is +0x8000000 from port 0 for the PHY windows (ADT atc-phy1), as for
  usb-drd1.
- `atc1_usb_aon` / `atc1_usb` / `atc1_phymxwrap` are in pmgr2 (0x288300000),
  `atc1_common` / `atc1_cio*` / `auss` in pmgr0 (0x280600000).

Next for USB3: the t8122 USB3 path (`atcphy_configure_pipehandler_usb3_host_t8122`)
uses the BIST block at core+0x17000; T6050 has no window there, so its location
is open. A SuperSpeed device is needed on port 1 for the link test.

## USB3 trial at the t8122 offsets: no link (2026-10-27 10:10)

Port 1 with a USB3 device in it (Ed, 10:00). The device is seen on the USB2
side (PORTSC[0] CCS=1); the USB3 port stays in RxDetect (PORTSC[1] 0x2a0).
Sequence, both orientations, from `tools/t6050_phy_power_test.py`: PHY power
control 0x1b, common init, then the ADT tunables at the windows in Ed's
bring-up doc (COMMON_CFG reg[43], FABRIC reg[40], AXI2AF reg[41] 0x2a8000000,
AUS40CMN_SHM reg[5], AUSPLL_CORE reg[8]: 148 entries, no faults; USB2 still
works after them), lane mode / crossbar at the t8122 spots, pipe handler to USB3
as `atcphy_configure_pipehandler_usb3` does it without the BIST step.

- core+0x60 / +0x64 are not the lane mode / crossbar on T6050: writes read back
  0, except bit 0 of +0x64.
- The lane-swap bit at power block +8 bit 2 sticks (0x1800 -> 0x1804), like
  `ATCPHY_MISC_LANE_SWAP`.
- Pipe handler: the PIPE lock is never acknowledged; MUX_CTRL takes clock OFF and
  data USB3 but not the USB3 clock select (reads back 0). Consistent with no
  USB3 PIPE clock from the PHY while its lanes are not configured.
- PORTSC[1] stays 0x2a0 (RxDetect), also after a warm reset.
- The first window (core+0x0-0x400) does not have the t8103 or t8122 layout:
  two blocks of the same shape at +0x80 and +0xd0, 0x50 apart.

Missing for a USB3 link: the T6050 lane mode / crossbar registers and the
USB3 BIST/PHY override block.

## T6050 AUSPLL locks; common block = ACIOPHY_CFG0 at core+0xc (2026-10-27 10:18)

Port 1, `tools/t6050_phy_power_test.py`, same base as above (PHY power control
0x1b, ADT tunables, USB2 host flip). USB2 keeps working throughout.

Common block wake (`wake`): `atcphy_wake_common_t8122` with ACIOPHY_CFG0 at
core+0xc instead of +0x8, same bits (BIG 0, BIG_OV 1, SMALL 2, SMALL_OV 3,
CLAMP 4, CLAMP_OV 5), bias BGBIAS_OV at core+0xa00 bit 1, RCAL done at
core+0x804 bit 0 (reads 0x19). CFG0 ends at 0x1003f32f. The common-init in
`usb3-usb4/t6050-usb3-usb4-bringup.md` matches this up to the RCAL read; its
last four steps (clear BGBIAS_OV, set CLAMP, clear BIG and SMALL) put the
common block back to sleep (CFG0 0x1003f33a).

AUSPLL start (`pllstart2`): `atc_t8122_tunnel_start`'s PLL steps with the
AUSPLL registers at +0x1000 (APB command core+0x3000, CLKOUT_MASTER +0x3200,
BGR +0x3218, FREQ_CFG +0x3234), frequency descriptor left as found
(+0x3080 0x298d8190, +0x3084 0, +0x3088 0x550800):

    APB 0x10000001 -> ack (0x10000003)
    lock: core+0x7034 bit 3 set (0x8), as T8122_DP_PCLK_STATUS
    APB 0x10010000 -> ack low

core+0x7044 stays 0. Without the common wake the APB command is acked but the
PLL does not lock.

Writable-bit map of core+0x0-0x400 (write ones, write zero, restore; no hang):
`log/t6050-port1-core-wmap-0-400.txt`. Not writable: +0x0, +0x4, +0x60.
Field-shaped candidates: +0x170 (18 bits, reset 0x12492 = six 3-bit fields of
2), +0x038 and +0x13c (18 bits), +0x064 (4 bits), +0x010 (9 bits), +0x120.

Sweep (`sweep`, 120 combinations, run with the PLL off and again with it
locked): +0x170 in {0x9249, 0, 0x36db, 0x12489, 0x12492} x crossbar
candidates +0x38 / +0x13c in {0x110, 0x10, 0xa, 0x111} and +0x64 in 0-15.
No combination made the pipe handler accept the USB3 clock or moved the USB3
port out of RxDetect.

Still missing for a USB3 link: the lane mode / crossbar registers and the
USB3 BIST/PHY override block. The pipe handler refuses the USB3 clock select
in every state tried.

## Pipe handler MUX_CTRL is the T8142 layout; PIPE routes to USB3 (2026-10-27 10:22)

`muxmap` writes 0x00-0x7f to PIPEHANDLER_MUX_CTRL (port 1, pipe handler
0x2aaa84000) and reads back: only bits [1:0] and [6:4] are implemented, before
and after the PLL lock. That is the T8142 field layout (clock [6:4], data
[1:0]); bit 3, the T8103 clock field's low bit, does not exist. The boot value
0x22 is clock 2 / data 2 in that layout. `atcphy_hw_t6050` in
drivers/phy/apple/atc.c uses the T8103 fields. The earlier USB3 attempts above
wrote clock USB3 as 0x08 and could not stick for this reason.

With the T8142 layout (clock off, data 0, clock 1 -> MUX_CTRL 0x10) the mux
takes USB3 and holds it, with the AUSPLL locked. Then:

- A controller reset with the PIPE on USB3 (`hcreset`: dwc3 core soft reset,
  host, HCRST) does not complete: CNR stays set (USBSTS 0x801), GSTS CSR
  timeout. No PIPE clock from the USB3 PHY.
- `sweep2`: the 120 lane-mode / crossbar combinations from the sweep above,
  each followed by that reset with the PIPE on USB3: CNR never clears, the
  USB3 port stays in RxDetect.
- PIPE lock (LOCK_REQ/ACK +0x10/+0x14) is acknowledged only while the dwc3 is
  in device mode (the stage 1 state), not in host mode after HCRST.

Missing for a USB3 link: the setting that makes the USB3 PHY lane deliver the
PIPE clock (lane mode / crossbar, the USB3 BIST/PCS enable, or the lane power
registers core+0x10 / +0x120).
- `sweep3`: lane power candidates core+0x10 in {0x1ff, 0x1, 0x3, 0x7, 0xf,
  0x3f, 0xff, 0x155, 0xaa} x core+0x120 in {reset 0x15540fcc, 0x1fffffff, 0,
  reset | 0xfff, reset & ~0xfff} x core+0x170 in {reset, 0x9249}, PIPE on USB3,
  PLL locked: 90 combinations, CNR never clears.

## Lane mode core+0x6c, PCS block core+0x29000: no PIPE clock (2026-10-27 10:58)

From Ed's updated `usb3-usb4/t6050-usb3-usb4-bringup.md`: lane mode at
core+0x6c bits [4:2] / [7:5] (USB3 values 2 or 7 per field), PCS/BIST enable at
core+0x29004 bit 0. Port 1, PHY up, tunables, common wake, AUSPLL locked.

- core+0x29000 (ADT window 35) is in the `atc1_cio` domain: with it off the
  first read hung the SoC (the 90 s watchdog rebooted it to the stage 1
  proxy); with `atc1_cio` + `atc1_cio_usb` on it reads 0x29004 = 0xe00 and
  bit 0 sets.
- `sweep4` and `u3loop`: [4:2] in {2, 7} x [7:5] in {2, 7} x lane swap (power
  block +8 bit 2), PCS enable, PIPE on USB3 (mux 0x10). `u3loop` follows
  dwc3-apple's order: dwc3 core soft reset, the glue CIO registers (+0xcd38
  0x0f800f80, +0xcd3c 0x0fc00fc0, +0xcd40 0x140a10), host, SUSPHY on, PIPE
  switch under the lock, then HCRST. All 8: PIPE lock not acknowledged, CNR
  stays set (USBSTS 0x801), USB3 port in RxDetect.
- With `atc1_cio` on, the controller does not finish a reset even for USB2
  only (dummy PIPE). Cycling the dwc3 block reset (pipe handler AON_GEN
  RESET_N bit 0 / FORCE_CLAMP_EN bit 4, as `atcphy_dwc3_reset_assert/deassert`)
  or setting the PCS enable does not change that.

The blocker for USB3: what lets the controller complete its reset once the
CIO domain is on, which the PCS block in that domain needs. PCS block contents
with CIO on are dumped above (`core:29000-29200`): +0x2905c 0x06712220,
+0x290c4/c8 0x28008, +0x29104 0x104, +0x29144 0x21001a21, ...
