"""Continuous volume minimax scheduling using bipartite maximum flow.

Each group connects only to eligible complete hourly slots. A max flow checks a
peak limit. Bisection finds the smallest feasible peak; a user cap returns the
maximum schedulable volume and explicitly accounts for any remainder.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass
class Simulation:
    hourly: np.ndarray
    allocations: pd.DataFrame
    scheduled: float
    unscheduled: float
    peak: float
    feasible: bool


class _Flow:
    def __init__(self, n: int):
        self.graph: list[list[list[float | int]]] = [[] for _ in range(n)]

    def add(self, a: int, b: int, capacity: float) -> list:
        forward = [b, len(self.graph[b]), float(capacity)]
        reverse = [a, len(self.graph[a]), 0.0]
        self.graph[a].append(forward)
        self.graph[b].append(reverse)
        return forward

    def maximum(self, source: int, sink: int) -> float:
        total = 0.0
        while True:
            level = [-1] * len(self.graph)
            level[source] = 0
            queue = deque([source])
            while queue:
                node = queue.popleft()
                for other, _, remaining in self.graph[node]:
                    if remaining > 1e-8 and level[other] < 0:
                        level[other] = level[node] + 1
                        queue.append(other)
            if level[sink] < 0:
                return total
            position = [0] * len(self.graph)

            def send(node: int, available: float) -> float:
                if node == sink:
                    return available
                while position[node] < len(self.graph[node]):
                    edge = self.graph[node][position[node]]
                    other, reverse, remaining = edge
                    if remaining > 1e-8 and level[other] == level[node] + 1:
                        sent = send(other, min(available, remaining))
                        if sent > 1e-8:
                            edge[2] -= sent
                            self.graph[other][reverse][2] += sent
                            return sent
                    position[node] += 1
                return 0.0

            while True:
                amount = send(source, float("inf"))
                if amount <= 1e-8:
                    break
                total += amount


def simulate(groups: pd.DataFrame, n_hours: int, prepick_hours: int,
             factor: float = 1.0, max_per_hour: float | None = None) -> Simulation:
    """Pre-picking window is relative to each group's baseline latest picking slot."""
    if not 0 <= prepick_hours <= 12:
        raise ValueError("Okno predpickovania musí byť 0 až 12 hodín.")
    if factor < 0 or not np.isfinite(factor):
        raise ValueError("Neplatný scaling.")
    if max_per_hour is not None and (max_per_hour < 0 or not np.isfinite(max_per_hour)):
        raise ValueError("Neplatný maximálny hodinový výkon.")
    groups = groups.reset_index(drop=True)
    counts = groups["count"].to_numpy(dtype=float) * factor
    total = float(counts.sum())
    empty = pd.DataFrame(columns=["group", "release", "latest", "earliest", "hour", "count"])
    if not total:
        return Simulation(np.zeros(n_hours), empty, 0.0, 0.0, 0.0, True)
    tolerance = max(1e-5, total * 1e-10)

    def run(peak: float, details: bool = False):
        source = len(groups) + n_hours
        sink = source + 1
        flow = _Flow(sink + 1)
        refs = []
        for i, row in enumerate(groups.itertuples()):
            flow.add(source, i, counts[i])
            earliest = max(int(row.release), int(row.latest) - prepick_hours)
            if earliest < 0 or row.latest >= n_hours or earliest > row.latest:
                raise ValueError("Skupina nemá platný hodinový interval.")
            for hour in range(earliest, int(row.latest) + 1):
                edge = flow.add(i, len(groups) + hour, counts[i])
                refs.append((i, int(row.release), int(row.latest), earliest, hour, edge))
        for hour in range(n_hours):
            flow.add(len(groups) + hour, sink, peak)
        scheduled = flow.maximum(source, sink)
        if not details:
            return scheduled
        rows = [dict(group=i, release=release, latest=latest, earliest=earliest,
                     hour=hour, count=max(0.0, counts[i] - edge[2]))
                for i, release, latest, earliest, hour, edge in refs if counts[i] - edge[2] > 1e-8]
        return scheduled, pd.DataFrame(rows, columns=empty.columns)

    upper = max_per_hour if max_per_hour is not None else total
    achievable = min(total, run(upper))
    lo, hi = 0.0, upper
    for _ in range(38):
        middle = (lo + hi) / 2
        if run(middle) >= achievable - tolerance:
            hi = middle
        else:
            lo = middle
    scheduled, allocation = run(min(upper, hi + tolerance), True)
    hourly = np.zeros(n_hours)
    if len(allocation):
        np.add.at(hourly, allocation.hour.to_numpy(dtype=int), allocation["count"].to_numpy())
    missing = max(0.0, total - scheduled)
    return Simulation(hourly, allocation, scheduled, missing, float(hourly.max()), missing <= tolerance)
