"""One-day counterfactual: no historical prepicking, two inventory-safe scenarios."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd
from src.data_processing import planning_metrics
from src.performance import apply_scaling, required_plan, scaling_factor, PickingPlan
from src.prepicking import simulate, Simulation


def _whole_day_plan(data: pd.DataFrame, hours: pd.DatetimeIndex, safety: float) -> PickingPlan:
    """Keep late work in the queue: a missed cutoff does not make inventory disappear."""
    strict = required_plan(data, hours, safety)
    start = hours[0]
    rows = []
    for row in data.itertuples(index=False):
        if pd.isna(row.ready_at) or pd.isna(row.collection_at):
            continue
        release = max(0, int(np.ceil((row.ready_at-start).total_seconds()/3600)))
        latest = int(np.floor((row.collection_at-pd.Timedelta(hours=safety)-start).total_seconds()/3600))-1
        if release >= len(hours):
            continue
        on_time = release <= latest < len(hours)
        rows.append(dict(release=release, latest=latest if on_time else len(hours)-1,
                         count=float(row.jobline_count), on_time=on_time))
    groups = pd.DataFrame(rows,columns=["release","latest","count","on_time"])
    if len(groups):
        groups = groups.groupby(["on_time","release","latest"],as_index=False)["count"].sum()
        # Deadline-eligible groups enter the flow first, ahead of already-late work.
        groups = groups.sort_values(["on_time","latest","release"],ascending=[False,True,True]).reset_index(drop=True)
    strict.groups = groups
    return strict


def _deadline_unmet(plan: PickingPlan, simulation: Simulation, target: float) -> float:
    if simulation.allocations.empty:
        return target
    valid = plan.groups.index[plan.groups.on_time]
    on_time = simulation.allocations.loc[simulation.allocations.group.isin(valid),"count"].sum()
    return max(0.0, target-float(on_time))


@dataclass
class Dashboard:
    day: pd.DataFrame
    planning: pd.DataFrame
    initial_buffer: float
    created_before_day: float
    picked_before_day: float
    completed_before_planning: float
    factor: float
    unmet: float
    structural_unmet: float
    plan: PickingPlan
    simulation: Simulation
    total_volume: float


def _scale_simulation(base: Simulation, factor: float) -> Simulation:
    allocation = base.allocations.copy()
    allocation["count"] = allocation["count"] * factor
    return Simulation(base.hourly * factor, allocation, base.scheduled * factor,
                      base.unscheduled * factor, base.peak * factor, base.feasible or factor == 0)


def _profile_pick(available: np.ndarray, requested: np.ndarray) -> np.ndarray:
    """Unused hourly capacity is lost; unpicked work stays in the queue."""
    picked = np.zeros(len(available))
    queue = 0.0
    for hour, arrivals in enumerate(available):
        queue += arrivals
        picked[hour] = min(queue, requested[hour])
        queue = max(0.0, queue - picked[hour])
    return picked


def comparison_table(report: Dashboard, limited: bool = False) -> pd.DataFrame:
    """Boundary balances against original measured capacity, never normalized to target.

    Measured warehouse throughput is used as capacity for this cohort, not claimed
    as observed picking of the cohort. Historical prepicking remains irrelevant.
    """
    day = report.day
    current = day.current_pick.to_numpy()
    balanced = day["prepick_smoothed_scaled" if limited else "balanced_required"].to_numpy()
    initial = report.initial_buffer*report.factor
    created = np.r_[initial,day.cumulative_created_scaled.to_numpy()]
    current_total = np.r_[0.0,current.cumsum()]
    balanced_total = np.r_[0.0,balanced.cumsum()]
    return pd.DataFrame(dict(
        time=[day.hour.iloc[0]]+(day.hour+pd.Timedelta(hours=1)).tolist(),
        created=created,picked_balanced=balanced_total,picked_current=current_total,
        buffer_balanced=np.maximum(0,created-balanced_total),
        buffer_current=np.maximum(0,created-current_total)))


def hourly_output(report: Dashboard, limited: bool = True) -> pd.DataFrame:
    """Export the same scenario and time boundaries as the visible charts."""
    day = report.day
    balances = comparison_table(report,limited).iloc[1:].reset_index(drop=True)
    return pd.DataFrame(dict(
        hour_start=day.hour.to_numpy(),hour_end=balances.time.to_numpy(),
        created_in_hour=day.created_scaled.to_numpy(),released_at_slot_start=day.available_scaled.to_numpy(),
        available_before_current_pick=(day.cumulative_available_scaled-day.current_pick.cumsum().shift(fill_value=0)).to_numpy(),
        available_before_balanced_pick=(day.cumulative_available_scaled-balances.picked_balanced.shift(fill_value=0)).to_numpy(),
        created_total=balances.created.to_numpy(),
        current_pick=day.current_pick.to_numpy(),balanced_pick=np.diff(np.r_[0,balances.picked_balanced]),
        current_picked_total=balances.picked_current.to_numpy(),balanced_picked_total=balances.picked_balanced.to_numpy(),
        current_buffer=balances.buffer_current.to_numpy(),balanced_buffer=balances.buffer_balanced.to_numpy(),
        balanced_required_without_limit=day.balanced_required.to_numpy(),balanced_pick_with_limit=day.prepick_smoothed_scaled.to_numpy(),
        missed_deadlines_with_limit=day.deadline_shortfall_scaled.to_numpy(),
        completed_on_time_with_limit=day.cumulative_completed_on_time.to_numpy(),
        completed_late_with_limit=day.cumulative_completed_late.to_numpy()))


def _scenario_columns(day: pd.DataFrame, factor: float, simulation: Simulation,
                      required: Simulation, cap: float | None, plan: PickingPlan) -> pd.DataFrame:
    day = apply_scaling(day, factor)
    # This counterfactual ignores PickedDate entirely. Every created job starts unpicked.
    # One reference definition everywhere: original measured warehouse capacity.
    # It is never increased just because the scenario target increases.
    day["current_requested"] = day.warehouse_picked
    day["current_pick"] = _profile_pick(day.available_scaled.to_numpy(), day.current_requested.to_numpy())
    day["current_limited"] = _profile_pick(day.available_scaled.to_numpy(),
                                          np.minimum(day.current_requested, cap) if cap is not None else day.current_requested)
    day["balanced_required"] = required.hourly
    day["prepick_smoothed_scaled"] = simulation.hourly
    day["cumulative_simulated"] = simulation.hourly.cumsum()
    day["cumulative_current"] = day.current_pick.cumsum()
    day["cumulative_current_limited"] = day.current_limited.cumsum()
    day["cumulative_balanced_required"] = required.hourly.cumsum()
    day["scenario_backlog"] = day.cumulative_created_scaled - day.cumulative_simulated
    day["current_backlog"] = day.cumulative_created_scaled - day.cumulative_current
    day["current_limited_backlog"] = day.cumulative_created_scaled - day.cumulative_current_limited
    day["balanced_required_backlog"] = day.cumulative_created_scaled - day.cumulative_balanced_required
    on_time_due = np.zeros(len(day))
    on_time_hourly = np.zeros(len(day))
    late_hourly = np.zeros(len(day))
    for row in simulation.allocations.itertuples():
        if plan.groups.on_time.iloc[int(row.group)]:
            on_time_due[int(row.latest)] += row.count
            on_time_hourly[int(row.hour)] += row.count
        else:
            late_hourly[int(row.hour)] += row.count
    day["cumulative_completed_on_time"] = on_time_hourly.cumsum()
    day["cumulative_completed_late"] = late_hourly.cumsum()
    day["cumulative_on_time_due"] = on_time_due.cumsum()
    # Completing a late job never erases its missed deadline. Credit each
    # eligible group's completions only against its own deadline, not all demand.
    day["deadline_shortfall_scaled"] = np.maximum(0, day.cumulative_required_scaled - day.cumulative_on_time_due)
    day["backlog_risky"] = day.deadline_shortfall_scaled > max(1e-4, float(day.total_volume.iloc[0]) * factor * 1e-9)
    return day


def analyze(data: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, target: float,
            lookback: int = 0, safety: float = 1, cap: float | None = None,
            throughput: pd.DataFrame | None = None) -> Dashboard:
    """Planning always starts at day start; lookback is retained only for API compatibility."""
    hours = pd.date_range(start, end, freq="h", inclusive="left")
    total = float(data.jobline_count.sum())
    factor = scaling_factor(total, target)
    day = planning_metrics(data, hours)
    plan = _whole_day_plan(data, hours, safety)
    base_simulation = simulate(plan.groups, len(hours))
    required = _scale_simulation(base_simulation, factor)
    if cap is not None and (not np.isfinite(cap) or cap < 0):
        raise ValueError("Neplatný maximálny hodinový výkon.")
    scenario = required if cap is None or cap >= required.peak else simulate(plan.groups, len(hours), factor=factor, max_per_hour=cap)
    day["required_pick_count"] = plan.hourly
    day["cumulative_required"] = plan.overdue_before_window + plan.hourly.cumsum()
    day["prepick_smoothed_count"] = base_simulation.hourly
    day["total_volume"] = total
    if throughput is not None and len(throughput):
        observed = throughput.groupby("hour").picked_count.sum()
        day["warehouse_picked"] = observed.reindex(hours, fill_value=0).to_numpy(dtype=float)
    else:
        day["warehouse_picked"] = day.picked_count
    profile = day.warehouse_picked.to_numpy(dtype=float)
    day["profile_share"] = profile / profile.sum() if profile.sum() else np.full(len(hours), 1 / len(hours))
    day = _scenario_columns(day, factor, scenario, required, cap, plan)
    initial = float(data.loc[data.created_at < start, "jobline_count"].sum())
    historical_prepicked = float(data.loc[data.picked_at < start, "jobline_count"].sum())
    structural = float(plan.unscheduled["count"].sum()) if len(plan.unscheduled) else 0.0
    return Dashboard(day, day.copy(), initial, initial, historical_prepicked, 0.0, factor,
                     _deadline_unmet(plan,scenario,target), structural, plan, scenario, total)


def rescale(base: Dashboard, target: float, cap: float | None = None) -> Dashboard:
    """Reuse the unscaled balanced solution; capacity-limited planning is recomputed."""
    if base.factor != 1:
        raise ValueError("Rescaling requires an unscaled base report.")
    factor = scaling_factor(base.total_volume, target)
    required = _scale_simulation(base.simulation, factor)
    if cap is not None and (not np.isfinite(cap) or cap < 0):
        raise ValueError("Neplatný maximálny hodinový výkon.")
    scenario = required if cap is None or cap >= required.peak else simulate(base.plan.groups, len(base.day), factor=factor, max_per_hour=cap)
    day = _scenario_columns(base.day.copy(), factor, scenario, required, cap, base.plan)
    return Dashboard(day, day.copy(), base.initial_buffer, base.created_before_day, base.picked_before_day,
                     0.0, factor, _deadline_unmet(base.plan,scenario,target),
                     base.structural_unmet, base.plan, scenario, base.total_volume)
