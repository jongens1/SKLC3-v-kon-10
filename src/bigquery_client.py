"""Read-only collection-day query adapter with bound values and safe identifiers."""
from __future__ import annotations

from typing import Any, Mapping, TYPE_CHECKING
import pandas as pd
from src.config import BigQueryConfig

if TYPE_CHECKING:
    from google.cloud import bigquery


def _canonical_source(config: BigQueryConfig) -> str:
    """Latest versions and the shared native process mapping."""
    config.validate()
    c = config.columns
    def col(alias: str, key: str, sql_type: str) -> str:
        return f"CAST({alias}.`{c[key]}` AS {sql_type})" if c.get(key) else f"CAST(NULL AS {sql_type})"
    if config.mode == "joined":
        version = c.get("version") or "load_timestamp"
        source = f"""
lines AS (
 SELECT * FROM {config.table_path(config.table)}
 QUALIFY ROW_NUMBER() OVER(PARTITION BY `{c['id']}` ORDER BY `{version}` DESC)=1
), jobs AS (
 SELECT * FROM {config.table_path(config.jobs_table)}
 QUALIFY ROW_NUMBER() OVER(PARTITION BY StoreJob_ID ORDER BY load_timestamp DESC)=1
), states AS (
 SELECT * FROM {config.table_path(config.states_table)}
 QUALIFY ROW_NUMBER() OVER(PARTITION BY StoreJobLine_ID ORDER BY load_timestamp DESC)=1
), stores AS (
 SELECT Store_ID, Store FROM {config.table_path(config.stores_table)}
 QUALIFY ROW_NUMBER() OVER(PARTITION BY Store_ID ORDER BY load_timestamp DESC)=1
), canonical AS (
 SELECT {col('l','id','STRING')} AS jobline_id,
 {col('l','created','TIMESTAMP')} AS created_at,
 {col('s','picked','TIMESTAMP')} AS picked_at,
 {col('j','collection','TIMESTAMP')} AS collection_at,
 {col('j','branch','STRING')} AS branch_id,
 {col('l','store','STRING')} AS store_id, st.Store AS store_name,
 CASE
   WHEN j.JobDirection_ID=-1 AND j.JobType_ID=1 AND j.JobSubType_ID=1 THEN 'Expedícia - Standard'
   WHEN j.JobDirection_ID=-1 AND j.JobType_ID=2 AND j.JobSubType_ID=7 THEN 'Distribúcia - LC'
   WHEN j.JobDirection_ID=-1 AND j.JobType_ID=2 AND j.JobSubType_ID=8 THEN 'Distribúcia - POB'
   ELSE 'Iný proces'
 END AS job_type, s.StornoDate IS NOT NULL AS is_cancelled
 FROM lines l LEFT JOIN jobs j USING(StoreJob_ID)
 LEFT JOIN states s ON l.`{c['id']}`=s.StoreJobLine_ID
 LEFT JOIN stores st ON l.`{c['store']}`=st.Store_ID
)"""
    else:
        latest = (f"QUALIFY ROW_NUMBER() OVER(PARTITION BY `{c['id']}` ORDER BY `{c['version']}` DESC)=1"
                  if c.get("version") else "")
        source = f"""
latest AS (SELECT * FROM {config.table_path(config.table)} {latest}),
canonical AS (
 SELECT {col('l','id','STRING')} AS jobline_id,
 {col('l','created','TIMESTAMP')} AS created_at,
 {col('l','picked','TIMESTAMP')} AS picked_at,
 {col('l','collection','TIMESTAMP')} AS collection_at,
 {col('l','branch','STRING')} AS branch_id,
 {col('l','store','STRING')} AS store_id,
 {col('l','store','STRING')} AS store_name,
 {col('l','job_type','STRING')} AS job_type, FALSE AS is_cancelled
 FROM latest l
)"""
    return source


def build_query(config: BigQueryConfig) -> str:
    """Select by COLLECTION time and process type; never restrict created time."""
    return f"""WITH {_canonical_source(config)}, cohort AS (
 SELECT * FROM canonical
 WHERE collection_at >= @collection_start AND collection_at < @collection_end
 AND (branch_id=@branch_id OR UPPER(COALESCE(store_name,'')) LIKE UPPER(@store_pattern)
      OR UPPER(COALESCE(store_id,'')) LIKE UPPER(@store_pattern))
 AND job_type IN UNNEST(@allowed_job_types)
), validated AS (
 SELECT *,COUNT(*) OVER(PARTITION BY jobline_id) AS id_occurrences FROM cohort
), buckets AS (
 SELECT store_id,branch_id,store_name,job_type,
 TIMESTAMP_TRUNC(created_at,HOUR,@timezone) AS created_at,
 IF(created_at=TIMESTAMP_TRUNC(created_at,HOUR,@timezone),created_at,
    TIMESTAMP_ADD(TIMESTAMP_TRUNC(created_at,HOUR,@timezone),INTERVAL 1 HOUR)) AS ready_at,
 TIMESTAMP_TRUNC(picked_at,HOUR,@timezone) AS picked_at,
 collection_at,is_cancelled,
 jobline_id IS NULL OR id_occurrences>1 AS invalid_id,
 COALESCE(picked_at<created_at,FALSE) AS invalid_order,
 created_at AS source_created_at,picked_at AS source_picked_at
 FROM validated
)
SELECT store_id,branch_id,store_name,job_type,created_at,ready_at,picked_at,
 collection_at,is_cancelled,invalid_id,invalid_order,COUNT(*) AS jobline_count,
 MIN(source_created_at) AS created_min,MAX(source_created_at) AS created_max,
 MIN(source_picked_at) AS picked_min,MAX(source_picked_at) AS picked_max
FROM buckets GROUP BY 1,2,3,4,5,6,7,8,9,10,11
ORDER BY collection_at,created_at,store_id"""


def build_actual_throughput_query(config: BigQueryConfig) -> str:
    """Observed warehouse picks in the day, including jobs for OTHER collection days."""
    return f"""WITH {_canonical_source(config)}, selected AS (
 SELECT *, COUNT(*) OVER(PARTITION BY jobline_id) AS id_occurrences
 FROM canonical
 WHERE picked_at >= @collection_start AND picked_at < @collection_end
 AND (branch_id=@branch_id OR UPPER(COALESCE(store_name,'')) LIKE UPPER(@store_pattern)
      OR UPPER(COALESCE(store_id,'')) LIKE UPPER(@store_pattern))
 AND job_type IN UNNEST(@allowed_job_types)
)
SELECT TIMESTAMP_TRUNC(picked_at,HOUR,@timezone) AS hour,job_type,
 COUNT(*) AS picked_count,COUNTIF(jobline_id IS NULL OR id_occurrences>1) AS invalid_ids
FROM selected GROUP BY 1,2 ORDER BY 1,2"""


def query_parameters(config: BigQueryConfig, start: pd.Timestamp, end: pd.Timestamp) -> list[dict[str, Any]]:
    """REST bindings also serve independent read-only connector verification."""
    scalar = {"collection_start": ("TIMESTAMP", start.isoformat()), "collection_end": ("TIMESTAMP", end.isoformat()),
              "branch_id": ("STRING", config.branch_id), "store_pattern": ("STRING", config.store_pattern),
              "timezone": ("STRING", config.timezone)}
    result = [{"name": key, "parameterType": {"type": kind}, "parameterValue": {"value": value}}
              for key, (kind, value) in scalar.items()]
    result.append({"name": "allowed_job_types", "parameterType": {"type": "ARRAY", "arrayType": {"type": "STRING"}},
                   "parameterValue": {"arrayValues": [{"value": value} for value in config.allowed_job_types]}})
    return result


def make_client(config: BigQueryConfig, secrets: Mapping[str, Any] | None = None) -> "bigquery.Client":
    from google.cloud import bigquery
    from google.oauth2 import service_account
    credentials = None
    if secrets and secrets.get("gcp_service_account"):
        credentials = service_account.Credentials.from_service_account_info(dict(secrets["gcp_service_account"]),
                         scopes=["https://www.googleapis.com/auth/bigquery"])
    return bigquery.Client(project=config.billing_project, credentials=credentials, location=config.location)


def _read_query(config: BigQueryConfig, start: pd.Timestamp, end: pd.Timestamp, query: str,
                secrets: Mapping[str, Any] | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    """SELECT only; latest versions before filters; no destination table or schema writes."""
    from google.cloud import bigquery
    parameters = []
    for item in query_parameters(config, start, end):
        kind = item["parameterType"]["type"]
        value = item["parameterValue"]
        if kind == "ARRAY":
            parameters.append(bigquery.ArrayQueryParameter(item["name"], "STRING", [v["value"] for v in value["arrayValues"]]))
        else:
            parameters.append(bigquery.ScalarQueryParameter(item["name"], kind, value["value"]))
    job = make_client(config, secrets).query(query,
                job_config=bigquery.QueryJobConfig(query_parameters=parameters), location=config.location)
    rows = job.result(timeout=180)
    data = pd.DataFrame([dict(row.items()) for row in rows])
    return data, {"job_id": job.job_id, "billing_project": config.billing_project,
                  "source_project": config.source_project, "location": config.location,
                  "bytes_processed": job.total_bytes_processed, "cohort_basis": "collection_at",
                  "allowed_job_types": list(config.allowed_job_types)}


def load_joblines(config: BigQueryConfig, start: pd.Timestamp, end: pd.Timestamp,
                  secrets: Mapping[str, Any] | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Offline preparation only; the Streamlit application never invokes this."""
    return _read_query(config,start,end,build_query(config),secrets)


def load_actual_throughput(config: BigQueryConfig, start: pd.Timestamp, end: pd.Timestamp,
                           secrets: Mapping[str, Any] | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    data,provenance = _read_query(config,start,end,build_actual_throughput_query(config),secrets)
    if len(data) and data.invalid_ids.sum():
        raise ValueError("Neunikátne ID v skutočnom výkone skladu.")
    provenance["cohort_basis"] = "picked_at"
    return data,provenance
