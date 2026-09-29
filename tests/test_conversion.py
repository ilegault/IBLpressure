"""Volts -> Torr, checked against the INFICON VGC083A manual tables."""
import pytest

from ibl.conversion import (
    APPROX,
    CG_SEGMENTS,
    CG_TABLE,
    FAULT,
    NEGATIVE,
    OK,
    OVER,
    UNDER,
    _evaluate,
    convectron_pressure,
    convert,
    ion_gauge_pressure,
)

IG_TABLE = [(1e-10, 0.0), (1e-9, 1.0), (1e-8, 2.0), (1e-7, 3.0), (1e-6, 4.0),
            (1e-5, 5.0), (1e-4, 6.0), (1e-3, 7.0), (1e-2, 8.0), (5e-2, 8.698)]


@pytest.mark.parametrize("p_want,v", IG_TABLE)
def test_ion_gauge_matches_manual(p_want, v):
    assert abs(ion_gauge_pressure(v) - p_want) / p_want < 0.01


# Below ~5 mTorr the whole decade spans under a millivolt of S-curve, so the
# manual's own coefficients only reproduce its own table to a few percent
# (its worked example, 0.3840 V, is printed as 1.0E-3 Torr but computes to
# 1.03E-3). That is the flat bottom of the S-curve, not a bug.
@pytest.mark.parametrize("p_want,v", [row for row in CG_TABLE if row[0] > 0])
def test_convectron_matches_manual_table(p_want, v):
    tol = 0.10 if p_want < 5.0e-3 else 0.02
    assert abs(convectron_pressure(v) - p_want) / p_want < tol


@pytest.mark.parametrize("i", range(len(CG_SEGMENTS) - 1))
def test_convectron_segments_are_continuous(i):
    v = CG_SEGMENTS[i][1]
    lo = _evaluate(CG_SEGMENTS[i][2], CG_SEGMENTS[i][3], v)
    hi = _evaluate(CG_SEGMENTS[i + 1][2], CG_SEGMENTS[i + 1][3], v)
    assert abs(lo - hi) / max(abs(lo), abs(hi), 1e-12) < 0.02


@pytest.mark.parametrize("is_ion,volts,status,pressure,tol", [
    (True, 7.0, OK, 1e-3, 0.01),
    (True, 10.4, FAULT, None, None),
    (True, 9.5, OVER, None, None),
    (False, 1.1552, OK, 0.2, 0.02),
    (False, 10.9, FAULT, None, None),
    (False, 0.2, UNDER, None, None),
    (False, 5.9, OVER, None, None),
    (True, -0.1, NEGATIVE, None, None),
    (False, -0.1, NEGATIVE, None, None),
])
def test_convert_statuses(is_ion, volts, status, pressure, tol):
    r = convert(0, volts, is_ion, 10.0)
    assert r.status == status
    if pressure is None:
        assert r.pressure is None
    else:
        assert abs(r.pressure - pressure) / pressure < tol


def test_convert_use_ig_is_shown_approximate():
    r = convert(1, 0.3759, False, 10.0)
    assert r.status == APPROX
    assert r.display_text().startswith("~")
