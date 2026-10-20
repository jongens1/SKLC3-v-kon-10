"""Safe user exports and snapshot provenance."""
from __future__ import annotations

import hashlib
from pathlib import Path
import pandas as pd


def csv_bytes(frame: pd.DataFrame) -> bytes:
    safe = frame.copy()
    for column in safe.select_dtypes(include=["object", "string"]).columns:
        safe[column] = safe[column].map(lambda value: "'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@")) else value)
    return safe.to_csv(index=False).encode("utf-8-sig")


def read_snapshot(path: Path, metadata: dict) -> pd.DataFrame:
    if hashlib.sha256(path.read_bytes()).hexdigest() != metadata["sha256"]:
        raise ValueError("Kontrolný súčet lokálneho snapshotu nesedí.")
    return pd.read_csv(path, dtype={"store_id": "string"})
