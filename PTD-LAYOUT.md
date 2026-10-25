# PMP PTD request ring and doorbell layout (J714c / T6050)

Worked out offline from the live ADT (`j714c/dumps/j714c.adt`) and the PMP
firmware dump. Addresses are host-visible physical (arm-io child + 0x200000000).

## Regions

| Region | Source | Address | Size |
|---|---|---|---|
| PTD aperture / doorbell | pmgr reg[7]; mcc reg[2] = `pmp_ptd_db_reg_idx` | 0x284240000 | 0x40000 / 0x4000 |
| PTD data (update) window | pmp0 reg[3] (`ptd-update-reg-index`=3); mcc reg[3] = `pmp_ptd_update_reg_idx` | 0x284250000 | 0x4000 |

The PTD channel words live in the update window at 0x284250000. The proxy
script's `pmp_base + off*8 + 0x10000` resolves to the same place, since
pmgr-reg7 + 0x10000 = 0x284250000.

## Channels (nub `ptd-range`): addr = 0x284250000 + off*8

| id | name | off | size | address |
|---|---|---|---|---|
| 1 | NULL | 0x000 | 1 | 0x284250000 |
| 2 | PMP-STATUS | 0x001 | 1 | 0x284250008 |
| 3 | DVFS-STATE | 0x008 | 4 | 0x284250040 |
| 4 | PMPTOOL | 0x00c | 4 | 0x284250060 |
| 5 | PMS-PMGR-PKT | 0x010 | 8 | 0x284250080 |
| 6 | PMS-DPE-PKT | 0x018 | 0x20 | 0x2842500c0 |
| 7 | PMS-DEVC-PKT | 0x038 | 0x48 | 0x2842501c0 |
| 8 | PMS-PWRS-PKT | 0x080 | 0x10 | 0x284250400 |
| 9 | SOC-DEV-PKT | 0x090 | 0x150 | 0x284250480 |
| 10 | SOC-DEV-PS-REQ | 0x1e0 | 8 | 0x284250f00 |
| 11 | SOC-DEV-PS-ACK | 0x1e8 | 8 | 0x284250f40 |
| 12 | SOC-DEV-DVFS | 0x1f0 | 0x30 | 0x284250f80 |
| 13 | SOC-DEV-BWR | 0x220 | 0x1a | 0x284251100 |
| 15 | MC-DRV-TO-CTRL | 0x23c | 0x0a | 0x2842511e0 |
| 18 | MC-CTRL-TO-DRV | 0x261 | 0x09 | 0x284251308 |

(Full table, including the SMC/GFX channels, is in the ADT.)

## Request/ack pair for device power

- Host writes the request word at SOC-DEV-PS-REQ 0x284250f00 (8 bytes).
- PMP writes its answer at SOC-DEV-PS-ACK 0x284250f40 (8 bytes).
- The firmware also drains a packet ring (SOC-DEV-PKT 0x284250480) via its
  PTD interrupt handler; this is the path that sets the per-device "enabled"
  flag the init thread waits on.

## Doorbell and register block (from macOS ApplePMGR/ApplePTD)

Confirmed by disassembling the macOS driver (kernelcache mac17j, symbols
resolved). Every PTD access is `ApplePMGR::writeReg64/readReg64(RegMap 8, off,
val)`; RegMap 8 is the aperture based at 0x284240000 (pmgr reg[7] / mcc reg[2],
0x40000). All offsets below are into that aperture.

| Function | op | offset in aperture | absolute |
|---|---|---|---|
| `ApplePTD::_writePTD` / `_readPTD` | descriptor word `i` | 0x10000 + i*8 | 0x284250000 + i*8 |
| `ApplePTD::_irqStatus` | pending status | 0x18000 + (v>>5)*4 | 0x284258000 |
| `ApplePTD::_enableIrq` | enable (set bit v) | 0x18200 + (v>>5)*4 | 0x284258200 |
| `ApplePTD::_disableIrq` | disable (clr bit v) | 0x18300 + (v>>5)*4 | 0x284258300 |
| `ApplePTD::_setIrq` | set / raise vector v | 0x18400 + ... | 0x284258400 |

The descriptor data at +0x10000 is the channel region this doc lists above:
0x10000 + 0x1e0*8 = 0x10f00, i.e. SOC-DEV-PS-REQ at 0x284250f00 - the same
address, so the RegMap-8 base is 0x284240000 and the channel addressing is
confirmed.

The interrupt block sits at aperture + 0x18000 (0x284258000), not in the first
0x4000 window and not at the 0x284240200 I guessed earlier from the aon-ptd
analogy. Layout is a standard per-vector controller: status +0x18000, enable
+0x18200, disable +0x18300, raise +0x18400, one 32-bit word per 32 vectors
(bit = vector).

### Doorbell for a device-power request

`ApplePMGR::_pmpWriteDashBoardSetDeviceState(dev, state, ...)` is the host call
that enables a device. It does `_readPTD` then `_writePTD` on the device's PTD
entry (the descriptor write to 0x284250000 + i*8), then, guarded by a flag,
an authenticated call through the ApplePMGR object (ivar +0xc88) - the notify
step. The raise register at +0x18400 (0x284258400) is the controller's own
set/cause op.

So the host side is: write the device's descriptor word in the data region,
then raise its vector. The one remaining unknown is the exact vector number for
the SOC-DEV request channel (the firmware waits on its device index 0); it is
derived at runtime from the PTD entry (`_readPTD` returns bits 8-15 as the
vector in `enablePTDEntryInterrupt`), not a fixed constant.

## (superseded) earlier doorbell note

The +0x200 guess has been replaced by the confirmed map above.

## Why runs 1-12 stalled

Init blocks in FUN_0104aa50 waiting for device index 0's enabled flag (+0x58
bit 0), set only when a device-enable request arrives through the ring above.
No run drove this channel during the handshake; PHASE B wrote SOC-DEV-PS-REQ
only after the 60 s timeout, for the CPU clusters, with no doorbell, and read
back 0.
