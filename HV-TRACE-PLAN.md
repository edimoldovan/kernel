# Plan: find the missing T6050 secondary-core state

Goal: find the one thing macOS does to wake a T6050 (M5 Max) secondary core
that our loader does not, then replay it. Reverse-engineer the binaries we
already have first (desk, no Mac); only trace live macOS under a ported
hypervisor if the desk path comes up empty.

## Why desk-first (facts)

- m1n1 bare-metal already performs the known T6050 core-start MMIO
  (`src/smp.c`: `cpu_start_bit()` handles `chip_id == T6050`; writes
  `start_base+0x4` then `start_base+0x8 + 4*cluster`). The core still parks.
  So the missing state is set **earlier**, not in this sequence.
- The two places it can be set are both in binaries on disk in
  `j714c/firmware/`:
  - iBoot's OS-mode path — reached only when `boot_mode==7` (gate at iBoot
    `0x2368`). CustomOS never takes this branch, so any CPU/cluster MMIO it
    writes is state the real boot sets and our boot does not.
  - SPTM's one-time boot-init path — **not** `register_cpu`/`reset_entry`,
    which we already diffed T6050-vs-T8142 as identical (BOOTKC.md). Init is
    a different function and was not compared.
- If the desk RE finds the writes, we add them to `smp.c` and never need the
  hypervisor at all.
- The hypervisor route is unported: `forks/omacom-m1n1` has 0 SPTM hv commits
  and no nested-virt work. Its hv virtualizes SPRR/GXF (`src/hv/hv_sprr.c`),
  not SPTM. Size of that port is unknown until Step 0a.

## Step 0 — Desk RE (no Mac)

- **0a. Can the hv even host an SPTM guest?** The hv runs at EL2; SPTM runs at
  GL2 (guarded EL2). A guest that contains SPTM at its own level needs nested
  virtualization. Determine from (i) the SPTM binary — does it assume it is the
  top privilege / does it probe for a hypervisor — and (ii) one live read of
  `ID_AA64MMFR2_EL1` NV field (bits 27:24) off the chip when the Mac is free.
  NV==0 → no nested virt → the guest cannot hold SPTM at GL2; the hv route then
  means emulate SPTM inside m1n1, or demote it to GL1 (both research, not
  porting).
  Done = one line: hv-hosts-SPTM feasible or not, and which sub-approach.
- **0b. iBoot OS-path MMIO.** Enumerate the MMIO writes reachable only via the
  `boot_mode==7` branch (the path CustomOS skips).
  Done = address list.
- **0c. SPTM init MMIO.** Enumerate the MMIO writes in SPTM's one-time boot-init
  path (not the per-core functions already diffed).
  Done = address list.
- Output: a candidate "missing writes" list — cluster/CPU-level MMIO the OS
  path does that m1n1 does not.

### Step 0 RESULTS (2026-10-29, workflow bootkc-step0-re + hand-verified diff)

Outcome: **no replayable software write exists.** The candidate "missing writes"
list is empty. The boot-path code that brings up a secondary is identical
between T6050 (cores park) and T8142 (cores start bare-metal under m1n1).

- **0b — iBoot OS-path: clean negative (high confidence).** The `boot_mode==7`
  path does only image/layout work (kc_layout builder `0x27830`, SPTM object
  registration `0x206568`) — zero MMIO, zero `msr`. iBoot writes nothing at
  `pmgr+0x88000` (the CPU_START online/wake block m1n1 uses); it is single-core
  and never starts APs, so there is no "cores may start" latch for CustomOS to
  skip. The cluster/CPU MMIO iBoot does do (CPM/ACC/cpu-impl init) is in common
  startup, run on BOTH boot modes, and already done before m1n1 is chainloaded.
- **0c — SPTM init: identical to T8142 (hand-verified).** Normalized diff of the
  ASM init (`0xab000..0xab988`) is empty but for the core-count constant
  (`mov x4,#0x24`=36 vs `#0xa`=10) and relocations. The C init
  (`0xb9900..0xbb354`) has an identical **sysreg and MMIO write set**: the `msr`
  to every guarded/CTXR register (`s3_6_c15_*`, `s3_0_c11_c5_*`) is byte-for-byte
  the same; the only deltas are two `strb` to struct memory and a relocated
  logging block, both consistent with 36 vs 10 cores. The guarded-mode self-
  config a secondary runs out of reset (SPRR_CONFIG enable+lock, GXF_CONFIG,
  GXF_ENTER/ABORT vectors, VBAR_GL1, SPRR_PERM tables, GENTER `0x00201420`, the
  CTXR arm-flag at `__DATA 0x112140` bit17, and CTXR `s3_0_c11_c5_*` region
  programming) is all PER-CPU self-config and all identical to the chip where
  cores work. No per-cluster reset-vector / cpu_start / RVBAR / "secondaries may
  start" MMIO store exists anywhere in the one-time init.
- **0a — hv route is expensive, not a port.** SPTM assumes it is top privilege:
  single unconditional `GENTER` to GL2, enables GXF for itself, never probes for
  or defers to a lower monitor (0 SMC, 0 HVC, never reads `ID_AA64MMFR2_EL1`).
  Hosting it as an m1n1 hv guest therefore needs BOTH (i) FEAT_NV2 present —
  still requires the live `ID_AA64MMFR2_EL1[27:24]` proxy read to confirm — AND
  (ii) m1n1 to trap-and-emulate Apple GXF (`GENTER`/`GEXIT` + the `s3_6_c15_*` GL
  registers), which FEAT_NV2 does not virtualize, plus a virtual-VHE EL2. That is
  a large emulation effort, not a modest port, and it is blocked until the NV
  read is non-zero.

### Consequence: the macOS trace is the wrong next move

Step 0 confirms there is no boot-path write to find, and the failure mode is
already characterized on hardware in `dumps/HANDOFF.md` + `CPU-START.md`. The
whole point of tracing macOS was to find the missing step; the notes already
localize it, so the hv trace (expensive per 0a) is not the next move.

- **Step 1 (replay in `smp.c`) has nothing to replay** — Step 0 produced zero
  candidates; per-core + init + iBoot code is identical to the working chip.
- **Hardware-tested failure mode (already known, not something a trace needs to
  discover):** a T6050 secondary releases, powers its PMGR domain fully ACTIVE
  (0x1f0, == running cpu0), holds the correct RVBAR (byte-identical to cpu0) —
  and never fetches its first instruction. Ruled out on hardware: RVBAR,
  firmware rev (mBoot-20457.41.3), SEV broadcast, cpm-impl writes (SError).
- **Where the missing step actually lives (HANDOFF.md "boundary", ranked #1):**
  on a real boot, XNU's **ApplePMGR** starts cpus 1–17 through the **PMP
  coprocessor** (`/arm-io/pmp0`, an ASC/RTKit coprocessor with a shared-memory
  "dashboard" + nub messaging) — a dashboard write or RTKit message, not an MMIO
  poke. `SPTM-t6050 does NOT start cores` (zero start-block constants; it only
  registers CPUs / checks CTRR). This is why Step 0 found nothing in SPTM/iBoot,
  and why the BootKC/SPTM-adoption route (BOOTKC.md) came up empty.

### Redirect: decode the PMP core-start protocol (desk RE, then one Mac test)

Cheaper and more concrete than the trace, and it needs no hv port:
1. Decode ApplePMGR's PMP core-start path in the kernelcache (already partly
   mapped: `FUN_…098428a4` init, `_pmpWriteDashBoardSetDeviceState`, the
   dashboard address/entry format, the nub message format). Desk RE, no Mac.
2. Implement it in m1n1 as an RTKit client (pattern: `src/asc.c`/`src/rtkit.c`)
   or a dashboard RAM write, plus the one-line dense-mask fix
   (`1 << index`, HANDOFF.md).
3. One Mac test: release cpu1, expect a fetch (crumb stub / `smp_is_alive`).

The macOS hv trace (Steps 1–2 above) drops to a fallback — only if the PMP
protocol cannot be recovered from the kernelcache.

## Step 1 — Replay on the Mac (cheap, no hv)

- Add the Step 0 candidate writes to `src/smp.c` before the existing T6050
  start sequence. Boot single-core, try to start a second core.
- Done = the second core checks into the spin table (fixed), or the list is
  narrowed to what still fails.
- This may make Step 2+ unnecessary.

## Step 2+ — Port the hv to trace macOS (only if Step 1 fails and 0a is feasible)

- Teach the hv SPTM, by the sub-approach 0a picked (emulate, or demote to GL1).
- Boot the Mac's own macOS as the guest; arm traps on the per-core start MMIO
  and the SPTM entry points; log the cold second-core bring-up.
- Diff that log against m1n1's own start attempt.
- Done = the delta write(s) — the state we then replay from `smp.c`.

## Constraints

- Steps 1–2 need the Mac; the proxy is shared with the sibling sessions. Ed
  coordinates Mac time; this session will not message the siblings.
- Step 0 needs no Mac — all desk RE on iBoot/SPTM binaries in `j714c/firmware/`.
- The hv route is new work (0 upstream SPTM hv commits); its size is unknown
  until 0a.
