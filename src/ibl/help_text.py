"""The text of the in-app Help dialog. Qt-free, built from the real constants.

Every number comes from config.py, link.py or history.py, so the Help cannot drift
away from what the app does (AGENTS.md rules 6 and 8).
"""
from __future__ import annotations

from .config import (
    MAX_HISTORY_S,
    MAX_LATE_AFTER_SAMPLES,
    MAX_SAMPLE_HZ,
    MIN_CSV_INTERVAL_S,
    MIN_LATE_AFTER_SAMPLES,
    MIN_SAMPLE_HZ,
    Settings,
)
from .history import RAW_SPAN_S, SUMMARY_BUCKET_S
from .link import RECOVERY_NOTICE_S, LinkMonitor
from .model import GaugeStatus

HELP_HINT = "(Help explains more.)"


def _span(seconds: float) -> str:
    """'1 h' for whole hours, else seconds."""
    if seconds % 3600 == 0:
        return f"{int(seconds // 3600)} h"
    return f"{seconds:g} s"


def help_html(settings: Settings) -> str:
    late_s = LinkMonitor(settings.late_after_samples, settings.sample_hz).late_threshold_s
    raw = _span(RAW_SPAN_S)
    bucket = f"{SUMMARY_BUCKET_S} s"
    history = _span(MAX_HISTORY_S)
    return f"""
<h2>How IBL Pressure works</h2>

<h3>Status light</h3>
<p>The dot next to the status line says whether the connection to the LabJack T7 is
delivering fresh data. It is the only thing that says so.</p>
<ul>
<li><b>Idle (grey)</b> &ndash; you have not pressed Connect.</li>
<li><b>Live (green)</b> &ndash; samples are arriving on time.</li>
<li><b>Late (amber)</b> &ndash; connecting, reconnecting, or no sample for longer than
the late threshold (see below).</li>
<li><b>Down (red)</b> &ndash; the T7 cannot be found; the app retries every 5 s.</li>
</ul>
<p>One faulted gauge does not change the status light or the status line: a bad gauge
only changes its own row. After a gap the status line reports the recovery for
{RECOVERY_NOTICE_S:.0f} s.</p>

<h3>When data is late</h3>
<p>With your current settings ({settings.late_after_samples} missed samples at
{settings.sample_hz:g} Hz) data counts as late after <b>{late_s:.1f} s</b> without a
new sample. The light turns amber, every pressure cell shows <b>STALE</b>, and the last
value moves to the Status column with its age. A number in a pressure cell is always
current; it is never an old value that only looks live.</p>

<h3>Gauge status colours</h3>
<p>These colour only the row of the gauge concerned.</p>
<ul>
<li><b>Red</b> &ndash; {GaugeStatus.FAULT.value} or {GaugeStatus.NEGATIVE.value}: the
reading cannot be trusted, so no pressure is shown.</li>
<li><b>Yellow</b> &ndash; {GaugeStatus.UNDER.value} or {GaugeStatus.OVER.value}: the
voltage is outside the gauge's measuring range.</li>
<li><b>Orange</b> &ndash; {GaugeStatus.APPROX.value}: the Convectron is near the bottom
of its range and is only approximate; read the Ion Gauge instead.</li>
</ul>

<h3>The plot at long time spans</h3>
<p>Only the most recent {raw} is kept sample by sample. Older data is summarised as
<b>min/max per {bucket}</b>: the lowest and highest reading of each {bucket}, so a
short spike still shows on a 24 h plot. Gaps in the data are drawn as breaks in
the line. Up to {history} of history is kept.</p>

<h3>CSV log files</h3>
<p>One file per day, named by date (for example <code>2026-08-18.csv</code>), in the
log folder. Restarting the app <b>appends</b> to the day's file rather than replacing
it. If the columns change during the day (for example when you tick &ldquo;Also record
raw volts&rdquo;), the app starts a second file with a <code>_b</code> suffix
(<code>2026-08-18_b.csv</code>, then <code>_c</code>, and so on) so a file never mixes two
headers. A faulted gauge is written as its status text, never as a number. When the app
starts it reloads today's and yesterday's files into the plot.</p>

<h3>Settings you can change</h3>
<ul>
<li><b>Update rate</b> &ndash; {MIN_SAMPLE_HZ:g} to {MAX_SAMPLE_HZ:g} Hz.</li>
<li><b>Late after</b> &ndash; {MIN_LATE_AFTER_SAMPLES} to {MAX_LATE_AFTER_SAMPLES} missed
samples; the preview shows it in seconds.</li>
<li><b>CSV interval</b> &ndash; at least {MIN_CSV_INTERVAL_S:g} s; the size preview
estimates one day's file.</li>
<li><b>History</b> &ndash; up to {history} kept in memory for the plot.</li>
<li><b>Simulation mode</b> &ndash; fake data, no LabJack needed. Never trust it for a
real beamline.</li>
</ul>
"""
