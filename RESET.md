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

## Also ruled out (2026-10-26 morning, one boot each, 1 s serial poll: kernel at 7-9 s, proxy back at 192-193 s every time)

- `pd_ignore_unused`: no change.
- `idle=poll`: no change.
- The PMGR words 0x288335260, 0x288330008, 0x28833002c, 0x288330020: 0 in the resident proxy, 0 for the whole kernel run (`t6050_wdtmon` prints them now).
- Userspace: a busybox initramfs that only sits (`initramfs/init-sit`, no disk root, no systemd) resets at the same time.
- NVMe: the same sit boot with the nvme node `status = "disabled"` resets at the same time.
- The loader's own recovery watchdog (`wdt_arm_seconds`, usb_cdc.c) is T8140-only and uses WD1.

Observation: WD0/WD1/WD2 ctrl read 0 in the resident proxy and 0xc0 in the kernel (bits 6-7; RESET_EN is bit 2).

## The loader is clear (2026-10-26 11:00-11:20)

- The chainloaded dev loader left alone, no kernel: sat 13+ minutes, no reset. Its WD0/1/2 ctrl words read 0, the PMGR words 0.
- The dev loader handing off through linux.py to a fake Image (arm64 header + `b .`, no kernel code): sat 5+ minutes, no reset. The handoff itself is clear.

So the trigger is in the kernel's own code, before any userspace and independent of NVMe.

## Kernel bisection from the sit initramfs (2026-10-26 11:05-11:25, `initcall_blacklist=`), all still reset at the same time

- `apple_wdt_driver_init`: no change (WD1 keeps the loader's 150 s bite, ctrl still reads 0xc0 under the kernel).
- `dockchannel_hid_driver_init,dockchannel_driver_init,dcuart_init`: no change.
- `apple_rtkit_helper_driver_init,apple_mbox_driver_init` (no coprocessor firmware started): no change.
- `apple_pmgr_ps_driver_init`: see log/boots.log (nopmgr).

- `apple_pmgr_ps_driver_init`: NO RESET (6 min, console dark because the framebuffer needs a power domain).

## Found (2026-10-26 12:00-12:45): a power-off of an SPMI bus domain

Switches added to pmgr-pwrstate.c (`t6050_noauto`, `t6050_nomin`, `t6050_nopower[=names]`, `t6050_noalways`, `t6050_nooff`, `t6050_noon`, `t6050_pmlog`), one boot each from the sit initramfs:
- probe-time auto-PM enable skipped: reset. Minimum-state write: no users. 
- every power_on/power_off a no-op: NO RESET (529 s). Only power-offs no-ops: NO RESET (244 s+). So a power-off.
- offs of `atc*,nub_spmi*,venc*,msr*,afr,aic_gfx,b2b_ctrl_gfx,fppt_gfx` skipped: NO RESET (349 s). Only `atc*`: reset. Only `nub_spmi*`: NO RESET (259 s+).

The kernel's unused-domain pass turns off nub_spmi0, nub_spmi2, nub_spmi3, nub_spmi4 (the SPMI buses to the power-management chips; `pd_ignore_unused` does not stop it in this tree); the machine resets about 179 s after that. nub_spmi1 was already `apple,always-on`.

Fix: `apple,always-on` on ps_nub_spmi0/2/3/4 in t6050-pmgr.dtsi (linux-aurora). boot-esp/aurora/linux/t6050-j714c.dtb rebuilt and written to the Mac's ESP (init-esp5, 13:00).

Verified 2026-10-26: disk root + systemd through the dev loader, 8 min at the login, no reset; then stage 1 (RAM) -> stage 2 -> kernel and dtb from the ESP -> disk root, 8 min at the login, no reset. Closed.
