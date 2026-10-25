# After the login from disk: speed and hardware on the M5 Max (J714c)

Once the root boots to a login, the work changes from "boot path" to
"drivers", one per piece of hardware, and the loop gets faster because each
test is a file copy to the EFI partition instead of a cable upload.

## In this order

1. **Speed on the one core: cpufreq.** The loader prints that the chip is
   unsupported for frequency setup, so the core runs at its boot clock.
   Adding the T6050 tables to the loader and the kernel's cpufreq driver
   lifts that. Contained work.
2. **USB host.** The Asahi USB stack exists; this chip needs its device-tree
   nodes and PHY setup. With USB comes Ethernet adapters, and with network
   comes pacman, Omarchy's own packages and updates from the Mac itself.
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
