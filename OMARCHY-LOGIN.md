# Omarchy login on the M5 Max (J714c)

The full Omarchy root boots read-write over the m1n1 proxy and logs in through SDDM into
Hyprland. Every feature below works in that login; this is the bar for each new one.

## Boot

```
/home/ed/dev/omarchy/kernel/tools/omarchy_boot.sh TAG
```

It reboots the Mac over SSH if Linux is running, boots the kernel, DTB and
`boot/initramfs-rw.cpio.gz` over the resident proxy with `initcall_blacklist=__asahi_init`, and
waits for SSH (ed@192.168.188.39). Kernel and DTB come from
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
| Lid | close locks the session | 4602eba4b9d2, 9dee12b1266c, binding below |
| Clock | rtc0 sets the system time at boot | 4602eba4b9d2 |

## Settings on the Mac

- `/etc/sudoers.d/ed-reboot`: `ed ALL=(root) NOPASSWD: /usr/bin/systemctl reboot`, so
  `omarchy_boot.sh` can reboot over SSH.
- `~/.config/hypr/bindings.lua` (backup `bindings.lua.bak.*` next to it): Omarchy binds the lid
  as `switch:on:Lid Switch`; the SMC switch is named "Apple SMC power/lid events", so the same
  two bindings are added for that name:
  ```
  o.bind("switch:on:Apple SMC power/lid events", nil, "omarchy-system-lid-close", { locked = true })
  o.bind("switch:off:Apple SMC power/lid events", nil, "omarchy-hyprland-monitor-clamshell", { locked = true })
  ```
  The same two lines in Omarchy's `default/hypr/bindings/utilities.lua` would cover every
  Apple Silicon Mac.

## Not yet

- GPU: the asahi driver stays off (`initcall_blacklist=__asahi_init`); GPU.md.
- SMC sensors: macsmc-hwmon finds none until the board sensor nodes are added.
- Battery, audio, Wi-Fi and Bluetooth, display brightness.
- Boot from disk: every boot goes over the proxy cable.
