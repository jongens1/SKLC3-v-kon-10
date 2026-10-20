from pathlib import Path
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def app():
    test = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90).run()
    next(x for x in test.sidebar.selectbox if x.label == "Dátový zdroj").set_value("DEMO · syntetické dáta").run()
    return test


def test_nine_sections_and_target_scaling():
    test = app()
    assert not test.exception, [e.value for e in test.exception]
    assert len(test.subheader) == 9
    assert next(m for m in test.metric if m.label == "Reálny objem").value == "124,000"
    next(x for x in test.sidebar.checkbox if x.label == "Manuálne zadať cieľový objem").check().run()
    next(x for x in test.sidebar.number_input if x.label == "Cieľový objem joblines").set_value(150000).run()
    assert not test.exception
    assert next(m for m in test.metric if m.label == "Cieľový objem").value == "150,000"


def test_day_granularity_and_168_hour_lookback():
    test = app()
    next(x for x in test.sidebar.selectbox if x.label == "Granularita created/picked grafov").set_value("day").run()
    next(x for x in test.sidebar.slider if x.label == "Pre-picking planning lookback (h)").set_value(168).run()
    assert not test.exception
    assert any("192 hodín" in text.value for text in test.markdown)


def test_insufficient_cap_and_zero_target():
    test = app()
    next(x for x in test.sidebar.checkbox if x.label == "Obmedziť maximálny hodinový výkon").check().run()
    next(x for x in test.sidebar.number_input if x.label.startswith("Maximálny výkon")).set_value(1).run()
    assert not test.exception
    assert any("nie je splniteľný" in e.value for e in test.error)
    next(x for x in test.sidebar.checkbox if x.label == "Manuálne zadať cieľový objem").check().run()
    next(x for x in test.sidebar.number_input if x.label == "Cieľový objem joblines").set_value(0).run()
    assert not test.exception
    assert next(m for m in test.metric if m.label == "Unmet / infeasible volume").value == "0.0"


def test_bigquery_error_does_not_crash(monkeypatch):
    import src.bigquery_client as adapter
    def unavailable(*a, **k):
        raise RuntimeError("No credentials")
    monkeypatch.setattr(adapter, "load_joblines", unavailable)
    test = app()
    next(x for x in test.sidebar.selectbox if x.label == "Dátový zdroj").set_value("BigQuery · iba čítanie").run()
    assert not test.exception
    assert any("BigQuery sa nepodarilo načítať" in e.value for e in test.error)
