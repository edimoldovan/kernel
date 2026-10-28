# USB4 item 2 — start the PHY's management core

Good news: this is NOT a firmware image to find and upload. The PHY's management
core runs from on-chip ROM; it is started with a register write.

## What it is
The management core is the `acio-phy-cpu` coprocessor (type `iop,mxwrap`):
    ctrl window   0x2a3140000 (size 0x4000)
    second window 0x2a3148000 (size 0x4000)
    IRQs          841-844   (port 0; ports 1/2 at the usual +offsets)

## The start step
The Linux driver starts it by reading ctrl+0x40, setting bit 0, writing back:
    0x2a3140040 : set bit 0
(i.e. read-modify-write, OR 0x1). It is done late in the PHY bring-up, after the
common block and PLL are up. There is no blob to load for this core.

## Status
This folds into the PHY bring-up (see ../cio-power and the SuperSpeed notes):
it is a single register step, reachable once power + reset release are done.

## Live result: CONFIRMED
After power + full reset release on port 0, the core-start register is reachable
and the run bit holds: 0x2a3140040 read 0xa0002, after OR 0x1 read 0xa0003
(bit 0 set and retained). The start mechanism works; it is a register step.
