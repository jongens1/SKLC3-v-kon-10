"""SKLC3 Warehouse Picking Performance — Streamlit entry point."""
from __future__ import annotations

from dataclasses import asdict, replace
from datetime import date, time
import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from src.bigquery_client import load_joblines
from src.config import load_config
from src.data_processing import (collection_distribution, demo_data, hourly_metrics,
                                  operational_window, prepare_data)
from src.performance import apply_scaling, required_plan, scaling_factor
from src.prepicking import simulate
from src.plots import backlog_chart, lines
from src.utils import csv_bytes, read_snapshot

ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title="SKLC3 Warehouse Picking Performance", page_icon="📦", layout="wide")
st.title("SKLC3 Warehouse Picking Performance")
st.caption("Logistický deň · Europe/Bratislava · výber podľa vzniku joblines · Branch 6281 alebo názov skladu SKLC3")


def get_secrets() -> dict:
    try:
        return st.secrets.to_dict()
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return {}


@st.cache_data(ttl=900, show_spinner="Čítam agregáty z BigQuery…")
def cached_bigquery(config_values: dict, start: pd.Timestamp, end: pd.Timestamp,
                    credential_signature: str, _secrets: dict):
    # Signature prevents cache reuse after a credential change; secrets themselves
    # are excluded from Streamlit's argument hashing and are never displayed.
    from src.config import BigQueryConfig
    return load_joblines(BigQueryConfig(**config_values), start, end, _secrets)


secrets = get_secrets()
try:
    config = load_config(secrets)
except (ValueError, TypeError, json.JSONDecodeError) as exc:
    st.error(f"Chyba konfigurácie: {exc}")
    st.info("Oprav .env alebo .streamlit/secrets.toml podľa priložených príkladov.")
    st.stop()

metadata_path = ROOT / "data" / "snapshot_metadata.json"
snapshot_meta = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else None
with st.sidebar:
    st.header("Nastavenia SKLC3")
    day = st.date_input("Logistický deň", date(2026, 10, 15))
    start_time = st.time_input("Začiatok logistického dňa", time(6), step=3600)
    choices = (["Overený lokálny snapshot"] if snapshot_meta else []) + ["BigQuery · iba čítanie", "DEMO · syntetické dáta"]
    source = st.selectbox("Dátový zdroj", choices)
    safety = st.number_input("Bezpečnostný predstih pred cutoffom (h)", min_value=0.0, max_value=12.0, value=1.0, step=0.5)
    lookback = st.slider("Okno predpickovania (h)", 0, 12, 4)
    use_cap = st.checkbox("Obmedziť maximálny hodinový výkon", False)
    cap = st.number_input("Maximálny výkon pre cieľový objem (jl/h)", min_value=0.0, value=10000.0, step=500.0) if use_cap else None
    with st.expander("BigQuery konfigurácia"):
        st.caption("Konfigurácia: prostredie / .env → Streamlit secrets → predvolené hodnoty.")
        billing = st.text_input("Billing project", config.billing_project)
        project = st.text_input("Zdrojový project", config.source_project)
        dataset = st.text_input("Dataset", config.dataset)
        location = st.text_input("Región", config.location)
        mode = st.selectbox("Zdrojová schéma", ["joined", "flat"], index=["joined", "flat"].index(config.mode))
        table = st.text_input("Joblines tabuľka / view", config.table)
        mapping = st.text_area("Mapovanie stĺpcov pre flat režim (JSON)", json.dumps(config.columns, indent=2))
        st.caption("joined používa v_StoreJobs, v_StoreJobLineStates a v_Stores. Ich názvy sa nastavujú v .env / secrets.")
        if st.button("Obnoviť cache BigQuery"):
            cached_bigquery.clear()
    config = replace(config, billing_project=billing, source_project=project, dataset=dataset,
                     location=location, mode=mode, table=table)

try:
    config = replace(config, columns=json.loads(mapping))
    config.validate()
    start, end = operational_window(day, start_time)
except (ValueError, TypeError, AttributeError, json.JSONDecodeError) as exc:
    st.error(f"Neplatné nastavenia: {exc}")
    st.stop()

provenance = {}
try:
    if source.startswith("DEMO"):
        raw = demo_data(day, start_time)
        st.warning("DEMO · syntetických 124 000 joblines. Výsledky neslúžia na hodnotenie skutočného skladu.")
    elif source.startswith("Overený"):
        if start.isoformat() != snapshot_meta["start"] or end.isoformat() != snapshot_meta["end"]:
            st.warning("Lokálny snapshot pokrýva iba 15. 10. 2026 06:00 – 16. 10. 2026 06:00. Pre iný deň vyber BigQuery alebo DEMO.")
            st.stop()
        raw = read_snapshot(ROOT / "data" / snapshot_meta["file"], snapshot_meta)
        provenance = snapshot_meta
        st.info("Lokálny historický snapshot z BigQuery. Obnovenie dát vyžaduje nový čítací dotaz; nejde o live pripojenie.")
    else:
        import hashlib
        import os
        credential_info = {"secrets": secrets.get("gcp_service_account", {}),
                           "adc": os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "ADC")}
        signature = hashlib.sha256(json.dumps(credential_info, sort_keys=True).encode()).hexdigest()
        raw, provenance = cached_bigquery(asdict(config), start, end, signature, secrets)
except Exception as exc:
    st.error("Dáta sa nepodarilo načítať. Skontroluj credentials, oprávnenia, región a konfiguráciu.")
    # Provider errors can contain connection details; expose type, not secrets.
    st.caption(f"Typ chyby: {type(exc).__name__}. Aplikácia podporuje GOOGLE_APPLICATION_CREDENTIALS, ADC a Streamlit secrets.")
    st.info("Pre lokálne overenie vyber v bočnom paneli DEMO · syntetické dáta.")
    st.stop()

try:
    # BigQuery and hash-verified snapshot already applied the location predicate.
    data, summary, notices = prepare_data(raw, start, end, filter_location=source.startswith("DEMO"))
except ValueError as exc:
    st.error(f"Kontrola dát neprešla: {exc}")
    st.stop()

actual = summary["rows"]
if not actual:
    st.warning("Pre zvolený deň a filter SKLC3 nie sú dostupné joblines.")
    st.stop()
with st.sidebar:
    manual = st.checkbox("Manuálne zadať cieľový objem", False)
    target = st.number_input("Cieľový objem joblines", min_value=0, value=actual, step=1000,
                             key=f"target_{source}_{start.isoformat()}_{actual}") if manual else actual
    st.caption(f"Reálny objem: {actual:,} · cieľový objem: {target:,}")
factor = scaling_factor(actual, target)
hourly = hourly_metrics(data, start, end)
hours = pd.DatetimeIndex(hourly.hour)
plan = required_plan(data, hours, safety)
historical_simulation = simulate(plan.groups, len(hours), lookback)
scenario = simulate(plan.groups, len(hours), lookback, factor=factor, max_per_hour=cap)
hourly["required_pick_count"] = plan.hourly
hourly["prepick_smoothed_count"] = historical_simulation.hourly
hourly = apply_scaling(hourly, factor)
# With a target cap, this is a new simulation, not a scaled claim of feasibility.
hourly["prepick_smoothed_scaled"] = scenario.hourly
hourly["prepick_difference_scaled"] = hourly.required_pick_scaled - hourly.prepick_smoothed_scaled
hourly["scenario_backlog"] = hourly.cumulative_created_scaled - hourly.prepick_smoothed_scaled.cumsum()
hourly["backlog_risky"] = (hourly.backlog_growing & (hourly.required_pick_scaled > (cap if cap is not None else scenario.peak)))
structural_missing = float(plan.unscheduled["count"].sum()) if len(plan.unscheduled) else 0.0
unplanned_target = structural_missing * factor + scenario.unscheduled
if notices or plan.warnings:
    st.warning(f"Dátové obmedzenia: {summary['missing_cutoff']:,} joblines bez cutoffu, {summary['cancelled']:,} so stornom. Podrobnosti sú v Kvalite a pôvode dát.")

st.subheader("1. Dataset overview")
st.write(f"**{start:%d.%m.%Y %H:%M %Z} – {end:%d.%m.%Y %H:%M %Z}** · {len(hours)} hodinových intervalov")
cols = st.columns(4)
for col, label, value in zip(cols, ["Reálny objem", "Unikátne joblines", "Cieľový objem", "Scaling koeficient"],
                             [f"{actual:,}", f"{summary['unique_joblines']:,}", f"{target:,}", f"{factor:.6f}"]):
    col.metric(label, value)
cols = st.columns(4)
for col, label, value in zip(cols, ["S časom pickovania (aj po dni)", "Bez pickovania", "Vypickované až po konci dňa", "Bez cutoffu"],
                             [summary["picked"], summary["missing_pick"], summary["picked_after_window"], summary["missing_cutoff"]]):
    col.metric(label, f"{value:,}")
with st.expander("Kvalita a pôvod dát"):
    for notice in notices + plan.warnings:
        st.warning(notice)
    st.json(summary)
    st.json(provenance)
    st.caption("SQL agregáty majú už overené ID. Počet skupín je technická veľkosť dát; počet a unikátnosť joblines sa vyhodnocujú pred agregáciou. Storná sa nevylučujú automaticky.")
st.caption("Hodinové metriky znamenajú celý interval [H, H+1). Plán používa iba celé hodiny po vzniku a pred presným deadline mínus predstih. Čiastočné hodiny sa konzervatívne nevyužívajú.")

st.subheader("2. Hourly created vs picked")
st.plotly_chart(lines(hourly, ["created_count", "picked_count", "created_scaled", "picked_scaled"], "Vznik a pickovanie · skutočnosť a cieľ"), width="stretch")
st.caption("Pickovanie zahŕňa iba joblines vzniknuté vo vybranom logistickom dni. Neobsahuje prenesenú prácu z predchádzajúcich dní.")

st.subheader("3. Cumulative curves")
st.plotly_chart(lines(hourly, ["cumulative_created_scaled", "cumulative_picked_scaled", "backlog_scaled"], "Kumulatívne počty na konci hodín · cieľ"), width="stretch")
st.subheader("4. Backlog / buffer")
st.plotly_chart(backlog_chart(hourly), width="stretch")
st.caption("Oranžová = rast backlogu. Červená = rast spolu s required výkonom nad limitom alebo minimálnou vyrovnanou špičkou. Backlog je evidencia vybranej kohorty.")
st.dataframe(hourly[["hour", "backlog", "backlog_scaled", "backlog_growing", "backlog_risky"]], hide_index=True)

st.subheader("5. Distribution by collection / cutoff / dispatch time")
collections = collection_distribution(data)
if collections.empty:
    st.warning("Čas svozu/cutoffu nie je dostupný. Distribúciu nie je možné zobraziť.")
else:
    collections["joblines_scaled"] = collections.jobline_count * factor
    st.plotly_chart(px.bar(collections, x="collection_hour", y=["jobline_count", "joblines_scaled"],
                           barmode="group", title="Objem podľa hodiny cutoffu (vrátane nasledujúcich dní)"), width="stretch")
    due = data.loc[data.cutoff_at.notna(), ["cutoff_at", "jobline_count"]].groupby("cutoff_at", as_index=False).sum()
    due["latest_picking_time"] = due.cutoff_at - pd.Timedelta(hours=safety)
    due["joblines_scaled"] = due.jobline_count * factor
    st.dataframe(due, hide_index=True)

st.subheader("6. Required picking performance")
st.plotly_chart(lines(hourly, ["required_pick_count", "required_pick_scaled"], "Baseline: posledná plná prípustná hodina pre každú jobline"), width="stretch")
if structural_missing:
    st.error(f"Bez platnej plánovacej hodiny: {structural_missing:,.0f} reálnych / {structural_missing * factor:,.1f} cieľových joblines. Sú mimo krivky, zostávajú v celkovom objeme.")
    rejected = plan.unscheduled.assign(count_scaled=plan.unscheduled["count"] * factor)
    rejected["reason"] = rejected.reason.replace({
        "invalid_pick_order": "Pickovanie pred vznikom",
        "missing_cutoff_and_pick": "Chýba cutoff aj pickovanie",
        "no_full_slot_before_deadline": "Medzi vznikom a deadline nie je celá voľná hodina",
    })
    st.dataframe(rejected.rename(columns={"reason": "Dôvod", "count": "Reálny objem", "count_scaled": "Cieľový objem"}), hide_index=True)
st.caption("Baseline je najneskoršie možné pickovanie. Vyhladený plán nižšie ho môže presunúť skôr. Zvyšujúci sa cieľový objem zachováva historický časový profil a mix.")

st.subheader("7. Pre-picking simulation")
st.plotly_chart(lines(hourly, ["required_pick_scaled", "prepick_smoothed_scaled", "prepick_difference_scaled"], "Cieľový objem: pôvodný plán, predpickovanie a rozdiel"), width="stretch")
cols = st.columns(4)
for col, label, value in zip(cols, ["Maximum pred (jl/h)", "Maximum po (jl/h)", "Priemer po (jl/h)", "Nenaplánovaný cieľový objem"],
                             [hourly.required_pick_scaled.max(), scenario.peak, float(scenario.hourly.mean()), unplanned_target]):
    col.metric(label, f"{value:,.1f}")
if unplanned_target > max(1e-4, target * 1e-9):
    st.error("Scenár nie je splniteľný pri zvolených časových pravidlách a prípadnom výkonovom limite. Nenaplánovaný objem sa nestratil ani nepresunul za deadline.")
elif plan.fallback_count:
    st.warning("Objem sa do modelu zmestí, ale časť deadline je iba odhad podľa pickovania. Splnenie expedície tým nie je potvrdené.")
else:
    st.success("Scenár je časovo splniteľný v modeli celých hodín. Over dostupnosť ľudí, zásob a procesný význam cutoffu.")
if cap is None:
    st.info(f"Najnižší vypočítaný špičkový výkon pri tomto okne predpickovania: {scenario.peak:,.1f} jl/h.")
st.caption("Optimalizácia minimalizuje maximum hodinového objemu. Jedna hodina má spoločný limit pre všetky joblines. Výsledok je objemový scenár s desatinnými hodnotami, nie rozpis jednotlivých pickerov.")
st.plotly_chart(lines(hourly, ["backlog_scaled", "scenario_backlog"], "Historický a simulovaný backlog · cieľový objem"), width="stretch")

st.subheader("8. Tables and export")
st.dataframe(hourly, hide_index=True)
st.download_button("Hodinové metriky CSV", csv_bytes(hourly), "sklc3_hourly.csv", "text/csv")
st.download_button("Distribúcia cutoffov CSV", csv_bytes(collections), "sklc3_cutoffs.csv", "text/csv")
st.download_button("Audit pridelenia do hodín CSV", csv_bytes(scenario.allocations), "sklc3_schedule_audit.csv", "text/csv")
scenario_summary = pd.DataFrame([dict(logistic_day=str(day), start=start.isoformat(), end=end.isoformat(), source=source,
                                     actual_volume=actual, target_volume=target, scaling_factor=factor,
                                     safety_hours=safety, prepick_hours=lookback, max_per_hour=cap,
                                     scheduled_target=scenario.scheduled, unscheduled_target=unplanned_target,
                                     peak=scenario.peak, missing_cutoff=summary["missing_cutoff"], cancelled=summary["cancelled"])])
st.download_button("Parametre a výsledok scenára CSV", csv_bytes(scenario_summary), "sklc3_scenario.csv", "text/csv")
