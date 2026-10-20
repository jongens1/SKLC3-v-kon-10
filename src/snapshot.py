"""Verified bundled aggregates. This module never connects to BigQuery."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import pandas as pd

DATA = Path(__file__).resolve().parents[1] / "data"


def manifest(directory: Path = DATA) -> dict:
    return json.loads((directory / "manifest.json").read_text(encoding="utf-8"))


def load_snapshot(day: str, directory: Path = DATA) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Check each file before loading the selected historical collection day."""
    catalog = manifest(directory)
    entry = catalog["days"][day]
    frames = []
    for name in ["cohort", "throughput"]:
        file = entry[name]
        path = directory / file["file"]
        if path.parent.resolve() != directory.resolve():
            raise ValueError("Snapshot path escapes data directory.")
        if hashlib.sha256(path.read_bytes()).hexdigest() != file["sha256"]:
            raise ValueError("Kontrolný súčet pripravených dát nesedí.")
        frames.append(pd.read_parquet(path))
    return frames[0], frames[1], entry


def save_snapshot(day: str, cohort: pd.DataFrame, throughput: pd.DataFrame,
                  metadata: dict, directory: Path = DATA) -> None:
    """Offline preparation writes only aggregated records and a reproducible manifest."""
    if "jobline_id" in cohort or "StoreJobLine_ID" in cohort:
        raise ValueError("Snapshot must contain aggregates, not individual IDs.")
    if not pd.Timestamp(day).strftime("%Y-%m-%d") == day:
        raise ValueError("Snapshot day must use YYYY-MM-DD.")
    directory.mkdir(parents=True,exist_ok=True)
    files = {}
    for kind,frame in [("cohort",cohort),("throughput",throughput)]:
        path = directory/f"sklc3_{kind}_{day}.parquet"
        frame.to_parquet(path,index=False,compression="zstd")
        files[kind] = dict(file=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    catalog = manifest(directory) if (directory/"manifest.json").exists() else {"version":2,"days":{}}
    catalog["days"][day] = dict(metadata,**files,contains_individual_ids=False)
    (directory/"manifest.json").write_text(json.dumps(catalog,ensure_ascii=False,indent=2),encoding="utf-8")
