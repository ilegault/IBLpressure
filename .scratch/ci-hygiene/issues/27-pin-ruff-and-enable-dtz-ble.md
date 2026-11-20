# 27: Pin ruff and enable the DTZ and BLE rules the code already annotates

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** no

**Blocked by:** None

**Binding:** ADR 0001

## What was seen

On 2026-11-20, CI went red on `master` and on PR #14 (ticket 26) at `ruff check .` with
5 × `RUF100 Unused noqa directive (non-enabled: DTZ00x)`:

```
src/ibl/csvlogger.py:48     # noqa: DTZ006
src/ibl/csvlogger.py:181    # noqa: DTZ006
src/ibl/csvlogger.py:247    # noqa: DTZ006
tests/test_csvlogger.py:70  # noqa: DTZ001
tests/test_linklog.py:13    # noqa: DTZ001
```

No code change caused it. The first red commit, 7a38a83, only edits a ticket file.
Locally, `ruff check .` passes. The planner reproduced it: **ruff 0.16.9 passes and
ruff 0.17.6 fails** on the same tree.

## Cause

1. `pyproject.toml` asks for `ruff>=0.6` (in `[project.optional-dependencies] dev`),
   so CI installs whichever ruff is newest that day and the developer's `.venv` keeps an
   older one. The gate changed under the repo with no commit.
2. The `# noqa: DTZ…` and `# noqa: BLE001` comments show that the code was written to
   follow flake8-datetimez (naive datetimes) and flake8-blind-except. Those rule sets
   were never turned on in `[tool.ruff]`, so ruff 0.17 calls the DTZ comments unused.
   With `DTZ` and `BLE` enabled, `ruff check .` passes on the current tree with zero
   violations. Every naive datetime and blind `except` is already annotated.

The fix enables the rules the comments were written for and pins ruff. Do **not**
delete the five comments: they record why the local calendar day is used, which is
exactly the kind of date bug that ticket 26 fixed.

## What to build

1. `pyproject.toml`, `[project.optional-dependencies]`: change `"ruff>=0.6"` to
   `"ruff==0.17.6"`. Leave `pytest` and `pytest-qt` as they are.
2. `pyproject.toml`: add this table directly after the existing `[tool.ruff]` table:
   ```toml
   [tool.ruff.lint]
   extend-select = ["BLE", "DTZ"]
   ```
   Do not add `SIM` or any other rule set (`SIM` finds a pre-existing issue at
   `csvlogger.py:272` that is out of scope). Do not change `line-length`,
   `target-version` or `extend-exclude`.
3. No file under `src/`, `tests/`, `scripts/` or `.github/` changes.

## Acceptance criteria

- [ ] After `pip install -e .[dev]`, `ruff --version` prints `ruff 0.17.6`, and
  `ruff check .` prints `All checks passed!` with the five `# noqa: DTZ…` comments still
  in place (`grep -c "noqa: DTZ" src/ibl/csvlogger.py` is 3; the two test files each
  still contain theirs).
- [ ] The rules are really enforced. Write a scratch file outside the repo containing
  `import datetime` and `datetime.datetime.now()`. Run
  `ruff check <that file> --config pyproject.toml` from the repo root: it reports
  `DTZ005`. Paste that output line into this ticket's `## Comments`, then delete the file.
- [ ] `python scripts/check_tests_first.py` passes. The change touches neither `src/`
  nor `main.py`, so no test change is required, and none is made.
- [ ] Existing tests still pass (no test: CI's full suite).
- [ ] The PR description says that PR #14 (ticket 26) must be updated from `master`
  after this merges. Re-running its old CI run would reuse the old merge commit and
  stay red.

## Out of scope

Removing or rewording any `noqa` comment; the `SIM115` comment at `csvlogger.py:230`;
any other ruff rule set; pinning pytest or pytest-qt; `.github/workflows/ci.yml`;
ticket 26's code.

## Gate

Run in CI's order (`.github/workflows/ci.yml`):

1. `ruff check .`
2. `python scripts/check_tests_first.py`
3. pytest: no test file is touched, so do not run it locally. CI runs the full suite on the PR.

## Comments

2026-11-20: Filed by the planner after ticket 26's PR went red at the lint step.
Reproduced with ruff 0.16.9 (passes) and 0.17.6 (5 × RUF100). With `--extend-select
DTZ,BLE`, 0.17.6 passes on the current tree.
