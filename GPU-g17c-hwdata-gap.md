# Where the 0x128 bytes go in the g17c HwData

Short answer: the 0x128-byte growth falls in a region of the host `HwData` that
the g17c firmware never reads, so its exact position cannot be read off the
firmware, and the driver does not need it exact. Add 0x128 bytes of padding
anywhere in G17P `0x1cf0..0x2534`; the simple, correct change is to grow
`unk_23dc` from `[u8; 0x168]` to `[u8; 0x290]`. The head fields (≤ `0x1cf0`) and
every tail field then land where g17c reads them.

This is layout only. It makes the firmware's fixed-offset reads line up; it does
not model the extra perf states semantically (see "Why not exact", below).

## What is fixed

- The host `HwData` on g17c is G17P's layout with 0x128 bytes inserted somewhere
  in G17P `0x1cf0 .. 0x2534`. Everything below `0x1cf0` is at the G17P offset;
  everything at/after G17P `0x2534` is at G17P offset + 0x128.
- Tail fields, confirmed by their access shape (`log/gpu-g17c-reads.txt`):
  - `completion_rings`: G17P `0x2614` -> g17c `0x273c`. Four 0x20-byte records,
    each read `+0x00` u64, `+0x10`/`+0x18` u32, `+0x1c` written by firmware —
    G17P's `CompletionRingDescriptor`.
  - `qos_va`: G17P `0x26ac` -> g17c `0x27d4`.
  - The fixed-value fields `unk_2544..unk_2550`, `unk_2570`, `unk_25f4`,
    `unk_2600`, `unk_2608`, `unk_2610` all map at G17P offset + 0x128.
- g17c `HwData` is at least `0x3db4 + 0x128 = 0x3edc` bytes.

## Why it cannot be pinned from the firmware

The host `InitData` is read once, by the init function at `__TEXT 0x21854`
(reached via main config at global `0x108888`, `main_config+0 = hw_data_va`).
After init the firmware works from its own resident copy; its internal layout
differs from the host's and says nothing about host offsets.

The init function reads **scattered scalars**, not the perf arrays:

- In `perf_a` (`0xfc4..0x16c8`): individual fields at `0xfc8..0x10cc`
  (`ldr x10,[x19]; ldr w10,[x10,#off]`, no loop).
- In `perf_b` (`0x1cd8..0x23dc`): only the first 0x18 bytes
  (`0x1cd8..0x1cf0`). Nothing from `perf_b+0x1c` on.
- In `unk_23dc` (`0x23dc..0x2544`): nothing.
- Then the tail from G17P `0x2534` (g17c `0x265c`) on.

So the init constrains the split only to the gap `(0x1cf0, 0x2534)`; it reads no
field inside it. The big perf tables (`freq_mhz[]`, `core_mv[][]`, `sram_mv[][]`)
are not copied from the host here — the firmware uses the ADT/OPP perf data it
already holds. A straight-line scan of both blobs (`gfx-asc`, `gfx1-asc`,
`tools/fwre/reads.py` over all of `__TEXT`, main-config pointer chain) finds no
host-`HwData` read in `0x1cd8..0x2614`. The scan cannot prove a negative, but no
read into the gap was found on either coprocessor.

Because the gap is not read, where the 0x128 sits inside it does not change
firmware behaviour. Only the total size and the head/tail offsets matter.

## Why not exact / why not "+3 perf states"

The M5 Max ADT `sgx` perf table has 14 entries (idle `freq=0` + 13 active;
`gpu-num-perf-states = 13`); G17P `PERF_STATES = 11`. A `PerfGroup` grown by 3
states at G17P's internal layout would add `0x84 * 3 = 0x18c`, not `0x128`, and
`perf_a` does not shift at all (head fields match). So g17c `perf_b` is not a
plain G17P `PerfGroup` with three more states, and the growth is not a clean
multiple of a known element. The host perf_b/unk_23dc region on g17c looks
partly vestigial (firmware uses its own perf copy), which is consistent with it
being unread. Modelling the region field-by-field would need the layout macOS's
`AGXG17X` builds, not the firmware.

## The change

In `drivers/gpu/drm/asahi/g17/fw/initdata.rs`, `HwData`:

```
-    pub(crate) unk_23dc: [u8; 0x168],
+    pub(crate) unk_23dc: [u8; 0x290],   // 0x168 + 0x128 for g17c (T6050)
```

and the size/offset `static_assert!`s for `completion_rings` (`0x273c`),
`qos_va` (`0x27d4`) and `size_of::<HwData>()` (`0x3edc`) follow. Gate it by chip
so G17P is unchanged.

`INTERFACE_VERSION` for g17c is `[0x04c0, 0x8728, 0x4339, 0x0c8e]` (separate
from this change; see `GPU.md`).

## Done looks like

A g17c boot where the firmware does not log "Host and FW Interface is
mismatched", does not fault reading the completion rings or QoS object, and
reaches the same init progress as G17P. That boot is the only thing that
confirms the 0x128 total and the tail offsets; the exact split within the gap
has no boot to confirm because nothing reads it.
