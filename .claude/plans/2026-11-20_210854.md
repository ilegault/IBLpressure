# Connection frame summary rolls over at midnight — ticket 26

This is a pointer, not the work.

- **Ticket:** `.scratch/link-recovery/issues/26-connection-summary-rolls-over-at-midnight.md` (the whole work order is there)
- **Binding ADRs:** `docs/adr/0001-tests-first.md`
- **Tracker conventions:** `docs/agents/issue-tracker.md`

**Next:** 26. It has no blockers and is the only `ready-for-agent` ticket.

Requirements an implementer would quietly treat as preferences — they are not:

- `local_day(now)` lives in `linklog.py` and is pure; the window does no date arithmetic of its own.
- The Link log is re-read only when the local day changes, never on every 500 ms tick.
- The test is driven by the real `_link_timer`; no window method is called by hand after the clock moves.
