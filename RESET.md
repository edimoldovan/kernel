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

## Next: bisect the kernel from the sit initramfs, one boot each

1. `initcall_blacklist=apple_wdt_driver_init` (the only driver that writes the watchdog block; ctrl reads 0xc0 only under the kernel).
2. `initcall_blacklist=dockchannel_hid_driver_init,dockchannel_driver_init` (the MTP input path).
3. Then the device tree node by node.
