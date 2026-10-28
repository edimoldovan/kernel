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

## Pipe-clock switch at power block +0x14: status never completes (2026-10-27 11:10)

Ed's bring-up doc step 7: pipe-clock switch at the PHY power block +0x14
(port 1 0x2ab200014), clear 0x2039, select << 3 (2 or 7), status at +0x18.
Power block before power-up: +0x14 0, +0x18 0, +0x2c 1; after (0x1b): +0xc 0x8.

- +0x14 takes the select (0x10 for 2, 0x38 for 7) and bits 0 / 13; +0x18
  stays 0 within 50 ms for select 2 and 7, alone and with bit 0, bit 13 or
  both (`pclkvar`).
- `u3doc`: USB2 host up first, then `auss` + `atc1_cio` + `atc1_cio_usb`, AUSPLL
  locked, then per try: lane mode core+0x6c, the switch, PCS enable
  core+0x29004 bit 0 (core+0x29110 reads 0), dwc3 core reset + glue CIO
  registers + host + SUSPHY on, PIPE to USB3 under the lock, HCRST. Select
  {2, 7} x [4:2] {2, 7} x [7:5] {2, 7} x swap: 16 tries, PIPE lock never
  acknowledged, CNR stays set, USB3 port in RxDetect.

Open: what completes the switch (+0x18 never changes) before the controller can
leave reset with the CIO domain on.

## What CIO power-on changes: register diff (2026-10-27 11:40)

Port 1, `tools/t6050_phy_power_test.py` `dump:` over every atc-phy1 ADT window
(up to 0x1000 bytes each) plus dwc3 globals (+0xc100) and the Apple glue
(+0xcd00): A with CIO off (PHY up, tunables, PLL locked, USB2 host working),
B after `auss` + `atc1_cio` + `atc1_cio_usb` on, C after a controller reset
attempt. Diff (`tools/t6050_dump_diff.py`): `log/t6050-port1-cio-diff.txt`.

Reads that hang with CIO off: window 35 (core+0x29000, PCS) at its first word,
window 34 (core+0x28400) partway in; window 34 also hangs partway with CIO on.
Every other window reads with CIO off.

A -> B, on CIO power-on alone:
- dwc3 GSTS (+0xc118) bit 5 (CSR timeout) sets at once.
- The Apple glue registers drd+0xcd28 / +0xcd2c (0x886), +0xcd40 (0x3c20060c),
  +0xcd44 (0x2000b) read 0; with CIO on they ignore writes (read back 0).
- The ATC_FABRIC registers (core+0x244000 ...) that the tunables set fall back
  to 0x80000000: the FABRIC tunables have to go in after CIO power-on.
B -> C: the controller's own registers (GHWPARAMS area, TX/RX FIFO sizes)
read 0 and usb2phy SIG loses bit 20 - the controller is not answering.

Re-applying the FABRIC tunables after CIO power-on restores their values but
not the controller (CNR still stuck). The PMGR registers of `atc1_usb`,
`atc1_usb_aon`, `atc1_phymxwrap` show no reset or disable bit with CIO on.

Open: what keeps the glue block at drd+0xcd00 and the controller's register
interface alive once `atc1_cio` is on.

## Reorder test: CIO-first + tunables-after is NOT the fix (2026-10-27 12:21)

Advisor's discriminating test. Fresh boot, port 1, `tools/t6050_phy_power_test.py
read cio tunables wake pllstart2 flip`: power ALL five domains including
`atc1_cio` FIRST, PWR reset release 0x1b, THEN apply every tunable (FABRIC
reg[40], AXI2AF reg[41], COMMON_CFG reg[43], AUS40CMN reg[5], AUSPLL reg[8]) so
FABRIC lands after CIO is on, then common wake, AUSPLL, USB2 host flip.

- All tunables apply with 0 faults after CIO-on (FABRIC 65, AXI2AF 75).
- Common block wakes (core+0xc 0x1003f33a -> 0x1003f32f, RCAL 0x19).
- AUSPLL locks with CIO on: core+0x7034 bit 3 set; core+0x3200 0x81554 ->
  0x81d5c (PCLK driver bit 3 + REFBUF bit 11 both set).
- flip: USB2 does NOT come up - PORTSC 0x2a0 (RxDetect), CCS timeout on all
  three attempts. HCRST self-clears (USBCMD 0) but CNR never clears
  (USBSTS 0x801 = HCHalted + CNR). Both ports PORTSC 0x2a0.

So the controller halt with CIO on is NOT an ordering problem: CIO-first with
full re-init in the correct order still halts the controller and breaks USB2.
This confirms the old "CIO-on breaks USB2" note and rules out ordering. The
glue block drd+0xcd00 is gated while CIO is on (diff: ignores writes), and that
gating - not tunable/FABRIC ordering - is what halts the controller.

Two open directions:
1. What un-gates the glue block drd+0xcd00 when atc1_cio is on (candidate: the
   acio-phy-cpu management core start at 0x2ab140040 bit 0, port 1).
2. Question the premise that USB3 needs atc1_cio at all. USB3's tunables are
   only AUS40CMN + AUSPLL (no CIO tunables); the catch-22 ("PCS at core+0x29000
   needs CIO, CIO breaks the controller") rests on the PCS block being required
   for the USB3 PIPE clock, which is a t8122-analogy assumption, not confirmed
   for the USB3 host path on T6050.

## (RETRACTED below - zero-read artifact) USB3 CIO-OFF with per-lane tunables (2026-10-27 12:35)

NOTE: the "CNR clears" in this section is a FALSE PASS - see the retraction at
the end of the file (12:45). The controller stops answering (reads 0) when the
MUX goes to USB3; a CNR=0 poll reads that 0 and reports ready. The per-lane
tunables and lane mode are real and apply cleanly, but USB3 is NOT solved.

Fresh boot, port 1,
`tools/t6050_phy_power_test.py pd:auss small big unclamp apb phyrst tunables
tunx wake pllstart2 flip u3clean` - atc1_cio / cio_usb / cio_auss stay OFF the
whole run, so the controller is never halted and core+0x29000 is never touched.

New vs every prior attempt: the `tunx` step applies the every-mode per-lane
tunables the old `tunables` step omitted -
  tunable_LN0_RX_EQ_DFLT         reg[18] 0x2ab00b000 (3)
  tunable_LN0_RX_CFG_TX_OF_RXCLK reg[20] 0x2ab00d000 (4)  <- lane TX clocking
  tunable_LN1_RX_EQ_DFLT         reg[27] 0x2ab01b000 (3)
  tunable_LN1_RX_CFG_TX_OF_RXCLK reg[29] 0x2ab01d000 (4)
  tunable_ATC0AXI2AF_LIOA        reg[42] 0x2a8020000 (5)
then lane mode core+0x6c ([4:2],[7:5]) and the PIPE switch to USB3 (mux 0x10,
T8142 layout) under the pipehandler lock.

Result (`u3clean`, all 8 combinations of [4:2]/[7:5]/swap):
- flip baseline: USB2 CCS ok, CNR clears (USBSTS 0x11). Controller alive.
- u3clean: PIPE lock ACKs (lock ok), mux holds USB3 (reads 0x10), and
  **CNR clears (USBSTS 0x0)** in all 8. In every earlier CIO-on attempt the
  lock never ACKed and CNR stayed set (USBSTS 0x801).

The PIPE lock ACK + CNR clear with the mux forced to USB3 is the oracle for
"the PHY delivers a USB3 PIPE clock" (with no clock the lock cannot ACK and CNR
sticks). So the two things that were missing all along:
1. the per-lane RX_CFG_TX_OF_RXCLK + RX_EQ_DFLT tunables (never applied before);
2. NOT powering atc1_cio (which only ever halted the controller; USB3 does not
   use it - the PCS block at core+0x29000 is a USB4/CIO block, not a USB3 one).

Still to confirm a live SuperSpeed LINK: a USB3 device in port 1 and a full SS
port bring-up (set PP, watch PLS RxDetect->Polling->U0). PORTSC[0] showed a
USB2 device present; whether it is USB3-capable is unknown. The PHY-level
blocker (PIPE clock / controller-ready) is solved regardless.

## RETRACTION: the 12:35 "CNR clears" was a zero-read artifact (2026-10-27 12:45)

Re-ran `u3clean` reading GSNPSID (drd+0xc120) and CAPLENGTH (drd+0x0) - both
non-zero on a live dwc3 - before and after the USB3 switch:

- baseline (dummy PIPE, after USB2 flip): SID 0x33313130, CAPLEN 0x1100020,
  GSTS 0x7e800001, USBSTS 0x11 (HCH 1). Controller alive.
- after MUX -> USB3 (0x10) + HCRST: SID 0x0, CAPLEN 0x0, GSTS 0x0, USBSTS 0x0.
  The whole dwc3 register interface stops answering.

So CNR did not "clear" - the register read 0, and `poll(USBSTS, bit 11 == 0)`
passes on 0 because bit 11 of 0 is 0. Same hazard hid in the HCRST self-clear
poll. The harness could not tell "ready" from "dead". USB3 is NOT solved.

POLL HAZARD (for whoever continues): never trust a CNR=0 / bit-clear poll
alone. Always confirm the controller is answering by reading GSNPSID
(drd+0xc120) and CAPLENGTH (drd+0x0); both are non-zero on a live dwc3.

What is actually established:
- CIO-off, the per-lane tunables (RX_EQ_DFLT reg 18/27, RX_CFG_TX_OF_RXCLK
  reg 20/29) and ATC0AXI2AF_LIOA (reg 42) apply with 0 faults; AUSPLL locks;
  lane mode core+0x6c is writable; USB2 host works. These are correct
  groundwork but not sufficient for a USB3 PIPE clock.
- Switching the MUX to USB3 with this sequence KILLS the controller's register
  clock (reads go to 0). This differs from the 10:22 `hcreset` result, where
  after the switch the controller still answered and CNR stuck at 0x801
  (answering, not ready). So something in the 12:35 switch path - the
  pipehandler override bits 0/2, the glue writes drd+0xcd38/cd3c/cd40, the
  c704/c200/c2c0 writes, or the lock-before-switch - gates the controller's
  register clock, on top of the original no-PIPE-clock problem.

Open, unchanged: what makes the USB3 PHY lane deliver the PIPE clock so the
controller leaves reset answering. The CIO premise is still worth doubting
(USB3's tunables are non-CIO), but neither the CIO-on nor the CIO-off switch
path has produced a live controller on USB3.

## Staged isolation: HCRST is the killer, i.e. no PIPE clock (2026-10-27 13:05)

`u3stage` (CIO off, one orientation, reading SID drd+0xc120 / CAPLEN drd+0x0
after each write group):

  baseline          ALIVE
  lane mode         ALIVE
  core reset+host   ALIVE
  glue writes       ALIVE
  c200/c2c0         ALIVE
  pipe lock ok      ALIVE
  mux USB3 0x10     ALIVE   <- switching the MUX to USB3 does NOT kill it
  unlock            ALIVE
  HCRST             DEAD    <- the xHCI reset kills the register interface

So the switch path is fine; the controller dies only when HCRST forces it to
resync to the selected USB3 pipe clock - the classic "no PIPE clock" signature.
The mux-switch being harmless rules out the glue/override/lock writes as the
cause. The problem is squarely: the USB3 PHY lane is not delivering a PIPE
clock. The one bring-up stage not yet done is the lane RX/TX power-up
(core+0x10 / core+0x120); done next.

## Correction: USB3 host DOES use the BIST block (CIO domain) (2026-10-27 13:30)

Reading the Linux atcphy driver source (forks/linux-aurora/drivers/phy/apple/
atc.c) settles the "does USB3 need CIO" question the other way:
`atcphy_configure_pipehandler_usb3_host_t8122` is a USB3-HOST function (its
comment: host mode breaks without this sequence) that drives the BIST MAC block
- ACIOPHY_BIST_* at t8122 base 0x17000, = T6050 reg[35] core+0x29000. It
toggles USB_EN, releases LN0_PIPE_RESET_N via the CFG_OV1/OV2 overrides, drives
the PWR_DOWN overrides, and polls PHY_STATUS2. That is the lane power-up + PIPE
reset release - the step that makes the PHY deliver a PIPE clock. None of the
earlier CIO-on attempts ran it (they set a single wrong bit at 0x29004). So
USB3 host needs atc1_cio (for the BIST block) AND this handshake. Testing next:
cio on + full bring-up + the BIST dance + mux USB3 + HCRST, with the
GSNPSID/CAPLEN oracle. Earlier "CIO-on halts the controller" was the lane left
in reset (no handshake), not CIO being inherently fatal.

## BIST dance completes CIO-on; controller alive but halted (2026-10-27 13:45)

`cio tunables tunx wake pllstart2 flip u3bist` (CIO on, BIST base reg[35]
core+0x29000, GSNPSID/CAPLEN oracle):

- BIST regs reachable CIO-on: +0x0 (CFG1) 0, +0x4 (CFG2) 0xe00, +0x80
  (STATUS2) 0, +0x88/+0x8c (CFG_OV1/2) 0. RMW is safe (OV regs start 0).
- BIST dance COMPLETES: USB_EN polls e1/e2/e3 all ok, STATUS2 s1/s2 ok - the
  lane answers and powers up. This is the step every earlier CIO-on attempt
  skipped.
- Controller stays ALIVE the whole time (SID 0x33313130, CAPLEN 0x1100020)
  including after HCRST - CIO-on does NOT kill the register interface (that was
  a CIO-off-only failure, from switching to USB3 with no pipe clock).
- BUT: controller is HALTED from baseline (USBSTS 0x801 = HCH+CNR) the moment
  CIO is on, before any USB3 switch; USB2 flip fails (CCS timeout); the
  pipehandler lock does NOT ACK (lock timeout); CNR never clears.

Two states now pinned:
- CIO OFF: controller healthy, USB2 works, CNR clears on dummy pipe; but the
  BIST block is unreachable and switching to USB3 + HCRST kills the controller
  (no PIPE clock).
- CIO ON: BIST dance works, lane up, controller answers through HCRST; but the
  controller is HALTED (CNR 0x801) from the moment CIO powers, and the pipe
  lock won't ACK.

So the CIO-on blocker is: the controller is halted the instant atc1_cio powers
(independent of USB3). Candidates for what halts it / won't let it leave reset:
FABRIC left at 0x80000000 bit 31 after the tunable RMW (mask may not clear
bit 31); the glue block drd+0xcd00 gated with CIO on (diff: reads 0, ignores
writes); or a missing ref/pipe clock. The pipe lock not ACKing is consistent
with a halted controller (it cannot clock the ACK).

## The wall: glue block drd+0xcd00 gated CIO-on; fabric + mgmt-core ruled out (2026-10-27 14:00)

In the held CIO-on state (atc1_cio actual 0xf), probing the halt:
- FABRIC core+0x244000 = 0x101f803f, bit 31 = 0. NOT stuck at 0x80000000 - the
  tunable RMW cleared it. Fabric is fine; it is not the halt. (Ruled out.)
- Glue drd+0xcd28/cd2c/cd40/cd44 all read 0; writing 0x886 to cd28 reads back 0
  (IGNORED). The glue block is gated/in-reset with CIO on.
- PHY management core start: 0x2ab140040 (reg[38]) 0xa0002 -> OR 1 -> 0xa0003,
  bit held. Glue STILL ignored after it; controller still halted (USBSTS 0x801).
  So the management core does NOT ungate the glue. (Ruled out, with Opus's
  earlier AON_GEN RESET_N / FORCE_CLAMP cycling, which also did nothing.)
- Controller answers throughout (SID 0x33313130, CAPLEN 0x1100020).
- dwc3-side m1n1 usb.c only inits the pipehandler (MUX 0x22, AON_GEN RESET_N,
  NONSELECTED 0x9332) - nothing writes drd+0xcd00, so it is not a missing
  boot-init the harness skips.

So the single remaining blocker is: what ungates the glue block at drd+0xcd00
when atc1_cio is on. It likely holds the controller's PIPE/ref-clock enables
and PHY-status path (a halted-but-answering dwc3 is waiting on PHY status); with
it gated, CNR never clears. Candidates not yet tried: a dedicated clock/power
enable for that block, or it only un-gates once a real USB3 PIPE clock reaches
the controller (making it a symptom of "no pipe clock routed", same root as the
CIO-off path). Lane-mode/crossbar routing for T6050 and the lane TX clock enable
(LN_TXA_CLK_EN in the lane TX SHM block) are the next things to pin down.

## PINPOINTED: the dwc3 GCTL CoreSoftReset gates the glue CIO-on (2026-10-27 14:20)

Stage-by-stage glue bisect, CIO on (all domains + PWR 0x1b), reading
drd+0xcd28/cd40 + USBSTS after each stage:

  cio+pwr     glue ALIVE (0x886) USBSTS 0x1
  tunables    glue ALIVE         USBSTS 0x1
  wake        glue ALIVE         USBSTS 0x1
  pll         glue ALIVE         USBSTS 0x1   <- controller READY, CIO on!
  flip-phy    glue ALIVE         USBSTS 0x1
  flip-sig    glue ALIVE         USBSTS 0x1
  flip-gctl   glue GATED (0)     USBSTS 0x801 <- dwc3 GCTL CoreSoftReset breaks it
  flip-done   glue GATED         USBSTS 0x801

The gating step is the dwc3 GCTL (drd+0xc110) CoreSoftReset (bit 11) pulse in
`flip`/`hcreset`. With CIO off that same pulse is fine (USB2 works). With CIO on
it gates the SS glue block drd+0xcd00 and sets CNR, and the controller cannot
recover - almost certainly because the core soft reset is done WITHOUT the dwc3
PHY-soft-reset handshake (GUSB2PHYCFG.PHYSOFTRST drd+0xc200 bit31 +
GUSB3PIPECTL.PHYSOFTRST drd+0xc2c0 bit31), so with the SS PHY now active (CIO on)
the SS side comes back gated.

KEY: with CIO on + PHY up + PLL locked, the controller is ALREADY ready
(USBSTS 0x1, glue alive) BEFORE any core soft reset. Every earlier u3bist/u3doc
ran `flip` first, so the glue was already dead by the time USB3 was configured.

Fix direction: bring up USB3 from the good post-PLL state WITHOUT the GCTL
CoreSoftReset - set host mode (GCTL prtcap bits 12-13, no bit-11 pulse), BIST
dance, pipe mux USB3, then only the xHCI HCRST (USBCMD bit1). Testing next.

## Breakthrough: controller runs on the USB3 pipe, CIO on, no HCRST (2026-10-27 14:35)

`cio tunables tunx wake pllstart2 u3bist` with u3bist fixed to (a) set host mode
WITHOUT a GCTL CoreSoftReset and (b) skip the xHCI HCRST after the USB3 switch,
just start the controller:

  baseline    glue ALIVE (0x886) USBSTS 0x11
  lock ok     glue ALIVE   <- pipehandler lock now ACKs (controller not halted)
  BIST        e1/e2/e3 ok, STATUS2 s1/s2 ok  <- lane up
  mux USB3    glue ALIVE, controller ALIVE   <- mux holds USB3
  no-hcrst    glue ALIVE, USBSTS 0x11
  run (R/S)   SID/CAP ALIVE, USBSTS 0x10 (HCH clear, CNR clear) <- controller RUNNING

So with CIO on + the BIST lane power-up + no self-inflicted GCTL reset, the dwc3
comes up in host mode on the USB3 pipe and RUNS without CNR stuck. That dissolves
the whole "CIO halts the controller" wall - it was the GCTL CoreSoftReset
(done without the PHY-soft-reset handshake) plus doing the xHCI HCRST in the
wrong order (after the USB3 switch instead of on the dummy pipe at init).

Remaining to confirm a live SuperSpeed LINK:
- PORTSC1 (SS port) sits at 0x2a0 = RxDetect (PLS 5), CCS 0 - it detects no
  device. Every run has shown a USB2 device on port 1 (PORTSC0 CCS 1) but never
  an SS device. Need a USB3 device physically in port 1 (left-front) to see the
  SS port train (RxDetect -> Polling -> U0).
- When the controller is started (R/S), the glue drd+0xcd00 gates again
  (0x886 -> 0) while the controller keeps running (HCH clear). Unclear if this
  is normal or a residual pipe-clock-stability issue; a real device would tell.
- The controller here was only minimally started (USBCMD R/S); a full xHCI
  bring-up (DCBAA, command/event rings) is needed to actually enumerate. That is
  the OS xhci driver's job; this harness only proves the PHY/pipe/controller-reset
  path is no longer the blocker.

## Device look + the real remaining blocker: lane routing/crossbar (2026-10-27 15:05)

Ran the clean path (cio tunables tunx wake pllstart2 u3bist, FORCE_PORT1=1) with
a phone on port 1 (an Android; the is_proxy guard false-positives on any device
in device mode on port 1, hence FORCE_PORT1). Result: controller runs clean on
the USB3 pipe (glue stable 0x886, USBSTS 0x0), but PORTSC1 (SS port) stays at
0x2a0 = RxDetect, CCS 0 - no SuperSpeed link, no Polling attempt.

Two reasons it can't link yet, both real:
1. Device side: a phone on its charging cable is USB 2.0 (no SS pairs) - cannot
   carry SuperSpeed regardless of our PHY. A USB3 flash drive/SSD is the clean
   confirmation device.
2. Mac side (the actual blocker): the USB3 PIPE clock is NOT confirmed delivered.
   The xHCI HCRST on the USB3 pipe still kills the controller (device-independent
   oracle), and PORTSC1 never attempts receiver detection. So even a proper USB3
   cable+device would not link today.

The missing Mac-side piece is the lane-mode/CROSSBAR routing. The driver model
(atcphy_configure_lanes) is: a lane-mode register (4x 3-bit fields RX0/TX0/RX1/
TX1) PLUS a SEPARATE crossbar register (protocol field [4:0]; USB3 = 0xa). On
T6050 only core+0x6c (lane mode, partial) has been used; the crossbar register
was never set, which is why lane-mode changes alone did nothing. Probe of the
region (CIO-on held state):
  core+0x6c = 0x07000026  writable 0xc3ffd9   (lane mode)
  core+0x70 = 0x00000100  writable 0xff
  core+0x74 = 0x00000001  writable 0x0        (enable? read-only-ish)
  core+0x78 = 0x0000002a  writable 0x1fffd5
  core+0x7c = 0x002a492a  writable 0x15b6d5
  core+0x80 = 0x00800620
None cleanly shows a 0xa/0x10 protocol select, so the T6050 crossbar offset +
field is not yet identified - this needs the lane-mode/crossbar config decoded
(adjust_lane_mode / xbar_config), not blind poking. That is the next RE target
and the one thing between "controller runs on USB3 pipe" and a real link.

## Second cable, same result (2026-10-27 15:15)

Re-ran with a different cable on port 1: PORTSC1 still 0x2a0 (RxDetect), no link;
Mac side still runs clean (USBSTS 0x0). Two cables -> identical. Rules out the
cable. Confirms the blocker is the Mac-side USB3 PIPE clock / lane routing
(crossbar), not the device or cable.

## Lane TX clock enabled, SS port still RxDetect (2026-10-27 15:35)

Added the lane TX-clock bring-up from the driver's lane configure (TX SHM
core+0xd000 lane0 / +0x1d000 lane1: LDO clock EN sml+big, byteclk reset-sync
released, TXA CLK_EN+OV, DIV2_EN+OV, DIV2_RESET released). Ran both lanes, no
HCRST, controller started.

- Everything stays alive (glue 0x886, controller runs, USBSTS 0x0).
- PORTSC1 still 0x2a0 = RxDetect, no change over 2.5 s.
- Earlier variant with HCRST after lane-clk: HCRST still kills the controller
  (no solid PIPE clock to latch).

So enabling the lane TX clock (as ported) does NOT produce a USB3 PIPE clock /
receiver detection. The driver's lane bring-up (atcphy_dp_configure_lane, ~200
lines: LDO clock, byteclk sync, DIV2, impedance cal, RX CTLE, PMA FSM, per-rate
and per-orientation) is far more than the clock-enable subset tried here, and is
DP-centric; the USB3 lane path on T6050 needs that full analog bring-up ported
and the correct per-rate/orientation config - not the incremental pokes tried
this session. Plus a confirmed SuperSpeed device to see the port train (the
device-independent HCRST oracle shows our side has no solid pipe clock yet).

State reached this session (big step from where it was):
- USB3 is NOT a working link.
- The controller runs cleanly on the USB3 pipe with CIO on (the old "CIO halts
  the controller" wall was dissolved: it was a self-inflicted GCTL CoreSoftReset
  + wrong-order HCRST). BIST lane power-up completes, pipe lock ACKs, mux holds
  USB3.
- The remaining blocker is the full lane analog bring-up (TX/RX clock routing to
  the PIPE). That is methodical driver-porting work, documented here and in
  usb3-usb4/t6050-usb3-usb4-bringup.md for the next pass.

## phypwr dead end; realistic state = controller runs on USB3 pipe (2026-10-27 16:00)

- phypwr (driver ATCPHY_POWER_CTRL = core+0x20000, reg[32]): ctrl took 0x1b but
  its STATUS (core+0x20004) never acked (sleep polls timed out). So reg[32] is
  NOT the functional power block on T6050; reg[39] (0x2ab200000, status DOES
  ack) is the one - which the bring-up already drives. The driver's core+0x20000
  maps to reg[39] here via a different core base. Dead end.
- Full best config (cio tunables tunx wake pllstart2 phypwr u3bist, both lane
  TX clocks, Android on port 1): controller runs clean on the USB3 pipe
  (USBSTS 0x0, SID/CAP alive), PORTSC1 stays 0x2a0 = RxDetect, no link.

IMPORTANT correction on the HCRST "oracle": issuing an xHCI HCRST with the MUX
already on USB3 kills the controller - but that sequence does NOT occur in the
real driver. dwc3/xhci does HCRST once at init on the DUMMY pipe, then the PHY
switches the mux to USB3 on cable-connect, AFTER the controller is up. So the
realistic working state is the "after run" line: controller running on the USB3
pipe, USBSTS 0x0, alive - which IS achieved. HCRST-on-USB3 is an artificial test
and its failure is NOT evidence the Mac side is broken.

So the SS port at RxDetect is consistent with simply having no SuperSpeed link
partner. An Android phone is a poor test: phones present as USB2 peripherals for
charging/MTP and generally do NOT bring up a SuperSpeed device link to a host.
The clean confirmation is a USB3 mass-storage device (flash drive / SSD / dock),
which always trains SuperSpeed on connect. Cannot be confirmed device-free from
here: a downstream SS port with no SS partner correctly stays in RxDetect.

Honest state: the Mac-side USB3 bring-up reaches its realistic running config
(controller live on the USB3 pipe, CIO on, no halt). Whether a real SuperSpeed
link comes up is UNCONFIRMED and needs a USB3 storage device in port 1. Residual
uncertainty: the PIPE clock has not been independently proven present, so a
negative result with a real USB3 device would point back to the lane clock/PCS
routing.

## Device-free proof: NO USB3 pipe clock (LTSSM frozen) (2026-10-27 16:20)

With the controller running on the USB3 pipe, sampled GDBGLTSSM (drd+0xc164)
over 2.5 s: frozen at 0x9cc20026, 1 distinct value. The SS link state machine
is not cycling through receiver-detection -> the USB3 PIPE clock is NOT running.
This is device-independent: no USB3 device/cable would make it link. The blocker
is definitively the Mac-side PIPE clock generation, not the phone/cable.

Everything driver-documented for USB3 has been tried and none starts the pipe
clock: tunables (incl per-lane RX_EQ/RX_CFG_TX_OF_RXCLK), common wake, AUSPLL
lock + its CLKOUT drivers (core+0x3200 PCLK bit3 / REFBUF bit11), lane mode
core+0x6c, crossbar (reg[35]/0x78 already protocol 0xa), BIST MAC lane power-up
(USB_EN + PHY_STATUS2 handshake completes), both lanes' TX clock (TX SHM
core+0xd000/0x1d000: LDO clk, byteclk sync, TXA CLK_EN, DIV2), and the power/
reset release. The controller runs on the pipe (USBSTS 0x0) but the PCS does not
emit pclk.

UNSOLVED: what makes the T6050 USB3 PCS output the pipe clock from the locked
AUSPLL. The t8103 path enables CIO3PLL_CLK_CTRL PCLK_EN/REFCLK_EN; t8122/T6050
do not use that register, and the equivalent AUSPLL/PCS pclk-output enable for
T6050 has not been identified. This is the single remaining piece for USB3 and
needs decode of the PCS pclk-output / AUSPLL-to-PCS clock path - it did not fall
out of the driver-documented steps or live probing this session.

## Deep binary RE of the clock path - mechanism decoded, trigger unsolved (2026-10-27 17:30)

Decoded the macOS AppleT6050TypeCPhy lane/clock bring-up from kernelcache
(scratchpad: kc_disasm.py / seqdec.py). Functions and registers:
- aciophy_rx_powerup(lane): RMW core+0x10 (RX lane sleep/clamp).
- aciophy_tx_powerup(lane): RMW core+0x120 (TX lane sleep/clamp).
- aciophy_tx_rm_ovrd / txrx_rm_ovrd / cmn_rm_ovrd: clear the OVERRIDE fields so
  the PHY FSM drives the blocks. Override {value,OV} 2-bit field pairs live at
  [3:2]/[7:6]/[11:10] in core+0x120 (TX) and core+0x10 (RX); CFG0 core+0xc has
  COMMON_*_OV at bits 1/3/5. (CFG0 bit map from the open driver: BIG0/BIG_OV1/
  SMALL2/SMALL_OV3/CLAMP4/CLAMP_OV5; lane fields same shape.)
- aciophy_pipe_bist_override: the BIST MAC dance (core+0x29000) already ported.

Live-tried, all leave the SS link state machine (GDBGLTSSM drd+0xc164) FROZEN =
no pipe clock:
- lane wake (core+0x10/0x120 BIG=SMALL=3, CLAMP=0, OV forced) + rm_ovrd (clear
  OV bits): PLL stays locked, LTSSM frozen.
- lane TX clock (TX SHM core+0xd000/0x1d000: LDO clk, byteclk sync, TXA CLK_EN).
- USB3 PHY reset at core+0x20000 (reg[32]): status never acks -> reg[32] is not
  the functional block on T6050 (reg[39]/0x2ab200000 is, already driven).
- GUSB3PIPECTL/GUSB2PHYCFG PHYSOFTRST (drd+0xc2c0/c200 bit31): already clear.

The glue/CIO catch-22, precisely pinned:
- The dwc3-apple glue drd+0xcd00 (cd28=0x886, cd40=0x3c20060c, from iBoot; holds
  pipe/ref-clock enables) is writable and restorable ONLY with the dwc3 NOT
  core-soft-reset. After a dwc3 core soft reset it zeroes and, with atc1_cio on,
  ignores writes.
- Restored the glue CIO-off (writes stick), then powering **atc1_cio** (the
  exact domain the BIST/PCS block needs) zeroes it again.
- BUT: in the no-core-reset path (host mode set without GCTL bit11), the glue
  STAYS alive (0x886) with CIO on - yet the LTSSM is still frozen there too. So
  glue-alive is necessary-looking but NOT the pipe-clock trigger.

Net: the controller runs on the USB3 pipe (USBSTS 0x0, CNR clear) with CIO on,
glue alive, BIST done, lanes woken, PLL locked, mux USB3 - but NO pipe clock
starts (LTSSM frozen). The specific register/sequence that makes the T6050 USB3
PCS emit pclk from the locked AUSPLL is NOT yet identified. It did not fall out
of: the open Linux driver's USB3 path, the decoded macOS lane/override/clock
functions, or ~20 live combinations. Remaining RE: decode the top-level USB3
configure orchestrator (virtual dispatch from aciophy_phy_init) to get the exact
ordered call sequence and the one step still missing; and/or the AUSPLL->PCS
pclk-output enable specific to this generation.

## CORRECTION: "no pipe clock" was a misread; LTSSM SS.Disabled is normal (2026-10-27 17:50)

The "frozen LTSSM = no pipe clock" oracle from 16:20 onward was WRONG. GDBGLTSSM
(drd+0xc164) bits [21:18] are the LTSSM state; 0x9cc20026 -> state 0 =
SS.Disabled, a stable state that holds constant by design, clock or no clock.

Proof: port 2 (the proxy, works fine at USB2) reads the IDENTICAL GDBGLTSSM
0x9cc20026 (state SS.Disabled). So that value is just "SuperSpeed not in use",
not evidence of a missing clock. The pipe clock is NOT proven absent - it is
unknown. The rm_ovrd / lane-wake / TX-SHM / core+0x20000 digging all rested on
this invalid oracle; the register decode from them is still valid, but none
proved anything about the clock.

Live compare, port 2 (works, USB2) vs port 1 (test, CIO on):
  GUSB3PIPECTL  p2 0x01021102   p1 0x01001102   (both configured; diff = bit17
                                                  SUSPENDEN - p2 idle/suspended)
  glue cd28     p2 0x00000886   p1 0x00000000   <-- the real difference
  glue cd40     p2 0x3c20060c   p1 0x00000000
  GDBGLTSSM     p2 0x9cc20026   p1 0x9cc20026   (both SS.Disabled - identical)
  GUSB2PHYCFG   p2 0x00102400   p1 0x00102400   (identical)

So GUSB3PIPECTL IS configured on port 1 (earlier "c2c0=0" was read on a dead
controller after an HCRST and wrongly dismissed). The one real difference is the
glue drd+0xcd00, which atc1_cio zeroes on port 1; port 2 never powers atc1_cio.

Corrected open question (controller side, not "no PHY clock"): how does a real
SS bring-up get the dwc3 SS link OUT of SS.Disabled (port enabled, warm reset /
Polling) with atc1_cio on and the glue kept configured? Next: (a) read port 2's
full glue/GUSB3PIPECTL as the working reference (done above - glue 0x886/
0x3c20060c, GUSB3PIPECTL 0x01021102); (b) try the pipehandler NONSELECTED/0x9332
write AFTER atc1_cio to see if the glue can be re-established; (c) force the SS
port to retrain (PORTSC warm reset) and watch the LTSSM state field (not the
whole word) actually change. The PHY side may already be fine.

## Device present: SS warm reset engages but never completes (PIPE-side) (2026-10-27 19:20)

USB3 stick in port 1 (left-front). Sequence `cio tunables tunx wake pllstart2 u3bist`
after a clean reboot. u3bist instrumented: glue (drd+0xcd28) printed after each of
the four port writes; glue restored (cd28/cd2c 0x886, cd40 0x3c20060c, cd44 0x2000b)
right after the WPR.

- USB2 PORTSC0 0x206e1 CCS 1: stick enumerates at USB2 on port 1.
- PLL locked (0x7034 bit3); controller alive throughout (SID 0x33313130, CAP
  0x01100020); no hang.
- SS PORTSC1 0x2b0 held 5 s: PR 1, WRC 0, PLS 5, CCS 0. The warm reset asserts
  (PR=1) and never completes (WRC stays 0). Device-free the same WPR settles to
  0x2a0 (PR 0). The far-end device makes the reset engage, then stall.
- glue 0x886 after R/S, after both PP writes, and after WPR; the restore took. By
  end of the 5 s watch glue read 0. No explicit write zeroed it; it is held 0 while
  PR is asserted (reset domain).
- GUSB3PIPECTL 0x1021102; BIST STATUS2 (core+0x29080) 0x0 -> bit7 LN0_PHY_STATUS2 = 0:
  the PHY is not asserting pipe PhyStatus / not in P0, so the warm-reset handshake
  cannot complete.

Open: get the PHY pipe to P0 (PhyStatus acked) so the reset completes, or drive the
link with a directed PLS=5+LWS transition (no WPR) that does not hold the glue in reset.

## Directed PLS (no WPR): steady RxDetect, no far-end -> orientation is live (2026-10-27 19:21)

Dropped the WPR; drive PORTSC1 PLS=5 (RxDetect) + LWS instead, so the port stays
observable (WPR pins PR=1 and masks the LTSSM).

- base PORTSC1 0x2a0 (PR 0, PLS 5, CCS 0, PP 1): R/S + port power alone park the SS
  link at RxDetect, no reset. Steady across 100 ms and the full 6 s watch.
- directed PLS=5+LWS added nothing: PORTSC1 held 0x2a0 for 6 s. PR stays 0, PLS 5,
  never advances to 7 (Polling).
- USB2 PORTSC0 0x206e1 CCS 1 throughout (stick on port 1).
- GUSB3PIPECTL 0x1021102, BIST STATUS2 (core+0x29080) 0x0.

Reading: the SS link is in steady RxDetect looking for a far-end SuperSpeed receiver
and not seeing one. lane-mode 0x6c [4:2]/[7:5] = 2/2 is one of the two cable
orientations. Next: test the other orientation (flip the stick), one change. If both
orientations park at 5, investigate STATUS2 / PWR_DOWN_OV (core+0x29088) with PR=0.

## Flip ruled out: both orientations park at RxDetect; PIPE-side (2026-10-27 19:41)

Flipped the stick (other cable orientation), same sequence. Identical result:
PORTSC1 0x2a0, PR 0, PLS 5, CCS 0, steady; USB2 PORTSC0 0x206e1 CCS 1. Both
orientations park at RxDetect, so it is not orientation.

STATUS2 (core+0x29080) = 0x0 with PR=0 -> bit7 LN0_PHY_STATUS2 low: the PHY/PCS is
not asserting pipe PhyStatus, i.e. the lane is not in an active (P0) output state, so
RxDetect sees no far-end regardless of orientation. GUSB3PIPECTL 0x1021102.

Open: bring the PHY lane/PCS to P0 (PhyStatus asserted) - check CFG_OV1/CFG_OV2
PWR_DOWN overrides (core+0x29088/0x2908c) and the actual lane power-down state.

## PCS dump at RxDetect: CFG_OV1 holds pipe in reset + P3 (2026-10-27 19:43)

Full state at steady RxDetect (both orientations, PR=0):
- PIPE: GUSB3PIPECTL 0x1021102, GUSB2PHYCFG 0x102400, GCTL 0x30c11004 (host, no soft
  reset), GSTS 0x7e800021.
- PCS (core+0x29000): CFG1 0x0, CFG2 0xe00, STATUS2 0x0, CFG_OV1 0x6100000, CFG_OV2 0x0.
- LANE: TXpwr c120 0x15540033, RXpwr c10 0x33 (both awake, OV cleared -> FSM-driven),
  CFG0 0x1003f305, lanemode 6c 0x700004a ([4:2]=2 [7:5]=2), PLL lock 0x8.

CFG_OV1 0x6100000 = PIPE_RESET_N_OV (bit20 0x100000) + PWR_DOWN_OV [26:25] = 3. The
BIST dance leaves CFG_OV1 asserted: pipe reset_n overridden and power-down forced to 3
(P3). The lanes are awake but the PCS holds the pipe in reset + deepest power-down, so
STATUS2 bit7 stays 0 and the lane never outputs -> RxDetect sees nothing either way.

u3bist clears CFG_OV2 (BB+0x8c) at the end but never clears CFG_OV1 (BB+0x88).
Candidate fix: release CFG_OV1 after the BIST dance so the pipe/FSM drives P0 + reset_n.

## [UNCONFIRMED - pending BASE[35] readback] T6050 BIST block offsets vs t8122 (2026-10-27 19:55)

CAVEAT (20:10): the "block moved by 0x84" claim below is NOT established. seqdec labels
addresses "[idx35]" by its own inference; BASE[35] was never read as a number. Also
u3bist's USB_EN set-and-poll PASSES at +0x0 (bits take there), so +0x0 behaves like CFG1.
The real unexplained symptom is STATUS2 (+0x80) bit7 never asserting. Verifying BASE[35]
and which offset is the live STATUS2 before trusting any of the below.

Decoded the real AppleT6050TypeCPhy::aciophy_pipe_bist_override from the kernelcache
(fffffe0009f055f4). It does NOT use the +0x88/+0x8c/+0x80 offsets our u3bist writes
(those are the t8122 atc.c map, block 0x17000). On T6050 the BIST block (core+0x29000)
uses a shadow-register / indirect-write protocol:
- data regs: +0x2910c (|0x6000000 = [26:25]=3), +0x29110 (|0x200)
- strobe/commit: +0x29004 (set bit3 0x8, poll bit0; also bit0/bit1), +0x29008 (set bit5
  0x20, poll)
- status: +0x29104 (bits 6/8 flags, bit0 busy)
Each data write is followed by a +0x29004 bit3 strobe (poll bit0) to latch it; +0x2910c
and +0x29110 are polled on bit0 (ready) before access.

The driver's override registers are +0x10c/+0x110 (same bit patterns our u3bist aimed
at +0x88/+0x8c: [26:25]=3 and 0x200), i.e. the block moved by 0x84 vs the t8122 map.
u3bist writes +0x88/+0x8c with no strobe; the driver's real override regs (+0x10c/+0x110)
were never touched by us. Whether our +0x88/+0x8c writes have ANY effect on T6050 is
unconfirmed (they are writable - read back our value - but are not the driver's override
regs). So the prior "CFG_OV1 holds pipe in P3" reading (19:43) is unconfirmed, not
established.

NOTE: pipe_bist_override takes a bool - it is an OVERRIDE path (park pipe for BIST). The
live USB3 path likely calls it true (park) then false (release). The false arm is the
fix, probably a couple of strobed writes, not the whole 69-W sequence. Next: raw-disasm
the arg branch + the two blank +0x10c/+0x110 writes for exact values, then port the
release arm to the correct offsets. STATUS2 remains the oracle.

## CONFIRMED: STATUS2 at +0x104, PHY acks; BIST MAC group moved +0x84 (2026-10-27 20:05)

Probe (pulse candidate CFG1/USB_EN with lanes powered, watch STATUS2 candidates):
  probe +0x0.2 / +0x4.2 / +0x4.3 -> STATUS2 bit7 at +0x104 = 1 (+0x80 stays 0)
  probe +0x8.5                   -> +0x104 = 0
Resolves the 19:55 UNCONFIRMED tag:
- STATUS2 (LN0_PHY_STATUS2 bit7) is at +0x104, NOT +0x80. The MAC_USBPHY group moved
  +0x84: STATUS2 0x80->0x104, CFG_OV1 0x88->0x10c, CFG_OV2 0x8c->0x110.
- The PHY DOES acknowledge (bit7 asserts). So this is a register-offset bug in u3bist,
  NOT a dead PHY / lane-power failure (c120/c10 awake 0x...33 throughout).
- u3bist polled +0x80 (always 0 -> trivially "ok") and wrote overrides to +0x88/+0x8c
  (dead), so the real STATUS2 was never checked and the real overrides never driven.

T6050 BIST map (macOS decode immediates + probe): CFG1 +0x4 (CLOCK_EN bit0, USB_EN
bit3), CFG2 +0x8 (PHY_STATUS_RE bit5), STATUS2 +0x104 (bit7), CFG_OV1 +0x10c, CFG_OV2
+0x110. Re-porting the dance (atcphy_configure_pipehandler_usb3_host_t8122) to these.

## Dance completes but SS link stays at RxDetect; STATUS2 semantics (2026-10-27 20:17)

Reordered (lanes before dance) + CFG1/CFG2 reverted to +0x0/+0x4 (only MAC group moved
+0x84: STATUS2 +0x104, CFG_OV1 +0x10c, CFG_OV2 +0x110). Results:
- Discriminator (from cleared STATUS2): USB_EN at cfg1@0x0.b2 AND cfg1@0x4.b3 both leave
  STATUS2(+0x104) bit7 = 0 (0->0). So USB_EN does NOT assert +0x104 bit7. The u3run-6
  "+0x104:1" was stale pre-existing state, cleared by the +0x8.b5 strobe - not a response.
- BUT Linux polls STATUS2 for bit7 == 0 (!(reg & PHY_STATUS2)) = waits for it to be clear.
  bit7 == 0 is the expected success post-condition, which we have. So the dance's STATUS2
  checks pass (trivially or correctly - unresolved which).
- Dance now completes cleanly: CFG_OV1/OV2 end 0x0 (set then released), glue preserved
  0x886 (not wiped), mux USB3, GSTS 0x7e800001.
- SS PORTSC1 still 0x2a0 (RxDetect, PR 0, CCS 0): controller drives RxDetect, no far-end.

Unresolved: is +0x104 really STATUS2 (it responds to the +0x8.b5 strobe but not to USB_EN)?
And the core gap remains RxDetect -> Polling: the controller sees no far-end SS receiver.
All orientation tests so far were with the BROKEN dance, so orientation is not re-excluded.

## KEY: u3bist never set the USB3 crossbar/lane-mode (USB3 = DP/USB3 combo) (2026-10-27 20:25)

atc.c APPLE_ATCPHY_MODE_USB3 comment: "USB3/USB3 does not work ... set up the lanes as
DP/USB3." USB3 on this PHY uses crossbar USB3_DP (0x10 normal / 0x11 swapped),
DP_SINGLE_PMA UNK008 (0x008), lane_mode {USB3,DP}/{DP,USB3}, ATCPHY_MISC LANE_SWAP per
orientation. configure_lanes writes aciophy_lane_mode (CORE+0x60) + aciophy_crossbar
(CORE+0x64), BEFORE configure_pipehandler.

u3bist never did this: it sets CORE+0x6c (NOT the atc.c lane-mode reg 0x60) and never
touches the crossbar 0x64. So the SS was never routed to a USB3-mode lane - RxDetect sees
no far-end regardless of orientation. The harness lanes:normal / lanes:swapped steps DO
encode the correct atc.c values (lane 0x60, xbar 0x64 = 0x10/0x11 | 0x008<<5, MISC swap).

Test: `cio tunables tunx wake pllstart2 lanes:normal u3bist`. normal routes USB3 to lane0
(u3bist powers lane0 via c120/c10); swapped routes to lane1 (would also need lane1 power).
The two cover the two cable orientations. (Footnote: the +0x104 "is it STATUS2" question
is not blocking - the dance end state is verified by CFG_OV/glue/GSTS; do not rathole on it.)

## adjust_lane_mode decode: lane-mode at core+0x6c, T6050 field values 2/7 (2026-10-27 20:35)

AppleT6050TypeCPhy::adjust_lane_mode(uint laneMask, uchar mode) @ f0a234:
  x8 = this->[0x250] (regs.core); reads+writes core+0x6c.
  field [4:2] gated by (laneMask & 1); field [7:5] gated by (laneMask & 2).
  field value = 7 if mode in {0x81,0x82}, else 2.
So lane-mode reg = core+0x6c (CONFIRMED; NOT 0x60). T6050 field encoding is 2/7, NOT
atc.c's 1(USB3)/2(DP)/3(OFF) - that enum does not apply to T6050. u3bist sets both
[4:2]=[7:5]=2. For USB3_DP the two lanes must DIFFER (USB3 vs DP) -> {2,7} in some order.
Open: which of 2/7 is USB3, and the crossbar offset/value (0x60/0x64 dead here; 0x78
unverified). NOTE: lanes:normal 0x60/0x64 writes read back 0 (before lanes powered).

## CROSSBAR FOUND: core+0x78 (writable); was 0xa (pure USB3 = "does not work") (2026-10-27 20:31)

DIAG with lanes powered: core+0x60/0x64 writes ignored (dead - t8122 offsets). core+0x78
is WRITABLE (0x2a -> 0x30 on [4:0]=0x10 write) = the crossbar. Reset value 0x2a =
protocol [4:0]=0xa (pure USB3) + DP_SINGLE_PMA bit. atc.c: pure USB3 "does not work",
needs USB3_DP (0x10). So the T6050 map is: lane-mode core+0x6c, crossbar core+0x78 (NOT
t8122's 0x60/0x64). Register dump @ lanes-up: 0x6c=0x700004a 0x70=0x100 0x74=0x1
0x78=0x2a 0x7c=0x2a492a 0x80=0x800620.

Fix: crossbar 0x78 = 0x10 | (0x008<<5) (USB3_DP, DP_SINGLE_PMA 0x008) normal / 0x11 swapped;
lane-mode 0x6c [4:2]=2 (USB3 lane0) [7:5]=7 (DP lane1); MISC core+0x20008 swap bit.
SWAP env flips orientation. Testing normal first.

## USB3_DP crossbar set correctly, still RxDetect (normal orientation) (2026-10-27 20:33)

route applied: 6c=0x70000ea ([4:2]=2 USB3 lane0, [7:5]=7 DP lane1), 78=0x110 (USB3_DP +
DP_SINGLE_PMA 0x008), misc=0 (no swap). Crossbar/lane-mode now match atc.c USB3 normal.
Result: PORTSC1 still 0x2a0 (RxDetect PR0 CCS0), STATUS2 0, no train.
Next candidates: (a) swapped orientation - but u3bist powers only lane0 (c120 0x120 / c10
0x10); swapped (USB3 on lane1) needs lane1 powered (lane stride 0x10000 -> 0x10120/0x10010);
(b) DP lane PMA FSM override (configure_lanes dp_lane[1]: LN1 RX_TOP+PMAFSM PCS_OV/REQ) not
done; (c) USB3-lane TX driver output enable.

## T6050 is T8122-gen: DP PMA FSM N/A; power lane1 for swapped test (2026-10-27 20:40)

atcphy_hw_t6050.gen = ATCPHY_GENERATION_T8122 ("same T8122-family core as M5 Air t8142").
configure_lanes early-returns for T8122 BEFORE the dp_lane PMA FSM override (that block is
T8103-only; T8122 DP lanes start via the link-rate sequence). So the DP PMA FSM is NOT
wanted for T6050 USB3 - do not add it.

Normal (USB3 lane0, powered) did not train -> stick may be swapped (USB3 on lane1), and
u3bist powered only lane0. Powering BOTH lanes (stride 0x10000: lane1 TX 0x10120, RX 0x10010)
and testing SWAP=1 (USB3 routed to lane1). Readback must show L1 c120/c10 = 0x..33.

## Both orientations fail detection -> TX not driving the SS pad (2026-10-27 20:38)

SWAP=1 (swapped): lane1 now powered (L1 c120 0x1033 c10 0x33 - stride 0x10000 correct),
route 6c=0x700005e ([4:2]=7 DP lane0, [7:5]=2 USB3 lane1), 78=0x111 (USB3_DP_SWAPPED +
DP_SINGLE_PMA 0x008), misc=0x4 (swap). All correct for swapped. Result: PORTSC1 0x2a0
(RxDetect PR0 CCS0), no train. Normal (run 12) also no train. So BOTH orientations fail
with crossbar/lanes correct -> NOT orientation. Host RxDetect sees no far-end either way
= the USB3 lane TX is not driving the pad. u3bist's c120/c10 + rm_ovrd is only a partial
lane power-up. Next: the real lane power-up (aciophy_tx_powerup / rx_powerup, decoded in
scratchpad) / TX output driver enable (LN_AUSPMA_TX_TOP core+0xc000 / 0x1c000).

## PLS=5 is static (device makes no difference); retry WPR kick with correct config (2026-10-27 20:42)

Both orientations + full correct config (crossbar USB3_DP, lanes, both powered): PORTSC1
0x2a0 (PLS 5), identical to the pre-stick device-free baseline (also 0x2a0). Device present
changes PORTSC1 by nothing in the no-WPR path -> the SS LTSSM is not actively probing; PLS=5
is a static resting state. So the link needs KICKING into training. Standard SS start = a
warm reset (WPR); earlier WPR stuck (PR=1) because the pipe was unconfigured - now the
crossbar/lanes are correct and glue holds 0x886. Retrying WPR, watching PR->0, WRC->1, PLS.
(Side note: lane1 c120 upper = 0x1000 vs lane0 0x15540000 - lane1 has less TX upper-config;
but normal with lane0 full also parked at 5, so that is not the sole cause.)

## WPR still stuck (PR=1) even with correct config + glue preserved (2026-10-27 20:42)

Normal orientation, full correct config, WPR: PORTSC1 -> 0x2b0 (PR=1), held, WRC stays 0 =
warm reset engages but never completes. glue now PRESERVED (0x886, not wiped - the offset fix
worked). STATUS2 (+0x104) bit7 stays 0 throughout. So even fully configured, the PHY does not
complete the reset handshake (no PhyStatus); the dwc3<->PHY pipe is not reaching an active
(P0 / PhyStatus-asserted) state. Remaining candidates: (1) GUSB3PIPECTL SUSPENDENABLE (bit17)
or the pipe not requesting P0; (2) the PHY management core (acio-phy-cpu; see usb4/phy-core-start
NOTES - start = ctrl+0x40 bit0) not running to drive the pipe FSM; (3) limits of software-only
bring-up without the full OS driver + PHY firmware.

## Both orientations (swap fully applied) fail WPR; need unplugged control (2026-10-27 20:45)

SWAP=1 with BOTH swap regs set (misc20008=0x4 AND pwr8=0x1804 - physical lane swap now
definitely applied) + swapped crossbar (78=0x111) + both lanes powered: WPR -> PORTSC1 0x2b0
(PR=1) stuck, WRC 0, STATUS2 0. Normal (run 14) same. So BOTH orientations, fully configured,
WPR engages but never completes. NOT orientation. The PHY does not complete the reset
handshake in any config. Decisive next test (needs the stick pulled), re-run:
  - PR still 1 unplugged -> host-side (PHY/pipe not producing PhyStatus) -> GUSB3PIPECTL /
    PHY management core (acio-phy-cpu).
  - PR clears to 0x2a0 unplugged -> device IS seen; stall is the device handshake.

## DECISIVE: unplugged control - PR still stuck -> host-side, not the device (2026-10-27 21:37)

Stick PULLED (USB2 PORTSC0 0x2a0 CCS 0 confirms out). Same sequence + WPR: SS PORTSC1 0x2b0
PR=1 stuck, WRC 0, STATUS2 0 - IDENTICAL to plugged (runs 14/15). So the warm-reset stall is
NOT about the device; it is purely host-side. The dwc3<->PHY pipe never completes the reset /
the PHY never asserts PhyStatus, with or without a device.

Key never-tried gap: the PHY management core (acio-phy-cpu, iop,mxwrap; port0 ctrl 0x2a3140000,
start 0x2a3140040 bit0 per usb4/phy-core-start/NOTES; port1 +0x8000000 = 0x2ab140040) has NEVER
been started in the u3bist sequence. The pipe FSM / PhyStatus generation likely needs it.
Caveat: its power domain is atc1_phymxwrap (PMGR2+0x170), which cio does NOT power (it's only
in WATCH) - may need powering first. Alt host-side: GUSB3PIPECTL (0x1021102) SUSPENDENABLE b17.

## Port compare: no working SS reference; p1 mgmt core NOT started (2026-10-27 21:38)

Read-only compare (p2 mgmt-core read hung the SoC -> WDT reboot; p2 phymxwrap off):
- PORT 2 (proxy, working USB2): PORTSC1 (SS) = 0x280 = PLS 4 (SS.Disabled), PP 1, CCS 0.
  GUSB3PIPECTL 0x1021102, GCTL 0x30c12004, USBSTS 0x1. The proxy is USB2-ONLY; its SS port
  is Disabled. So there is NO trained-SS reference on this board to compare against.
- p1 atc1_phymxwrap (PMGR2+0x170) = 0x3ff = ALREADY powered (boot/cio leaves it on; earlier
  "off" assumption was wrong).
- p1 mgmt core start 0x2ab140040 = 0xa0002 = bit0 CLEAR = NOT started (= NOTES port0 "before").
  Never started in any u3bist run.
Next: start the mgmt core (OR bit0 -> expect 0xa0003) in u3bist after PLL/lanes, then WPR -
direct test of whether the dwc3<->PHY pipe FSM / PhyStatus needs the core running.

## Management core started (0xa0003) - no change; PR still stuck (2026-10-27 21:46)

Started acio-phy-cpu mgmt core (0x2ab140040: 0xa0002 -> 0xa0003, bit0 held). STATUS2 still 0,
PORTSC1 still 0x2b0 (PR=1 stuck), WRC 0. So the mgmt core is NOT the gate (or not sufficient).
The PHY still does not complete the pipe reset / assert PhyStatus.

Remaining hypothesis: no PIPE CLOCK from the PHY to the dwc3 controller. The warm reset waits
for the PHY's reset-done (PhyStatus); without the pipe3 clock the PHY pipe interface cannot
run. This is the original "clock path" question. Candidates: pipe-clock routing/derive from
the lane (TX SHM core+0xd000 beyond CLK_EN) or a pipe-clock mux/enable not yet found.

## PHYSoftRst test INCONCLUSIVE; converging evidence = SS pipe not active (2026-10-27 21:51)

Ran it: GUSB3PIPECTL bit31 set, stays set at +1ms and +20ms. BUT this is NOT a valid pipe-clock
test: in dwc3 PHYSoftRst (GUSB3PIPECTL bit31) is software-set/cleared, not self-clearing. The
self-clearing clock-gated reset is DCTL.CSFTRST ("cleared only after all clocks are synchronized")
- device-side, and dwc3_core_soft_reset returns early in HOST mode (core.c:332). So "stuck set"
only means software did not clear it. DISREGARD the harness "NO PIPE CLK" print label.

What IS solid (device-independent, converging):
  (1) SS warm reset engages (PR=1) but never completes (WRC never sets);
  (2) STATUS2 / PhyStatus2 (core+0x104 b7) never asserts;
  (3) PLS static, plugged == unplugged (0x2a0 / 0x2b0-under-WPR regardless of device);
  (4) earlier xHCI HCRST never completed ("killed the controller").
All point to the dwc3<->PHY SS pipe interface not being active - most likely the PHY not
providing the SS pipe clock. That is the remaining problem = the original "clock path" question.
End-state pipehandler: mux(+0xc)=0x10 (clk=1 USB3, data=0), nonsel(+0x20)=0x8333.

## WHERE IT STANDS (session end 2026-10-27 ~21:51)

SOLVED / working this session:
- USB2 host works on port 1 (left-front); USB3 stick enumerates at USB2 (PORTSC0 CCS=1).
- Full USB3 PHY bring-up, all with correct T6050 register offsets:
  * power domains (cio), tunables + per-lane tunables (tunx), AUSPLL locked (0x7034 b3).
  * BOTH lanes powered (c120/c10 at lane stride 0x10000), FSM-driven (rm_ovrd).
  * crossbar core+0x78 = USB3_DP (0x10 / 0x11 swapped) + DP_SINGLE_PMA 0x008 (t8122's
    0x60/0x64 are DEAD on T6050; map discovered this session).
  * lane-mode core+0x6c: USB3 lane = field 2, DP lane = field 7 (adjust_lane_mode decode).
  * BIST MAC dance at the real T6050 offsets (STATUS2 +0x104, CFG_OV1 +0x10c, CFG_OV2 +0x110;
    the MAC_USBPHY group moved +0x84 vs the t8122 map the old u3bist used).
  * lane order: configure_lanes BEFORE the dance (Linux order).
  * glue (drd+0xcd28 pipe-clock cfg) preserved at 0x886 (was being wiped by wrong-order resets).
  * acio-phy-cpu management core started (0x2ab140040 0xa0002->0xa0003).
- dwc3 controller runs on the USB3 pipe, CIO on, no halt (SID/CAP alive, no HCRST).

THE REMAINING WALL (device-independent):
- The SS LTSSM never leaves RxDetect; warm reset engages but never completes; PhyStatus2 never
  asserts. The PHY is not bringing up the active SS pipe (clock + PhyStatus) to the controller.
- Orientation is NOT the cause (both orientations, swap fully applied, identical).
- Management core running does NOT fix it.

NEXT (for whoever continues): the USB3 pipe-clock path - how the PHY derives/outputs the pipe3
clock to the dwc3 controller once the lane is in USB3_DP mode. Candidates untried: a pipe-clock
source-select/enable in the PCS or the TX SHM beyond CLK_EN; the DP-lane start that T8122 does
via the link-rate sequence (atcphy_dp_set_rate_t8122) - the USB3_DP combo may need the DP lane's
PMA actually running, which only that sequence does. A clean pipe-clock-present probe is still
needed (PHYSoftRst was invalid; DCTL.CSFTRST is device-mode only).

## Full lane power-up (step1+step2, bits 4-7) - still no pipe clock (2026-10-27 22:18)

Ported tx/rx_powerup faithfully: c120/c10 now 0x..f3 (bits 4-7 both lanes; step2 bits 6,7
were missing before). STATUS2 still 0, PORTSC1 still 0x2b0 (PR=1), warm reset still never
completes. So lane power-up was NOT the gate. (Stick re-plugged - PORTSC0 CCS 1 again - no
effect, as expected for a host-side stall.) NOTE: seqdec "bit0 wait" was a misread (it was
the logging-gate tbz on flags [0xe]/[0x1e]); tx_powerup has NO poll - just OR bit(4+lane)
then bit(6+lane) per lane on c120 (rx_powerup same on c10).

All documented PHY config now done (power, tunables, PLL lock, lanes fully powered, crossbar
USB3_DP + lane modes, BIST dance at real offsets, mgmt core) per atcphy_configure's sequence -
yet the SS pipe clock never comes up and the warm reset never completes. Out of high-confidence
host-side leads from the current sources.

## Controller rings unset; GDBGLTSSM frozen constant -> LTSSM unclocked (2026-10-27 22:22)

Controller-side read (advisor angle): CRCR/DCBAAP/CONFIG/ERSTSZ/ERSTBA all 0 - the xHCI runs
(USBCMD R/S=1) with NO rings. (Note: WRC is a HW PORTSC bit, so this may not be why PR sticks,
but the controller is uninitialised.)

GDBGLTSSM (drd+0xc164) re-decoded with the CORRECT nibble [25:22]: = 0x9cc20026, ltssm 0x3,
rxei(b17) 1, txdet(b24) 0 - and CONSTANT at base / +100ms / through the watch, stick in. This
is the same 0x9cc20026 seen at session start. A GDBGLTSSM frozen at one value across every
config and plugged/unplugged = the SS LTSSM is NOT being clocked. Robust "no pipe clock".
(Earlier I had read bits [21:18] = 0 and called it SS.Disabled-normal; the frozen-ness is the
real tell, not the nibble value.)

So: PHY fully configured, controller runs on the pipe, but the SS LTSSM is unclocked. The
remaining problem is strictly the USB3 pipe-clock generation/routing from the PHY. Untested
pipe-clock candidates: the dwc3 glue clock-config regs drd+0xcd40/0xcd44 (only cd28=0x886 has
been verified-preserved; cd40/cd44 never checked) and pclk:SEL re-run with the crossbar fixed.

## GCTL CoreSoftReset wedges the controller (CNR stuck) - the SS-init dead end (2026-10-27 22:32)

Tried the one standard dwc3 init step u3bist always skipped: GCTL CoreSoftReset (b11), then
host mode + clear SUSPHY + restore glue. Result:
- GDBGLTSSM 0x9cc20026 -> 0x0: so it is NOT immutably frozen - the core reset changed it - but
  it then stays 0 and the controller is wedged.
- USBSTS 0x801 = HCH + CNR (Controller Not Ready) SET and STUCK. CoreSoftReset puts the
  controller in CNR and it never comes ready; glue restore does not take (CNR blocks writes,
  glue reads 0); lock times out; USBCMD R/S won't set.
Confirms the original reason u3bist avoids CoreSoftReset: with CIO on the reset zeroes the Apple
glue (pipe-clock cfg) and the controller cannot come ready without it, but the glue cannot be
restored while CNR=1. Chicken-and-egg. Reverted CoreSoftReset + SUSPHY-clear in the harness.

BOTTOM LINE (session end): SuperSpeed does NOT train. The SS core appears to need CoreSoftReset
to initialise, but that wedges the controller (CNR) over the proxy given how the Apple glue is
managed. Best stable state = "controller runs on the USB3 pipe, glue 0x886, LTSSM 0x9cc20026,
PLS 5" - not trained. Getting past this likely needs the full dwc3+xHCI+clock driver framework
(proper reset handshake that restores the glue and clears CNR), not register pokes over m1n1.
Leads if ever resumed: the glue/CNR reset-handshake ordering; a minimal xHCI init (rings) so the
controller is driven as a real host; or the exact pipe-clock gate the frozen 0x9cc20026 implies.

## xHCI HCRST also wedges (same as CoreSoftReset); use firmware-clean controller (2026-10-27 22:50)

cio xhcirst: pre USBCMD 0x0 USBSTS 0x1 (HCH, clean) glue 0x886 SID alive. After HCRST (USBCMD
b1): HCRST does NOT self-clear (USBCMD 0x2, timeout); SID/CAP/glue all -> 0 (controller held in
reset, regs read 0 - so "CNR clear" was just everything reading 0). The xHCI-level reset wipes
the Apple glue and never completes - SAME wall as GCTL CoreSoftReset. ANY controller reset over
the proxy wipes the glue (clock cfg) and can't complete without it; the OS driver avoids this
via the Apple dwc3 glue/clock/reset framework.

Implication for the real-host path: do NOT issue our own reset. Firmware left the controller
clean (CNR clear, HCH set). Build rings (DCBAA/cmd/event, DART-mapped via hw/dart8110.py) +
CONFIG on the as-is controller, bring up the PHY, R/S, enable the port. m1n1 provides XhciRegs
and the DART driver. OPEN: the SS LTSSM is a HW port state machine - unclear if rings make it
train or the real gate is still the pipe clock.

## BREAKTHROUGH: reset BEFORE CIO -> controller survives; order was the deadlock (2026-10-27 22:57)

xhcirst (CIO off) -> HCRST completes, controller clean. THEN cio -> controller SURVIVES: SID/CAP
alive, glue 0x886, USBSTS 0x1 (CNR 0, HCH). So powering CIO AFTER a clean reset does NOT wedge
the controller - only resetting WHILE CIO is on wedges it. The harness always ran cio FIRST and
never did a clean HCRST with CIO off, so the SS controller was never properly reset = the
self-inflicted deadlock. clkdump confirmed CIO flips NO software-visible register (MUX 0x22,
glue 0x886 both ways) - it's a hardware clock-tree gate, fixable only by ORDER (the driver's
"HCRST on the dummy pipe, then switch").

Fix under test: HCRST first (CIO off), THEN cio + PHY bring-up + u3bist:
`xhcirst cio tunables tunx wake pllstart2 u3bist`. May also need to keep the pipehandler mux
off pipe3 until the PHY produces the clock (not switch to the dead pipe early in the dance).

## Corrected order (reset-first) preserves the controller but LTSSM still frozen (2026-10-27 22:58)

xhcirst cio tunables tunx wake pllstart2 u3bist: the controller now SURVIVES clean (glue 0x886
preserved through u3bist, CNR clear, SID/CAP alive) - the order fix works and the controller is
no longer wedged. BUT GDBGLTSSM still 0x9cc20026 (frozen), STATUS2 0, PORTSC1 0x2b0 (PR=1 stuck),
LSP sels []. base PORTSC1 now 0x2b0 (PR=1) vs 0x2a0 before - reset-first changed the port state.
So the order fix resolved the controller deadlock (real, explains "CIO halts the controller")
but SS still does not train: switching the pipehandler mux onto pipe3 freezes the LTSSM because
pipe3 has no clock. Back to the fundamental pipe3-clock wall. Advisor point (2) untried: keep the
pipehandler mux OFF pipe3 (dummy/AON clock) during PHY bring-up, switch only once pipe3 is live.

## RCAL done; PHY_RESET_N no help; pipe3-clock wall stands (session end 2) (2026-10-27 23:07)

RCAL ALL_CODES_DONE = bit0; harness wake polls bit0 and reads 0x19 (bit0 set) = calibration IS
done. core+0x20000 <= 0x1b took (PHY_RESET_N set, write sticks) but did NOT unfreeze the LTSSM.
GDBGLTSSM relentlessly 0x9cc20026 across: corrected reset order, dummy mux (0x22), USB3 mux,
both orientations, device in/out, mgmt core, PHY_RESET_N, full lane power-up (bits 4-7).

SESSION RESULT: SuperSpeed does not train. GENUINE BREAKTHROUGH this session: the reset-order
deadlock ("CIO halts the controller") - resetting the controller WHILE atc1_cio is on wedges it
(glue/clock wiped, CNR stuck); reset FIRST (CIO off, HCRST completes) then power CIO -> the
controller survives clean. Real fix, real mechanism. Also corrected the T6050 register map
(crossbar core+0x78, lane-mode 0x6c, BIST MAC group +0x84, lane power c120/c10 bits 4-7).

But the core wall is unmoved: the T6050 USB3 PHY, fully configured per every documented
atc.c/kernelcache step (power, tunables, AUSPLL lock, RCAL done, lanes powered, crossbar
USB3_DP, lane modes, BIST dance at real offsets, PHY_RESET_N, mgmt core started), does NOT
output the pipe3 clock -> the SS LTSSM never runs (GDBGLTSSM frozen) and nothing trains. Beyond
register-poking over the m1n1 proxy with current sources; needs the exact (not-in-these-sources)
T8122/T6050 pipe-clock generation/handoff, or the full OS dwc3+xHCI+PHY+clock driver doing the
dummy-pipe -> real-pipe handoff.

## Controller side: tunables, TXDETRX lock, lock-ACK test (2026-10-28 09:30-09:44)

Logs: `u3run-31..35` in the session scratchpad. Harness steps added: `ackprobe`, `tunread`,
`tunapply`, `txdeton`.

- PIPE lock ACK is not a clock probe. Before u3bist the ACK follows LOCK_REQ under every mux
  value, clock OFF (0x00) included; after u3bist (xHCI R/S=1) it never sets, dummy mux (0x22)
  included. It tracks the controller's run state, not the selected PIPE clock.
- drd+0xc164 is writable: `tunable_DRD_USB31_GBL_DEFAULT` clears its bit 1 and the read-back
  changes 0x9cc20026 -> 0x9cc20024. Port 2 reads the same 0x9cc20026. The "frozen GDBGLTSSM"
  value is the reset/parked value of a register that is not a pure status readout; it is not
  evidence about the pipe3 clock.
- Controller tunables (usb-drd1, never applied before). Windows from
  `AppleT8150USBXHCI::applyAllTunables` (vfunc +0xd78, slot = ADT reg index):
  BULK_FABRIC reg[6], PIPE_HANDLER reg[3], PWR_CTRL reg[5], DRD_USB31_GBL/DBG slot 0
  (read at the dwc3 globals, core+0xc100), DRD_USB31_CFG_HOST reg[1], LINK_REGS reg[7]
  (core+0xd000), AUSBC_DEBUG reg[8]; DRD_CIO_REGS at the Apple glue core+0xcd00.
  Ports 1 and 2 read identical values, and 19 of 22 entries differ from the tunables. Applying
  them all on port 1 (after xhcirst) keeps the controller alive and USB2 working
  (PORTSC0 0x206e1); SS unchanged (PORTSC1 0x2b0, PR=1, PLS=5).
- `atcusbClkCfg` / `atcusbPipeClkCfg` maps (AppleT8150USBXDCI::start, provider reg 11/12) are
  optional sleep-DDR registers; usb-drd1 has only reg[0..9]. Not a lead.
- `AppleT8150USBXHCI::setUSB3Mode` (0xfffffe000b30502c) dummy -> USB3 order, register calls
  vfunc +0xd10 read / +0xd20 write (map, offset, value):
  1. PWR_CTRL (reg[5], 0x2aaa80000) +0x18 |= 1 (TXDETRX_LOCK_REQ)
  2. PHY setPowerLevel (AppleTypeCPhy)
  3. PIPE +0x4 &= ~0xe; +0x0 |= 1; +0x0 |= 4
  4. PIPE +0x10 |= 1, wait +0x14 bit 0
  5. wait PWR_CTRL +0x1c bit 0 (TXDETRX_LOCK_ACK)
  6. PIPE +0x20 NATIVE_POWER_DOWN, +0x20 &= ~0x1000; +0xc clock off (&= ~0x70), PIPE_MODE,
     clock on
  7. PIPE +0x0 &= ~1, &= ~4; +0x10 &= ~1, wait +0x14 clear
  8. PWR_CTRL +0x18 &= ~1, wait +0x1c clear
- PWR_CTRL reads the same on ports 1 and 2 (+0x0 0x101, +0x20/+0x24 1, +0x28 0x101,
  +0x2c/+0x30 0xffffffff, TXDETRX REQ/ACK 0).
- Run 35 with the TXDETRX lock taken before the PHY bring-up: the TXDETRX ACK never sets
  (at request time and again after the PIPE lock); release clears normally. SS unchanged.

Open: what answers TXDETRX_LOCK_ACK. In macOS the PHY's setPowerLevel runs between the request
and the wait, so the ACK most likely comes from the PHY side once it is in USB3 power level.

## macOS PHY USB3 bring-up re-decoded: BIST bits wrong, PHY CPU firmware step missing (2026-10-28 ~10:30)

Correction to all earlier call-sequence decodes: `vseq.py` read the AppleT6050TypeCPhy vtable
from the `__ZTV` symbol, not the address point (`__ZTV` + 0x10), so every virtual call it named
was two slots off. With the address point (`seq3.py` in the session scratchpad):

- AppleTypeCPhyInterface::setPowerLevel -> AppleT6050TypeCPhy::usbClientSetACIO; "Powering On
  ACIO" calls initACIO(mode 4) -> aciophy_phy_init(mode, flipped = orientation == 2):
  partA(), partB(mode, flipped) = aciophy_apply_tunables + aciophy_xbar_config,
  partC(mode, flipped).
- partC, BIST block core+0x29000 (register helpers 0xfffffe0009f4063c read / ...064c write),
  for mode 1 or 4:
  1. +0x4 |= 0x1 (CLOCK_EN)
  2. +0x10c: &= 0xe1efffff, |= 0x4000000 (PWR_DOWN_OV [28:25] = 2, bit 20 clear)
  3. +0x4 |= 0x8, then &= ~0x8 (USB_EN = bit 3 of +0x4)
  4. +0x110: &= ~0x660, |= 0x220
  5. +0x4 USB_EN toggle
  6. reg[39] (0x2ab200000) +0x8: bit 1 = flipped (CFG_S2R_USB_LN_SWAP); the harness used bit 2
  7. wait 10; if mode != 3: wait 10, runFirmware(), wait 5000, poll core+0x260 bit 10
     (ACIOPHY_TOP_BLK_UC_CTRL_REG.UC_TNBL_DONE), timeout 1 s
  8. aciophy_phy_deassert_aciophy_reset
  9. +0x10c |= 0x100000; +0x4 USB_EN toggle; poll +0x104 bit 8 clear (USBPHY_MAC_LN0_PHY_STATUS_2)
  10. +0x10c PWR_DOWN_OV = 3 (&= 0xe1ffffff, |= 0x6000000); +0x4 USB_EN toggle; poll +0x104
      bit 8 set, then clear
  11. +0x110 &= ~0x660; +0x4 USB_EN toggle
  The harness dance used CFG1 at +0x0 with USB_EN bit 2 and STATUS2 bit 7: it toggled the wrong
  bits, and its status polls passed without the PHY answering.
- runFirmware: reg[38] (0x2ab140000, MXWRAP) +0x40 |= 1 (MXWRAP_BLK_IDLE_CTRL; the "mgmt core
  start" bit), wait 10, then the embedded CPU service (AppleTypeCPhyCIO80PhyMBI, ADT
  `acio-phy-cpu` phandle 166 = `iop-aciophy1-nub`, `iop-nub,rtbuddy-v2`) method +0x818 (1, this);
  "couldn't power up embedded CPU" on failure.
- PHY CPU: ADT `acio-phy-cpu1`, `iop,mxwrap`, reg 0x2ab148000 (mailbox, ASC layout +0x8000) and
  0x2ab140000 (MXWRAP); segments __TEXT core+0x40000, __DATA core+0xc0000; nub `pre-loaded = 1`,
  `running = 1`, `user-power-managed`, `dont-power-on`. Linux drivers/thunderbolt/apple.c runs an
  MxWrap CPU with CPU_CTRL +0x28 |= RUN (bit 4), then apple_rtkit_boot.
- Live (port 1, after a u3bist run): core+0x260 = 0x881 (UC_TNBL_DONE clear), MXWRAP +0x28 = 0x2
  (RUN clear), +0x40 = 0xa0003, +0x44 = 0x6c. Reading core+0x40000 (PHY CPU __TEXT) hung the SoC
  (watchdog reset).
- AppleT8150USBXHCI (host controller) does not map atcusbClkCfg/atcusbPipeClkCfg; only the device
  driver does, as optional sleep registers.

## Corrected dance live; PHY CPU does not answer (2026-10-28 10:50-10:55, runs 36-40)

Harness: `MACBIST=1` runs the macOS partC dance above (BIST+0x4 CLOCK_EN/USB_EN b3, STATUS2 +0x104
bit 8, OV1/OV2 values, reg[39]+0x8 bit 1 lane swap, UC_TNBL_DONE poll, reg[39] bit 4 release);
`NORESET=1` holds reg[39] bit 4 until that point; `FWRUN=1` sets MxWrap +0x28 bit 4; `FWWAKE=1` /
step `fwstart` run `phy_cpu_wake()` (MxWrap +0x40 bit 0, +0x28 bit 4, RTKit SetIOPPower 0x220 over
the mailbox at MxWrap+0x8000 with m1n1 StandardASC); `MBOX=1` prints the mailbox state last.

- Run 36 (MACBIST, NORESET): RCAL and AUSPLL lock time out with the PHY reset held. STATUS2
  reads 0x104: bit 8 stays 1 through every USB_EN toggle (clear polls time out).
- Run 37 (MACBIST, reset released early): RCAL done, PLL locked; STATUS2 still 0x104, bit 8
  stuck at 1. UC_TNBL_DONE clear (core+0x260 0x881). SS unchanged (PORTSC1 0x2b0).
  In PIPE terms the PHY holds PhyStatus high until PCLK is stable: first direct reading from
  the PHY that its pipe clock does not come up.
- Run 38 (+FWRUN): MxWrap ctrl 0x2 -> 0x12, status 0x6c unchanged, UC_TNBL_DONE clear;
  mailbox INBOX_CTRL / OUTBOX_CTRL 0x20001 (enabled, empty).
- Run 39 (`fwstart` after cio/tunables/wake/pllstart2): SetIOPPower 0x220 sent, inbox drained,
  no reply in 3 s; MxWrap status 0x6c -> 0x48; UC_TNBL_DONE clear.
- Run 40 (`fwstart` straight after reboot): the first MxWrap read (+0x40) faults (SYNC) and the
  proxy hangs: the PHY CPU block is unpowered at handoff (reg[39] reads 0x4 there: clamped, both
  sleep bits clear).
- iBoot (`iBoot.j714c.RELEASE.bin`) has the `acio-phy-cpu%d/iop-aciophy%d-nub` property code and
  image-type tags (`rkosftab`), no embedded PHY CPU image (no Mach-O inside). It loads the PHY
  firmware from disk at boot. No local copy.

## PHY CPU firmware boots over RTKit; UC_TNBL_DONE set; PhyStatus still high (2026-10-28 10:59-11:01, runs 41-44)

macOS MxWrap driver (com.apple.driver.AppleA7IOP-MXWrap-v1): `AppleMxWrap::_runCPU` writes
+0x28 = 0x10 outright (not RMW; clears the bit 1 that reads 0x2 at rest); `_isIdle` = +0x44
bit 1; mailbox inbox +0x800, outbox +0x830, control +0x110 (bit 16 full, 17 empty).
`AppleMxWrapACIO::_runCPU` raises the `function-reconfig_req_interrupt` platform function instead,
falling back to the generic write when the property is absent (it is absent on acio-phy-cpu1);
`_apInitializesMailboxes` returns false.

- Run 41: +0x28 = 0x10 -> the PHY CPU sends RTKit HELLO (version 12) at once and answers Ping
  with Pong. The firmware iBoot loaded is still in place after m1n1 powers the PHY up.
- Run 42 (`fwstart` = `phy_cpu_wake()`, m1n1 StandardASC handlers, no DART, physical buffers):
  HELLO/ack, endpoint map 0x0, 0x1 (crashlog, buffer prealloc at 0x10007df0), 0x20, 0x21, 0x22;
  AP power 0x20, IOP power 0x20; MxWrap status 0x16e. core+0x260 0x881 -> 0xc81:
  UC_TNBL_DONE set for the first time.
- Run 43 (full sequence, MACBIST + FWWAKE at the partC firmware point, PHY reset released at
  power-on): firmware boots and UC_TNBL_DONE sets; it rewrites core+0x120 (0x155500f3 ->
  0x155300f3) and core+0x6c (0x70000ea -> 0x70010ea). STATUS2 stays 0x104 (bit 8 high); SS
  unchanged (PORTSC1 0x2b0).
- Run 44 (as 43 with NORESET: PHY reset released after the firmware, the macOS order):
  firmware boots, UC_TNBL_DONE sets, AUSPLL not locked (the harness PLL start runs before the
  release), STATUS2 bit 8 high.

Open: the macOS AUSPLL/common bring-up order relative to the reset release and the firmware
(setDevicePowerState / setPhyMxwrapPowerState / partA-B), and whether the application endpoints
0x20-0x22 (AppleTypeCPhyCIO80PhyMBI) take a mode message.

## SUPERSPEED LINK UP on port 1: U0 at SuperSpeedPlus (10 Gbps) (2026-10-28 ~11:20, runs 45-52)

Port 1 (left-front), USB3 stick, over the stage-1 proxy. Final PORTSC1 = 0x00021603: CCS 1,
PED 1, PLS 0 (U0), speed 5 (SuperSpeedPlus, Gen 2). The USB2 port drops its connection at the
same time (PORTSC0 0x206f1 -> 0x2202a0): the stick moved to SuperSpeed.

Command (from forks/omacom-m1n1, after `usb3-usb4/mac_ctl.py`):
```
MACBIST=1 FWWAKE=1 NOPHYPWR=1 NORESET=1 NOLANES=1 HCRST_AFTER=1 MACORDER=1 MACXBAR=1 U2RESET=1 \
  .venv/bin/python kernel/tools/t6050_phy_power_test.py \
  xhcirst tunapply txdeton cio tunables tunx u3bist
```
What each piece contributed (each was tested on its own, runs 45-52):
- `NOLANES` (macOS aciophy_slpctrl_init for mode 4: core+0xc &= ~0x2a, then the active lane's
  override bits only; no tx/rx_powerup, no TX SHM clock writes - those are DisplayPort-only):
  STATUS2 bit 8 (PhyStatus) finally drops (0x104 -> 0x84). The old lane block kept the PHY stuck.
- `HCRST_AFTER`: xHCI reset with CIO on and the PIPE on USB3 now completes (HCRST and CNR
  clear, glue kept); the SS warm reset completes (PORTSC1 0x2b0 -> 0x2802a0, WRC/PRC). The
  controller runs on the USB3 PHY's PIPE clock.
- `MACORDER` (PHY dance + firmware before the PIPE overrides/lock): the TXDETRX ack now sets
  (0x1); the SS port starts clean (PORTSC1 0x2a0, PR 0).
- `MACXBAR` (aciophy_xbar_config, mode 4): normal orientation = lane mode lane0 1 / lane1 2
  (core+0x6c |= 0x44, clear bits 23/25), crossbar 0x110; flipped = 0x28 (clear 22/24), 0x111;
  core+0x6c [1:0] = 2. The link trained with it (normal orientation); a U2RESET run without it
  has not been done.
- `U2RESET`: the stick had run USB2 since boot, so its SS side was in SS.Disabled with the
  receiver terminations off. A USB2 port reset (PORTSC0 PR) sends it back to Rx.Detect; the host
  SS port then goes RxDetect -> Polling (PLS 7) -> U0.
- `FWWAKE`: PHY CPU RTKit firmware booted at the partC firmware point (UC_TNBL_DONE set).
- `NORESET`: PHY reset (reg[39] bit 4) released after the firmware, as macOS does.
- `MACBIST`: the macOS partC dance with the T6050 bits.
- `tunapply` + `txdeton`: controller tunables and the TXDETRX lock (setUSB3Mode order).
- Not used: the harness `wake` (t8122 common wake / RCAL) and `pllstart2` (t8122 AUSPLL start).
  macOS starts the AUSPLL from the AP only in the DisplayPort paths; core+0x7034 stays 0.

Not done: xHCI rings / device enumeration over SS (needs the full host driver: path 2).

Ablations (2026-10-28 ~11:30), same command with one flag removed:
- Without `FWWAKE` (run 54): UC_TNBL_DONE clear, STATUS2 stuck at 0x104, HCRST times out and
  the controller reads all zeros. The PHY CPU firmware is required.
- Without `MACXBAR` (run 55, Linux t8122 lane values 0x70000ea): after U2RESET the SS port goes
  RxDetect -> Polling (PLS 7) and back to RxDetect, no U0. The macOS lane mode is required.
- Repeat of the full command (run 53): U0, speed ID 5 again.
(Speed ID 5 = SuperSpeedPlus under the default xHCI protocol speed-ID map.)

### Port 1 SuperSpeed host sequence (the spec for the kernel driver)

Addresses for port 1; port 0 = -0x8000000, port 2 = +0xd8000000 on the usb-drd / atc-phy windows.
DRD = 0x2aa280000 (dwc3), PIPE = 0x2aaa84000 (usb-drd reg[3]), PCTL = 0x2aaa80000 (reg[5]),
CORE = 0x2ab000000 (atc-phy reg[2]), BB = CORE+0x29000, PWR = 0x2ab200000 (reg[39]),
MXW = 0x2ab140000 (reg[38], mailbox at MXW+0x8000).

1. xHCI reset with CIO off (USBCMD |= HCRST, wait HCRST and CNR clear); glue cd28 0x886 stays.
2. Controller tunables (usb-drd1 ADT, windows per applyAllTunables; GBL/DBG at DRD+0xc100,
   CIO_REGS at DRD+0xcd00).
3. PCTL+0x18 |= 1 (TXDETRX lock request).
4. Power domains atc1_common, auss, atc1_cio, atc1_cio_usb, atc1_cio_auss on; PWR: sleep small
   (b0, ack PWR+4 b0), sleep big (b1, ack b1), clamp off (b2), APB reset release (b3). PHY reset
   (b4) stays asserted.
5. PHY tunables: ATC_COMMON_CFG reg[43], ATC_FABRIC reg[40], ATC0AXI2AF reg[41], AUS40CMN_SHM
   reg[5], AUSPLL_CORE reg[8], ATC0AXI2AF_LIOA reg[42], LN0/1_RX_EQ_DFLT reg[18]/[27],
   LN0/1_RX_CFG_TX_OF_RXCLK reg[20]/[29].
6. GCTL prtcap host (DRD+0xc110 [13:12] = 1), no core soft reset.
7. slpctrl (mode 4): CORE+0xc &= ~0x2a; for the active lane L (0 normal, 1 flipped):
   CORE+0x10 &= ~(1<<(2+L) | 1<<(6+L)); CORE+0xc &= ~(1<<(16+L) | 1<<(8+L) | 1<<(12+L));
   CORE+0x120 &= ~(1<<(6+L) | 1<<(2+L) | 1<<(10+L)).
8. MXW+0x40 |= 1 (MxWrap IDLE_CTRL).
9. xbar: normal CORE+0x6c = (v & ~(0xfc|1<<23|1<<25)) | 0x44, CORE+0x78 [16:0] = 0x110;
   flipped (v & ~(0xfc|1<<22|1<<24)) | 0x28, 0x111; then CORE+0x6c [1:0] = 2.
10. BIST first half: BB+0x4 |= 1; BB+0x10c = (v & ~0x1e100000) | 2<<25; BB+0x4 bit 3 toggle;
    BB+0x110 = (v & ~0x660) | 0x220; BB+0x4 bit 3 toggle; PWR+0x8 bit 1 = flipped.
11. PHY CPU: MXW+0x28 = 0x10; RTKit boot over the mailbox (HELLO -> ack v12, EPMAP -> ack,
    start EP 1 crashlog, AP power 0x20, IOP power 0x220; wait IOP and AP power 0x20);
    wait CORE+0x260 bit 10 (UC_TNBL_DONE), 1 s.
12. PWR |= 1<<4 (PHY reset release); wait 100 ms.
13. BIST second half: BB+0x10c |= 1<<20; toggle; wait BB+0x104 bit 8 clear; BB+0x10c PWR_DOWN_OV
    = 3; toggle; BB+0x110 &= ~0x660; toggle; PIPE+0x20: [3:0] = 3, bit 12 clear.
14. PIPE: +0x4 &= ~0x6; +0x0 |= 1, |= 4; +0x10 |= 1, wait +0x14 bit 0; wait PCTL+0x1c bit 0.
15. PIPE+0xc: clock field [6:4] = 0, data [1:0] = 0 (USB3), clock [6:4] = 1; +0x0 &= ~5;
    +0x10 &= ~1, wait +0x14 clear.
16. PCTL+0x18 &= ~1, wait PCTL+0x1c clear.
17. xHCI reset (completes now on the USB3 PIPE clock); restore glue cd28/cd2c/cd40/cd44 if
    changed; prtcap host; run; port power.
18. USB2 port reset on the HS port of the same connector: the device retries SS and trains to U0.

## SuperSpeed under Linux: the stick reads as a disk at 10 Gbps on port 1 (2026-10-28 ~12:12, boots ss1-ss4)

Boot ss4 (`usb 4-1` = port 1's USB3 root hub):
```
usb 4-1: new SuperSpeed Plus Gen 2x1 USB device number 2 using xhci-hcd
usb-storage 4-1:1.0: USB Mass Storage device detected
scsi 0:0:0:0: Direct-Access     SanDisk  Extreme Pro DDE1 0010 PQ: 0 ANSI: 6
sd 0:0:0:0: [sda] 1953525160 512-byte logical blocks: (1.00 TB/932 GiB)
 sda: sda1
```
Kernel: linux-aurora `t6050-j714c` (uncommitted on top of ae65f0d3a88e):
- `drivers/phy/apple/t6050-usb2.c`: a port whose node has the `atc-power` window runs steps
  1-16 of the sequence above after the USB 2.0 flip. Its PHY CPU RTKit boot is a polling
  hand-roll of m1n1's StandardASC (no mailbox driver, no IRQs). `phy_calibrate()` (called by
  usb_add_hcd after the xHCI driver's reset) is step 17's glue restore and prtcap host; the
  hub's USB 2.0 port reset is step 18. Normal plug orientation only.
- `drivers/phy/apple/Kconfig`: `select APPLE_TUNABLE`.
- `t6050-j714c-usb2.dtsi`, `usb2phy_1`: 16 windows (usb2phy, pipehandler, core, pctl, drd-cfg,
  ausbc-debug, bulk-fabric, atc 0x30000, atc-mxwrap, atc-power, atc-fabric, atc-axi2af,
  atc-axi2af-lioa, atc-common-cfg, pmgr, pmgr-mxwrap) and 13 `apple,tunable-*` properties, 189
  triples from the usb-drd1 / atc-phy1 ADT tunables (boot-j714c/adt.txt), offsets relative to
  the window of the same name, in the proxy's apply order.
- CIO domains (atc1_common, auss, atc1_cio, atc1_cio_usb, atc1_cio_auss) and atc1_phymxwrap are
  powered by direct PMGR writes in phy_init, after step 1 (genpd would power CIO at probe,
  before the xHCI reset).

Boot command (Mac on the resident proxy, fresh from a reset):
```
IMG=/tmp/opencode/aurora-build-j714c/arch/arm64/boot/Image.gz \
DTB=/tmp/opencode/aurora-build-j714c/arch/arm64/boot/dts/apple/t6050-j714c.dtb \
WDT=170 EXTRA="pd_ignore_unused" /home/ed/dev/omarchy/kernel/tools/boot_t6050.sh ss4
```
`boot_t6050.sh` needs its absolute path (it derives the log paths from `$0`).
Not tested: a boot without `pd_ignore_unused`, and a second ss4 boot (the result is from one boot).
The tunable triples were generated by a scratchpad script (not in this folder) from adt.txt.

Boots:
- ss1: started on a Mac still in the state of the last proxy run (CIO on, PHY CPU running; the
  harness disarms the watchdog and does not reboot). Step 1 HCRST CNR stuck, PHY CPU silent,
  UC_TNBL_DONE already set, stick not seen on USB 2.0. Boot only after a reset.
- ss2, ss3 (clean): PHY CPU RTKit v12, endpoints 0x3, AP 0x20, IOP 0x20, one crashlog message
  (prealloc 0x10007df0); HCRST/CNR ok, CIO ok, UC_TNBL_DONE set, PhyStatus s1/rise/fall ok,
  TXDETRX ack/release ok, PIPE lock ack not seen in 10 ms. Glue 0 at the end of step 16. The
  stick enumerated high-speed on `usb 3-1` (port 1's USB 2.0 bus).
- Cause: the USB 2.0 flip's GCTL core soft reset clears the Apple glue (cd28/cd2c 0x886, cd40
  0x3c20060c, cd44 0x2000b from iBoot); the proxy runs always had it.
- ss4: the driver writes the iBoot glue values back right before step 1 (CIO off, the write
  sticks: cd28 reads 0x886). SuperSpeed Plus Gen 2x1, disk attached, partition table read.

Seen in ss4 and not explained: at the end of step 16 the glue reads 0 again (CIO on), and
after the xHCI reset `phy_calibrate()` finds all four changed and writes those zeros back
("glue restored 0xf"). The link trains anyway. PIPE lock ack still not seen in 10 ms.

Screen capture: the BRIO's MJPEG mode tops out at 1920x1080 (a 3840x2160 request returns
1080p). A 150 s recording (`ffmpeg -f v4l2 -input_format mjpeg -video_size 1920x1080 ... -vf
fps=4 -c:v libx264`) catches the lines that scroll off before the shell prompt; tesseract on
the frames finds them.

## Network logs instead of the camera; stick test: SuperSpeed 1 of 2 boots (2026-10-28 ~12:33, boot net1)

USB Ethernet adapter (ASIX AX88179B, 0b95:1790) in the left rear port (port 0, USB 2.0 host),
cabled to the router: enumerates as `usb 1-1` at 480 Mb/s, binds `cdc_ncm` as eth0
(6c:6e:07:41:d2:14), DHCP 192.168.188.39, link 1000 Mb/s, ping to 192.168.188.1 3/3.

`initramfs/init-net` (+ `initramfs/udhcpc.sh`; packed as `boot/initramfs-net.cpio.gz` = the
stock image followed by a gzip cpio of the two files, the later /init wins): waits for eth0 and
/dev/sda, DHCP, runs read-only stick tests (USB speeds, blkid, a 2 GiB direct read, sha256 of
the first 256 MiB twice), keeps dmesg, and sends the report one way to 192.168.188.35:8000 (open
in Omarchy's ufw for 192.168.188.0/24). Nothing listens on the Mac. Receiver on Omarchy: a
one-shot Python TCP accept that writes the bytes to a file (scratchpad, not in this folder).
Boot: `IRD=/home/ed/dev/omarchy/kernel/boot/initramfs-net.cpio.gz` with the ss4 command.

net1 report (`log/net1-report.txt`, includes the full dmesg):
- Stick on `usb 3-1`, speed 480 (USB 2.0), "SanDisk 3.2 Gen2"; sda1 exFAT, LABEL "USB";
  2 GiB direct read 51.2 s = 40.0 MB/s; sha256 of the first 256 MiB equal on both reads.
- The SS driver lines are identical to ss4 (glue written 0x886, HCRST/CNR/CIO/mxwrap/
  UC_TNBL_DONE ok, RTKit v12 AP/IOP 0x20, PhyStatus ok, lock 0, glue 0 at step 16, "glue
  restored 0xf" after the xHCI reset, PORTSC2 0x2a0 = PP set, RxDetect). ss4 went
  `usb 3-1` high-speed first, then `usb 4-1` SuperSpeed Plus; net1 stayed high-speed.
- So the SuperSpeed link trains on some boots only (1 of 2 so far). Not known: whether the
  host SS port reached Polling in net1 (no PORTSC trace after the hub's USB 2.0 reset), and
  where the glue goes to 0 between step 1 and step 16 (the proven proxy runs report it held
  0x886 with CIO on).

## Glue traced; SuperSpeed is a race with the hub's USB 2.0 enumeration (2026-10-28 ~12:45, boots net-g1..g3)

Driver change (linux-aurora, uncommitted): cd28 logged after the iBoot write and after each of
steps 1-16; `phy_calibrate()` now writes the iBoot glue values back after the xHCI reset
(only where they differ) instead of the end-of-sequence snapshot, and logs what it read.
Three network boots, adapter in port 0 each time (`log/net-g1..g3.txt`):

| Boot | Stick | 2 GiB direct read |
|---|---|---|
| g1 | `usb 3-1`, 480 Mb/s | 40.0 MB/s |
| g2 | `usb 3-1`, 480 Mb/s | 39.4 MB/s |
| g3 | `usb 4-1`, 10000 Mb/s, SuperSpeed Plus Gen 2x1 | 777.5 MB/s |

- cd28 in all three: 886 after the write, after step 1 and after steps 2-3; 0 from the CIO
  domains (step 4) through step 16. After the xHCI reset it reads 0x886 0x886 0x3c20060c 0x2000b
  again and nothing is rewritten. The glue is not wiped: it reads 0 while CIO is on before the
  controller runs on the USB3 PIPE clock. The earlier snapshot restore wrote those zeros back
  over the iBoot values (ss2, ss3, ss4, net1).
- Every SS driver line is identical in g1, g2 and g3 (RTKit, HCRST/CNR, CIO, UC_TNBL_DONE,
  PhyStatus, lock 0, TXDETRX, PORTSC 0x206e1 / 0x2a0 before and after the reset).
- The difference is the order after the root hubs register. g1, g2: `usb 3-1: new high-speed`
  right after hub 4-0, the stick stays on USB 2.0. g3: no USB 2.0 enumeration of the stick at
  all; `usb 4-1: new SuperSpeed Plus` follows a few seconds later. ss4: high-speed first, then
  SuperSpeed (the hub's USB 2.0 port reset worked as the proxy's U2RESET did).
- sha256 of the first 256 MiB is the same at 480 Mb/s and at 10 Gbps
  (5fd91c2a...0b5d3a) in every boot.
- With the adapter in port 0: 1 of 3 SS. Without (ss4): 1 of 1. Each port has its own
  controller and PHY.

Since the glue fix, SuperSpeed has come up on 2 of 5 boots. Not known: what the host SS port
does after the hub's USB 2.0 port reset in a failing boot (stays in RxDetect = the stick never
retries SS; Polling then back = training fails). The kernel has DEBUG_FS (xhci debugfs
portsc) and DYNAMIC_DEBUG (hub / xhci-hub port events via `dyndbg=`) for that.

## Timing and SUSPHY tests (2026-10-28 13:00-13:58, boots net-t*, net-p*, net-s*, net-w*, net-u*)

Driver boot parameters (module `phy_apple_t6050_usb2`, uncommitted): `ss_pace_us` (gap after
each sequence write, default 0), `ss_settle_ms` (pause after step 16, default 0), `ss_susphy`
(set GUSB3PIPECTL SUSPHY before step 1, default 1). A 3 s logger after the xHCI reset prints
every change of PORTSC (USB 2.0 / SS) and GDBGLTSSM.

| Batch | Setting | SuperSpeed |
|---|---|---|
| ss4, net1, g1-g3, t1-t3 | no pacing, SUSPHY cleared by the flip | 3 of 8 |
| p1-p4, s1-s4 | 1 ms per write | 0 of 8 (s1-s4: the parameters had the wrong prefix) |
| w1-w4 | settle 2000 ms | 0 of 4 |
| u1-u4 | SUSPHY set before step 1 | 0 of 4 |

- Failing boots without SUSPHY: the SS port stays in RxDetect (PLS 5) through the hub's
  USB 2.0 resets; it never reaches Polling. GDBGLTSSM stays 0x9cc20024.
- Passing boot t1: Polling 16 ms after the hub's first USB 2.0 port reset, U0 3 ms later.
- With SUSPHY set (u1): the SS port leaves RxDetect on its own after the stick has enumerated
  on USB 2.0: Polling (0x2e0) at 3.49 s, SS.Inactive (0x2c0) at 4.58 s; the hub then warm
  resets it at 6.2 s (Polling again, then RxDetect, no connection).
- The resident proxy leaves port 1 in device mode with GUSB3PIPECTL 0x01021102 (SUSPHY set),
  GUSB2PHYCFG 0x00102400, glue 0x886: the proven proxy runs never ran the USB 2.0 flip.

## Port 1 without the USB 2.0 flip, from the proxy start state: 0 of 5 (2026-10-28 14:20-14:40, boots net-i1..i4)

Driver change (linux-aurora, uncommitted): on port 1 `t6050_usb2_init()` skips
`t6050_usb2_host_flip()` and runs `t6050_usb3_up()` directly (step 6 sets host mode); ports 0
and 2 keep the flip. First it logs the inherited state (pipehandler first, the core only with
dwc3 out of reset). Five boots with the hub and port event log; the first i1 report was
overwritten by the batch's i1.

- The chainloaded loader (`build/m1n1.macho`) is the `T6050_NO_HOST_PREP` build: its
  "T6050 host prep skipped" string is in the binary. It does not flip port 1; no loader change.
- Inherited state, every boot: pipehandler +0x0 0, +0x4 0x16, +0xc 0x22, +0x1c 1, +0x20 0x9332;
  GCTL 0x30c12004, GUSB2PHYCFG 0x102400, GUSB3PIPECTL 0x1021102, glue 0x886 / 0x3c20060c,
  PORTSC 0x280 / 0x280. Equal to the resident proxy's values.
- Sequence: cd28 0x886 at every step, CIO on included; PIPE lock 1. Same as with SUSPHY set in
  u1-u4 and in the proxy runs (with the flip it was 0 from step 4, lock 0).
- End of step 16: PORTSC 0x206e1 / 0x2b0, the SS port in a warm reset (with the flip: 0x2a0).
  It completes after the xHCI reset (0x2802a0 at 2.07 s, then RxDetect 0x2a0), as with
  `HCRST_AFTER` in the proxy runs.
- i1-i3 and the first i1: the hub's two USB 2.0 port resets (2.10 s, 2.22 s); the stick stays
  on USB 2.0 (`usb 3-1: speed 480`), the SS port stays in RxDetect.
- i4: after the second USB 2.0 reset the stick leaves USB 2.0 (disconnect, 0x2202a0 at 2.28 s).
  The SS port stays in RxDetect until 3.46 s, then Polling (0x2e0), SS.Inactive (0x2c0) at
  4.55 s, the hub's warm reset at 6.19 s, RxDetect again; the stick is back on USB 2.0 at
  6.31 s. Same late Polling and SS.Inactive as u1 (Polling at 3.49 s).
- From 2.18 s the usb4 root hub suspends and resumes (WCE/WOE on the SS port, 0xa0002a0); from
  3.10 s the usb3 root hub is suspended too.

| Batch | Setting | SuperSpeed |
|---|---|---|
| i1-i4 + first i1 | no flip on port 1, proxy start state, SUSPHY set | 0 of 5 |
| j1-j4 | as i, GUSB3PIPECTL SUSPHY cleared after the step 17 xHCI reset (`ss_susphy_clear=1`) | 0 of 4 |

- j (new boot parameter `ss_susphy_clear`, default 0): the readback after the xHCI reset is
  GUSB3PIPECTL 0x1001102. Every boot has the trace of i1-i3: the SS port's warm reset completes
  at 2.07 s, the hub's USB 2.0 resets at 2.10 s and 2.22 s, the stick stays on USB 2.0, the SS
  port stays in RxDetect.

## The proven proxy command fails today too (2026-10-28 ~15:05, `log/proxy-ref1.log`, `log/proxy-swap1.log`)

The command of runs 45-53 (`MACBIST FWWAKE NOPHYPWR NORESET NOLANES HCRST_AFTER MACORDER MACXBAR
U2RESET`, steps `xhcirst tunapply txdeton cio tunables tunx u3bist`, then `reboot`), each run
from a reset (after j4's watchdog reset, after the first run's reboot):

| Run | Orientation | Result |
|---|---|---|
| ref1 | normal | USB 2.0 reset: PORTSC0 0x206f1 -> 0x220e03 (stick enabled at high speed); SS port 0x2a0 RxDetect for the whole 6 s |
| swap1 | flipped (`SWAP=1`) | the same |

- Both: HCRST after the PHY ok, glue 0x886 kept, base PORTSC1 0x2a0 (PR 0, clean: no warm reset
  pending, unlike the kernel's 0x2b0), TXDETRX ack and release ok, PIPE lock ok, BIST s1 ok, rise
  timeout, fall ok. GUSB3PIPECTL 0x1021102 (SUSPHY set), GDBGLTSSM 0x9cc20024 throughout.
- Last SuperSpeed boot: t1 (~13:00). Since then 0 of 27 kernel boots (t2-t3, p, s, w, u, i + first i1, j) and 0 of 2 proxy runs.

After Ed reseated the stick in port 1 (adapter not pressing on it), the same command from a
reset (`log/proxy-ref2.log`, `log/proxy-swap2.log`):

| Run | Orientation | Result |
|---|---|---|
| ref2 | normal | as ref1: stick at high speed after the USB 2.0 reset, SS port in RxDetect for 6 s |
| swap2 | flipped | the same |
| ref3 | normal, network adapter out of port 0 | the same |

- The harness (`tools/t6050_phy_power_test.py`) is unchanged since 11:13, before runs 45-53.
  The command that trained the link at ~11:20 fails now with or without the adapter, in both
  orientations, after a reseat of the stick.
- The stick in Omarchy (Bus 009, xhci-pci-prom21): `0781:55e8 SanDisk 3.2 Gen2`, usb-storage,
  10000M. The stick still does SuperSpeed.

After a full shutdown and power-on of the Mac (stick in port 1, adapter in port 0):

| Run | Setting | Result |
|---|---|---|
| cold1 | normal, first run after the cold boot | as ref1: stick at high speed, SS port in RxDetect |
| twice1a + twice1b | normal, two runs with no reset in between | both as ref1; in the second the PHY CPU no longer answers RTKit (already booted), UC_TNBL_DONE still set |

- In every run since ~13:00 the stick stays on USB 2.0 after the USB 2.0 reset (PORTSC0
  0x220e03). In runs 45-53 it left USB 2.0 at that point (0x206f1 -> 0x2202a0) and trained to U0.
  The stick does not see the host's SuperSpeed receiver: the host side of the SS lanes, or the
  contact to them, is what changed.
| turn1 | stick turned 180° in port 1, normal | as ref1 |
| turnswap1 | stick turned 180° in port 1, flipped (`SWAP=1`) | as ref1 |

- With ref3/swap2 before the turn, both plug orientations have been run with both lane
  settings: the stick never leaves USB 2.0, the SS port stays in RxDetect.

macOS 27.2 on the same Mac, stick in port 1 (after the 180° turn), System Information: "USB 3.1
Bus", Location ID 0x01000000, driver AppleT8142USBXHCI; SanDisk 3.2 Gen2 (0781:55e8) at Location
ID 0x01200000, Link Speed 10 Gb/s, power allocated 4.48 W (896 mA). Port 1 and the stick do
SuperSpeed under macOS.

macOS port state (`ioreg`, same session): Type-C controllers on SPMI: `hpm0@C` (nub-spmi-a0)
= Port-USB-C@1, `hpm1@A` (nub-spmi-a0) = Port-USB-C@2, `hpm2@C` (nub-spmi-a1) = Port-USB-C@3.
Port-USB-C@1 and @2 (the two left ports): ConnectionActive, TransportsActive ("CC","USB3"),
PlugOrientation 2. Port-USB-C@3: ("CC","USB3","USB2"), PlugOrientation 1.

Restart from macOS into m1n1 without touching the stick, then the reference at once:

| Run | Setting | Result |
|---|---|---|
| macos-swap1 | flipped (`SWAP=1`, matches PlugOrientation 2) | as ref1 |
| macos-ref1 | normal | as ref1 |

Batches i and j ran while the reference itself failed: their 0 of 5 and 0 of 4 do not judge
skipping the flip or clearing SUSPHY after step 17. Both settings are untested, not refuted.

PHY reset released early, then the reference on top (both flipped, `SWAP=1`; `log/proxy-stackA1.log`,
`log/proxy-stackB1.log`):

| Run | Setting | Result |
|---|---|---|
| stackA1 | reference without `NORESET` (PHY reset released at power-on, power ctrl 0x1b), no reboot | as ref1 |
| stackB1 | full reference on top of A, then `reboot` | as ref1 (HCRST at the start completes) |

Comparison with the morning runs (record of the session that ran them:
`~/.config/Claude/side-session-notes/local_41904250-8a0b-4c2a-b5d3-767316a3a49b/morning-pass.txt`;
each morning run started from a `mac_ctl.py` reboot, which is `p.reboot()` like the harness
`reboot` step; the network adapter was not in the Mac then):

- Every displayed host register in run 52 equals today's ref1 up to the USB 2.0 reset: HCRST after
  the PHY ok, glue 0x886 0x886 0x3c20060c 0x2000b, base PORTSC1 0x2a0 (PR 0), GDBGLTSSM
  0x9cc20024, PORTSC0 0x206e1 -> 0x206f1, GUSB3PIPECTL 0x1021102, GUSB2PHYCFG 0x2102500, GCTL
  0x30c11004, GSTS 0x7e800001.
- Runs 52, 53 and 55 (all three morning runs with `U2RESET`): while the USB 2.0 reset was still
  running (PORTSC0 0x206f1, PR 1) the SS port went Polling (0x2e0) and, in 52 and 53, U0
  (0x21603, speed 5); then PORTSC0 0x2202a0 (the stick left USB 2.0). Today (14 runs): the
  USB 2.0 reset ends with the stick enabled at high speed (0x220e03), the SS port stays 0x2a0.

## Replug with the SuperSpeed side up: U0 at once (2026-10-28 ~16:00, `log/proxy-hotplug3.log`)

Harness change: `WATCH_SECS` sets the watch after the sequence (default 6 s). The reference
(flipped, `SWAP=1`, with `U2RESET`), watch 120 s, `WDT_SECS=178`. (hotplug1/2 used `NOSWITCH=1`
to skip the warm reset; it also skips the PIPE switch to USB3 in step 15, so the xHCI reset
after the PHY timed out and the controller read 0. Not a Mac fault.)

- USB 2.0 reset: as all day, PORTSC0 0x206f1 -> 0x220e03 (stick at high speed), SS 0x2a0.
- Ed unplugged the stick, counted to three, plugged it back in the same way up: PORTSC0 0x2202a0
  (USB 2.0 disconnect), SS 0x21603: CCS, PED, U0, speed 5 (SuperSpeedPlus). No Polling state
  seen at the 10 ms watch rate.
- The host side of the sequence is sound. What stopped working at ~13:00 is the stick going for
  SuperSpeed on a USB 2.0 reset; a fresh connection trains at once.
- Not explained: t1 passed and t2, 3.5 minutes later, failed with nothing physical changed.

The Type-C controller can simulate a disconnect: linux-aurora's tipd driver supports
`apple,sn201202x` over SPMI (`drivers/usb/typec/tipd/spmi.c`) and has the 4CC command `DISC`
(debugfs, `CONFIG_TYPEC_TPS6598X_DEBUG_COMMANDS`). `t6050-j714c-usb.dtsi` (not included by
`t6050-j714c.dts`) has the SPMI controller `spmi@28a188000` and hpm0 at SPMI address 0xc. macOS:
hpm0@C and hpm1@A on nub-spmi-a0, hpm2@C on nub-spmi-a1.

## Simulated disconnect through port 1's Type-C controller (2026-10-28 ~16:10-16:40, boots net-k1, net-l1, net-m1)

Kernel change (linux-aurora, uncommitted): `t6050-j714c-usb2.dtsi` gets the SPMI controller
`spmi@28a188000` (nub-spmi-a0) with port 1's controller only, `hpm1` (ADT hpm1, left-front,
`usb-pd@a`, `apple,sn201202x`, polled, no interrupts, `connector` without a graph), and
`usb2phy_1` points at it (`apple,typec-controller`). tipd exports `tps6598x_exec_cmd_tmo` and
`tps6598x_block_read`; `spmi.c` has `sn201202x_simulate_disconnect()`. The PHY driver queues it
at the end of step 16 (`ss_replug_s`, default 2, 0 = off) and retries every 100 ms until the
controller is bound. Port 1 runs without the flip, SUSPHY set, `ss_susphy_clear` 0.

| Boot | Sequence | Result |
|---|---|---|
| k1 | `DISC` (1 byte: 2) | `-EINVAL`: the controller answers `!CMD` outside its debug mode; stick on USB 2.0 |
| l1 | `LOCK` "417J" (ADT target-type J714c, first four characters reversed, as m1n1's `tps6598x_enter_kis`), `DBMa` 1, `DISC` 2, 2.5 s, `DBMa` 0, `LOCK` 0000 | every command 0; USB 2.0 disconnect at 2.17 s, then no port 1 event up to the report at 35 s (no stick) |
| m1 | as l1, with the controller state logged | as l1 (the stick was back on USB 2.0 at boot: l1 left nothing behind) |

Controller state in m1 (MODE, STATUS 0x1a, POWER_STATUS 0x3f, DATA_STATUS 0x5f):
- before: APP, 0x100248fd, 0xf01, 0x80000073;
- right after `DISC`: DISC, 0x58000002, 0, 0;
- 2.6 s later: APP, 0x100240fd (bit 11 clear), 0x1, 0x80000073;
- 14.2 s (about 12 s after the reattach): APP, 0x100248fd, 0xf01, 0x80000073, the state of
  before. Still no USB 2.0 or SS connection on port 1 up to 35 s.
| n1 | `LOCK`, `DBMa` 1, `DISC` 2, then at once `DBMa` 0, `LOCK` 0000 | every command 0; same as l1/m1 |

n1 controller state: DISC done: DISC 0x58000002; locked again (0.14 s later): APP 0x50000002;
0.7 s: APP 0x10000002; 2.3 s after `DISC`: APP 0x100240fd, power 0x1, data 0x80000073 (attached,
data connection, STATUS bits 11:10 = 0: PP_HV switch off); 11.6 s after `DISC`: 0x100248fd,
power 0xf01 (bits 11:10 = 2: PP_HV switch enabled as output, the state before). No port 1 USB 2.0
or SS event after the disconnect up to the report at 35 s; PORTSC 0x0a0002a0 / 0x0a0002a0.
| o1 | as n1, with the port and PHY registers logged around it | stick back on USB 2.0 only (`usb 3-1: speed 480`) |

o1: the hub had reset the stick to high speed (2.27 s) before the disconnect (USB 2.0 disconnect
2.40 s). Controller attached again at 4.54 s (power 0x1); the stick reconnected on USB 2.0 at
5.04 s (PORTSC1 0xa0206e1, WCE/WOE: the bus was suspended) and enumerated at high speed; the SS
port stayed in RxDetect (0xa0002a0). Power 0xf01 at 13.9 s. Port and PHY registers before /
after: PORTSC 0x206e1 / 0x2b0 -> 0xe03 / 0xa0002a0, usb2phy 0x102 0x0 0xd0000f -> 0x102 0x0
0xc0000f (SIG bit 20 clear), pipe mux 0x10, GUSB2PHYCFG 0x2102500, GUSB3PIPECTL 0x1021102, power
0x1b / 0x103, UC_CTRL 0xc81, STATUS2 0x1c4 -> 0xc4: the SS side is still up. In n1 the stick had
not been reset before the disconnect and did not come back at all.
| p1 | as o1, `usbcore.autosuspend=-1` | as n1: the stick did not come back (PORTSC 0x2a0 / 0x2a0 at 28 s) |

Orientation: since Ed turned the stick 180° (~15:20) it is in the flipped orientation (macOS
PlugOrientation 2; the controller's STATUS bit 4 set: 0x100248fd). The hotplug3 replug that
trained ran the flipped lane setting (`SWAP=1`); the kernel boots k1-p1 ran the driver's fixed
normal crossbar. New boot parameter `ss_flip` (default 0): active lane 1 in step 7, lane mode
0x28 (bits 22/24 cleared) and crossbar 0x111 in step 9, PWR+0x8 lane swap bit 1 in step 10, as
the harness's `SWAP` path.
| q1 | as o1, `ss_flip=1` | the stick goes for SS after the reattach: SS port 0xa4002c0 (SS.Inactive, PLC) at 8.29 s, hub warm reset, RxDetect at 8.44 s; then no port 1 device on either bus |

q1: controller attached again at 5.0 s (power 0x1); SS.Inactive 3.3 s later, during a suspended
usb4 root hub (WCE/WOE on the SS port). In hotplug3 (proxy, nothing suspends the port) the
flipped setting went to U0 at once.
| r1 | as q1, `usbcore.autosuspend=-1` | as q1: SS.Inactive (0x4002c0, no WCE/WOE) at 8.29 s, hub warm reset, then no device |

Harness step `disc` (new): port 1's controller over SPMI from the proxy (`m1n1.hw.spmi`, nub-spmi-a0
SID 0xa, ACE3 register window as tipd/spmi.c): wakeup, `LOCK` "417J", `DBMa` 1, `DISC` 2,
`DBMa` 0, `LOCK` 0000, then 30 s watch of PORTSC0/PORTSC1 and the controller state.

proxy-disc1 (reference flipped with `U2RESET`, 3 s watch, then `disc`; `log/proxy-disc1.log`):
every command 0. Controller: 0.02 s APP 0x50000002, power 0; 2.22 s 0x100240fd, power 0x1, data
0x80000073; 3.48 s power 0xf01; 11.46 s 0x100248fd (the state before). PORTSC0 0x2202a0 and
PORTSC1 0x2a0 for all 30 s: the stick does not come back on either bus. A physical replug on the
same bring-up (hotplug3) went to U0 at once: `DISC` is not a replug for the stick.

Follow-up for the driver: `ss_flip` is a test switch. The orientation is in port 1's controller
(STATUS bit 4: set in the flipped plug, 0x100248fd), readable once tipd has bound.

proxy-replug2 (as disc1 with `NODISC=1`: no command, 90 s watch with the controller read every
20 ms; Ed replugged the stick by hand, same way up): the controller goes through the same states
as after `DISC`: 11.21 s detach (0x50000002, power 0), 15.97 s attached (0x100240fd, power 0x1),
17.27 s power 0xf01, 25.20 s 0x100248fd. The stick did not come back on either bus in 90 s. In
hotplug3 (same replug, no SPMI traffic to the controller) it went to U0 at once. With the
controller woken and read over SPMI, a real replug fails like `DISC`.

proxy-discq1 (`disc`, then SPMI sleep for the controller and a 60 s watch without reading it,
`DISC_QUIET=1`): every command 0; PORTSC0 0x2202a0, PORTSC1 0x2a0 for 60 s, no reconnection.

proxy-disca1 (`disc` with the controller's events read and cleared every 50 ms, `DISC_ACK=1`,
as tipd's interrupt handler: INT_EVENT1 0x14, 8 bytes, written back to INT_CLEAR1 0x18):
INT_EVENT1 stayed 0 (no event latched; the interrupt mask is iBoot's); controller states as
disc1; no reconnection in 60 s.

Where it stands (~17:20):
- The host SuperSpeed bring-up is right: a physical replug with no SPMI traffic to the controller
  trains to U0 at once (hotplug3, flipped lane setting).
- The USB 2.0 reset trick stopped working at ~13:00 (t1 passed, t2 3.5 min later failed); not
  explained.
- `DISC` reattaches the controller (same state sequence as a physical replug) but the stick does
  not come back on the proxy; in Linux it comes back erratically (USB 2.0 in o1, a failed SS
  attempt in q1/r1, nothing in n1/p1).
- A physical replug while the controller is woken and read over SPMI does not bring the stick
  back either (replug2). Not tested: the controller's system power state (register 0x20; tipd
  sends `SSPS` 0 at probe when it is not S0, the proxy runs never did).

proxy-discs1 (`DISC_SSPS=1`: system power state read first, `SSPS` 0, then `disc`): POWER_STATE
(0x20) was 0 (S0) before; `SSPS` 0 returned 0; controller states as disc1; no reconnection in 60 s.

proxy-gaid1 (`DISC_GAID=1`: `Gaid`, the controller's firmware reset, written to CMD1 instead of
`DISC`): the controller restarts (MODE BOOT at 0.06 s, APP at 0.31 s) with POWER_STATE 7, STATUS
0x10000000 (no plug), power 0, and stays there for 60 s (it falls asleep between reads); the stick
gets no power. iBoot sets the power state at boot; nothing set it here.

## The USB 2.0 reset trick works again after a controller firmware reset (2026-10-28 ~17:45, `log/proxy-gaid2.log`)

proxy-gaid2 ran right after gaid1 (port 1's controller reset by `Gaid`, the stick unpowered for
60 s, then the harness `reboot`, so iBoot set the controller up again: before the run it read APP,
POWER_STATE 0, 0x100248fd, power 0xf01 as always). The reference (flipped, `U2RESET`) trained:
PORTSC0 0x206f1 with SS 0x2a0 -> SS 0x2e0 (Polling) -> SS 0x21603 (U0, speed 5) -> PORTSC0
0x2202a0 (the stick left USB 2.0), the sequence of runs 52/53. First SuperSpeed by the USB 2.0
reset since ~13:00 (0 of 20 proxy runs before). The run then stopped at `SSPS` sent while the
controller was still restarting (`command not acknowledged`); the Mac was rebooted with
`mac_ctl.py`.

proxy-postgaid1 (the plain reference after an ordinary reboot, following gaid2's U0): fails
again (PORTSC0 0x220e03, SS 0x2a0). gaid2's difference: the stick had been without power for
over 60 s (gaid1) and was powered up again by iBoot.

proxy-gaid3 (`Gaid`, then `SSPS` 0 with retries): `SSPS` 0 returned 0 right after the restart;
the controller attached at 0.27 s (0x100240fd, power 0x1), power 0xf01 at 1.73 s, 0x100248fd at
9.53 s, the same sequence as after `DISC`; the stick did not come back in 60 s.

proxy-gaid4 (`DISC_GAID=nossps`: `Gaid` only): the controller stays in power state 7 with no plug
for 60 s (the stick unpowered), then `reboot` (iBoot sets the controller up and powers the stick).
The first kernel boot after it (fresh1) did not start: `chainload.py` timed out on the proxy that
was still coming up (`UartTimeout`); nothing touched port 1 (PORTSC1 0x280, GCTL 0x30c12004 on the
resident proxy afterwards). fresh1 was then booted again.

fresh1 (kernel boot right after gaid4's reboot: `ss_flip=1`, `ss_replug_s=0`, tipd bound to hpm1):
`usb 3-1: speed 480`; the hub's USB 2.0 resets at 2.27 s / 2.40 s, SS port in RxDetect throughout.

proxy-gaid5 (`DISC_GAID=sleep`: `Gaid`, `SSPS` 0, then the controller sent to sleep at once and
not read): no reconnection in 60 s.

## Where it stands (2026-10-28 ~18:10)

- SuperSpeed on port 1 trains when the stick is plugged in fresh with the SS side up and nothing
  has talked to port 1's controller over SPMI (hotplug3: U0 at once, flipped lane setting).
- No automatic way to get that fresh connection has worked:
  - USB 2.0 reset (`U2RESET`, the hub's port reset under Linux): 3 of 3 in the morning, then 1 of
    about 20 proxy runs (gaid2, after the stick had been unpowered for 60 s) and 0 kernel boots
    since 13:00;
  - the controller's `DISC` (debug mode), `Gaid` + `SSPS` 0, with or without the controller put
    back to sleep or its events cleared: the controller detaches and attaches again, the stick
    never comes back on the proxy; in Linux it comes back erratically and has not trained;
  - a physical replug while the controller is woken and read over SPMI: the stick did not come
    back either (replug2).
- The plug orientation must match: since ~15:20 the stick is flipped (`ss_flip=1` in the kernel,
  `SWAP=1` in the harness; the controller's STATUS bit 4 gives it).

Kernel tree (linux-aurora, uncommitted): port 1 without the flip; `ss_flip`, `ss_susphy_clear`,
`ss_replug_s` (now default 0: the simulated disconnect made the stick vanish in n1/p1); hpm1 in
the devicetree with tipd bound (tipd wakes and polls the controller); `sn201202x_simulate_disconnect()`
in tipd. Harness: `WATCH_SECS`, step `disc` (`NODISC`, `DISC_WATCH`, `DISC_QUIET`, `DISC_ACK`,
`DISC_SSPS`, `DISC_GAID`=1|nossps|sleep).

Open: what iBoot (or macOS) does with port 1's controller that makes a new attach usable, and why
the USB 2.0 reset stopped making the stick retry SuperSpeed at ~13:00.

## The USB 2.0 reset trains again on the proxy (2026-10-28 ~18:40)

macOS AppleHPM (kernelcache mac17j, `com.apple.driver.AppleHPM` 3.4.4, extracted with `ipsw`,
symbols kept): on a new attach the Type10 port class (port 1's) runs `forceUSB23On` (sets
fWaitingForUSB, creates the USB3 port object, `setPinConfiguration`), waits for its USB stack
(`driverStatusInterrupt` -> `turnOnVbus`, or `tUSBTimeout` "Waiting for USB Timedout After 10
seconds"). `turnOnVbus` = `forcePortEvaluation`: read and clear INT_EVENT1 (0x14), add plug/status
events, `processInterruptEvents`. `overrideHPMMode` and `setPinConfiguration` set properties
("Forced Status Reg", "Forced Data Status Reg", pin configuration). No controller command found in
this path so far; the per-connection work is in macOS's USB and PHY drivers.

| Run | Setting | Result |
|---|---|---|
| hotplug4 | reference flipped, `U2RESET`, 120 s watch for a replug (nobody replugged) | USB 2.0 reset: high speed (0x220e03), SS in RxDetect |
| hotplug5 | the same, next run | USB 2.0 reset: SS Polling, U0 (0x21603, speed 5), stick left USB 2.0; still U0 at the end of the 150 s watch |

Since the 180° turn the reference with the flipped setting and `U2RESET` has trained in 2 runs
(gaid2, hotplug5) of about 15. Both followed a stretch without kernel boots (each kernel boot reads
2.5 GiB from the stick at USB 2.0 speed). Open question: does the stick's temperature decide
whether it retries SuperSpeed on a USB 2.0 reset?

Kernel batch flip (`ss_flip=1`, `ss_replug_s=0`, right after hotplug5; tipd bound to hpm1):

| Boot | Result |
|---|---|
| flip1 | `usb 3-1: speed 480`; SS port in RxDetect through the hub's USB 2.0 resets |
| flip2 | `usb 3-1: speed 480`; the SS port reached SS.Inactive (0x2c0) at 4.79 s, hub warm reset at 6.41 s |
| flip3 | `usb 3-1: speed 480` (report saved as `net-wpr1.txt`: the next batch was started too early and both ran at once) |
| flip4 | not booted (chainload clash with that batch) |

Kernel and proxy differ here: at the end of step 16 the kernel's SS port is still in a warm
reset (0x2b0), which completes at about 2.1-2.2 s, just before the hub's USB 2.0 reset; the
proxy reaches step 17 with it finished (about 1 ms per register access), and the xHCI reset
leaves a clean port (base PORTSC1 0x2a0). New in the driver: after step 16 it waits up to
500 ms for that warm reset to finish (logged as "warm reset after step 16 done").

wpr batch (driver waits up to 500 ms after step 16 for the SS port's warm reset): the wait times
out every time ("done 0 after 504000 us"); the warm reset completes about 140 ms after the
step 17 xHCI reset. wpr1 is flip3's report, wpr2 never booted (both batches ran at once).

| Boot | Result |
|---|---|
| wpr3 | `usb 3-1: speed 480`; SS.Inactive (0xa4002c0) at 6.92 s, the stick back on USB 2.0 at 7.06 s |
| wpr4 | `usb 3-1: speed 480`; SS port in RxDetect |

The driver's `phy_calibrate` also runs on a root hub resume (wpr3: second "after xHCI reset"
line at 7.06 s); harmless.

proxy-pr1 (reference with PORTSC1 printed around the step 17 xHCI reset): before HCRST
0x2802a0 (the warm reset already done: WRC, PRC set, PR 0), after HCRST 0x2a0. In the kernel the
same warm reset is still running 500 ms after step 16 (0x2b0) and finishes only after the
controller runs. The SS training failures in the kernel (flip2, wpr3: Polling then SS.Inactive)
come with this difference.

Where the warm reset finishes (proxy-pr3/pr4, harness stage prints with PORTSC1 and time; kernel
trace1, SS PORTSC after each step):
- Proxy: 0x280 (SS.Disabled) through `xhcirst`..`tunx`; 0x2b0 (RxDetect, PR) 7 ms after u3bist
  sets host mode; still 0x2b0 after the firmware (1.38 s), after the PHY reset release (1.48 s)
  and after the first BIST toggle (1.50 s); 0x2802a0 (done) by "after BIST" (2.51 s). In between:
  power-down override 3, USB_EN toggle, and a 1 s poll for PhyStatus rising that times out (the
  proxy misses the pulse).
- Kernel: 0x280 through step 9, 0x2b0 from step 10 to the end (steps 6-9 take microseconds); its
  step 13 sees the PhyStatus pulse ("rise 1") and goes on within milliseconds; the warm reset then
  never completes before step 17.
Driver change: in step 13, after the rise/fall, wait up to 1 s for the warm reset (PR clear)
before OV2 is cleared ("warm reset in step 13 done"); the 500 ms wait after step 16 is removed.

wr131 (step 13 wait, `ss_flip=1`): "warm reset in step 13 done 1 after 544000 us"; SS PORTSC
trace 280 x10, 2b0 x3, 2802a0 x4; after the xHCI reset 0x206e1 / 0x2a0 (clean, as the proxy).
The hub's USB 2.0 resets: `usb 3-1: speed 480`, SS port in RxDetect. The kernel now reaches the
USB 2.0 reset in the proxy's state; what is left is the stick's answer to that reset, which on the
proxy trains in about 2 of 17 runs this afternoon.

## Repeated USB 2.0 resets (2026-10-28 ~19:40)

proxy-u2r10 (reference flipped, `U2RESETS=10`: further USB 2.0 resets 2 s apart until the SS port
is in U0): resets 1-4 leave the stick at high speed (PORTSC0 0x220e03); on the 5th the SS port goes
to U0 (0x21603, speed 5) and the stick leaves USB 2.0 (0x2202a0).

Driver change: step 18 repeated (`ss_u2resets`, default 10, 0 = off): from 3 s after the step 17
xHCI reset, while the SS port has no connection, the driver writes PR to the USB 2.0 PORTSC every
2 s (PP, indicators and wake enables kept, change bits not cleared) and logs each reset.

u2r1 (`ss_flip=1`, `ss_u2resets` 10): extra resets at 5.86, 7.87, 9.89, 11.90 s; each one costs
the hub's high-speed device (disconnect, re-enumeration). After the 4th the stick left USB 2.0
(PORTSC1 0x2202a0 at 11.96 s) but the SS port stayed in RxDetect with the usb4 root hub suspended
(0xa0002a0, WCE/WOE); no device on either bus afterwards.

u2ra1 (as u2r1, `usbcore.autosuspend=-1`): extra resets at 7.87-15.94 s; after the 5th the stick
left USB 2.0 (0x2202a0 at 15.99 s); the SS port stayed 0x2a0 (RxDetect, no wake bits): the host
does not see the stick's SS attempt in Linux. On the proxy the same 5th reset trained (u2r10).

notipd1 (as u2ra1, `initcall_blacklist=sn201202x_driver_init`: tipd not started, port 1's
controller untouched by Linux): the same: after the 5th extra reset (15.68 s) the stick left
USB 2.0, the SS port stayed in RxDetect. tipd is not the cause. The stick goes for SS on about the
5th USB 2.0 reset on the proxy and in Linux; only the host side differs. In Linux "clk: Disabling
unused clocks" runs at 2.93 s, after the SS bring-up (2.6 s).

clk1 (as u2ra1, `clk_ignore_unused`): inconclusive. The extra resets knocked the high-speed stick
off during the read test, so the report went out early and its kernel log stops at 9.94 s (after
the 3rd extra reset). Test change: `init-net` now waits up to 40 s for `4-1` (the stick on port 1's
SS bus) and then up to 15 s for `/dev/sda` before the tests; `boot/initramfs-net.cpio.gz` repacked.

clkb1 (as clk1, new init-net): 10 extra resets (7.87-26.02 s); the stick stayed at high speed
after every one (PORTSC1 0x200e03), never left USB 2.0; "no connection after 10 extra USB 2.0
resets". Says nothing about the clocks (the stick made no SS attempt).

Test without Linux's USB stack on port 1 (as the advisor suggested): driver parameter
`ss_standalone` runs, 1 s after probe, steps 1-16, then the harness's step 17 (xHCI reset, glue,
host mode, R/S, port power on both ports, mask 0x4e00ffe9 | PP), then up to 10 USB 2.0 resets
2 s apart, logging every PORTSC change, stopping at U0. Port 1's `generic-xhci` node disabled in
a copy of the DTB (`fdtput ... /soc/usb@2aa280000 status disabled`). `init-net` also prints
`/sys/kernel/debug/clk/clk_summary` now.

alone1 (`ss_standalone=1`, port 1's xHCI node disabled, tipd not started): the sequence ran
(warm reset done in step 13 after 548 ms, clean 0x2a0 after the xHCI reset, R/S, port power);
10 USB 2.0 resets (8 s apart: the 1 ms sleeps ran long): the stick stayed at high speed after
each (0x220e03), no SS attempt at all. The stick's retry on a USB 2.0 reset cannot be relied on.

AppleHPM commands (4CC constants built with mov/movk in the kext, per function): `USBd` in
`AppleHPMInterface::usbDataConnect(uint, bool)` (also `usbDataDetect`, `usbDataMonitor`), `SSPS`
in `setPowerStateHPM`, `SCfg` in `disablePort`, `SSAM` in `reconfigureSSAM`, `UFPf` in
`forceUSBDeviceMode`, `USBw` in `configureUSBRemoteWakeup`, `VBSi` in `ignoreVbusLoss`, `HChk`,
`VDMs`. `usbDataConnect(.., true)`: `execute4Cc(8 (CMD1), "USBd", data 1, 1 byte)`, then the ADT
platform functions `function-orientation` and `function-usb_dconnect` (not in the J714c ADT; the
driver logs "No orientation function" and goes on); with false only the platform functions. So
on J714c macOS connects a port's USB data with `USBd` 1.

proxy-usbd1 (`disc`, then `USBd` 1 at 4 s, after the reattach): `USBd` -> `!CMD`. proxy-usbd2
(the same inside `LOCK` "417J" / `DBMa` 1 ... `DBMa` 0 / `LOCK` 0000): LOCK 0, DBMa 0, `USBd`
`!CMD`, DBMa 0 0, LOCK 0 0. No reconnection in either.

`AppleHPMARM::set4ccLock(u8)`: if the SMC object at this+0x108 is there, SMC write of key `D1Vn`
(0x4431566e), 1 byte = the argument (`vtable+0x898` of the SMC object: key, size 1, &value);
`get4ccLockStatus` reads the same key. macOS gates the controller's restricted 4CC commands with
the SMC key `D1Vn`; `USBd` is presumably one of them.

SMC keys (read over the proxy with m1n1's SMC client, the session quiesced afterwards as m1n1's
own `smc_shutdown` does): `D1Vn` ui8 (attributes 0xd0) = 0, `D2Vn` ui8 = 0, `D0Vn` absent. Writing
them from this session was blocked by the permission check; Ed wrote `D1Vn`=1, `D2Vn`=1 himself
(`scratchpad/smc_d1vn.py`); both read back 2.

proxy-usbd3 (right after that write, no reboot): the first USB 2.0 reset trained (SS Polling, U0
0x21603 speed 5, stick off USB 2.0). Then `disc`: the controller detached and reattached as
before; `USBd` 1 at 4 s: `!CMD` again; no reconnection.

After the reboot the keys read 0 again; the plain reference failed (proxy-smcref1). With the keys
written to 1 again by `tools/smc_keys.sh 1` (read back 2; allowed by Ed's permission rule for that
one script), the plain reference failed too (proxy-smcref2: PORTSC0 0x220e03, SS 0x2a0). The
usbd3 success was not the keys; `D1Vn`/`D2Vn` at 0 or 2 do not unlock `USBd`.

## Where it stands (2026-10-28 ~22:00)

- Host side: the kernel reaches the USB 2.0 reset in the proxy's exact state (warm reset finished
  in step 13, clean SS port after the step 17 xHCI reset). A fresh plug-in with the SS side up
  trains at once (hotplug3, flipped lane setting).
- The stick goes for SuperSpeed on a USB 2.0 reset only sometimes: on the proxy about 1 run in 5
  this afternoon, sometimes on the first reset, sometimes on the 5th, sometimes never in 10; in
  Linux the host side has not caught any of those attempts (u2r1, u2ra1, notipd1).
- macOS connects a port's USB data with the controller command `USBd` 1 (`usbDataConnect`); this
  controller rejects it (`!CMD`) in normal and debug mode, with the SMC keys `D1Vn`/`D2Vn` at 0 or
  2. What else macOS does first (the other half of `set4ccLock`, or a different unlock) is not
  found yet.
- Driver defaults now: port 1 without the USB 2.0 flip, step 13 waits for the warm reset;
  `ss_flip` (must be 1 while the stick is flipped), `ss_u2resets`, `ss_replug_s`,
  `ss_standalone`, `ss_susphy_clear` all default off. hpm1 stays in the devicetree (tipd binds).
- Test changes: harness `disc` step and options, `WATCH_SECS`, `U2RESETS`, stage prints with
  PORTSC; `init-net` waits up to 40 s for the stick on SS and prints the clock summary;
  `tools/smc_keys.sh` reads or writes `D1Vn`/`D2Vn`.
