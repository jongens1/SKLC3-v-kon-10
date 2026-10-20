"""Environment and Streamlit secrets, without importing Streamlit into the model."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import re
from typing import Any, Mapping

from dotenv import load_dotenv

ZONE = "Europe/Bratislava"
DEFAULT_COLUMNS: dict[str, str | None] = {
    "id": "StoreJobLine_ID", "created": "Created", "picked": "PickedDate",
    "branch": "Branch_ID", "store": "Store_ID", "cutoff": "DepartureLimitTime",
    "version": "load_timestamp",
}


@dataclass(frozen=True)
class BigQueryConfig:
    billing_project: str = "d-log-bi-common"
    source_project: str = "p-plat-datadf-l1st"
    dataset: str = "L1_LogisticsViews"
    location: str = "europe-west4"
    mode: str = "joined"
    table: str = "v_StoreJobLines"
    jobs_table: str = "v_StoreJobs"
    states_table: str = "v_StoreJobLineStates"
    stores_table: str = "v_Stores"
    columns: dict[str, str | None] = field(default_factory=lambda: DEFAULT_COLUMNS.copy())

    def validate(self) -> None:
        if self.mode not in {"joined", "flat"}:
            raise ValueError("BQ_MODE musí byť joined alebo flat.")
        if not re.fullmatch(r"[a-z][a-z0-9-]{4,62}", self.billing_project):
            raise ValueError("Neplatný billing project.")
        for value in [self.source_project, self.dataset, self.table,
                      self.jobs_table, self.states_table, self.stores_table]:
            if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
                raise ValueError(f"Neplatný BigQuery identifikátor: {value!r}")
        for value in self.columns.values():
            if value and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
                raise ValueError(f"Neplatný názov stĺpca: {value!r}")
        if not self.columns.get("id") or not self.columns.get("created"):
            raise ValueError("Mapovanie id a created je povinné.")
        if self.mode == "flat" and not (self.columns.get("branch") or self.columns.get("store")):
            raise ValueError("Pre filter skladu treba branch alebo store.")

    def table_path(self, table: str) -> str:
        self.validate()
        return f"`{self.source_project}.{self.dataset}.{table}`"


def load_config(secrets: Mapping[str, Any] | None = None) -> BigQueryConfig:
    """Precedence: environment > Streamlit secrets > defaults."""
    load_dotenv(override=False)
    section = dict((secrets or {}).get("bigquery", {}))
    defaults = BigQueryConfig()
    values = {
        name: os.getenv("BQ_" + name.upper(), section.get(name, getattr(defaults, name)))
        for name in defaults.__dataclass_fields__ if name != "columns"
    }
    columns = {**DEFAULT_COLUMNS, **dict(section.get("columns", {}))}
    if os.getenv("BQ_COLUMN_MAP_JSON"):
        override = json.loads(os.environ["BQ_COLUMN_MAP_JSON"])
        if not isinstance(override, dict) or set(override) - set(DEFAULT_COLUMNS):
            raise ValueError("BQ_COLUMN_MAP_JSON obsahuje neznáme mapovanie.")
        columns.update(override)
    values["columns"] = {key: value or None for key, value in columns.items()}
    result = BigQueryConfig(**values)
    result.validate()
    return result
