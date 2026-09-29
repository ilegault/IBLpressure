"""
Physical wiring map: which LabJack T7 analog input is fed by which
VGC083A analog output, at which beamline location.

Straight out of Design.pdf, "LabJack wiring".
"""
from __future__ import annotations

from dataclasses import dataclass

ION = "Ion Gauge"
CONVECTRON = "Convectron Gauge"


@dataclass(frozen=True)
class Channel:
    ain: int            # LabJack T7 analog input number
    location: str       # beamline location
    gauge: str          # ION or CONVECTRON
    vgc_output: int     # which VGC083A analog output feeds it (1 or 2)

    @property
    def name(self) -> str:
        """Short label used in the table, the plot legend and the CSV header."""
        short = "IG" if self.gauge == ION else "CG"
        return f"{self.location} {short}"

    @property
    def is_ion(self) -> bool:
        return self.gauge == ION


# AIN 0..13.  Odd = Convectron, even = Ion gauge.
CHANNELS: tuple[Channel, ...] = (
    Channel(0,  "SNICS",            ION,        1),
    Channel(1,  "SNICS",            CONVECTRON, 2),
    Channel(2,  "Injector",         ION,        1),
    Channel(3,  "Injector",         CONVECTRON, 2),
    Channel(4,  "Post-accel",       ION,        1),
    Channel(5,  "Post-accel",       CONVECTRON, 2),
    Channel(6,  "Switching Magnet", ION,        1),
    Channel(7,  "Switching Magnet", CONVECTRON, 2),
    Channel(8,  "Left Chamber",     ION,        1),
    Channel(9,  "Left Chamber",     CONVECTRON, 2),
    Channel(10, "Middle Chamber",   ION,        1),
    Channel(11, "Middle Chamber",   CONVECTRON, 2),
    Channel(12, "Right Chamber",    ION,        1),
    Channel(13, "Right Chamber",    CONVECTRON, 2),
)

# Register names handed to the LJM library, e.g. "AIN0".
AIN_NAMES: list[str] = [f"AIN{c.ain}" for c in CHANNELS]
