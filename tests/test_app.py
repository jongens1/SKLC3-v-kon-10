from pathlib import Path
import socket
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def app():
    return AppTest.from_file(str(ROOT/"app.py"),default_timeout=90).run()


def test_default_is_real_snapshot_and_runs_without_network(monkeypatch):
    def offline(*args,**kwargs):raise AssertionError("No network allowed")
    monkeypatch.setattr(socket,"create_connection",offline)
    test = app()
    assert not test.exception,[e.value for e in test.exception]
    assert next(x for x in test.sidebar.selectbox if x.label=="Dátový zdroj").value == "Pripravené dáta z BigQuery"
    assert next(x for x in test.metric if x.label=="Joblines pre svozy dňa").value == "121 290"
    assert next(x for x in test.metric if x.label=="Vstupný buffer o 06:00").value == "55 990"
    assert next(x for x in test.metric if x.label=="Skutočne vypickované v dni").value == "114 649"
    assert not any("DEMO" in w.value for w in test.warning)


def test_target_changes_without_changing_measured_picks():
    test = app()
    next(x for x in test.sidebar.number_input if x.label=="Cieľový objem joblines").set_value(250000).run()
    assert not test.exception
    assert next(x for x in test.metric if x.label=="Cieľový objem").value == "250 000"
    assert next(x for x in test.metric if x.label=="Vstupný buffer o 06:00").value == "115 405"
    assert next(x for x in test.metric if x.label=="Skutočne vypickované v dni").value == "114 649"


def test_all_four_views_and_exports():
    test = app()
    for view in ["Buffer a vznik","Svozy","Dáta a export","Výkon a plán"]:
        test.radio[0].set_value(view).run()
        assert not test.exception,(view,[e.value for e in test.exception])


def test_zero_target_and_cap_and_demo_are_explicit():
    test = app()
    next(x for x in test.sidebar.checkbox if x.label=="Uplatniť limit v krivkách").check().run()
    next(x for x in test.sidebar.number_input if x.label=="Limit skladu (jl/h)").set_value(1).run()
    assert not test.exception
    assert any("nedá naplánovať" in w.value for w in test.warning)
    next(x for x in test.sidebar.number_input if x.label=="Cieľový objem joblines").set_value(0).run()
    assert not test.exception
    assert next(x for x in test.metric if x.label=="Nesplnené v termíne pri limite").value == "0"
    next(x for x in test.sidebar.selectbox if x.label=="Dátový zdroj").set_value("DEMO · syntetické dáta").run()
    assert not test.exception
    assert any("DEMO" in w.value for w in test.warning)
