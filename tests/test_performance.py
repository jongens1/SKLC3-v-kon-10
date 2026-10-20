from datetime import date
import numpy as np
import pandas as pd
import pytest
from src.data_processing import operational_window, planning_window, prepare_data, planning_metrics
from src.demo_data import demo_data
from src.performance import picking_deadlines, required_plan, apply_scaling, scaling_factor
from src.prepicking import simulate
from test_data_processing import row


def test_latest_pick_deadline_subtracts_safety_buffer():
    cutoff = pd.Series(pd.to_datetime(["2026-10-15T14:00:00+02:00"], utc=True))
    assert picking_deadlines(cutoff, 1).iloc[0] == pd.Timestamp("2026-10-15T13:00:00+02:00")
    with pytest.raises(ValueError):
        picking_deadlines(cutoff, -1)


def test_simulation_never_picks_before_creation_or_after_deadline():
    start, end = operational_window(date(2026, 10, 15))
    raw = pd.DataFrame([row(1, created_at="2026-10-15T07:10:00+02:00"),
                        row(2, created_at="2026-10-13T00:00:00+02:00")])
    data, _, _ = prepare_data(raw, start, end)
    hours = planning_window(start, end, 24)
    plan = required_plan(data, hours, 1)
    result = simulate(plan.groups, len(hours))
    assert result.scheduled == pytest.approx(2)
    for allocation in result.allocations.itertuples():
        assert allocation.release <= allocation.hour <= allocation.latest
    # Source row 1 is available only at 08:00; its deadline is 09:00.
    later = plan.groups[plan.groups.release == 26].index[0]
    assert result.allocations.loc[result.allocations.group == later, "hour"].min() == 26


def test_scaling_124000_to_150000_all_curves():
    coefficient = scaling_factor(124000, 150000)
    assert coefficient == pytest.approx(150000 / 124000)
    frame = pd.DataFrame(dict(created_count=[100], picked_count=[80], backlog=[20],
                              cumulative_created=[100], cumulative_picked=[80], cumulative_available=[100],
                              cumulative_required=[90], available_count=[100], required_pick_count=[90], prepick_smoothed_count=[85]))
    result = apply_scaling(frame, coefficient)
    for a, b in [("created_count", "created_scaled"), ("picked_count", "picked_scaled"),
                 ("backlog", "backlog_scaled"), ("required_pick_count", "required_pick_scaled"),
                 ("prepick_smoothed_count", "prepick_smoothed_scaled"), ("cumulative_required", "cumulative_required_scaled")]:
        assert result[b].iloc[0] == pytest.approx(frame[a].iloc[0] * coefficient)
    assert scaling_factor(124000, 0) == 0
    with pytest.raises(ValueError):
        scaling_factor(0, 1)


def test_minimax_known_optimum_and_shared_cap():
    groups = pd.DataFrame([dict(release=0, latest=3, count=80), dict(release=2, latest=3, count=40)])
    result = simulate(groups, 4)
    assert result.scheduled == pytest.approx(120, abs=1e-4)
    assert result.peak == pytest.approx(30, abs=1e-4)
    assert np.allclose(result.allocations.groupby("group")["count"].sum(), [80, 40])
    limited = simulate(groups, 4, max_per_hour=20)
    assert limited.hourly.max() <= 20 + 1e-6
    assert limited.scheduled + limited.unscheduled == pytest.approx(120)
    assert limited.unscheduled == pytest.approx(40, abs=1e-4)
    assert not limited.feasible


def test_lookback_makes_early_cutoff_feasible_without_per_job_limit():
    start, end = operational_window(date(2026, 10, 15))
    data, _, _ = prepare_data(pd.DataFrame([row(collection_at=start, created_at=start - pd.Timedelta(days=3))]), start, end)
    short = required_plan(data, planning_window(start, end, 0), 1)
    long = required_plan(data, planning_window(start, end, 24), 1)
    assert short.unscheduled["count"].sum() == 1
    result = simulate(long.groups, 48)
    assert result.scheduled == pytest.approx(1)
    # Full 23-hour feasible range before 05:00 is usable, not only last N per job.
    assert result.peak == pytest.approx(1 / 23, abs=1e-5)


def test_missing_created_and_deadline_before_creation_remain_in_demand():
    start, end = operational_window(date(2026, 10, 15))
    data, _, _ = prepare_data(pd.DataFrame([row(1, created_at=None),
                    row(2, created_at="2026-10-15T10:00:00+02:00")]), start, end)
    plan = required_plan(data, planning_window(start, end, 24), 1)
    assert plan.hourly.sum() == 2
    assert plan.unscheduled["count"].sum() == 2
    assert set(plan.unscheduled.reason) == {"missing_created", "deadline_before_creation"}
    assert plan.groups.empty


def test_demo_conservation_and_scaling_of_simulation():
    start, end = operational_window(date(2026, 10, 15))
    data, _, _ = prepare_data(demo_data(date(2026, 10, 15)), start, end)
    hours = planning_window(start, end, 24)
    plan = required_plan(data, hours, 1)
    a = simulate(plan.groups, len(hours))
    b = simulate(plan.groups, len(hours), factor=150000 / 124000)
    assert a.scheduled == pytest.approx(124000, abs=1e-3)
    assert b.scheduled == pytest.approx(150000, abs=1e-3)
    assert np.allclose(b.hourly, a.hourly * 150000 / 124000, atol=1e-3)
    metrics = planning_metrics(data, hours)
    assert np.min(metrics.cumulative_available - a.hourly.cumsum()) >= -1e-3
