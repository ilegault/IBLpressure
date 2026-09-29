# CONTEXT — IBL Pressure

The vocabulary of this app. If code and this file disagree, flag it; do not
silently pick a side.

## Hardware and wiring

**Location** — a place on the beamline with its own pair of gauges: SNICS,
Injector, Post-accel, Switching Magnet, Left Chamber, Middle Chamber, Right
Chamber.

**Gauge** — one pressure sensor. Each Location has an **Ion Gauge (IG)** and a
**Convectron Gauge (CG)**. Together they are the Location's **gauge pair**.

**Channel** — one LabJack T7 analog input (AIN0–AIN13) wired to one Gauge's
controller output.

**Link** — the connection between the app and the T7. It is about the device, not
about any one gauge.

## Data

**Reading** — one Channel's voltage, its pressure in Torr (or none), and its
Gauge status, at one instant.

**Sample** — one sweep of all 14 Channels, read in a single request. A Sample
arrives whole or not at all.

**Gauge status** — the verdict on one Reading: OK, Gauge Fault, Neg Voltage, Under
range, Over range, or Use IG (Convectron below its accurate range). A Gauge status
problem belongs to its own row only; it never says anything about the Link.

**Freshness** — how long since the last Sample arrived, compared with the Late
threshold.

**Late threshold** — how long the app waits for a Sample before calling the Link
Late: *Late after N missed samples*, i.e. N ÷ sample rate seconds. N is at least 2;
the default is 3 (3 s at 1 Hz).

## Link state

Exactly one of these at any moment, shown by the status dot and the status line
together:

**Idle** (grey) — the operator has not pressed Connect, or pressed Disconnect.

**Live** (green) — connected, and the last Sample is within the Late threshold.

**Late** (amber) — connected, but no Sample within the Late threshold; also while
reconnecting.

**Down** (red) — the operator asked to connect, and the T7 cannot be opened.

**Recovery** — the moment a Sample arrives after the Link was Late or Down. The
status line reports it ("Recovered at 14:03:22 after a 7 s gap") for 10 s.

**Gap** — the stretch of time with no Samples between going Late and Recovery. The
plot shows a Gap as a break in the line, never a line drawn across it.

**Stale** — what a pressure cell shows when the Link is not Live: the word STALE,
never a number. The last value and its age move to the Status column.

## History and plotting

**History** — the pressures kept in memory for the plot, at most 24 h.

**Raw tier** — the most recent hour of History, every Sample kept.

**Summary tier** — History older than one hour, kept as the minimum and maximum
of each 10-second bucket per Channel, so spikes survive.

**Plot bucket** — the slice of time one pixel of the plot covers. Each Plot bucket
is drawn as its minimum and maximum.

## Logging

**Daily CSV** — one file per calendar day named `YYYY-MM-DD.csv`, one row every
*Write every* seconds. Restarting the app appends to the day's file. If the columns
change mid-day, the new rows go to `YYYY-MM-DD_b.csv` (then `_c`, …) so no file
ever mixes two headers.

**Write every** — the CSV row interval, separate from the sample rate.
