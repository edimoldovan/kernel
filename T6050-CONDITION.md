# T6050 secondary-core block: the real condition (2026-11-03)

Driven by scottjones's data (T8142/base-M5 runs unsigned Linux on all cores,
direct loader start, identical SPTM code) + the GPU session's "PMP never started".
Three-way diff T6050(j714c) vs T8142(j813): ADT, SPTM, iBoot. Result reframes the
problem and CORRECTS the earlier "SPTM crypto wall" framing.

## It is a reset-RELEASE problem, not execute-permission

- The T6050 secondary powers up (PS 0xef20d102), holds a correct, cpu0-identical
  RVBAR, and NEVER fetches instruction 0 — so it never reaches SPTM reset_entry
  (0xab46c). The SPTM therefore cannot be what blocks it.
- For a raw (CustomOS) loader the SPTM is NOT active on either chip: live cpu0
  GXF_CONFIG_EL1=0, /chosen SPTM-ro/rx/rw absent (0xffff). iBoot's SPTM-adoption
  gate (0x28554, kc_layout bx_size) is byte-identical in both iBoots, not chip-
  conditional. (The sptm_retype crypto wall is real only for the ride-XNU scenario
  — running Linux UNDER adopted XNU — not for direct loader start.)
- SPTM per-core path (reset_entry 0xab46c, GXF bootstrap 0xab8e4, register_cpu
  0xb8fac, CTXR/SPRR writer 0xbd0c0, sptm_retype 0xf4bb0) is byte-identical T6050
  vs T8142, differing only by relocations and the CPU-table capacity bound
  (cmp #0x23 vs #9). Unconditional — no chip-id/fuse/DT branch.
- No device-tree prop gates fetch: neither DeviceTree.j714cap nor .j813ap has any
  per-core reset/RVBAR/CTRR/CTXR/fetch-enable prop, and iBoot+SPTM read none of the
  props that differ. Not DT-fixable.

## The T6050-specific discriminator: the PMP moved + the AP window is locked

- **pmgr function-pmp_control (PMPC): T8142 HAS it, T6050 does NOT.** On T8142 the
  core-release/PMP function is driven directly from pmgr registers a plain EL2
  loader can write — so the release lands and every core fetches. On T6050 that
  function moved into TWO standalone PMP coprocessors (/arm-io/pmp0 @0x284e00000
  + /arm-io/pmp1) that must be BOOTED; their ASC control surface is EL2-locked
  (reads fault/wedge the proxy). The PMP is never started on our boot (GPU session:
  PTD window all zero), so nothing grants the per-core release.
- **The per-core ACC/impl register window is EL2-access-locked at reset default:**
  cpu-impl-reg/acc-impl-reg/cpm-impl-reg/cpu-uttdbg-reg/coresight-reg SError on
  read AND write at every offset except RVBAR(+0x0) and +0x100 — and the SError
  reproduces on the RUNNING cpu0 (e.g. uttdbg+0x8). So it is a chip-wide MMIO-fabric
  access control, not a per-secondary not-yet-released state.
- Stuck core = cpu1 (cluster 0, die0, no cluster-power-down). m1n1 reaches its
  correct RVBAR, so addressing is right; the block is downstream of addressing.
  (die-stride / cluster-power-down loader-bug hypotheses are CLOSED for cpu1; they
  would apply only to die-1 cores or the P-clusters cpu12-17/30-35.)

## Verdict + the one cheap test that could flip it

Verdict: leans **silicon / wait-for-Apple** (medium confidence) — on T6050 the
per-core release is routed through the PMP coprocessor + an EL2-locked MMIO window,
where on T8142 it is plain EL2 MMIO. Not loader-fixable from m1n1's EL2 context,
not DT, not SPTM. Cores AND the GPU's CS domain share this one root cause (PMP
unstarted + EL2 access-lock).

ONE cheap, safe live test could still flip it to tractable (single 32-bit reads +
at most one write; NO bulk reads — they killed the proxy; NO PMP ASC reads — they
wedge it):
- Read cpu0 cpu-impl-reg +0x100 vs cpu1 +0x100 (the only offset besides RVBAR that
  does NOT SError). Nobody has compared it across cores.
- If IDENTICAL -> no EL2-writable per-core lever -> silicon verdict stands.
- If DIFFERENT -> write cpu0's +0x100 value into cpu1's +0x100, re-check fetch. The
  only safe write in the picture and the one experiment that could make this a
  tractable lead.
