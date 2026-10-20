from datetime import date
import numpy as np
import pandas as pd
import pytest
from src.data_processing import operational_window, prepare_data, demo_data, hourly_metrics
from src.performance import required_plan, scaling_factor, apply_scaling
from src.prepicking import simulate


def sample():
    start, end = operational_window(date(2026, 10, 15))
    data, _, _ = prepare_data(demo_data(date(2026, 10, 15)), start, end)
    hours = pd.date_range(start, end, freq="h", inclusive="left")
    return start, end, data, hours


def test_scaling_every_metric_and_zero_target():
    start, end, data, hours = sample()
    plan = required_plan(data, hours)
    hourly = hourly_metrics(data, start, end)
    hourly["required_pick_count"] = plan.hourly
    hourly["prepick_smoothed_count"] = simulate(plan.groups, len(hours), 4).hourly
    factor = scaling_factor(124000, 150000)
    scaled = apply_scaling(hourly, factor)
    assert scaled.created_scaled.sum() == pytest.approx(150000)
    for source, target in [("picked_count", "picked_scaled"), ("backlog", "backlog_scaled"),
                           ("required_pick_count", "required_pick_scaled"),
                           ("prepick_smoothed_count", "prepick_smoothed_scaled"),
                           ("cumulative_created", "cumulative_created_scaled")]:
        assert np.allclose(scaled[target], hourly[source] * factor)
    assert scaling_factor(124000, 0) == 0
    with pytest.raises(ValueError):
        scaling_factor(0, 100)


def test_pre_pick_minimax_known_optimum_and_release_constraints():
    groups = pd.DataFrame([dict(release=0, latest=3, count=80), dict(release=2, latest=3, count=40)])
    before = simulate(groups, 4, 0)
    after = simulate(groups, 4, 3)
    assert before.peak == pytest.approx(120, abs=1e-4)
    assert after.peak == pytest.approx(30, abs=1e-4)
    assert after.scheduled == pytest.approx(120, abs=1e-4)
    assert (after.allocations.hour >= after.allocations.release).all()
    assert (after.allocations.hour <= after.allocations.latest).all()
    assert (after.allocations.hour >= after.allocations.earliest).all()
    by_group = after.allocations.groupby("group")["count"].sum()
    assert np.allclose(by_group, [80, 40])


def test_cap_rejects_instead_of_overfilling_or_losing_volume():
    groups = pd.DataFrame([dict(release=0, latest=3, count=120)])
    result = simulate(groups, 4, 3, max_per_hour=20)
    assert result.hourly.max() <= 20 + 1e-7
    assert result.scheduled == pytest.approx(80, abs=1e-4)
    assert result.unscheduled == pytest.approx(40, abs=1e-4)
    assert not result.feasible
    assert simulate(groups, 4, 3, max_per_hour=0).unscheduled == 120


def test_scaling_simulation_and_window_monotonicity():
    _, _, data, hours = sample()
    plan = required_plan(data, hours)
    previous = float("inf")
    for lookback in [0, 1, 4, 12]:
        result = simulate(plan.groups, len(hours), lookback)
        assert result.peak <= previous + 1e-3
        assert result.scheduled == pytest.approx(plan.hourly.sum(), abs=1e-3)
        previous = result.peak
    a = simulate(plan.groups, len(hours), 4)
    b = simulate(plan.groups, len(hours), 4, factor=1.5)
    assert np.allclose(b.hourly, a.hourly * 1.5, atol=1e-3)


def test_exact_release_cutoff_safety_and_missing_deadline():
    start, end, _, hours = sample()
    rows = pd.DataFrame([
        dict(created_at=start, cutoff_at=start+pd.Timedelta(hours=3), picked_at=start+pd.Timedelta(hours=1)),
        dict(created_at=start+pd.Timedelta(minutes=1), cutoff_at=start+pd.Timedelta(hours=2), picked_at=pd.NaT),
        dict(created_at=start, cutoff_at=pd.NaT, picked_at=start+pd.Timedelta(hours=4)),
        dict(created_at=start, cutoff_at=pd.NaT, picked_at=pd.NaT),
    ]).assign(jobline_id=range(4))
    data, _, _ = prepare_data(rows, start, end, filter_location=False)
    plan = required_plan(data, hours, safety_hours=1)
    # first line occupies 07-08, second has no complete slot before 07:00.
    assert plan.hourly[1] == 1
    assert plan.hourly[4] == 1
    assert plan.fallback_count == 2
    assert plan.unscheduled["count"].sum() == 2
    assert plan.hourly.sum() + plan.unscheduled["count"].sum() == 4


def test_integer_boundary_release_can_use_the_same_slot():
    start, end, _, hours = sample()
    raw = pd.DataFrame([dict(jobline_id=1, created_at=start, cutoff_at=start+pd.Timedelta(hours=1), picked_at=pd.NaT)])
    data, _, _ = prepare_data(raw, start, end, filter_location=False)
    plan = required_plan(data, hours, safety_hours=0)
    assert plan.hourly[0] == 1
