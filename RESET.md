# Reset after boot (open)

Symptom: every boot from disk reaches `omarchy-m5 login:` and the machine resets about 179 s after the kernel starts. Measured with a 1 s poll of the USB serial nodes: kernel start at t0+8 s, resident proxy back at t0+193 s (dev loader, 2026-10-26 00:53). Same with stage 1 → stage 2 and with the dev loader.

## Ruled out (one boot each, dev loader, root on p6)

- `t6050_wdt=` hook in pmgr-pwrstate.c: default 0, gated, reset still at 196 s.
- AP watchdog block 0x28836c000 (`t6050_wdtmon=15`): ctrl reads 0xc0 on WD0/WD1/WD2 (no RESET_EN); WD0 and WD2 wrapped their 32-bit counters without a reset; WD1 passed its 30 s bite without a reset. Feeding WD1 every 15 s (`t6050_wdtmon_ping=1`): reset still at 196 s.
- The secondary word at 0x288330008 stays 0 (the loader zeroes it).
- Kernel reboot path: `apple_wdt_restart` instrumented with a message, stack dump and a 20 s hold; nothing printed and no hold, proxy back at the usual time. Not a userspace reboot, not a panic reboot (`CONFIG_PANIC_TIMEOUT=0`).

## Facts

- `t6050_wdtmon=<s>` (pmgr-pwrstate.c, commit 4f0418b2b2e5) prints the watchdog counters on the console.
- ADT `/arm-io/wdt`: wdt-version 3, five regs: 0x28836c000/0x4000, 0x288335260, 0x288330008, 0x28833002c, 0x288330020 (the last four are PMGR + 0x35260/0x30008/0x3002c/0x30020; the Linux pmgr2 node covers only 0x288300000+0xc000). `trigger-config` lists 18 per-core entries (3 clusters × 6). The loader zeroes only 0x288330008.
- 179 s is 2^32 ticks at 24 MHz.

## Next experiments (one boot each, same command as the `rstwho` run in log/boots.log)

1. `pd_ignore_unused` on the command line (genpd powers off unclaimed domains at late init).
2. `idle=poll` (the loader never enters WFI; the kernel idles in WFI).
3. Read 0x288335260, 0x28833002c, 0x288330020 from the proxy before and after a kernel run; add them to `t6050_wdtmon`.
