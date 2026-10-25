# Starting the secondary cores (J714c / T6050)

## The PMP is not on this path

The boot CPU is cpu0, in cluster 0. cpu1-cpu5 are in that same cluster 0 and
do not start. Since cpu0 runs, cluster 0's power and fabric are fully up. So
what blocks cpu1-5 is not cluster or device power - which is the PMP's job -
it is a per-core release step. The PMP handshake we chased does not gate core
start.

macOS confirms this: cores are started by `ApplePMGR::enableCPUCore(core)`
(kernelcache mac17j), which writes PMGR/ACC registers directly. It does not go
through the PMP coprocessor at all. The PMP coprocessor does DVFS, thermal and
peripheral device power states.

## Why the 12 earlier experiments failed

They used the PMGR held-mask + per-cluster trigger (pmgr reg[0] + 0x88000).
That path brings the per-core PMGR power domain to ACTIVE (0x1f0, matching
cpu0) - it powers the core. The core then never fetches at RVBAR. Powering a
core is not the same as releasing it; the release is a separate ACC register
write the experiments never did.

## The mechanism that should work: the ACC core-enable, as on T8152

The omacom m1n1 fork already starts all 12 cores on the M6 Mac mini (T8152)
with `smp_start_t8152` using the ACC block, not the held-mask:

    cpu_start_base = acc_base + 0x4000;
    set32(cpu_start_base + 4, BIT(cpu_index));        // setCoreOnline
    set32(cpu_start_base + 8 + 4*cluster, BIT(core)); // wakeCore
    dsb; sev;

T8152 has one ACC block at 0x300730000. T6050 has one ACC block per cluster,
from the cpu nodes' `acc-impl-reg`:

| cluster | type | acc-impl base | cpm-impl base |
|---|---|---|---|
| 0 | M | 0x210f00000 | 0x210e40000 |
| 1 | M | 0x211f00000 | 0x211e40000 |
| 2 | P | 0x212f00000 | 0x212e40000 |

## Proposed experiment

Add a T6050 path to the fork's `smp.c` mirroring `smp_start_t8152`, but writing
the online/wake bits into the target core's own cluster ACC block (above)
instead of one global block, keeping the dense per-core held-mask release that
already works, then dsb + sev. Build, chainload, boot, and check
`smp_start_secondaries`.

Open item: the exact offset/bit within the T6050 ACC block. First try the
T8152 layout (base + 0x4000, +4 online, +8+4*cluster wake). If that faults or
does nothing, pin it from `ApplePMGR::enableCPUCore` (it calls a method at the
ApplePMGR object +0xa88 with the core bitmask; resolving that reaches the exact
register) - offline work, no hardware.

Caution from the notes: writes to `cpu-impl-reg` and `cpm-impl-reg` took an
SError in earlier runs. The ACC block (`acc-impl-reg`) is a different block and
has not been written yet.

## Tested on hardware (2026-10-23) + Aura source review

Correction to an earlier conclusion in this file: the ACC register I probed
(acc-impl-reg, 0x210f00000) SErrors from EL2, but that is a side/debug block,
not the core-start path. Core start on M5 does NOT go through it, so there is
no proven SPTM wall for starting a core. The start path is EL2-accessible.

What Aura and the m1n1 fork actually use for M5 core start (src/smp.c):

- One PMGR register block: `cpu_start_base = pmgr_reg[0] + off`. T8142 uses
  off 0x34000; T6050 uses off 0x88000 (CPU_START_OFF_T6031). pmgr_reg[0] is
  0x280600000, so the T6050 block is 0x280688000 - exactly what the 12 earlier
  experiments wrote.
- Release per core: `write32(base+0x4, start_bit); write32(base+0x8+4*cluster,
  1<<core)`, then WFE/SEV dispatch. All EL2-accessible.
- Aura's T6050 path adds nothing guarded: no GXF, and it writes the reset
  vector (which "also clears RVBAR_LOCK") only `if apple_sysregs_unlocked`,
  which is skipped when the sysregs are locked (as on T6050, where impl-reg
  writes SError).

So Aura hands us the same mechanism we already tried, not a working recipe.
Per discussion 142, no T6050 board has a published hardware core-start result,
Aura included; their T6050 smp path is present but unproven on hardware.

The real open question is unchanged and is not answered by Aura: on T6050 the
PMGR mask powers the core (domain ACTIVE, matching cpu0) but it never fetches
at RVBAR, while the identical mechanism starts all cores on T8142. The
differences worth testing next, all EL2-level:

1. The per-core RVBAR_LOCK bit is set on T6050 secondaries. T8142, via
   `apple_sysregs_unlocked`, clears it by writing the reset vector; T6050
   cannot write impl-reg from EL2 (SError). Whether the lock must be cleared
   for the reset fetch, and how macOS does it on T6050, is the key unknown.
2. The start-bit formula: dense BIT(index) (omacom fork, and the experiments)
   vs BIT(4*cluster+core) (Aura) - but 6-core clusters make the cluster form
   wrong, and the dense form already brought the domain ACTIVE.
3. WFE pre-arm + SEV ordering and the reset-stack handoff.

Honest status: starting a T6050 secondary from m1n1 is unsolved publicly. This
is experimental work, not a port of known-good code.

## SPTM owns the per-core reset registers (2026-10-23)

The SPTM binary (sptm.t6050.release.bin) references `cpu-impl-reg` and carries
the CPU page-table retype/bootstrap machinery ("Bootstrapping XNU..."). The
per-core impl registers (RVBAR / reset-vector, the lock) SError when touched
from EL2. Together: on T6050 these registers are owned by the SPTM, and are
programmed through SPTM-mediated access, not raw EL2 writes.

That is the wall, and it is architectural, not a missing offset. To start a
secondary, its reset vector/lock must be set via the SPTM. Plain m1n1 runs at
EL2 and has no SPTM-mediated path, so it cannot. This is exactly the capability
Aurora's "Aura" monitor adds over m1n1.

### Strategic options (this is a decision, not a missing fact)

1. Accept one core now; build NVMe + the standard boot chain + install, for a
   usable single-core Omarchy. Real progress toward a booting system.
2. Add SPTM-mediated core start to m1n1 - large, experimental, and essentially
   re-does what Aura already has. This is where Aurora's own T6050 work sits.
3. Switch the loader to Aura (the monitor) instead of plain m1n1, inheriting
   its SPTM groundwork, and pursue cores there.

Recommendation: option 1 for a usable system now; cores ride on the
SPTM-mediation work, which realistically comes from or with Aurora.

## Definitive: m1n1 has no guarded mode on M5 (2026-10-23, on hardware)

Read on the boot CPU over the proxy:
- AIDR_EL1 = 0x1a80000023. The GXF support bit (BIT 16) is CLEAR.
- SPRR_CONFIG_EL1 = 0, GXF_CONFIG_EL1 = 0, GXF_STATUS_EL1 = 0.

So `supports_gxf()` is false on T6050, and m1n1 never enables guarded mode.
The old M1/M2 GXF-at-EL2 mechanism is gone on M3+; guarded mode (GL2) belongs
to the SPTM. m1n1 at EL2 therefore cannot enter GL to reach the per-core reset
registers, and writing them from EL2 SErrors.

Conclusion (firm): the only way to program a secondary's reset vector / release
it on T6050 is to call the SPTM. m1n1 has no SPTM-call path; Aurora's Aura
monitor is built to mediate to the SPTM, which is why it can. The road to
multiple cores from this loader is to add an SPTM CPU-start call to the loader.
This is substantial: the SPTM dispatch ABI, the CPU-start selector and its
argument structures, and getting the SPTM to accept the call from a non-XNU
caller. No public loader has this for T6050.

Next: map the SPTM CPU-start call (sptm.t6050.release.bin + how XNU invokes it).

## The SPTM validates its caller as XNU (2026-10-23)

The SPTM binary's dispatch layer (`dispatch.c`, `dispatch_cmd_call_from_xnu_handler`,
`DISPATCH_ID_SPTM_CORE`, `dispatch_state_machine`, hop tracking "XNU->TXM")
shows the SPTM is entered by dispatch commands and tracks an execution-mode
state machine, validating that the caller is XNU in the expected state. So a
loader cannot just find a "start CPU" selector and call it: it must hold the
SPTM's expected XNU-side state. That is why starting cores on M5 needs a full
monitor that mediates to the SPTM (Aura), not a register poke or a lone call.

## Bottom line for multiple cores on M5

Proven, in order:
1. Core start = per-core reset registers (not the PMP, not the pmgr power mask
   alone, which only powers the core).
2. Those registers SError from EL2.
3. m1n1 has no guarded mode on M5 (AIDR GXF bit clear).
4. Only the SPTM can program them, and it admits only XNU-state callers.

So multiple cores on M5 require SPTM mediation in the loader - an Aura-class
monitor. No public loader has this for T6050; Aurora is building exactly it and
has not finished it publicly. The two real routes to cores:
- Build SPTM mediation into the loader (major; matches Aura).
- Ride Aurora's T6050 work (Aura + their kernel) as it lands.

Plain m1n1 as it stands cannot start the secondaries, and no amount of
register-level experimentation changes that; the gate is the SPTM.

## RESOLVED EXTERNALLY (2026-10-23): it's a known Apple firmware bug on T6050

GitHub research found this is a known, Apple-reported firmware issue specific to
T6050/T6051 (M5 Pro/Max), not a bootloader problem, and not currently fixable
from any loader. Multiple independent efforts hit the exact symptom we did
(core powers up in PMGR, never fetches):

- Asahi m1n1 PR #610 (yuyuyureka, MERGED 2026-06-29), "Initial support for
  T6050/T6051": "smp secondaries startup is not functional: the cores turn on
  (as can be seen in pmgr), but never start executing our code. Tested on
  macOS 26.2b2 and 27.0b2."
- Gravity Linux FAQ: as of macOS 27.0 Beta 5 the M5 Pro/Max are "misconfigured
  out of the box and we are unable to start secondary CPU cores"; reported to
  Apple, "no choice but to wait for Apple."
- rolotrealanis98/m5pro-linux (J716s, T6050) docs/smp-t6050-raw-path.md: same
  symptom, reverse-engineered macOS's own path and found it does nothing more
  than m1n1 - AppleARMCPU::startCPU -> ApplePMGRFunctionEnableCPUCore ->
  configMiscCores(mask,true) = the same two PMGR writes (CPU_START+0x4,
  +0x8+4*cluster) via writeACCReg32 that we do. Mach-O/BootKC packaging to get
  SPTM loaded was refused by kmutil.
- betim-hodza/omarchy-m5, antiapplefox/m5-linux: same chip, same wall.
- Base M5 (T8142) and M4/M4 Pro start secondaries fine; T6050/T6051 is the one
  blocked generation.

### This corrects the SPTM-wall conclusion above

The RE shows macOS starts a core with the SAME EL2 PMGR writes m1n1 uses. So it
is NOT a privilege/SPTM-mediation wall and NOT the PMP. The core simply does not
fetch after a correct release - an Apple firmware misconfiguration on T6050/T6051.
Nobody (Asahi, Gravity, Aurora, these independents) can start these cores from
the loader today; it waits on Apple. Re-test after each macOS update by reading
/chosen/system-firmware-version then releasing a core and watching for a crumb.

## Driver trace of the core-start write (2026-10-23, Opus): structure confirmed, aperture not yet pinned

Traced macOS `ApplePMGR::configMiscCores` (the function AppleARMCPU::startCPU
reaches through function-enable_core). The two writes, confirmed instruction by
instruction:

- x23 = this + 0x5e10, a register descriptor: {enabled flag @ +0, regmap
  selector @ +4, base offset @ +8}.
- Write 1 (die/complex bits): writeReg(regmap=[x23+4], offset=[x23+8]+0x4, value=die_bits)
- Write 2 (per-core bits):   writeReg(regmap=[x23+4], offset=[x23+8]+0x8+4*cluster, value=core_bits)

Both go through the object's low-level writer at this+0x1060. This independently
confirms the independent M5 Pro bring-up's structural claim: CPU_START+0x4 for
die bits, +0x8+4*cluster for core bits.

What is NOT yet pinned: the regmap selector [this+0x5e14] and the base offset
[this+0x5e18] are runtime fields set during AppleT6050PMGR init, not immediates.
So the absolute address (whether it is pmgr+0x88000 = 0x280688000 that m1n1 uses,
or the per-cluster ACC space) is not determined from this function alone.

Related finding: AppleT6050PMGR::writeACCReg32 resolves ACC register ids through
a mapping table (kernelcache @ 0xfffffe00082c44e0, 3 per-complex structs) whose
offsets land in the PER-CLUSTER ACC space, verified against known addresses:
0x210150000 = cpu1 cpu-impl, 0x210e40000 = cpm-impl, 0x210f00000 = acc-impl,
with complexes 1/2 at 0x211000000 / 0x212000000. But configMiscCores calls the
low-level writer DIRECTLY with its own regmap, not through writeACCReg32's
mapping, so this does not by itself prove the core-start write lands in the ACC
space. It is a strong hint, not proof.

Next to pin it to the byte: trace AppleT6050PMGR init where the this+0x5e10
descriptor is populated (regmap selector + base offset), and the regmap->aperture
table the low-level writer (this+0x1060) uses. That resolves the absolute
address and settles pmgr+0x88000 vs ACC space.

## Driver trace conclusion (2026-10-23, Opus)

After tracing configMiscCores -> writeReg and the init path (initRegMaps /
initRegGroups), the descriptor that holds the core-start register (this+0x5e10:
regmap selector + base offset) is built at init from a static register table
through several pointer-authenticated indirection layers. I did not extract the
absolute address as a static immediate; it resolves at runtime.

What the trace DID settle:
- The write structure matches macOS exactly: CPU_START+0x4 (die/complex bits),
  CPU_START+0x8+4*cluster (per-core bits). Independent confirmation of the M5
  Pro bring-up's claim.
- The behavioral evidence is the strongest single signal and points firmly at
  the register being correct: m1n1's write to pmgr[0]+0x88000 produces the EXACT
  observable effect macOS produces - the core's power state goes 0x100->0x1f0
  and its impl-status register goes ...d800 -> ...d102 (the running pattern). A
  different register would not reproduce that identical transition.

Correction to an earlier note in this file: the ACC mapping table
(writeACCReg32 -> per-cluster 0x21X space) is a SEPARATE register path (the ACC
impl / perf / DVFS registers), not the core-start write. It was a real lead to
check but it is not where configMiscCores writes the start bits. I over-stated
it earlier; the core-start write is the pmgr register m1n1 already uses.

Bottom line: the register m1n1 uses for T6050 core start is almost certainly
correct (structure matches macOS; the write reproduces macOS's exact effect on
the core). So the M6 "wrong register" hypothesis does not hold for the M5 Max.
The core is started correctly and still never fetches - downstream of a correct
write, which is the firmware behavior Asahi (PR #610), Gravity Linux, and the
M5 Pro bring-up all report. The decisive outstanding question remains the one
for the M6 implementer: did his M6 cores ever sit powered-but-not-fetching, or
run immediately on the correct write.

## Firmware re-test on mBoot-20457.41.3 (2026-10-25): no change; RVBAR ruled out

Updated firmware from mBoot-20457.1.29 to mBoot-20457.41.3. Symptom unchanged:
secondaries power up, no fetch. Read RVBAR (cpu-impl-reg +0) on all cores:

  cpu0 (running): addr 0x100056cc000 lock=1 high=0x10
  cpu1 (waiting): addr 0x100056cc000 lock=1 high=0x10   <- identical to cpu0
  cpu2 (waiting): addr 0x100056cc000 lock=1 high=0x10
  cpu6 (waiting): addr 0x100056cc000 lock=1 high=0x110  (cluster 1)
  cpu12(waiting): addr 0x100056cc000 lock=1 high=0x210  (cluster 2)

All point at m1n1's vector base (m1n1 base 0x100056cc000). cpu0 and cpu1 are
byte-identical and cpu0 runs, so RVBAR is definitively NOT the gate.

Conclusion: the gate is per-core execute permission (the ACC-CTXR execute-region
registers the SPTM manages). iBoot sets them for the boot core; the raw m1n1
boot never sets them for the secondaries, so a secondary holds the correct
reset vector and still refuses to fetch. Not firmware-fixable; next is to locate
the ACC-CTXR registers, read cpu0's values, and test whether m1n1 can set a
secondary's to match before release.

## Full mechanism + the only lever (2026-10-25, with antiapplefox SPTM map)

Combining today's hardware facts with the two public M5 efforts, the chain is
now mapped end to end:

raw m1n1 image -> iBoot does NOT register it with the SPTM (raw image, not an
SPTM-aware kernel collection) -> SPTM never runs its per-core execute-permission
setup for the secondaries -> secondary powers up, holds correct RVBAR, refuses
to fetch. Boot core works because iBoot/SPTM set it up.

Confirmed ruled out: firmware (mBoot-20457.41.3, no change) and RVBAR (identical
across running/stuck cores).

The only lever = the boot image:
- m1n1 must be packaged as an SPTM-aware BootKC: kc_layout present==1 and
  bx_size != 0 (a declared executable segment). Then iBoot registers it with
  the SPTM.
- m1n1 then issues the SPTM boot-handoff: subsys 0, idx 0xf = `mov x16,#0xf`
  then GENTER. (antiapplefox mapped 148 SPTM calls from the M4 kernelcache;
  there is NO named cpu_start/resume/ctxr selector - core prep rides on the
  boot handoff + the SPTM's own per-core init.)

Open gates (both unsolved publicly, static-only, no hardware success):
1. Apple's kmutil refuses a non-Apple BootKC (rolotrealanis hit this).
2. A non-XNU caller getting past iBoot's `uses_sptm` assertion (fatal halt at
   0x1223a4 for a non-SPTM-aware kernel) and the SPTM handoff. antiapplefox has
   a draft shim (patch 0004) but it "does not yet boot Linux."

SPTM is shared source 611.120.6 across M3/M4/M5; call tables above are from the
M4 kernelcache and must be re-anchored per binary for T6050. m1n1 smp.h MAX_CPUS
is 24; M5 Pro/Max 18-core is fine, but note it for larger configs.

Bottom line: secondary cores on T6050 are reachable only by making m1n1 an
SPTM-registered BootKC and completing the SPTM handoff - genuine unfinished RE
that antiapplefox/m5-linux and rolotrealanis98/m5pro-linux are closest to.

## BootKC route: toolkit gathered, installation is the first wall (2026-10-25)

antiapplefox/m5-linux provides a near-complete draft toolkit (copies in
scratchpad/bootkc/):
- scripts/pack-bootkc.py: m1n1.macho -> SPTM-aware BootKC. Renames segments to
  Apple names (TEXT->__TEXT_EXEC = the executable region the SPTM locks,
  RODA->__DATA_CONST, DATA->__DATA, _HDR->__TEXT), zeros PYLD, sets
  LC_UNIXTHREAD.pc to __TEXT_EXEC start, adds LC_UUID, LC_BUILD_VERSION,
  __DATA_SPTM (0x54000 RW, file-empty), empty LC_DYLD_CHAINED_FIXUPS,
  LC_FILESET_ENTRY. Structural confidence HIGH, completeness MEDIUM.
- m1n1-patches/0004: adds `sptm_call` (bare `genter`, encoding 0x00201420,
  reusing gxf) + `sptm_boot_handoff()` issuing SPTM call (0x0:0xf) in main.c's
  next-stage handoff. DRAFT, does not boot Linux. 3 open questions: SPTM
  pre-state (MMU on/off vs mmu_shutdown ordering), non-XNU caller permission,
  whether earlier SPTM calls are required.
- m1n1-patches/0001-0003: M4/M5 chip IDs, MIDR part IDs, chicken stubs.
- linux-sptm/: Linux-side SPTM driver (sptm.c/.h).

Build+pack chain (ready, mechanical): apply 0001-0004 to m1n1 -> build
m1n1.macho -> pack-bootkc.py -> m1n1.bootkc.macho.

FIRST WALL = installation. There is no supported way to install a BootKC as the
boot object: `kmutil configure-boot` on macOS 27.x takes only `--raw` (raw
image = no SPTM registration), and rolotrealanis confirmed kmutil refuses a
BootKC/Mach-O. Everything downstream (iBoot acceptance, SPTM activation, the
handoff, core prep) is untestable until a BootKC can be installed.

Next target: the only unexplored install path - replace the stub's own
kernelcache and boot the stub's normal (non---raw) path under its permissive
policy, to see if iBoot accepts an unsigned BootKC there. Unexplored publicly;
this is the thing that would move the route.

## Install path investigation (2026-10-25): verdict

Researched the Apple Silicon boot-policy install path. Findings:

- There are two boot-object slots in the LocalPolicy: CustomOS (coih = CustomOS
  Image4 hash, set by `kmutil configure-boot`) and the OS kernelcache (nsih).
  m1n1 today is a CustomOS (coih): iBoot loads+starts it ahead of the OS; it is
  NOT registered with the resident SPTM. That is why secondaries get no SPTM
  per-core prep.
- `kmutil configure-boot -c <KC>` DOES take a kernel collection, not only raw.
  The 2021 custom-XNU guide installs a full `kmutil create` KC this way:
  `kmutil configure-boot -v /Volumes/Macintosh HD -c BUILD/OpenSource.kc`,
  from Recovery, Permissive Security + SIP off. So a BootKC-shaped image is the
  correct thing to feed it. The `--raw`-only limit is the flag, not the tool.
- rolotrealanis's BootKC was refused by kmutil but the EXACT ERROR was never
  recorded ("error text to be added"). So we don't know if it's a fixable
  format issue or a hard validation. That missing error gates the route.

Whether iBoot registers a CustomOS KC with SPTM depends on the image being a
valid BootKC (kc_layout present, bx_size != 0 = real __TEXT_BOOT_EXEC), per
antiapplefox. Plausible, unverified.

Concrete next experiments (both need the Mac in Recovery, Permissive + SIP off):
1. Pack m1n1 as a BootKC, run `kmutil configure-boot -c m1n1.bootkc.macho
   -v /Volumes/<stub>`, and CAPTURE THE EXACT ERROR. That decides fix-packer vs
   change-approach.
2. Try `kmutil create` with m1n1 as the -k kernel to get an Apple-tool-built KC
   that passes kmutil's own validation.

Make-or-break unknowns, in order: (a) kmutil accepts the KC; (b) iBoot loads
SPTM for a CustomOS KC; (c) the SPTM handoff from a non-XNU image works. Each
needs a hardware step; (a)'s error is the cheap decisive first datum.
