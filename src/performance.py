"""Baseline picking obligations and consistent volume scaling."""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass
class PickingPlan:
    hourly: np.ndarray
    groups: pd.DataFrame
    unscheduled: pd.DataFrame
    warnings: list[str]
    fallback_count: float = 0


def scaling_factor(actual: float, target: float) -> float:
    if actual <= 0:
        raise ValueError("Prázdny deň nemá definovaný scaling koeficient.")
    if target < 0 or not np.isfinite(target):
        raise ValueError("Cieľový objem musí byť nezáporný a konečný.")
    return target / actual


def required_plan(data: pd.DataFrame, hours: pd.DatetimeIndex,
                  safety_hours: float = 1) -> PickingPlan:
    """Latest full hourly slot before exact cutoff minus safety; no work before ready."""
    if not np.isfinite(safety_hours) or safety_hours < 0:
        raise ValueError("Bezpečnostný predstih musí byť nezáporný.")
    start, end = hours[0], hours[-1] + pd.Timedelta(hours=1)
    groups, rejected = [], []
    fallback = 0.0
    future_cutoff = 0.0
    for row in data.itertuples(index=False):
        count = float(row.jobline_count)
        release = max(0, int(np.ceil((row.ready_at - start).total_seconds() / 3600)))
        if row.invalid_order:
            rejected.append(dict(reason="invalid_pick_order", count=count))
            continue
        if pd.notna(row.cutoff_at):
            deadline = row.cutoff_at - pd.Timedelta(hours=safety_hours)
            latest = int(np.floor((deadline - start).total_seconds() / 3600)) - 1
            future_cutoff += count if deadline > end else 0
        else:
            fallback += count
            if pd.isna(row.picked_at):
                rejected.append(dict(reason="missing_cutoff_and_pick", count=count))
                continue
            latest = int(np.floor((row.picked_at - start).total_seconds() / 3600))
            deadline = start + pd.Timedelta(hours=latest + 1)
        latest = min(len(hours) - 1, latest)
        if release > latest or latest < 0 or release >= len(hours):
            rejected.append(dict(reason="no_full_slot_before_deadline", count=count))
        else:
            groups.append(dict(release=release, latest=latest, count=count))
    frame = pd.DataFrame(groups, columns=["release", "latest", "count"])
    if not frame.empty:
        frame = frame.groupby(["release", "latest"], as_index=False)["count"].sum()
    hourly = np.zeros(len(hours), dtype=float)
    if len(frame):
        np.add.at(hourly, frame.latest.to_numpy(dtype=int), frame["count"].to_numpy())
    warnings = []
    if fallback:
        warnings.append(f"FALLBACK: {fallback:,.0f} joblines nemá cutoff. Ak majú čas pickovania, použije sa jeho hodina; bez oboch časov zostávajú nenaplánované. Deadline expedície nie je overený.")
    if future_cutoff:
        warnings.append(f"{future_cutoff:,.0f} joblines má pick deadline po konci dňa. Scenár požaduje ich dokončenie už v sledovanom dni.")
    unscheduled = pd.DataFrame(rejected, columns=["reason", "count"])
    if len(unscheduled):
        unscheduled = unscheduled.groupby("reason", as_index=False)["count"].sum()
    return PickingPlan(hourly, frame, unscheduled, warnings, fallback)


def apply_scaling(hourly: pd.DataFrame, factor: float) -> pd.DataFrame:
    result = hourly.copy()
    names = {"created_count": "created_scaled", "picked_count": "picked_scaled",
             "cumulative_created": "cumulative_created_scaled", "cumulative_picked": "cumulative_picked_scaled",
             "backlog": "backlog_scaled", "required_pick_count": "required_pick_scaled",
             "prepick_smoothed_count": "prepick_smoothed_scaled"}
    for column, target in names.items():
        if column in result:
            result[target] = result[column] * factor
    return result
