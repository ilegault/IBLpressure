# 24: AGENTS.md describes the process split

**Status:** ready-for-agent

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

- [ ] The architecture table rows match the modules that exist under `src/ibl/`
  (`ls src/ibl` and the table agree; `daq.py` is gone from both).
- [ ] Rule 2 and the new LJM rule are present with the wording above.
- [ ] The `<!-- ACTIVE-PLAN:START -->` … `<!-- ACTIVE-PLAN:END -->` block is
  byte-for-byte unchanged (check with `git diff`).
- [ ] Full gate green.

## Gate

Run in CI's order (`.github/workflows/ci.yml`):

1. `ruff check .`
2. `python scripts/check_tests_first.py`
3. `pytest -q`

## Comments
