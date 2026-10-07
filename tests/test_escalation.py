"""Escalation: which recovery step comes next. Real Escalation, explicit `now`, no fakes."""
from __future__ import annotations

from ibl import config
from ibl.escalation import Attempt, Escalation, Step


def _run_climb(esc: Escalation, until: int = 130):
    seen = []
    for t in range(until + 1):
        attempt = esc.due(float(t))
        if attempt is not None:
            seen.append((t, attempt))
            assert esc.in_flight
            # while the Attempt is in flight nothing else is due
            assert esc.due(float(t)) is None
            esc.failed(float(t), "1298")
    return seen


def test_constants_live_in_config():
    assert config.RETRY_INTERVAL_S == 5.0
    assert config.TRIES_PER_STEP == 3
    assert config.ACQUISITION_RESTART_INTERVAL_S == 30.0
    assert config.HUNG_AFTER_S == 15.0


def test_step_values():
    assert [s.value for s in Step] == ["Reopen", "Library reset", "Acquisition restart"]


def test_full_climb_order_and_timing():
    esc = Escalation()
    esc.lost(0.0, retry_now=True)
    seen = [(t, a.step.value, a.number, a.total) for t, a in _run_climb(esc)]
    assert seen == [
        (0, "Reopen", 1, 1),
        (5, "Reopen", 2, 2),
        (10, "Reopen", 3, 3),
        (15, "Library reset", 1, 4),
        (20, "Library reset", 2, 5),
        (25, "Library reset", 3, 6),
        (30, "Acquisition restart", 1, 7),
        (60, "Acquisition restart", 2, 8),
        (90, "Acquisition restart", 3, 9),
        (120, "Acquisition restart", 4, 10),
    ]


def test_attempt_of_field():
    esc = Escalation()
    esc.lost(0.0, retry_now=True)
    ofs = [(a.step, a.of) for _, a in _run_climb(esc)]
    assert ofs[0] == (Step.REOPEN, config.TRIES_PER_STEP)
    assert ofs[3] == (Step.LIBRARY_RESET, config.TRIES_PER_STEP)
    assert ofs[6] == (Step.ACQUISITION_RESTART, None)


def test_hand_off_starts_after_first_restart_fails():
    esc = Escalation()
    esc.lost(0.0, retry_now=True)
    for t in range(131):
        attempt = esc.due(float(t))
        if attempt is None:
            continue
        if t <= 30:
            assert attempt.hand_off is False
            assert esc.hand_off is False
        else:
            assert attempt.hand_off is True
            assert esc.hand_off is True
        esc.failed(float(t), "1298")
        assert esc.hand_off is (t >= 30)


def test_connect_failure_waits_five_seconds():
    esc = Escalation()
    esc.lost(0.0, retry_now=False)
    assert esc.climbing
    assert esc.due(4.9) is None
    assert esc.due(5.0) == Attempt(Step.REOPEN, 1, 3, 1, False)


def test_hung_jumps_to_restart():
    esc = Escalation()
    esc.lost(0.0, retry_now=True)
    assert esc.due(0.0) == Attempt(Step.REOPEN, 1, 3, 1, False)
    esc.hung(3.0)
    assert not esc.in_flight
    assert esc.due(3.0) == Attempt(Step.ACQUISITION_RESTART, 1, None, 2, False)


def test_hung_while_idle_starts_climb_at_restart():
    esc = Escalation()
    esc.hung(10.0)
    assert esc.climbing
    assert esc.due(10.0) == Attempt(Step.ACQUISITION_RESTART, 1, None, 1, False)


def test_recovery_reports_step_and_resets():
    esc = Escalation()
    esc.lost(0.0, retry_now=True)
    for t in range(23):
        attempt = esc.due(float(t))
        if attempt is None:
            continue
        if attempt == Attempt(Step.LIBRARY_RESET, 2, 3, 5, False):
            break
        esc.failed(float(t), "1298")
    assert esc.in_flight
    assert esc.recovered(22.0) is Step.LIBRARY_RESET
    assert not esc.climbing
    assert not esc.hand_off
    assert not esc.in_flight
    assert esc.due(100.0) is None
    esc.lost(200.0, retry_now=True)
    assert esc.due(200.0) == Attempt(Step.REOPEN, 1, 3, 1, False)


def test_recovered_when_not_climbing_is_none():
    esc = Escalation()
    assert esc.recovered(5.0) is None


def test_recovery_before_any_attempt_reports_no_step():
    esc = Escalation()
    esc.lost(0.0, retry_now=False)
    assert esc.recovered(1.0) is None
    assert not esc.climbing


def test_reset_mid_climb_returns_nothing_and_clears():
    esc = Escalation()
    esc.lost(0.0, retry_now=True)
    esc.due(0.0)
    assert esc.reset() is None
    assert not esc.climbing
    assert not esc.in_flight
    assert esc.due(50.0) is None
    esc.lost(60.0, retry_now=True)
    assert esc.due(60.0) == Attempt(Step.REOPEN, 1, 3, 1, False)


def test_hand_off_clears_on_recovery():
    esc = Escalation()
    esc.lost(0.0, retry_now=True)
    _run_climb(esc, until=40)
    assert esc.hand_off
    assert esc.recovered(41.0) is Step.ACQUISITION_RESTART
    assert not esc.hand_off


def test_failed_reason_is_kept():
    esc = Escalation()
    esc.lost(0.0, retry_now=True)
    esc.due(0.0)
    esc.failed(0.0, "LJME_ATTR_LOAD_COMM_FAILURE")
    assert esc.last_reason == "LJME_ATTR_LOAD_COMM_FAILURE"
