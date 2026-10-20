from pathlib import Path
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def demo_app():
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    if not app.exception:
        source = next(x for x in app.sidebar.selectbox if x.label == "Dátový zdroj")
        source.set_value("DEMO · syntetické dáta").run()
    return app


def test_demo_sections_and_target_scaling():
    app = demo_app()
    assert not app.exception, [e.value for e in app.exception]
    assert len(app.subheader) == 8
    next(x for x in app.sidebar.checkbox if x.label == "Manuálne zadať cieľový objem").check().run()
    next(x for x in app.sidebar.number_input if x.label == "Cieľový objem joblines").set_value(150000).run()
    assert not app.exception
    assert next(m for m in app.metric if m.label == "Cieľový objem").value == "150,000"


def test_zero_target_and_insufficient_cap():
    app = demo_app()
    next(x for x in app.sidebar.checkbox if x.label == "Obmedziť maximálny hodinový výkon").check().run()
    next(x for x in app.sidebar.number_input if x.label.startswith("Maximálny výkon")).set_value(1).run()
    assert not app.exception
    assert any("nie je splniteľný" in e.value for e in app.error)
    next(x for x in app.sidebar.checkbox if x.label == "Manuálne zadať cieľový objem").check().run()
    next(x for x in app.sidebar.number_input if x.label == "Cieľový objem joblines").set_value(0).run()
    assert not app.exception


def test_bigquery_missing_credentials_is_handled(monkeypatch):
    import src.bigquery_client
    def unavailable(*args, **kwargs):
        raise RuntimeError("Unavailable")
    monkeypatch.setattr(src.bigquery_client, "load_joblines", unavailable)
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    next(x for x in app.sidebar.selectbox if x.label == "Dátový zdroj").set_value("BigQuery · iba čítanie").run()
    assert not app.exception
    assert any("Dáta sa nepodarilo načítať" in e.value for e in app.error)
