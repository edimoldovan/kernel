# Omarchy login on the M5 Max (J714c)

The full Omarchy root boots read-write over the m1n1 proxy and logs in through SDDM into
Hyprland. Every feature below works in that login; this is the bar for each new one.

## Boot

```
/home/ed/dev/omarchy/kernel/tools/omarchy_boot.sh TAG
```

It reboots the Mac over SSH if Linux is running, sets m1n1's `chosen.asahi,show-notch=1` (the
full 3024x1964 panel instead of 3024x1890 below the notch), boots the kernel, DTB and
`boot/initramfs-rw.cpio.gz` over the resident proxy with `initcall_blacklist=__asahi_init`, and
waits for SSH (ed@192.168.188.39). Omarchy's bar keeps clear of the notch on its own: omarchy-mac's
`/usr/share/omarchy-platform/display-cutouts.json` describes the 3024x1964 eDP panel (top 64
rows), which needs the panel to be eDP (9dee12b1266c). Kernel and DTB come from
`/tmp/opencode/aurora-build-j714c-swap` (linux-aurora `t6050-j714c`, `O=` that directory,
`make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- Image.gz apple/t6050-j714c.dtb`).
Firmware, resident m1n1 and network setup: `TEST-LOOP.md`.

## What works

| Feature | In Omarchy | Where |
|---|---|---|
| 18 CPUs | `nproc` 18 | linux-aurora c04e453c26ac (MPIDRs) |
| CPU frequency, all three clusters | schedutil, 1.34-4.38 / 4.61 GHz | e0a190841586 |
| zram swap, Landlock (pacman sandbox) | `/dev/zram0`, `pacman -Sy` | 13c28edbabb6 |
| Software rendering on all cores | llvmpipe (mesa-aurora 20261031) | Omarchy package |
| Keyboard backlight | Ctrl+F1 / Ctrl+F2 | 594f4b3a49ec |
| Power button | opens the power menu | 4602eba4b9d2, 0fbd859e287d |
| Lid | close locks the session | 4602eba4b9d2, 9dee12b1266c |
| Clock | rtc0 sets the system time at boot | 4602eba4b9d2 |
| Full panel with the notch | 3024x1964 eDP-1, the bar's center beside the notch | `omarchy_boot.sh` (m1n1 `asahi,show-notch=1`), 9dee12b1266c |
| Battery and charger | battery level and state in the bar, battery icon when unplugged | 68d2fe0a8e7f, 0bc84cc4a6b2 |
| Sensors | `sensors`: fans, temperatures, voltages, power | c5b0600d19a4 |
| Sleep | lid close sleeps (s2idle), lid open wakes to the lock screen, network back | 17b3cc9ca3a6, 9f8535b38fcb |

## Settings on the Mac

- `/etc/sudoers.d/ed-reboot`: `ed ALL=(root) NOPASSWD: /usr/bin/systemctl reboot`, so
  `omarchy_boot.sh` can reboot over SSH.
- `/etc/sudoers.d/ed-sleeptest`: `/usr/bin/tee` on `/sys/power/state`, `pm_test`,
  `pm_print_times` and `pm_debug_messages`, for the sleep tests below.

The lid bindings are Omarchy's own: `default/hypr/bindings/utilities.lua` binds both
"Lid Switch" and the SMC's "Apple SMC power/lid events". The lock needs the panel to be eDP
(9dee12b1266c): Omarchy treats any other connector as an external monitor and skips the lock.

## Battery

The m1n1 proxy cable feeds about 2.4 W over USB-C, and the SMC counts it as a connected power
source (`macsmc-ac` online, `input_power_limit` 2375000). The bar shows the battery icon only
with the MagSafe and the proxy cable both out.

## Sleep tests

Drivers through suspend and resume without real sleep (5 s, then resume), over SSH:
```
echo 1 | sudo tee /sys/power/pm_print_times
echo devices | sudo tee /sys/power/pm_test
echo freeze | sudo tee /sys/power/state
echo none | sudo tee /sys/power/pm_test
```
`dmesg` then shows every device's suspend and resume call. Run it detached (`nohup`): the
network adapter suspends with the rest. Real sleep: close the lid; `/sys/power/pm_wakeup_irq`
names the wake interrupt (the SMC's, 59, for the lid).

## Not yet

- GPU: the asahi driver stays off (`initcall_blacklist=__asahi_init`); GPU.md.
- CPU die temperature: no sensor key for it on T6050 yet.
- Audio, Wi-Fi and Bluetooth, display brightness.
- Power use while asleep: not measured.
- Boot from disk: ready, not registered (below). Every boot still goes over the proxy cable.

## Boot from disk (ready, postponed)

Postponed until the m1n1 work for Wi-Fi and the display controller is in, so stage 1 is
registered once. Stage 1 loads the kernel from the ESP itself (`boot=`), so the secondaries start
from the image iBoot loaded; the 15 s proxy window keeps the cable loop.

- m1n1: forks/omacom-m1n1 `t6050-aurora` @ 53653157e6da, `make CHAINLOADING=1 RELEASE=0` with
  `M1N1_VERSION_TAG=160b644c-diskboot` (0x420000), then
  `tools/fill_stage1_config.py --esp-partuuid 6790ddc4-e993-42c2-8135-807df1548aaf --window-ms 15000`,
  then these lines and four NUL bytes appended, padded to 64 KiB (0x430000, the largest stage 1
  measured to boot on mBoot-20457.60.65):
  ```
  boot=6790ddc4-e993-42c2-8135-807df1548aaf;aurora/linux/Image.gz;aurora/linux/t6050-j714c.dtb;aurora/linux/initramfs-rw.cpio.gz
  chosen.bootargs=console=tty0 pd_ignore_unused printk.time=1 initcall_blacklist=__asahi_init
  chosen.asahi,show-notch=1
  ```
  On the Mac: `"Omarchy - Data"/Users/Shared/m1n1-diskboot.bin`, sha256 `edef93200609…`.
- ESP (nvme0n1p3, /boot/efi): `aurora/linux/Image.gz` (6872745564…), `t6050-j714c.dtb`
  (11abc8bfe8…), `initramfs-rw.cpio.gz` (f5d5e2312b…), from the swap build of 2026-11-05.
  Refresh them when the kernel changes.
- To switch on, from Omarchy's paired recovery:
  ```
  kmutil configure-boot -c "/Volumes/Omarchy - Data/Users/Shared/m1n1-diskboot.bin" --raw --entry-point 2048 --lowest-virtual-address 0 -v "/Volumes/Omarchy"
  ```
  Rollback: the same command with `m1n1-omacom-160b644c.bin`.

