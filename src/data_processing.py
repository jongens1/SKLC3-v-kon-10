"""Collection cohorts and complete event history, independent of Streamlit."""
from __future__ import annotations

from datetime import date, time, timedelta
import re
from typing import Any
import numpy as np
import pandas as pd
from src.config import ALLOWED_JOB_TYPES, ZONE


def operational_window(day: date, start_time: time = time(6), timezone: str = ZONE) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Wall-clock logistic day; DST can produce 23 or 25 elapsed hours."""
    if start_time.minute or start_time.second or start_time.microsecond:
        raise ValueError("Začiatok logistického dňa musí byť na celej hodine.")
    start = pd.Timestamp.combine(day, start_time).tz_localize(timezone, ambiguous="raise", nonexistent="raise")
    end = pd.Timestamp.combine(day + timedelta(days=1), start_time).tz_localize(timezone, ambiguous="raise", nonexistent="raise")
    return start, end


def planning_window(start: pd.Timestamp, end: pd.Timestamp, lookback: int = 24) -> pd.DatetimeIndex:
    """Lookback extends the ENTIRE window, rather than each job's deadline."""
    if not isinstance(lookback, int) or not 0 <= lookback <= 168:
        raise ValueError("Planning lookback musí byť celé číslo od 0 do 168 hodín.")
    return pd.date_range(start - pd.Timedelta(hours=lookback), end, freq="h", inclusive="left")


def parse_timestamps(series: pd.Series, timezone: str = ZONE) -> pd.Series:
    """Naive values are local; explicit offsets are converted to the selected zone."""
    def convert(value: Any) -> pd.Timestamp:
        if pd.isna(value) or str(value).strip() == "":
            return pd.NaT
        stamp = pd.Timestamp(value)
        return stamp.tz_convert(timezone) if stamp.tzinfo else stamp.tz_localize(timezone, ambiguous="raise", nonexistent="raise")
    try:
        return pd.to_datetime(series.map(convert), utc=True).dt.tz_convert(timezone)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Neplatný alebo nejednoznačný dátum v {series.name}.") from exc


def _like(series: pd.Series, pattern: str) -> pd.Series:
    regex = "^" + "".join(".*" if c == "%" else "." if c == "_" else re.escape(c) for c in pattern) + "$"
    return series.astype("string").str.match(regex, case=False, na=False)


def floor_hour(values: pd.Series) -> pd.Series:
    """Local-hour buckets preserve offset, including repeated DST hours."""
    return (values - pd.to_timedelta(values.dt.minute, unit="m")
            - pd.to_timedelta(values.dt.second, unit="s")
            - pd.to_timedelta(values.dt.microsecond, unit="us")
            - pd.to_timedelta(values.dt.nanosecond, unit="ns"))


def prepare_data(raw: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp,
                 allowed_job_types: tuple[str, ...] = ALLOWED_JOB_TYPES,
                 branch_id: str = "6281", store_pattern: str = "%SKLC3%") -> tuple[pd.DataFrame, dict[str, Any], list[str]]:
    """Filter by collection, warehouse and process; keep all created/picked history."""
    data = raw.copy()
    warnings: list[str] = []
    mandatory = {"collection_at", "job_type"}
    if data.empty:
        for column in mandatory:
            if column not in data:
                data[column] = pd.Series(dtype="object")
        if "jobline_count" not in data:
            data["jobline_count"] = pd.Series(dtype="int64")
    missing = mandatory - set(data)
    if missing:
        raise ValueError("Chýbajú povinné stĺpce: " + ", ".join(sorted(missing)))
    weighted = "jobline_count" in data
    if not weighted:
        if "jobline_id" not in data:
            raise ValueError("Detailné dáta musia obsahovať jobline_id.")
        data["jobline_count"] = 1
    counts = pd.to_numeric(data.jobline_count, errors="coerce")
    if (counts.isna() | ~np.isfinite(counts) | (counts <= 0) | (counts % 1 != 0)).any():
        raise ValueError("Počty musia byť kladné celé čísla.")
    data["jobline_count"] = counts.astype("int64")
    for column in ["created_at", "picked_at", "collection_at", "ready_at", "created_min", "created_max", "picked_min", "picked_max"]:
        if column not in data:
            if column in {"created_at", "picked_at"}:
                warnings.append(f"Chýba {column}; príslušná analýza bude obmedzená.")
            data[column] = pd.NaT
        data[column] = parse_timestamps(data[column], str(start.tz))
    data = data.loc[(data.collection_at >= start) & (data.collection_at < end)
                    & data.job_type.isin(allowed_job_types)].copy()
    if not data.empty and not any(c in data for c in ["branch_id", "store_id", "store_name"]):
        raise ValueError("Chýba branch_id alebo store pre filter SKLC3.")
    branch = data.get("branch_id", pd.Series("", index=data.index)).astype("string").str.replace(r"\.0$", "", regex=True).eq(str(branch_id)).fillna(False)
    store = pd.Series(False, index=data.index)
    for column in ["store_name", "store_id"]:
        if column in data:
            store |= _like(data[column], store_pattern)
    data = data.loc[branch | store].copy()
    if (not weighted and (data.jobline_id.isna().any() or data.jobline_id.duplicated().any())) or ("invalid_id" in data and data.invalid_id.fillna(False).any()):
        raise ValueError("Chýbajúce alebo duplicitné jobline ID; nastav verziovanie zdroja.")
    created_floor = floor_hour(data.created_at)
    ready = created_floor + pd.to_timedelta((data.created_at > created_floor).astype(int), unit="h")
    data["ready_at"] = data.ready_at.fillna(ready)
    if (data.ready_at < data.created_at).any():
        raise ValueError("Ready time nesmie predchádzať vzniku jobline.")
    data["operational_hour"] = ((data.collection_at - start).dt.total_seconds() // 3600).astype(int)
    data["invalid_order"] = data.get("invalid_order", pd.Series(False, index=data.index)).fillna(False).astype(bool) | (data.picked_at < data.created_at)
    data["is_cancelled"] = data.get("is_cancelled", pd.Series(False, index=data.index)).fillna(False).astype(bool)
    count = data.jobline_count
    def limit(column: str, fallback: str, method: str) -> str | None:
        values = data[column].fillna(data[fallback])
        value = getattr(values, method)()
        return value.isoformat() if pd.notna(value) else None
    summary = dict(rows=int(count.sum()), unique_joblines=int(count.sum()), aggregate_rows=len(data),
                   missing_created=int(count[data.created_at.isna()].sum()),
                   missing_pick=int(count[data.picked_at.isna()].sum()), picked=int(count[data.picked_at.notna()].sum()),
                   missing_collection=int(count[data.collection_at.isna()].sum()),
                   invalid_order=int(count[data.invalid_order].sum()), cancelled=int(count[data.is_cancelled].sum()),
                   min_created=limit("created_min", "created_at", "min"), max_created=limit("created_max", "created_at", "max"),
                   min_picked=limit("picked_min", "picked_at", "min"), max_picked=limit("picked_max", "picked_at", "max"))
    for key, label in [("missing_created", "bez času vzniku"), ("missing_pick", "bez času pickovania"),
                       ("invalid_order", "s pickovaním pred vznikom"), ("cancelled", "so stornom")]:
        if summary[key]:
            warnings.append(f"Joblines {label}: {summary[key]:,}.")
    return data.reset_index(drop=True), summary, warnings


def event_timeline(data: pd.DataFrame, column: str, granularity: str = "hour") -> pd.DataFrame:
    """Full min-to-max range of one event, independent of collection/planning window."""
    if granularity not in {"hour", "day"}:
        raise ValueError("Granularita musí byť hour alebo day.")
    stamps = data[column].dropna()
    if stamps.empty:
        return pd.DataFrame({"hour": pd.Series(dtype=data[column].dtype), "count": pd.Series(dtype=float)})
    bucket = floor_hour(data[column]) if granularity == "hour" else data[column].dt.normalize()
    counts = data.groupby(bucket).jobline_count.sum()
    index = pd.date_range(counts.index.min(), counts.index.max(), freq="h" if granularity == "hour" else "D")
    return counts.reindex(index, fill_value=0).rename_axis("hour").rename("count").reset_index()


def collection_distribution(data: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    hours = pd.date_range(start, end, freq="h", inclusive="left")
    if data.empty:
        return pd.DataFrame(columns=["hour", "job_type", "count"])
    bucket = floor_hour(data.collection_at)
    grouped = data.groupby([bucket, "job_type"]).jobline_count.sum()
    grouped.index = grouped.index.set_names(["hour", "job_type"])
    index = pd.MultiIndex.from_product([hours, sorted(data.job_type.unique())], names=["hour", "job_type"])
    return grouped.reindex(index, fill_value=0).rename("count").reset_index()


def planning_metrics(data: pd.DataFrame, hours: pd.DatetimeIndex) -> pd.DataFrame:
    """Carry-in plus hourly events; availability uses conservative whole-slot release."""
    start = hours[0]
    result = pd.DataFrame({"hour": hours, "planning_hour": np.arange(len(hours))})
    for column, target in [("created_at", "created_count"), ("picked_at", "picked_count"), ("ready_at", "available_count")]:
        bucket = floor_hour(data[column])
        counts = data.groupby(bucket).jobline_count.sum()
        result[target] = counts.reindex(hours, fill_value=0).to_numpy(dtype=float)
    created_before = float(data.loc[data.created_at < start, "jobline_count"].sum())
    picked_before = float(data.loc[data.picked_at < start, "jobline_count"].sum())
    ready_before = float(data.loc[data.ready_at < start, "jobline_count"].sum())
    result.loc[0, "available_count"] += ready_before
    result["cumulative_created"] = created_before + result.created_count.cumsum()
    result["cumulative_picked"] = picked_before + result.picked_count.cumsum()
    result["cumulative_available"] = result.available_count.cumsum()
    result["backlog"] = result.cumulative_created - result.cumulative_picked
    result["backlog_growing"] = result.backlog.diff().fillna(result.backlog.iloc[0] - (created_before - picked_before)) > 0
    result["initial_created"] = created_before
    result["initial_picked"] = picked_before
    return result
