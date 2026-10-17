"""BigQuery export: the snapshot rows (no personal data), the load per table, and the ML forecast written back."""

import dataclasses
import types as pytypes

from app import bq_export


def test_rows_keep_only_the_columns_and_no_names_or_phones(store):
    out = bq_export.rows(store)
    assert set(out) == set(bq_export.TABLES)
    f = out["farmers"][0]
    assert "name" not in f and "phone" not in f and set(f) == {n for n, _ in bq_export.TABLES["farmers"]}
    assert len(out["deliveries"]) == len(store.list("deliveries")) and isinstance(out["deliveries"][0]["net_kg"], float)


def test_off_without_a_dataset(store, settings):
    assert "skipped" in bq_export.export(store, settings)


class FakeBQ:
    project = "proj"

    def __init__(self):
        self.loaded, self.queries = {}, []

    def create_dataset(self, ds, exists_ok=False):
        self.ds = ds

    def load_table_from_json(self, data, table, job_config=None):
        self.loaded[table.split(".")[-1]] = len(data)
        return pytypes.SimpleNamespace(result=lambda: None)

    def query(self, sql):
        self.queries.append(sql)
        rows = [] if "CREATE" in sql else [{"crop": "palm", "day": "2026-10-20", "kg": 6100.4, "low": 4000.0, "high": 8000.0}]
        return pytypes.SimpleNamespace(result=lambda: rows)


def test_export_loads_every_table_and_saves_the_ml_forecast(store, settings):
    s = dataclasses.replace(settings, bigquery_dataset="harvest")
    bq = FakeBQ()
    out = bq_export.export(store, s, client=bq)
    assert set(bq.loaded) == set(bq_export.TABLES) and bq.loaded["deliveries"] == len(store.list("deliveries"))
    assert "ARIMA_PLUS" in bq.queries[0] and out["ml_forecast"]["days"] == 1
    assert store.get("ml_forecast", "palm-2026-10-20")["kg"] == 6100
