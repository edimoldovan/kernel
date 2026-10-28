# GPU on the M5 Max: device tree, loader, kernel config

Detail for the plan items in [GPU.md](GPU.md): the T6050 GPU device-tree node,
the m1n1 handoff (`dt_set_gpu_t6050`), and `hw/t6050.rs`. Addresses are from the
proxy probe (`log/gpu-probe1.txt`) and the ADT (`boot-j714c/adt.txt`); the A18
Pro (`apple,agx-t8140`) is the template.

Done when the asahi driver probes the GPU on the J714c. [x] filled, [ ] open.

## Facts (T6050 GPU)

- Registers (probe): sgx `0x2300000000`; gfx-asc wrapper `0x2302600000` (size
  0x88000), iop-vbar `0x2302050000`; gfx1-asc wrapper `0x2302e00000`, second
  region `0x2302850000` (size 0x60000 — gfx-asc's is 0x8; confirm before use).
- Interrupts (ADT): gfx-asc `[2798, 2797, 2800, 2799]`, gfx1-asc
  `[2802, 2801, 2804, 2803]` (ascwrap-v6 order).
- Power: ADT power-gates gfx `614`, gfx1 `657`. Power domain `ps_gfx`
  (`t6050-pmgr.dtsi:1695`, `power-controller@110`, label "gfx"); must be
  `apple,always-on` as on t8140.
- Identity (ID registers): family `0x0b`, variant `0x04`, 1 die, 4 clusters x
  10 cores = 40 cores. GPU variant C (`G17C`, from the firmware and Mesa).
- Perf (ADT): `perf-state-count = 14`, `gpu-num-perf-states = 13`,
  `perf-state-table-count = 4`. The A18 Pro has 16 / 11 / 2. So the OPP table has
  14 entries, 13 active DVFS states, and four SRAM voltage tables
  (`perf-states-sram`, `-sram1`, `-sram2`, `-sram3` — one per cluster).
- Operating points (ADT `perf-states`, freq Hz / volt mV):
  `0/125, 338M/630, 486M/670, 636M/705, 796M/745, 888M/755, 988M/780,
  1084M/815, 1182M/825, 1278M/860, 1374M/900, 1470M/940, 1578M/1020,
  1620M/1055`. SRAM volts are a separate table (`perf-states-sram`).
- Loader regions (ADT, filled into reserved-memory): `gpu-region` (0x4000),
  `gfx-shared-region` (0x80000), `gfx-shared-l2-region` (0x4000),
  `gfx-handoff` (0x4000). Bases are ADT-provided; the loader copies them.

## Device tree (add to `t6050*.dtsi`, a new GPU node)

```dts
gpu: gpu@... {
    compatible = "apple,agx-t6050";
    reg = <0x23 0x02600000 0x0 0x88000>,   /* asc  (gfx-asc wrapper) */
          <0x23 0x00000000 0x0 0x4000000>; /* sgx  (GPU MMIO) */
    reg-names = "asc", "sgx";
    mboxes = <&gfx_mbox>, <&gfx1_mbox>;
    power-domains = <&ps_gfx>;
    memory-region = <&uat_ttbs>, <&uat_pagetables>, <&uat_handoff>;
    memory-region-names = "ttbs", "pagetables", "handoff";
    operating-points-v2 = <&gpu_opp>;
    status = "disabled";               /* the loader enables it */
};

gfx_mbox: mailbox@2302600000 {
    compatible = "apple,t6050-ascwrap-v6";
    reg = <0x23 0x02600000 0x0 0x88000>, <0x23 0x02050000 0x0 0x8>;
    reg-names = "wrapper", "iop-vbar";
    interrupt-parent = <&aic>;
    interrupts = <AIC_IRQ <n> IRQ_TYPE_LEVEL_HIGH>,   /* send-empty, recv-not-empty */
                 <AIC_IRQ <n> IRQ_TYPE_LEVEL_HIGH>;   /* from [2798,2797,2800,2799] */
    interrupt-names = "send-empty", "recv-not-empty";
    apple,firmware-role = "GFX";
    power-domains = <&ps_gfx>;
    #mbox-cells = <0>;
    status = "disabled";
};
/* gfx1_mbox: as above at 0x2302e00000, role "GFX1", irqs from [2802,2801,2804,2803] */
```

- `ps_gfx`: add `apple,always-on` (as t8140; the firmware runs across sleep).
- `reserved-memory`: `uat-handoff`, `uat-pagetables`, `uat-ttbs` (and
  `uat-l2-pagetables`) with `reg = <0 0 0 0>`, filled by the loader.
- `gpu_opp`: `operating-points-v2` with **14** `oppNN` placeholder nodes (t8140
  has 16), each `opp-hz = <0>` and `opp-microvolt = <125000>`; the loader
  overwrites them in perf-state order (not sorted by frequency).
- [ ] The mailbox interrupt numbers: map the four ADT values to
  send-empty/recv-not-empty as t8140 does (993/996 there).
- [ ] The sgx window size (`0x4000000` as t8140; probe reg0 was `0x3fdc000`).
- [ ] The gfx1 second region size (`0x60000` in the probe vs `0x8` for gfx-asc).

## Loader: `dt_set_gpu_t6050()` in m1n1 `src/kboot_gpu.c`

From `dt_set_gpu_t8140()` (the template), changed for T6050:

- Accept `perf-state-count == 14` (t8140 requires 16) and a 14-node OPP table.
- Fill the 14 OPP nodes from ADT `perf-states` (`opp-hz` = freq, `opp-microvolt`
  = volt x 1000), in perf-state order.
- Fill the four reserved-memory regions from ADT `gpu-region`,
  `gfx-shared-region`, `gfx-shared-l2-region`, `gfx-handoff` base/size into
  `/reserved-memory/uat-ttbs`, `uat-pagetables`, `uat-l2-pagetables`,
  `uat-handoff`.
- Enable the node (clear `status = "disabled"`); match on `apple,agx-t6050`.
- [ ] The four SRAM tables (`perf-states-sram{,1,2,3}`): t8140 passes one SRAM
  table; T6050 has four (one per cluster). Decide what the handoff/driver needs.

## Kernel: `hw/t6050.rs` (from `hw/t8140.rs`)

`Config` (`g17/mod.rs`):
- [x] `chip_id = 0x6050`.
- [x] `identity`: family `0xb`, variant `0x4`, `num_dies = 1`,
      `gpu_variant = GpuVariant::C`, `usc_generation`/`hal_generation` TBD
      (t8140: 3 / 200; confirm from the g17c firmware).
- [x] `uat_ias = 42`, `uat_oas = 42` (same UAT geometry; confirm).
- [ ] `secondary_root_offset` (t8140 `0x40000`), `crash_buffers`, `pm_metrics`:
      confirm the g17c firmware requests the same addresses (it has two
      coprocessors like t8140).

`PerfConfig` (`PERF`) and `OPPS`:
- `PERF_STATES = 13` (t8140: 11), `OPPS = 14` (t8140: 16). These are new
  constants for the T6050 path, not the shared G17P values.
- [ ] `states_a` / `states_b`: which operating point each DVFS state uses.
      With 4 perf tables (not 2), the A/B split differs — derive from the ADT
      `afr-perf-states` / `cs-perf-states` and the four SRAM tables.
- [ ] `relative_a` / `relative_b`, `sram_min_mv`: from the ADT.

`REGISTER_WINDOWS` / `RESERVED_REGISTER_SLOTS`:
- The firmware's MMIO register map, 18 windows (`hw/t8140.rs`). It is not an ADT
  property (the macOS sgx node has only its two `reg` ranges, no window list) and
  the sgx-relative offsets are not stored in the kernelcache (the AGX kext forms
  them at runtime as sgx-base + offset). The asahi values were traced from macOS.
- [x] 12 of 18 are sgx-relative: `phys - 0x4_8000_0000` (t8140 sgx) is in
      `[0, 0x400_0000)`, and for those `unk_18` is that offset. They rebase to
      the T6050 sgx base `0x23_0000_0000`. GPU-internal, same generation, so the
      offsets carry over; all land inside the sgx window (size `0x3fdc000`), and
      slot 26 (`+0xd04000`, ID_VERSION) was read live in the probe.

      | slot | T6050 phys       | size     | unk_18    | unk_20 |
      |------|------------------|----------|-----------|--------|
      | 17   | `0x23_0000_0000` | `0x21400`| 0         | 2 |
      | 22   | `0x23_0100_0000` | `0x8000` | 0         | 2 |
      | 26   | `0x23_00d0_4000` | `0x8000` | `0xd04000`| 2 |
      | 27   | `0x23_00d0_d000` | `0x1000` | `0xd0d000`| 2 |
      | 28   | `0x23_00d5_8000` | `0x8000` | `0xd58000`| 2 |
      | 29   | `0x23_00d1_0000` | `0x4000` | `0xd10000`| 2 |
      | 31   | `0x23_00d4_0000` | `0x4000` | `0xd40000`| 2 |
      | 32   | `0x23_00d6_0000` | `0x4000` | `0xd60000`| 2 |
      | 35   | `0x23_00e0_0000` | `0x4000` | `0xe00000`| 2 |
      | 39   | `0x23_00e0_8000` | `0x8000` | 0         | 2 |
      | 40   | `0x23_00e1_c000` | `0x4000` | `0xe1c000`| 2 |
      | 41   | `0x23_00e1_f800` | `0x4000` | 0         | 2 |

      The aperture offset (`va`) and `size` are unchanged from t8140.
- [ ] 6 windows are other SoC blocks (not sgx-relative), t8140:
      slot 0 `0x3_0101_4000`, 3 `0x2_2010_4000`, 9 `0x3_003d_0000`,
      10 `0x3_003c_0000`, 12 `0x4_0165_c000`, 14 `0x3_0028_0000`. These are
      fabric / PMGR / MCC blocks around the GPU (the sgx node names an MCC via
      `function-mcc_dataset` -> `/arm-io/mcc`; PMGR holds clock/power-gates
      614/615/616). Their T6050 addresses differ and are not derivable by rebase.
- [ ] Get all 18 definitively by tracing macOS GPU init under the m1n1
      hypervisor (`hv.trace_range` on the sgx/gfx MMIO during AGXG17X startup) —
      the method the asahi values came from. This also confirms the 12 above and
      the window sizes. The AGX register-map builder is near kernelcache offset
      `0x151000` (it references the sgx offsets `0xd04000`, `0xd40000`,
      `0xd60000`), if a static extraction is preferred over a trace.
- `RESERVED_REGISTER_SLOTS` (t8140: 17 slots): re-derive from the T6050 trace;
  the slot numbering may differ.

`kernel_window` / `dynamic` / `low` (GPU-VA layout):
- [ ] Likely unchanged from t8140 (same firmware generation); confirm the g17c
      firmware requests the same fixed VAs (crash buffers, completion rings,
      free lists).

## Plan

- [x] GPU node addresses, interrupts, power domain, perf counts, OPP values.
- [x] `Config` identity, chip id, UAT geometry for `hw/t6050.rs`.
- [ ] Device-tree node committed to `t6050*.dtsi` (+ `ps_gfx` always-on, OPP
      placeholders, reserved-memory).
- [ ] `dt_set_gpu_t6050()` in m1n1 (14 states, 4 SRAM tables, regions).
- [~] `hw/t6050.rs` register windows: 12 of 18 rebased (above); 6 non-sgx and
      the slot reservations need a macOS MMIO trace.
- [ ] `hw/t6050.rs`: perf tables, fixed buffers; `apple,agx-t6050` in the OF table.
- [ ] `CONFIG_DRM_ASAHI` + the G17 path in `j714c.config`.
