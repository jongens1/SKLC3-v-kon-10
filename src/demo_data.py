"""Deterministic synthetic collection cohort, never a silent production fallback."""
from datetime import date, time
import numpy as np
import pandas as pd
from src.config import ALLOWED_JOB_TYPES, ZONE
from src.data_processing import operational_window


def demo_data(day: date, start_time: time = time(6), timezone: str = ZONE, volume: int = 124000) -> pd.DataFrame:
    """124k weighted joblines, created up to 72h before an in-day collection."""
    if volume < 1:
        raise ValueError("Demo objem musí byť kladný.")
    start, end = operational_window(day, start_time, timezone)
    hours = pd.date_range(start, end, freq="h", inclusive="left")
    weights = np.array([2 + 10 * np.exp(-((i - 7) / 4) ** 2) + 6 * np.exp(-((i - 16) / 3) ** 2) for i in range(len(hours))])
    counts = np.floor(weights / weights.sum() * volume).astype(int)
    counts[:volume - int(counts.sum())] += 1
    rows = []
    for i, (hour, count) in enumerate(zip(hours, counts)):
        collection = hour + pd.Timedelta(minutes=30)
        for k, n in enumerate([int(count // 3), int(count // 3), int(count - 2 * (count // 3))]):
            if n == 0:
                continue
            age = [5, 28, 68][k] + i % 4
            created = collection - pd.Timedelta(hours=age, minutes=15)
            picked = collection - pd.Timedelta(hours=2 + i % 2)
            rows.append(dict(created_at=created, picked_at=picked, collection_at=collection,
                             branch_id="6281", store_id="10686", store_name="162 SKLC3",
                             job_type=ALLOWED_JOB_TYPES[k], jobline_count=n, is_cancelled=False))
    return pd.DataFrame(rows)
