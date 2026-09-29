# Spec — stability-and-structure

**Effort:** make IBL Pressure smooth at long plot spans, make the status light and
status line tell the truth, and put the codebase on the tests-first / CI footing
the developer's other repos use.

Vocabulary: `CONTEXT.md`. Binding decisions: `docs/adr/0001-tests-first.md`,
`docs/adr/0002-two-tier-history-and-plot-decimation.md`.

---

## 1. Problems (observed, with causes found in the code)

1. **12 h / 24 h views freeze the app.** `MainWindow._redraw_plot` runs on every
   Sample and, per visible curve, turns the full History slice (up to 86 400
   Python floats) into a numpy array and calls `curve.setData` with all of it, then
   `setXRange`, with global antialiasing on. See ADR 0002.
2. **The status dot goes red on a working system and stays red.**
   `MainWindow._check_stale` turns it red after 5 s without a Sample; nothing turns
   it green again except a reconnect (`_on_connection_changed`), and the watchdog
   can fire before the first post-reconnect Sample. A UI freeze from problem 1
   makes queued Samples look like a gap, which trips it. The 5 s limit is also
   fixed, so below 0.2 Hz the app is always "stale".
3. **The status text goes stale too.** `DaqWorker._tick` emits
   `"Read error (n): …"`; nothing clears it after the next good read.
4. **Settings changes never reach the worker's reconnect logic.** `MainWindow`
   hands `self.settings` to `DaqWorker`, then mutates it in place, so
   `DaqWorker.update_settings` compares the object with itself and `relink` is
   always false. Changing connection, identifier, resolution or Simulation while
   connected is silently ignored. Two threads also share one mutable object.
5. **Structure:** `mainwindow.py` (~1 000 lines) owns UI, settings binding, History,
   plotting, CSV cadence, link state, theme and driver install; theme colours are
   module globals rewritten with `global`; `csvlogger` imports `Sample` from `daq`
   (which imports PySide6); the "IG = `pair*2`, CG = `pair*2+1`" layout is
   hard-coded in ~6 places; errors are swallowed (`Settings.save`, `closeEvent`);
   `app_dir()` is duplicated in `driver.py`; no tests, no CI.

## 2. Decisions

### Link state (tickets 05, 06)

- One pure `LinkMonitor` (`src/ibl/link.py`) decides the Link state — Idle, Live,
  Late, Down — and returns a `LinkView(state, dot_color, text)` from `view(now)`.
  The dot and the status line are both drawn from that one view, refreshed every
  0.5 s and on every event.
- Status texts, exactly:
  - Idle: `Not connected. Press Connect.`
  - Live: `Live · {description} · last sample {age:.1f} s ago`
  - Live, within 10 s of Recovery: `Live · Recovered at {HH:MM:SS} after a {gap:.0f} s gap`
  - Live with a current read error: `Live · {description} · read error: {message}`
  - Late, connected: `Late · no sample for {age:.0f} s`
  - Late, reconnecting: `Reconnecting (attempt {n})…`
  - Late, connected but no Sample yet: `Connected · waiting for first sample`
  - Down: `T7 not found: {reason}. Retrying every 5 s.`
- Dot colours: Idle `#999999`, Live `#2ca02c`, Late `#ff9f1a`, Down `#d62728`.
- Late threshold = `late_after_samples ÷ sample_hz` seconds. `late_after_samples`
  is a setting, integer, min 2, max 20, default 3.
- A read error is shown only until the next good Sample.
- Gauge status never feeds the Link state (AGENTS.md rule 5).

### Stale table (ticket 06)

- When the Link is not Live and a Sample has been seen, every pressure cell shows
  `STALE`, every status cell shows `last {value}, {age:.0f} s ago` (the last
  `display_text()` of that Reading), and the row's cells get the theme's
  `stale_bg`. When the Link returns to Live the next Sample restores normal cells.
- Before any Sample has been seen, cells show `---` as now.

### History and plot (tickets 07, 08)

- `History` (`src/ibl/history.py`): Raw tier = numpy ring buffer of the last
  3 600 s (capacity sized for `MAX_SAMPLE_HZ`), Summary tier = 10 s buckets of
  per-Channel min and max for up to `MAX_HISTORY_S` (24 h). NaN = no valid pressure.
- `minmax_decimate(t, lo, hi, t0, t1, n_buckets)` returns ≤ 2 points per bucket; a
  bucket with no finite data yields one NaN (a break).
- Consecutive points further apart than the Late threshold get a NaN between them
  (a Gap never gets a line across it).
- Redraw interval = `max(1 / sample_hz, span_s / plot_width_px)`.
- The plot shows a caption when the visible span reaches past the Raw tier:
  `Older than 1 h: min/max per 10 s`.

### Settings (tickets 04, 09)

- New constants in `config.py`: `MAX_SAMPLE_HZ = 10.0`, `MIN_SAMPLE_HZ = 0.1`,
  `MAX_HISTORY_S = 24 * 3600`, `MIN_HISTORY_S = 3600`, `MIN_LATE_AFTER_SAMPLES = 2`,
  `MAX_LATE_AFTER_SAMPLES = 20`, `MIN_CSV_INTERVAL_S = 1.0`,
  `MAX_CSV_INTERVAL_S = 3600.0`. `Settings.load` clamps every loaded value into range.
- New field `late_after_samples: int = 3`.
- The worker always gets `dataclasses.replace(settings)`, never the window's object.
- `Settings.save` returns an error string (empty on success) instead of passing.
- Settings panel previews, updated live:
  - next to *Late after*: `= {seconds:.1f} s at {hz:g} Hz`
  - next to *Write every*: `≈ {size} per day ({rows:,} rows)` where size is
    formatted `KB`/`MB` with one decimal, computed by
    `csvlogger.estimate_bytes_per_day(interval_s, include_voltages)` from the
    logger's real row formatter.

### CSV (ticket 10)

- Appending to today's file stays. If today's file exists and its header differs
  from the current header, the logger writes to `YYYY-MM-DD_b.csv` (then `_c`, …),
  the first candidate that is missing or has a matching header.
- On startup the window reloads History from yesterday's and today's Daily CSVs
  (all suffixes), keeping rows within the last 24 h. `Gauge Fault` and other status
  words load as NaN.

### Structure (tickets 01, 03, 11)

- Package moves to `src/ibl/`; `pyproject.toml` with `pythonpath = ["src"]` for
  pytest; `main.py` stays at the root; `IBLpressure.spec` gets `pathex=['src']`;
  `build.bat` runs `python -m ibl.conversion` with `src` on the path.
- `Reading`/`Sample` move to `model.py`; `GaugeStatus` becomes a `str` Enum whose
  values are today's strings (CSV output unchanged).
- `channels.py` gains `LOCATIONS` (ordered location names) and `PAIRS`
  (`tuple[tuple[Channel, Channel], ...]`, IG first); nothing else computes
  `pair*2`.
- `MainWindow` is split into `ui/topbar.py`, `ui/table_panel.py`,
  `ui/plot_panel.py`, `ui/settings_panel.py`, `ui/widgets.py` (`CompactSpin`);
  theme colours are read from the current theme dict, never module globals.

### In-app help (ticket 12)

- A `Help` button in the top bar opens `How IBL Pressure works`, a read-only
  dialog whose text comes from `src/ibl/help_text.py`. It explains the four Link
  states and dot colours, Late threshold, Stale cells, Gauge status colours, the two
  History tiers and plot decimation, Daily CSV naming/append/suffix rules, and the
  file-size preview. Its numbers come from `config.py` constants, not literals.

## 3. Testing decisions

- Cores (`link`, `history`, `csvlogger`, `config`, `channels`, `conversion`) are
  tested directly with plain data and explicit `now`.
- Qt tests use `pytest-qt` (`qtbot`), offscreen, `Settings(simulate=True)`, and
  drive `MainWindow`'s slots directly with hand-built `Sample`s rather than waiting
  on the worker thread.
- CI: ubuntu-latest, Python 3.14, `QT_QPA_PLATFORM=offscreen`, system packages for
  Qt (`libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3`).

## 4. Out of scope

- Jules dispatch and the engine's `dispatch` workflow (the developer adds these
  once the worker box is set up).
- Changing the conversion physics or coefficients.
- Stream mode acquisition.
- Per-channel reads (a Sample stays one request).
