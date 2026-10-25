# Plan: Omarchy boot chain on the M5 Max (J714c)

Target chain, the one Omarchy uses on M1 and M2: iBoot -> m1n1 stage 1 (stub volume, enrolled once from recovery) -> m1n1 stage 2 (EFI partition) -> U-Boot -> Limine -> unified kernel image -> btrfs root.

Order of work:

1. NVMe clean. Find the power domain that breaks it, so the normal device tree boots with the disk. Today the disk enumerates only with every pmgr domain firmware-owned (`boot/t6050-j714c-allfw.dtb`).
2. Enough hardware for daily use. All cores, display, Wi-Fi, GPU, sleep. Each is its own bring-up.
3. Partitions. The LINUX partition (nvme0n1p3, 195 GB ExFAT) becomes EFI 500 MiB, boot 2 GiB, root btrfs.
4. Stage 1. m1n1 from forks/omacom-m1n1, built `RELEASE=1 CHAINLOADING=1`, EFI partition ID baked in. Ed enrols it once from recovery mode with `kmutil configure-boot --raw --entry-point 2048 --lowest-virtual-address 0`.
5. Stage 2 and U-Boot on the EFI partition. m1n1 plus the J714c device tree plus U-Boot. U-Boot needs a T6050 board entry and console. Not written.
6. Limine, kernel image and root. Limine at EFI/BOOT/BOOTAA64.EFI, the kernel as a unified image, Omarchy's aarch64 packages on the root. No M5-specific work.

Facts behind the chain: Omarchy on Apple Silicon is pre-release (edge channel, announced 2026-09-11), M5 is in development there and in no installer catalog. Sources: omacom/omarchy-mac-pkgs mac-manual, omacom/omarchy-mac-installer image-builder, forks/omacom-m1n1/docs (j700-install.md, boot-options.md).
