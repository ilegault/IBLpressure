# 23: Help and tooltips explain Escalation, the watchdog and the Link log

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 22

**Spec:** `.scratch/link-recovery/spec.md`
**Binding:** ADR 0001

## What to build

Operator-facing behaviour is explained in the app (AGENTS.md rule 8). Add a
section **When the connection drops** to `help_html` in `src/ibl/help_text.py`:
the three steps and their timing (built from the `config.py` constants, never
literals), the Hand-off message and what to do, that the T7 restarts itself after
`WATCHDOG_TIMEOUT_S` s without contact (including whenever the app is closed —
harmless, it only reads inputs), and where the Link log is (one file per month in
the `link-log` folder next to the CSVs) and what the Connection frame shows. Fix
the Down bullet that still says "retries every 5 s". Update the status-dot
tooltip in `src/ibl/ui/topbar.py` and the README's operator section to match.

## Acceptance criteria

Tests in `tests/test_help_text.py` call `help_html(Settings())` directly and patch
`config` constants with `monkeypatch` to prove the text is built from them.

- [x] `help_html` contains `When the connection drops`, `Reopen`, `Library reset`,
  `Acquisition restart`, `unplug and replug the T7` and `link-log`.
- [x] With `ACQUISITION_RESTART_INTERVAL_S` patched to 45 and `WATCHDOG_TIMEOUT_S` to
  90, the text contains `45 s` and `90 s` (no hard-coded 30/60).
- [x] The text no longer contains `retries every 5 s`.
- [x] `window.topbar.lbl_link.toolTip()` mentions automatic recovery and the
  Connection frame.

## Gate

Run in CI's order (`.github/workflows/ci.yml`):

1. `ruff check .`
2. `python scripts/check_tests_first.py`
3. `pytest -q`

## Comments

2026-10-07 — `help_html` has a new section **When the connection drops** built from `config`
constants at call time (so tests can patch them); the Down bullet no longer says "retries every 5 s";
the status-dot tooltip mentions automatic recovery and the Connection box; the README's operator
section and code layout are updated. Tests: `tests/test_help_text.py` (the section-order test gained
the new heading in place) and `tests/test_window_link.py`.
