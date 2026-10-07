"""Supervisor: owns the acquisition child and the Escalation. No Qt.

May fake: the child handle (FakeChild) and the clock (explicit `now`).
Must be real: Supervisor and Escalation. One test uses a real child process.
"""
from __future__ import annotations

import dataclasses
import time

from ibl import config
from ibl.acquisition import (
    Alive,
    ApplySettings,
    LibraryReset,
    LinkDown,
    LinkUp,
    Lost,
    Quit,
    Reopen,
    SampleReady,
    Start,
)
from ibl.acquisition import ReadError as ChildReadError
from ibl.config import Settings
from ibl.escalation import Attempt, Step
from ibl.model import Sample
from ibl.supervisor import (
    Down,
    NewSample,
    Reconnecting,
    Supervisor,
    Up,
)
from ibl.supervisor import ReadError as WindowReadError

SETTINGS = Settings(simulate=False, connection="USB", identifier="ANY")
UP = LinkUp("T7 #470012345 over USB", "1.2300", "1.0234", "")


class FakeChild:
    """A child handle that records every command and kill."""

    def __init__(self, heartbeats=True, exits_on_quit=False):
        self.heartbeats = heartbeats
        self.exits_on_quit = exits_on_quit
        self.sent: list = []
        self.incoming: list = []
        self.joins: list = []
        self.terminated = False
        self.killed = False
        self._alive = True
        self._quit_sent = False
        self.answered = 0           # how many Reopen/LibraryReset we have answered

    def send(self, command):
        self.sent.append(command)
        if isinstance(command, Quit):
            self._quit_sent = True

    def receive(self):
        out, self.incoming = self.incoming, []
        if self.heartbeats and self._alive:
            out.append(Alive())
        return out

    def alive(self):
        return self._alive

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True
        self._alive = False

    def join(self, timeout=None):
        self.joins.append(timeout)
        if self.exits_on_quit and self._quit_sent:
            self._alive = False

    def die(self):
        self._alive = False

    def retries(self):
        return [c for c in self.sent if isinstance(c, (Reopen, LibraryReset))]

    def answer_retries_with(self, event):
        """Reply to every Reopen / LibraryReset not yet answered."""
        pending = len(self.retries()) - self.answered
        self.answered += pending
        self.incoming.extend([event] * pending)


class Spawner:
    def __init__(self, **child_kwargs):
        self.children: list[FakeChild] = []
        self.settings: list[Settings] = []
        self.child_kwargs = child_kwargs

    def __call__(self, settings):
        child = FakeChild(**self.child_kwargs)
        self.children.append(child)
        self.settings.append(settings)
        return child


def _sample(t=0.0):
    return Sample(t, [])


def _types(events):
    return [type(e) for e in events]


def test_constants():
    assert config.STOP_TIMEOUT_S == 2.0


def test_connect_spawns_a_child_and_sends_start():
    spawn = Spawner()
    sup = Supervisor(spawn=spawn)
    sup.connect(0.0, SETTINGS)
    assert len(spawn.children) == 1
    start = spawn.children[0].sent[0]
    assert isinstance(start, Start)
    assert start.settings == SETTINGS
    assert start.settings is not SETTINGS            # a copy crosses the boundary (rule 2)


def test_up_and_samples_become_window_events():
    spawn = Spawner()
    sup = Supervisor(spawn=spawn)
    sup.connect(0.0, SETTINGS)
    child = spawn.children[0]
    child.incoming = [UP, SampleReady(_sample(1.0)), ChildReadError("timeout")]
    events = sup.poll(1.0)
    assert events[0] == Up(UP.description, "1.2300", "1.0234", "", None)
    assert isinstance(events[1], NewSample) and events[1].sample.timestamp == 1.0
    assert events[2] == WindowReadError("timeout")


def test_mid_run_loss_climbs_and_recovers():
    spawn = Spawner()
    sup = Supervisor(spawn=spawn)
    sup.connect(0.0, SETTINGS)
    child = spawn.children[0]
    child.incoming = [UP, SampleReady(_sample(1.0))]
    sup.poll(1.0)

    child.incoming = [Lost("timeout")]
    events = sup.poll(10.0)
    first = Attempt(Step.REOPEN, 1, 3, 1, False)
    assert events == [Reconnecting(first)]
    assert child.retries() == [Reopen()]

    child.answer_retries_with(LinkDown("1298"))
    assert sup.poll(10.5) == [Down("1298", first)]

    sent_library_reset_at = None
    t = 10.5
    while sent_library_reset_at is None and t < 60:
        t += 0.5
        events = sup.poll(t)
        child.answer_retries_with(LinkDown("1298"))
        if LibraryReset() in child.sent:
            sent_library_reset_at = t
    # Each failure is seen half a second after its Attempt, then 5 s pass: Reopen #2 at 15.5,
    # #3 at 21.0, and the 4th Attempt (Library reset #1) at 26.5.
    assert sent_library_reset_at == 26.5
    assert events[0] == Reconnecting(Attempt(Step.LIBRARY_RESET, 1, 3, 4, False))

    child.incoming = [UP]
    up = [e for e in sup.poll(26.0) if isinstance(e, Up)]
    assert up == [Up(UP.description, "1.2300", "1.0234", "", Step.LIBRARY_RESET)]


def test_escalation_ends_on_the_first_sample_not_on_link_up():
    spawn = Spawner()
    sup = Supervisor(spawn=spawn)
    sup.connect(0.0, SETTINGS)
    child = spawn.children[0]
    child.incoming = [UP, SampleReady(_sample(1.0))]
    sup.poll(1.0)
    child.incoming = [Lost("timeout")]
    sup.poll(10.0)                                   # Reopen #1
    child.incoming = [UP]
    up = sup.poll(10.5)
    assert up == [Up(UP.description, "1.2300", "1.0234", "", Step.REOPEN)]
    child.incoming = [Lost("timeout")]               # opened, but reads still fail
    assert sup.poll(13.0) == [Down("timeout", Attempt(Step.REOPEN, 1, 3, 1, False))]
    events = sup.poll(18.0)                          # the climb goes on: Reopen #2, not #1
    assert events == [Reconnecting(Attempt(Step.REOPEN, 2, 3, 2, False))]


def test_recovery_resets_the_climb():
    spawn = Spawner()
    sup = Supervisor(spawn=spawn)
    sup.connect(0.0, SETTINGS)
    child = spawn.children[0]
    child.incoming = [UP, SampleReady(_sample(1.0))]
    sup.poll(1.0)
    child.incoming = [Lost("timeout")]
    sup.poll(10.0)
    child.incoming = [UP, SampleReady(_sample(11.0))]
    sup.poll(11.0)
    child.incoming = [Lost("timeout")]
    events = sup.poll(30.0)                          # a new loss starts again at Reopen #1
    assert events == [Reconnecting(Attempt(Step.REOPEN, 1, 3, 1, False))]


def _fail_until_restart(spawn, sup, start_t=10.0):
    """Drive failures until the first Acquisition restart is due; return its time."""
    child = spawn.children[0]
    child.incoming = [UP, SampleReady(_sample(1.0))]
    sup.poll(1.0)
    child.incoming = [Lost("timeout")]
    t = start_t
    sup.poll(t)
    while len(spawn.children) == 1 and t < 100:
        child.answer_retries_with(LinkDown("1298"))
        t += 0.5
        sup.poll(t)
    return t


def test_acquisition_restart_replaces_the_child():
    spawn = Spawner()
    sup = Supervisor(spawn=spawn)
    sup.connect(0.0, SETTINGS)
    old = spawn.children[0]
    t = _fail_until_restart(spawn, sup)
    assert t == 43.0                                  # Reopen x3, Library reset x3, then restart
    assert len(spawn.children) == 2
    assert any(isinstance(c, Quit) for c in old.sent)
    assert old.joins and old.killed                   # asked politely, waited, then killed
    new = spawn.children[1]
    start = new.sent[0]
    assert isinstance(start, Start) and start.settings == SETTINGS


def test_first_failed_restart_reports_hand_off():
    spawn = Spawner()
    sup = Supervisor(spawn=spawn)
    sup.connect(0.0, SETTINGS)
    _fail_until_restart(spawn, sup)
    new = spawn.children[1]
    new.incoming = [LinkDown("1298")]
    events = sup.poll(30.5)
    assert events == [Down("1298", Attempt(Step.ACQUISITION_RESTART, 1, None, 7, True))]


def test_silent_child_is_hung():
    spawn = Spawner(heartbeats=False)
    sup = Supervisor(spawn=spawn)
    sup.connect(0.0, SETTINGS)
    old = spawn.children[0]
    old.incoming = [UP, SampleReady(_sample(0.5))]
    sup.poll(0.5)
    assert sup.poll(15.0) == []                       # 14.5 s of silence: not yet
    events = sup.poll(15.6)                           # 15.1 s of silence
    assert events == [
        Down("acquisition not responding", None),
        Reconnecting(Attempt(Step.ACQUISITION_RESTART, 1, None, 1, False)),
    ]
    assert old.killed
    assert len(spawn.children) == 2
    assert isinstance(spawn.children[1].sent[0], Start)


def test_child_that_exits_on_its_own_is_restarted():
    spawn = Spawner()
    sup = Supervisor(spawn=spawn)
    sup.connect(0.0, SETTINGS)
    child = spawn.children[0]
    child.incoming = [UP, SampleReady(_sample(0.5))]
    sup.poll(0.5)
    child.die()
    events = sup.poll(1.0)
    assert events[0] == Down("acquisition process exited", None)
    assert isinstance(events[1], Reconnecting)
    assert len(spawn.children) == 2


def test_open_failure_at_connect_waits_five_seconds():
    spawn = Spawner()
    sup = Supervisor(spawn=spawn)
    sup.connect(0.0, SETTINGS)
    child = spawn.children[0]
    child.incoming = [LinkDown("no device")]
    assert sup.poll(0.0) == [Down("no device", None)]
    assert sup.poll(4.9) == []
    assert child.retries() == []
    events = sup.poll(5.0)
    assert events == [Reconnecting(Attempt(Step.REOPEN, 1, 3, 1, False))]
    assert child.retries() == [Reopen()]


def test_disconnect_kills_a_child_that_ignores_quit():
    spawn = Spawner()
    sup = Supervisor(spawn=spawn)
    sup.connect(0.0, SETTINGS)
    child = spawn.children[0]
    sup.disconnect(1.0)
    assert Quit() in child.sent
    assert child.joins[0] == config.STOP_TIMEOUT_S
    assert child.terminated and child.killed
    child.incoming = [UP, SampleReady(_sample(2.0))]
    assert sup.poll(2.0) == []
    assert sup.poll(100.0) == []
    assert len(spawn.children) == 1                   # and nothing restarts it


def test_disconnect_of_a_polite_child_does_not_kill_it():
    spawn = Spawner(exits_on_quit=True)
    sup = Supervisor(spawn=spawn)
    sup.connect(0.0, SETTINGS)
    child = spawn.children[0]
    sup.disconnect(1.0)
    assert not child.terminated and not child.killed


def test_shutdown_stops_the_child():
    spawn = Spawner()
    sup = Supervisor(spawn=spawn)
    sup.connect(0.0, SETTINGS)
    sup.shutdown()
    assert spawn.children[0].killed
    sup.shutdown()                                    # safe to call twice


def test_connect_again_replaces_the_old_child():
    spawn = Spawner()
    sup = Supervisor(spawn=spawn)
    sup.connect(0.0, SETTINGS)
    sup.connect(5.0, SETTINGS)
    assert len(spawn.children) == 2
    assert spawn.children[0].killed


def test_update_settings_sends_a_copy():
    spawn = Spawner()
    sup = Supervisor(spawn=spawn)
    sup.connect(0.0, SETTINGS)
    newer = dataclasses.replace(SETTINGS, sample_hz=2.0)
    sup.update_settings(1.0, newer)
    sent = spawn.children[0].sent[-1]
    assert isinstance(sent, ApplySettings)
    assert sent.settings == newer and sent.settings is not newer


def test_restart_uses_the_latest_settings():
    spawn = Spawner()
    sup = Supervisor(spawn=spawn)
    sup.connect(0.0, SETTINGS)
    newer = dataclasses.replace(SETTINGS, sample_hz=2.0)
    sup.update_settings(1.0, newer)
    _fail_until_restart(spawn, sup)
    assert spawn.children[1].sent[0].settings == newer


def test_update_settings_without_a_child_is_remembered_not_sent():
    spawn = Spawner()
    sup = Supervisor(spawn=spawn)
    sup.update_settings(0.0, SETTINGS)               # before Connect: nothing to send to
    sup.connect(1.0, dataclasses.replace(SETTINGS, sample_hz=3.0))
    assert spawn.children[0].sent[0].settings.sample_hz == 3.0


def test_spawn_failure_is_reported_and_retried():
    attempts = []

    def spawn(settings):
        attempts.append(settings)
        if len(attempts) == 1:
            raise OSError("cannot fork")
        return FakeChild()

    sup = Supervisor(spawn=spawn)
    sup.connect(0.0, SETTINGS)
    assert sup.poll(0.0) == [Down("could not start acquisition: cannot fork", None)]
    events = sup.poll(5.0)
    assert events == [Reconnecting(Attempt(Step.REOPEN, 1, 3, 1, False))]
    assert len(attempts) == 2                         # with no child, any step spawns a new one


def test_real_child_streams_simulated_samples():
    sup = Supervisor()
    sup.connect(time.time(), Settings(simulate=True, sample_hz=10.0))
    got_sample = False
    deadline = time.time() + 20.0
    try:
        while time.time() < deadline and not got_sample:
            events = sup.poll(time.time())
            got_sample = any(isinstance(e, NewSample) for e in events)
            time.sleep(0.05)
        assert got_sample
        child = sup.child                              # to prove it is really gone
    finally:
        started = time.time()
        sup.shutdown()
    assert time.time() - started < 4.0
    assert not child.alive()
