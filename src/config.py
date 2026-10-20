"""Validated settings from environment, .env and Streamlit secrets."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
import json
import os
import re
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ZONE = "Europe/Bratislava"
ALLOWED_JOB_TYPES = ("Expedícia - Standard", "Distribúcia - LC", "Distribúcia - POB")
FLAT_COLUMNS: dict[str, str | None] = {
    "id": "JobLine_ID", "created": "Created_At", "picked": "Picked_At",
    "collection": "Collection_At", "branch": "Branch_ID", "store": "Store_ID",
    "job_type": "Job_Type", "version": "load_timestamp",
}
JOINED_COLUMNS = {**FLAT_COLUMNS, "id": "StoreJobLine_ID", "created": "Created",
                  "picked": "PickedDate", "collection": "DepartureLimitTime"}
COLUMN_ENV = {
    "id": "JOBLINE_ID_COLUMN", "created": "CREATED_TIME_COLUMN",
    "picked": "PICKED_TIME_COLUMN", "collection": "COLLECTION_TIME_COLUMN",
    "branch": "BRANCH_ID_COLUMN", "store": "STORE_ID_COLUMN",
    "job_type": "JOB_TYPE_COLUMN", "version": "VERSION_COLUMN",
}


@dataclass(frozen=True)
class BigQueryConfig:
    billing_project: str = "d-log-bi-common"
    source_project: str = "p-plat-datadf-l1st"
    dataset: str = "L1_LogisticsViews"
    table: str = "v_StoreJobLines"
    location: str = "europe-west4"
    mode: str = "joined"
    jobs_table: str = "v_StoreJobs"
    states_table: str = "v_StoreJobLineStates"
    stores_table: str = "v_Stores"
    branch_id: str = "6281"
    store_pattern: str = "%SKLC3%"
    allowed_job_types: tuple[str, ...] = ALLOWED_JOB_TYPES
    timezone: str = ZONE
    default_logistic_start_time: str = "06:00"
    columns: dict[str, str | None] = field(default_factory=lambda: JOINED_COLUMNS.copy())

    def validate(self) -> None:
        """Only identifiers enter SQL; all filter values remain query parameters."""
        if self.mode not in {"joined", "flat"}:
            raise ValueError("BQ_MODE musí byť joined alebo flat.")
        for value in [self.billing_project, self.source_project, self.dataset, self.table,
                      self.jobs_table, self.states_table, self.stores_table]:
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
                raise ValueError(f"Neplatný BigQuery identifikátor: {value!r}")
        if not isinstance(self.columns, dict) or set(self.columns) - set(FLAT_COLUMNS):
            raise ValueError("Neznáme mapovanie stĺpcov.")
        for value in self.columns.values():
            if value is not None and (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value)):
                raise ValueError(f"Neplatný názov stĺpca: {value!r}")
        required = ["id", "created", "collection"] + (["job_type"] if self.mode == "flat" else [])
        if any(not self.columns.get(key) for key in required):
            raise ValueError("Povinné mapovanie: id, created, collection a vo flat režime job_type.")
        if not (self.columns.get("branch") or self.columns.get("store")):
            raise ValueError("Pre filter SKLC3 treba branch alebo store.")
        if self.mode == "joined" and not self.columns.get("store"):
            raise ValueError("Joined režim potrebuje Store_ID pre spojenie na názov skladu.")
        if not self.allowed_job_types or any(not isinstance(v, str) or not v.strip() for v in self.allowed_job_types):
            raise ValueError("Vyber aspoň jeden povolený typ jobu.")
        ZoneInfo(self.timezone)
        start = time.fromisoformat(self.default_logistic_start_time)
        if start.minute or start.second:
            raise ValueError("Začiatok logistického dňa musí byť na celej hodine.")

    def table_path(self, table: str) -> str:
        self.validate()
        return f"`{self.source_project}.{self.dataset}.{table}`"


def load_config(secrets: Mapping[str, Any] | None = None) -> BigQueryConfig:
    """Environment/.env > secrets > defaults. Uppercase keys also work in secrets."""
    load_dotenv(override=False)
    section = dict((secrets or {}).get("bigquery", {}))
    defaults = BigQueryConfig()
    aliases = {"source_project": "GCP_PROJECT_ID", "billing_project": "BQ_BILLING_PROJECT",
               "timezone": "TIMEZONE", "default_logistic_start_time": "DEFAULT_LOGISTIC_START_TIME",
               "branch_id": "BRANCH_ID", "store_pattern": "STORE_PATTERN"}
    def setting(name: str, fallback: Any) -> Any:
        key = aliases.get(name, "BQ_" + name.upper())
        return os.getenv(key, section.get(key, section.get(name, fallback)))
    values = {name: setting(name, getattr(defaults, name)) for name in defaults.__dataclass_fields__
              if name not in {"columns", "allowed_job_types"}}
    columns = (JOINED_COLUMNS if values["mode"] == "joined" else FLAT_COLUMNS).copy()
    columns.update(section.get("columns", {}))
    for key, env in COLUMN_ENV.items():
        columns[key] = os.getenv(env, section.get(env, columns.get(key))) or None
    if os.getenv("BQ_COLUMN_MAP_JSON"):
        override = json.loads(os.environ["BQ_COLUMN_MAP_JSON"])
        if not isinstance(override, dict):
            raise ValueError("BQ_COLUMN_MAP_JSON musí byť JSON objekt.")
        columns.update(override)
    allowed = os.getenv("ALLOWED_JOB_TYPES", section.get("ALLOWED_JOB_TYPES", section.get("allowed_job_types", ALLOWED_JOB_TYPES)))
    if isinstance(allowed, str):
        allowed = [part.strip() for part in allowed.split(",") if part.strip()]
    values.update(columns=columns, allowed_job_types=tuple(allowed), branch_id=str(values["branch_id"]))
    result = BigQueryConfig(**values)
    result.validate()
    return result
