# Unblock CI (ticket 27), then land ticket 26

This is a pointer, not the work.

- **Ticket 27:** `.scratch/ci-hygiene/issues/27-pin-ruff-and-enable-dtz-ble.md`: pins ruff and enables the DTZ/BLE rules. `master` CI is red until it lands. Auto-merge: no; the developer merges it.
- **Ticket 26:** `.scratch/link-recovery/issues/26-connection-summary-rolls-over-at-midnight.md`: implemented in PR #14, red only because of ticket 27's problem.
- **Tracker conventions:** `docs/agents/issue-tracker.md`

**Next:** 27. After it merges, update PR #14's branch from `master` (do not just re-run its old CI run, which reuses the old merge commit), let CI go green, merge, then set 26 to `done`.

Requirements an implementer would quietly treat as preferences — they are not:

- Ticket 27 changes only `pyproject.toml`. The five `# noqa: DTZ…` comments stay; the fix enables the rules, not deletes the comments.
- ruff is pinned exactly (`==`), so CI and the developer's `.venv` run the same version.
