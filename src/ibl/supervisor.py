"""Supervisor: runs in the window process, owns the acquisition child and the Escalation.

WHY THIS EXISTS
---------------
The T7 conversation runs in a child process (`acquisition.run`, ADR 0003) so that a wedged
LJM can be thrown away and a fresh one loaded. The Supervisor is the window's side of that
bargain. It starts the child, drains its messages, drives `Escalation` from them, sends
`Reopen` / `LibraryReset` or replaces the child (Acquisition restart) when an Attempt is
due, and turns everything into window events. No Qt: the window polls it from a QTimer.

    window --connect/disconnect/update_settings/poll/shutdown--> Supervisor
    Supervisor --Start/ApplySettings/Reopen/LibraryReset/Quit--> child
    child --Alive/LinkUp/LinkDown/Lost/ReadError/SampleReady--> Supervisor
    Supervisor --Up/Down/Reconnecting/ReadError/NewSample--> window --> LinkMonitor, Link log

Rules:
- The child never retries on its own; only this class (via Escalation) decides.
- The window never waits on LJM. The only blocking call is stopping a child, bounded by
  STOP_TIMEOUT_S (a polite Quit), then terminate, then kill.
- An Attempt only succeeds when a Sample arrives. A LinkUp whose reads then fail counts as
  the same Attempt failing, so a T7 that opens but cannot be read still climbs the steps.
- A child that sends nothing for HUNG_AFTER_S is hung (it is blocked in an LJM call, since it
  sends Alive every HEARTBEAT_S even when it has nothing else to say): it is killed and the
  climb jumps to Acquisition restart. A child that has exited is treated the same way.
- Every method takes `now`; this module never reads the clock.
"""
from __future__ import annotations

import dataclasses
import logging
import multiprocessing
import queue
from dataclasses import dataclass
from typing import Protocol

from . import acquisition, config
from .config import Settings
from .escalation import Attempt, Escalation, Step
from .model import Sample

_log = logging.getLogger(__name__)


# --- events for the window ---------------------------------------------------
@dataclass(frozen=True)
class Up:
    description: str
    ljm_version: str
    firmware: str
    warning: str
    recovered_by: Step | None


@dataclass(frozen=True)
class Down:
    reason: str
    attempt: Attempt | None


@dataclass(frozen=True)
class Reconnecting:
    attempt: Attempt


@dataclass(frozen=True)
class ReadError:
    message: str


@dataclass(frozen=True)
class NewSample:
    sample: Sample


# --- the child ---------------------------------------------------------------
class ChildHandle(Protocol):
    def send(self, command: object) -> None: ...
    def receive(self) -> list[object]: ...
    def alive(self) -> bool: ...
    def terminate(self) -> None: ...
    def kill(self) -> None: ...
    def join(self, timeout: float | None = None) -> None: ...


class _ProcessChild:
    """The real child: `acquisition.run` in a spawned process, two queues."""

    def __init__(self, settings: Settings):
        ctx = multiprocessing.get_context("spawn")
        self._commands = ctx.Queue()
        self._events = ctx.Queue()
        self._process = ctx.Process(
            target=acquisition.run, args=(self._commands, self._events), daemon=True)
        self._process.start()

    def send(self, command: object) -> None:
        self._commands.put(command)

    def receive(self) -> list[object]:
        out: list[object] = []
        while True:
            try:
                out.append(self._events.get_nowait())
            except queue.Empty:
                return out

    def alive(self) -> bool:
        return self._process.is_alive()

    def terminate(self) -> None:
        self._process.terminate()

    def kill(self) -> None:
        self._process.kill()

    def join(self, timeout: float | None = None) -> None:
        self._process.join(timeout)
        if not self._process.is_alive():
            # Never let a queue's feeder thread keep the window process from exiting.
            for q in (self._commands, self._events):
                q.close()
                q.cancel_join_thread()


def spawn_child(settings: Settings) -> ChildHandle:
    return _ProcessChild(settings)


class Supervisor:
    def __init__(self, spawn=spawn_child):
        self._spawn = spawn
        self._child: ChildHandle | None = None
        self._settings = Settings()
        self._wanted = False                # the operator pressed Connect
        self._esc = Escalation()
        self._attempt: Attempt | None = None    # the latest Attempt issued
        self._last_heard = 0.0
        self._pending: list[object] = []    # window events produced outside poll()

    @property
    def child(self) -> ChildHandle | None:
        return self._child

    # --- the window's calls -----------------------------------------------
    def connect(self, now: float, settings: Settings) -> None:
        self._stop_child()
        self._esc.reset()
        self._attempt = None
        self._pending = []
        self._wanted = True
        self._settings = dataclasses.replace(settings)
        self._start_child(now)

    def disconnect(self, now: float) -> None:
        self._wanted = False
        self._esc.reset()
        self._attempt = None
        self._pending = []
        self._stop_child()

    def update_settings(self, now: float, settings: Settings) -> None:
        self._settings = dataclasses.replace(settings)
        if self._child is not None:
            self._child.send(acquisition.ApplySettings(dataclasses.replace(settings)))

    def shutdown(self) -> None:
        self._wanted = False
        self._stop_child()

    def poll(self, now: float) -> list[object]:
        out, self._pending = self._pending, []
        if not self._wanted:
            return out
        if self._child is not None:
            messages = self._child.receive()
            if messages:
                self._last_heard = now
            for message in messages:
                out.extend(self._translate(message, now))
            out.extend(self._check_child(now))
        attempt = self._esc.due(now)
        if attempt is not None:
            out.append(self._run_attempt(attempt, now))
        return out

    # --- child messages -> window events ------------------------------------
    def _translate(self, message: object, now: float) -> list[object]:
        if isinstance(message, acquisition.LinkUp):
            recovered_by = self._esc.current_step if self._esc.climbing else None
            return [Up(message.description, message.ljm_version, message.firmware,
                       message.warning, recovered_by)]
        if isinstance(message, acquisition.LinkDown):
            return [self._failed(now, message.reason)]
        if isinstance(message, acquisition.Lost):
            if self._esc.in_flight:
                # It opened but could not be read: that Attempt did not work after all.
                return [self._failed(now, message.reason)]
            if not self._esc.climbing:
                self._esc.lost(now, retry_now=True)
            return []
        if isinstance(message, acquisition.ReadError):
            return [ReadError(message.message)]
        if isinstance(message, acquisition.SampleReady):
            self._esc.recovered(now)
            return [NewSample(message.sample)]
        return []                                           # Alive, or anything unknown

    def _failed(self, now: float, reason: str) -> Down:
        """An open (or the reads after it) failed: report it and schedule the next Attempt."""
        if not self._esc.climbing:
            self._esc.lost(now, retry_now=False)            # failed open at Connect
            return Down(reason, None)
        self._esc.failed(now, reason)
        attempt = self._attempt
        if attempt is not None:
            # hand_off turns on when this failure is the first failed Acquisition restart.
            attempt = dataclasses.replace(attempt, hand_off=self._esc.hand_off)
        return Down(reason, attempt)

    # --- watching the child -------------------------------------------------
    def _check_child(self, now: float) -> list[object]:
        if self._child is None:
            return []
        if not self._child.alive():
            reason = "acquisition process exited"
        elif now - self._last_heard > config.HUNG_AFTER_S:
            reason = "acquisition not responding"
        else:
            return []
        self._kill_child()
        self._esc.hung(now)
        return [Down(reason, None)]

    def _run_attempt(self, attempt: Attempt, now: float) -> Reconnecting:
        self._attempt = attempt
        child = self._child
        if child is not None and attempt.step is Step.REOPEN:
            child.send(acquisition.Reopen())
        elif child is not None and attempt.step is Step.LIBRARY_RESET:
            child.send(acquisition.LibraryReset())
        else:
            # Acquisition restart (or no child to talk to): a fresh process loads LJM afresh.
            self._stop_child()
            self._start_child(now)
        return Reconnecting(attempt)

    # --- starting and stopping ----------------------------------------------
    def _start_child(self, now: float) -> None:
        self._last_heard = now
        try:
            child = self._spawn(dataclasses.replace(self._settings))
            child.send(acquisition.Start(dataclasses.replace(self._settings)))
        except Exception as exc:  # noqa: BLE001 - reported as a Down event; Escalation retries
            self._child = None
            self._pending.append(Down(f"could not start acquisition: {exc}", None))
            if self._esc.climbing:
                self._esc.failed(now, str(exc))
            else:
                self._esc.lost(now, retry_now=False)
            return
        self._child = child

    def _stop_child(self) -> None:
        """Ask the child to quit, wait at most STOP_TIMEOUT_S, then terminate, then kill."""
        child, self._child = self._child, None
        if child is None:
            return
        try:
            child.send(acquisition.Quit())
        except Exception as exc:  # noqa: BLE001 - the pipe may already be gone; we kill it below
            _log.warning("could not send Quit to the acquisition child: %s", exc)
        self._finish(child, config.STOP_TIMEOUT_S)

    def _kill_child(self) -> None:
        """A hung or dead child gets no polite Quit."""
        child, self._child = self._child, None
        if child is not None:
            self._finish(child, 0.0)

    @staticmethod
    def _finish(child: ChildHandle, wait_s: float) -> None:
        child.join(wait_s)
        if child.alive():
            child.terminate()
            child.join(config.KILL_JOIN_S)
        if child.alive():
            child.kill()
            child.join(config.KILL_JOIN_S)
