# 12: In-app "How IBL Pressure works" help

**What to build:** A *Help* button in the top bar opening a read-only dialog that
explains, in operator language, every rule an operator relies on — so nobody has to
read the repo to know what the dot, STALE, the plot summary or the CSV files mean.
AGENTS.md rule 8; spec §2 *In-app help*.

**Blocked by:** 11

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

## Acceptance criteria

- [ ] **Text lives in one Qt-free module.** `src/ibl/help_text.py` exposes
  `def help_html(settings: Settings) -> str`, built from `config.py`, `link.py` and
  `history.py` constants (no repeated numbers). Sections, in order, each an `<h3>`:
  `Status light`, `When data is late`, `Gauge status colours`, `The plot at long time spans`,
  `CSV log files`, `Settings you can change`.
- [ ] **Content is right and current.** `tests/test_help_text.py`:
  the text names all four Link states with their colours (Idle grey, Live green,
  Late amber, Down red); with `Settings(sample_hz=0.5, late_after_samples=2)` it says
  `4.0 s`; it contains `min/max per 10 s` and `1 h` taken from `RAW_SPAN_S` /
  `SUMMARY_BUCKET_S` (test by monkeypatching `SUMMARY_BUCKET_S` to 30 and seeing
  `per 30 s`); it explains `_b` suffix files and that restarting appends; it states
  one faulted gauge does not change the status light.
- [ ] **Dialog.** `ui/help_dialog.py` `HelpDialog(QDialog)` with a read-only
  `QTextBrowser` showing `help_html(current settings)`, title
  `How IBL Pressure works`. `TopBar` gets a `Help` button that opens it
  (`F1` shortcut too). Qt test: clicking *Help* shows a dialog whose browser text
  contains `Status light`.
- [ ] **Tooltips point to it.** The dot, the status line, the plot caption, *Late
  after* and the CSV size preview each have a tooltip ending
  `(Help explains more.)`. Test asserts all five.
- [ ] README gets a short *Using the app* section that points to the in-app Help
  rather than duplicating it. Full gate green.

Gates, in CI order: `ruff check .`, `python scripts/check_tests_first.py`, `pytest -q`.

## Comments
