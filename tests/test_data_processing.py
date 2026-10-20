from datetime import date, time
import pandas as pd
import pytest
from src.data_processing import operational_window, prepare_data, hourly_metrics, demo_data


def test_local_window_and_dst():
    start, end = operational_window(date(2026, 10, 15))
    assert start.isoformat() == "2026-10-15T06:00:00+02:00"
    assert len(pd.date_range(start, end, freq="h", inclusive="left")) == 24
    a, b = operational_window(date(2026, 10, 24))
    assert (b-a).total_seconds() / 3600 == 25
    a, b = operational_window(date(2026, 3, 28))
    assert (b-a).total_seconds() / 3600 == 23
    with pytest.raises(ValueError):
        operational_window(date(2026, 10, 15), time(6, 30))


def test_demo_conservation_scaling_cohort_and_later_picks():
    start, end = operational_window(date(2026, 10, 15))
    data, summary, _ = prepare_data(demo_data(date(2026, 10, 15)), start, end)
    hourly = hourly_metrics(data, start, end)
    assert summary["rows"] == summary["unique_joblines"] == 124000
    assert hourly.created_count.sum() == 124000
    assert summary["picked_after_window"] > 0
    assert hourly.picked_count.sum() + summary["picked_after_window"] == 124000
    assert hourly.backlog.iloc[-1] == summary["picked_after_window"]
    assert data.operational_hour.between(0, 23).all()


def test_branch_or_store_filter_and_exclusive_end():
    start, end = operational_window(date(2026, 10, 15))
    frame = pd.DataFrame(dict(jobline_id=range(5), created_at=[start, start, start, start, end],
                              branch_id=[6281, 5, 5, 5, 6281],
                              store_name=["X", "162 sklc3", "Y", "SKLC3 B2B", "X"]))
    data, summary, warnings = prepare_data(frame, start, end)
    assert summary["rows"] == 3
    assert set(data.jobline_id) == {0, 1, 3}
    assert any("cutoff" in warning for warning in warnings)


def test_invalid_ids_dates_and_counts_block():
    start, end = operational_window(date(2026, 10, 15))
    for frame in [pd.DataFrame(dict(jobline_id=[1, 1], created_at=[start, start])),
                  pd.DataFrame(dict(jobline_id=[1], created_at=["bad"])),
                  pd.DataFrame(dict(jobline_count=[-1], created_at=[start])),
                  pd.DataFrame(dict(jobline_count=[1], created_at=[start], invalid_id=[True]))]:
        with pytest.raises(ValueError):
            prepare_data(frame, start, end, filter_location=False)


def test_empty_data_does_not_crash():
    start, end = operational_window(date(2026, 10, 15))
    data, summary, _ = prepare_data(pd.DataFrame(columns=["created_at", "jobline_count", "store_id"]), start, end)
    assert summary["rows"] == 0
