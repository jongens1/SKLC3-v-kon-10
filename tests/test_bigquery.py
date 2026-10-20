from dataclasses import replace
from datetime import date
from types import SimpleNamespace
import pytest
from src.config import BigQueryConfig, FLAT_COLUMNS, load_config, ALLOWED_JOB_TYPES
from src.bigquery_client import build_query, query_parameters, load_joblines
from src.data_processing import operational_window


def test_sql_filters_collection_and_types_not_created():
    config = BigQueryConfig()
    sql = build_query(config)
    assert "collection_at >= @collection_start" in sql
    assert "collection_at < @collection_end" in sql
    assert "job_type IN UNNEST(@allowed_job_types)" in sql
    assert "created_at >=" not in sql and "created_at < @" not in sql
    assert "JobDirection_ID=-1" in sql
    assert "JobSubType_ID=6" not in sql
    assert sql.index("PARTITION BY StoreJob_ID") < sql.index("collection_at >=")


def test_array_parameter_and_billing_project():
    start, end = operational_window(date(2026, 10, 15))
    config = BigQueryConfig()
    params = {item["name"]: item for item in query_parameters(config, start, end)}
    assert params["allowed_job_types"]["parameterType"]["type"] == "ARRAY"
    assert [v["value"] for v in params["allowed_job_types"]["parameterValue"]["arrayValues"]] == list(ALLOWED_JOB_TYPES)
    assert params["store_pattern"]["parameterValue"]["value"] == "%SKLC3%"
    assert config.billing_project == "d-log-bi-common"


def test_flat_mapping_identifiers_and_optional_pick():
    config = replace(BigQueryConfig(), mode="flat", columns={**FLAT_COLUMNS, "picked": None, "version": None})
    sql = build_query(config)
    assert "l.`Collection_At`" in sql and "l.`Job_Type`" in sql
    assert "CAST(NULL AS TIMESTAMP) AS picked_at" in sql
    assert "id_occurrences" in sql
    with pytest.raises(ValueError):
        build_query(replace(config, table="table`; DROP TABLE x"))
    with pytest.raises(ValueError):
        build_query(replace(config, columns={**FLAT_COLUMNS, "collection": None}))


def test_environment_and_toml_configuration(monkeypatch):
    monkeypatch.setenv("BQ_MODE", "flat")
    monkeypatch.setenv("COLLECTION_TIME_COLUMN", "Dispatch_At")
    monkeypatch.setenv("ALLOWED_JOB_TYPES", "Expedícia - Standard,Distribúcia - LC")
    config = load_config({"bigquery": {"GCP_PROJECT_ID": "source-project", "JOB_TYPE_COLUMN": "Process_Type"}})
    assert config.source_project == "source-project"
    assert config.columns["collection"] == "Dispatch_At"
    assert config.columns["job_type"] == "Process_Type"
    assert len(config.allowed_job_types) == 2


def test_python_client_binds_array_and_never_sets_destination(monkeypatch):
    import src.bigquery_client as adapter
    captured = {}
    class Client:
        def query(self, sql, job_config, location):
            captured.update(sql=sql, job_config=job_config, location=location)
            return SimpleNamespace(result=lambda timeout: [], job_id="read-only-test", total_bytes_processed=0)
    monkeypatch.setattr(adapter, "make_client", lambda *a, **k: Client())
    start, end = operational_window(date(2026, 10, 15))
    _, provenance = load_joblines(BigQueryConfig(), start, end)
    assert captured["job_config"].destination is None
    parameters = captured["job_config"].to_api_repr()["query"]["queryParameters"]
    assert next(p for p in parameters if p["name"] == "allowed_job_types")["parameterType"]["type"] == "ARRAY"
    assert provenance["billing_project"] == "d-log-bi-common"
