from datetime import date, time
import pandas as pd
import pytest
from src.config import ALLOWED_JOB_TYPES
from src.data_processing import (operational_window, planning_window, prepare_data,
                                  event_timeline, planning_metrics, collection_distribution)
from src.demo_data import demo_data


def row(identifier=1, **changes):
    result = dict(jobline_id=identifier, created_at="2026-10-13T10:00:00+02:00",
                  picked_at="2026-10-14T18:00:00+02:00", collection_at="2026-10-15T10:00:00+02:00",
                  branch_id="6281", store_id="10686", job_type=ALLOWED_JOB_TYPES[0])
    result.update(changes)
    return result


def prepare(rows):
    start, end = operational_window(date(2026, 10, 15))
    return prepare_data(pd.DataFrame(rows), start, end)


def test_collection_day_includes_older_created():
    data, summary, _ = prepare([row()])
    assert summary["rows"] == 1
    assert data.created_at.iloc[0].day == 13
    assert data.operational_hour.iloc[0] == 4


def test_created_in_day_does_not_include_outside_collection():
    data, summary, _ = prepare([row(created_at="2026-10-15T07:00:00+02:00",
                                       collection_at="2026-10-16T06:00:00+02:00")])
    assert data.empty and summary["rows"] == 0


def test_only_allowed_job_types_pass():
    records = [row(i, job_type=kind) for i, kind in enumerate([*ALLOWED_JOB_TYPES, "Príjem", "Expedícia - Balíkový"])]
    data, summary, _ = prepare(records)
    assert summary["rows"] == 3
    assert set(data.job_type) == set(ALLOWED_JOB_TYPES)


def test_location_is_branch_or_name_pattern():
    data, summary, _ = prepare([row(1, branch_id="5", store_id="162 SKLC3"),
                                row(2), row(3, branch_id="5", store_id="other")])
    assert set(data.jobline_id) == {1, 2}


def test_complete_event_history_is_independent_of_planning_window():
    data, _, _ = prepare([row(), row(2, created_at="2026-10-14T12:00:00+02:00")])
    timeline = event_timeline(data, "created_at")
    daily = event_timeline(data, "created_at", "day")
    assert timeline.hour.min().day == 13
    assert timeline.hour.max().day == 14
    assert timeline["count"].sum() == daily["count"].sum() == 2


def test_planning_window_includes_carry_in_and_extends_globally():
    data, _, _ = prepare([row()])
    start, end = operational_window(date(2026, 10, 15))
    hours = planning_window(start, end, 24)
    assert len(hours) == 48
    assert hours[0] == start - pd.Timedelta(hours=24)
    metrics = planning_metrics(data, hours)
    assert metrics.available_count.iloc[0] == 1
    assert metrics.initial_created.iloc[0] == 1
    assert metrics.cumulative_created.iloc[-1] == 1
    assert metrics.cumulative_picked.iloc[-1] == 1


def test_dst_and_lookback_bounds():
    for day, expected in [(date(2026, 10, 24), 25), (date(2026, 3, 28), 23)]:
        start, end = operational_window(day)
        assert len(planning_window(start, end, 24)) == expected + 24
    start, end = operational_window(date(2026, 10, 15))
    assert len(planning_window(start, end, 168)) == 192
    with pytest.raises(ValueError):
        planning_window(start, end, 169)
    with pytest.raises(ValueError):
        operational_window(date(2026, 10, 15), time(6, 30))


def test_missing_created_is_retained_and_reported():
    data, summary, notices = prepare([row(created_at=None, picked_at=None)])
    assert summary["rows"] == summary["missing_created"] == summary["missing_pick"] == 1
    assert notices


def test_bad_counts_ids_and_dates_are_rejected():
    for rows in [[row(), row()], [row(created_at="invalid")],
                 [dict(row(), jobline_count=-1)], [dict(row(), jobline_count=1, invalid_id=True)]]:
        with pytest.raises(ValueError):
            prepare(rows)


def test_empty_source_is_supported():
    start, end = operational_window(date(2026, 10, 15))
    _, summary, _ = prepare_data(pd.DataFrame(), start, end)
    assert summary["rows"] == 0


def test_demo_collection_and_history_contract():
    start, end = operational_window(date(2026, 10, 15))
    raw = demo_data(date(2026, 10, 15))
    data, summary, _ = prepare_data(raw, start, end)
    assert summary["rows"] == 124000
    assert data.collection_at.between(start, end, inclusive="left").all()
    assert (data.created_at < start - pd.Timedelta(hours=24)).any()
    assert ((data.collection_at - data.created_at) <= pd.Timedelta(hours=72)).all()
    assert (data.picked_at >= data.created_at).all()
    assert (data.picked_at <= data.collection_at).all()
    assert collection_distribution(data, start, end)["count"].sum() == 124000


def test_half_hour_zone_and_repeated_dst_buckets():
    from src.data_processing import floor_hour, parse_timestamps
    values = parse_timestamps(pd.Series(["2026-10-15T06:10:00+05:30"]), "Asia/Kolkata")
    assert floor_hour(values).iloc[0].isoformat() == "2026-10-15T06:00:00+05:30"
    repeated = parse_timestamps(pd.Series(["2026-10-25T02:30:00+02:00", "2026-10-25T02:30:00+01:00"]))
    assert floor_hour(repeated).nunique() == 2
