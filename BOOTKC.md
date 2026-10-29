# Secondary cores via an SPTM-registered BootKC (J714c / T6050)

Goal: start the other 17 CPU cores. Per [CPU-START.md](CPU-START.md), a raw m1n1
boots as a CustomOS that iBoot does NOT register with the SPTM, so the SPTM never
runs its per-core execute-permission setup for the secondaries; they power up,
hold the correct reset vector, and never fetch. The only lever is the boot image:
make m1n1 an SPTM-registered BootKC. This file drives that.

Status: offline RE. One hardware gate (macOS Recovery, Permissive + SIP off) for
the decisive install test. Publicly unsolved on T6050.

## Assets in hand (more than the public efforts had for T6050)

- `j714c/firmware/iBoot.j714c.RELEASE.bin` — **decrypted**, this machine's iBoot
  (`mBoot-20457.1.29`). Carries the validator and SPTM strings:
  `Kernelcache too large`, `Kernelcache image not valid`, `kc_layout`,
  `uses_sptm`, `BootKC`, `BootKC-ro/-rs/-rx/-bx/-rw`, `coih`, `nsih`,
  `boot-object`, `raw`. So the iBoot side (walls 2-3) is analyzable offline on the
  exact firmware. Public M5 efforts used iBoot from other machines.
- `j714c/firmware/kernelcache.mac17j.bin` — the real T6050 BootKC (the exact
  structural target). Map below.
- `j714c/firmware/sptm.t6050.release.bin`, `txm.macosx.release.bin`.
- `forks/omacom-m1n1/build/m1n1.macho` — m1n1 (filetype MH_FILESET already).
- antiapplefox toolkit, preserved in scratchpad `bootkc/`: `pack-bootkc.py`,
  `0004-shim.patch` (adds `sptm_call` = bare `genter` + `sptm_boot_handoff`,
  SPTM call 0x0:0xf), `bootkc-packaging.md`.

## Real T6050 KC structure (the target), from kernelcache.mac17j.bin

filetype 12 (MH_FILESET), cputype 0x100000c (arm64e), cpusub 0xc0000002.
Load commands: UUID×1, BUILD_VERSION×1, UNIXTHREAD×1, DYLD_CHAINED_FIXUPS×1,
SEGMENT_64×9, FILESET_ENTRY×369. `LC_UNIXTHREAD pc = 0xfffffe000c424000`.

| segment          | initprot | vmsize    | role   | note |
|------------------|----------|-----------|--------|------|
| __TEXT           | r--      | 0x8000    | header | |
| __PRELINK_TEXT   | r--      | 0xda0000  | ro     | kext text |
| __DATA_CONST     | r--      | 0xcf8000  | ro     | |
| __DATA_SPTM      | r--      | 0x74000   | SPTM   | file-zero, runtime-filled |
| __TEXT_EXEC      | r-x      | 0x390c000 | rx     | main code |
| __TEXT_BOOT_EXEC | r-x      | 0x8000    | bx     | **entry point lands here** |
| __PRELINK_INFO   | rw-      | 0x3a4000  | info   | |
| __DATA           | rw-      | 0x4b4000  | rs/rw  | |
| __LINKEDIT       | r--      | 0x1958000 | le     | |

First fileset entries: `com.apple.kernel`, `com.apple.kec.Libm`, `...pthread`,
`...AFKHIDTBDevice`.

## Packer deltas (pack-bootkc.py vs the real KC)

- Entry point: the real KC's `LC_UNIXTHREAD pc` is the start of a separate
  `__TEXT_BOOT_EXEC` (r-x, 0x8000) at the top of the layout, not `__TEXT_EXEC`.
  The packer sets pc to `__TEXT_EXEC` start and creates no `__TEXT_BOOT_EXEC`.
  Fix: add a small `__TEXT_BOOT_EXEC` holding (or trampolining to) m1n1's reset
  vector and point pc there.
- `__DATA_SPTM`: real is 0x74000 and r-- (packer uses 0x54000, RW). Match 0x74000.
- Segment order/roles: match the table above.

## The decisive offline question

Does iBoot SPTM-register a **CustomOS** (coih slot, how m1n1 installs via
`kmutil configure-boot --raw`), or only the OS slot (nsih) / a `-c`-installed KC?
- If a CustomOS can be SPTM-registered by shaping the image (kc_layout present,
  valid BootKC roles), we **bypass kmutil** — we already install raw images, so a
  raw-but-BootKC-shaped m1n1 would get SPTM prep. This is the crack, if true.
- If SPTM registration is gated on the install slot/tool, we must get a KC past
  kmutil's `-c` validation (the recorded public wall), or use `kmutil create`.

Answer it by RE of iBoot.j714c: xrefs of `uses_sptm` / `kc_layout` / `BootKC*` /
`coih` / `nsih`, and the branch that decides SPTM registration. Needs the iBoot
load base first (not in the header; derive from code pointers / ADRP+ADD solving).

## Walls, in order

1. Install: kmutil accepts a hand-packed BootKC via `-c` (public wall, exact
   error never recorded) OR `kmutil create` with m1n1 as `-k` OR bypass via a raw
   CustomOS if iBoot allows (the decisive question above).
2. iBoot accepts the KC (not "image not valid") and registers it with SPTM
   (`uses_sptm`/`kc_layout`, BootKC role mapping).
3. SPTM handoff from a non-XNU caller: the `sptm_boot_handoff` (call 0x0:0xf)
   and getting past the SPTM's XNU-state validation (CPU-START.md: SPTM tracks an
   XNU execution-mode state machine). antiapplefox patch 0004 is a draft that
   "does not yet boot Linux".

## Hardware gate (Ed, macOS Recovery, Permissive security + SIP off)

The decisive datum is cheap: pack m1n1 as a BootKC, run
`kmutil configure-boot -c m1n1.bootkc.macho -v /Volumes/<stub>`, and CAPTURE THE
EXACT ERROR (or success). That decides fix-packer vs change-approach. Coordinate:
this reboots the Mac, so it collides with the GPU/USB sessions' hardware use.

## Next offline steps

1. Derive the iBoot load base; RE the uses_sptm/kc_layout/coih-nsih/BootKC-role
   logic to answer the decisive question (can a raw CustomOS be SPTM-registered).
2. Fix pack-bootkc.py to match the real KC (entry in __TEXT_BOOT_EXEC, __DATA_SPTM
   0x74000/ro); confirm forks/omacom-m1n1 has the SPTM patches (0001-0004) or
   build a patched m1n1; produce m1n1.bootkc.macho.
3. Validate the packed KC against iBoot's static validator as far as possible.

## iBoot/SPTM binary RE (2026-10-29, workflow + adversarial verify)

What the iBoot/SPTM binaries gate on. NOTE: the first framing below ("route is
closed") is PARTLY SUPERSEDED by the hardware-verified prior art in "Corrected
synthesis" — read that section too. The open-ended "map the validator / enumerate
the dispatch table" RE agents were flagged by the cyber safeguard; the bounded,
hypothesis-driven adversarial verifiers ran and produced the L1-L3 evidence.

### L1 — a CustomOS is never SPTM-registered (bypass-kmutil is dead)

The kc_layout builder (the BootKC descriptor parser, iBoot `0x27830`; emits
"Kernelcache image not valid" via `0x27968`, Mach-O parse `bl 0x166044` at
`0x27960`) has EXACTLY ONE caller: `0x2464`. That call is reached only when
`boot_mode == 7`:
- `0x2368 bl 0x1bbdf0` (get boot_mode); `0x236c cmp w0,#7`; `0x2370 b.ne 0x2680`.
- mode-7 success path: `0x2470 ldrb [sp,#0x90]==1` (present), `0x247c ldr
  [sp,#0xc8]!=0` (bx_size, struct +0x38), then `0x24a0 bl 0x206568` = the SPTM
  object-layout/registration routine (derefs SPTM globals `0x39bd90`/`0x49bd90`).

`boot_mode` is NOT derived from the image. It is `byte[(*0x39bf60)+1]` (getter
`0x1bbdf0`), set by `set_boot_mode` (`0x1bbb24`, store `0x1bbb88`, sole caller
`0x1cfd68`) from `cboh->byte[0xc]` (`0x1cfd64`). `cboh` (magic `0x686f6263`,
validator `0x1b8398`) is a validated external boot-context blob; iBoot never
synthesizes the magic (all `0x686f6263` sites are compares, never stores).
The non-7 branch (`0x2680`) is the CustomOS/downgrade path — reads
`non-apple-or-untrusted-code` (`0x38fccb`), `security-downgradable` (`0x38fce7`),
`protected-data-access` (`0x38fcfd`) and loads the object WITHOUT calling the KC
parser. iBoot computes `is_custom = (boot_mode != 7)` at `0x30dbc-0x30de0`.

So this analysis concluded: coih/--raw CustomOS → non-7 → `0x2680` → kc_layout
NULL → uses_sptm false. [CONTESTED — a second iBoot agent found NO coih/nsih
discriminator in the SPTM decision (gate is purely `kc_layout->bx_size` at
`0x28554`) and a SECOND kc_layout loader on `boot_os`'s mode-1 path (`0x2800c`)
that a CustomOS can reach. The real question is what boot_mode a coih object
installed via `kmutil -c` (a Mach-O with a bx segment, NOT `--raw`) yields. See
"Corrected synthesis". What IS firm: a `--raw` opaque blob (today's m1n1) has no
bx segment → never SPTM-registered.]

### L3 — the SPTM only ever bootstraps XNU (fatal to a non-XNU BootKC)

`sptm.t6050.release.bin` has exactly ONE guest-start path, "Bootstrapping
XNU..." (str `0x2a3d`, logged `0xbc2ec`, final handoff `0xbc320`); no generic/
non-XNU payload path. The bootstrap (`~0xbae40-0xbc060`) resolves required region
symbols from a symbol table (`[0x98000+0x4d8]`) via `bl 0xb8940` (w1=1 = REQUIRED):
`slide, CL4-entry, CL4-rx/ro/rw/le, TXM-entry, TXM-ro, TXM-virt, BootKC-entry,
BootKC-ro, BootKC-virt` (name table `0x2894-0x2990`). A missing table or symbol
PANICS (`0xb8990 b.ne 0xb89e0` → "Error looking up ... '%s'" `0x2aaf/0x6496` →
`0x100400` → "SPTM PANIC:" `0x5ee9`, `wfe;b .` `0x1002d4` / `brk #1`, NORETURN).
It then bounds-checks XNU-internal structures — `xnu_el2_exception_vector`,
`xnu_exc_return_handler`, `xnu_ctrr_dispatch_table`, `xnu_ro_pagetables_begin`,
`xnu_ro_pagetables_end` — must all lie within the BootKC regions. Every failure
is a hard noreturn panic BEFORE control could reach the bx entry.

So per-core execute-permission setup is performed only as part of XNU bootstrap,
gated on XNU-specific symbols and structures m1n1 cannot provide. A non-XNU
BootKC panics the SPTM.

### L2 — no signature gate (medium), but moot

uses_sptm is layout-only (assert `0x3981bf` / `0x1bf710`); the SPTM-vs-opaque
decision in `load_kernelcache` (`0x28294`) is a parsed-structure byte flag
(`[x19][0]`, tested `0x28a2c/0x28acc/0x28b50/0x28c2c`), hard-coding the SPTM arg
`w12=1` at `0x28bb8`; the layout routine (`0x2c72c-0x2ca40`) is signature-free.
No signature gate blocks an unsigned BootKC before uses_sptm. Irrelevant given
L1 and L3.

## Corrected synthesis (2026-10-29, WF2 prior-art, hardware-verified)

The "route is closed" framing above is WRONG. The route is hard and unsolved for
T6050 secondaries, but it is OPEN. Sources: antiapplefox/m5-linux (HW-verified on
base M5 T8142), rolotrealanis98/m5pro-linux, Asahi/Gravity, + fresh RE of our own
sptm.t6050 / iBoot.j714c.

A. kmutil is NOT the wall (correction). `kmutil configure-boot -c <KC>` accepts a
   valid Mach-O BootKC and sets coih ("found valid Mach-O binary, deriving Mach-O
   boot properties"). It refuses only MALFORMED ones: `KMErrorDomain Code=71
   "Fileset Error: Invalid Mach-O boot properties"` (AsahiLinux/m1n1 #135) — which
   is why hand-packed m1n1 is refused (and pack-bootkc.py refuses its OWN output:
   __DATA_SPTM VMA-ordering vs place() appending — a dead end). `--raw` is only for
   non-Mach-O blobs. `kmutil create` can build a GENUINE canonical BootKC WITHOUT an
   Apple KDK, via a synthetic-KDK + `-R` shadow-root trick (antiapplefox
   build-bootkc-kmutil.sh), kernel-only (`-x`); linking real kexts fails. kmutil /
   bputil configure-boot are recoveryOS/1TR-only (SEP).

B. The SPTM-registration gate is image SHAPE = `kc_layout->bx_size != 0` (a real
   `__TEXT_BOOT_EXEC`), NOT the install slot. iBoot single branch `0x28554`
   `ldr x8,[x19,#0x38]; cbz x8`: bx_size!=0 → SPTM layout (`lay_out_sptm_objects
   0x2dce4`); ==0 → opaque (`0x2c72c`). No coih/nsih discriminator in the SPTM
   decision. OPEN: whether a coih object installed via `kmutil -c` (Mach-O with bx,
   not --raw) reaches a kc_layout loader — L1 says mode-7 only, the full-flow agent
   found a mode-1 (boot_os/CustomOS) kc_layout loader at `0x2800c`. Cheap decider:
   install such an object to coih, boot, read `/chosen` for `BootKC-bx/-rx/-ro`.

C. The SPTM does per-core setup ONLY for an SPTM-registered XNU image (L3 +
   dispatch, confirmed). A T6050 secondary gets CTXR execute permission only by
   coming out of reset INTO the SPTM per-core entry `0xab46c` in guarded mode,
   which happens only for a registered boot image. SPTM_CORE table (id 0) is the
   XNU-facing API; pinned on OUR binary: REGISTER_CPU = ep14, REGISTER_EXC_RETURN =
   ep18, FIXUPS_COMPLETE = ep15. Correction: "0x0:0xf = boot handoff" is WRONG on
   T6050 (ep15/0xf is FIXUPS_COMPLETE). No non-XNU supervisor domain exists
   (EXEC_MODE ∈ {SPTM,TXM,XNU}); domain is region-derived (per-CPU
   `[tpidr_gl2+0xa30]`). So code must execute inside a domain-1 (BootKC-rx) region.

D. The hardware-verified workaround: RIDE Apple's blessed XNU BootKC (antiapplefox,
   on T8142). Get code into domain 1 either (A) as a kext linked into Apple's real
   kernelcache, or (B) a binary-patched detour at `IOPlatformExpert::start` into a
   code cave inside the blessed BootKC-rx span. HW-proven: a detour inside a valid
   BootKC EXECUTES (entry-nop boots / entry-brk hangs); a `--raw` blob is refused
   before its first instruction. XNU then bootstraps normally (satisfying the SPTM),
   and on T6050 XNU starts all cores — our domain-1 code runs after.

E. Status: NOBODY has started a T6050/T6051 secondary under Linux (2026-10-29).
   Same symptom across all macOS/mBoot incl. Ed's .41.3; no update fixes it.
   Mechanism unsettled (firmware-misconfig-wait-for-Apple vs needs-registered-
   image). Post-10-25 is all hv-side tooling (m1n1 PR #737 T8142 hv CPU startup;
   #717 trap GENTER to a Python shell — a live RE tool). betizzel/omarchy-m5 has
   LIVE T6050 hardware and invites collaboration (FOR-AURORA.md).

F. The two open frontiers: (1) hand off from live XNU / a domain-1 shim to Linux
   while keeping the cores (H1/H2, untested by anyone); (2) T6050-specific: whether,
   once XNU-ridden/registered, T6050 secondaries actually start or the misconfig
   still bites.

G. Decisive next experiments, cheapest first:
   1. OFFLINE (no hardware, highest value): diff sptm.t8142.release.bin (base M5,
      secondaries WORK) vs sptm.t6050.release.bin SPTM_CORE table + per-core
      reset/CTXR entry (`0xab46c`) — the single most discriminating fact for the
      T6050-specific gate. Both binaries are in firmware/.
   2. OFFLINE: `kmutil inspect --show-mach-boot-properties` real KC vs packed m1n1
      (needs macOS kmutil — Ed) to see the region set `-c` requires.
   3. HARDWARE (Ed, 1TR/Recovery, Permissive+SIP off): install a Mach-O BootKC
      (kmutil create via synthetic-KDK, or a fixed packer) to coih; boot; read
      `/chosen` for `BootKC-bx/-rx/-ro`; capture kmutil output verbatim.
   4. Use m1n1 PR #717 (trap GENTER→Python) to recover the sptm_register_cpu/cpu_init
      call sequence live.
   5. Coordinate with betizzel/omarchy-m5 (live T6050).

Bottom line: not a dead end, not necessarily "wait for Apple" — a concrete,
hard, nobody-has-done-it route (valid BootKC → ride XNU in domain 1 → cores start
via the SPTM path XNU uses → hand off to Linux), with the XNU→Linux handoff and
the T6050-specific SPTM gate as the open frontiers. Cheapest decisive move is the
offline T8142-vs-T6050 SPTM diff (experiment 1).

## SPTM code diff T6050 vs T8142 (2026-10-29): the gate is NOT SPTM software

Direct diff of our two SPTM binaries (same build — identical panic strings),
the chip where secondaries WORK (T8142, base M5) vs where they DON'T (T6050):
- `register_cpu` (0xb8fac in both): 99.0% identical. Only diffs are core-count
  constants — `cmp w8,#9 / mov w9,#0xa` (T8142 = its 10 cores) vs `#0x23 / #0x24`
  (T6050) — and one per-CPU struct offset (`+0x5a0` vs `+0x8e0`, the bigger
  per-CPU table). Same logic, sized for more cores.
- `reset_entry` (0xab46c in both): 96.3% identical; every diff is a relocated
  `add xN,#imm` address. Same logic.

So the SPTM per-core registration/reset LOGIC is the same on both chips. Join
this with the already-known facts: RVBAR identical across running/stuck cores
(CPU-START.md), the PMGR release write byte-identical to macOS and producing
macOS's exact power transition (CPU-START.md), and CTXR/CTRR ruled out as the
gate (betizzel + rolotrealanis, on hardware). The T6050 secondary-fetch failure
is therefore NOT in the SPTM software and NOT in any register the loader gets
wrong — it is T6050-specific silicon/firmware STATE.

Decisive inference: the SPTM code is identical AND macOS starts all T6050 cores,
so macOS/XNU must set some T6050-specific per-core enable state OUTSIDE the SPTM
(during full XNU boot) that iBoot + the SPTM alone do not. That is the
"misconfiguration" Gravity reports.

## Where this lands (2026-10-29, honest bottom line)

No known solution. Nobody has started a T6050/T6051 secondary core under Linux.
The corrected, evidence-backed picture:

- Not a kmutil wall: kmutil installs a VALID Mach-O BootKC (sets coih); it
  refuses malformed ones (Code=71). `kmutil create` can build a genuine one
  without an Apple KDK (synthetic-KDK trick), kernel-only. The public refusals
  were malformed hand-packed images; nobody tried `kmutil create` on T6050.
- Not fixable by shaping/registering alone in an obvious way: the SPTM software
  is identical to the chip where cores work, so SPTM registration per se is not
  the missing ingredient — T8142 starts cores with the SAME SPTM and NO
  registration (raw m1n1).
- The missing ingredient is T6050-specific per-core enable state that full XNU
  sets. Two routes, both unsolved for T6050 secondaries:
  1. RIDE a real XNU BootKC (kmutil create → install → code in domain 1 as a
     kext or a detour cave inside BootKC-rx; proven to execute on T8142). Real
     XNU boots, sets the T6050 state, starts all cores; then hand off to Linux.
     Frontier: the XNU→Linux handoff while keeping the cores (H1/H2, untested
     by anyone).
  2. Find what XNU writes that iBoot+SPTM don't, and do it from m1n1. Needs a
     live trace of macOS's T6050 secondary bring-up (m1n1 PR #717 traps
     GENTER→Python; or an hv MMIO/sysreg trace of macOS). Unknown if
     EL2-reachable (likely not — if it were, the raw path would already work).
- Gravity's "wait for Apple" is the pessimistic reading and is consistent with
  all of the above: if the needed state is genuinely not settable from a
  non-XNU context, only Apple (or a full XNU ride) can start these cores.

Highest-value next steps that are not pure hardware:
- Trace macOS's own T6050 secondary start (hv GENTER→Python per PR #717, or an
  MMIO/sysreg trace) to identify the state XNU sets that iBoot+SPTM don't — the
  one fact that would settle loader-solvable vs wait-for-Apple.
- Coordinate with betizzel/omarchy-m5 (live T6050, invites it).

## SPTM call-interface scoping (2026-10-29): resident-call route is gated — ride-XNU is the only viable SPTM path

Pursued the "use the resident SPTM" idea (call its per-core setup from m1n1 instead
of replacing it). Mapped the SPTM runtime call interface and it is NOT usable by a
non-adopted loader:
- Runtime GENTER dispatcher = `0xa25e8` (installed as GXF_ENTER_EL1 by the per-core
  bootstrap at `0xab8e4`; VBAR_GL1 runtime = `0x104000`). Selector = top byte of x0
  (`lsr x20,x0,#0x38`); it routes to `0xeea58`.
- Router `0xeea58` gates every call: requires guarded context (`s3_6_c15_c8_0`
  nonzero), a per-selector permission byte (table `0x9a3b0 + sel*0x40 [+0x20]`), a
  reentrancy-depth check, AND a global boot-phase at `0x10c00c` that must equal
  `0x8000` (`ldarh; cmp #0x8000; b.ne bail`). That phase is the adopted-OS running
  state — not something a non-XNU loader is in.
- `register_cpu` (`0xb8fac`) is reached only from `0xe18ac`, inside a handler that
  reads **its own `MPIDR_EL1`** (`0xe18a4: mrs x8,mpidr_el1; and x0,#0xffff; bl
  register_cpu`). So register_cpu is the secondary's SELF-registration, run after it
  comes out of reset INTO SPTM's reset_entry (`0xab46c`) in guarded mode — there is
  no "boot CPU asks SPTM to start secondary N" call to make.

Why that blocks the resident-call route: to use it, a secondary would have to come
out of reset into SPTM's `reset_entry` — i.e. its RVBAR must point at `0xab46c`. But
the secondaries' RVBAR is LOCKED to m1n1's base (HANDOFF.md fw41 read, lock=1), and
only SPTM can change it — via a call that is itself gated behind the adopted-OS
phase. Circular: you need to be the adopted OS to get the cores, and the cores are
what you wanted the OS for.

Conclusion: the only SPTM path that can work is **ride-XNU** — boot the real,
SPTM-adopted XNU (which legitimately clears the phase gate, programs the secondary
RVBARs into reset_entry, and self-registers every core), then hand control to Linux
with the cores already up, via a detour in the BootKC-rx segment (BOOTKC.md notes
this was proven on T8142). This is a frontier-scale build, not a loader tweak.
Live-checkable detail (needs proxy): read `0x10c00c` under m1n1 to confirm the phase
is not 0x8000 there.
