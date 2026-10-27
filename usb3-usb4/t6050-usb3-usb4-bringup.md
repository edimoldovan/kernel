# T6050 USB-C PHY — SuperSpeed bring-up notes for the Linux driver

Hardware register reference and the bring-up sequence for SuperSpeed (USB3) on
the Apple T6050 (M5 Max, board J714c) USB-C ports, for the mainline/Asahi-style
Linux `phy-apple-atc` driver and the `dwc3` glue. This is interoperability
documentation: register layouts and the values the open driver needs. All facts
below were checked live on the hardware over the m1n1 stage-1 proxy unless
marked otherwise.

USB2 host already works (committed driver). This file is about adding USB3.

## TL;DR status (read this first)

- The USB3 PHY path comes up with no faults: power + reset release, all
  tunables, common-block wake, AUSPLL lock, lane mode/crossbar, the PCS/BIST
  lane handshake, and the pipe-handler switch to USB3. The `dwc3` controller
  then **runs on the USB3 pipe with CNR clear and no halt**.
- A live SuperSpeed **link is not yet confirmed**. The SS link state machine
  sits in **SS.Disabled**, which is the normal idle state (the working USB2
  proxy port reads the identical value) — it is NOT evidence of a missing pipe
  clock. The pipe clock is unverified, not proven absent.
- The real remaining work is **controller-side**: getting the `dwc3` SS link
  out of SS.Disabled (SS port enable / warm reset → Polling), which normally the
  xHCI driver does, while the CIO power domain is on.
- One hardware conflict to design around: powering `atc0_cio` (needed for the
  PCS/BIST block) **zeroes the dwc3 glue block** at `drd+0xcd00` that holds the
  pipe/ref-clock config. See "The glue / CIO conflict".

A USB3 mass-storage device (flash drive / SSD) in the port is needed to confirm
a link; a phone is a poor test (phones usually present as USB2 peripherals).

## Per-port offset

Uniform: port1 = +0x8000000, port2 = +0xe0000000, for ALL PHY blocks (core and
usb2phy/pipehandler) and the dwc3 (usb-drd). E.g. port0 core 0x2a3000000 →
port1 0x2ab000000. Power-domain registers are the exception (each port has its
own pmgr register, not a simple add). Addresses below are port 0.

## Power domains
Write 0xf to bits[3:0]; poll bits[7:4]==0xf.

    atc0_common    0x280600208   (USB2/USB3 base)
    atc0_auss      <per-port>    (USB3 PLL; port1 is 0x280600248)
    atc0_cio       0x280600280   (PCS/BIST block + USB4; see conflict below)
    atc0_cio_usb   0x280600340
    atc0_cio_auss  0x280600348

USB2/AON domains (usb_aon, usb, phymxwrap, in pmgr2 0x288300000) are already on
from firmware at boot.

## Reset controller — release before touching the core
atc-phy reg[39] = 0x2a3200000 (port1 0x2ab200000). One register:

    bit0 sleep-small (1=released)  bit1 sleep-big (1=released)
    bit2 clamp (0=released)        bit3 APB reset (1=released)
    bit4 main/PHY reset (1=released)

Full release = 0x1b; status acks at +4. Verified: with 0x1b the common block
powers up and the core reads live. NOTE: the driver's generic `ATCPHY_POWER_CTRL`
at core+0x20000 (reg[32]) has the same named bit layout but on T6050 its status
register never acks — the functional reset block is reg[39] above.

## Register windows (core = 0x2a3000000)

    usb2phy            0x2a2a90000
    pipehandler        0x2a2a84000   MUX_CTRL +0xc, LOCK_REQ +0x10, LOCK_ACK +0x14,
                                     OVERRIDE +0x0, OVERRIDE_VALUES +0x4, NONSELECTED +0x20
    CFG0 (common)      core+0xc      (t8122 is +0x8; T6050 is +0xc)
    lane mode          core+0x6c     per-lane fields [4:2] and [7:5]
    crossbar           core+0x78     protocol [4:0] (USB3 = 0xa); reads 0x2a at rest
    lane RX power      core+0x10     sleep/clamp {value,OV} fields (see overrides)
    lane TX power      core+0x120    sleep/clamp {value,OV} fields
    AUS40CMN           core+0xa00
    AUSPLL             core+0x3200   APB cmd core+0x3000, lock core+0x7034 bit3
    RCAL done          core+0x804    bit0 (ALL_CODES_DONE)
    PCS/BIST block     core+0x29000  (reg[35]; in the atc0_cio domain)
    lane0 windows      core+0x9000 / +0xb000 / +0xd000
    lane1 windows      core+0x19000 / +0x1b000 / +0x1d000
    fabric             core+0x244000
    common cfg         0x2a3250000
    axi2af             0x2a0000000
    axi2af_lioa        0x2a0020000
    PHY mgmt core      0x2a3140000   start: set bit0 at 0x2a3140040

dwc3 (usb-drd, port0 0x2a2280000; op base = +0x20):

    CAPLENGTH    +0x0      GCTL        +0xc110   GSTS       +0xc118
    GSNPSID      +0xc120   GUSB2PHYCFG +0xc200   GUSB3PIPECTL +0xc2c0
    GDBGLTSSM    +0xc164   glue        +0xcd28/+0xcd2c/+0xcd40/+0xcd44
    USBSTS       op+0x4    USBCMD      op+0x0    PORTSC[0/1] op+0x400/+0x410

## Override model (how the PHY powers blocks)

Common/lane power uses {value, override-enable} field pairs. Setting the OV bit
forces the value; clearing the OV hands the block to the PHY FSM. CFG0 (core+0xc):
COMMON_BIG bit0 / BIG_OV bit1 / SMALL bit2 / SMALL_OV bit3 / CLAMP bit4 /
CLAMP_OV bit5; RX fields in the higher bits. Lane TX/RX power (core+0x120 /
core+0x10): BIG[1:0]/BIG_OV[3:2]/SMALL[5:4]/SMALL_OV[7:6]/CLAMP[9:8]/
CLAMP_OV[11:10]. "Awake" = BIG=SMALL set, CLAMP clear, OVs set; the driver then
clears the OVs so the FSM runs the block.

## Bring-up sequence (what is known to apply cleanly)

1. Power atc0_common (on at boot) + atc0_auss. For the PCS/BIST path, also the
   atc0_cio domains — but see the conflict below.
2. Release reset reg[39] → 0x1b.
3. Common-block init at CFG0 (core+0xc): set bit2,bit3,bit0,bit1, clear bit4,
   set bit5; AUS40CMN core+0xa00 set bit1; read core+0x804 (RCAL, bit0=1).
4. Apply ALL tunables (next section), including the per-lane groups.
5. Lane mode core+0x6c (USB3 per-lane values) and crossbar core+0x78 protocol
   [4:0]=0xa; lane-swap for a flipped cable at the power block.
6. AUSPLL: APB command at core+0x3000, wait lock core+0x7034 bit3. Its output
   drivers come up with it (core+0x3200 ~0x81d5c when locked).
7. Lane power-up: core+0x10 (RX) and core+0x120 (TX) to "awake" (above), then
   clear the OV bits so the FSM drives the lanes.
8. PCS/BIST lane handshake at core+0x29000 (needs atc0_cio): CLOCK_EN (+0x0 bit0),
   set LN0_PIPE_RESET_N_OV / PWR_DOWN_OV in +0x88, RESET_N_OV / PWR_DOWN_OV in
   +0x8c, then toggle USB_EN (+0x0 bit2) and poll STATUS2 (+0x80 bit7) — all
   complete on hardware.
9. Pipe-handler to USB3 under the lock: disable link detect (OVERRIDE_VALUES
   clear RXDETECT0/1, OVERRIDE set RXVALID+RXDETECT), LOCK_REQ, MUX_CTRL
   clock field [6:4]=1 / data [1:0]=0 (value 0x10, the T8142 field layout),
   LOCK_ACK, unlock.
10. Controller: set host mode via GCTL prtcap (bits[13:12]=1) WITHOUT a GCTL
    core-soft-reset (bit11) once atc0_cio is on — that reset gates the glue (see
    below). Do NOT issue an xHCI HCRST after the USB3 switch for the same reason;
    HCRST belongs at init on the dummy pipe. The controller runs (USBCMD R/S),
    CNR clear.

## Tunables
AUSPLL (core+0x3200): +0x024 m 0x00000c00 v 0x00000800; +0x030 m 0x1f v 0x0f;
+0x040 m 0x07d8007f v 0x04000029; +0x0b0 m 0x0b800000 v 0x01800000; +0x0e8
m 0x00060001 v 0x00040001; +0x138 m 0x0f800000 v 0x07800000. AUS40CMN (core+0xa00):
+0x004 m 0x7c v 0x54. common cfg (0x2a3250000): +0x008 m 1 v 1.

Large groups are platform tunable tables, applied as (offset, mask, value) RMW
at each group's window base. ALL are required for USB3:
    FABRIC            core+0x244000  (65)
    AXI2AF            0x2a0000000    (75)
    AXI2AF_LIOA       0x2a0020000    (5)
    LN0 RX_EQ_DFLT    core+0xb000    (3)   <- per-lane, required
    LN0 RX_CFG_TX_OF_RXCLK core+0xd000 (4) <- per-lane TX clocking, required
    LN1 RX_EQ_DFLT    core+0x1b000   (3)
    LN1 RX_CFG_TX_OF_RXCLK core+0x1d000 (4)
The per-lane groups were the ones the first attempts omitted.

## The glue / CIO conflict (the key open problem)

The dwc3 glue block at drd+0xcd00 (cd28=0x886, cd2c=0x886, cd40=0x3c20060c,
cd44=0x2000b from firmware) holds the pipe/ref-clock config. Findings:

- It survives as long as the dwc3 is not core-soft-reset AND atc0_cio stays off.
- A dwc3 GCTL core-soft-reset (or xHCI HCRST) zeroes it. With atc0_cio off the
  controller recovers (USB2 works); it can also be restored by writing the four
  values back (writes stick with atc0_cio off).
- Powering **atc0_cio** — the exact domain the PCS/BIST block needs — zeroes the
  glue again and, once on, the glue ignores writes.
- In the no-reset path (host mode set without GCTL bit11), the glue stays alive
  (0x886) with atc0_cio on, and the controller runs on the USB3 pipe.

Working reference (proxy port, USB2): GUSB3PIPECTL 0x01021102, glue 0x886 /
0x3c20060c, GDBGLTSSM 0x9cc20026 (state SS.Disabled). Test port in the running
USB3 config: GUSB3PIPECTL 0x01001102, glue zeroed by atc0_cio, same GDBGLTSSM.

## What is unresolved (for the next pass)

Get the dwc3 SS link out of **SS.Disabled** into training (RxDetect → Polling →
U0) with atc0_cio on and the glue configured. Candidates:
1. The SS port is never actually enabled here (no full xHCI init: DCBAA, command/
   event rings, port enable). This is normally the OS xHCI/dwc3 driver's job;
   in the real driver the HCRST + GUSB3PIPECTL programming happen at probe on
   the dummy pipe, then the PHY switches the mux to USB3 on connect. Reproduce
   that order rather than resetting after the USB3 switch.
2. Whether the glue zeroing on atc0_cio-on is a reset that can be released after
   the domain is up (the pipe-handler NONSELECTED/0x9332 path after atc0_cio was
   not tried; the AON_GEN reset cycle was, with no effect).
3. Confirm with a USB3 storage device in the port, watching the LTSSM state
   field and PORTSC.

## Verification rules (avoid the traps this cost)

- "Controller alive" = GSNPSID (core+0xc120) and CAPLENGTH (core+0x0) non-zero.
  Do NOT trust a CNR=0 (USBSTS bit11) poll alone — a dead/zero-reading register
  also reads bit11 clear, which looks like "ready".
- SS link state = GDBGLTSSM (drd+0xc164) bits [21:18]. 0 = SS.Disabled (idle,
  constant by design — NOT "no clock"). Watch the STATE FIELD change, not the
  whole word.

## Tooling

- `tools/t6050_phy_power_test.py` drives all of the above over the m1n1 proxy on
  port 1 (left side). Steps chain on the command line (e.g. `cio tunables tunx
  wake pllstart2 ...`); it arms the 90 s watchdog for the whole run and refuses
  the proxy's own port. `FORCE_PORT1=1` overrides the proxy-port guard when a
  device in the test port makes port 1 look device-mode.
- `usb3-usb4/mac_ctl.py` reboots + reconnects the board unattended and arms the
  watchdog, so a stalled access self-recovers.
- ALWAYS arm the watchdog before any first read of an unpowered window; reading
  an unpowered DRD (e.g. a port whose domains are off) hard-hangs the SoC.
