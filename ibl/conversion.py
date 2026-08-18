"""
Voltage -> pressure conversion for the two VGC083A analog outputs.

All of this comes from the INFICON VGC083A manual, sections 7.2 (IG LOG N-10)
and 7.9 (CG1/CG2 NON-LIN), for nitrogen/air.

Ion gauge -- Analog Output 1, "IG LOG N - 10"
    Log-linear, 0 to 9 V dc, 1 volt per decade:
        P[Torr] = 10 ** (V - 10)
    Output jumps above +11 V on any gauge fault, sensor off, or over-pressure.

Convectron -- Analog Output 2, "CG1 NON-LIN"
    The Granville-Phillips "S-curve": 0.375 V below 1e-4 Torr, rising to
    5.659 V at 1000 Torr.  Three segments, and note that only the FIRST one
    is a plain polynomial -- the other two are ratios of polynomials:

        0.375 - 2.842 V   (0 to ~2 Torr)
            y = a + bx + cx^2 + dx^3 + ex^4 + fx^5

        2.842 - 4.945 V   (2 to ~100 Torr)
                a + cx + ex^2
            y = ---------------------------
                1 + bx + dx^2 + fx^3

        4.940 - 5.659 V   (100 to 1000 Torr)
                a + cx
            y = ------------------
                1 + bx + dx^2

    where y = pressure in Torr and x = measured analog output in volts.
    Output above +11 V means a faulty gauge or an unplugged gauge cable.
"""
from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Status codes attached to every reading
# ---------------------------------------------------------------------------
OK = "OK"
FAULT = "Gauge Fault"
UNDER = "Under range"
OVER = "Over range"

# ---------------------------------------------------------------------------
# Ion gauge
# ---------------------------------------------------------------------------
IG_LOG_OFFSET = 10.0      # P = 10^(V - 10)
IG_V_MAX = 9.0            # top of the normal log-linear output span

# ---------------------------------------------------------------------------
# Convectron gauge, non-linear "S-curve" analog output
# ---------------------------------------------------------------------------
# Coefficients are listed a, b, c, d, e, f exactly as printed in the manual.
# "kind" says how to combine them:
#   "poly"    -> a + bx + cx^2 + dx^3 + ex^4 + fx^5
#   "rat5"    -> (a + cx + ex^2) / (1 + bx + dx^2 + fx^3)
#   "rat3"    -> (a + cx)        / (1 + bx + dx^2)
CG_SEGMENTS: list[tuple[float, float, str, tuple[float, ...]]] = [
    # v_low, v_high, kind,  (a, b, c, d, e, f)
    (0.375, 2.842, "poly", (-0.02585, 0.03767, 0.04563, 0.1151, -0.04158, 0.008738)),
    (2.842, 4.945, "rat5", (0.1031, -0.3986, -0.02322, 0.07438, 0.07229, -0.006866)),
    (4.940, 5.659, "rat3", (100.624, -0.37679, -20.5623, 0.0348656)),
]

CG_V_MIN = 0.375          # 0.3751 V is "less than 1e-4 Torr"
CG_V_MAX = 5.659          # 1000 Torr
CG_P_MIN = 1.0e-4         # what we report when the gauge is pinned at the bottom
CG_P_MAX = 1000.0

# Reference points from the manual's pressure/voltage table, used by self_test().
CG_TABLE: list[tuple[float, float]] = [
    (0.000, 0.3751), (1.00e-4, 0.3759), (2.00e-4, 0.3768), (5.00e-4, 0.3795),
    (1.00e-3, 0.3840), (2.00e-3, 0.3927), (5.00e-3, 0.4174), (1.00e-2, 0.4555),
    (2.00e-2, 0.5226), (5.00e-2, 0.6819), (1.00e-1, 0.8780), (2.00e-1, 1.1552),
    (5.00e-1, 1.6833), (1.00e+0, 2.2168), (2.00e+0, 2.8418), (5.00e+0, 3.6753),
    (1.00e+1, 4.2056), (2.00e+1, 4.5766), (5.00e+1, 4.8464), (1.00e+2, 4.9449),
    (2.00e+2, 5.0190), (3.00e+2, 5.1111), (4.00e+2, 5.2236), (5.00e+2, 5.3294),
    (6.00e+2, 5.4194), (7.00e+2, 5.4949), (7.60e+2, 5.5340), (8.00e+2, 5.5581),
    (9.00e+2, 5.6141), (1.00e+3, 5.6593),
]


@dataclass(frozen=True)
class Reading:
    """One channel at one instant."""
    ain: int
    voltage: float
    pressure: float | None   # Torr, or None when it cannot be trusted
    status: str              # OK / Gauge Fault / Under range / Over range

    @property
    def ok(self) -> bool:
        return self.status == OK

    def display_text(self) -> str:
        """What goes in the table cell and in the CSV."""
        if self.pressure is None:
            return self.status
        if self.status == UNDER:
            return f"< {self.pressure:.2E}"
        if self.status == OVER:
            return f"> {self.pressure:.2E}"
        return f"{self.pressure:.2E}"


def _horner(coeffs: tuple[float, ...], x: float) -> float:
    """c0 + c1*x + c2*x^2 + ..."""
    total = 0.0
    for c in reversed(coeffs):
        total = total * x + c
    return total


def _evaluate(kind: str, k: tuple[float, ...], x: float) -> float:
    if kind == "poly":
        a, b, c, d, e, f = k
        return _horner((a, b, c, d, e, f), x)
    if kind == "rat5":
        a, b, c, d, e, f = k
        num = _horner((a, c, e), x)
        den = _horner((1.0, b, d, f), x)
        return num / den if den else float("inf")
    if kind == "rat3":
        a, b, c, d = k
        num = _horner((a, c), x)
        den = _horner((1.0, b, d), x)
        return num / den if den else float("inf")
    raise ValueError(f"unknown segment kind {kind!r}")


def ion_gauge_pressure(v: float) -> float:
    """VGC083A Analog Output 1, 'IG LOG N - 10'."""
    return 10.0 ** (v - IG_LOG_OFFSET)


def convectron_pressure(v: float) -> float:
    """VGC083A Analog Output 2, 'CG1 NON-LIN'. Volts in, Torr out."""
    for v_low, v_high, kind, coeffs in CG_SEGMENTS:
        if v <= v_high:
            return _evaluate(kind, coeffs, v)
    return _evaluate(CG_SEGMENTS[-1][2], CG_SEGMENTS[-1][3], v)


def convert(ain: int, voltage: float, is_ion: bool, fault_volts: float) -> Reading:
    """
    Turn one raw analog input voltage into a Reading.

    fault_volts is the "gauge fault" threshold.  The manual says the VGC083A
    drives its output above +11 V on a fault, but a LabJack T7 analog input
    saturates just past 10 V, so the practical threshold is 10 V: neither
    gauge type ever legitimately outputs that much (IG tops out at 9 V,
    the Convectron at 5.659 V).
    """
    if voltage > fault_volts:
        return Reading(ain, voltage, None, FAULT)

    if is_ion:
        p = ion_gauge_pressure(voltage)
        if voltage > IG_V_MAX:
            # Between 9 V and the fault threshold the IG is off its stated span.
            return Reading(ain, voltage, p, OVER)
        return Reading(ain, voltage, p, OK)

    # --- Convectron ---
    if voltage < CG_V_MIN:
        return Reading(ain, voltage, CG_P_MIN, UNDER)
    if voltage > CG_V_MAX:
        return Reading(ain, voltage, CG_P_MAX, OVER)

    p = convectron_pressure(voltage)
    if p <= 0.0:
        return Reading(ain, voltage, CG_P_MIN, UNDER)
    return Reading(ain, voltage, p, OK)


# ---------------------------------------------------------------------------
# Self check -- run:  python -m ibl.conversion
# ---------------------------------------------------------------------------
def self_test() -> int:
    failures = 0

    print("=" * 68)
    print("ION GAUGE   P = 10^(V-10)   [manual section 7.2 table]")
    print("=" * 68)
    ig_table = [(1e-10, 0.0), (1e-9, 1.0), (1e-8, 2.0), (1e-7, 3.0), (1e-6, 4.0),
                (1e-5, 5.0), (1e-4, 6.0), (1e-3, 7.0), (1e-2, 8.0), (5e-2, 8.698)]
    for p_want, v in ig_table:
        p_got = ion_gauge_pressure(v)
        err = abs(p_got - p_want) / p_want
        ok = err < 0.01
        failures += 0 if ok else 1
        print(f"  {v:6.3f} V -> {p_got:.4E} Torr   (manual {p_want:.2E})   "
              f"{'ok' if ok else 'FAIL'}")

    print()
    print("=" * 68)
    print("CONVECTRON  S-curve  [manual section 7.9 pressure/voltage table]")
    print("=" * 68)
    print(f"  {'V in':>7}  {'P computed':>12}  {'P in manual':>12}   {'error':>8}")
    worst = 0.0
    for p_want, v in CG_TABLE:
        p_got = convectron_pressure(v)
        if p_want == 0.0:
            ok = abs(p_got) < 1e-3
            err_txt = f"{p_got:+.1E}"
        else:
            err = abs(p_got - p_want) / p_want
            worst = max(worst, err)
            # Below ~5 mTorr the whole decade spans under a millivolt of
            # S-curve, so the manual's own coefficients only reproduce its
            # own table to a few percent.  (Its worked example, 0.3840 V,
            # is printed as 1.0E-3 Torr but computes to 1.03E-3.)  That is
            # a property of the gauge, not a bug -- and it is exactly the
            # region where you should be reading the ion gauge instead.
            tol = 0.10 if p_want < 5.0e-3 else 0.02
            ok = err < tol
            err_txt = f"{err*100:6.2f} %"
        failures += 0 if ok else 1
        print(f"  {v:7.4f}  {p_got:12.4E}  {p_want:12.4E}   {err_txt:>8}  "
              f"{'ok' if ok else 'FAIL'}")
    print(f"\n  worst relative error over the whole span: {worst*100:.2f} %")

    print()
    print("=" * 68)
    print("SEGMENT CONTINUITY")
    print("=" * 68)
    for i in range(len(CG_SEGMENTS) - 1):
        v = CG_SEGMENTS[i][1]
        lo = _evaluate(CG_SEGMENTS[i][2], CG_SEGMENTS[i][3], v)
        hi = _evaluate(CG_SEGMENTS[i + 1][2], CG_SEGMENTS[i + 1][3], v)
        rel = abs(lo - hi) / max(abs(lo), abs(hi), 1e-12)
        ok = rel < 0.02
        failures += 0 if ok else 1
        print(f"  at {v:6.3f} V : segment {i+1} -> {lo:10.4f} Torr, "
              f"segment {i+2} -> {hi:10.4f} Torr  ({rel*100:.2f} %)  "
              f"{'ok' if ok else 'FAIL'}")

    print()
    print("=" * 68)
    print("MANUAL WORKED EXAMPLE   (0.3840 V should be 1.0E-03 Torr)")
    print("=" * 68)
    got = convectron_pressure(0.3840)
    ok = abs(got - 1.0e-3) / 1.0e-3 < 0.10
    failures += 0 if ok else 1
    print(f"  0.3840 V -> {got:.4E} Torr   {'ok' if ok else 'FAIL'}")

    print()
    print("=" * 68)
    print("FAULT HANDLING  (threshold 10.0 V)")
    print("=" * 68)
    for ain, v, is_ion in [(0, 7.0, True), (0, 10.4, True), (1, 1.1552, False),
                           (1, 10.9, False), (1, 0.2, False), (1, 5.9, False)]:
        r = convert(ain, v, is_ion, 10.0)
        kind = "IG" if is_ion else "CG"
        print(f"  {kind} {v:6.3f} V -> {r.display_text():>12}   [{r.status}]")

    print()
    if failures:
        print(f"*** {failures} CHECK(S) FAILED ***")
    else:
        print("All checks passed.")
    return failures


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(1 if self_test() else 0)
