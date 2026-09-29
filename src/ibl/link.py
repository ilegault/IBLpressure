"""LinkMonitor: the one pure core that decides the Link state. No Qt, no clock.

The dot and the status line are both drawn from the single LinkView returned by
LinkMonitor.view(now); nothing else decides the Link state (AGENTS.md rule 3).
Gauge status never feeds it (rule 5). Every method takes `now` in seconds.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


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
        self._reconnect_attempt: int | None = None
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

    def link_up(self, now: float, description: str) -> None:
        self._connected = True
        self._description = description
        self._down_reason = None
        self._reconnect_attempt = None

    def link_down(self, now: float, reason: str) -> None:
        self._connected = False
        self._down_reason = reason
        self._reconnect_attempt = None
        self._mark_lost(now)

    def reconnecting(self, now: float, attempt: int) -> None:
        self._connected = False
        self._down_reason = None
        self._reconnect_attempt = attempt
        self._mark_lost(now)

    def sample(self, now: float) -> None:
        if self._lost_at is not None:
            self._recovered_gap_s = now - self._lost_at
            self._recovered_at = now
        elif self._last_sample is not None and now - self._last_sample > self.late_threshold_s:
            self._recovered_gap_s = now - self._last_sample
            self._recovered_at = now
        self._lost_at = None
        self._last_sample = now
        self._read_error = None

    def read_error(self, now: float, message: str) -> None:
        self._read_error = message

    def _mark_lost(self, now: float) -> None:
        if self._lost_at is None:
            self._lost_at = self._last_sample if self._last_sample is not None else now

    # --- the answer -------------------------------------------------------
    def view(self, now: float) -> LinkView:
        state, text = self._decide(now)
        return LinkView(state, DOT_COLORS[state], text)

    def _decide(self, now: float) -> tuple[LinkState, str]:
        if not self._requested:
            return LinkState.IDLE, "Not connected. Press Connect."
        if self._down_reason is not None:
            return (LinkState.DOWN,
                    f"T7 not found: {self._down_reason}. Retrying every 5 s.")
        if self._reconnect_attempt is not None:
            return LinkState.LATE, f"Reconnecting (attempt {self._reconnect_attempt})…"
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
            stamp = datetime.fromtimestamp(self._recovered_at).strftime("%H:%M:%S")
            return (LinkState.LIVE,
                    f"Live · Recovered at {stamp} after a {self._recovered_gap_s:.0f} s gap")
        return LinkState.LIVE, f"Live · {self._description} · last sample {age:.1f} s ago"
