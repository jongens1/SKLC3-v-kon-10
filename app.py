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
from src.plots import arrivals_chart, collection_chart, performance_chart, inventory_chart, lines
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
    return f"{round(value):,}".replace(","," ")


@st.cache_data(show_spinner="Načítavam pripravené dáta…")
def bundled(day: str, fingerprint: str):
    return load_snapshot(day)


@st.cache_data(max_entries=16,show_spinner=False)
def prepared(raw,start,end,types):
    return prepare_data(raw,start,end,types)


@st.cache_data(max_entries=16,show_spinner="Počítam základný plán…")
def base_report(data,start,end,safety,throughput):
    return analyze(data,start,end,float(data.jobline_count.sum()),0,safety,None,throughput)


@st.cache_data(max_entries=32,show_spinner="Prepočítavam limit a buffer…")
def scenario_report(base,target,cap):
    return rescale(base,target,cap)


with st.sidebar:
    st.header("SKLC3")
    source = st.selectbox("Dátový zdroj",["Pripravené dáta z BigQuery","DEMO · syntetické dáta"])
    day = st.date_input("Logistický deň",date(2026,10,15))
    st.caption("06:00 → 06:00 nasledujúceho dňa · Bratislava")
    cap = st.number_input("Limit skladu (jl/h)",min_value=0.0,value=10000.0,step=500.0)
    limited = st.checkbox("Uplatniť limit v krivkách",False,
                          help="Vypnuté: potrebné výkony a prekročenia limitu. Zapnuté: realizovateľný pick a buffer pri dodržaní limitu.")
    with st.expander("Možnosti plánovania"):
        safety = st.number_input("Predstih pred svozom (h)",min_value=0.0,max_value=168.0,value=1.0,step=.5)
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
report = scenario_report(base_report(data,start,end,safety,throughput),target,cap)
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
                           [actual,target,report.initial_buffer*factor,day_frame.warehouse_picked.sum()]):
    col.metric(label,fmt(value))
st.caption(f"Scenár bez predpickovania · O 06:00 čaká všetkých {fmt(report.initial_buffer*factor)} dovtedy vzniknutých joblines. "
           f"Historický pick pred začiatkom dňa sa ignoruje. Cieľový objem aj vzniky sú prepočítané ×{factor:.4f}.")
view = st.radio("Pohľad",["Výkon a plán","Buffer a vznik","Svozy","Dáta a export"],horizontal=True,label_visibility="collapsed")

if view in ["Výkon a plán","Buffer a vznik"]:
    st.subheader("Vzniky a pickovanie v rovnakom scenári")
    st.caption("Modrá zachováva hodinový profil nameraného výkonu skladu, prepočítaný na cieľový objem. "
               "Zelená vyrovnáva výkon pri rešpektovaní vzniku a splniteľných svozových termínov. Obe začínajú s rovnakým plným buffrom.")
    if limited:
        st.info("Krivky dodržiavajú limit skladu. Nevyužitá kapacita sa neprenáša do ďalšej hodiny; nevypickovaná práca zostáva v buffri.")
    else:
        st.caption("Krivky ukazujú potrebný pick bez obmedzenia kapacity. Oranžová je limit skladu. Pre reálny dopad limitu zapni jeho uplatnenie vľavo.")
    st.plotly_chart(performance_chart(day_frame,cap,limited),width="stretch",key="main_performance")
    st.caption("Stĺpce = nové vzniky počas hodiny. Čiary = pick v hodine začínajúcej na osi. "
               "Vznik v priebehu hodiny je konzervatívne dostupný od nasledujúcej celej hodiny. "
               "Dnešný profil je simulácia cieľového objemu, nie pôvodné namerané počty.")
    over_current = day_frame.current_pick > cap + 1e-4
    over_balanced = day_frame.balanced_required > cap + 1e-4
    cols = st.columns(3)
    cols[0].metric("Nad limitom · dnešný profil",f"{int(over_current.sum())} h")
    cols[1].metric("Nad limitom · vyrovnaný pick",f"{int(over_balanced.sum())} h")
    cols[2].metric("Nesplnené v termíne pri limite",fmt(report.unmet))
    st.caption(f"Potrebná vyrovnaná špička bez limitu: {fmt(day_frame.balanced_required.max())} jl/h. "
               f"{fmt(report.structural_unmet*factor)} joblines nemá časový priestor od 06:00 po deadline ani bez limitu. "
               "Aj túto oneskorenú prácu naďalej pickujeme; nezmizne z bufferu.")
    if report.unmet > max(1e-4,target*1e-9):
        st.warning(f"{fmt(report.unmet)} cieľových joblines sa pri limite {fmt(cap)} jl/h nedá naplánovať do termínu. "
                   "Objem zostáva v bilancii; historické predpickovanie ho neznižuje.")
    st.subheader("Buffer: koľko máme stále čo pickovať")
    st.plotly_chart(inventory_chart(day_frame,report.initial_buffer*factor,limited),width="stretch",key="buffer")
    current_end = day_frame["current_limited_backlog" if limited else "current_backlog"].iloc[-1]
    balanced_end = day_frame["scenario_backlog" if limited else "balanced_required_backlog"].iloc[-1]
    st.caption(f"Buffer na konci dňa · dnešný profil: {fmt(current_end)} · vyrovnaný pick: {fmt(balanced_end)} joblines.")
    st.caption("Buffer na hranici hodiny = počiatočné vzniky + nové vzniky − pick od 06:00. "
               "Nula znamená vyčerpanú dostupnú prácu; pick nesmie predbehnúť jej vznik.")
    st.subheader("Kontrola: vypickované nikdy neprekročí vzniknuté")
    st.plotly_chart(inventory_chart(day_frame,report.initial_buffer*factor,limited,True),width="stretch",key="cumulative")
    st.caption("Všetky tri krivky majú rovnaký výber joblines a rovnaký cieľový objem. "
               "Kumulatívny pick začína nulou, vzniky začínajú plným vstupným buffrom.")
    with st.expander("Kde presne prekračujeme limit a kde je nulový pick"):
        detail = day_frame[["hour","created_scaled","current_pick","balanced_required"]].copy()
        detail["nad_limitom_dnes"] = (detail.current_pick-cap).clip(lower=0)
        detail["nad_limitom_vyrovnane"] = (detail.balanced_required-cap).clip(lower=0)
        st.dataframe(detail,hide_index=True)
        st.caption("Vyrovnaný pick môže byť nulový, ak nie je dostupná práca, už je dokončená alebo je limit nulový. "
                   "Zmeškaný termín nevyraďuje jobline z pickovania. "
                   "Minimalizácia špičky je doplnená vyrovnávaním hodinového zaťaženia, aby nevznikali ľubovoľné prázdne sloty.")
    with st.expander("Nameraná história skladu · referenčné hodnoty"):
        st.plotly_chart(lines(day_frame,["warehouse_picked","picked_count"],
                             ["Celý sklad · namerané","Vybrané svozy · namerané"]),width="stretch")
        st.caption("Referenčné hodnoty sa s cieľom nemenia a neznižujú scenárový buffer. "
                   "Denný profil nie je dôkazom dodržania konkrétneho svozu; vyrovnaný plán kontroluje termíny každej časovej skupiny.")
    if view == "Buffer a vznik":
        st.plotly_chart(arrivals_chart(day_frame,report.initial_buffer,factor),width="stretch")

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
                                 safety_hours=safety,lookback_hours=0,cap=cap,unmet=report.unmet,source=source,
                                 historical_prepicking_ignored=True,limit_applied_to_charts=limited)])
    audit = report.simulation.allocations.copy()
    if len(audit):
        audit["on_time"] = report.plan.groups.on_time.reindex(audit.group).to_numpy()
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
