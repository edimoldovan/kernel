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
