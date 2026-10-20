"""Cohort selection, exact-time cleaning, weighted aggregates and synthetic data."""
from __future__ import annotations

from datetime import date, time, timedelta
import numpy as np
import pandas as pd

from src.config import ZONE


def operational_window(day: date, start_time: time = time(6)) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Local wall-clock day, including 23/25-hour DST days."""
    if start_time.minute or start_time.second or start_time.microsecond:
        raise ValueError("Začiatok logistického dňa musí byť na celej hodine.")
    start = pd.Timestamp.combine(day, start_time).tz_localize(ZONE, ambiguous="raise", nonexistent="raise")
    end = pd.Timestamp.combine(day + timedelta(days=1), start_time).tz_localize(
        ZONE, ambiguous="raise", nonexistent="raise")
    return start, end


def parse_timestamps(series: pd.Series) -> pd.Series:
    """Offset timestamps are converted; naive timestamps are local Bratislava time."""
    def convert(value):
        if pd.isna(value) or str(value).strip() == "":
            return pd.NaT
        try:
            stamp = pd.Timestamp(value)
            return stamp.tz_convert(ZONE) if stamp.tzinfo else stamp.tz_localize(
                ZONE, ambiguous="raise", nonexistent="raise")
        except (ValueError, TypeError):
            return pd.NaT
    return pd.to_datetime(series.map(convert), utc=True).dt.tz_convert(ZONE)


def prepare_data(raw: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp,
                 filter_location: bool = True) -> tuple[pd.DataFrame, dict, list[str]]:
    """Canonical details or weighted SQL groups; never silently fix duplicated IDs."""
    warnings: list[str] = []
    if "created_at" not in raw:
        if raw.empty:
            raw = pd.DataFrame(columns=["created_at"])
        else:
            raise ValueError("Chýba povinný stĺpec created_at.")
    data = raw.copy()
    weighted = "jobline_count" in data
    if not weighted:
        if "jobline_id" not in data:
            raise ValueError("Detailné dáta musia obsahovať jobline_id.")
        if data.jobline_id.isna().any() or data.jobline_id.duplicated().any():
            raise ValueError("Chýbajúce alebo duplicitné jobline ID. Oprav zdroj alebo nastav version.")
        data["jobline_count"] = 1
    counts = pd.to_numeric(data.jobline_count, errors="coerce")
    if ((counts.isna()) | (~np.isfinite(counts)) | (counts <= 0) | (counts % 1 != 0)).any():
        raise ValueError("Počty joblines musia byť kladné celé čísla.")
    data["jobline_count"] = counts.astype("int64")
    if "invalid_id" in data and data.invalid_id.fillna(False).any():
        raise ValueError("Zdroj obsahuje neunikátne alebo chýbajúce jobline ID.")
    for column in ["created_at", "picked_at", "cutoff_at", "ready_at"]:
        if column not in data:
            if column in {"picked_at", "cutoff_at"}:
                warnings.append(f"Chýba {column}; príslušné výpočty budú obmedzené.")
            data[column] = pd.NaT
        original = data[column]
        parsed = parse_timestamps(original)
        invalid = original.notna() & original.astype(str).str.strip().ne("") & parsed.isna()
        if invalid.any():
            raise ValueError(f"Neplatný alebo nejednoznačný čas v {column}.")
        data[column] = parsed
    if data.created_at.isna().any():
        raise ValueError("Chýba čas vzniku jobline.")
    data = data.loc[(data.created_at >= start) & (data.created_at < end)].copy()
    if filter_location:
        if not any(c in data for c in ["branch_id", "store_name", "store_id"]):
            raise ValueError("Chýba branch_id / store_name / store_id pre filter SKLC3.")
        branch = data.get("branch_id", pd.Series("", index=data.index)).astype("string").str.replace(r"\.0$", "", regex=True).eq("6281").fillna(False)
        store = pd.Series(False, index=data.index)
        for column in ["store_name", "store_id"]:
            if column in data:
                store |= data[column].astype("string").str.contains("SKLC3", case=False, na=False, regex=False)
        data = data.loc[branch | store].copy()
    # Whole slots only: a line becoming ready at 06:01 can start in the 07:00 slot.
    created_utc = data.created_at.dt.tz_convert("UTC")
    conservative_ready = created_utc.dt.ceil("h").dt.tz_convert(ZONE)
    data["ready_at"] = data.ready_at.fillna(conservative_ready)
    if (data.ready_at < data.created_at).any():
        raise ValueError("ready_at nesmie predchádzať vzniku.")
    data["operational_hour"] = ((created_utc - start.tz_convert("UTC")).dt.total_seconds() // 3600).astype(int)
    invalid_order = data.get("invalid_order", pd.Series(False, index=data.index)).fillna(False)
    invalid_order |= data.picked_at.notna() & (data.picked_at < data.created_at)
    data["invalid_order"] = invalid_order
    data["is_cancelled"] = data.get("is_cancelled", pd.Series(False, index=data.index)).fillna(False).astype(bool)
    count = data.jobline_count
    total = int(count.sum())
    summary = {
        "rows": total, "unique_joblines": total,
        "aggregate_rows": len(data), "picked": int(count[data.picked_at.notna()].sum()),
        "missing_pick": int(count[data.picked_at.isna()].sum()),
        "missing_cutoff": int(count[data.cutoff_at.isna()].sum()),
        "invalid_order": int(count[data.invalid_order].sum()),
        "cancelled": int(count[data.is_cancelled].sum()),
        "picked_after_window": int(count[data.picked_at >= end].sum()),
    }
    if summary["invalid_order"]:
        warnings.append(f"{summary['invalid_order']:,} joblines má pickovanie pred vznikom; v pláne sú označené ako nesplniteľné, v histórii zostávajú.")
    if summary["cancelled"]:
        warnings.append(f"{summary['cancelled']:,} joblines má StornoDate. Zostávajú v požadovanej kohorte; plán je scenár celého objemu vrátane storien.")
    if summary["missing_pick"]:
        warnings.append("Chýbajúci PickedDate nie je dôkaz otvorenej fyzickej práce. Over procesné typy a storná.")
    return data.reset_index(drop=True), summary, warnings


def hourly_metrics(data: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Only events of lines CREATED in the selected day; retains their later pick times in data."""
    index = pd.date_range(start, end, freq="h", inclusive="left")
    result = pd.DataFrame({"hour": index, "operational_hour": np.arange(len(index))})
    for source, name in [("created_at", "created_count"), ("picked_at", "picked_count")]:
        hours = data[source].dt.tz_convert("UTC").dt.floor("h").dt.tz_convert(ZONE)
        count = data.groupby(hours).jobline_count.sum()
        result[name] = count.reindex(index, fill_value=0).to_numpy(dtype=float)
    result["cumulative_created"] = result.created_count.cumsum()
    before = float(data.loc[data.picked_at < start, "jobline_count"].sum())
    result["cumulative_picked"] = result.picked_count.cumsum() + before
    result["backlog"] = result.cumulative_created - result.cumulative_picked
    result["backlog_growing"] = result.backlog.diff().fillna(result.backlog.iloc[0]) > 0
    return result


def collection_distribution(data: pd.DataFrame) -> pd.DataFrame:
    available = data.loc[data.cutoff_at.notna()].copy()
    available["collection_hour"] = available.cutoff_at.dt.tz_convert("UTC").dt.floor("h").dt.tz_convert(ZONE)
    return available.groupby("collection_hour", as_index=False).jobline_count.sum()


def demo_data(day: date, start_time: time = time(6), volume: int = 124_000) -> pd.DataFrame:
    """Deterministic weighted synthetic cohort with delayed picking and several deadlines."""
    start, end = operational_window(day, start_time)
    hours = pd.date_range(start, end, freq="h", inclusive="left")
    weights = np.array([2 + 12 * np.exp(-((i - 6) / 3) ** 2) + 9 * np.exp(-((i - 15) / 3) ** 2) for i in range(len(hours))])
    counts = np.floor(weights / weights.sum() * volume).astype(int)
    counts[:volume - int(counts.sum())] += 1
    rows = []
    for i, (hour, count) in enumerate(zip(hours, counts)):
        # Split each hour over two loads; exact cutoff remains separate from hour buckets.
        for offset, n in [(5, int(count // 2)), (35, int(count - count // 2))]:
            created = hour + pd.Timedelta(minutes=offset)
            block = (i // 4 + 1) * 4
            cutoff = start + pd.Timedelta(hours=block + 3)
            rows.append(dict(created_at=created, picked_at=created + pd.Timedelta(minutes=80 + i % 3 * 20),
                             cutoff_at=cutoff, branch_id="6281", store_id="10686", store_name="162 SKLC3",
                             jobline_count=n, is_cancelled=False))
    return pd.DataFrame(rows)
