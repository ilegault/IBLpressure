# 24: AGENTS.md describes the process split

**Status:** done

**Runner:** any

**Auto-merge:** no

**Blocked by:** 20

**Spec:** `.scratch/link-recovery/spec.md`
**Binding:** ADR 0003

## What to build

Update `AGENTS.md` (sections 1–3 only; never the `ACTIVE-PLAN` block) so a future
worker meets the new structure: the architecture table lists `escalation.py`,
`linklog.py`, `acquisition.py` (child process, no Qt) and `supervisor.py` (no Qt)
and drops `daq.py`; rule 2 becomes "processes never share a mutable object — the
child receives Settings copies in `Start` / `ApplySettings`"; add a rule that only
`acquisition.py` calls LJM and the window never waits on it; the testing section
says the child handle may be faked and names `tests/test_supervisor.py`'s real
Simulation-mode process test as the one that spawns a process.

## Acceptance criteria

Docs-only; no code changes.

- [x] The architecture table rows match the modules that exist under `src/ibl/`
  (`ls src/ibl` and the table agree; `daq.py` is gone from both).
- [x] Rule 2 and the new LJM rule are present with the wording above.
- [x] The `<!-- ACTIVE-PLAN:START -->` … `<!-- ACTIVE-PLAN:END -->` block is
  byte-for-byte unchanged (check with `git diff`).
- [x] Full gate green.

## Gate

Run in CI's order (`.github/workflows/ci.yml`):

1. `ruff check .`
2. `python scripts/check_tests_first.py`
3. `pytest -q`

## Comments

2026-10-07 — AGENTS.md sections 1–3 updated: the architecture table matches `ls src/ibl`
(`daq.py` gone; `escalation.py`, `linklog.py`, `acquisition.py`, `supervisor.py`, plus the previously
unlisted `help_text.py`/`theme.py` added); rule 2 now speaks of processes; new rule 9 (only
`acquisition.py` calls LJM, the window never waits on it) is numbered 9 so existing "rule 7" references
stay valid; the testing section names the child-handle fake and the real-process tests. The
`ACTIVE-PLAN` block is byte-for-byte unchanged (diffed). `Auto-merge: no`: needs the developer's approval.
