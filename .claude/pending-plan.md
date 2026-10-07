# Link recovery — automatic Escalation, acquisition in its own process, Link log

This is a pointer, not the work.

- **Spec:** `.scratch/link-recovery/spec.md`
- **Binding ADRs:** `docs/adr/0001-tests-first.md`, `docs/adr/0003-acquisition-in-its-own-process.md`
- **New glossary terms (CONTEXT.md):** Escalation, Reopen, Library reset, Acquisition restart, Device watchdog, Link log
- **Tickets:** 14–25 in `.scratch/link-recovery/issues/`
- **Tracker conventions:** `docs/agents/issue-tracker.md`

**Next:** 14, 15, 16 have no blockers. Start with **14** (Escalation core): 18 and 19 both wait on it, and it is a pure core with the clearest tests. 15 and 16 can run in parallel.

Dependency graph:

```
14 ─┬─> 18 ─────────────┐
    └─> 19 <── 16 ──> 17 ┤
             19 ─────────┴─> 20 ─┬─> 21 (needs 15) ─> 22 ─> 23 ─> 25 [ready-for-developer: bench check]
15 ──────────────────────────────┘                └─> 24 [held: Auto-merge no, AGENTS.md]
```

Requirements an implementer would quietly treat as preferences — they are not:

- `acquisition.py`, `supervisor.py`, `escalation.py`, `linklog.py` import no PySide6/pyqtgraph; cores take `now`, never `time.time()`.
- The child never retries on its own; only the Supervisor (via Escalation) decides.
- The window never waits on LJM: no `BlockingQueuedConnection`, no unbounded `join`.
- Watchdog `_DEFAULT` registers are written only when they differ (flash wear).
- Status texts are verbatim from spec §2 *Status texts*; every timing is a `config.py` constant.
- Link log write failures are reported, never swallowed (AGENTS.md rule 7).
- History, plot and the Daily CSV system are not changed.

Deliberately not done: Windows USB device reset, Ethernet migration, alerts beyond the screen and the Link log.
