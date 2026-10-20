from datetime import date
import numpy as np
import pandas as pd
import pytest
from src.config import ALLOWED_JOB_TYPES
from src.dashboard import analyze,rescale
from src.data_processing import operational_window,prepare_data
from src.demo_data import demo_data
from src.snapshot import load_snapshot
from src.plots import performance_chart,arrivals_chart


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


def test_initial_buffer_subtracts_already_picked_and_is_one_bucket():
    data,throughput,_,start,end = real_data()
    report = analyze(data,start,end,121290,throughput=throughput)
    assert report.created_before_day == 55990
    assert report.picked_before_day == 44421
    assert report.initial_buffer == 11569
    chart = arrivals_chart(report.day,report.initial_buffer,1)
    assert chart.data[0].x[0] == "Vstupný buffer"
    assert chart.data[0].y[0] == 11569
    assert len(chart.data[0].x) == 25


def test_completed_work_is_not_scheduled_again_and_scale_conserves_volume():
    data,throughput,_,start,end = real_data()
    report = analyze(data,start,end,250000,throughput=throughput)
    assert report.simulation.scheduled + report.unmet + report.completed_before_planning*report.factor == pytest.approx(250000,abs=.001)
    assert report.factor == pytest.approx(250000/121290)
    assert np.allclose(report.day.created_scaled,report.day.created_count*report.factor)
    assert np.allclose(report.day.picked_scaled,report.day.picked_count*report.factor)
    assert np.allclose(report.day.backlog_scaled,report.day.backlog*report.factor)
    assert report.day.scenario_backlog.min() >= -.001


def test_comparison_uses_actual_unscaled_and_true_planned_curve():
    data,throughput,_,start,end = real_data()
    a = analyze(data,start,end,121290,throughput=throughput)
    b = analyze(data,start,end,250000,throughput=throughput)
    fig = performance_chart(b.day)
    assert fig.data[0].name == "Skutočný výkon skladu"
    assert np.allclose(fig.data[0].y,a.day.warehouse_picked)
    assert np.allclose(fig.data[1].y,b.day.prepick_smoothed_scaled)
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
    assert quick.simulation.scheduled+quick.unmet+quick.completed_before_planning*quick.factor == pytest.approx(250000,abs=.001)
