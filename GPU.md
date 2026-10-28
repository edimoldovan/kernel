# GPU on the M5 Max (J714c / T6050)

Done: Hyprland on the J714c renders through the GPU (`/dev/dri/renderD128`,
Mesa's asahi driver), not llvmpipe.

## Facts (2026-10-28)

- Generation: G17. macOS 27.0 loads `com.apple.AGXG17X` and
  `AGXFirmwareKextG17XRTBuddy` for this machine (`j714c/firmware/kernelcache.mac17j.bin`,
  xnu-13432.1.9, RELEASE_ARM64_T6050). The A18 Pro (T8140, the Neo) is G17 too.
- ADT `sgx`: `compatible = [gpu,t6050]`, 13 performance states up to 1620 MHz.
  Two GPU coprocessors, `gfx-asc` and `gfx1-asc`, firmware `GFX` and `GFX1`,
  `pre-loaded = 1` (iBoot loads the firmware). System firmware `mBoot-20457.41.3`.
- linux-aurora `drivers/gpu/drm/asahi`: a G17 path (`g17/`, about 11,300 lines,
  73 commits since 2026-10-03) for T8140 only (`hw/t8140.rs`, OF id
  `apple,agx-t8140`). It already drives two coprocessors.
  The firmware interface version the G17 path writes:
  `[0x04c0, 0x0396, 0xa322, 0x0c8a]` (`g17/fw/initdata.rs`); the firmware rejects any other.
- m1n1 (omacom fork) `src/kboot_gpu.c`: `dt_set_gpu_t8140()` fills the GPU node
  from the ADT; nothing for T6050.
- Our device tree (`t6050*.dtsi`) has no GPU node.
- Mesa on the Mac: mesa-aurora 26.3.0 devel (2026-10-28); its strings name
  G17P, G17G, G17S and G17C.
- The interface version bytes are not in the kernelcache.

## Proxy probe (2026-10-28, `tools/gpu_probe.sh`, `log/gpu-probe1.txt`)

- sgx: `0x2300000000` (0x3fdc000) and `0x2300d00000` (0x177000).
  gfx-asc: `0x2302600000` (0x88000), `0x2302050000` (0x8).
  gfx1-asc: `0x2302e00000` (0x88000), `0x2302850000` (0x60000).
- Preloaded firmware, saved to `/home/ed/dev/omarchy/firmware/gpu/` (not in git):
  - GFX, UUID `61B4CD74-FF02-3C39-AE39-1BA25A386AA1`: __TEXT 0x50000 at
    `0x10001148000`, __DATA 0xc0000, __DATA_SHARED_RO 0x8000.
  - GFX1, UUID `D93B638C-649D-3BF3-AFAA-A4D2D267B331`: __TEXT 0x54000 at
    `0x10001198000`, __DATA 0xb4000, __DATA_SHARED_RO 0x8000.
  - Both: `RTKit_armv8_lightning_Oz_flto_pac-3514.41.1.release`,
    "FW Build variant: g17c", "FW Build version: a0".
- The G17 interface version `[0x04c0, 0x0396, 0xa322, 0x0c8a]` is in none of the
  segments, neither as bytes nor as MOVZ/MOVK immediates: the g17c firmware's
  interface is not the one `g17/` is written for (G17P, the A18 Pro).
- ID registers (sgx power domain on): `ID_VERSION 0x0b041100` (family 0x0b,
  variant 0x04, revision 0x1100), `ID_COUNTS_1 0x0011040a` (1 die, 4 clusters,
  10 cores each: 40 cores), `ID_COUNTS_2 0x00040404`, `ID_UNK18 0x01320311`,
  `ID_CLUSTERS 0x400c1809`, `CORE_MASKS_G14X 0xffffffff`, `G17_CORE_POWER 0`.
  `hw/t8140.rs` has family 0xa, variant 0, 1 die.

## g17c firmware interface (2026-10-28, `tools/fwre/`, GFX __TEXT at `0xfffffc0000000000`)

- Init entry at __TEXT `0x21854`: waits on endpoint 0x20 for the init data
  pointer, checks its tag (bits 55-48 masked with 0xbf must be 0x81), then reads
  the root.
- Root `+0x00`: interface version `0x0c8e4339872804c0`, as u16
  `[0x04c0, 0x8728, 0x4339, 0x0c8e]` (`0x218a4`; GFX1 the same at `0x26ce4`).
  G17P: `[0x04c0, 0x0396, 0xa322, 0x0c8a]`. Mismatch: "Host and FW Interface is
  mismatched, please ensure the versions are aligned."
- The root is 0xc8 bytes (copied to `0xfffffc0000108890`); G17P's `Root` is 0xb8.
- Same offsets as G17P: `+0x18` main config, `+0x20` region C, `+0x2c` must be
  nonzero ("Host-mapped FW allocations are disabled, but FW only supports
  enabled"), `+0xa8` status A, `+0xb0` status B.
- Init reads, `0x2191c`-`0x220fc` (`tools/fwre/reads.py`, list in
  `log/gpu-g17c-init-reads.txt`, checked with `tools/fwre/layout.py` against
  `g17/fw/initdata.rs`):
  - Main config: `+0x00` (the HwData address), `+0x2e0` and `+0x2f0`, the same
    offsets as G17P's `hw_data_va`, `pb_descriptors_va`, `page_pool_descriptors_va`.
  - HwData, 113 reads. `0xfb0`-`0x1cf0` (perf_a, perf_b) fit G17P's layout. The
    frequency arrays are read up to index 13 (`0xffc`); G17P fills 11 states,
    the M5 Max ADT has 13.
  - Differences: `0x265c`-`0x2678` are read as eight u32 values into one block
    of firmware state, where G17P has its completion-ring descriptors
    (`0x2614` + 4 x 0x20). `0x26ac` is a u32 and `0x26b0` a u64, where G17P has
    `qos_va` (u64) at `0x26ac`. From about `0x2600` on, the g17c HwData differs
    from G17P's; the reads go on to `0x2825` (G17P: `unk_26ec`, unknown).
- Whole-firmware reads through the main config global `0xfffffc0000108888`
  (124 sites; `log/gpu-g17c-reads.txt`):
  - The HwData tail is G17P's layout 0x128 bytes later. Four completion-ring
    descriptors at `0x273c` (G17P `0x2614`), each read as G17P's
    `CompletionRingDescriptor`: `+0x00` u64, `+0x10` and `+0x18` u32 loads,
    `+0x1c` stored by the firmware. QoS address at `0x27d4` (G17P `0x26ac`).
    Minus 0x128, the reads land on G17P's filled fields `unk_2544`-`unk_2550`,
    `unk_2570`, `unk_25f4`, `unk_2600`, `unk_2608`, `unk_2610`.
  - The extra 0x128 bytes are between G17P `0x1cf4` (inside `perf_b`) and
    `0x2534` (inside `unk_23dc`); no tracked read falls there. g17c HwData is
    at least 0x3edc bytes (G17P 0x3db4).
- Next: pin the 0x128 insertion (indexed reads of `perf_b`), then region A,
  region C, the status blocks and the channels.

## Steps

1. Firmware interface (in progress, above). Version, root and the init reads
   of main config and HwData done, HwData tail placed (+0x128); next the
   insertion point, then regions A and C, the status blocks and the channels,
   each diffed against `g17/fw/` (G17P).
2. GPU identity (done, above).
3. m1n1: `dt_set_gpu_t6050()` from `dt_set_gpu_t8140()`.
4. Device tree: GPU node for T6050 (`asc` and `sgx` regs, `gfx`/`gfx1` mailboxes,
   `ps_gfx`, `ttbs`/`pagetables`/`handoff` regions, OPP table from the ADT).
5. Kernel: `hw/t6050.rs` (G17 `Config`: chip id, identity with variant C,
   address-space sizes, secondary root offset, crash buffers) and the
   `apple,agx-t6050` OF entry.
6. Mesa: the G17C (T6050) device entry, mesa-aurora rebuilt on the Mac.
7. Boot: driver probe log, `kmscube`, then Hyprland on the GPU.

Step 1 works on the dumped firmware and needs no Mac. Steps 3-7 need boots.
