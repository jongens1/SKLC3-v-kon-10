import json
from datetime import date
from pathlib import Path
import numpy as np
import pandas as pd
from src.data_processing import operational_window, prepare_data, hourly_metrics
from src.performance import required_plan
from src.prepicking import simulate
from src.utils import read_snapshot

ROOT = Path(__file__).resolve().parents[1]


def test_real_snapshot_totals_and_quality():
    meta = json.loads((ROOT / "data/snapshot_metadata.json").read_text(encoding="utf-8"))
    raw = read_snapshot(ROOT / "data" / meta["file"], meta)
    start, end = operational_window(date(2026, 10, 15))
    data, summary, _ = prepare_data(raw, start, end, filter_location=False)
    assert summary == meta["summary"]
    assert summary["rows"] == 276869
    assert summary["picked"] == 117283
    assert summary["missing_pick"] == 159586
    assert summary["cancelled"] == 6228
    assert summary["missing_cutoff"] == 38738
    hourly = hourly_metrics(data, start, end)
    assert hourly.created_count.sum() == summary["rows"]
    assert hourly.picked_count.sum() == 99061
    assert hourly.backlog.iloc[-1] == 177808
    assert not any("jobline_id" in str(c).lower() for c in raw.columns)


def test_real_plan_conservation_and_scaled_cap():
    meta = json.loads((ROOT / "data/snapshot_metadata.json").read_text(encoding="utf-8"))
    raw = read_snapshot(ROOT / "data" / meta["file"], meta)
    start, end = operational_window(date(2026, 10, 15))
    data, _, _ = prepare_data(raw, start, end, filter_location=False)
    hours = pd.date_range(start, end, freq="h", inclusive="left")
    plan = required_plan(data, hours, safety_hours=1)
    assert plan.hourly.sum() + plan.unscheduled["count"].sum() == 276869
    assert plan.hourly.max() == 67027
    result = simulate(plan.groups, 24, 4)
    assert abs(result.scheduled - plan.hourly.sum()) < 1e-3
    assert abs(result.peak - 24281.125) < 1e-2
    capped = simulate(plan.groups, 24, 4, factor=150000 / 276869, max_per_hour=10000)
    assert capped.hourly.max() <= 10000 + 1e-6
    assert np.isclose(capped.scheduled + capped.unscheduled,
                      plan.hourly.sum() * 150000 / 276869)


def test_snapshot_is_default_and_wrong_day_stops():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    assert not app.exception
    assert next(x for x in app.sidebar.selectbox if x.label == "Dátový zdroj").value.startswith("Overený")
    assert next(m for m in app.metric if m.label == "Reálny objem").value == "276,869"
    next(x for x in app.sidebar.date_input if x.label == "Logistický deň").set_value(date(2026, 10, 16)).run()
    assert not app.exception
    assert any("Lokálny snapshot pokrýva iba" in w.value for w in app.warning)
