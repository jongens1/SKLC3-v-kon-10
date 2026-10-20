from pathlib import Path
import socket
import pandas as pd
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
    assert next(x for x in test.sidebar.checkbox if x.label=="Uplatniť limit v krivkách").value is True


def test_target_changes_without_changing_measured_picks():
    test = app()
    next(x for x in test.sidebar.number_input if x.label=="Cieľový objem joblines").set_value(250000).run()
    assert not test.exception
    assert next(x for x in test.metric if x.label=="Cieľový objem").value == "250 000"
    assert next(x for x in test.metric if x.label=="Vstupný buffer o 06:00").value == "115 405"
    assert next(x for x in test.metric if x.label=="Skutočne vypickované v dni").value == "114 649"
    assert next(x for x in test.metric if x.label=="Vypickované · aktuálny výkon").value == "114 649"
    assert next(x for x in test.metric if x.label=="Buffer · aktuálny výkon").value == "135 349"
    next(x for x in test.select_slider if x.label=="Stav k času").set_value(pd.Timestamp("2026-10-15T06:00:00+02:00")).run()
    assert not test.exception
    assert next(x for x in test.metric if x.label=="Vzniknuté joblines").value == "115 405"
    assert next(x for x in test.metric if x.label=="Vypickované · aktuálny výkon").value == "0"


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


def test_requested_270000_15000_scenario_and_all_views():
    test = app()
    next(x for x in test.sidebar.number_input if x.label=="Limit skladu (jl/h)").set_value(15000).run()
    next(x for x in test.sidebar.number_input if x.label=="Cieľový objem joblines").set_value(270000).run()
    assert not test.exception
    expected = {"Vstupný buffer o 06:00":"124 638","Vzniknuté joblines":"269 998",
                "Vypickované · vyrovnaný pick":"269 998","Vypickované · aktuálny výkon":"114 649",
                "Buffer · vyrovnaný pick":"0","Buffer · aktuálny výkon":"155 349",
                "Nesplnené v termíne pri limite":"80 181","Nad limitom · pôvodný výkon":"0 h",
                "Nad limitom · vyrovnaný pick":"0 h"}
    for label,value in expected.items():
        assert next(x for x in test.metric if x.label==label).value == value
    assert any("2.23" in caption.value for caption in test.caption)
    for view in ["Buffer a vznik","Svozy","Dáta a export","Výkon a plán"]:
        test.radio[0].set_value(view).run()
        assert not test.exception


def test_changing_model_source_invalidates_warm_streamlit_cache(monkeypatch):
    import streamlit as st
    import src.dashboard as dashboard
    st.cache_data.clear()
    analyze = dashboard.analyze
    calls = []
    def counted(*args,**kwargs):
        calls.append(1)
        return analyze(*args,**kwargs)
    monkeypatch.setattr(dashboard,"analyze",counted)
    test = app()
    assert not test.exception
    assert len(calls) == 1
    test.run()
    assert len(calls) == 1
    read_bytes = Path.read_bytes
    def changed_source(path):
        content = read_bytes(path)
        return content+b"\n# model revision\n" if path.name=="prepicking.py" else content
    monkeypatch.setattr(Path,"read_bytes",changed_source)
    test.run()
    assert not test.exception
    assert len(calls) == 2
    st.cache_data.clear()
