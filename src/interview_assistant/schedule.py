"""FR-09 schedule matching: common free time of several interviewers, and slots in it.

Same rules as the frontend's lib/schedule.ts (`commonFreeIntervals`, `suggestSlots`), plus one the
mock does not apply: time already booked for a scheduled or running interview is not free.
`absorb` is the rule for writing one interviewer's blocks: touching blocks become one.
Intervals are (start, end) in epoch milliseconds.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence

Interval = tuple[int, int]
MINUTE = 60_000


def merge(intervals: Iterable[Interval]) -> list[Interval]:
    out: list[list[int]] = []
    for start, end in sorted(intervals):
        if out and start <= out[-1][1]:
            out[-1][1] = max(out[-1][1], end)
        else:
            out.append([start, end])
    return [(a, b) for a, b in out]


def absorb(others: Mapping[str, Interval], new: Interval) -> tuple[Interval, list[str]]:
    """What `new` becomes when it is written beside one interviewer's other blocks: a single block
    that also covers every block touching or overlapping it (directly or through another one), and
    the ids of the blocks it replaces. So one person's free time is never two boxes on top of
    each other. Same rule as the frontend's `absorbInto`."""
    joined = next(m for m in merge([*others.values(), new]) if m[0] <= new[0] and new[1] <= m[1])
    return joined, [i for i, (a, b) in others.items() if joined[0] <= a and b <= joined[1]]


def subtract(intervals: Iterable[Interval], busy: Iterable[Interval]) -> list[Interval]:
    free = merge(intervals)
    for b_start, b_end in merge(busy):
        nxt: list[Interval] = []
        for start, end in free:
            if b_end <= start or end <= b_start:
                nxt.append((start, end))
                continue
            if start < b_start:
                nxt.append((start, b_start))
            if b_end < end:
                nxt.append((b_end, end))
        free = nxt
    return free


def common_free(
    by_interviewer: Mapping[str, Sequence[Interval]],
    interviewer_ids: Sequence[str],
    min_count: int | None = None,
) -> list[tuple[int, int, list[str]]]:
    """Stretches in which at least `min_count` of the interviewers are free at once."""
    need = len(interviewer_ids) if min_count is None else min_count
    if not interviewer_ids or need <= 0:
        return []
    points = sorted({p for i in interviewer_ids for it in by_interviewer.get(i, ()) for p in it})
    out: list[tuple[int, int, list[str]]] = []
    for start, end in zip(points, points[1:]):
        mid = (start + end) / 2
        ids = [
            i for i in interviewer_ids if any(a <= mid < b for a, b in by_interviewer.get(i, ()))
        ]
        if len(ids) < need:
            continue
        if out and out[-1][1] == start and out[-1][2] == ids:
            out[-1] = (out[-1][0], end, ids)
        else:
            out.append((start, end, ids))
    return out


def suggest_slots(
    by_interviewer: Mapping[str, Sequence[Interval]],
    interviewer_ids: Sequence[str],
    duration_minutes: int,
    *,
    min_count: int | None = None,
    start_from: int | None = None,
    until: int | None = None,
    limit: int = 8,
) -> list[tuple[int, int, list[str]]]:
    """Slots of `duration_minutes` aligned to 30 minutes, earliest first, at most one per hour of
    a free stretch so the list stays short."""
    step = 30 * MINUTE
    duration = duration_minutes * MINUTE
    out = []
    for start, end, ids in common_free(by_interviewer, interviewer_ids, min_count):
        t = math.ceil(max(start, start_from if start_from is not None else start) / step) * step
        stop = min(end, until if until is not None else end)
        while t + duration <= stop:
            out.append((t, t + duration, ids))
            t += max(duration, 60 * MINUTE)
    out.sort(key=lambda x: (x[0], -len(x[2])))
    return out[:limit]
