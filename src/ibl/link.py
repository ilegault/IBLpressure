"""LinkMonitor: the one pure core that decides the Link state. No Qt, no clock.

The dot and the status line are both drawn from the single LinkView returned by
LinkMonitor.view(now); nothing else decides the Link state (AGENTS.md rule 3).
Gauge status never feeds it (rule 5). Every method takes `now` in seconds.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from . import config
from .escalation import Attempt, Step


class LinkState(Enum):
    IDLE = "idle"
    LIVE = "live"
    LATE = "late"
    DOWN = "down"


DOT_COLORS = {
    LinkState.IDLE: "#999999",
    LinkState.LIVE: "#2ca02c",
    LinkState.LATE: "#ff9f1a",
    LinkState.DOWN: "#d62728",
}

# How long the status line reports a Recovery before going back to the normal Live text.
RECOVERY_NOTICE_S = 10.0


@dataclass(frozen=True)
class LinkView:
    state: LinkState
    dot_color: str
    text: str
    detail: str = ""     # the latest LabJack error while the Link is not Live, else ""


@dataclass(frozen=True)
class Recovery:
    """Returned by LinkMonitor.sample on the Sample that ends a Gap."""
    gap_s: float
    step: Step | None    # the Escalation step that worked, None if none was needed


class LinkMonitor:
    def __init__(self, late_after_samples: int, sample_hz: float):
        self._late_after_samples = late_after_samples
        self._sample_hz = sample_hz
        self._reset()

    def _reset(self) -> None:
        self._requested = False          # operator pressed Connect
        self._connected = False          # the T7 is open
        self._description = ""
        self._down_reason: str | None = None
        self._attempt: Attempt | None = None        # the Escalation Attempt, if one is known
        self._attempt_in_flight = False
        self._pending_step: Step | None = None      # step named by link_up, used at Recovery
        self._recovered_step: Step | None = None
        self._detail = ""                           # latest LabJack error
        self._last_sample: float | None = None
        self._lost_at: float | None = None       # start of the current Gap, if any
        self._recovered_at: float | None = None
        self._recovered_gap_s = 0.0
        self._read_error: str | None = None

    # --- settings ---------------------------------------------------------
    def configure(self, late_after_samples: int, sample_hz: float) -> None:
        self._late_after_samples = late_after_samples
        self._sample_hz = sample_hz

    @property
    def late_threshold_s(self) -> float:
        return self._late_after_samples / self._sample_hz

    # --- events -----------------------------------------------------------
    def connect_requested(self, now: float) -> None:
        self._reset()
        self._requested = True

    def disconnect_requested(self, now: float) -> None:
        self._reset()

    def link_up(self, now: float, description: str, recovered_by: Step | None = None) -> None:
        self._connected = True
        self._description = description
        self._down_reason = None
        self._attempt = None
        self._attempt_in_flight = False
        self._pending_step = recovered_by

    def link_down(self, now: float, reason: str, attempt: Attempt | None = None) -> None:
        """An open failed. `attempt` is the Escalation Attempt that failed, if there was one."""
        self._connected = False
        self._down_reason = reason
        self._detail = reason
        self._attempt = attempt
        self._attempt_in_flight = False
        self._mark_lost(now)

    def reconnecting(self, now: float, attempt: Attempt) -> None:
        self._connected = False
        self._down_reason = None
        self._attempt = attempt
        self._attempt_in_flight = True
        self._mark_lost(now)

    def sample(self, now: float) -> Recovery | None:
        """A Sample arrived. Returns a Recovery if it ends a Gap."""
        gap_s: float | None = None
        if self._lost_at is not None:
            gap_s = now - self._lost_at
        elif self._last_sample is not None and now - self._last_sample > self.late_threshold_s:
            gap_s = now - self._last_sample
        recovery = None
        if gap_s is not None:
            self._recovered_gap_s = gap_s
            self._recovered_at = now
            self._recovered_step = self._pending_step
            recovery = Recovery(gap_s, self._recovered_step)
        self._pending_step = None
        self._lost_at = None
        self._last_sample = now
        self._read_error = None
        self._detail = ""
        return recovery

    def read_error(self, now: float, message: str) -> None:
        self._read_error = message
        self._detail = message

    def _mark_lost(self, now: float) -> None:
        if self._lost_at is None:
            self._lost_at = self._last_sample if self._last_sample is not None else now

    # --- the answer -------------------------------------------------------
    def view(self, now: float) -> LinkView:
        state, text = self._decide(now)
        detail = self._detail if state in (LinkState.LATE, LinkState.DOWN) else ""
        return LinkView(state, DOT_COLORS[state], text, detail)

    def _hand_off_text(self) -> str:
        total = self._attempt.total if self._attempt is not None else 0
        return (f"T7 not responding — automatic recovery still trying (attempt {total}). "
                "If this persists: check the USB cable to the T7, unplug and replug the T7, "
                "then reboot this PC. Details in the Link log.")

    @staticmethod
    def _attempt_label(attempt: Attempt) -> str:
        if attempt.of is None:
            return f"{attempt.step.value} (attempt {attempt.number})"
        return f"{attempt.step.value} (attempt {attempt.number} of {attempt.of})"

    def _decide(self, now: float) -> tuple[LinkState, str]:
        if not self._requested:
            return LinkState.IDLE, "Not connected. Press Connect."
        attempt = self._attempt
        if attempt is not None and attempt.hand_off and not self._connected:
            return LinkState.DOWN, self._hand_off_text()
        if self._down_reason is not None:
            if attempt is None:
                return (LinkState.DOWN,
                        f"T7 not found: {self._down_reason}. Next try in 5 s.")
            wait = (config.ACQUISITION_RESTART_INTERVAL_S if attempt.step is Step.ACQUISITION_RESTART
                    else config.RETRY_INTERVAL_S)
            failed = f"{self._attempt_label(attempt)} failed; next try in {wait:.0f} s."
            return LinkState.DOWN, f"T7 not found: {self._down_reason}. {failed}"
        if attempt is not None and self._attempt_in_flight:
            return LinkState.LATE, f"Reconnecting — {self._attempt_label(attempt)}…"
        if not self._connected:
            return LinkState.LATE, "Connecting…"
        if self._last_sample is None:
            return LinkState.LATE, "Connected · waiting for first sample"
        age = max(0.0, now - self._last_sample)
        if age > self.late_threshold_s:
            return LinkState.LATE, f"Late · no sample for {age:.0f} s"
        if self._read_error is not None:
            return (LinkState.LIVE,
                    f"Live · {self._description} · read error: {self._read_error}")
        if self._recovered_at is not None and now - self._recovered_at < RECOVERY_NOTICE_S:
            # The operator reads wall-clock time, so show it in local time.
            local = datetime.fromtimestamp(self._recovered_at, tz=UTC).astimezone()
            stamp = local.strftime("%H:%M:%S")
            how = f" ({self._recovered_step.value})" if self._recovered_step is not None else ""
            return (LinkState.LIVE,
                    f"Live · Recovered at {stamp} after a {self._recovered_gap_s:.0f} s gap{how}")
        return LinkState.LIVE, f"Live · {self._description} · last sample {age:.1f} s ago"
