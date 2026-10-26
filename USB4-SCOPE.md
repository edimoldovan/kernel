# USB4 / SuperSpeed on T6050 (M5 Max, J714c): scope of the bring-up

Goal: get the USB-C ports past USB 2.0 - SuperSpeed (USB3) and USB4/Thunderbolt.
This is the part the USB2-only patch deliberately skips. Scoped 2026-10-26 from
the live ADT (`j714c/dumps/j714c.adt`), m1n1 `src/kboot_atc.c`, and the kernel
PHY driver `drivers/phy/apple/atc.c`. No boot was done; no SuperSpeed link was
brought up. The verdict below is what the code and the firmware tables show.

## Verdict

SuperSpeed is NOT a new-silicon unknown - it is a new PHY *generation* of a
known family, and the work is bounded and identifiable, not open-ended. The
firmware ships every tuning table; the kernel driver has a SuperSpeed engine;
two pieces of plumbing are missing and must be written and verified:

1. **m1n1 does not propagate the T6050 SuperSpeed tunables into the Linux DT.**
2. **The kernel PHY driver has no T6050 PHY generation**, and a few T6050
   tunables have no analogue in the generation it is closest to (t8122).

The encouraging part: the T6050 PLL registers sit at the **same core-block
offsets** as the known AUSPLL/CIO PLL, so the driver's existing SuperSpeed
sequence is very likely reusable. What changed is the tuning *values* (firmware
provides them) and a short list of new/renamed tunables.

## Gap 1 - the loader (m1n1 `kboot_atc.c`)

m1n1 picks its tunable table from the ADT's own `compatible`:

```
atc-phy,t8130                      -> atc_tunables_t8130[]
atc-phy,t8142/t8122/t8132          -> atc_tunables_t8122[]
everything else                    -> atc_tunables[]      (oldest, t8103-era)
```

The T6050 PHY is `atc-phy,t6050` / `atc-phy,t6040`, which matches none of these,
so it falls to the **t8103 table**. That table looks for `tunable_CIO3PLL_CORE`,
`tunable_USB_LN0_AUSPMA_*`, `tunable_AUS_CMN_*` - names the T6050 ADT does not
have. Result: **no SuperSpeed tunable is copied into the DT**, so the kernel PHY
has nothing to apply and the controller stays USB2 at best (here, it never binds
at all with the plain t8142 description).

Fix: add a `atc_tunables_t6050[]` table and a compat branch for
`atc-phy,t6050`/`t6040`. The T6050 ADT SuperSpeed tunable set (atc-phy0):

| ADT tunable | triples | maps like (t8122) | confidence |
|---|---|---|---|
| tunable_ATC0AXI2AF | 75 | axi2af @ 0x0 | high (same name) |
| tunable_ATC0AXI2AF_LIOA | 5 | axi2af @ ? | NEW - offset unknown |
| tunable_ATC_FABRIC | 65 | common-b @ 0x44000 | high |
| tunable_ATC_COMMON_CFG | 1 | common-b @ ? | NEW - offset unknown |
| tunable_AUSPLL_CORE | 6 | common-b @ 0x2200 | high (same name) |
| tunable_AUS40CMN_SHM | 1 | common-b @ 0xa00 (was AUSCMN_SHM) | medium (renamed) |
| tunable_CIO4PLL_CORE | 4 | common-b @ 0x2a00 (was CIO3PLL_CORE) | medium (renamed) |
| tunable_LN0/1_RX_TOP_CIO_DFLT | 1 | lane-cio @ 0x9000 | high (in t8122 table) |
| tunable_LN0/1_RX_EQ_DFLT | 3 | lane @ 0xa000 (RX_EQ region) | medium |
| tunable_LN0/1_RX_CFG_TX_OF_RXCLK | 4 | lane @ ? | NEW - offset unknown |
| tunable_LN0/1_RX_EQ_CIO_DFLT | 0 (empty) | - | absent in this ADT |
| tunable_UC_REGS_CIO_DFLT | 0 (empty) | - | absent in this ADT |

Absent vs t8122 (so either folded in or not needed on T6050): CIO3PLL_TOP,
AUSPLL_TOP, AUSCMN_DIG, ACIOPHY_TOP/PLL_TOP/LANE_USBC0, AUX_TOP, CIO_SHIM,
the RX_TOP_USB / RX_SHM / TX_TOP / TX_SHM lane tunables. The T6050 lane set is
smaller and more generic (`RX_EQ_DFLT`, `RX_CFG_TX_OF_RXCLK` carry no USB/CIO
suffix), suggesting one lane profile serves both USB3 and USB4.

Also: m1n1 `dt_append_fuses()` copies per-port ATC calibration fuses ("USB3 /
Thunderbolt will not work" without them). The T6050 fuse layout
(`struct atc_fuse_hw`) must be added too; none exists for it today.

## Gap 2 - the kernel PHY driver (`drivers/phy/apple/atc.c`)

The driver has a full SuperSpeed engine (AUSPLL frequency descriptors at core
0x2080, APB command override at 0x2000, CLKOUT/BGR at 0x2200-0x2214, lock poll
on `ACIOPHY_DP_PCLK_STAT` 0x7044). It has no T6050 generation and no `CIO4PLL`
awareness. The register OFFSETS the firmware tunables target line up with this
map (AUSPLL at 0x2200, the CIO PLL at 0x2a00), so the existing sequence is the
right starting point.

Needed:
- A `atcphy_hw_t6050` generation and a verified SuperSpeed path. Reuse the
  t8122 sequence first; the open question is whether the CIO4PLL locks with the
  t8122 enable steps or needs different ones.
- Handling for the new tunables once their register blocks are known
  (ATC_COMMON_CFG, ATC0AXI2AF_LIOA, RX_CFG_TX_OF_RXCLK).
- The USB2-only patch's `atcphy_hw_t6050` (optional_tunables=true) is the
  USB2 floor; the SuperSpeed version drops `optional_tunables` once the
  tunables are present.

## Key register programming (from the ADT, atc-phy0)

AUSPLL_CORE (sub-block relative; add 0x2200 for the core-block address):
```
off 0x024 mask 0x00000c00 val 0x00000800
off 0x030 mask 0x0000001f val 0x0000000f
off 0x040 mask 0x07d8007f val 0x04000029
off 0x0b0 mask 0x0b800000 val 0x01800000
off 0x0e8 mask 0x00060001 val 0x00040001
off 0x138 mask 0x0f800000 val 0x07800000
```
CIO4PLL_CORE (add 0x2a00):
```
off 0x030 mask 0x0000001f val 0x0000000f
off 0x04c mask 0x0000fe7f val 0x00004e1e
off 0x0b0 mask 0x00700000 val 0x00300000
off 0x0e8 mask 0x00060000 val 0x00020000
```
The 0x30/0xb0/0xe8 offsets recur in both PLLs - the CIO4PLL is register-layout
compatible with the AUSPLL, consistent with "same map, new values."

## Work plan (ordered)

1. m1n1: add `atc_tunables_t6050[]` (table above) + a `atc-phy,t6050`/`t6040`
   compat branch; add the T6050 `atc_fuse_hw`. Confirm the DT then carries
   `apple,tunable-common-b`, `-lane0/1-usb`, `-lane0/1-cio`, `-axi2af`.
2. Resolve the three unknown-offset tunables (ATC_COMMON_CFG, ATC0AXI2AF_LIOA,
   RX_CFG_TX_OF_RXCLK) - from the macOS AppleT6050TypeCPhy driver or by probing
   the core block (needs the core powered first; see the lockup note below).
3. atc.c: add `atcphy_hw_t6050`, SuperSpeed path reusing the t8122 sequence.
4. Build + boot; plug a USB3 device; watch for AUSPLL lock and SS link train.
   Then a USB4/Thunderbolt device.

## Lockup note (why a live PLL survey was not completed)

Reading the ATC *core* block (0x383000000 on port 2) over the proxy hung the
machine: the core is powered down while the port is in USB2/DUMMY, and the
unpowered-MMIO fault was not caught by the proxy exception guard (same failure
mode as the earlier ACC probe). Any live survey of the CIO4PLL/AUSPLL core
registers must first run the core power-on (`ATCPHY_MISC_RESET_N` +
`ATCPHY_POWER_SLEEP`) that `atcphy_power_on()` does - or, more safely, be done
from inside the kernel driver. The ADT tunables above already give the register
targets without touching the core live.
