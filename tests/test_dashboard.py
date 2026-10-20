from datetime import date
import numpy as np
import pandas as pd
import pytest
from src.config import ALLOWED_JOB_TYPES
from src.dashboard import analyze,rescale
from src.data_processing import operational_window,prepare_data
from src.demo_data import demo_data
from src.snapshot import load_snapshot
from src.plots import performance_chart,arrivals_chart,inventory_chart


def real_data():
    raw,throughput,_ = load_snapshot("2026-10-15")
    start,end = operational_window(date(2026,10,15))
    data,summary,_ = prepare_data(raw,start,end)
    return data,throughput,summary,start,end


def test_real_process_mix_is_not_demo_and_expedition_dominates():
    data,_,summary,_,_ = real_data()
    counts = data.groupby("job_type").jobline_count.sum()
    assert counts.to_dict() == {"Distribúcia - LC":3013,"Distribúcia - POB":1272,"Expedícia - Standard":117005}
    assert summary["rows"] == 121290
    assert counts[ALLOWED_JOB_TYPES[0]]/summary["rows"] > .96


def test_actual_throughput_and_night_peak_are_measured_separately():
    data,throughput,_,start,end = real_data()
    report = analyze(data,start,end,121290,throughput=throughput)
    assert report.day.warehouse_picked.sum() == 114649
    assert report.day.picked_count.sum() == 75837
    peak = report.day.loc[report.day.warehouse_picked.idxmax()]
    assert peak.hour == pd.Timestamp("2026-10-16T01:00:00+02:00")
    assert peak.warehouse_picked == 10079


def test_initial_buffer_ignores_historical_picks_and_is_one_bucket():
    data,throughput,_,start,end = real_data()
    report = analyze(data,start,end,121290,throughput=throughput)
    assert report.created_before_day == 55990
    assert report.picked_before_day == 44421
    assert report.initial_buffer == 55990
    chart = arrivals_chart(report.day,report.initial_buffer,1)
    assert chart.data[0].x[0] == "Vstupný buffer"
    assert chart.data[0].y[0] == 55990
    assert len(chart.data[0].x) == 25


def test_every_created_job_is_planned_again_and_scale_conserves_volume():
    data,throughput,_,start,end = real_data()
    report = analyze(data,start,end,250000,throughput=throughput)
    unavailable = report.total_volume*report.factor-report.simulation.scheduled-report.simulation.unscheduled
    assert unavailable == pytest.approx(report.factor,abs=.001)  # One job arrives outside the day.
    assert report.completed_before_planning == 0
    assert report.factor == pytest.approx(250000/121290)
    assert np.allclose(report.day.created_scaled,report.day.created_count*report.factor)
    assert np.allclose(report.day.picked_scaled,report.day.picked_count*report.factor)
    assert np.allclose(report.day.backlog_scaled,report.day.backlog*report.factor)
    assert report.day.scenario_backlog.min() >= -.001


def test_comparison_uses_same_target_and_availability_for_both_scenarios():
    data,throughput,_,start,end = real_data()
    a = analyze(data,start,end,121290,throughput=throughput)
    b = analyze(data,start,end,250000,throughput=throughput)
    fig = performance_chart(b.day)
    assert fig.data[0].name == "Nové vzniky"
    assert np.allclose(fig.data[1].y,b.day.current_pick)
    assert np.allclose(fig.data[2].y,b.day.balanced_required)
    assert np.allclose(b.day.current_requested, a.day.current_requested*b.factor)
    assert fig.layout.yaxis.rangemode == "tozero"


def test_demo_is_unequal_but_remains_synthetic():
    raw = demo_data(date(2026,10,15))
    counts = raw.groupby("job_type").jobline_count.sum()
    assert counts.sum() == 124000
    assert counts[ALLOWED_JOB_TYPES[0]] > .96*124000


def test_instant_rescale_matches_fresh_target_and_keeps_measured_performance():
    data,throughput,_,start,end = real_data()
    base = analyze(data,start,end,121290,throughput=throughput)
    quick = rescale(base,250000)
    fresh = analyze(data,start,end,250000,throughput=throughput)
    for column in ["prepick_smoothed_scaled","cumulative_required_scaled","scenario_backlog","backlog_scaled"]:
        assert np.allclose(quick.day[column],fresh.day[column],atol=.001)
    assert np.allclose(quick.day.warehouse_picked,base.day.warehouse_picked)
    assert quick.unmet == pytest.approx(fresh.unmet)


@pytest.mark.parametrize("target,cap",[(250000,None),(250000,5000),(0,0),(121290,0)])
def test_both_scenarios_never_exceed_created_or_available_and_buffer_balances(target,cap):
    data,throughput,_,start,end = real_data()
    report = analyze(data,start,end,target,cap=cap,throughput=throughput)
    frame = report.day
    for pick,backlog in [("current_pick","current_backlog"),("current_limited","current_limited_backlog"),
                         ("balanced_required","balanced_required_backlog"),("prepick_smoothed_scaled","scenario_backlog")]:
        assert (frame[pick].cumsum() <= frame.cumulative_available_scaled+.001).all()
        assert (frame[pick].cumsum() <= frame.cumulative_created_scaled+.001).all()
        assert np.allclose(frame[backlog],frame.cumulative_created_scaled-frame[pick].cumsum())
        assert frame[backlog].min() >= -.001
    if cap is not None:
        assert frame.current_limited.max() <= cap+.001
        assert frame.prepick_smoothed_scaled.max() <= cap+.001
    chart = inventory_chart(frame,report.initial_buffer*report.factor,cumulative=True)
    assert chart.data[0].y[0] == pytest.approx(report.initial_buffer*report.factor)
    assert chart.data[1].y[0] == chart.data[2].y[0] == 0
    assert chart.data[0].x[0] == start
    assert chart.data[0].x[-1] == end


def test_historical_prepicking_cannot_change_either_scenario():
    data,throughput,_,start,end = real_data()
    before = analyze(data,start,end,121290,throughput=throughput)
    changed = data.copy()
    changed["picked_at"] = data.picked_at.mask(pd.Series(True,index=data.index))
    after = analyze(changed,start,end,121290,throughput=throughput)
    for col in ["current_pick","balanced_required","current_backlog","balanced_required_backlog"]:
        assert np.allclose(before.day[col],after.day[col])
    assert before.initial_buffer == after.initial_buffer == 55990


def test_late_jobs_stay_in_queue_and_no_arbitrary_empty_hours_remain():
    data,throughput,_,start,end = real_data()
    report = analyze(data,start,end,121290,throughput=throughput)
    assert report.structural_unmet > 30000  # No credit for historical prepicking.
    assert report.day.balanced_required.min() > 5000
    assert report.day.balanced_required.max()-report.day.balanced_required.min() < .01
    assert report.day.balanced_required_backlog.iloc[-1] == pytest.approx(0,abs=.001)
    late = report.plan.groups.index[~report.plan.groups.on_time]
    assert report.simulation.allocations.loc[report.simulation.allocations.group.isin(late),"count"].sum() > 30000
    for row in report.simulation.allocations.itertuples():
        assert row.release <= row.hour <= row.latest
