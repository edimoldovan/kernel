# PMP core-start protocol (T6050 / M5 Max) — decode state

How macOS's ApplePMGR starts a secondary CPU, recovered from the owner's
kernelcache + PMP firmware (workflow pmp-corestart-decode, 2026-10-29; every
"confirmed" line was re-disassembled by an independent verifier).

Flat map: kernelcache file offset = VMA − 0xfffffe0007004000; PMP firmware image
base 0x284500000.

## Bottom line

A secondary core is NOT started by an AP MMIO poke (that path is exhausted and
ruled out on hardware). ApplePMGR asks the **PMP coprocessor** to power the core
to "on + full access" by writing a per-device **PTD entry into a shared-memory
"dashboard"**, ringing a doorbell, and polling a per-die ready byte. The PMP is
what actually releases the core to fetch.

The mechanism and data shapes are decoded. The CPU-core path is now traced
end-to-end down to one orchestrator function, `FUN_985b3d4` — but the actual
shared-RAM write + doorbell sit one vtable hop below it, in five virtual methods
not yet decoded. That hop, plus EDT-runtime values, is what still blocks writing
this in m1n1.

## CPU-core path (corrected 2026-10-29, keystone pass — verifier-confirmed chain)

Cores do NOT use the generic dashboard-writer / `{0,4,0xf}` path below (that is
the DVFS / generic-device path). `ApplePMGRFunctionEnableCPUCore` is a red
herring: it is only an OSMetaClass registration token (ctors at `0x988457c` /
`0x98846c0`), with no custom handler. The real path is a `gPMGR` vtable chain,
confirmed instruction-exact:

- `cpu_start()` (`0xfffffe000bc34c18`): `x0 = gPMGR` (`[0xc9f32d8]`),
  `w1 = cpuPhysId` (`[percpu+0x40]`, i.e. MPIDR/DT-derived) → vtable+0x880 thunk →
- `ApplePMGR::enableCPUCore` (vtable+0x888, `0xfffffe000985bf4c`):
  `coreMask = 1 << cpuPhysId` (`0x985bf54`), `enable = 1` → vtable+0xa88 →
- `ApplePMGR::setCPUCoreState` (vtable+0xa88, `0xfffffe000985bafc`): per-core lock
  loop over table `this+0x3f150` (stride `0x8e08`), maintains a running-core
  bitmap at `struct+0x68` → vtable+0xd20 →
- `FUN_985b3d4` (vtable+0xd20, `0xfffffe000985b3d4`): **orchestrator**. For each
  set core bit: resolve the core's PMP device (resolver `~0x984d238`, builds a
  resource-NAME string from the core number), build a per-core descriptor **on
  the stack** (the `str w10,[x13]`/`str w9,[x11]` are `[sp]` writes — NOT shared
  RAM; the `0x2bad` high-half is a bounds poison, not PAC), then dispatch **five
  `0xfd0b`-discriminated virtual calls** through ApplePMGR vtable slots ~`0x1060`
  (`0x985b62c/6e0/7e0/844/94c`). The real PMP shared-RAM write and the doorbell
  are inside those five methods — one hop deeper, undecoded.

The only AP-emitted core-on constant is `coreMask = 1<<cpuPhysId`, `enable=1`.
Per-core PTD field values are composed at runtime from EDT tables, not constants.

## Confirmed (re-disassembled)

- **Device power-state enum `{0, 4, 0xf}`.** `_enableDeviceGated`
  (`0xfffffe000986e940`): `ubfiz w8,enableBit,#2,#1` → {0,4}; `csel` on an access
  flag → `0xf`. 0 = off/gated, 4 = on, **0xf = on + full access** (the core
  target). The apply-worker `FUN(0x9850e04)` switches on exactly 0/4/0xf and
  panics otherwise.
- **Dashboard entry = 0x20 bytes**, address = `base + entryIndex*0x20`
  (`entryIndex<<5` at `0x986a568`). Fields:
  - `+0x00` u64 **PS-REQ bitmask** — bit N = request power level N; write
    `1<<level` to power on at that level, `0` to gate off (set `str x,[..]`
    `0x986a63c`; clear `str xzr` `0x986a8ec`). Logged `PTD-SOC-DEV-PS-REQ`.
  - `+0x08/+0x0c/+0x10/+0x14/+0x18` u32 sub-fields, selected by PTD op
    `0x21/0x22/0x23/0x24/0x25` (writer `FUN_986a480`, switch confirmed).
  - PMP writes `PTD-SOC-DEV-PS-ACK` + a packed `PTD-PMP-STATUS` word back.
- **Transport = PTD-entry write + doorbell + poll** (not a single RTKit opcode):
  - `ApplePPMPmgrAdapter::writeOutboundPacket(const u64* data, u32 len, u16, u16)`
    (`0xfffffe0009907034`) writes `len` u64 PTD entries via `writePTDEntry`,
    indices `len-1..1` first then **index 0 last** (commit/header word with the
    op). Real loop at `0x99070a4`; word0 committed at `0x99070f8`. (The earlier
    `0x99030a4` cites were wrong by 0x4000 — corrected here.)
  - Channel **`PPM-TO-SMC`** on the `ApplePMGRNub` (`/arm-io/pmp0 iop-pmp0-nub`);
    adapter binds the nub at `adapter+0x110` (`0x9906b6c`); channel-name table
    {`PPM-TO-SMC`,`SMC-TO-PPM`,`PPM-TO-SMC2`} at VMA `0xfffffe00080ecf28`.
  - Doorbell: `_ringPMPDoorbell` kicks the PMP after the write.
  - Readiness: the `SMC-TO-PPM` interrupt sets a per-die byte at
    `ApplePMGR+0x72864+die`; `_waitForPMPReadyActionGatedv2` (`0xfffffe0009869a60`)
    polls it.
- **Device index is runtime/DT-built, two-level** (not a static table): dense cpu
  (0..17) → DeviceData (helper `0x984ae40`) → `DeviceData.byte[+3]` = per-die
  slot → `flat = die*devsPerDie + slot` (devsPerDie at `this+0x72860`) →
  `entryIndex = i32 map[this+0x72870 + flat*4]` (−1 = invalid),
  `pmpDeviceId = i32 map[this+0x72c74 + flat*4]` (logged `Device=0x%x`).
- **PMP firmware receive side**: message dispatcher jump-table at VMA
  `0x284554778`; **type nibble `0xb`** = set/ack device power state (handler
  `0x28454a71c`). Firmware maps AP value **`0x20` → internal `0x21`** (top "on"
  state; `cmp w22,#0x21` special-case at `0x28453d7e4` sets client+0x58 and
  signals the AP-on waiter). For the type-0xb path the device id comes from the
  per-channel **context object** (`ldr w19,[x20,#4]`), not the message word.

## The core-start descriptor — recovered (data path complete)

Decoded from the dispatcher `FUN_985b3d8` (`0xfffffe000985b3d8`, body of vtable
slot +0xd20) and hand-confirmed. Per secondary core:

- Resolve the core's two-level entry. Two gated sources give the same values
  (`obj+0x10c` bit0 selects): the indexed table at `obj+0x6b170` (stride `0x88`,
  resolver `FUN_984d238`) or the array at `obj+0x3f160` (stride `0xb00`). Fields
  per core: `+0x08` = **word-index**, `+0x0c` = **block-index**, `+0x7c` =
  **bit-position**; a second table (`obj+0x6b180`, stride 8) matched by a 2-byte
  key gives a **group bit** at its `+5`.
- Build the PTD entry: in the PTD window, **set bit `bit-position` in the 32-bit
  word at offset `(block<<6) + (word<<2)`**; and set bit `group-bit` in a group
  bitmask word at `base + block*4`.
- That value is pushed through the RegMap accessor `FUN_985e400` (vtable+0x1060,
  called 5× with different field indices/masks), which sets the field in a shadow
  buffer (`helper(0x284add8)+0x18`, indexed by field) and commits through further
  RegMap vtable methods (+0x1068 div `0x7f`, +0x1070 div `0x8c12`) — the generic
  register-map layer that finally touches MMIO.
- The window + doorbell are ADT-indexed into `/arm-io/mcc` reg[]:
  `ptd-ranges = {0x0a,0x0b,0x0c,0x0d,0x02,0x04}`, `pmp_ptd_db_reg_idx = 2`
  (doorbell), `pmp_ptd_update_reg_idx = 3`, `ptd-range-drv2ctrl = 15`,
  `ptd-range-ctrl2drv = 18`. PA via `/arm-io` `ranges` (m1n1 `adt_get_reg`).
- `function-enable_core` per core = `{/arm-io/pmgr, fourcc "Core", args:[1<<dense]}`
  = the `coreMask` the code computes. Device ids `id2` 1..0x12 from the 18
  MCPU/PCPU nodes.

## Open — two numbers, best taken from a live dump

The control flow, the PTD-entry bit formula, and every ADT parameter are
recovered. Two concrete numbers sit behind several more generic-RegMap vtable
hops (`FUN_985e400` → +0x1068/+0x1070 → RegMap MMIO), which are turtles to peel
statically but trivial to read live:

1. **Which `/arm-io/mcc` reg window** among the `ptd-ranges` indices the per-core
   PTD words land in (the `drv2ctrl` = reg[15] is the likely AP→PMP range).
2. **The doorbell value** written to mcc reg[2].

Live dump to settle both (needs the Mac + o-4.8-gpu-boss for proxy): cold-boot to
the proxy, read the mcc `ptd-ranges` windows + reg[2] with a core parked, then on
a real macOS boot (or via the resident image) read them with that core up; the
bytes that differ ARE the PTD entry + doorbell value. This confirms the whole
chain end-to-end on hardware — the standard terminus, cheaper than peeling the
RegMap layers.

## m1n1 implementation shape (fill in #1–#2, then test)

New `chip_id == T6050` block invoked from `smp_start_cpu()` per secondary:
map the mcc `ptd-ranges` windows (`adt_get_reg`), for the cpu set bit
`bit-position` in the word at `(block<<6)+(word<<2)` of the AP→PMP range plus the
group bit, write mcc reg[2] (the doorbell value from #2), poll the per-die ready
byte, then fall through to m1n1's existing spin-table path. Plus the one-line
dense-mask fix (`1 << index`, HANDOFF.md). The per-core `word`/`block`/`bit`
triples come from the ADT core nodes (or are read once from the live tables).

## Decode terminus (2026-10-29): the core-start write is NOT a static poke

Finished the RegMap write-path decode (FUN_985e400 vtable+0x1060 → +0x1068
`0x285a5c0` / +0x1070 `0x28777e0`, helper `0x284add8`, resolver `0x284ae40`).
Result: the write is a runtime-parameterized **RegMap framework** operation, not a
literal MMIO write.
- `FUN_985e400` is a generic "set field" accessor: it writes the value into a
  SHADOW register entry inside the ApplePMGR object — `helper(obj,dev,idx)` returns
  `&obj[0x29e8 + dev*0x60 + idx*0x30]`, then `str value,[entry+0x18 buffer, field]`
  — then dispatches vt+0x1070/vt+0x1068 to commit to hardware.
- Register OFFSETS are resolved at runtime: resolver `0x284ae40` maps a field index
  via a u16 table at `obj+0x9d40` into an entry array at `obj+0x90a8` (stride 0x30).
  These descriptor tables are built at ApplePMGR init from the ADT.
- vt+0x1068 (`0x285a5c0`) and vt+0x1070 add further vt+0x1058 dispatch and
  poll-until-stable retry loops before the terminal MMIO store.

Consequence: the exact PTD request word/offset/value and the doorbell value are
NOT constants in the binary — they are computed through the RegMap descriptor
tables from runtime/ADT state. A "constructed write from decode" by pinning
constants is therefore not achievable. The real core-start MMIO transaction can
only be obtained by:
  (a) LIVE-TRACING macOS performing a core-start (capture the actual MMIO writes
      to the mcc PTD windows) — needs macOS running under the m1n1 hypervisor,
      which on T6050 needs the SPTM-under-hv port (large; see HV-TRACE-PLAN.md 0a);
      or
  (b) reconstructing ApplePMGR's RegMap descriptor tables from the ADT (emulating
      its init) to compute the field→offset mapping — large but desk-doable.

Write-test 1 (pmgr start-block + bare doorbell) already showed the doorbell alone
is inert (dumps/ptd-live-reads.md). Both remaining routes are substantial.

## Route (b) progress: the RegMap offset-resolution chain (2026-10-29)

Decoded the register-offset resolver `FUN_0x2853a4c(obj, field)` (ApplePMGR exec):
- `descidx = u16 [obj+0x9d40][field]`  (index map; 0x2bad-poison bounds check)
- `desc = [obj+0x90a8] + descidx*0x30`  (descriptor array, stride 0x30)
- `id = desc[+0x1a] (u16) ? : desc[+3] (u8)`
- `tabidx = FUN_0x2849dcc(obj, id)`     (id → offset-table index)
- `reg_offset = [obj+0x60c0]-table[tabidx].[+4] + sub*8`  (0x2853b48-54)
- value-read variant `FUN_0x2853bb4`: `w0 = [[obj+0x60c0] + tabidx*0xc]`

So the MMIO offset for any field is a function over three ADT-built tables
(`obj+0x9d40`, `obj+0x90a8` stride 0x30, `obj+0x60c0` stride 0xc). vt+0x1070
(`0x28777e0`) is a no-op stub set; the real RegMap commit is vt+0x1068
(`0x285a5c0`) → vt+0x1058 → terminal store into the mapped window.

To compute a core's transaction, route (b) must rebuild these tables from the
ADT (reimplement the relevant ApplePMGR init), then run the chain for the core's
field index. Tables to reconstruct: obj+0x9d40, obj+0x90a8, obj+0x60c0, and the
per-core obj+0x6b170 (word/block/bit). This is a multi-part reconstruction, now in
progress.

## MAJOR REFRAME (2026-10-29, reconstruction R1/R3/R4 + ADT + verifiers)

The PMP doorbell/PTD path is NOT the core-enable path. R4 (verifier-confirmed):
`setCPUCoreState` (FUN_0x28573d4) rings NO doorbell and writes NO PTD dashboard —
the doorbell is gated by the device `notify_pmp` flag, which is **0 for all 18 CPU
cores**, so the whole PMP/PTD/doorbell subsystem is perf-state/cache-mode, not core
enable. (Write-test 1's doorbell ring was therefore testing the wrong subsystem.)

The REAL core-start (T6050 = mode 2, `u32[obj+0x238c]==2`) is two RMW-OR 32-bit
writes into the **mapped pmgr reg0 window** (`/arm-io/pmgr` reg0 = phys
`0x280600000`, size 0x1fc000), via the RegMap set-field accessor FUN_985e400
(terminal `str w23,[mappedVA, byteoff]` at 0x285a4dc):
- loop1: `[reg0 + B + 4]      |= (1 << acc-cores[core].byte5)`  (byte5 = global idx 0..17)
- loop2: `[reg0 + B + 8 + 4*cluster] |= (1 << acc-cores[core].byte6)` (byte6 = cluster-core 0..5)
  where `B = u32[obj+0x5e18]` = the pmgr "Core"-function register byte-offset.

ADT `acc-cores` (18×8B, parsed offline): byte5 = global index 0..0x11, byte6 =
cluster-core 0..5. For cpu1 (MCPU0_1): byte5=1, byte6=1 → both writes = `1<<1 = 0x2`.

### This is essentially m1n1's existing path

m1n1 (release_one.py / HANDOFF.md) writes `pmgr_reg0 + 0x88000 + 4 = 1<<idx` and
`+ 0x88000 + 8 + 4*cluster = 1<<core`. For cpu1 the VALUES match macOS exactly
(0x2, 0x2). pmgr reg0 base matches. The only differences vs m1n1:
1. **B (Core-fn offset) vs m1n1's hardcoded 0x88000** — B = `u32[obj+0x5e18]`, a
   runtime init value not yet statically resolved (its init writer wasn't found).
   m1n1's 0x88000 is an unverified M3/M4-Max inheritance (HANDOFF.md).
2. **RMW-OR vs overwrite** — macOS ORs (accumulates all started cores' bits);
   m1n1 does plain write32, so starting cpu1 overwrites cpu0's bit0 (writes 0x2
   where macOS would hold 0x3).
3. **mode selector** `u32[obj+0x238c]` (mode 2 assumed; else per-device PS path).

### Consequence (honest)

Write-test 1 already showed m1n1's 0x88000 writes drive cpu1 to the running
pattern 0xef20d102 but it never fetches. Since the bit values match and the base
is plausibly right, the core-start WRITE is likely correct — which matches the
long-standing CPU-START.md finding "the core is started correctly and still never
fetches, downstream of a correct write." That points the fetch gate back at the
**SPTM per-core execute-permission** (CTXR/reset-into-SPTM), the original hard
problem, NOT the PMP. The PMP excursion is now closed as a dead end for core-enable.

### Refined write-test (ready; needs proxy un-pause)

One shot worth taking to rule out B/RMW-OR: for cpu1, RMW-OR `[reg0+0x88000+4] |= 0x2`
and `[reg0+0x88000+8] |= 0x2` (keeping cpu0's bits), with the crumb stub, watch for
a fetch. If still no fetch, it confirms the gate is the SPTM execute path, not the
pmgr write — i.e. back to the BOOTKC/SPTM-resident route.

## Write-test 2 (RMW-OR, 2026-10-29): REFUTES RMW-OR; confirms gate is downstream

Refined cpu1 write-test over the proxy (o-4.8-gpu-boss granted access). Observed:
- Cold pmgr start-block: PM+0x0 = PM+0x4 = **0x3fffe** (bits 1..17 set = the 17
  parked secondaries; bit0/cpu0 clear). PM+0x8/0xc/0x10 = 0.
- RMW-OR `[PM+0x4] |= (1<<1)` was a no-op (cpu1's bit already set in 0x3fffe);
  `[PM+0x8] |= (1<<1) = 0x2` triggered. Writing PM+0x8 cleared PM+0x0/PM+0x4 to 0
  (side effect) and cpu1 -> **0xef20d102** (running pattern), `+0x104`=0x118080ca.
- cpu1 NEVER fetched: no crumbs, smp_is_alive=false, AIC cfg=0, through t+2.0s.
  (dumps/write-test-2-rmwor.json)

Conclusion: RMW-OR vs overwrite makes NO difference; the pmgr start-block write is
correct (reaches the running pattern every time) and is NOT the fetch gate. This is
the THIRD consistent observation (plain overwrite, +doorbell, +RMW-OR) of
"started-correctly / never-fetches". The pmgr/PMP core-enable line is EXHAUSTED.

The fetch gate is downstream of a correct start write — the SPTM per-core
execute-permission (CTXR / coming out of reset into resident SPTM), matching
CPU-START.md and BOOTKC.md. That route has no known loader-side fix (BOOTKC.md);
the realistic options are the SPTM-resident / BootKC route or wait-for-Apple.
