"""Reading and Sample: the plain data every core passes around. No Qt."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class GaugeStatus(str, Enum):
    """The verdict on one Reading. The value is the text shown and logged."""
    OK = "OK"
    FAULT = "Gauge Fault"
    UNDER = "Under range"
    OVER = "Over range"
    NEGATIVE = "Neg Voltage"
    APPROX = "Use IG"


@dataclass(frozen=True)
class Reading:
    """One channel at one instant."""
    ain: int
    voltage: float
    pressure: float | None   # Torr, or None when it cannot be trusted
    status: GaugeStatus

    @property
    def ok(self) -> bool:
        return self.status is GaugeStatus.OK

    def display_text(self) -> str:
        """What goes in the table cell and in the CSV."""
        if self.pressure is None:
            return self.status.value
        if self.status is GaugeStatus.APPROX:
            return f"~{self.pressure:.2E}"
        return f"{self.pressure:.2E}"


class Sample:
    """One sweep of all 14 channels."""
    __slots__ = ("readings", "timestamp")

    def __init__(self, timestamp: float, readings: list[Reading]):
        self.timestamp = timestamp
        self.readings = readings

    def by_ain(self) -> dict[int, Reading]:
        return {r.ain: r for r in self.readings}
