"""Explicit SELECT-only export of a collection cohort to ignored local data/."""
from __future__ import annotations
import argparse
from datetime import date, datetime, time
import hashlib
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.bigquery_client import build_query, load_joblines
from src.config import load_config
from src.data_processing import operational_window, prepare_data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat, default=date(2026, 10, 15))
    parser.add_argument("--start", type=time.fromisoformat, default=time(6))
    args = parser.parse_args()
    secret_path = ROOT / ".streamlit/secrets.toml"
    secrets = {}
    if secret_path.exists():
        import tomllib
        secrets = tomllib.loads(secret_path.read_text(encoding="utf-8"))
    config = load_config(secrets)
    start, end = operational_window(args.date, args.start, config.timezone)
    raw, provenance = load_joblines(config, start, end, secrets)
    _, summary, warnings = prepare_data(raw, start, end, config.allowed_job_types,
                                        config.branch_id, config.store_pattern)
    directory = ROOT / "data"
    directory.mkdir(exist_ok=True)
    path = directory / f"sklc3_collection_{args.date.isoformat()}.csv"
    raw.to_csv(path, index=False)
    metadata = dict(provenance, file=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    prepared_at=datetime.now(ZoneInfo(config.timezone)).isoformat(),
                    start=start.isoformat(), end=end.isoformat(), timezone=config.timezone,
                    collection_column=config.columns["collection"], job_type_column=config.columns["job_type"],
                    summary=summary, warnings=warnings)
    (directory / "snapshot_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    (directory / "snapshot_query.sql").write_text(build_query(config), encoding="utf-8")
    print(f"Saved {summary['rows']:,} selected joblines in {len(raw):,} aggregate groups. Job: {provenance['job_id']}")


if __name__ == "__main__":
    main()
