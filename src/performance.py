"""Collection deadlines, conservative hourly demand and uniform scaling."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass
class PickingPlan:
    hourly: np.ndarray
    groups: pd.DataFrame
    unscheduled: pd.DataFrame
    deadlines: pd.DataFrame
    overdue_before_window: float


def scaling_factor(actual: float, target: float) -> float:
    if actual <= 0 or not np.isfinite(actual):
        raise ValueError("Reálny objem musí byť kladný.")
    if target < 0 or not np.isfinite(target):
        raise ValueError("Cieľový objem musí byť nezáporný a konečný.")
    return target / actual


def picking_deadlines(collection: pd.Series, safety_hours: float) -> pd.Series:
    if safety_hours < 0 or not np.isfinite(safety_hours):
        raise ValueError("Safety buffer musí byť nezáporný a konečný.")
    return collection - pd.Timedelta(hours=safety_hours)


def required_plan(data: pd.DataFrame, hours: pd.DatetimeIndex, safety_hours: float = 1) -> PickingPlan:
    """Demand includes infeasible jobs; only feasible groups enter the simulation."""
    deadline = picking_deadlines(data.collection_at, safety_hours)
    start = hours[0]
    hourly = np.zeros(len(hours), dtype=float)
    groups, rejected = [], []
    overdue = 0.0
    details = data[["collection_at", "created_at", "jobline_count", "job_type"]].copy()
    details["picking_deadline"] = deadline
    for i, row in enumerate(data.itertuples(index=False)):
        count = float(row.jobline_count)
        due = deadline.iloc[i]
        if pd.isna(due):
            rejected.append(dict(reason="missing_collection", count=count))
            continue
        latest = int(np.floor((due - start).total_seconds() / 3600)) - 1
        if latest < 0:
            overdue += count
        elif latest < len(hours):
            hourly[latest] += count
        if pd.isna(row.created_at) or pd.isna(row.ready_at):
            rejected.append(dict(reason="missing_created", count=count))
            continue
        release = max(0, int(np.ceil((row.ready_at - start).total_seconds() / 3600)))
        reason = None
        if due < row.created_at:
            reason = "deadline_before_creation"
        elif latest < 0:
            reason = "deadline_before_planning_window"
        elif latest >= len(hours):
            reason = "deadline_after_planning_window"
        elif release > latest or release >= len(hours):
            reason = "no_full_slot_before_deadline"
        if reason:
            rejected.append(dict(reason=reason, count=count))
        else:
            groups.append(dict(release=release, latest=latest, count=count))
    group_frame = pd.DataFrame(groups, columns=["release", "latest", "count"])
    if len(group_frame):
        group_frame = group_frame.groupby(["release", "latest"], as_index=False)["count"].sum()
    unscheduled = pd.DataFrame(rejected, columns=["reason", "count"])
    if len(unscheduled):
        unscheduled = unscheduled.groupby("reason", as_index=False)["count"].sum()
    return PickingPlan(hourly, group_frame, unscheduled, details, overdue)


def apply_scaling(frame: pd.DataFrame, factor: float) -> pd.DataFrame:
    result = frame.copy()
    mapping = {"created_count": "created_scaled", "picked_count": "picked_scaled",
               "available_count": "available_scaled", "cumulative_created": "cumulative_created_scaled",
               "cumulative_picked": "cumulative_picked_scaled", "cumulative_available": "cumulative_available_scaled",
               "cumulative_required": "cumulative_required_scaled", "backlog": "backlog_scaled",
               "required_pick_count": "required_pick_scaled", "prepick_smoothed_count": "prepick_smoothed_scaled"}
    for source, target in mapping.items():
        if source in result:
            result[target] = result[source] * factor
    return result
