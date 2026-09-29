# AGENTS.md — orientation for AI sessions working on IBL Pressure

## Agent skills

### Issue tracker

Issues live as local markdown files under `.scratch/<effort>/`. See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context layout: one `CONTEXT.md` at the repo root, ADRs in `docs/adr/`.
Use the glossary's words in code, tests, commits and PRs.

---

IBL Pressure is the beamline vacuum monitor for the UW Ion Beam Laboratory. A
LabJack T7 reads the analog outputs of seven INFICON VGC083A gauge controllers
(14 channels: one Ion Gauge and one Convectron per location), the app converts
volts to Torr, shows them live in a table and a log-scale plot, and logs them to
one CSV file per day.

**Operators trust this screen to tell them the vacuum state of a beamline.** A
number that looks live but is not, or a status light that is wrong, is the worst
bug this app can have. A green build made green by weakening a test is worse than
a red one.

Two kinds of session read this file:

- **The planner** (Claude, in Cowork) grills designs and writes specs and
  tickets. It never implements.
- **A worker** (a local Claude Code / Antigravity session using the
  `implement-ticket-parallel` skill) implements one ticket from `.scratch/`.

---

## 1. Quick facts

| | |
|---|---|
| Language / runtime | Python 3.14 on the developer's Windows PC; CI runs 3.14 on `ubuntu-latest` |
| GUI | PySide6 + pyqtgraph. Tests run Qt headless (`QT_QPA_PLATFORM=offscreen`) |
| Package | `src/ibl/` (after ticket 01; before it, `ibl/` at the repo root) |
| Entry point | `main.py` at the repo root (`python main.py`, `--simulate` forces Simulation mode) |
| Tests | `pytest`, in `tests/` |
| Build | `build.bat` → PyInstaller `IBLpressure.spec` → `dist\IBLpressure\IBLpressure.exe`, then `verify_build.py` |
| Repo | `github.com/ilegault/IBLpressure`, default branch `master` |
| Hardware | LabJack T7 over USB/Ethernet through the LJM library. **CI never has a T7**; tests use Simulation mode or fakes |

```
# setup (Windows)
python -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]

# the gate, in the order CI runs it (.github/workflows/ci.yml, after ticket 02)
ruff check .
python scripts/check_tests_first.py
pytest -q
```

---

## 2. Architecture — the rules that matter

**Pure cores, thin Qt shells.** Every decision the operator can see (is the link
live? is this reading stale? which points get plotted? how big is a day's CSV?)
lives in a module that imports neither PySide6 nor pyqtgraph and takes the clock
as an argument. The Qt code only carries the core's answer to the screen. This is
what lets a test prove the status light is right without a window, a thread or a
T7.

| Layer | Module (under `src/ibl/`) | Owns | Imports Qt? |
|---|---|---|---|
| Wiring | `channels.py` | `Channel`, `CHANNELS`, the IG/CG pair of each location | no |
| Physics | `conversion.py` | volts → Torr, `GaugeStatus` per reading | no |
| Model | `model.py` (ticket 03) | `Reading`, `Sample` | no |
| Settings | `config.py` | `Settings`, its limits, load/save | no |
| Link | `link.py` (ticket 05) | `LinkMonitor`: Link state, Freshness, status text | no |
| History | `history.py` (ticket 07) | two-tier History, min/max decimation | no |
| CSV | `csvlogger.py` | daily file, append safety, size estimate, reload | no |
| Driver | `driver.py` | LJM present? bundled installer | no |
| Acquisition | `daq.py` | `DaqWorker` on its own `QThread` | yes |
| Window | `mainwindow.py` + `ui/` panels (ticket 11) | widgets only | yes |

Rules:

1. **A core never imports `PySide6` or `pyqtgraph`, never reads `time.time()`,
   never touches the filesystem unless file I/O is its job (`csvlogger`, `config`).**
   Pass `now` in.
2. **Threads never share a mutable object.** The acquisition worker receives a
   *copy* of `Settings` (`dataclasses.replace`) every time settings change. Never
   hand it `self.settings`.
3. **One state, one place.** The status dot and the status text are both drawn
   from one `LinkView` returned by `LinkMonitor.view(now)`. No other code sets the
   dot's colour or the status text.
4. **A number is only shown in a pressure cell when the Link is Live.** When the
   Link is not Live, pressure cells show `STALE` and the last value moves to the
   Status column with its age.
5. **A Gauge status problem stays in its own row.** A faulted, negative or
   out-of-range reading changes only that gauge's cells, never the dot, the status
   line, or another row.
6. **Every limit lives in `config.py`** as a named constant (`MAX_SAMPLE_HZ`,
   `MAX_HISTORY_S`, `MIN_LATE_AFTER_SAMPLES`, …). Widgets read their ranges from
   there. Never repeat a limit as a literal in a widget.
7. **Never swallow an error silently.** `except Exception: pass` is not allowed in
   new code. Either handle it, or report it (status line, CSV label, log).
8. **Behaviour the operator relies on is explained in the app**, not only in the
   repo: tooltips, plot captions and the Help dialog (ticket 12). When a ticket
   changes such behaviour it updates the in-app text too.

---

## 3. Testing conventions (see ADR 0001)

- Tests first, watched failing, then the code.
- Test cores directly with plain data and an explicit `now`.
- Qt tests use `pytest-qt`'s `qtbot` with `QT_QPA_PLATFORM=offscreen` and
  `Settings(simulate=True)`. Never a real T7, never LJM.
- **May fake:** the clock (pass `now`), the LJM module (a fake object with
  `eReadNames` etc.), the worker's signals. **Must be real:** the core under
  change, and any file under change (use `tmp_path`).
- Assert what the operator would see: cell text, dot colour, status text, the
  file written, the number of points handed to a curve.
- No `skip`, `skipif` or `xfail`. No loosened tolerances without a physical reason
  written in the test.

---

## 4. Roles, not people

Never write real people's names, handles or emails in code, commits, tickets or
docs. Say "the operator", "the developer".

---

## 5. Implementation protocol

Tickets are implemented with the `implement-ticket-parallel` skill (one ticket
per session, own git worktree, tests first, full gate before pushing, never merge
your own PR). Its rules are the ticket-engine's runner-agnostic ticket skill:
`src/ticket_engine/resources/ticket_skill.md` in `ilegault/ticket-engine`.

---

<!-- ACTIVE-PLAN:START -->
Effort: `.scratch/stability-and-structure/` — spec in `spec.md`, tickets 01–13.
Next: the lowest-numbered `ready-for-agent` ticket whose blockers are all `done`.
<!-- ACTIVE-PLAN:END -->
