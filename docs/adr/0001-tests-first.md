# ADR 0001 — Tests first, honest tests

**Status:** accepted
**Date:** 2026-09-28

## Context

IBL Pressure is what an operator looks at to decide whether a beamline is at
vacuum. Its earlier bugs were exactly the kind a test would have caught and a
glance at the running app would not: a status light that never turned green again,
and a settings change that never reached the acquisition thread. Tickets are
implemented by agents that are rewarded for a green build, and the cheapest way to
turn a red build green is to stop the test from reporting the problem.

## Decision

1. Tests are written from a ticket's acceptance criteria **before** the
   implementation and are watched failing for the right reason.
2. `scripts/check_tests_first.py` runs in CI: a PR that changes application code
   under `src/` (or `main.py`) must also change tests under `tests/`.
3. No `skip`, `skipif` or `xfail`. No deleted test functions or lost assertions
   unless the ticket lists them on a `Deletes tests:` line.
4. The ticket-engine integrity gate runs on every PR (`.github/workflows/integrity.yml`)
   and enforces 3 and more: a new test must fail against the base branch, the
   ticket must be `done` with every box ticked, and changes to `.github/`,
   `scripts/`, `docs/adr/`, `AGENTS.md` or `CONTEXT.md` hold for the developer.
5. Decisions live in Qt-free cores so they can be tested with plain data and an
   explicit clock. Qt tests run headless with `pytest-qt`.

## Consequences

- A test that already passes before its feature exists is caught by the gate.
- Anything that needs a real T7 (unplugging USB, a 24 h run) is a
  `ready-for-developer` bench ticket, never simulated by an agent.
