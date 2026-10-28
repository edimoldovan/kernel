# T6050 SuperSpeed/USB4 PHY: reverse-engineering results

From AppleT6050TypeCPhy in kernelcache.mac17j.bin + the live ADT. This is the
ground truth for T6050, and it supersedes the t8122-by-analogy guesses in the
earlier m1n1 draft and in the committed device tree.

## The register model (how the kext programs the PHY)

`applyTunables(uint idx, OSData *tunable)` is the leaf. The object holds an
array of 32-byte window descriptors at `this+0x208` (base at +0x8, size at
+0x18), populated in `start()` from the static table `_sRegisters`. `idx`
selects a window; each tunable triple `(offset, mask, value)` is applied as a
read-modify-write at `window_base + offset`.

`_sRegisters` decodes exactly to the ADT `atc-phy` reg list, per port:
**window idx == ADT reg index.** So a tunable applied with idx N lands in
ADT reg[N]. The 44 windows for port 0 (masking the 0x40_00000000 tag):

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

## The complete tunable -> register map

Fully extracted with every (register, mask, value) triple in
`t6050-phy-tunable-map.txt`. Summary of targets:

| tunable | idx | absolute base | note |
|---|---|---|---|
| USB2PHY_DFLT/HOST/DEV | 0 | 0x2a2a90000 | USB2 (already working) |
| ATC0AXI2AF (+WR_DIS,+LOCK) | 41 | 0x2a0000000 | 75 triples |
| ATC0AXI2AF_LIOA | 42 | 0x2a0020000 | |
| ATC_FABRIC | 40 | 0x2a3244000 | 65 triples |
| ATC_COMMON_CFG | 43 | 0x2a3250000 | 1 enable bit |
| AUS40CMN_SHM | 5 | 0x2a3000a00 | |
| AUSPLL_CORE | 8 | 0x2a3003200 | the USB3 PLL |
| CIO4PLL_CORE | 10 | 0x2a3003a00 | the USB4/TBT PLL |
| LN0/1_RX_TOP_CIO_DFLT | 16/25 | 0x2a3009000 / 0x2a3019000 | |
| LN0/1_RX_EQ_DFLT | 18/27 | 0x2a300b000 / 0x2a301b000 | |
| LN0/1_RX_CFG_TX_OF_RXCLK | 20/29 | 0x2a300d000 / 0x2a301d000 | |
| UC_REGS_CIO_DFLT | 3 | 0x2a3000400 | empty in J714c ADT |

### Corrections this forces on the earlier drafts
- **PLL offsets were wrong by 0x1000.** AUSPLL is core+0x3200 (not 0x2200),
  CIO4PLL is core+0x3a00 (not 0x2a00). The t8122 analogy does not hold.
- **Lane layout differs from t8122.** lane0 at core+0x9000/0xb000/0xd000,
  lane1 at core+0x19000/0x1b000/0x1d000 (not 0x10000/0x11000/0x12000).
- **Four tunables target blocks the linux device tree does not map:**
  ATC0AXI2AF -> 0x2a0000000, LIOA -> 0x2a0020000, ATC_FABRIC -> 0x2a3244000,
  ATC_COMMON_CFG -> 0x2a3250000. None are inside the dtsi "core"
  (0x2a3000000, size 0x4c000) or "axi2af" (0x2a2800000) windows. The dtsi
  reg windows and the atc.c region mapping need rework for T6050; a tunable
  table alone is not enough. Treat the earlier m1n1 draft's offsets as
  superseded by the map above.

## Which tunables each mode applies
- Every mode: the globals in `aciophy_apply_tunables` - ATC0AXI2AF (+WR_DIS,
  +LOCK_LOCK), ATC_FABRIC, ATC_COMMON_CFG, ATC0AXI2AF_LIOA, and per-lane
  RX_CFG_TX_OF_RXCLK + RX_EQ_DFLT.
- USB3 adds (`aciophy_apply_usb_tunables`): AUS40CMN_SHM, AUSPLL_CORE.
- USB4/Thunderbolt adds (`aciophy_apply_cio_tunables` + `_cio80_tunables`):
  AUSPLL_CORE, AUS40CMN_SHM, CIO4PLL_CORE, UC_REGS_CIO_DFLT,
  LN0/1_RX_TOP_CIO_DFLT, LN0/1_RX_EQ_CIO_DFLT.
- USB2 (`eusb2phy_init`): USB2PHY_DFLT then DEV or HOST, at idx 0.

## Init sequence - stage functions (ordering not yet fully traced)
The bring-up is spread across these methods (register work done through inline
read/modify/write/poll helpers, orchestrated virtually):
- `aciophy_cmn_init`, `aciophy_phy_init` (+partA/B/C), `aciophy_phy_powerup_rst`,
  `aciophy_phy_deassert_aciophy_reset`, `aciophy_phy_efuse_load`
- `aciophy_apply_tunables` / `_usb` / `_cio` / `_cio80` (the maps above)
- `aciophy_xbar_config`, `adjust_lane_mode`, `aciophy_rx_powerup`,
  `aciophy_tx_powerup`, `aciophy_pwr_up_rxa`
- `overrideUSBControllerSignals` (dwc3 <-> PHY pipe handshake)
- PLL lock is polled on ACIOPHY_DP_PCLK_STAT (core+0x7044), bit 3 (AUSPLL_LOCK)
- USB4 only: `runFirmware` + `aciophy_assert_fw_reset` /
  `aciophy_deassert_fw_reset` + `aciophy_uc_idle` (the CIO80 microcontroller)

What remains: the exact ordered register sequence within these stages (resets,
PLL enable steps, lock waits, lane power-up order). That is the large piece -
each stage's register writes must be read out of its disassembly. The tunable
values above are the data those stages overlay.

## Init sequence - mechanism, primitives, and what is decoded

### Primitives (resolved via the kext GOT)
- register read  = `_ml_io_read32(addr)`   (helper thunk at 0xf4063c)
- register write = `_ml_io_write32(addr,v)` (helper thunk at 0xf4064c)
- `_ml_get_interrupts_enabled` (0xf4062c, used only in debug asserts), `_panic`

So every stage is read-modify-write register traffic on absolute addresses.

### Address model
A stage loads a window base cached in an object field and adds an offset:
`addr = *(this + field) + off`. The field maps to a window index by
`idx = (field - 0x210) / 0x20` (the window array is at this+0x208, 32-byte
descriptors, base at +0x8), and `idx` is the ADT reg index (see the table
above). Example: field 0x250 -> idx 2 -> core (0x2a3000000).

`decode-stage.py` (saved here) walks a function and prints its register writes
as `idxN core+off op val`. It catches straight-line writes; it does not yet
resolve reads/polls, conditional branches, or the between-stage virtual
dispatch order - those are the remaining work.

### Decoded so far
- `aciophy_cmn_init`: core+0xc |= 0x4, |= 0x8, |= 0x1, |= 0x2 (common block
  enable/reset bits 0-3), then the AUS40CMN_SHM tunable.
- `aciophy_rx_powerup`: writes core+0x10 (lane RX power).
- `aciophy_tx_powerup`: writes core+0x120 (lane TX power).
- `aciophy_pwr_up_rxa`: core+0x10.
- `aciophy_phy_init_partC`: calls `runFirmware` (the CIO80 microcontroller load)
  at +0xc2c - USB4/Thunderbolt only.
- PLL lock is read on core+0x7044 (ACIOPHY_DP_PCLK_STAT), bit 3 (AUSPLL_LOCK).

### Stage order (partial; dispatch is virtual)
`aciophy_phy_init` drives `_partA/_partB/_partC`; partB reaches the DPTX main
init, partC runs the firmware. The common/PLL/lane stages
(`cmn_init`, `phy_powerup_rst`, `phy_deassert_aciophy_reset`, `phy_efuse_load`,
`xbar_config`, `rx_powerup`, `tx_powerup`) and the tunable appliers are invoked
through the vtable; recovering their exact order needs the dispatch trace.

### What remains for a complete sequence
A systematic pass with `decode-stage.py` extended to emit reads, poll loops
(read-until-bit), and the conditional structure, run over every stage, plus the
virtual dispatch order from `aciophy_phy_init`. The register model, the
primitives, the window map, and all tunable values are now in hand, so this is
mechanical extraction rather than open discovery.
