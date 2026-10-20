"""Offline SKLC3 dashboard: verified bundled aggregates, no runtime BigQuery calls."""
from __future__ import annotations
from datetime import date, time
import json
import pandas as pd
import streamlit as st

from src.config import ALLOWED_JOB_TYPES, ZONE
from src.data_processing import collection_distribution, event_timeline, operational_window, prepare_data
from src.dashboard import analyze, rescale, comparison_table, hourly_output
from src.demo_data import demo_data
from src.plots import arrivals_chart, collection_chart, performance_chart, comparison_charts, lines
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
    limited = st.checkbox("Uplatniť limit v krivkách",True,
                          help="Limit sa uplatňuje na vyrovnaný plán. Aktuálny variant je pôvodný nameraný výkon bez úprav. Vypnuté: teoretická potreba bez limitu.")
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
    if view == "Výkon a plán":
        st.subheader("Vzniky a pickovanie v rovnakom scenári")
        st.caption("Modrá používa pôvodný nameraný výkon skladu bez škálovania na cieľový objem. "
                   "Zelená vyrovnáva výkon pri rešpektovaní vzniku a splniteľných svozových termínov. Obe začínajú s rovnakým plným buffrom.")
        if limited:
            st.info("Vyrovnaný pick dodržiava limit skladu. Modrá zostáva pôvodným výkonom bez úprav. Nevyužitá kapacita sa neprenáša do ďalšej hodiny; nevypickovaná práca zostáva v buffri.")
        else:
            st.caption("Krivky ukazujú potrebný pick bez obmedzenia kapacity. Oranžová je limit skladu. Pre reálny dopad limitu zapni jeho uplatnenie vľavo.")
        st.plotly_chart(performance_chart(day_frame,cap,limited),width="stretch",key="main_performance")
        st.caption("Stĺpce = nové vzniky počas hodiny. Čiary = pick v hodine začínajúcej na osi. "
                   "Vznik v priebehu hodiny je konzervatívne dostupný od nasledujúcej celej hodiny. "
                   "Dnešný profil je simulácia cieľového objemu, nie pôvodné namerané počty.")
        over_current = day_frame.current_pick > cap + 1e-4
        over_balanced = day_frame.balanced_required > cap + 1e-4
        cols = st.columns(3)
        cols[0].metric("Nad limitom · pôvodný výkon",f"{int(over_current.sum())} h")
        cols[1].metric("Nad limitom · vyrovnaný pick",f"{int(over_balanced.sum())} h")
        cols[2].metric("Nesplnené v termíne pri limite",fmt(report.unmet))
        st.caption(f"Potrebná vyrovnaná špička bez limitu: {fmt(day_frame.balanced_required.max())} jl/h. "
                   f"{fmt(report.structural_unmet*factor)} joblines nemá časový priestor od 06:00 po deadline ani bez limitu. "
                   "Aj túto oneskorenú prácu naďalej pickujeme; nezmizne z bufferu.")
        if report.unmet > max(1e-4,target*1e-9):
            st.warning(f"{fmt(report.unmet)} cieľových joblines sa pri limite {fmt(cap)} jl/h nedá naplánovať do termínu. "
                       "Objem zostáva v bilancii; historické predpickovanie ho neznižuje.")
    st.subheader("Presné porovnanie: vzniky, pick a buffer")
    st.caption("Aktuálny výkon bez úprav = pôvodné namerané jl/h skladu bez škálovania a bez nového limitu. "
               "Používame ho ako kapacitu pre zvolenú kohortu; pri nedostatku dostupnej práce sa pick zastaví. "
               "Ide o simuláciu pri pôvodnom výkone, nie historické pickovanie tejto kohorty.")
    if limited:
        st.info(f"Zobrazený vyrovnaný plán má limit {fmt(cap)} jl/h · denná kapacita {fmt(cap*len(day_frame))} joblines. "
                "Aktuálny výkon zostáva pôvodnou nameranou referenciou bez úprav.")
    else:
        st.warning("Zobrazený vyrovnaný plán je BEZ LIMITU. Zapni Uplatniť limit v krivkách pre realizovateľný výsledok pri zadanej kapacite.")
    st.caption("Oba varianty začínajú s rovnakým plným buffrom a nulovým pickom. Všetky grafy používajú rovnakú definíciu aktuálneho výkonu.")
    outside_day = max(0.0,target-day_frame.cumulative_created_scaled.iloc[-1])
    if outside_day > 1e-4:
        st.caption(f"Do konca dňa vznikne {fmt(day_frame.cumulative_created_scaled.iloc[-1])} z cieľových {fmt(target)} joblines. "
                   f"Rozdiel {outside_day:.2f} pripadá na zdrojové joblines vzniknuté až mimo dňa a nemožno ho v tomto dni pickovať.")
    comparison = comparison_table(report,limited)
    selected_time = st.select_slider("Stav k času",options=comparison.time.tolist(),
                                     value=comparison.time.iloc[-1],format_func=lambda t:t.strftime("%d.%m. %H:%M"),
                                     key=f"comparison_time_{day}")
    selected = comparison.loc[comparison.time==selected_time].iloc[0]
    cumulative_plot,buffer_plot = comparison_charts(comparison,selected_time)
    cols = st.columns(3)
    for col,label,column in zip(cols,["Vzniknuté joblines","Vypickované · vyrovnaný pick","Vypickované · aktuálny výkon"],
                                ["created","picked_balanced","picked_current"]):
        col.metric(label,fmt(selected[column]))
    if limited:
        elapsed = int(comparison.index[comparison.time==selected_time][0])
        completed_on_time = day_frame.cumulative_completed_on_time.iloc[elapsed-1] if elapsed else 0
        completed_late = day_frame.cumulative_completed_late.iloc[elapsed-1] if elapsed else 0
        st.caption(f"Z vyrovnaného picku do zvoleného času: {fmt(completed_on_time)} v termíne a {fmt(completed_late)} po termíne. "
                   "Celkový pick neznamená, že boli dodržané všetky svozové termíny.")
    st.caption("1. Vzniknuté a vypickované joblines celkom do zvoleného času · biela zvislá čiara označuje vybraný čas.")
    st.plotly_chart(cumulative_plot,width="stretch",key="comparison_cumulative")
    cols = st.columns(2)
    cols[0].metric("Buffer · vyrovnaný pick",fmt(selected.buffer_balanced))
    cols[1].metric("Buffer · aktuálny výkon",fmt(selected.buffer_current))
    st.caption("2. Buffer = všetky dovtedy vzniknuté joblines − vypickované joblines daného variantu. "
               "Ukazuje prácu, ktorú ešte môžeme pickovať; nevzniknuté joblines nie sú dostupné.")
    st.plotly_chart(buffer_plot,width="stretch",key="comparison_buffer")
    readable = comparison.rename(columns={"time":"Čas","created":"Vzniknuté joblines",
        "picked_balanced":"Vypickované · vyrovnaný pick","picked_current":"Vypickované · aktuálny výkon bez úprav",
        "buffer_balanced":"Buffer · vyrovnaný pick","buffer_current":"Buffer · aktuálny výkon bez úprav"})
    with st.expander("Presné hodnoty po hodinách"):
        st.dataframe(readable,hide_index=True,column_config={column:st.column_config.NumberColumn(format="%.2f")
                                                           for column in readable if column!="Čas"})
        st.download_button("Porovnanie vznikov, pickov a bufferu CSV",csv_bytes(readable),
                           "sklc3_comparison.csv","text/csv")
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
        with st.expander("Vstupný buffer a jednotlivé hodinové vzniky"):
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
        rejections = report.plan.unscheduled.copy()
        rejections["Cieľový objem"] = rejections["count"]*factor
        st.dataframe(rejections.rename(columns={"reason":"Dôvod","count":"Zdrojové joblines"}),hide_index=True)
    st.caption("Hodinový výstup používa rovnaký aktuálny pick, vyrovnaný pick a buffer ako grafy. "
               "hour_start označuje začiatok výkonu, kumulatívne hodnoty sú stav k hour_end. "
               "Stĺpce with_limit vždy vykazujú variant pri zadanom limite.")
    exported_hourly = hourly_output(report,limited)
    st.dataframe(exported_hourly,hide_index=True)
    with st.expander("Úplná auditná tabuľka vrátane historických referencií"):
        st.caption("picked_count, cumulative_picked a backlog sú pôvodná história kohorty. Ich scaled varianty sú len prepočítané historické referencie; nejde o scenárový buffer.")
        st.dataframe(day_frame,hide_index=True)
    types = data.groupby("job_type",as_index=False).jobline_count.sum()
    scenario = pd.DataFrame([dict(day=str(day),real_volume=actual,target_volume=target,scaling_factor=factor,
                                 initial_buffer=report.initial_buffer,initial_buffer_scaled=report.initial_buffer*factor,
                                 already_completed_before_planning=report.completed_before_planning,
                                 safety_hours=safety,lookback_hours=0,cap=cap,unmet=report.unmet,source=source,
                                 historical_prepicking_ignored=True,limit_applied_to_charts=limited)])
    scenario["day_hours"] = len(day_frame)
    scenario["daily_capacity"] = cap*len(day_frame)
    scenario["created_by_day_end"] = day_frame.cumulative_created_scaled.iloc[-1]
    scenario["not_created_by_day_end"] = max(0.0,target-day_frame.cumulative_created_scaled.iloc[-1])
    scenario["balanced_picked_with_limit"] = report.simulation.scheduled
    scenario["missed_deadlines_with_limit"] = report.unmet
    audit = report.simulation.allocations.copy()
    if len(audit):
        audit["on_time"] = report.plan.groups.on_time.reindex(audit.group).to_numpy()
        times = pd.DatetimeIndex(report.planning.hour)
        audit["slot_start"] = times[audit.hour.to_numpy(dtype=int)]
        audit["slot_end"] = audit.slot_start+pd.Timedelta(hours=1)
    exports = [(exported_hourly,"Hodinový prehľad","hourly"),(report.planning,"Úplný audit vrátane histórie","planning"),
               (collections,"Svozy","collections"),(throughput,"Skutočný výkon skladu","actual_picking"),
               (types,"Typy procesov","types"),(scenario,"Nastavenia a výsledok","scenario"),
               (audit,"Audit plánovania","audit")]
    cols = st.columns(3)
    for i,(frame,label,name) in enumerate(exports):
        cols[i%3].download_button(label+" CSV",csv_bytes(frame),f"sklc3_{name}.csv","text/csv")
