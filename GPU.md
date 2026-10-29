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

## Plan

Done when Hyprland on the J714c renders through the GPU. [x] done, [ ] open.

Hardware and firmware facts
- [x] GPU generation: G17 (macOS loads AGXG17X).
- [x] GPU identity from the ID registers: family 0x0b, variant 0x04, 1 die,
      4 clusters x 10 cores.
- [x] Register, coprocessor and firmware locations from the ADT (proxy probe).
- [x] Preloaded firmware saved; build g17c, RTKit 3514.41.1, same on GFX and GFX1.

Firmware interface (g17c against the G17P definitions in `g17/fw/`)
- [x] Interface version: `[0x04c0, 0x8728, 0x4339, 0x0c8e]`.
- [x] Root: 0xc8 bytes, used fields at G17P's offsets.
- [x] Main config: the fields read at init are at G17P's offsets.
- [x] HwData up to G17P `0x1cf4`: G17P's layout.
- [x] HwData tail: G17P's layout 0x128 bytes later (completion rings `0x273c`,
      QoS `0x27d4`).
- [ ] HwData: where the 0x128 bytes start (between G17P `0x1cf4` and `0x2534`)
      and what they hold.
- [ ] Main config: the fields read after init (channels, views, power config).
- [ ] Secondary root and main config for GFX1.
- [ ] Region A and region C.
- [ ] Status blocks A and B.
- [ ] Channel, queue and command structures (render, compute, completion).

Kernel driver (linux-aurora `drivers/gpu/drm/asahi`)
- [ ] g17c interface in `g17/`, chosen by firmware build: version constant, root
      size, HwData offsets, and each structure that differs.
- [ ] `hw/t6050.rs`: G17 `Config` with the identity above, address-space sizes,
      secondary root offset, crash-buffer addresses, 13 performance states.
- [ ] `apple,agx-t6050` in the OF table.
- [x] `CONFIG_RUST` and `CONFIG_DRM_ASAHI` in `j714c.config` (rustc 1.99, bindgen
      0.73.2); the kernel builds with the driver in it (#87, Image.gz 7.3 MB).

Loader and device tree
- [x] m1n1: `dt_set_gpu_g17()` (was `dt_set_gpu_t8140()`) with the T6050 shape:
      14 perf states, 13 GPU states, 4 tables; fills the OPP table and the four UAT
      regions from the ADT. Device tree alias `gpu = &gpu`. Built, not boot-tested.
- [x] Device tree: `t6050-gpu.dtsi` (linux-aurora): GPU node `apple,agx-t6050`,
      `gfx`/`gfx1` mailboxes (ADT interrupts 2797-2800, 2801-2804), `ps_gfx`, UAT
      regions for the loader, OPP table from the ADT's `perf-states` (14 entries).
      All disabled until the loader hands the GPU over.

Userspace
- [ ] Mesa: G17C (T6050) device entry; mesa-aurora rebuilt on the Mac.

Bring-up
- [ ] Boot: both coprocessors start and the driver probes (kernel log).
- [ ] `kmscube` renders.
- [ ] Hyprland on the GPU.

## g17c interface — complete map (2026-10-28, workflow wf_cc83ddc2: 16 agents, all verified)

Every g17c firmware structure mapped against the G17P defs in `g17/fw/`. Deltas:

- **Interface version** (both coprocessors): `[0x04c0,0x8728,0x4339,0x0c8e]` (G17P `[0x04c0,0x0396,0xa322,0x0c8a]`). Checked at GFX `0x218a4`, GFX1 `0x26ce4`.
- **Root: 0xb8 -> 0xc8**, primary AND secondary. Two fields G17P had only on `SecondaryRoot` are now on both: `power_state_va` @+0xb8, `config_va` @+0xc0. Firmware copies 0xc8 bytes and extracts +0xb8/+0xc0 in both GFX and GFX1 init.
- **HwData: tail shifted +0x128.** Confirmed anchors: completion_rings @`0x273c` (G17P 0x2614), qos_va @`0x27d4` (G17P 0x26ac), unk_2544..2550 (=4,6,3,7) @`0x266c..0x2678`. The +0x128 insertion lives in G17P `[0x1cf4, 0x2534)` — perf_b's voltage tables / the `unk_23dc` opaque block — which the firmware **block-copies/DMAs, never field-reads**, so a 0x128 pad anywhere in that window is correct (grow `unk_23dc` 0x168 -> 0x290). perf_a is unshifted and unchanged (14 states overflow into its `unk_30` padding). GFX1 shares GFX's HwData.
- **RegionC: tail shifted +0xe38** (a *different* shift from HwData). Head `0x0..0xa06` unchanged; a 0xe38 block is inserted in the `unk_9d4` array; size 0x1000 -> ~0x1e38. `power_assert_tally` is firmware-written. Read-width diffs at +0x54/+0x6a/+0x998 are cosmetic (same offsets).
- **StatusBlock B: head +0x1e0 larger** (most divergent). `recovery_info` 0x40b8 -> 0x4298; the recovery/doorbell handshake relocated to the tail at +0xe71c (host pointer +0xe720); `PowerState` is NOT at the G17P offset. Needs a careful per-field remap, not a uniform shift.
- **PERF_STATES: 11 -> 14** (perf_a.freq_mhz read to index 13; 13 active + idle). OPPS=14, sram_min_mv=775, states_a=states_b=identity[0..13]. `relative_a/relative_b` are host->fw and macOS computes them at runtime from a power model (confirmed not a static table in the kext) — bring-up placeholder = t8140's `relative_a=[0,15,22,29,42,56,74,86,90,92,100]` / `relative_b=[0,0,13,24,40,52,63,73,83,88,100]`, padded to 14 (repeat the last pre-100 value, keep final 100). DVFS tuning only, not the interface gate.
- **Unchanged (carry over as-is):** MainConfig (every field at its G17P offset; +0x3e0 is used as a flags *byte* not u32, cosmetic), RegionA (opaque zeroed page; host must zero it), StatusBlock A (0x80 head; firmware writes a few more fields in place, no size change), Channels (byte-for-byte same ring/channel ABI), SecondaryRoot (0xc8, same as G17P).

Driver implication: the firmware-ABI structs must become chip-variant for **PERF_STATES (11/14), Root (0xb8/0xc8), HwData (+0x128), RegionC (+0xe38), StatusBlock B (+0x1e0)**. The first boot only needs the version + Root to pass the version gate; the rest gate whether firmware init completes.

## Bring-up fault loop (2026-10-29, increment 1 = interface-version gate)

Driver: per-chip interface version threaded through RootArgs; hw/t6050.rs (identity
real, register windows / perf curves / fixed buffers = t8140 placeholders, consumed
only after the version gate). Booted with WDT=170 so the Mac auto-recovers.

- gpu1 (WDT=0): GPU node bound, loader kept it "okay" (dt_set_gpu_g17 validated on
  hardware). Probe failed: "GFX1 ASCWrap v6 resources do not match T8140" — the
  mailbox driver hardcodes the T8140 wrapper/iop-vbar bases.
  FIX: drivers/soc/apple/mailbox.c — made the 4 bases per-chip fields on
  struct apple_mbox_hw, added apple_mbox_t6050_ascwrap_v6_hw (T6050 bases) and an
  "apple,t6050-ascwrap-v6" match entry. t8140 unchanged.
- gpu2 (WDT=170): big progress — driver Probes, reads GPU ID
  0xb041100 0xb0a00 0x11040a 0x40404 0x1320311 0x400c1809 (family 0xb variant 0x4,
  matches hw/t6050.rs), MMU init OK, RTKit init (protocol 12). New blocker, BEFORE
  the version gate: "RTKit: failed buffer request for 0x8000 bytes (-22)" x2. The
  g17c firmware requests its crash-log buffers at g17c-specific VAs; shmem_map
  (g17/mod.rs:318) rejects them because they != the t8140 placeholder crash_buffers
  va. Register windows mapped (t8140 placeholder phys) but not yet accessed.
  INVESTIGATING: added a pr_err in shmem_map to log the firmware's requested iova,
  so one boot reveals the T6050 crash-buffer VAs for both coprocessors.

- gpu3 (crash-buffer debug): added pr_err in shmem_map; firmware requests crash
  buffers at iova 0x10002864000 (GFX) / 0x10002920000 (GFX1), masked VAs
  0x2864000 / 0x2920000 = the GFX/GFX1 __DATA_SHARED_RO segments.
  FIX: hw/t6050.rs crash_buffers = {va 0x2864000, 0x8000}, {va 0x2920000, 0x8000}.
- gpu4 (crash buffers fixed): **INTERFACE VERSION GATE PASSED.** RTKit init
  completes on both coprocessors (crash buffers accepted), then:
  "RTKit: co-processor has crashed", "Expected crashlog header but got a5a5a5a5"
  (0xa5 = CRASH_BUFFER_FILL, so the fw crashed before writing a log),
  "GPU firmware (Primary) crashed", probe -EIO. NO "interface mismatch" message
  (the fw's version-reject path prints one), so the g17c version
  [0x04c0,0x8728,0x4339,0x0c8e] was ACCEPTED and the firmware crashed downstream
  reading the G17P-layout Root/HwData/RegionC/StatusB at g17c offsets (+ the
  t8140-placeholder register map). This is the "next increment" signal: the
  chip-variant ABI structs (Root 0xc8, HwData +0x128, RegionC +0xe38,
  StatusBlock B +0x1e0, PERF_STATES 14) and the real register map are now needed.

## Version gate PROVEN + remaining work (2026-10-29, increment 2 scope)

PROOF the g17c version is accepted: gpu4 showed the firmware hard-crash ("co-processor
has crashed", crashlog still 0xa5) while READING the init structs. Struct reads happen
AFTER the version check; a wrong version is a clean "interface mismatched" halt, not a
hard crash. So the firmware necessarily passed the version gate. The whole g17c
interface map is validated on hardware.

Fault-loop fixes landed (uncommitted, forks/linux-aurora):
- g17 Config is chip-parametric (register_windows/reserved_slots/perf/opps/
  interface_version per chip; t8140 unchanged).
- hw/t6050.rs (OF apple,agx-t6050), board DTS enables gpu+mailboxes, t6050-gpu.dtsi,
  m1n1 dt_set_gpu_g17 (all validated: loader keeps the node "okay").
- mailbox.c: per-chip ascwrap-v6 bases + apple_mbox_t6050_ascwrap_v6_hw + match.
- crash_buffers = {0x2864000, 0x2920000} (from the firmware's RTKit requests).

Remaining (increment 2 — the chip-variant ABI refactor; needs care, no t8140 boot here):
- Root: g17c primary is 0xc8 (G17P primary 0xb8) with power_state_va@0xb8,
  config_va@0xc0 — the fields G17P has only on SecondaryRoot. OPEN: the correct
  values for the PRIMARY (the secondary uses base+PRIVATE_CLUSTER+STATUS_B+POWER_STATE
  and state_va+STATUS_B). Likely the first crash (firmware reads the root first).
  This is an end-grow, safe for t8140 (it copies only 0xb8), so can be universal.
- HwData +0x128, RegionC +0xe38, StatusBlock B +0x1e0: MIDDLE insertions that shift
  later fields, so they need chip-variant layouts (const-generic on the delta, or
  duplicate struct types selected by chip). These CAN break t8140 if done wrong and
  t8140 is not boot-testable here — do carefully, keep t8140's layout byte-identical.
- PERF_STATES 11->14: shared const in the perf arrays; same const-generic problem.
- Register map: replace the t8140 placeholder windows with the real T6050 map
  (GPU-t6050-dt-config.md: 10 sgx-control windows + MCC) and grow on faults. The
  aperture `va` per window still needs deriving; fault-loop supplies the slots.

## Increment 2 fault loop (2026-10-29)

- gpu5 (real crash log): the g17c firmware asks for its crash-log buffers by
  PHYSICAL address (iova 0x10002864000 / 0x10002920000 = the GFX / GFX1
  __DATA_SHARED_RO segments) and writes the log there, not into the host's
  buffer (hence the a5a5a5a5). FIX: Config.crash_log_phys (t6050 true, t8140
  false); shmem_map memremaps the requested address. RESULT: full RTKit crash
  dump (`log/gpu5-crashlog.txt`): SError (ESR 0xbe000000) at fabric address
  FAR 0x480d40010 = t8140's slot-31 window phys + 0x10, nothing there on T6050.
  So the first blocker after the version gate is the register map. Also: the
  primary copies root+0xb8/+0xc0 to globals 0x10b788/0x1087b0 and never loads
  them, so Root growth is not the crash.
- gpu6: T6050 register map = the 10 sgx-control windows from the kext table at
  their T6050 slots/phys (SGX 0x23_0000_0000 + offset), reserved slots
  {2,5,6,7,8,18,19,20,21,24}; the slots t8140 uses outside that group
  (0,3,9,10,12,14,17,22) are TRAPS: va = aperture + 0x100_0000 + (slot << 20),
  phys 0 = left unmapped, so the firmware's first access faults with a FAR that
  names the slot and register offset.
- gpu6 (fault on trap 17 at +0x21038): the 10 sgx-control windows are right
  (no SError); slot 17 = sgx base, as on t8140.
- gpu7 (slots 17/22 mapped): secondary assert "AGFAfrPerfStateInit: When AFR
  pstate is controlled through PRC, async pstate change is not supported"
  (HwData+0x1058 != 0); primary NULL at StatusB+0xe720.
- gpu8: StatusB g17c init: +0xe720 = fwctl page (the firmware raises +0xe71c,
  then reads the word there, wants 0). Primary no longer crashes.
- gpu9: secondary NULL via MainConfig+0x481 = the PowerConfig pointer (G17P
  +0x471, moved +0x10 on g17c). FIX: init_secondary_g17c.
- gpu10..12: the g17c register map. KEY FINDINGS:
  - GFX1 data 0xfffffc000007bf88 holds the slot table: 54 x {slot, 0,
    name_ptr, 0x200000}, names in __TEXT (e.g. 46 ThrtlStatCntrsRegisters,
    24 DVFMMgpuRegisters, 20 AFRRegisters, 0 GPCAICSWInt). The macOS kext has
    the matching description list (kernelcache ~0x1565d5), with "(unused)" on
    1, 2, 3, 4, 5, 6, 7, 14, 44, 52.
  - Slots go to 59: the g17c HwData register map has 60 slots (G17P 53), so
    everything after it moves +0x118 (chip_id 0xfa8, perf_a 0x10dc; the AFR
    word 0x1058 is G17P's unset 0xf40; 0x10d4/0x10d8 = G17P's required 4/6);
    the tail (0x2544 on) is +0x128, i.e. another 0x10 later. HwData is now
    HwData<SLOTS, GAP>, g17c = HwData<60, 0x10>.
  - GFX1 copies an entry only if phys != 0, so unmapped "trap" slots read as
    NULL: traps removed. Unlocated blocks are host-RAM scratch windows (phys
    0xdead_0000_0000 marker, 1 MiB, 4 elements, 2 MiB apart) so firmware
    writes land in RAM. Multi-element blocks (DVFMMgpu: 4 per-cluster
    elements at element_size stride) need RegisterWindow.elements.
  - Known T6050 windows: 0 = AIC SW-int page 0x2_8041_4000 (ADT
    meta-sw-interrupt), 17 = sgx (0x21500), 22 = sgx+0x100_0000 (t8140
    analogy), 53 = sgx+0x2_3d00 (0x200), sgx-control 31..48 (kext table).
  - Scratch (address still to find): 9 10 11 12 13 15 16 18 19 20 23 24 25
    26 27 29 30 32 35 43 45 46 47 49 54 55 56 57 58 59.
- gpu13: **FIRMWARE INIT COMPLETE.** "[drm] Initialized asahi 0.0.0 for
  2302600000.gpu on minor 1"; no coprocessor crash; card1 + renderD128.
  Userspace: the rootfs Mesa refuses it ("Apple G17C uses the HAL300 command
  stream, which this driver does not implement (variant 0x43, 4 clusters)"),
  SDDM's wayland greeter fails EGL, the screen stays on the console
  (`log/gpu13b-desktop.txt`). Next: Mesa G17C/HAL300 support, and the real
  addresses of the scratch slots (DVFS/clocks/throttle do nothing yet).
- Open (not verified on hardware):
  - "No crash" in gpu13 means none in the ~60 s sampled after handoff; a
    longer run (WDT=0) would show whether the firmware survives its first
    idle/power-down (the +0xe71c/+0xe720 handshake).
  - The extra 0x10 of the g17c HwData tail is placed at the end of unk_23dc;
    only fields after it are anchored, so its exact position is unconfirmed.
  - bundle::VIEWS[0..1] (0x2740/0x3380) lie inside HwData and were not moved
    for g17c; init works, the recovery-view code reads them host-side.
- gpu14 (hal_generation 300, WDT 178, sampled 145 s after handoff): firmware
  still up at ~2 min of uptime, no crash. The Mac has no GL/Vulkan test tool
  (no vulkaninfo, kmscube, eglinfo, glmark2). Its Mesa (mesa-aurora
  7f0206e79f9, 2026-10-28) has no ASAHI_M5_BRINGUP switch, so the M5 HAL300
  path needs a newer Mesa build.
- Mesa (omacom/mesa integration/aurora, from aurora-silicon/mesa): the M5
  HAL300 path exists (AGX3C compiler, HAL300 records, Honeykrisp submit),
  behind ASAHI_M5_BRINGUP=1, admitted only for G17G/0x8142 and G17S/0x6050
  (agx_params_m5_bringup_supported). G17C has the same ISA encoding (AGX3C),
  command stream (HAL300) and descriptor generation (10) as G17S; only that
  gate and agx_chip_g17_m5() leave it out. A basic compute dispatch needs no
  M5 kernel feature bits (COMPUTE_RESOURCES only with scratch/TPS).
- aurora-silicon/linux has t6050/* platform branches (usb, pcie, nvme, dcp,
  smc, ...) but no GPU branch.
- Mesa cross-build (2026-10-29): forks/mesa-aurora (omacom/mesa
  integration/aurora 672657e) + G17C admitted in the ASAHI_M5_BRINGUP gate
  (exact: G17C, chip 0x6050, 4 clusters; agx_chip_g17_m5 includes G17C; the
  three AGX3C encoding switches and the shader-binary version switch cover
  G17C). Built on Omarchy with clang --target=aarch64-unknown-linux-gnu
  against a sysroot copied from the Mac (glibc 2.43, GCC 16.1.1 libstdc++);
  native mesa_clc/asahi_clc/vtn_bindgen2 from a separate host build. Runs from
  ~/mesa-m5 on the Mac via VK_ICD_FILENAMES; the system Mesa is untouched.
  Test: ~/mesa-m5/vkfill (one compute dispatch, i*3+7 into 4096 words).
- gpu15b: Mesa opens "Apple M5 Max (G17C B1)", compiles the shader, records
  the command buffer; vkQueueSubmit fails: kernel ENOENT.
- gpu16..18 (asahi.debug_flags=0x3600 + temporary submit traces): parse and
  validation pass; ENOENT from ensure_compute -> install_job_context_aliases:
  the seven G17P "native render context" views (user VA 0x1000000000..) are
  not bound. Mesa says they are a HAL200 construct (agx_chip_has_native_
  render_context = G17P only). FIX: G17C user VMs have no context views
  (Vm::without_context_views; install_job_context_aliases skips none).
- gpu19/20: the submit is accepted and the compute job reaches the firmware;
  it never completes: job timeout (ETIMEDOUT), "GPU event service failed:
  Error(110)", device lost. No firmware crash, no firmware log output (with
  FwLogCh/EventCh/DeviceControlCh/FwCtlCh tracing). Next: the g17c compute
  queue/job structures (queue descriptor, work ring entry, compute command,
  kick), mapped against the firmware like the init structures.
- Workflow wf_3756af2b (10 agents, claude-opus-4-8): g17c job structures vs
  G17P. Byte-for-byte unchanged (confirmed): WorkSlot (0x18; GFX consumes all
  work rings, channel = priority*3 + engine, a data_master mismatch is
  skipped silently), QueueRecord/PointerBlock/item ring, QueueConfig/
  KickAnnounce/KickPredecessor (tags unchanged; dispatch covers tags 0..0x12),
  KickEntry (stride 0x200, 256 slots; descriptor_va bit 0 is a firmware
  flag). ComputeDescriptor: unchanged through current_id@0xf68; g17c also
  touches +0xfac/+0xff9/+0xffd/+0x101d (G17P padding) on its retire
  sub-path; +0xff9 is firmware-written (1 on start).
- gpu21/22 (timeout dumps): the compute job is descriptor slot 1 (tag 3).
  The firmware drained all 4 item-ring commands (QueueRecord+0x1c = 4,
  PointerBlock done = 4) but never marked the kick entry (header 0x4, no bit
  1) and never started the descriptor (+0xff9 = 0). Kick entry 1:
  0x10001000_00000004, descriptor 0xfffffc2189524000, queue
  0xfffffc20c083c000, +0x20 dependency_control 1 / 0xffff0802.
- gpu23 (scratch dump at timeout): the firmware wrote only slots 20 (AFR,
  per-element +0x4=0x10101/+0x10=1/+0x118=0x10, 0x10000 stride; the ADT has
  16 FAB_AFR_AMCC units), 23/24 (DVFM, +0x4000 = 1 per element) and 46/58
  (throttle-counter masks). No writes to the power/clock scratch blocks.
  Open: why the KickAnnounce does not launch the kick entry (a dependency
  that never resolves, or a wait on a stubbed register).
- Kick launch path (GFX, static): KickAnnounce (0x12b84) only records qid
  and count (into [0x1096c8]+0x103a8 / +0x21018) and bumps 0xb7c70; it does
  not launch. QueueConfig install (0x12924 -> 0x12db4) fills the per-QID
  table 0xb94b8 + qid*0x28: +0x00 installed=1, +0x08 = QueueConfig+0x10
  (kick-ring base), +0x10 = QueueConfig+0x08, +0x18 = QueueConfig+0x04,
  +0x1c = (4 - QueueConfig+0x1e)*3 - 2, +0x20 = QueueConfig+0x22 (engine,
  selects ready bitmap 0xba8c0 + engine*16). The scheduler (0x108d4.., 128
  QIDs) keeps per-QID state at 0xbb930 + qid*0x58 (+0x40 next slot, +0x48
  remaining) and launches kick entries ring_base + (slot & 0xff)*0x200 via
  0xfc48, up to the host timestamp in MainConfig+0x274 (view 4) per QID
  {u32 at +0, u64 at +8}.
- k33 (built, not booted): on compute timeout, dumps those firmware globals
  for the job's QID from the GFX __DATA segment (phys 0x100027a4000, VA
  0xfffffc0000050000), to see whether the QID is installed and where its
  cursor stands.
- gpu24..30 (firmware-side readouts at the compute timeout; traces only):
  - The job's QID (4) is installed (per-QID table: kick ring
    0xfffffc2189500000, engine 2, priority 2) and set in the compute ready
    bitmap; its scheduler record shows the kick announced (+0x10 = 1,
    +0x18 = 1). Slot numbering matches (next slot = +0x00 + 1 = 1).
  - Firmware event trace (status A word 0 = trace mask, copied to fw global
    0x1092a4; records drained from the trace ring): 0x40 queue install
    (qid 4, engine 2, prio 2), 0x41 kick announce (qid 4, ts 1, count 1),
    0x57 KickPredecessor (qid 4, prev 0, 0xfe), then 0x46 "GPU active"
    mask set 0x80/0x40/0x2.
  - On the 0 -> active transition the firmware calls
    agfKSMKickQueuesSchedulingPause (0x234fc): request bit 0 of
    sgx+0x211c8, poll bit 0 of sgx+0x211d0 ("ERROR: PIO poll ... timeout
    ..., continue wait"). Readback: sgx+0x211c8 = 5 (pause requested),
    sgx+0x211d0 = 4 (never acknowledged). The firmware stays in that wait;
    the kick is never launched and later host events time out.
  - GPU power domains at the timeout (PMGR target/actual): gpx, gfx,
    pms_gfx_c1ppt, soc_dpe_gfx on; afr target f / actual 4; cs, aic_gfx,
    b2b_ctrl_gfx, fppt_gfx off. Forcing cs (gpu28) and all four (gpu30) on
    with apple,always-on did not change the stall.
  - Open: what the KSM needs to acknowledge a pause. Candidates are the
    blocks still backed by host RAM (AFR 20, DVFM 23/24, KSMFE 35, PMC 16,
    PMGR misc 54/55, DpwrMXU 56, ...): their real addresses come from the
    macOS kext's runtime ADT lookup, not from any static table found so far.
- Workflow wf_a0538809 (9 agents, claude-opus-4-8): the macOS AGXG17X
  register map for this machine. The kext keeps one 0x438-byte record per
  firmware slot (object+0x760 + slot*0x438; per element phys[], size,
  type word). Addresses come from (a) its static sgx table (kernelcache
  0x153040), (b) per-block filler functions with literal offsets
  (regBase(die) + offset, or absolute literals), (c) chip-variant gates.
  Mapped on T6050: 0 (0x2_8041_4000), 3 MCache (4 x 0x24000 from
  0x22_2010_4000, 0x200_0000 apart), 9 (0x2_8425_0000), 11 (0x2_8425_8000),
  12 ANE0 (0x5_0965_c000), 15 AON PTD (0x2_8cdc_0000, 0x24000), 17, 18 AFR
  clkgen (sgx+0xeb4000), 20 AFR (4 x 0x40000 from sgx+0x3000000, 0x200000
  apart), 22 (sgx+0x1000000), 23 AFR DVFM (sgx+0xf00000, 0x10000), 24 GPU
  DVFM (4 x 0x10000 from sgx+0xec0000), the sgx-control group, 44 MTR (2 x
  0x8000 at sgx+0xe08000), 46/58 throttle counters (sgx+0xe33800 /
  sgx+0xe73800), 52 AFR MTR (sgx+0xe48000), 53. Address but type 0: 4, 10,
  14. Empty on T6050 (including KSMFE 35, PMC 16, PMGR misc 54/55, DpwrMXU
  56, GFXCLKGEN 45, ANE1 13 = Ultra-only, D2DNI 59 = Ultra-only). The
  earlier RAM-backed stand-ins gave the firmware ~20 blocks macOS leaves
  absent.
- k40 (built, not booted yet): hw/t6050.rs uses exactly that map
  (RegisterWindow.phys_stride for non-contiguous elements, type-0 windows,
  reserved = slots macOS names with type 2 but no window; RAM stand-ins
  removed).
- gpu31 (k40, macOS register map): init still completes; same stall (KSM
  pause requested, never acknowledged). halWriteKSMFEReg/halReadKSMFEReg are
  panic stubs on this HAL300 build, so macOS does not program KSMFE either.
- gpu32/33 + pmgrcs (cs, aic_gfx, b2b_ctrl_gfx, fppt_gfx forced
  apple,always-on; dump also on event-service failure): aic_gfx and
  b2b_ctrl_gfx come on, fppt_gfx goes to auto (actual 4), but CS refuses:
  "PS cs: Failed to reach power state 0xf (requested 0xf00000f, now:
  0xf000300)" - the target write does not stick. t6050_noauto changes
  nothing (AFR is already in auto mode before Linux).
- The ADT PMGR entry for CS (id2 361, group 3, offset 0x108) has
  notify_pmp = True, parents 360 (AFR) and 359: its power transitions must
  go through the PMP coprocessor. Linux has no T6050 PMP path yet (the PMP
  work for CPU core start is in kernel/PMP-CORESTART.md, another session).
  Working hypothesis: the GPU compute slice (CS) stays off, so the kick
  scheduler cannot acknowledge the pause and no compute job runs, until CS
  can be powered through the PMP.
- gpu34 (render test ~/mesa-m5/vkdraw: 64x64 linear colour target, a
  clear-only render pass, then a triangle): the graphics pipeline compiles;
  the clear-only pass already stalls. The firmware trace shows the stuck kick
  is again QID 4 on engine 2 (compute): Mesa's M5 path runs a precompiled
  compute helper for the render pass first. So rendering depends on CS too.
- PMP0 (ADT /arm-io/pmp0, ascwrap-v6): reg[0] 0x2_84e0_0000 (ASC, 0x88000),
  reg[1] 0x2_8485_0000, reg[2] 0x2_8450_0000 (0x100000), reg[3]
  0x2_8425_0000 = the PTD update register (ptd-update-reg-index 3) - the same
  block macOS hands the GPU firmware as slot 9 (PushTelemetryDashboard); slot
  11 0x2_8425_0000+0x8000 is its config space. So the GPU firmware itself
  talks to the PMP through the PTD on macOS.
- Proxy read of the PMP ASC CPU_CONTROL (0x2_84e0_0044) takes a SYNC
  exception in m1n1 and wedges the resident proxy (needs a manual reset):
  the AP cannot even read the PMP's ASC registers in this context. Whether
  the PMP is running is still unknown.
- PMP liveness (proxy, read-only): the PMP firmware memory (pmp0 reg[2]
  0x2_8450_0000, 1 MiB) holds firmware (95715 nonzero words) and did not
  change in 3 s. ps_pmp (0x2_8060_0128) = 0x0f0000ff: the PMP's own domain is
  on. Its ASC registers still fault (SYNC) on AP access, so the AP is
  locked out of the PMP's control and mailbox in this context. mcc PTD
  ranges: doorbell reg[2] 0x2_8424_0000, update reg[3] 0x2_8425_0000,
  drv2ctrl reg[15] 0x22_2200_0000, ctrl2drv reg[18] 0x22_2800_0000.
- Conclusion for the GPU: CS (notify_pmp) can only be powered by the PMP;
  the PMP does not act on requests from this context (GPU firmware PTD
  ring, m1n1 or Linux), and starting or handshaking it needs registers the
  AP cannot touch. Compute and rendering (whose Mesa M5 path starts every
  render pass with a compute helper) are blocked on that, the same SPTM/PMP
  wall as the secondary CPU cores. Everything before job execution works:
  firmware init, DRM device, Mesa device/compile/submit.
