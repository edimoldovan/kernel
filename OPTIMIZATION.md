# After the login from disk: speed and hardware on the M5 Max (J714c)

Once the root boots to a login, the work changes from "boot path" to
"drivers", one per piece of hardware, and the loop gets faster because each
test is a file copy to the EFI partition instead of a cable upload.

## In this order

1. **Speed on the one core: cpufreq.** DONE 2026-10-26: cluster 0 runs
   1.344 to 4.38 GHz under schedutil (loader cluster table, kernel OPP
   table and cpufreq node, cpu ids fixed to the MPIDR affinity 0x40000+n;
   busy loop 0.50 s -> 0.27 s). The loader prints that the chip is
   unsupported for frequency setup, so the core runs at its boot clock.
   Adding the T6050 tables to the loader and the kernel's cpufreq driver
   lifts that. Contained work.
2. **USB host.** USB 2.0 host works on port 2 (2026-10-26 19:17, four boots
   in a row); port 0 is described the same way and under test. The loader
   leaves the free ports in USB 2.0 host mode before the jump
   (usb_t6050_host_prep: port bring-up, usb2phy host bits, gadget stopped,
   core reset, port capability host, PIPE parked, connection verified with up
   to three attempts; the result is recorded in /chosen/apple,t6050-usbprep).
   The kernel binds the generic xHCI driver with the port's two DARTs
   (t6050-j714c-usb2.dtsi); the ATC CIO domains are firmware-owned in
   t6050-pmgr.dtsi because the kernel's power-on of them broke the xHCI
   reset. A USB 2.0 stick enumerates at high speed (usb-storage).
   USB 3 and USB4 need the T6050 Type-C PHY generation (44 register windows,
   tunables AUS40CMN/CIO4PLL/LN*_RX_CFG_TX_OF_RXCLK) in
   drivers/phy/apple/atc.c plus a loader tunable table; the full port
   description for that is t6050-j714c-usb.dtsi (not included).
   The ESP carries it since 2026-10-26 19:55 (stage 2 with the prep, usb2h
   kernel, two-port dtb; boot-esp/ mirrors the files). The stage 2 image
   chainloaded from the stage 1 proxy boots the kernel from the ESP to the
   disk-root login prompt (20:49); the USB lines of that boot are in its
   journal, not seen on camera. Not exercised: stage 1's own handoff to the
   ESP stage 2 after its window; with the cable attached and the boot tools
   running on Omarchy, stage 1 sat in its proxy for 10 min three times
   (cause not isolated: the window ends in the proxy once a host request
   arrives). Open: USB 2.0 Ethernet for
   pacman and SSH; hot-plug after boot.
3. **Display driver.** Today the kernel draws into the framebuffer the loader
   left. The real display driver gives brightness, mode setting and later the
   compositor. Aurora has the M5 Air path to copy from.
4. **Audio, then sleep.** Each a known Asahi driver that needs this chip's
   nodes and firmware handoff.

## Not in our hands

- **All cores.** A known Apple firmware issue on the M5 Pro and Max, reported
  to Apple by several groups; no loader can work around it today
  (CPU-START.md).
- **GPU.** Needs Aurora's M5 driver work, not public yet.
- **Wi-Fi and Bluetooth.** New chip; the Omarchy team announced
  reverse-engineering work, nothing released.

The daily-driver line: login from disk, cpufreq, USB and network, display,
audio, sleep. Cores, GPU and Wi-Fi arrive from upstream when they arrive, and
the boot chain boots them unchanged.
