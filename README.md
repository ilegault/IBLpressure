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

## Install the LabJack driver (bundled installer)

The target PC also needs the LabJack **LJM** driver — the `LabJackM.dll`
the app talks to. PyInstaller cannot bundle that system driver, so the app
ships LabJack's own installer alongside it and offers to run it on demand.

**Setup (do this once, before building):** download the LJM installer from
https://support.labjack.com/docs/ljm-software-installer-windows (the
"minimal" driver-only build is smallest) and drop the `.exe` into the
`vendor\` folder. The file name must start with `LabJack`. `build.bat`
bundles whatever is in `vendor\` into `dist\IBLpressure\`.

**What the user sees:** on a PC without the driver, an **Install driver**
button appears in the top bar. Clicking it launches LabJack's installer;
Windows asks for administrator permission; when it finishes, the user
restarts IBL Pressure and it connects. If no installer was bundled, the
app instead points them to labjack.com. Until the driver is present the
app still runs fully in **Simulation mode**.

On startup the app checks that LJM is not just *installed* but actually
*responding* (it reads the library version), and reports the result in the
status bar.

---

## Reusing this in another project

**What this pattern is called.** Shipping a dependency's own installer
inside your app and running it on first launch is a **dependency
bootstrapper** (also "prerequisite bootstrapping", or bundling a
"redistributable"). It is the same idea as a game bundling the Visual C++
runtime (`vcredist`) and installing it the first time it is needed. Two
pieces make it work: a **preflight dependency check** that asks "is the
dependency here and healthy?", and an **elevated installer launch** that
hands off to the vendor's installer (which needs admin rights). Your app
never installs anything itself — it only detects and delegates.

**The moving parts here, if you want to lift them:**

1. `ibl/driver.py` — three small, GUI-free functions:
   `check_ljm()` (is the dependency importable *and* responding?),
   `find_installer()` (glob a `vendor\` folder for the bundled `.exe`),
   `launch_installer()` (run it elevated via a Windows "runas" call).
2. `ibl/mainwindow.py` — a hidden **Install driver** button, a
   `_refresh_driver_state()` that shows it (and a message) when the check
   fails, and an `_install_driver()` handler that runs the installer.
3. `IBLpressure.spec` — a `_vendor_datas()` helper that folds
   `vendor\*.exe` into PyInstaller's `datas`, so the installer rides along
   in the one-folder build.

**To adapt it to a different dependency:** point `check_ljm()` at whatever
proves *your* dependency is alive (an import, a DLL probe, a
`subprocess` version call), keep the `vendor\` convention and the spec
helper as-is, and rename the button text. The check/find/launch split and
the "detect on startup, delegate on click, restart after" flow stay the
same regardless of what you are installing.

**Caveats worth keeping in mind:** the admin (UAC) prompt is unavoidable
for anything that installs system-wide — that is a Windows security
boundary, not a limitation you can code around. The app can't see the
driver the installer just added until it restarts, so "restart after"
is part of the flow. And the bundled `.exe` inflates your build by its own
size (LabJack's is ~18 MB), which is the price of the one-click
convenience.

---

## Code layout

```
src/ibl/
  channels.py    — AIN → location / gauge type
  conversion.py  — volts → Torr, fault rules
  csvlogger.py   — daily CSV rotation
  daq.py         — DaqWorker (separate QThread, auto-reconnects on failure)
  config.py      — Settings dataclass, settings.json load/save
  driver.py      — LJM driver check + one-click installer launch
  mainwindow.py  — the single PySide6 window
tests/           — pytest suite (run `pytest -q`)
main.py          — entry point (`python main.py`)
pyproject.toml   — package metadata, pytest and ruff settings
build.bat        — PyInstaller build script
```
