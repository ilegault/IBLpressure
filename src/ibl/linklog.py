"""Link log: the permanent, on-disk record of every Link event. No Qt, no clock.

WHY THIS EXISTS
---------------
When the Link fails at 3 a.m. nobody is watching the screen. The Link log keeps every loss,
reconnect attempt and recovery, with the exact LabJack error text, so the failure can be
diagnosed afterwards (CONTEXT.md: Link log).

Files: one per calendar month, `<directory>/link-log/YYYY-MM.log` (local time), appended,
UTF-8, created on first write, kept forever. One line per event:
`YYYY-MM-DD HH:MM:SS  KIND  detail`. The Daily CSV system is not touched.

Folding: a record may carry a `fold_key`. The first record of a (kind, fold_key) inside a
LINK_LOG_FOLD_S window is written; later ones in that window are only counted. When the
window has ended (checked on the next record of any kind), or a record with no `fold_key`
arrives, a `REPEATED  {kind} {fold_key} ×{count} since {HH:MM:SS}` line is written first for
every key with a count above zero. A bad night therefore costs a few hundred lines.

File I/O is this module's job (AGENTS.md rule 1) but it never reads the clock: every call
takes `now`. A write failure never stops the app and is never swallowed (rule 7): `record`
returns False and `last_error` says why.
"""
from __future__ import annotations

import os
import re
from datetime import UTC, datetime

from . import config
from .escalation import Step

_FOLDER = "link-log"
_RECOVERED_RE = re.compile(r"^(?P<step>.+?) · gap (?P<gap>[0-9.]+) s$")


def _local(now: float) -> datetime:
    # The operator reads wall-clock time, so the log is in local time (as link.py does).
    return datetime.fromtimestamp(now, tz=UTC).astimezone()


class LinkLog:
    def __init__(self, directory: str):
        self._directory = directory
        # (kind, fold_key) -> [window start, suppressed count]
        self._folds: dict[tuple[str, str], list[float]] = {}
        self.last_error: str = ""

    def reconfigure(self, directory: str) -> None:
        """The CSV folder changed: write to the new folder from now on."""
        self._directory = directory

    @property
    def folder(self) -> str:
        return os.path.join(self._directory, _FOLDER)

    # --- writing ----------------------------------------------------------
    def record(self, now: float, kind: str, detail: str = "", fold_key: str | None = None,
               step: str | None = None, gap_s: float | None = None) -> bool:
        """Log one event. True if it was written or folded into a counted repeat."""
        if kind == "RECOVERED" and not detail and step is not None and gap_s is not None:
            detail = f"{step} · gap {gap_s:.0f} s"
        lines = self._flush_lines(now, everything=fold_key is None)
        counted = False
        if fold_key is not None:
            key = (kind, fold_key)
            if key in self._folds:
                self._folds[key][1] += 1
                counted = True
            else:
                self._folds[key] = [now, 0]
        if not counted:
            lines.append(self._format(now, kind, detail))
        if not lines:
            return True
        return self._write(now, lines)

    def _flush_lines(self, now: float, everything: bool) -> list[str]:
        """REPEATED lines for the keys whose window ended (or all of them), then forget them."""
        lines: list[str] = []
        for key, (start, count) in list(self._folds.items()):
            if everything or now - start >= config.LINK_LOG_FOLD_S:
                del self._folds[key]
                if count > 0:
                    kind, fold_key = key
                    since = _local(start).strftime("%H:%M:%S")
                    lines.append(self._format(now, "REPEATED", f"{kind} {fold_key} ×{int(count)} since {since}"))
        return lines

    @staticmethod
    def _format(now: float, kind: str, detail: str) -> str:
        return f"{_local(now):%Y-%m-%d %H:%M:%S}  {kind}  {detail}".rstrip()

    def _write(self, now: float, lines: list[str]) -> bool:
        path = os.path.join(self.folder, f"{_local(now):%Y-%m}.log")
        try:
            os.makedirs(self.folder, exist_ok=True)
            with open(path, "a", encoding="utf-8", newline="\n") as fh:
                fh.write("\n".join(lines) + "\n")
        except OSError as exc:
            self.last_error = f"Link log not written: {exc}"
            return False
        self.last_error = ""
        return True

    # --- reading (for the Connection frame) -------------------------------
    def _files_newest_first(self) -> list[str]:
        try:
            names = sorted((n for n in os.listdir(self.folder) if n.endswith(".log")), reverse=True)
        except OSError:
            return []
        return [os.path.join(self.folder, n) for n in names]

    @staticmethod
    def _read(path: str) -> list[str]:
        try:
            with open(path, encoding="utf-8") as fh:
                return [line for line in fh.read().splitlines() if line]
        except OSError:
            return []

    def recent(self, n: int) -> list[str]:
        """The last `n` log lines, newest first, reaching back into earlier months if needed."""
        out: list[str] = []
        for path in self._files_newest_first():
            out.extend(reversed(self._read(path)))
            if len(out) >= n:
                break
        return out[:n]

    def summary(self, now: float) -> str:
        """`Today: 3 recoveries — Reopen 2, Library reset 1 · longest gap 42 s`."""
        local = _local(now)
        path = os.path.join(self.folder, f"{local:%Y-%m}.log")
        today = f"{local:%Y-%m-%d} "
        counts: dict[str, int] = {}
        longest = 0.0
        total = 0
        for line in self._read(path):
            if not line.startswith(today):
                continue
            parts = line.split("  ", 2)
            if len(parts) < 3 or parts[1] != "RECOVERED":
                continue
            match = _RECOVERED_RE.match(parts[2])
            if match is None:
                continue
            total += 1
            counts[match["step"]] = counts.get(match["step"], 0) + 1
            longest = max(longest, float(match["gap"]))
        if total == 0:
            return "Today: no recoveries"
        order = [s.value for s in Step]
        steps = sorted(counts, key=lambda s: order.index(s) if s in order else len(order))
        by_step = ", ".join(f"{s} {counts[s]}" for s in steps)
        noun = "recovery" if total == 1 else "recoveries"
        return f"Today: {total} {noun} — {by_step} · longest gap {longest:.0f} s"
