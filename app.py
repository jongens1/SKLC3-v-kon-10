"""SKLC3 collection-day picking performance — Streamlit entry point."""
from __future__ import annotations

from dataclasses import asdict, replace
from datetime import date, time
import hashlib
import json
import os
import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from src.bigquery_client import load_joblines
from src.config import load_config
from src.data_processing import (collection_distribution, event_timeline, operational_window,
                                  planning_metrics, planning_window, prepare_data)
from src.demo_data import demo_data
from src.performance import apply_scaling, required_plan, scaling_factor
from src.prepicking import simulate
from src.plots import backlog_chart, lines
from src.utils import csv_bytes

st.set_page_config(page_title="SKLC3 Warehouse Picking Performance", page_icon="📦", layout="wide")
st.title("SKLC3 Warehouse Picking Performance")
st.caption("Svozový deň podľa collection/cutoff · história vzniku a pickovania bez časového orezu")


def read_secrets() -> dict:
    try:
        return st.secrets.to_dict()
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return {}


@st.cache_data(ttl=900, show_spinner="Čítam svozovú kohortu z BigQuery…")
def cached_bigquery(config_values: dict, start: pd.Timestamp, end: pd.Timestamp,
                    credential_signature: str, _secrets: dict):
    from src.config import BigQueryConfig
    return load_joblines(BigQueryConfig(**config_values), start, end, _secrets)


secrets = read_secrets()
try:
    config = load_config(secrets)
except Exception as exc:
    st.error(f"Neplatná konfigurácia: {exc}")
    st.info("Skontroluj .env alebo .streamlit/secrets.toml podľa príkladov v repozitári.")
    st.stop()

with st.sidebar:
    st.header("Nastavenia SKLC3")
    day = st.date_input("Sledovaný svozový deň", date(2026, 10, 15))
    start_time = st.time_input("Začiatok logistického dňa", time.fromisoformat(config.default_logistic_start_time), step=3600)
    timezone = st.text_input("Timezone", config.timezone)
    available_credentials = bool(secrets.get("gcp_service_account") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))
    source = st.selectbox("Dátový zdroj", ["BigQuery · iba čítanie", "DEMO · syntetické dáta"],
                          index=0 if available_credentials else 1)
    safety = st.number_input("Safety buffer pred svozom (h)", min_value=0.0, max_value=168.0, value=1.0, step=0.5)
    lookback = st.slider("Pre-picking planning lookback (h)", 0, 168, 24)
    granularity = st.selectbox("Granularita created/picked grafov", ["hour", "day"])
    use_cap = st.checkbox("Obmedziť maximálny hodinový výkon", False)
    cap = st.number_input("Maximálny výkon pre cieľový objem (jl/h)", min_value=0.0, value=10000.0, step=500.0) if use_cap else None
    with st.expander("BigQuery konfigurácia a stĺpce"):
        billing = st.text_input("Billing project", config.billing_project)
        project = st.text_input("Zdrojový GCP project", config.source_project)
        dataset = st.text_input("Dataset", config.dataset)
        table = st.text_input("Joblines table / view", config.table)
        location = st.text_input("Región BigQuery", config.location)
        mode = st.selectbox("Zdrojová schéma", ["joined", "flat"], index=["joined", "flat"].index(config.mode))
        mapping_text = st.text_area("Mapovanie stĺpcov (JSON)", json.dumps(config.columns, ensure_ascii=False, indent=2))
        allowed_text = st.text_area("Povolené job typy (oddelené čiarkou)", ",".join(config.allowed_job_types))
        branch = st.text_input("Branch ID", config.branch_id)
        pattern = st.text_input("Store LIKE pattern", config.store_pattern)
        st.caption("joined mapuje natívne typy podľa ID a smeru. job_type mapovanie sa používa pre flat tabuľku. Názvy pripojených tabuliek sa nastavujú v .env / secrets.")
        if st.button("Obnoviť BigQuery cache"):
            cached_bigquery.clear()

try:
    config = replace(config, billing_project=billing, source_project=project, dataset=dataset,
                     table=table, location=location, mode=mode, timezone=timezone,
                     columns=json.loads(mapping_text), branch_id=branch, store_pattern=pattern,
                     allowed_job_types=tuple(v.strip() for v in allowed_text.split(",") if v.strip()))
    config.validate()
    start, end = operational_window(day, start_time, timezone)
    hours = planning_window(start, end, int(lookback))
except Exception as exc:
    st.error(f"Neplatné nastavenia: {exc}")
    st.stop()

provenance = {}
try:
    if source.startswith("DEMO"):
        raw = demo_data(day, start_time, timezone)
        st.warning("DEMO · 124 000 syntetických joblines pred filtrami. Ide o ukážku, nie reálny výkon skladu.")
    else:
        credential_info = {"service_account": secrets.get("gcp_service_account", {}),
                           "adc_path": os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "ADC")}
        signature = hashlib.sha256(json.dumps(credential_info, sort_keys=True).encode()).hexdigest()
        raw, provenance = cached_bigquery(asdict(config), start, end, signature, secrets)
except Exception as exc:
    st.error("BigQuery sa nepodarilo načítať. Skontroluj credentials, oprávnenia, názvy stĺpcov a región.")
    st.caption(f"Typ chyby: {type(exc).__name__}. Credentials sa nezobrazujú. Konfigurácia podporuje service account, ADC a Streamlit secrets.")
    st.info("Na lokálne overenie vyber Dátový zdroj → DEMO · syntetické dáta.")
    st.stop()

try:
    data, summary, notices = prepare_data(raw, start, end, config.allowed_job_types,
                                         config.branch_id, config.store_pattern)
except ValueError as exc:
    st.error(f"Kontrola dát: {exc}")
    st.stop()

actual = summary["rows"]
if actual == 0:
    st.warning("Po filtroch svozového času, skladu a typov jobu nie sú dostupné joblines.")
    st.stop()
with st.sidebar:
    manual = st.checkbox("Manuálne zadať cieľový objem", False)
    target = st.number_input("Cieľový objem joblines", min_value=0, value=actual, step=1000,
                             key=f"target_{source}_{start.isoformat()}_{actual}") if manual else actual
    st.caption(f"Reálny objem: {actual:,} · cieľový objem: {target:,}")
factor = scaling_factor(actual, target)
created = event_timeline(data, "created_at", granularity)
picked = event_timeline(data, "picked_at", granularity)
created["count_scaled"] = created["count"] * factor
picked["count_scaled"] = picked["count"] * factor
collections = collection_distribution(data, start, end)
collections["count_scaled"] = collections["count"] * factor
hourly = planning_metrics(data, hours)
plan = required_plan(data, hours, safety)
real_simulation = simulate(plan.groups, len(hours))
scenario = simulate(plan.groups, len(hours), factor=factor, max_per_hour=cap)
hourly["required_pick_count"] = plan.hourly
hourly["cumulative_required"] = plan.overdue_before_window + hourly.required_pick_count.cumsum()
hourly["prepick_smoothed_count"] = real_simulation.hourly
hourly = apply_scaling(hourly, factor)
hourly["prepick_smoothed_scaled"] = scenario.hourly
hourly["cumulative_simulated"] = hourly.prepick_smoothed_scaled.cumsum()
hourly["scenario_backlog"] = hourly.cumulative_available_scaled - hourly.cumulative_simulated
hourly["prepick_difference_scaled"] = hourly.required_pick_scaled - hourly.prepick_smoothed_scaled
hourly["deadline_shortfall_scaled"] = np.maximum(0, hourly.cumulative_required_scaled - hourly.cumulative_simulated)
hourly["backlog_risky"] = hourly.deadline_shortfall_scaled > max(1e-4, target * 1e-9)
structural = float(plan.unscheduled["count"].sum()) if len(plan.unscheduled) else 0.0
unmet = structural * factor + scenario.unscheduled

st.subheader("1. Dataset overview")
st.write(f"**Svozový interval:** {start:%d.%m.%Y %H:%M %Z} – {end:%d.%m.%Y %H:%M %Z}")
st.write(f"**Planning okno:** {hours[0]:%d.%m.%Y %H:%M %Z} – {end:%d.%m.%Y %H:%M %Z} · {len(hours)} hodín")
st.caption(f"Collection stĺpec: {config.columns['collection']} · Job type: {config.columns['job_type']}" +
           (" (joined: odvodený z JobType_ID, JobSubType_ID a JobDirection_ID)" if config.mode == "joined" else ""))
st.write("**Povolené typy:** " + ", ".join(config.allowed_job_types))
cols = st.columns(4)
for col, label, value in zip(cols, ["Reálny objem", "Unikátne joblines", "Cieľový objem", "Scaling factor"],
                             [f"{actual:,}", f"{summary['unique_joblines']:,}", f"{target:,}", f"{factor:.6f}"]):
    col.metric(label, value)
cols = st.columns(3)
for col, label, key in zip(cols, ["Bez Created_At", "Bez Picked_At", "Bez collection/cutoff"],
                           ["missing_created", "missing_pick", "missing_collection"]):
    col.metric(label, f"{summary[key]:,}")
st.caption("Joblines bez collection času nemožno priradiť k svozovému dňu a filter ich vyradí. Zobrazený počet je po filtroch; nulová hodnota nepotvrdzuje úplnosť celého zdroja.")
by_type = data.groupby("job_type", as_index=False).jobline_count.sum()
by_type["scaled"] = by_type.jobline_count * factor
st.dataframe(by_type, hide_index=True)
with st.expander("Časové rozsahy, kvalita a pôvod dát"):
    for notice in notices:
        st.warning(notice)
    st.json(summary)
    st.json(provenance)
    st.caption("Storná zostávajú v požadovanej kohorte. Chýbajúce PickedDate nie je dôkaz otvorenej fyzickej práce. Neplatné poradie historických časov nemení dostupnosť simulácie.")

st.subheader("2. Created timeline")
st.caption(f"Min Created_At: {summary['min_created']} · Max Created_At: {summary['max_created']}")
if created.empty:
    st.warning("Chýbajú časy vzniku; nie je možné vytvoriť created graf.")
else:
    st.plotly_chart(lines(created, ["count", "count_scaled"], "Joblines created over time for selected collection day"), width="stretch")
st.caption("Celá dostupná história vybranej svozovej kohorty, aj niekoľko dní pred svozom.")

st.subheader("3. Picked timeline")
st.caption(f"Min Picked_At: {summary['min_picked']} · Max Picked_At: {summary['max_picked']}")
if summary["missing_pick"]:
    st.warning(f"Bez Picked_At: {summary['missing_pick']:,} joblines. Chýbajúce časy sa nedopĺňajú odhadom.")
if picked.empty:
    st.info("Žiadne vyplnené časy pickovania.")
else:
    st.plotly_chart(lines(picked, ["count", "count_scaled"], "Joblines picked over time for selected collection day"), width="stretch")

st.subheader("4. Collection / cutoff / dispatch distribution")
tabs = st.tabs(["Reálne hodnoty", "Cieľový objem"])
for tab, column in zip(tabs, ["count", "count_scaled"]):
    with tab:
        st.plotly_chart(px.bar(collections, x="hour", y=column, color="job_type", barmode="stack",
                               title="Svozy po hodinách podľa procesu", template="plotly_white"), width="stretch")

st.subheader("5. Cumulative curves")
st.plotly_chart(lines(hourly, ["cumulative_available_scaled", "cumulative_required_scaled", "cumulative_simulated"],
                      "Planning okno: dostupnosť, splatná potreba a simulované pickovanie · cieľ"), width="stretch")
st.caption("Dostupnosť zahŕňa carry-in pred planning oknom. Required vychádza z cutoffu mínus safety buffer. Simulácia modeluje celú kohortu od začiatku okna, nie zvyšok po historických pickoch.")

st.subheader("6. Backlog / buffer")
st.plotly_chart(backlog_chart(hourly), width="stretch")
st.plotly_chart(lines(hourly, ["backlog", "backlog_scaled", "scenario_backlog"], "Historický backlog a simulovaný dostupný buffer"), width="stretch")
st.caption("Oranžová = historický backlog rastie. Červená = simulácia nestihla kumulatívnu potrebu. Každý bod je stav na konci hodiny.")

st.subheader("7. Required picking performance")
st.plotly_chart(lines(hourly, ["required_pick_count", "required_pick_scaled"], "Potrebný objem v poslednej celej hodine pred pick deadline"), width="stretch")
st.caption("Celé hodinové sloty: 06:10 vznik → najskôr 07:00–08:00. Cutoff 14:30 a safety 1 h → deadline 13:30, posledný celý slot 12:00–13:00. Ide o konzervatívnu hodinovú presnosť.")
if plan.overdue_before_window:
    st.warning(f"Potreba už pred začiatkom planning okna: {plan.overdue_before_window:,.0f} joblines.")
if structural:
    st.error(f"Objem bez prípustnej celej hodiny: {structural:,.0f} reálnych / {structural * factor:,.1f} cieľových joblines. Zostáva v required potrebe a v nenaplánovanom objeme.")
    rejected = plan.unscheduled.assign(scaled=plan.unscheduled["count"] * factor)
    rejected["reason"] = rejected.reason.replace({
        "missing_created": "Neznámy čas vzniku", "missing_collection": "Neznámy cutoff",
        "deadline_before_creation": "Deadline pred vznikom", "deadline_before_planning_window": "Deadline pred planning oknom",
        "deadline_after_planning_window": "Deadline po planning okne", "no_full_slot_before_deadline": "Nie je dostupný celý hodinový slot"})
    st.dataframe(rejected, hide_index=True)

st.subheader("8. Pre-picking simulation")
st.plotly_chart(lines(hourly, ["required_pick_scaled", "prepick_smoothed_scaled", "prepick_difference_scaled"],
                      "Cieľový objem: baseline, vyhladené pickovanie a rozdiel"), width="stretch")
cols = st.columns(4)
for col, label, value in zip(cols, ["Maximum pred (jl/h)", "Maximum po (jl/h)", "Priemer po (jl/h)", "Unmet / infeasible volume"],
                             [hourly.required_pick_scaled.max(), scenario.peak, scenario.hourly.mean(), unmet]):
    col.metric(label, f"{value:,.1f}")
if unmet > max(1e-4, target * 1e-9):
    st.error("Scenár nie je splniteľný pri zvolenom planning okne a prípadnom hodinovom limite. Nenaplánovaný objem sa nestratil ani nepresunul za deadline.")
else:
    st.success("Cieľový objem sa zmestí do dostupných hodín a zadaného limitu v hodinovom modeli.")
st.caption("Plán minimalizuje hodinovú špičku spoločným fondom kapacity. Hodiny pred vznikom a po deadline sú zakázané. Planning lookback predlžuje celé okno, nie interval každej jobline o rovnaký počet hodín.")

st.subheader("9. Tables and export")
st.dataframe(hourly, hide_index=True)
audit = scenario.allocations.copy()
if len(audit):
    audit["slot_start"] = hours[audit.hour.to_numpy(dtype=int)]
    audit["slot_end"] = audit.slot_start + pd.Timedelta(hours=1)
scenario_summary = pd.DataFrame([dict(collection_start=start.isoformat(), collection_end=end.isoformat(),
        planning_start=hours[0].isoformat(), timezone=timezone, source=source,
        real_volume=actual, target_volume=target, scaling_factor=factor, lookback_hours=lookback,
        safety_hours=safety, max_per_hour=cap, scheduled=scenario.scheduled, unmet=unmet,
        structural_infeasible_scaled=structural * factor, capacity_unmet=scenario.unscheduled,
        allowed_job_types=",".join(config.allowed_job_types))])
exports = [(created,"created_timeline"), (picked,"picked_timeline"), (collections,"collection_distribution"),
           (hourly,"planning_hourly"), (hourly[["hour","required_pick_count","required_pick_scaled"]],"required_performance"),
           (hourly[["hour","prepick_smoothed_count","prepick_smoothed_scaled"]],"prepick_performance"),
           (hourly[["hour","backlog","backlog_scaled","scenario_backlog","backlog_risky"]],"backlog"),
           (audit,"schedule_audit"), (scenario_summary,"scenario_parameters")]
for frame, name in exports:
    st.download_button(f"Export {name} CSV", csv_bytes(frame), f"sklc3_{name}.csv", "text/csv")
