# Ride-XNU: start T6050 secondaries by riding Apple's blessed XNU, then hand to Linux

The committed SPTM path (why: kernel/BOOTKC.md — resident-SPTM-call is gated behind
the adopted-OS phase; the SPTM per-core code is identical to T8142 where cores work,
so riding real XNU gets the T6050-specific per-core enable "for free"). Boot the
real, SPTM-adopted XNU kernelcache with a binary-patched detour in its BootKC-rx
span; XNU brings up all 18 cores; our shim then hands control to Linux with the
cores running.

## Injection — scoped (2026-10-29), desk-confirmed

- **Adoption gate (iBoot):** `0x28550 ldr x8,[x19,#0x38]; 0x28554 cbz x8` — a
  kernelcache with `bx_size != 0` (a real `__TEXT_BOOT_EXEC`) routes to the SPTM
  adoption/layout path; else the non-adopted path. No signature gate before that
  (BOOTKC.md L2). A detour patched inside a VALID BootKC executes (HW-proven on
  T8142: entry-nop boots, entry-brk hangs); a `--raw` blob is refused.
- **Target segment:** `__TEXT_BOOT_EXEC` = VM `0xfffffe000c424000`, size `0x8000`,
  fileoff `0x05420000` (entry point at its base).
- **Code cave (for the shim):** free zero tail of **`0x1514` bytes at VM
  `0xfffffe000c42aaec`** (fileoff `0x05426aec`). Enough for the shim.
- **Detour point:** patch an early, reliably-executed domain-1 (BootKC-rx) XNU
  function to branch into the cave. antiapplefox used `IOPlatformExpert::start`
  (T8142). Exact T6050 address: TO FIND (not symbolized in ghidra_out; search the
  prelink/__TEXT_EXEC for the method). The detour must land in domain 1 — only
  BootKC-rx code runs as a non-SPTM/TXM domain (BOOTKC.md: EXEC_MODE region-derived).
- **kext route is out:** `kmutil create` (synthetic-KDK, `-x` kernel-only) builds a
  canonical BootKC but CANNOT link real kexts. So the shim is a binary patch + cave,
  not a kext.

## Packaging + install (Mac-side; needs Ed)

- Build the patched KC: `kmutil create` via the synthetic-KDK / `-R` shadow-root
  trick (antiapplefox build-bootkc-kmutil.sh) to get a genuine BootKC, then apply
  the binary detour + cave shim.
- Install to the **coih (CustomOS)** boot-object slot; boot under a **Permissive
  LocalPolicy with SIP off** (1TR/Recovery). THIS CHANGES ED'S MAC BOOT STATE —
  Ed's explicit action and approval required (boot policy + SIP). Do not attempt
  from this session.
- Verify with `kmutil inspect --show-mach-boot-properties` and `/chosen`
  `BootKC-bx/-rx/-ro` on boot.

## The shim + handoff — the open frontier (F1, nobody has done it)

After the detour fires, the shim runs in domain 1 while XNU boots. It must:
1. Let XNU complete SMP bring-up so all 18 cores are started (XNU `cpu_start()` =
   `0xfffffe000bc34c18` per core; the "all up" point is after the SMP loop — hook
   or spin on the per-CPU up-count).
2. Hand off to Linux/m1n1 KEEPING the cores running — the untested part. Design
   options (H1/H2, BOOTKC.md F1): quiesce XNU and jump each core to an m1n1 spin
   vector; or stage m1n1 in RAM and have the shim relocate+enter it with the cores
   parked in a controlled spin. Needs the per-core state XNU leaves (CTXR/guarded)
   to remain valid for the Linux entry.

## Build order

1. (desk) Find `IOPlatformExpert::start` (or an equivalent early domain-1 fn) in the
   kernelcache = the detour patch point.
2. (desk) Design the cave shim: SMP-complete detection + the handoff (H1/H2).
3. (desk) Write the patcher (detour + shim into the KC) + the kmutil-create packaging.
4. (Mac, Ed) Install to coih under Permissive/SIP-off; boot; confirm the detour
   executes (nop-boots / brk-hangs) and XNU starts all cores.
5. (Mac) Exercise the handoff; iterate.

## Honest status

Injection is scoped and desk-confirmable; the handoff (step F1) is the genuine
unsolved frontier (untested by anyone, incl. upstream). Installing the patched KC
changes Ed's Mac boot policy (Permissive/SIP) — his call and his hands.

## Step 1 DONE (2026-10-29): detour point pinned

- Detour point: `IOPlatformExpert::start` = VM **0xfffffe000c3018e8** (file 0x52fd8e8),
  in __TEXT_EXEC. From the kernel fileset symtab (`__ZN16IOPlatformExpert5startEP9IOService`).
  Prologue: `pacibsp; sub sp,#0x50; stp ...` (clean function start). AppleARMPE (the
  concrete PE) calls into it via super::start, so it is reliably executed.
- Detour instruction: overwrite the leading `pacibsp` at 0x52fd8e8 with
  `b 0xfffffe000c42aaec` (the BootKC-rx cave) = **0x1404a481** (delta 0x129204, in
  ARM64 b range). Shim re-executes `pacibsp` then branches back to 0xfffffe000c3018ec.
- Timing note for step 2: IOPlatformExpert::start is IOKit-init time. Secondary CPUs
  are started by the AppleARMCPU drivers around/after this, so the shim should
  SPIN-WAIT on the per-CPU up-count (or re-hook a later point) before handing off,
  rather than assume all cores are up the instant it fires.

## Step 2 RESULT (2026-10-29): ride-XNU REFUTED — starts cores, cannot run Linux on them

SMP signal (S1, found): shim detects all-cores-up via u32 counter 0xfffffe000c9d9b04
== ncpus 0xfffffe0007e81794 (live, ~18), confirmed by per-core online array
0xfffffe000c9f8008[idx]==2. Timing caveat: at the IOPlatformExpert::start detour
only the boot CPU is up; XNU starts the other 17 later (AppleARMCPU/IOKit), so the
shim must let XNU keep driving the boot CPU, not freeze it. (All moot — see below.)

THE CRUX (S2, verifier-confirmed, high confidence): a T6050 core fetches only from a
physical frame whose SPTM frame-type is EL1-executable. Frame-type is changed ONLY
by sptm_retype (SPTM 0xf4bb0; "update PAPT permissions outside of a retype()" panic
confirms it is the sole execute-permission changer). sptm_retype gates:
- owner-domain check (0xf4cac): the calling domain (percpu[0xb00]) must already own
  the frame's current type, else hard VIOLATION panic (0xf5474, noreturn).
- transition bitmap (descriptor+0x40): whitelists current->new type transitions.
The EL1-executable kernel-code types SPTM_CODE(4)/SPTM_TXM_CODE(5)/SPTM_XNU_CODE(6)
are all owner DOMAIN 0 (SPTM) and reachable ONLY from UNTYPED(0); UNTYPED is
reachable only from UNTYPED -> reset-only. So kernel-code frames are minted SOLELY
in the SPTM bootstrap window that validates the SIGNED XNU image. SPTM_XNU_CODE(6)
has an empty (terminal) transition bitmap, so even the signed kernel text can't be
repurposed. From the XNU domain (where the shim runs = domain 1) reverse-reachable
types are XNU_USER_EXEC/DEBUG/JIT (EL0 user code only), page tables, IOMMU — NEVER
an EL1-code type, NEVER UNTYPED.

Therefore: the adopted-XNU shim can make a region EL0-executable at most (useless for
a kernel), and Linux/m1n1's RAM region can NEVER be made EL1-fetchable at runtime.
- H1 (repoint running cores to m1n1): prefetch abort the instant a core branches into
  m1n1's non-executable frame. Dead.
- H2 (retype m1n1's region to SPTM_XNU_CODE): the retype call panics (domain 1 cannot
  retype to a domain-0 type). Dead.

VERDICT: ride-XNU can START all 18 cores (under XNU) but cannot RUN Linux on them.
Steps 3-4 (build/install the patched BootKC) are moot — a booted ride-XNU could not
hand the cores to Linux. The SPTM cryptographically binds EL1 code execution to the
Apple-signed kernel image via sptm_retype's domain/transition rules; there is no
runtime path to grant it to non-Apple code from any loader-reachable context.

## Bottom line for T6050 secondary cores

Not fixable loader-side. The block is the SPTM frame-type/execute model, now
understood at the binary level (sptm_retype gates), not merely "nobody has done it":
running Linux code at EL1 on a secondary requires an SPTM-minted, signed-image code
frame, which only Apple's bootstrap produces. Remaining theoretical routes all need
something we cannot supply: Apple signing a third-party kernel, an Image4/coreTrust
(TXM) signing break, or Apple changing the SPTM. Single-core is the practical ceiling
for Linux on T6050 until one of those changes. This is the evidence-backed form of
"wait for Apple."
