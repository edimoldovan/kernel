# USB4 item 3 — power the CIO domain without breaking the USB controller

The recorded failure: when the kernel powers the CIO power domains, the xHCI
controller's reset times out. This is understood now, and there is a sequence
that avoids it (confirmed live on the cable).

## The cause
Powering the CIO domains is not enough on its own. The PHY core sits behind a
reset / clamp / sleep gate; while those are asserted, any access to the core
block faults, and that is what makes the controller's reset hang. Powering the
domain without releasing that gate leaves the block in the faulting state.

## The sequence that works (confirmed live)
1. Power the domains (write 0xf to bits[3:0], poll bits[7:4]==0xf). Port 0:
       atc0_common   0x280600208
       atc0_cio      0x280600280
       atc0_cio_usb  0x280600340
       atc0_cio_auss 0x280600348
   (ports 1/2 are the same registers at their own offsets.)
2. Release the gate at the controller 0x2a3200000:
       clear bit 2 (clamp), set bit 0 (sleep-small), set bit 1 (sleep-big),
       set bit 3 (APB reset), set bit 4 (main reset)   -> value 0x1b
3. The core at 0x2a3000000 is then reachable and reads cleanly.

## Evidence
- With only the power + partial release, the core faulted (this is the timeout).
- With power + full release (0x1b), the core comes up and its status register
  holds live values.
- Powering one port's CIO did not disturb another port's USB controller.

## To prove it against the controller break
Reproduce the kernel path (power the CIO domain for the active port, then start
the controller) with step 2 inserted before the controller reset, and confirm
the reset completes. `../../usb3-usb4/mac_ctl.py` gives unattended board control
(reboot + reconnect) to iterate safely.

## Live result: power+release is safe; controller readiness is gated by the PLL
On port 0: powered the CIO domains + full release (0x1b), flipped the controller
to host, issued the xHCI reset. The reset bit self-cleared (no crash, no
timeout) BUT USBSTS kept CNR set (controller-not-ready = 0x801). So:
- Powering CIO with the release does NOT crash the controller.
- The controller does not become ready until the SuperSpeed PHY provides a pipe
  clock, i.e. until the AUSPLL is locked. So the "break" is really downstream of
  the (still-missing) PLL lock, not a power-ordering crash.
Conclusion: CIO power is safe in this order; controller readiness needs the PLL.
