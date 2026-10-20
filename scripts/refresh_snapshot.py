"""Offline data preparation. Never invoked by the deployed Streamlit app."""
from __future__ import annotations
import argparse
from datetime import date,datetime,time
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.bigquery_client import load_joblines,load_actual_throughput
from src.config import load_config
from src.data_processing import operational_window,prepare_data,parse_timestamps
from src.snapshot import save_snapshot


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date",type=date.fromisoformat,default=date(2026,10,15))
    parser.add_argument("--start",type=time.fromisoformat,default=time(6))
    args=parser.parse_args()
    secret_path=ROOT/".streamlit/secrets.toml"
    secrets={}
    if secret_path.exists():
        import tomllib
        secrets=tomllib.loads(secret_path.read_text(encoding="utf-8"))
    config=load_config(secrets)
    start,end=operational_window(args.date,args.start,config.timezone)
    raw,provenance=load_joblines(config,start,end,secrets)
    cohort,summary,_=prepare_data(raw,start,end,config.allowed_job_types,config.branch_id,config.store_pattern)
    actual,actual_provenance=load_actual_throughput(config,start,end,secrets)
    if len(actual):
        actual["hour"]=parse_timestamps(actual.hour,config.timezone)
    else:
        import pandas as pd
        actual=pd.DataFrame(columns=["hour","job_type","picked_count"])
    actual=actual[["hour","job_type","picked_count"]]
    metadata=dict(start=start.isoformat(),end=end.isoformat(),timezone=config.timezone,
                  prepared_at=datetime.now(ZoneInfo(config.timezone)).strftime("%Y-%m-%d"),
                  source=config.source_project+"."+config.dataset,billing_project=config.billing_project,
                  cohort_job=provenance["job_id"],actual_job=actual_provenance["job_id"],summary=summary,
                  actual_scope="All allowed lines picked in the day, regardless of collection day")
    save_snapshot(args.date.isoformat(),cohort.drop(columns=["jobline_id"],errors="ignore"),actual,metadata)
    print(f"Prepared {summary['rows']:,} collection joblines and {actual.picked_count.sum():,} measured picks.")


if __name__=="__main__":
    main()
