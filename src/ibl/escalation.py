"""Escalation: the pure core that decides which recovery step comes next. No Qt, no clock.

WHY THIS EXISTS
---------------
When the Link is lost, a plain reopen can keep failing for hours (LJM error 1298) until the
PC is rebooted. Escalation climbs through stronger recovery steps on its own, one at a time,
moving up only after the step below has failed (ADR 0003):

    Reopen (3 tries) -> Library reset (3 tries) -> Acquisition restart (forever)

Hand-off begins when the first Acquisition restart fails and lasts until Recovery: the app
shows the operator what to do by hand, and keeps trying. It never stops.

Every method takes `now` in seconds (AGENTS.md rule 1). The caller (the Supervisor) runs the
Attempt that `due` returns, then calls `failed` or `recovered`. The timings are named
constants in `config.py` (rule 6).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from . import config


class Step(Enum):
    REOPEN = "Reopen"
    LIBRARY_RESET = "Library reset"
    ACQUISITION_RESTART = "Acquisition restart"


@dataclass(frozen=True)
class Attempt:
    step: Step
    number: int            # 1-based, within the step
    of: int | None         # tries in the step; None for Acquisition restart (unbounded)
    total: int             # 1-based, every Attempt since the loss
    hand_off: bool         # the operator is being told to act by hand


class Escalation:
    def __init__(self) -> None:
        self._clear()

    def _clear(self) -> None:
        self._climbing = False
        self._hand_off = False
        self._in_flight = False
        self._next: tuple[Step, int] = (Step.REOPEN, 1)   # the Attempt that comes next
        self._next_due = 0.0
        self._total = 0
        self._current: Step | None = None                 # step of the latest Attempt
        self._last_reason = ""

    # --- events -----------------------------------------------------------
    def lost(self, now: float, retry_now: bool) -> None:
        """The Link is lost. A mid-run loss retries at once; a failed Connect waits one interval."""
        if self._climbing:
            return
        self._clear()
        self._climbing = True
        self._next_due = now if retry_now else now + config.RETRY_INTERVAL_S

    def due(self, now: float) -> Attempt | None:
        """The Attempt to run now, or None (not climbing, one in flight, or not yet time)."""
        if not self._climbing or self._in_flight or now < self._next_due:
            return None
        step, number = self._next
        self._total += 1
        self._in_flight = True
        self._current = step
        of = None if step is Step.ACQUISITION_RESTART else config.TRIES_PER_STEP
        return Attempt(step, number, of, self._total, self._hand_off)

    def failed(self, now: float, reason: str) -> None:
        """The Attempt in flight failed; schedule the next one."""
        if not self._climbing or not self._in_flight:
            return
        self._in_flight = False
        self._last_reason = reason
        step, number = self._next
        if step is Step.ACQUISITION_RESTART:
            self._hand_off = True
            self._next = (step, number + 1)
            self._next_due = now + config.ACQUISITION_RESTART_INTERVAL_S
            return
        if number < config.TRIES_PER_STEP:
            self._next = (step, number + 1)
        elif step is Step.REOPEN:
            self._next = (Step.LIBRARY_RESET, 1)
        else:
            self._next = (Step.ACQUISITION_RESTART, 1)
        self._next_due = now + config.RETRY_INTERVAL_S

    def hung(self, now: float) -> None:
        """The child went silent and was killed: jump straight to an Acquisition restart."""
        if not self._climbing:
            self._clear()
            self._climbing = True
        number = 1
        if self._next[0] is Step.ACQUISITION_RESTART:
            number = self._next[1] + (1 if self._in_flight else 0)
        self._in_flight = False
        self._next = (Step.ACQUISITION_RESTART, number)
        self._next_due = now

    def recovered(self, now: float) -> Step | None:
        """A Sample arrived. Return the step that worked (None if no Attempt had run) and reset."""
        if not self._climbing:
            return None
        step = self._current
        self._clear()
        return step

    def reset(self) -> None:
        """Connect or Disconnect: forget the climb."""
        self._clear()

    # --- state ------------------------------------------------------------
    @property
    def climbing(self) -> bool:
        return self._climbing

    @property
    def hand_off(self) -> bool:
        return self._hand_off

    @property
    def in_flight(self) -> bool:
        return self._in_flight

    @property
    def current_step(self) -> Step | None:
        """The step of the latest Attempt, or None before the first one."""
        return self._current

    @property
    def last_reason(self) -> str:
        return self._last_reason
