# J714c test loop: boot a kernel, get its log back over the network

A kernel build is tested on the MacBook (J714c) by chainloading it over the resident m1n1
proxy. The Mac's own USB-C network adapter sends the test report and the full kernel log to
this machine (Omarchy). The camera on the Mac's screen is the fallback for a boot that dies
before the network is up.

## Setup

| What | Where |
|---|---|
| m1n1 proxy cable (resident proxy `...g7cde...`) | Mac right port (port 2) |
| USB-C network adapter, ASIX AX88179B (0b95:1790), cabled to the router | Mac left rear port (port 0, USB 2.0 host) |
| USB3 stick, SanDisk Extreme Pro 1 TB (0781:55e8), plugged in directly | Mac left front port (port 1) |
| Charger | MagSafe, left side behind the two USB-C ports |
| Omarchy | 192.168.188.35, port 8000 open in ufw for 192.168.188.0/24 |
| BRIO camera at the Mac's screen | /dev/video0 |

On the Mac the adapter binds `cdc_ncm` as eth0 (6c:6e:07:41:d2:14) and gets 192.168.188.39
over DHCP from the router.

## One boot

1. Build: `make -C forks/linux-aurora O=/tmp/opencode/aurora-build-j714c ARCH=arm64
   CROSS_COMPILE=aarch64-linux-gnu- -j$(nproc) Image.gz dtbs` (from /home/ed/dev/omarchy,
   in the background).
2. Start the receiver: `python3 kernel/tools/net_recv.py OUT.txt 400`. It accepts one
   connection on port 8000 from 192.168.188.0/24, saves the bytes and exits.
3. Boot:
   ```
   IMG=/tmp/opencode/aurora-build-j714c/arch/arm64/boot/Image.gz \
   DTB=/tmp/opencode/aurora-build-j714c/arch/arm64/boot/dts/apple/t6050-j714c.dtb \
   IRD=/home/ed/dev/omarchy/kernel/boot/initramfs-net.cpio.gz \
   WDT=170 EXTRA="pd_ignore_unused printk.time=1" \
   /home/ed/dev/omarchy/kernel/tools/boot_t6050.sh TAG
   ```
   `boot_t6050.sh` chainloads `forks/omacom-m1n1/build/m1n1.macho`, boots the kernel with
   `tools/linux.py`, then waits for the watchdog to bring the Mac back to the proxy (about
   3 minutes). Call it by its absolute path: it builds its log paths from `$0`.
4. About 10 s after the kernel starts, the report lands in OUT.txt.

Several boots in a row: `kernel/tools/net_boots.sh TAG COUNT` (reports in
`log/net-TAG<n>.txt`, one summary line per boot; IMG, DTB, IRD, WDT and EXTRA can be set as
above).

Rules:
- Chainload only, over the resident proxy. Never write the Mac's EFI partition.
- The Mac must start from a reset. After a `t6050_phy_power_test.py` run the proxy is still
  up but CIO is on and the PHY CPU is running (the harness disarms its watchdog and does not
  reboot): a kernel booted on top of that fails. The watchdog reset at the end of each kernel
  boot leaves a clean state for the next one.
- `WDT` is the kernel's AP watchdog (`t6050_wdt=`, at most 178 s); 0 leaves the Mac in Linux
  until it is reset by hand.
- `pd_ignore_unused` keeps the kernel from switching off power domains it has no driver for;
  every SuperSpeed result so far was taken with it.

## The network report (`initramfs/init-net`)

`boot/initramfs-net.cpio.gz` is the stock `boot/initramfs.cpio.gz` followed by a gzip cpio of
`init` (= `initramfs/init-net`) and `udhcpc.sh`; the later /init wins. Repack after editing:
```
D=$(mktemp -d); cp initramfs/init-net $D/init; cp initramfs/udhcpc.sh $D/
(cd $D && printf 'init\nudhcpc.sh\n' | cpio -o -H newc | gzip -9) > /tmp/overlay.cpio.gz
cat boot/initramfs.cpio.gz /tmp/overlay.cpio.gz > boot/initramfs-net.cpio.gz
```
init-net: waits for eth0 and /dev/sda, DHCP (`udhcpc.sh` sets address and route), then
writes the report:
- address, link speed, ping to the router;
- every USB device with speed, version, maker, product;
- the xHCI port registers of port 1 from debugfs
  (`/sys/kernel/debug/usb/xhci/2aa280000.usb/ports/port01|02/portsc`), before and after the
  tests;
- read-only stick tests: blkid, 2 GiB direct read (`dd ... iflag=direct`), sha256 of the
  first 256 MiB twice;
- the whole `dmesg`.

It sends the report once with `nc 192.168.188.35 8000` (retried for 60 s), then gives the
console shell. Nothing listens on the Mac and nothing it sends is executed here. A remote
shell over the network was tried and refused by the permission check; the report is one way
by design.

Changing what the Mac reports = edit `init-net` and repack. Changing what the kernel logs:
- `printk.time=1` (in EXTRA) adds timestamps;
- `dyndbg="file hub.c +p; file xhci-hub.c +p; func handle_port_status +p"` adds the USB hub
  and xHCI port events (every PORTSC change with its value). These are debug-level: they go
  to dmesg, not to the screen.

## Fallback: the camera

For a boot that hangs before the report:
- Video of the whole boot (the BRIO's MJPEG tops out at 1920x1080):
  `ffmpeg -f v4l2 -input_format mjpeg -video_size 1920x1080 -i /dev/video0 -t 150 -vf fps=4
  -c:v libx264 -crf 16 -preset veryfast boot.mp4`, started together with the boot.
- Frames: `ffmpeg -i boot.mp4 -vf fps=2 f%03d.png`; find lines with `tesseract fNNN.png -`
  (grep the text), crop and enlarge a region with `ffmpeg -vf crop=W:H:X:Y,scale=...` to read
  it.
- One still: `tools/snap.sh NAME`.

## Related

- `USB-BRINGUP.md`: the port 1 SuperSpeed sequence, the proxy harness
  (`tools/t6050_phy_power_test.py`) and every boot's result.
- `README.md`: the loader, kernel branches and how the Mac boots Linux at all.
