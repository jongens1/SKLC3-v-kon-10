"""Offline SKLC3 dashboard: verified bundled aggregates, no runtime BigQuery calls."""
from __future__ import annotations
from datetime import date, time
import json
import pandas as pd
import streamlit as st

from src.config import ALLOWED_JOB_TYPES, ZONE
from src.data_processing import collection_distribution, event_timeline, operational_window, prepare_data
from src.dashboard import analyze, rescale
from src.demo_data import demo_data
from src.plots import arrivals_chart, collection_chart, performance_chart, lines
from src.snapshot import load_snapshot, manifest
from src.utils import csv_bytes

st.set_page_config(page_title="SKLC3 · Výkon a plán",page_icon="📦",layout="wide")
st.markdown("""<style>
.block-container{padding-top:2rem;max-width:1520px}
h1{font-size:2.15rem!important;letter-spacing:-.05rem;margin-bottom:0!important}
h2,h3{letter-spacing:-.02rem}
[data-testid="stMetric"]{background:linear-gradient(140deg,#12243b,#0d192a);border:1px solid #203c59;border-radius:14px;padding:16px 18px}
[data-testid="stMetricValue"]{font-size:1.9rem;color:#e9f5ff}
[data-testid="stMetricLabel"]{color:#9db7d5}
[data-testid="stSidebar"]{border-right:1px solid #18304a}
div[data-testid="stRadio"]>div{gap:1.2rem}
</style>""",unsafe_allow_html=True)
st.title("Výkon skladu SKLC3")


def fmt(value: float) -> str:
    return f"{value:,.0f}".replace(","," ")


@st.cache_data(show_spinner="Načítavam pripravené dáta…")
def bundled(day: str, fingerprint: str):
    return load_snapshot(day)


@st.cache_data(max_entries=16,show_spinner=False)
def prepared(raw,start,end,types):
    return prepare_data(raw,start,end,types)


@st.cache_data(max_entries=16,show_spinner="Počítam základný plán…")
def base_report(data,start,end,lookback,safety,throughput):
    return analyze(data,start,end,float(data.jobline_count.sum()),lookback,safety,None,throughput)


with st.sidebar:
    st.header("SKLC3")
    source = st.selectbox("Dátový zdroj",["Pripravené dáta z BigQuery","DEMO · syntetické dáta"])
    day = st.date_input("Logistický deň",date(2026,10,15))
    st.caption("06:00 → 06:00 nasledujúceho dňa · Bratislava")
    with st.expander("Možnosti plánovania"):
        lookback = st.slider("Predpickovanie pred začiatkom dňa (h)",0,168,24)
        safety = st.number_input("Predstih pred svozom (h)",min_value=0.0,max_value=168.0,value=1.0,step=.5)
        use_cap = st.checkbox("Zadať limit výkonu",False)
        cap = st.number_input("Limit skladu (jl/h)",min_value=0.0,value=10000.0,step=500.0) if use_cap else None
        selected_types = st.multiselect("Procesy",list(ALLOWED_JOB_TYPES),default=list(ALLOWED_JOB_TYPES))

start,end = operational_window(day,time(6),ZONE)
is_demo = source.startswith("DEMO")
try:
    if is_demo:
        raw = demo_data(day)
        metadata = {"prepared_at":"syntetické", "source":"DEMO"}
        # Demo observes only its synthetic cohort; it is never labelled as measured data.
        full_demo,_,_ = prepare_data(raw,start,end)
        observed = full_demo.loc[(full_demo.picked_at>=start)&(full_demo.picked_at<end)].copy()
        observed["hour"] = observed.picked_at.dt.floor("h")
        throughput = observed.groupby(["hour","job_type"],as_index=False).jobline_count.sum().rename(columns={"jobline_count":"picked_count"})
    else:
        fingerprint = json.dumps(manifest()["days"][day.isoformat()],sort_keys=True)
        raw,throughput,metadata = bundled(day.isoformat(),fingerprint)
except KeyError:
    st.info("Pre tento deň zatiaľ nemáme pripravené dáta. Dostupný je 15. 10. 2026; prípadne vyber DEMO.")
    st.stop()
except Exception as exc:
    st.error(f"Pripravený dataset sa nepodarilo načítať: {type(exc).__name__}.")
    st.stop()
try:
    data,summary,notices = prepared(raw,start,end,tuple(selected_types))
except ValueError as exc:
    st.error(str(exc));st.stop()
if not summary["rows"]:
    st.info("Vyber aspoň jeden proces s dostupnými dátami.");st.stop()
throughput = throughput.loc[throughput.job_type.isin(selected_types)].copy()
actual = summary["rows"]
with st.sidebar:
    target = st.number_input("Cieľový objem joblines",min_value=0,value=actual,step=1000,
                             key=f"target_{source}_{day}_{actual}")
    st.caption(f"Základ: {fmt(actual)} joblines pre svozy dňa")
report = rescale(base_report(data,start,end,int(lookback),safety,throughput),target,cap)
day_frame = report.day
factor = report.factor
collections = collection_distribution(data,start,end)
collections["count_scaled"] = collections["count"]*factor

st.caption(f"{start:%d.%m.%Y} · 06:00 – 06:00 · " + ("DEMO" if is_demo else f"Overený snapshot z {metadata['prepared_at']}"))
if is_demo:
    st.warning("DEMO · syntetická ukážka nočného profilu. Pre skutočný výkon zvoľ Pripravené dáta z BigQuery.")
else:
    st.caption("● Pripravené reálne dáta · aplikácia sa nepripája do BigQuery")
cols = st.columns(4)
for col,label,value in zip(cols,["Joblines pre svozy dňa","Cieľový objem","Vstupný buffer o 06:00","Skutočne vypickované v dni"],
                           [actual,target,report.initial_buffer,day_frame.warehouse_picked.sum()]):
    col.metric(label,fmt(value))
st.caption(f"Prepočet cieľa: ×{factor:.4f} · "
           f"Pred dňom vzniklo {fmt(report.created_before_day)}, už vypickovaných bolo {fmt(report.picked_before_day)}. "
           f"Vstupný buffer obsahuje iba zostávajúcich {fmt(report.initial_buffer)} joblines.")
view = st.radio("Pohľad",["Výkon a plán","Buffer a vznik","Svozy","Dáta a export"],horizontal=True,label_visibility="collapsed")

if view == "Výkon a plán":
    st.subheader("Aký výkon sklad mal a aký potrebuje")
    st.plotly_chart(performance_chart(day_frame),width="stretch",key="main_performance")
    st.caption("Modrá: všetky povolené joblines vypickované skladom v tomto dni, aj pre iné svozy. "
               "Zelená: vyrovnaný plán pre zvolený cieľový objem svozov. Výkon pre konkrétne svozy je v detaile nižšie.")
    peak = day_frame.loc[day_frame.warehouse_picked.idxmax()]
    cols = st.columns(3)
    cols[0].metric("Špička skutočného výkonu",f"{fmt(peak.warehouse_picked)} jl/h",help=f"{peak.hour:%d. %m. %H:%M} – {(peak.hour+pd.Timedelta(hours=1)):%H:%M}")
    cols[1].metric("Potrebná špička v celom pláne",f"{fmt(report.simulation.peak)} jl/h")
    cols[2].metric("Nenaplánovateľný objem",fmt(report.unmet))
    st.caption(f"Najsilnejšia skutočná hodina: {peak.hour:%d. %m. %H:%M}–{(peak.hour+pd.Timedelta(hours=1)):%H:%M}. "
               f"Plán môže začať {report.planning.hour.iloc[0]:%d. %m. %H:%M}; už dokončenú prácu znovu neplánuje.")
    if report.unmet > max(1e-4,target*1e-9):
        st.warning(f"{fmt(report.unmet)} cieľových joblines sa pri týchto časoch alebo limite nedá naplánovať. Podrobnosti sú v Dáta a export.")
    else:
        st.success("Cieľový objem sa zmestí do dostupných hodín pri zadaných pravidlách.")
    with st.expander("Výkon pre tieto svozy a prepočet histórie"):
        st.plotly_chart(lines(day_frame,["picked_count","picked_scaled","prepick_smoothed_scaled"],
                             ["Skutočne pre tieto svozy","Historický profil × koeficient","Potrebný cieľový výkon"]),width="stretch")
    with st.expander("Kumulatívne splnenie svozov"):
        st.plotly_chart(lines(day_frame,["cumulative_actual","cumulative_required_scaled","cumulative_simulated"],
                             ["Vypickované pre tieto svozy","Splatný cieľový objem","Naplánovaný cieľový objem"]),width="stretch")
    with st.expander("Predpickovanie a celé plánovacie okno"):
        st.plotly_chart(lines(report.planning,["prepick_smoothed_scaled","required_pick_scaled"],
                             ["Vyrovnaný cieľový výkon","Objem splatný pred cutoffom"]),width="stretch")
        st.caption("Predpickovanie rešpektuje vznik práce, začiatok plánovacieho okna a cutoff mínus predstih. Využíva iba celé hodinové sloty.")

elif view == "Buffer a vznik":
    st.subheader("Vstupný buffer a nová práca")
    st.caption("Všetka nevypickovaná práca vzniknutá pred 06:00 je v jednom vstupnom buffri. Staršie dátumy nepredlžujú hlavnú časovú os.")
    st.plotly_chart(arrivals_chart(day_frame,report.initial_buffer,factor),width="stretch")
    st.subheader("Koľko práce zostávalo")
    st.plotly_chart(lines(day_frame,["backlog","backlog_scaled","scenario_backlog"],
                         ["Skutočný buffer","Historický buffer × koeficient","Buffer podľa nového plánu"]),width="stretch")
    st.caption("Skutočný buffer = vstupný buffer + vzniky dňa − pickovanie pre tieto svozy. Nový plán môže mať vďaka predpickovaniu iný stav o 06:00.")
    with st.expander("Úplná história vzniku a pickovania"):
        granularity = st.selectbox("Podrobnosť histórie",["hour","day"])
        for column,title in [("created_at","Vzniky"),("picked_at","Pickovanie")]:
            history = event_timeline(data,column,granularity)
            history["count_scaled"] = history["count"]*factor
            st.plotly_chart(lines(history,["count","count_scaled"],["Skutočný objem","Cieľový objem"],title),width="stretch",key=column)

elif view == "Svozy":
    st.subheader("Čo musí byť pripravené na svozy")
    scaled = st.radio("Zobrazený objem",["Reálny","Cieľový"],horizontal=True) == "Cieľový"
    st.plotly_chart(collection_chart(collections,scaled),width="stretch")
    by_type = data.groupby("job_type").jobline_count.sum().sort_values(ascending=False)
    cols = st.columns(len(by_type))
    for col,(kind,count) in zip(cols,by_type.items()):
        col.metric(kind,fmt(count*(factor if scaled else 1)),f"{count/actual:.1%} objemu")
    st.caption("Podiely pochádzajú zo zvoleného datasetu. Zmena cieľového objemu zachováva procesný mix.")

else:
    st.subheader("Dáta a export")
    with st.expander("Kvalita, filtre a pôvod dát"):
        for notice in notices:st.warning(notice)
        st.json(summary)
        st.json(metadata)
        st.caption("Chýbajúce pickovanie samo osebe neznamená otvorenú fyzickú prácu. Storná sú ponechané a vykázané. Časové odhady používajú celé hodiny.")
    if report.structural_unmet:
        st.dataframe(report.plan.unscheduled.rename(columns={"reason":"Dôvod","count":"Joblines"}),hide_index=True)
    st.dataframe(day_frame,hide_index=True)
    types = data.groupby("job_type",as_index=False).jobline_count.sum()
    scenario = pd.DataFrame([dict(day=str(day),real_volume=actual,target_volume=target,scaling_factor=factor,
                                 initial_buffer=report.initial_buffer,initial_buffer_scaled=report.initial_buffer*factor,
                                 already_completed_before_planning=report.completed_before_planning,
                                 safety_hours=safety,lookback_hours=lookback,cap=cap,unmet=report.unmet,source=source)])
    audit = report.simulation.allocations.copy()
    if len(audit):
        times = pd.DatetimeIndex(report.planning.hour)
        audit["slot_start"] = times[audit.hour.to_numpy(dtype=int)]
        audit["slot_end"] = audit.slot_start+pd.Timedelta(hours=1)
    exports = [(day_frame,"Hodinový prehľad","hourly"),(report.planning,"Celé plánovacie okno","planning"),
               (collections,"Svozy","collections"),(throughput,"Skutočný výkon skladu","actual_picking"),
               (types,"Typy procesov","types"),(scenario,"Nastavenia a výsledok","scenario"),
               (audit,"Audit plánovania","audit")]
    cols = st.columns(3)
    for i,(frame,label,name) in enumerate(exports):
        cols[i%3].download_button(label+" CSV",csv_bytes(frame),f"sklc3_{name}.csv","text/csv")
