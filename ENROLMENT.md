# Enrolling stage 1 on the M5 Max (J714c)

Enrolment registers the program the Mac's firmware starts for the Omarchy
volume. It is a one-time step from the Omarchy stub's recovery system, with
the owner password. Today the registered program is the proxy-only m1n1
(`m1n1.bin`); after enrolment it is stage 1, which loads stage 2 and the
kernel from the EFI partition and boots Linux from the disk without a cable.

Only stage 1 is enrolled. Stage 2, the kernel, the device tree, the initramfs
and the root filesystem are files on the disk and are updated without recovery.

## The images

Both are in `boot-esp/`, built from forks/omacom-m1n1 (branch t6050-aurora)
with `RELEASE=1 CHAINLOADING=1`, default logo (the Aurora logo exceeds the
0x120000 stage-1 file limit), filled with `tools/fill_stage1_config.py`:
EFI partition PARTUUID `6790ddc4-e993-42c2-8135-807df1548aaf`, stage 2 path
`aurora/stage2.bin`.

| File | Proxy window | sha256 |
|---|---|---|
| `m1n1-stage1-filled-15s.bin` | 15 s on every boot; a USB host can take the proxy in that window | `1646a851f9e4ab38827aaf8e645638b49589181b731736794f033c797e4a065c` |
| `m1n1-stage1-filled-nowait.bin` | none; straight to stage 2 | `a7924c82156ddcdff90c07fb3f6e5142c5bd3ac2062ec187d1fb27524c50e8ab` |

The 15 s image is the one tested on 2026-10-25 (RAM-vectored over the
proxy: stage 1 → ESP → stage 2 → kernel → prompt in 25 s). Enrol it first.

## Steps

1. Copy the image to the Mac, from this machine:

   ```bash
   scp /home/ed/dev/omarchy/kernel/boot-esp/m1n1-stage1-filled-15s.bin ed@ed-mac.local:"/Volumes/Omarchy\ -\ Data/Users/Shared/stage1.bin"
   ```

2. Check it on the Mac (macOS or recovery Terminal):

   ```bash
   shasum -a 256 "/Volumes/Omarchy - Data/Users/Shared/stage1.bin"
   ```

   Expected: `1646a851f9e4ab38827aaf8e645638b49589181b731736794f033c797e4a065c`

3. Boot the Omarchy stub's recovery (the same way as for the first m1n1
   enrolment) and run, with the same volume path as then:

   ```bash
   kmutil configure-boot -c "/Volumes/Omarchy - Data/Users/Shared/stage1.bin" --raw --entry-point 2048 --lowest-virtual-address 0 -v "/Volumes/Omarchy"
   ```

   It asks for the owner password.

4. Boot: choose Omarchy in the startup picker. Stage 1 waits 15 s for a USB
   host, loads `aurora/stage2.bin` from the EFI partition, stage 2 loads
   `aurora/linux/Image.gz`, `t6050-j714c.dtb` and the initramfs named in its
   `boot=` line, and the kernel starts.

## Behaviour and rollback

- The USB cable to the development machine can stay connected; nothing takes
  the proxy unless a proxy tool is run during the 15 s window.
- If `aurora/stage2.bin` is missing or malformed, stage 1 falls back to the
  proxy. A kernel that hangs needs a power-button reset (hold the power
  button).
- Rollback: the same kmutil command with the old `m1n1.bin`. Keep that file
  where it is.
- Changing stage 2, the kernel or the root never needs recovery; only a new
  stage 1 does.
- Switching to the no-wait image later is the same procedure with
  `m1n1-stage1-filled-nowait.bin`.

## State of the EFI partition

See `boot-esp/aurora/` for the exact files. `stage2.bin` carries the
`boot=` line and `chosen.bootargs`; `stage2-root.bin` is the variant that
boots the btrfs root (`root=PARTUUID=44527dff-05a1-4ad4-9199-e9287225e201
rootflags=subvol=@`) once the root filesystem is installed.
