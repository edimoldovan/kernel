# T6050 (J714c) Linux bring-up

Linux boots to a busybox shell on one core of the M5 Max MacBook Pro (J714c).
First shell: 2026-10-23 08:06, kernel 7.2.10-aurora-t6050-j714c-wip+.
The internal keyboard has no driver path yet, so the shell cannot be typed into.

## Contents

- `boot/Image.gz`, `boot/t6050-j714c.dtb`, `boot/initramfs.cpio.gz`: the booting set.
- `initramfs/init`, `initramfs/busybox`: the init script and the static aarch64 busybox 1.36.1 (cross-built, CONFIG_STATIC, CONFIG_TC off). Repack: rootfs with these at `/init` and `/bin/busybox` plus busybox `install`, then `find . -print0 | cpio --null -o -H newc | gzip -9`.
- `config/t6050.config`: the kernel .config (16K pages, NR_CPUS=18, FB_SIMPLE, no APPLE_WATCHDOG).
- `tools/chainload_t6050.py`: m1n1's chainload.py with the secondary RVBAR writes skipped on chip 0x6050. The stock script faults the resident m1n1 into an SError loop on cpu1's cpu-impl-reg.
- `tools/boot_t6050.sh [tag]`: chainload `m1n1/build/m1n1.macho` (or `M1N1_MACHO=...`, e.g. the omacom fork build; `EXTRA` adds bootargs) over the resident proxy, boot `boot/*` over the new proxy, then time the watchdog reset (see Crumbs). Logs in `log/`.
- `log/boots.log`: the 17 overnight runs.

## Sources and commits

| Repo | Branch | Commit | Content |
|---|---|---|---|
| linux-aurora (origin omacom/linux-aurora) | integration/aurora | b7558249b | T6050 device tree, the PR candidate |
| linux-aurora | integration/aurora | e3b1e1799 | fbcrumb instrumentation, not for upstream |
| m1n1 (origin AsahiLinux/m1n1) | main | fcb4102e | smp: dense per-core held mask on T6050 |
| m1n1 | main | 2e74ab9c | kboot: skip dapf_init_all on T6050, the PR candidate |
| m1n1 | main | bf820fb3 | wdt_arm and crumbs, instrumentation |
| j714c (edimoldovan/j714c, pushed) | master | 377c352 | t6050-pmgr.dtsi, dumps, tools, notes |

Build: `make -C linux-aurora O=/tmp/opencode/aurora-build ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- Image.gz dtbs` with `config/t6050.config` as `.config`; `make -C m1n1`. The build directory under /tmp is tmpfs.

## Pushing

Fork clones live in `/home/ed/dev/omarchy/forks`: `linux-aurora` (origin edimoldovan/linux-aurora, upstream omacom/linux-aurora) and `omacom-m1n1` (origin edimoldovan/m1n1, upstream omacom/m1n1; one fork per network on GitHub, AsahiLinux/m1n1 is the same network). The PR branches are rebuilt there on the current upstream heads; the working clones under `/home/ed/dev/omarchy` keep the history with the crumbs. No PR goes to AsahiLinux: their contribution guidelines reject AI-generated code.

forks/linux-aurora
- `t6050-j714c`: the T6050 device tree, the MTP keyboard and trackpad nodes, the rtkit-helper early AP wake case (three commits, no crumbs).
- `t6050-j714c-wip`: the working history with the crumbs.
```
git -C forks/linux-aurora push origin t6050-j714c t6050-j714c-wip
```
PR: `t6050-j714c` into omacom/linux-aurora `integration/aurora`.

forks/omacom-m1n1
- `t6050-aurora`: MTP DAPF on T6050, dense secondary release mask, i2c limit 16 (one commit). Boot-tested as run 27 from the m1n1-omacom clone. Build needs `CARGO_NET_GIT_FETCH_WITH_CLI=true make`.
- `t6050-wip`: the Asahi-based loader that booted first, with the crumbs (record only). `t6050-boot` is already on the fork.
```
git -C forks/omacom-m1n1 push origin t6050-aurora t6050-wip
```
PR: `t6050-aurora` into omacom/m1n1 `integration/aurora`. Its loader refuses to start secondaries on a chainload ("RVBAR differs from vector"); `tools/linux_t6050.py` continues with the boot CPU.

## Crumbs

The kernel and m1n1 carry milestone crumbs (asm/fbcrumb.h). Each draws a 16 px white band into the panel framebuffer, writes a word at 0x10800000000 and can arm the primary watchdog (0x28836c000, 24 MHz) with a per-milestone timeout. The host reads the furthest milestone from the reset-to-proxy time; a watchdog reboot returns the proxy in 11 s, and 20 s steps are needed because of a 5 s jitter. All timeouts are 0 in the committed trees, so the machine stays up after boot. The white bands remain on the panel. The RAM word does not survive a reset and lands in allocator space; it is the first thing to strip. `git revert e3b1e1799` removes all kernel crumbs.

## Verified

Run 29, 2026-10-23 10:2x: kernel built from `arch/arm64/configs/j714c.config` (KCONFIG_ALLCONFIG + allnoconfig) on edimoldovan/linux-aurora `t6050-j714c` at 321908da, loader edimoldovan/m1n1 `t6050-aurora` at 7c61d6bc, chainloaded and booted with the proxyclient tools committed on that branch. Shell with keyboard on one core. Nothing in this folder is needed for that boot any more.


Run 28, 2026-10-23 10:07: the pushed pair boots the J714c to a shell with a working keyboard on one core. Loader: edimoldovan/m1n1 `t6050-aurora` at 26c2c861 (forks/omacom-m1n1). Kernel and dtb: edimoldovan/linux-aurora `t6050-j714c` at 60362b23 (forks/linux-aurora), built with `config/t6050.config`, copies in `boot-pr/`. Chainloaded with `tools/chainload_t6050.py`, booted with `tools/linux_t6050.py`, both from this folder; the PR trees contain neither tool nor a T6050 config fragment.

## Facts established overnight

- m1n1's kboot path faulted on T6050 in dapf_init_all, writing dart-aop reg 1 at 0x2890fc000; pcie_init bails on its own.
- The stock chainload RVBAR writes to cpu1 (0x210150000) lock the resident m1n1 in an SError loop.
- MMIO addresses in the dts must be physical: ADT arm-io child + 0x200000000 (AIC 0x280400000, UART 0x505200000, WDT 0x28836c000, GPIO 0x29c000000, pmgr 0x280600000).
- m1n1 enables the framebuffer node only inside its per-chip display setup, which returns early for T6050; the dts enables it statically.
- The kernel passes init_IRQ, time_init, all initcalls, simplefb registration and /init exec on one core.

## Next

1. Keyboard: dockchannel MTP nodes in the dts and the HID transport driver, or USB host (dwc3 and atcphy nodes) for an external keyboard. The ADT has `dockchannel-mtp` and `usb-drd0..2` with `atc-phy,t6050`.
2. Clean push, after the keyboard: strip the crumbs (RAM word first) from the PR branches, port the m1n1 gate onto omacom/m1n1 and chainload-test it, push the PR branches to the forks.
3. pmgr: copy `j714c/dt/t6050-pmgr.dtsi` into the tree, include it from `t6050.dtsi`, boot.
4. cpufreq: `apple_soc_cpufreq_init: failed to get cluster info: -19`; cluster-cpufreq nodes or leave disabled.
5. Secondary CPUs: locked RVBAR, the j714c research in `j714c/dumps/HANDOFF.md`.
6. Root filesystem: NVMe (ans2 and dart nodes) or USB storage once host works.
7. chainload.py upstream change: skip RVBAR writes for CPUs whose cpu-impl-reg is locked, instead of the scratch copy.

## PMP (secondary CPU power) research, 2026-10-23

Runs are `log/pmp-run1..11.log`, tool `tools/j714c_pmp.py` (boots the PMP coprocessor from the resident proxy).

- Runs 1-10: HELLO, endpoint map, crashlog/kdebug/ioreport/endpoint-7 buffers served; no IOP power acknowledgement; no endpoint 0x20 traffic; cores do not start.
- The PMP firmware's boot-argument records (SRAM +0x22c/+0x230) that macOS writes before starting the core (`ApplePMPFirmware::patchFirmware`, kernelcache mac17j): BDID and DVID from /chosen; DCAP, DCHD from the nub when present; PMC_ = pmgr `pmc`; PMCV = pmgr `pmc-pmgr` bit 0; PMCB = pmgr `pmc-pmgr` bit 3; PMCX = nub `pmc-msg-disabled` when present; CVAR = nub `soc-chip-variant`. J714c values: BDID 0xa, DVID 0xff, PMC_ 1, PMCV 1, PMCB 1, CVAR 1, the rest 0. The pmgr `pmc`/`pmc-pmgr` properties exist on M4-generation and later device trees (j604, j616c, j714c, j813, j873s), not on j516c.
- PMC = a separate power controller whose firmware iBoot loads (`MARK_PMC_IMEM_LOAD_*` in iBoot). macOS only monitors it (AppleT6050 error handler, assert dumps, life-check timer).
- Run 11 (full record set): same result as runs 1-10.
- Firmware dump (SRAM 0x284500000 1 MiB + DRAM text 0x10001e5c000 64 KiB, AArch64, linked at 0x1000000) analysed with Ghidra 12 headless (`scratchpad/pmp_ghidra_out`). The live data shows the init task parked in a wait for the host's AP power-on; the script had replaced m1n1's default `boot_done` (AP power ON right after the endpoint map) with an endpoint start and never sent AP power ON when the IOP acknowledgement did not come.
- Run 12 plan: default `boot_done` (AP power ON after the map), wait for IOP and AP acknowledgements, then endpoint 0x20, then phases B/C. Needs a power-cycled Mac; the PMP core does not restart on a RUN toggle.
- Run 12 (default ordering, AP power ON right after the endpoint map, 60 s wait): same result, no acknowledgements. Reboot over the proxy (`j714c/tools/reboot.py`) brings the resident proxy back in about 11 s. Stopped here: the firmware-internals route is not being pursued further.

## PMP disassembly finding, 2026-10-23

Firmware image analysed in Ghidra (`scratchpad/pmp_ghidra_out`), cross-checked against a live SRAM dump.

- Init runs as `FUN_01019e34` and ends by printing "PMP started". Early-init globals are set in the live dump (DAT_010f20c8=0x1100), but every late-init global it writes after the mid-point is still 0. So init started and did not finish.
- On the init path, before the late globals, `FUN_0104aa50` finds the device object whose id (+4) is 0 and blocks until that object's enabled flag (+0x58 bit 0) is set, then releases (`FUN_0103cdbc(...,7,...)`). In the live dump that node is 0x10edfa0, id 0, flag 0. So init is parked on this wait.
- The flag is set by a device-enable request the host delivers, handled by the dispatch loop at 0104a46c reading `FUN_0104dab0`, which drains a shared-memory ring (head/tail at ring+0x40, valid bit per entry, DMB), i.e. a PTD channel, not the RTKit mailbox. That is why the RTKit buffers and ioreport streaming work while the IOP/AP power acknowledgements never come: the acknowledgement is downstream of an init step that waits on the PTD ring, and nothing on the mailbox unblocks it.
- Runs 1-12 never drove the PTD ring during the handshake. PHASE B wrote SOC-DEV-PS-REQ only after the 60 s timeout, for the CPU clusters, and read back 0.
- Next experiment: during the handshake, before waiting for the power acknowledgement, deliver the device-enable request for the firmware's device index 0 through its PTD request ring and ring the doorbell, then watch whether init completes and the acknowledgement follows. Needs the ring/doorbell layout from the nub ptd-range table and the pmgr PTD aperture (reg[7] 0x284240000).

## 2026-10-25

The working clones `linux-aurora` and `m1n1` under `/home/ed/dev/omarchy` are deleted. The only trees are the forks: `forks/linux-aurora` (branch `t6050-j714c`, origin edimoldovan/linux-aurora) and `forks/omacom-m1n1` (branch `t6050-aurora`, origin edimoldovan/m1n1), plus `j714c`. Kernel build: `make -C forks/linux-aurora O=/tmp/opencode/aurora-build-j714c ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- Image.gz dtbs`. Proxy tools run with `forks/omacom-m1n1/.venv/bin/python` and `PYTHONPATH=forks/omacom-m1n1/proxyclient`; `tools/boot_t6050.sh` uses them. The fork kernel at f1229bc0e5f8 carries the T6050 pmgr power domains (boots with unused domains powered off) and, in f8f55f4651f8, a per-domain probe print and a 150 s watchdog arm at late_initcall: every boot of that kernel resets itself after 150 s.

`boot/initramfs-lsal.cpio.gz` (source `initramfs/init-lsal`) is the same initramfs with `ls -al /` run by init before the shell, so a boot proves itself on the panel; pass it as `IRD=` to `tools/boot_t6050.sh`.

## Disk layout, 2026-10-25

After `diskutil apfs resizeContainer disk3 1800g ExFAT LINUX 0` from Recovery (the installed 27.2 beta panicked twice on container operations; Recovery's kernel did not): APFS container disk0s2 is 1,800,000,000,000 bytes; the new partition is `LINUX`, disk0s5, ExFAT, offset 439593984 sectors = 1,800,576,958,464 bytes, size 47647744 sectors = 195,165,159,424 bytes, 4096-byte sectors. Linux must read exactly this from the GPT before any write; the Linux EFI and root partitions replace it later. The other partitions: disk0s1 iBoot (576.7 MB), disk0s3 recovery (5.4 GB).
