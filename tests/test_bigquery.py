from dataclasses import replace
from datetime import date
import pytest
from src.config import BigQueryConfig, load_config
from src.bigquery_client import build_query, query_parameters
from src.data_processing import operational_window


def test_joined_sql_contract_and_parameter_binding():
    config = BigQueryConfig()
    sql = build_query(config)
    assert "@start" in sql and "@end" in sql and "@branch_id" in sql and "@store_pattern" in sql
    assert "d-log-bi-common" not in sql
    assert "v_StoreJobs" in sql and "st.Store AS store_name" in sql
    assert sql.index("PARTITION BY StoreJob_ID") < sql.index("created_at >= @start")
    assert "DELETE " not in sql and "CREATE " not in sql
    start, end = operational_window(date(2026, 10, 15))
    params = {p["name"]: p["parameterValue"]["value"] for p in query_parameters(start, end)}
    assert params["branch_id"] == "6281" and params["timezone"] == "Europe/Bratislava"
    assert config.billing_project == "d-log-bi-common"


def test_flat_column_mapping_and_missing_optional_columns():
    config = replace(BigQueryConfig(), mode="flat", table="custom_joblines", columns={
        "id": "JobLine_ID", "created": "Created_At", "picked": None, "cutoff": None,
        "branch": "Branch_ID", "store": None, "version": None})
    sql = build_query(config)
    assert "`JobLine_ID`" in sql and "`Created_At`" in sql
    assert "CAST(NULL AS TIMESTAMP) AS cutoff_at" in sql
    assert "COUNT(*) OVER(PARTITION BY jobline_id)" in sql


def test_identifier_injection_is_rejected():
    for config in [replace(BigQueryConfig(), table="table`; DROP TABLE x"),
                   replace(BigQueryConfig(), columns={"id": "x`", "created": "Created"})]:
        with pytest.raises(ValueError):
            build_query(config)


def test_environment_overrides_secrets(monkeypatch):
    monkeypatch.setenv("BQ_BILLING_PROJECT", "d-log-bi-common")
    monkeypatch.setenv("BQ_COLUMN_MAP_JSON", '{"created":"CreationTime"}')
    config = load_config({"bigquery": {"billing_project": "another-project"}})
    assert config.billing_project == "d-log-bi-common"
    assert config.columns["created"] == "CreationTime"
