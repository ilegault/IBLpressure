# IBL Pressure

Beamline vacuum monitor. A **LabJack T7** DAQ reads the analog outputs of 7 **INFICON VGC083A** gauge controllers (14 channels total), converts volts to Torr, and displays them in a live table and scrolling log-scale plot.

---

## Channel map

Each beamline location has two gauges on consecutive AIN pairs — Ion Gauge (IG) on the even input, Convectron (CG) on the odd one.

| AIN | Location | Gauge |
|---|---|---|
| 0 / 1 | SNICS | IG / CG |
| 2 / 3 | Injector | IG / CG |
| 4 / 5 | Post-accel | IG / CG |
| 6 / 7 | Switching Magnet | IG / CG |
| 8 / 9 | Left Chamber | IG / CG |
| 10 / 11 | Middle Chamber | IG / CG |
| 12 / 13 | Right Chamber | IG / CG |

Wiring lives in `ibl/channels.py`.

---

## Conversion (VGC083A manual)

- **Ion gauge** — `P [Torr] = 10^(V − 10)`, log-linear, 0–9 V.
- **Convectron** — Three-segment S-curve (polynomial / rational), 0.375–5.659 V = 1×10⁻⁴–1000 Torr.
- Anything above the fault threshold (default **10 V**) → **Gauge Fault**.

The T7 saturates just past 10 V, so 10 V is the practical ceiling — neither gauge ever legitimately reaches it (IG tops at 9 V, Convectron at 5.66 V).

---

## GUI

- **Top bar** — Connect / Disconnect, Simulation mode, dark mode, status, CSV indicator, open log folder.
- **Table** — 14 rows, live volts + pressure + status. Fault rows go red, out-of-range amber. Checkboxes control which channels appear on the plot.
- **Plot** — Log-scale pressure vs. time, selectable span (1 min – 24 h), auto or manual Y axis.
- **Settings panel** (collapsible at the bottom) — connection type, identifier, ADC resolution index, sample rate, fault threshold, history depth, CSV options, legend toggle. All saved to `settings.json` next to the executable.

---

## CSV logging

One file per day: `YYYY-MM-DD.csv` in the configured folder (`data\` by default). Default write interval: every 10 s. Faulted channels are written as `Gauge Fault` (never a number). Optionally records raw volts too.


No hardware? Tick **Simulation mode** in the GUI — the app generates plausible drifting pressures for all 14 channels.

---

## Install labjack driver


The target PC also needs the LabJack **LJM** driver: https://support.labjack.com/docs/ljm-software-installer

Without it the app opens in Simulation mode only.


---

## Code layout

```
ibl/
  channels.py    — AIN → location / gauge type
  conversion.py  — volts → Torr, fault rules
  csvlogger.py   — daily CSV rotation
  daq.py         — DaqWorker (separate QThread, auto-reconnects on failure)
  config.py      — Settings dataclass, settings.json load/save
  mainwindow.py  — the single PySide6 window
smoke_test.py    — headless integration test
build.bat        — PyInstaller build script
```
