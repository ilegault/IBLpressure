"""Two-tier History and min/max decimation for the plot. Pure numpy: no Qt, no clock.

The Raw tier keeps every Sample for the most recent RAW_SPAN_S. Older data is folded
into the Summary tier: the minimum and maximum of each SUMMARY_BUCKET_S bucket, per
Channel. Nothing older than the History span is kept, so memory is bounded whatever
the sample rate (ADR 0002).

`minmax_decimate` turns any window of that data into at most two points per Plot
bucket (one pixel of time), with Gaps as NaN breaks in the line.
"""
from __future__ import annotations

import numpy as np

from ibl import config

RAW_SPAN_S = 3600
SUMMARY_BUCKET_S = 10


class History:
    """Preallocated ring buffers: a Raw tier (every Sample) and a Summary tier (min/max)."""

    def __init__(
        self,
        n_channels: int,
        max_span_s: int = config.MAX_HISTORY_S,
        raw_span_s: int = RAW_SPAN_S,
        bucket_s: int = SUMMARY_BUCKET_S,
        max_rate_hz: float = config.MAX_SAMPLE_HZ,
    ) -> None:
        self.n_channels = n_channels
        self.max_span_s = max_span_s
        self.raw_span_s = min(raw_span_s, max_span_s)
        self.bucket_s = bucket_s

        self._raw_cap = int(self.raw_span_s * max_rate_hz) + 2
        self._raw_t = np.empty(self._raw_cap)
        self._raw_v = np.empty((self._raw_cap, n_channels))
        self._raw_start = 0
        self._raw_n = 0

        self._sum_cap = int(max_span_s // bucket_s) + 2
        self._sum_id = np.empty(self._sum_cap, dtype=np.int64)
        self._sum_lo = np.empty((self._sum_cap, n_channels))
        self._sum_hi = np.empty((self._sum_cap, n_channels))
        self._sum_start = 0
        self._sum_n = 0

    def clear(self) -> None:
        self._raw_start = self._raw_n = 0
        self._sum_start = self._sum_n = 0

    def memory_bytes(self) -> int:
        arrays = (self._raw_t, self._raw_v, self._sum_id, self._sum_lo, self._sum_hi)
        return sum(a.nbytes for a in arrays)

    def append(self, t: float, values: np.ndarray) -> None:
        """Add one Sample. `values` has one entry per channel; NaN = no valid pressure."""
        if self._raw_n == self._raw_cap:
            self._fold_oldest_raw()  # faster than max_rate_hz: never grow, never crash
        i = (self._raw_start + self._raw_n) % self._raw_cap
        self._raw_t[i] = t
        self._raw_v[i] = values
        self._raw_n += 1

        raw_cutoff = t - self.raw_span_s
        while self._raw_n and self._raw_t[self._raw_start] <= raw_cutoff:
            self._fold_oldest_raw()

        sum_cutoff = t - self.max_span_s
        while self._sum_n and self._sum_id[self._sum_start] * self.bucket_s < sum_cutoff:
            self._sum_start = (self._sum_start + 1) % self._sum_cap
            self._sum_n -= 1
        while self._raw_n and self._raw_t[self._raw_start] < sum_cutoff:
            self._raw_start = (self._raw_start + 1) % self._raw_cap
            self._raw_n -= 1

    def _fold_oldest_raw(self) -> None:
        s = self._raw_start
        t, row = self._raw_t[s], self._raw_v[s]
        bucket = int(np.floor(t / self.bucket_s))
        last = (self._sum_start + self._sum_n - 1) % self._sum_cap
        if self._sum_n and self._sum_id[last] == bucket:
            # fmin/fmax ignore NaN, so a bucket with any finite value keeps it
            self._sum_lo[last] = np.fmin(self._sum_lo[last], row)
            self._sum_hi[last] = np.fmax(self._sum_hi[last], row)
        else:
            if self._sum_n == self._sum_cap:
                self._sum_start = (self._sum_start + 1) % self._sum_cap
                self._sum_n -= 1
            i = (self._sum_start + self._sum_n) % self._sum_cap
            self._sum_id[i] = bucket
            self._sum_lo[i] = row
            self._sum_hi[i] = row
            self._sum_n += 1
        self._raw_start = (s + 1) % self._raw_cap
        self._raw_n -= 1

    def window(
        self, channel: int, t0: float, t1: float
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Points with t0 <= t < t1, in time order, as (t, lo, hi). Raw points have lo == hi.

        A Summary point is stamped with the start of its bucket, so it sorts before any
        Raw point that follows it.
        """
        si = (self._sum_start + np.arange(self._sum_n)) % self._sum_cap
        st = self._sum_id[si] * float(self.bucket_s)
        sm = (st >= t0) & (st < t1)
        ri = (self._raw_start + np.arange(self._raw_n)) % self._raw_cap
        rt = self._raw_t[ri]
        rm = (rt >= t0) & (rt < t1)
        raw = self._raw_v[ri[rm], channel]
        t = np.concatenate([st[sm], rt[rm]])
        lo = np.concatenate([self._sum_lo[si[sm], channel], raw])
        hi = np.concatenate([self._sum_hi[si[sm], channel], raw])
        return t, lo, hi


def minmax_decimate(
    t: np.ndarray,
    lo: np.ndarray,
    hi: np.ndarray,
    t0: float,
    t1: float,
    n_buckets: int,
    gap_s: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Reduce a time-ordered window to at most two points per Plot bucket.

    Each of the `n_buckets` equal slices of [t0, t1] emits its minimum and maximum in the
    order they occur; a slice with no finite data emits one NaN; two neighbouring output
    points further apart than `gap_s` get a NaN between them. NaN is a break in the line.
    """
    t = np.asarray(t, dtype=float)
    lo = np.asarray(lo, dtype=float)
    hi = np.asarray(hi, dtype=float)
    empty = np.empty(0)
    if n_buckets < 1 or t1 <= t0:
        return empty, empty.copy()

    keep = (t >= t0) & (t <= t1) & np.isfinite(lo) & np.isfinite(hi)
    t, lo, hi = t[keep], lo[keep], hi[keep]
    width = (t1 - t0) / n_buckets
    bucket = np.minimum(((t - t0) / width).astype(np.int64), n_buckets - 1)

    out_t: list[np.ndarray] = []
    out_p: list[np.ndarray] = []
    out_key: list[np.ndarray] = []  # sort key: bucket * 2 + position within bucket

    present = np.zeros(n_buckets, dtype=bool)
    if len(t):
        starts = np.flatnonzero(np.r_[True, np.diff(bucket) != 0])
        gid = np.repeat(np.arange(len(starts)), np.diff(np.r_[starts, len(t)]))
        b_of_group = bucket[starts]
        present[b_of_group] = True
        mn = np.minimum.reduceat(lo, starts)
        mx = np.maximum.reduceat(hi, starts)
        pos_mn = _first_match(lo == mn[gid], gid)
        pos_mx = _first_match(hi == mx[gid], gid)
        min_first = pos_mn <= pos_mx
        first_pos = np.where(min_first, pos_mn, pos_mx)
        first_val = np.where(min_first, mn, mx)
        second_pos = np.where(min_first, pos_mx, pos_mn)
        second_val = np.where(min_first, mx, mn)
        single = (first_pos == second_pos) & (first_val == second_val)
        out_t += [t[first_pos], t[second_pos[~single]]]
        out_p += [first_val, second_val[~single]]
        out_key += [b_of_group * 2, b_of_group[~single] * 2 + 1]

    gaps = np.flatnonzero(~present)
    if len(gaps):
        out_t.append(t0 + (gaps + 0.5) * width)
        out_p.append(np.full(len(gaps), np.nan))
        out_key.append(gaps * 2)

    if not out_t:
        return empty, empty.copy()
    order = np.argsort(np.concatenate(out_key), kind="stable")
    t_out = np.concatenate(out_t)[order]
    p_out = np.concatenate(out_p)[order]

    both = np.isfinite(p_out[:-1]) & np.isfinite(p_out[1:])
    breaks = np.flatnonzero(both & (np.diff(t_out) > gap_s)) + 1
    if len(breaks):
        mid = (t_out[breaks - 1] + t_out[breaks]) / 2
        t_out = np.insert(t_out, breaks, mid)
        p_out = np.insert(p_out, breaks, np.nan)
    return t_out, p_out


def _first_match(mask: np.ndarray, gid: np.ndarray) -> np.ndarray:
    """Index of the first True in each group (every group has at least one)."""
    idx = np.flatnonzero(mask)
    _, first = np.unique(gid[idx], return_index=True)
    return idx[first]
