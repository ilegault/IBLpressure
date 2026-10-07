# Spec — link-recovery

**Effort:** when the Link is lost, IBL Pressure gets it back on its own without a
PC reboot whenever software can, always tells the operator what it is doing, and
keeps a permanent record of every loss and recovery.

Vocabulary: `CONTEXT.md` (new terms: **Escalation**, **Reopen**, **Library reset**,
**Acquisition restart**, **Device watchdog**, **Link log**). Binding decisions:
`docs/adr/0001-tests-first.md`, `docs/adr/0003-acquisition-in-its-own-process.md`.

---

## 1. Problem (observed on the beamline PC)

About once a day the Link goes Down and stays Down. The status line reads
`T7 not found: LJM library error code 1298 LJME_ATTR_LOAD_COMM_FAILURE. Retrying
every 5 s.` forever; only a PC reboot brings it back. The T7 has its own power
supply, so a reboot does not power-cycle it — it resets the PC's USB host, driver
and the LJM library in our process. The USB cable is very long and crosses the
accelerator (LabJack's classic cause: transients make the USB host lose the
device). The developer is separately moving the T7 to Ethernet; this effort is the
software side and must work with either cable.

Causes found in the code:

1. `DaqWorker` (`src/ibl/daq.py`) only ever retries `ljm.openS`. It never resets
   the LJM library and cannot reload it: LJM is a DLL loaded once per process.
2. Everything LJM runs on one `QThread`. A call that never returns blocks the
   queued Connect/Disconnect/settings slots, and `MainWindow.closeEvent` waits on
   that thread with `Qt.BlockingQueuedConnection` and no time limit, so Quit can
   hang and leave a process holding the T7.
3. Nothing is written to disk: the LJM error lives only on the status line.

## 2. Decisions

### Escalation (pure core, ticket 14)

- Steps, in order, one at a time: **Reopen** (3 tries) → **Library reset**
  (3 tries: `ljm.closeAll()` then open) → **Acquisition restart** (kill the
  acquisition child process and start a fresh one; repeated forever).
- Tries within Reopen and Library reset are `RETRY_INTERVAL_S = 5` apart; the first
  Library reset and the first Acquisition restart also come 5 s after the previous
  failure; Acquisition restarts are `ACQUISITION_RESTART_INTERVAL_S = 30` apart.
- A mid-run loss (3 failed reads in a row) starts the climb with Reopen due
  *immediately*. A failed open at Connect starts it with Reopen due in 5 s.
- **Hand-off** begins when the first Acquisition restart fails and lasts until
  Recovery. The app never stops trying.
- A child that sends nothing for `HUNG_AFTER_S = 15` s while connected is **hung**:
  it is killed and the climb jumps straight to Acquisition restart, due now.
- Recovery reports the step that worked and resets the climb; the next loss starts
  again at Reopen. Connect and Disconnect reset it too.
- All of these numbers are named constants in `config.py` (AGENTS.md rule 6).
  They are rules, not settings.

### Process split (ADR 0003; tickets 16, 19, 20)

- `src/ibl/acquisition.py` (no Qt): the whole T7 conversation — open, AIN
  configuration, Device watchdog, read, close, Library reset, Simulation. It runs
  in a child process started with `multiprocessing.get_context("spawn")`.
- `src/ibl/supervisor.py` (no Qt): runs in the window process, owns the child and
  the Escalation, and turns child messages into window events. The window polls it
  every 100 ms from a `QTimer`. It never blocks longer than one stop: Quit
  waits `STOP_TIMEOUT_S = 2` s for a clean exit, then terminates, then kills.
- History, plot, Daily CSV, LinkMonitor and Link log stay in the window process and
  are never touched by an Acquisition restart. Daily CSV append-on-restart
  (ticket 10) is unchanged.

Child messages (plain picklable dataclasses in `acquisition.py`):

| Commands (window → child) | Events (child → window) |
|---|---|
| `Start(settings)` | `Alive()` — at least every `HEARTBEAT_S = 1` s |
| `ApplySettings(settings)` | `LinkUp(description, ljm_version, firmware, warning)` |
| `Reopen()` | `LinkDown(reason)` — an open failed |
| `LibraryReset()` | `Lost(reason)` — 3 reads failed in a row; handle closed |
| `Quit()` | `ReadError(message)`, `SampleReady(sample)` |

The child never retries on its own: it opens only when told (`Start`, `Reopen`,
`LibraryReset`, or an `ApplySettings` that changes connection, identifier,
resolution or Simulation, as `DaqWorker.update_settings` does today).

### Device watchdog (ticket 17)

On every successful open (not in Simulation) the child reads
`WATCHDOG_ENABLE_DEFAULT`, `WATCHDOG_TIMEOUT_S_DEFAULT`,
`WATCHDOG_RESET_ENABLE_DEFAULT`, `WATCHDOG_STRICT_ENABLE_DEFAULT`. If they are not
already `1, 60, 1, 0` it writes, in one `eWriteNames` call and in this order:
`WATCHDOG_ENABLE_DEFAULT=0`, `WATCHDOG_TIMEOUT_S_DEFAULT=60`,
`WATCHDOG_RESET_ENABLE_DEFAULT=1`, `WATCHDOG_STRICT_ENABLE_DEFAULT=0`,
`WATCHDOG_ENABLE_DEFAULT=1`. These are flash-stored `_DEFAULT` registers, so it
never writes when they already match (flash wear). A failure here never blocks the
Link: `LinkUp.warning` carries `Device watchdog not set: {error}`. The T7 is used
for analog inputs only, so a watchdog restart is harmless. `WATCHDOG_TIMEOUT_S = 60`
lives in `config.py`.

### Status texts (ticket 18; replaces spec §2 of stability-and-structure where they differ)

`Attempt(step, number, of, total, hand_off)` — `of` is 3 for Reopen and Library
reset, `None` for Acquisition restart; `total` counts every attempt since the loss.

| Situation | State | Text |
|---|---|---|
| Attempt in flight | Late | `Reconnecting — {step} (attempt {n} of 3)…` / `Reconnecting — Acquisition restart (attempt {n})…` |
| Attempt failed | Down | `T7 not found: {reason}. {step} (attempt {n} of 3) failed; next try in 5 s.` / `T7 not found: {reason}. Acquisition restart (attempt {n}) failed; next try in 30 s.` |
| Open failed at Connect (no attempt yet) | Down | `T7 not found: {reason}. Next try in 5 s.` |
| Hand-off (in flight or failed) | Down | `T7 not responding — automatic recovery still trying (attempt {total}). If this persists: check the USB cable to the T7, unplug and replug the T7, then reboot this PC. Details in the Link log.` |
| Recovery after Escalation | Live | `Live · Recovered at {HH:MM:SS} after a {gap:.0f} s gap ({step})` for 10 s |
| Recovery without Escalation | Live | unchanged: `Live · Recovered at {HH:MM:SS} after a {gap:.0f} s gap` |

`LinkView` gains `detail`: the latest LabJack error while the Link is not Live,
`""` otherwise. The top bar shows it as the status line's tooltip. All other texts
and dot colours are unchanged.

### Link log (tickets 15, 21, 22)

- One file per month: `<csv_dir>/link-log/YYYY-MM.log` (local time), appended,
  UTF-8, created on first write. Kept forever. The Daily CSV system is not touched.
- One line per event: `YYYY-MM-DD HH:MM:SS  KIND  detail`. Kinds: `APP_START`,
  `APP_STOP`, `CONNECT`, `DISCONNECT`, `LINK_UP`, `LINK_DOWN`, `LOST`,
  `RECONNECTING`, `RECOVERED`, `READ_ERROR`, `HAND_OFF`, `REPEATED`.
- **Folding:** a record may carry a `fold_key`. The first record with a given
  (kind, fold_key) in a `LINK_LOG_FOLD_S = 600` s window is written; later ones in
  that window are only counted. When that key's window has ended (checked on the
  next record of any kind), or a record with no `fold_key` is written, a
  `REPEATED  {kind} {fold_key} ×{count} since {HH:MM:SS}` line is written first for
  each key whose count is above zero. Different keys fold independently, so a climb
  alternating `RECONNECTING` and `LINK_DOWN` folds both. A bad night costs a few
  hundred lines, not tens of thousands.
- `LINK_UP` records the description, LJM library version, T7 firmware, connection,
  identifier and sample rate. `RECOVERED` records `{step} · gap {gap} s`.
- A write failure never stops the app; it is reported (AGENTS.md rule 7).

### Connection frame (ticket 22)

A new **Connection** group inside the Settings box (collapsed with it, so it never
takes over the screen):
- a summary line: `Today: 3 recoveries — Reopen 2, Library reset 1 · longest gap 42 s`
  (`Today: 1 recovery — …`, `Today: no recoveries`);
- the last `CONNECTION_FRAME_EVENTS = 20` Link log lines, newest first, read-only;
- an **Open Link log** button that opens the `link-log` folder the way
  `TopBar.open_folder` opens the CSV folder.

## 3. Out of scope

- Resetting the USB device through Windows (needs admin; deferred until the Link
  log shows Acquisition restart is not enough — ADR 0003).
- Ethernet migration (hardware, the developer's own work).
- Alerts beyond the screen and the Link log (email, Slack, sound).
- Any change to conversion physics, History, plotting or the Daily CSV.

## 4. Tickets

14 Escalation core · 15 Link log core · 16 Acquisition core · 17 Device watchdog ·
18 LinkMonitor knows the step · 19 Supervisor · 20 Window runs on the Supervisor ·
21 Link log wired in · 22 Connection frame · 23 Help and tooltips ·
24 AGENTS.md architecture (held) · 25 Bench check (developer).
