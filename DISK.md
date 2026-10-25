Todos for Linux to use the disk properly, in order:

Find which power domains must stay firmware-owned. Boot with half the domains handed back to the kernel, then halve again, until the one or two that break the storage coprocessor are known. Then mark only those in t6050-pmgr.dtsi. Until this is done every NVMe boot needs the test dtb.
Read test. Read the first megabytes of the LINUX partition and the whole partition once, check the ExFAT signature and the throughput, and check in /proc/interrupts that the NVMe interrupt fires rather than the driver polling.
Clean shutdown. Today every boot ends in a watchdog reset with the controller still running. Writes need the NVMe shutdown notification and a wait for the controller to acknowledge it before the reset. The quirk note in the driver already records a write that was reverted after an abrupt reset on this family.
Write test, limited to the LINUX partition. The initramfs gets the ext4 tools, the kernel config gets ext4 and vfat. Steps: check the partition’s size matches the known block count before touching it, format it ext4, mount, write a file with a known checksum, sync, clean shutdown, reboot, mount again, verify the checksum. The kernel sees the whole disk, so the only device name the scripts ever use is the third partition.
Strip the instrumentation. Remove the traces and the two module parameters, turn the chip checks in the RTKit code into hardware flags like the NVMe driver already has, and recommit on both forks. This is what makes the two branches PR-ready.
Then the install layout. The LINUX partition becomes an EFI system partition plus a root partition, following whatever Omarchy ships on M1 and M2. That answer is still pending from the research and I will give it with the flow diagram when it reports back.

Items 2 to 4 are each one boot cycle through the proxy. Item 1 is about four boots. Nothing in this list needs the Mac touched by hand except the cold power cycles the loader sometimes demands.

The commits and the todo list above are the full answer. The boot-chain write-up with the diagram follows as soon as the research agents report.