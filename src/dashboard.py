"""Consistent real-day comparisons, historical opening buffer and target planning."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd
from src.data_processing import planning_metrics, planning_window
from src.performance import apply_scaling, required_plan, scaling_factor, PickingPlan
from src.prepicking import simulate, Simulation


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
    allocation["count"] = allocation["count"]*factor
    return Simulation(base.hourly*factor,allocation,base.scheduled*factor,
                      base.unscheduled*factor,base.peak*factor,base.feasible or factor == 0)


def analyze(data: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, target: float,
            lookback: int = 24, safety: float = 1, cap: float | None = None,
            throughput: pd.DataFrame | None = None) -> Dashboard:
    """Do not schedule work that was already completed before the planning horizon."""
    total = float(data.jobline_count.sum())
    factor = scaling_factor(total, target)
    hours = planning_window(start, end, lookback)
    completed = data.picked_at.notna() & (data.picked_at < hours[0])
    remaining = data.loc[~completed].reset_index(drop=True)
    historical = planning_metrics(data, hours)
    planning = planning_metrics(remaining, hours)
    plan = required_plan(remaining, hours, safety)
    demand = required_plan(data, hours, safety)
    actual_simulation = simulate(plan.groups, len(hours))
    scenario = (_scale_simulation(actual_simulation,factor) if cap is None
                else simulate(plan.groups,len(hours),factor=factor,max_per_hour=cap))
    done = float(data.loc[completed, "jobline_count"].sum())
    planning["required_pick_count"] = demand.hourly
    planning["cumulative_required"] = demand.overdue_before_window + demand.hourly.cumsum()
    planning["prepick_smoothed_count"] = actual_simulation.hourly
    planning = apply_scaling(planning, factor)
    planning["prepick_smoothed_scaled"] = scenario.hourly
    planning["cumulative_simulated"] = done * factor + scenario.hourly.cumsum()
    planning["cumulative_actual"] = historical.cumulative_picked
    planning["scenario_backlog"] = planning.cumulative_available_scaled - scenario.hourly.cumsum()
    planning["deadline_shortfall_scaled"] = np.maximum(0, planning.cumulative_required_scaled - planning.cumulative_simulated)
    planning["backlog_risky"] = planning.deadline_shortfall_scaled > max(1e-4, target * 1e-9)
    day_hours = pd.date_range(start, end, freq="h", inclusive="left")
    day = apply_scaling(planning_metrics(data, day_hours), factor)
    planned_day = planning.set_index("hour").reindex(day_hours)
    for column in ["required_pick_count", "required_pick_scaled", "prepick_smoothed_count", "prepick_smoothed_scaled",
                   "cumulative_required_scaled", "cumulative_simulated", "scenario_backlog", "backlog_risky", "deadline_shortfall_scaled"]:
        day[column] = planned_day[column].to_numpy()
    day["cumulative_actual"] = day.cumulative_picked
    if throughput is not None and len(throughput):
        observed = throughput.groupby("hour").picked_count.sum()
        day["warehouse_picked"] = observed.reindex(day_hours, fill_value=0).to_numpy(dtype=float)
    else:
        day["warehouse_picked"] = np.nan
    created_before = float(data.loc[data.created_at < start, "jobline_count"].sum())
    picked_before = float(data.loc[data.picked_at < start, "jobline_count"].sum())
    pending = data.picked_at.isna() | (data.picked_at >= start)
    initial = float(data.loc[(data.created_at < start) & pending, "jobline_count"].sum())
    structural = float(plan.unscheduled["count"].sum()) if len(plan.unscheduled) else 0.0
    return Dashboard(day, planning, initial, created_before, picked_before, done, factor,
                     structural * factor + scenario.unscheduled, structural, plan, scenario,total)


def rescale(base: Dashboard, target: float, cap: float | None = None) -> Dashboard:
    """Instant target-volume changes reuse the unscaled schedule unless a cap changes it."""
    factor = scaling_factor(base.total_volume,target)
    if base.factor != 1:
        raise ValueError("Rescaling requires an unscaled base report.")
    scenario = (_scale_simulation(base.simulation,factor) if cap is None else
                simulate(base.plan.groups,len(base.planning),factor=factor,max_per_hour=cap))
    planning = apply_scaling(base.planning,factor)
    planning["prepick_smoothed_scaled"] = scenario.hourly
    planning["cumulative_simulated"] = base.completed_before_planning*factor+scenario.hourly.cumsum()
    planning["scenario_backlog"] = planning.cumulative_available_scaled-scenario.hourly.cumsum()
    planning["deadline_shortfall_scaled"] = np.maximum(0,planning.cumulative_required_scaled-planning.cumulative_simulated)
    planning["backlog_risky"] = planning.deadline_shortfall_scaled > max(1e-4,target*1e-9)
    day = apply_scaling(base.day,factor)
    daily = planning.set_index("hour").reindex(pd.DatetimeIndex(day.hour))
    for column in ["prepick_smoothed_scaled","cumulative_required_scaled","cumulative_simulated",
                   "scenario_backlog","deadline_shortfall_scaled","backlog_risky"]:
        day[column] = daily[column].to_numpy()
    return Dashboard(day,planning,base.initial_buffer,base.created_before_day,base.picked_before_day,
                     base.completed_before_planning,factor,base.structural_unmet*factor+scenario.unscheduled,
                     base.structural_unmet,base.plan,scenario,base.total_volume)
