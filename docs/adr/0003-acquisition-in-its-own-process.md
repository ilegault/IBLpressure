# ADR 0003 — Acquisition runs in its own process so it can be restarted

**Status:** accepted
**Date:** 2026-10-07

## Context

About once a day on the beamline PC the Link goes Down and stays Down: every
reopen fails with LJM error 1298 `LJME_ATTR_LOAD_COMM_FAILURE` ("Retrying every
5 s" forever). Only a PC reboot brings it back. The T7 has its own power supply,
so a reboot does not power-cycle it; what a reboot resets is the PC side — the
USB host, its driver, and the LJM library loaded in our process. The USB cable is
very long and runs across the accelerator, which LabJack names as the classic
source of transients that make a USB host lose a device.

The worker only ever retried `ljm.openS`. LJM is a DLL loaded once per process;
it cannot be unloaded and reloaded from inside the app, so a wedged LJM state
survives every in-app retry. The same design also let one stuck LJM call block
Connect/Disconnect and make Quit hang, because the window waited on the worker
thread with no time limit.

## Decision

1. **The T7 conversation runs in a separate child process** (open, configure the
   AINs and the Device watchdog, read, close — and Simulation mode, so tests take
   the real path). It sends Samples and Link events to the window as messages.
2. **Everything else stays in the window process**: History, plot, Daily CSV,
   LinkMonitor, Link log. Restarting acquisition never touches them.
3. **Escalation** climbs Reopen → Library reset (`ljm.closeAll`, reopen) →
   Acquisition restart (kill and respawn the child, which loads LJM afresh), one
   step at a time, then shows the operator a by-hand message while it keeps
   retrying Acquisition restart.
4. **The window never waits on LJM.** Disconnect, Connect and Quit stop the
   child with a short timeout and kill it if it does not answer, so Quit always
   exits and never leaves a process holding the T7.

## Alternatives considered

- **Keep the QThread and add `ljm.closeAll()`** — cheap, but cannot reload the
  DLL and cannot rescue a call that never returns.
- **Reset the USB device through Windows** (disable/enable in Device Manager) —
  needs admin setup on the beamline PC. Deferred until the Link log shows that
  Acquisition restart is not enough.
- **Switch the T7 to Ethernet** — LabJack's recommended long-term fix and being
  pursued separately at the hardware level. The process split is still wanted:
  recovery should not depend on which cable is in use.

## Consequences

- Readings cross a process boundary (a pipe/queue); a Sample is still whole or
  absent.
- The PyInstaller build must support a child process (`multiprocessing`
  `freeze_support`), and the bench check must cover it.
- Unit tests drive Escalation against a scripted fake LJM; only the bench check
  touches the real T7.
