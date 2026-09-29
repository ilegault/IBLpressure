# ADR 0002 — Two-tier History, min/max decimation, throttled redraw

**Status:** accepted
**Date:** 2026-09-28

## Context

At 1 Hz, a 24 h plot held about 86 400 points per curve, ~600 000 for seven
curves. Every second the app converted each whole slice from a Python list to a
numpy array and handed it all to pyqtgraph, which redid the log transform and
downsampling and drew it antialiased. The app was smooth at short spans and froze
at 12 h and 24 h. That freeze also delayed the stale watchdog, which is part of why
the status light went red on a working system.

At 24 h on a plot ~1 000 px wide, one pixel covers ~86 s. Redrawing 600 000 points
every second draws a picture that can only change about once a minute and a half.
At the 10 Hz maximum rate, a full-resolution 24 h History would also need
~200 MB of memory.

## Decision

1. **History has two tiers.** The Raw tier keeps every Sample for the most recent
   hour. Older data is folded into the Summary tier: the minimum and maximum of each
   10-second bucket, per Channel. History is capped at 24 h, matching the Daily CSV.
2. **The plot draws at most two points per Plot bucket** (one pixel of time): that
   bucket's minimum and maximum, in time order. A bucket with no finite data is a
   break in the line.
3. **Long spans redraw only when a pixel's worth of time has passed**:
   the redraw interval is `max(sample interval, span ÷ plot width in px)`. The table
   still updates on every Sample.
4. **The operator is told**, on the plot (a caption when the span reaches past the
   Raw tier) and in the Help dialog.

## Why min/max and not averaging

A short pressure burst is what someone scanning 24 h is looking for. An average
per bucket would flatten it; min/max keeps it.

## Consequences

- Zooming into an event older than one hour shows 10 s resolution. The Daily CSV
  is the full-resolution record at its Write every interval.
- Memory is bounded (~20 MB) whatever the sample rate.
