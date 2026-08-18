# IBL Pressure

Live vacuum readout for the beamline: a LabJack T7 reads the analog outputs of
the INFICON VGC083A gauge controllers, this program turns those volts into
pressures, shows them, plots them, and logs them.

One window. One folder. One executable.

---

## What it does

* Reads **AIN0 - AIN13** on a LabJack T7 over USB
* Converts each voltage to a pressure in **Torr**
  * Ion gauge (VGC083A Analog Output 1, `IG LOG N - 10`): `P = 10^(V-10)`
  * Convectron (Analog Output 2, `CG1 NON-LIN`): the Granville-Phillips
    S-curve, three segments, coefficients from the VGC083A manual
  * Anything above the fault threshold reads **Gauge Fault**
* Shows all 14 channels live in a table, faults highlighted red
* Plots any subset of them on a shared log-scale graph with an adjustable
  time span
* Writes every pressure to a CSV every 10 seconds, **one file per day**,
  named `YYYY-MM-DD.csv`

## Channel map

| AIN | Location         | VGC083A output | Gauge      |
|-----|------------------|----------------|------------|
| 0   | SNICS            | Analog Out 1   | Ion        |
| 1   | SNICS            | Analog Out 2   | Convectron |
| 2   | Injector         | Analog Out 1   | Ion        |
| 3   | Injector         | Analog Out 2   | Convectron |
| 4   | Post-accel       | Analog Out 1   | Ion        |
| 5   | Post-accel       | Analog Out 2   | Convectron |
| 6   | Switching Magnet | Analog Out 1   | Ion        |
| 7   | Switching Magnet | Analog Out 2   | Convectron |
| 8   | Left Chamber     | Analog Out 1   | Ion        |
| 9   | Left Chamber     | Analog Out 2   | Convectron |
| 10  | Middle Chamber   | Analog Out 1   | Ion        |
| 11  | Middle Chamber   | Analog Out 2   | Convectron |
| 12  | Right Chamber    | Analog Out 1   | Ion        |
| 13  | Right Chamber    | Analog Out 2   | Convectron |

Change it in `ibl/channels.py` if the wiring ever moves.

---

## Running it from source (PyCharm)

```
pip install -r requirements.txt
python main.py
```

No LabJack on your desk? Tick **Simulation mode** in the top-left, or start it
with `python main.py --simulate`. It generates believable gauge data so you can
work on the GUI anywhere.

## Building the .exe

Double-click **`build.bat`**. It installs the dependencies, runs the conversion
self-check, and calls PyInstaller.

Result: **`dist\IBLpressure\IBLpressure.exe`**

Copy that *whole* `IBLpressure` folder to the control PC — the .exe needs the
DLLs sitting next to it. That is what `--onedir` means, and it starts noticeably
faster than a single-file build.

### The one thing the .exe cannot bundle

The LabJack **LJM** library is a native Windows driver, not a Python package.
Install it once on any PC that will talk to real hardware:

> https://support.labjack.com/docs/ljm-software-installer

Without it the program still opens; it just says the driver is missing and you
can only use Simulation mode.

---

## How it is wired together

```
main.py
   |
   +-- ibl/config.py       Settings dataclass, saved to settings.json
   +-- ibl/channels.py     which AIN is which gauge
   +-- ibl/conversion.py   volts -> Torr, and the fault rules
   +-- ibl/daq.py          DaqWorker: talks to the T7 on its own thread
   +-- ibl/csvlogger.py    daily CSV file
   +-- ibl/mainwindow.py   the window: table, plot, settings panel
```

The flow each tick:

```
QTimer (in the DAQ thread)
   -> read AIN0..AIN13 in one LJM call
   -> convert() each voltage to a Reading
   -> emit sample  ---> MainWindow
                          |-- update the table
                          |-- append to the plot history
                          |-- every 10 s, write a CSV row
                          '-- redraw the plot
```

The acquisition runs on a **separate thread** on purpose: if the T7 is slow to
answer or gets unplugged, the window keeps responding instead of going white.
If five reads in a row fail, it closes the handle and tries to reconnect by
itself.

---

## Settings

Everything defaults to what the design document asks for. Open the **Settings**
strip at the bottom to change any of it; changes apply immediately and are
remembered in `settings.json` next to the executable.

| Setting | Default | Notes |
|---|---|---|
| Connection | USB | or Ethernet / Any |
| Identifier | ANY | serial number or IP, ANY = first T7 found |
| Resolution index | 8 | T7 ADC resolution, higher = quieter but slower |
| Update rate | 1 Hz | how often the table and plot refresh |
| Gauge fault above | 10.0 V | see below |
| Keep history | 6 hours | how much data stays in memory for the plot |
| CSV logging | on, every 10 s | one file per day |
| CSV folder | `data\` next to the .exe | |
| Record raw volts | off | adds 14 voltage columns to the CSV |

### Why the fault threshold is 10 V, not 11 V

The VGC083A manual says the output goes **above +11 V** on a gauge fault. But a
LabJack T7 analog input saturates just past 10 V, so it physically cannot report
11. Ten volts is a safe trip point because neither gauge ever legitimately gets
there: the ion gauge output tops out at **9 V** (1e-1 Torr) and the Convectron at
**5.659 V** (1000 Torr). Anything at 10 V is a fault, an unplugged gauge cable,
or a controller that has switched its output high.

---

## Checking the maths

```
python -m ibl.conversion
```

This replays the pressure/voltage reference table printed in the VGC083A manual
through the code and prints the error at every point, checks that the three
Convectron segments join up at 2.842 V and 4.945 V, and re-runs the manual's own
worked example (0.3840 V -> 1.0E-03 Torr).

Everything above 5 mTorr matches the manual to better than **0.75 %**. Below
that the agreement loosens to a few percent — that is the gauge, not the code:
the entire decade from 1e-4 to 1e-3 Torr spans less than one millivolt of the
S-curve. It is also the region where you should be reading the ion gauge anyway.

---

## CSV format

```
timestamp,epoch_s,SNICS IG (Torr),SNICS CG (Torr),Injector IG (Torr),...
2026-08-18T09:14:20,1787065638.075,Gauge Fault,3.61E-03,2.71E-04,...
```

Faulted channels are written as the words `Gauge Fault` rather than a number, so
a bad gauge can never be mistaken for a real reading later. Each row is flushed
to disk immediately, so a power cut costs you at most the last 10 seconds.
