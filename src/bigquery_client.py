"""Read-only BigQuery adapter. SQL values are bound parameters; identifiers validated."""
from __future__ import annotations

from typing import Any, Mapping, TYPE_CHECKING
import pandas as pd

from src.config import BigQueryConfig

if TYPE_CHECKING:
    from google.cloud import bigquery


def build_query(config: BigQueryConfig) -> str:
    """Latest full versions precede cohort selection; return weighted hourly groups."""
    config.validate()
    if config.mode == "joined":
        source = f"""
lines AS (
 SELECT StoreJobLine_ID, StoreJob_ID, Store_ID, Created
 FROM {config.table_path(config.table)}
 QUALIFY ROW_NUMBER() OVER(PARTITION BY StoreJobLine_ID ORDER BY load_timestamp DESC)=1
), jobs AS (
 SELECT StoreJob_ID, Branch_ID, DepartureLimitTime
 FROM {config.table_path(config.jobs_table)}
 QUALIFY ROW_NUMBER() OVER(PARTITION BY StoreJob_ID ORDER BY load_timestamp DESC)=1
), states AS (
 SELECT StoreJobLine_ID, PickedDate, StornoDate
 FROM {config.table_path(config.states_table)}
 QUALIFY ROW_NUMBER() OVER(PARTITION BY StoreJobLine_ID ORDER BY load_timestamp DESC)=1
), stores AS (
 SELECT Store_ID, Store
 FROM {config.table_path(config.stores_table)}
 QUALIFY ROW_NUMBER() OVER(PARTITION BY Store_ID ORDER BY load_timestamp DESC)=1
), canonical AS (
 SELECT l.StoreJobLine_ID AS jobline_id, l.Created AS created_at,
 s.PickedDate AS picked_at, j.DepartureLimitTime AS cutoff_at,
 CAST(j.Branch_ID AS STRING) AS branch_id, CAST(l.Store_ID AS STRING) AS store_id,
 st.Store AS store_name, s.StornoDate IS NOT NULL AS is_cancelled
 FROM lines l LEFT JOIN jobs j USING(StoreJob_ID)
 LEFT JOIN states s USING(StoreJobLine_ID) LEFT JOIN stores st USING(Store_ID)
)"""
    else:
        c = config.columns
        def col(key: str, sql_type: str) -> str:
            return f"CAST(`{c[key]}` AS {sql_type})" if c.get(key) else f"CAST(NULL AS {sql_type})"
        latest = (f"QUALIFY ROW_NUMBER() OVER(PARTITION BY `{c['id']}` "
                  f"ORDER BY `{c['version']}` DESC)=1") if c.get("version") else ""
        source = f"""
latest AS (SELECT * FROM {config.table_path(config.table)} {latest}),
canonical AS (
 SELECT {col('id', 'STRING')} AS jobline_id, {col('created', 'TIMESTAMP')} AS created_at,
 {col('picked', 'TIMESTAMP')} AS picked_at, {col('cutoff', 'TIMESTAMP')} AS cutoff_at,
 {col('branch', 'STRING')} AS branch_id, {col('store', 'STRING')} AS store_id,
 {col('store', 'STRING')} AS store_name, FALSE AS is_cancelled FROM latest
)"""
    return f"""WITH {source},
cohort AS (
 SELECT * FROM canonical
 WHERE created_at >= @start AND created_at < @end
 AND (branch_id = @branch_id OR STRPOS(UPPER(COALESCE(store_name, '')), @store_pattern) > 0
      OR STRPOS(UPPER(COALESCE(store_id, '')), @store_pattern) > 0)
), validated AS (
 SELECT *, COUNT(*) OVER(PARTITION BY jobline_id) AS id_occurrences FROM cohort
), buckets AS (
 SELECT store_id, TIMESTAMP_TRUNC(created_at,HOUR,@timezone) AS created_at,
 IF(created_at=TIMESTAMP_TRUNC(created_at,HOUR,@timezone),created_at,
    TIMESTAMP_ADD(TIMESTAMP_TRUNC(created_at,HOUR,@timezone),INTERVAL 1 HOUR)) AS ready_at,
 TIMESTAMP_TRUNC(picked_at,HOUR,@timezone) AS picked_at,
 cutoff_at, is_cancelled,
 jobline_id IS NULL OR id_occurrences > 1 AS invalid_id,
 picked_at < created_at AS invalid_order
 FROM validated
)
SELECT store_id, created_at, ready_at, picked_at, cutoff_at, is_cancelled,
 invalid_id, invalid_order, COUNT(*) AS jobline_count
FROM buckets GROUP BY 1,2,3,4,5,6,7,8
ORDER BY created_at, store_id"""


def query_parameters(start: pd.Timestamp, end: pd.Timestamp) -> list[dict[str, Any]]:
    """REST form shared by the connector audit and Python client."""
    return [
        {"name": "start", "parameterType": {"type": "TIMESTAMP"}, "parameterValue": {"value": start.isoformat()}},
        {"name": "end", "parameterType": {"type": "TIMESTAMP"}, "parameterValue": {"value": end.isoformat()}},
        {"name": "branch_id", "parameterType": {"type": "STRING"}, "parameterValue": {"value": "6281"}},
        {"name": "store_pattern", "parameterType": {"type": "STRING"}, "parameterValue": {"value": "SKLC3"}},
        {"name": "timezone", "parameterType": {"type": "STRING"}, "parameterValue": {"value": "Europe/Bratislava"}},
    ]


def make_client(config: BigQueryConfig, secrets: Mapping[str, Any] | None = None) -> "bigquery.Client":
    from google.cloud import bigquery
    from google.oauth2 import service_account

    credentials = None
    if secrets and secrets.get("gcp_service_account"):
        credentials = service_account.Credentials.from_service_account_info(
            dict(secrets["gcp_service_account"]),
            scopes=["https://www.googleapis.com/auth/bigquery"],
        )
    return bigquery.Client(project=config.billing_project, credentials=credentials,
                           location=config.location)


def load_joblines(config: BigQueryConfig, start: pd.Timestamp, end: pd.Timestamp,
                  secrets: Mapping[str, Any] | None = None) -> tuple[pd.DataFrame, dict]:
    """Only SELECT; no destination table, schema edits, DML or DDL."""
    from google.cloud import bigquery

    client = make_client(config, secrets)
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter(p["name"], p["parameterType"]["type"], p["parameterValue"]["value"])
        for p in query_parameters(start, end)
    ])
    job = client.query(build_query(config), job_config=job_config, location=config.location)
    rows = job.result(timeout=180)
    frame = pd.DataFrame([dict(row.items()) for row in rows])
    return frame, {"job_id": job.job_id, "billing_project": config.billing_project,
                   "bytes_processed": job.total_bytes_processed, "source": config.source_project,
                   "location": config.location}
