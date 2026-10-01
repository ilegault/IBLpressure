# 13: Bench check on the real T7 and the Windows build

**What to build:** The developer confirms on the beamline PC, with the real T7,
what CI cannot: the Link states under a real unplug, smooth long spans over a long
run, and a working exe from the new `src/` layout.

**Blocked by:** 12

**Status:** done

**Runner:** developer

**Auto-merge:** no

## Acceptance criteria

- [x] `build.bat` completes, `verify_build.py` passes, and `dist\IBLpressure\IBLpressure.exe`
  starts, finds LJM, and connects.
- [x] Unplug the T7's USB for ~15 s at 1 Hz: the dot goes amber within ~3 s with
  `Late · no sample for …`, cells show STALE with `last …, N s ago`, then red/
  reconnecting; plug back in → green with `Recovered at … after a … s gap` for 10 s,
  and the plot shows a break over the gap.
- [x] Leave it running ≥ 12 h, then switch to 12 hours and 24 hours: the window
  stays responsive (dragging, switching tabs, toggling channels), and the status
  stays green the whole time.
- [x] Restart mid-day: today's CSV keeps growing (no second header) and the plot
  reloads the last 24 h.
- [x] Open *Help* and read it as an operator would; note anything unclear under
  `## Comments` for a follow-up.

## Comments
