# 25: Bench check: recovery on the beamline T7 and the exe

**Status:** ready-for-developer

**Runner:** developer

**Auto-merge:** no

**Blocked by:** 23

**Spec:** `.scratch/link-recovery/spec.md`
**Binding:** ADR 0003

## What to build

The developer confirms on the beamline PC, with the real T7 and the built exe,
what CI cannot: the child process starts from the exe, Escalation climbs and
recovers on real hardware, Quit never hangs, and the Link log and Daily CSV look
right afterwards.

## Acceptance criteria

- [ ] `build.bat` completes, `verify_build.py` passes, `dist\IBLpressure\IBLpressure.exe`
  starts, connects, and Task Manager shows the child `IBLpressure.exe` while Live.
- [ ] Unplug the T7's USB for more than 2 minutes at 1 Hz: the status line walks
  `Reconnecting — Reopen (attempt 1 of 3)…` → Library reset → Acquisition restart,
  then shows the Hand-off message in red; plug back in → green with
  `Recovered at … after a … s gap (<step>)` for 10 s, and the plot shows a break.
- [ ] While in Hand-off, press Quit: the window closes in under 5 s and Task Manager
  shows no `IBLpressure.exe` left. Relaunch connects without a reboot.
- [ ] `link-log\YYYY-MM.log` reads as a clear story of the above (LINK_UP with
  firmware and LJM version, the climb, one HAND_OFF, REPEATED lines, RECOVERED),
  and the Connection frame shows the recovery. Today's Daily CSV kept appending
  (one header) across the outage and the relaunch.
- [ ] In Kipling (with IBL Pressure closed), the T7's watchdog shows enabled, 60 s,
  reset on timeout. Note anything unclear under `## Comments`.

## Gate

Run in CI's order (`.github/workflows/ci.yml`):

1. `ruff check .`
2. `python scripts/check_tests_first.py`
3. `pytest -q`

## Comments
