"""BigQuery: the mill's supply data for analysis (Looker Studio) and a statistical forecast (BigQuery ML).

Off until BIGQUERY_DATASET is set. Each run (the hourly job, or "Send to BigQuery" in the dashboard) replaces these
tables in the dataset with a snapshot of the store:
  farmers     id, village, crop, campaign, usual kg a week, plot area, certification, agent calls on
              (no names and no phone numbers: personal data stays in the app, PDP Law)
  calls       kind, channel, status, outcome, timings, consent, Gemini's sentiment and score
  harvests    the answers: kg, ready date, firm or unsure
  offers      deals: kg, price, status, delivery week, delivered kg
  deliveries  weighbridge: gross and net kg, grading, price, amount, paid
  forecast    each campaign week: expected, target, gap, capacity
Then BigQuery ML trains an ARIMA_PLUS model on daily net deliveries per crop and forecasts the next 35 days; the
forecast is written back to the store (collection ml_forecast) so the dashboard shows it next to the farmers' answers.
"""

from __future__ import annotations

import datetime as dt
import logging

from .config import Settings
from .store import Store

log = logging.getLogger(__name__)

HORIZON_DAYS = 35

S, F, I, B, D, T = "STRING", "FLOAT", "INTEGER", "BOOLEAN", "DATE", "TIMESTAMP"
TABLES = {
    "farmers": [("id", S), ("village", S), ("crop", S), ("campaign_id", S), ("usual_kg_week", F), ("plot_ha", F),
                ("certification", S), ("agent_calls", B), ("type", S)],
    "calls": [("id", S), ("farmer_id", S), ("campaign_id", S), ("kind", S), ("channel", S), ("status", S), ("outcome", S),
              ("attempt", I), ("created_at", T), ("started_at", T), ("ended_at", T), ("duration_s", F), ("consent", B),
              ("sentiment", S), ("sentiment_score", F)],
    "harvests": [("farmer_id", S), ("crop", S), ("kg", F), ("ready_date", D), ("confidence", S), ("every_days", F),
                 ("source", S), ("call_id", S), ("updated_at", T)],
    "offers": [("id", S), ("farmer_id", S), ("crop", S), ("kg", F), ("price_per_kg", F), ("currency", S), ("status", S),
               ("deliver_week_start", D), ("created_at", T), ("decided_at", T), ("delivered_kg", F)],
    "deliveries": [("id", S), ("farmer_id", S), ("crop", S), ("date", D), ("week_start", D), ("kg", F), ("net_kg", F),
                   ("deduction_pct", F), ("price_per_kg", F), ("amount", F), ("currency", S), ("offer_id", S), ("paid", B)],
    "forecast": [("campaign_id", S), ("crop", S), ("week", I), ("week_start", D), ("expected_kg", F), ("target_kg", F),
                 ("gap_kg", F), ("is_gap", B), ("capacity_kg", F)],
}


def _secs(a, b):
    try:
        return round((dt.datetime.fromisoformat(b) - dt.datetime.fromisoformat(a)).total_seconds(), 1)
    except (TypeError, ValueError):
        return None


def rows(store: Store) -> dict[str, list[dict]]:
    """The snapshot, one list of plain rows per table (only the columns above)."""
    calls = []
    for c in store.list("calls"):
        ins = c.get("insights") or {}
        calls.append({**c, "duration_s": _secs(c.get("started_at"), c.get("ended_at")),
                      "sentiment": ins.get("sentiment"), "sentiment_score": ins.get("score")})
    data = {"farmers": store.list("farmers"), "calls": calls, "harvests": store.list("harvests"),
            "offers": store.list("offers"), "deliveries": store.list("deliveries"), "forecast": store.list("forecast")}
    out = {}
    for table, cols in TABLES.items():
        keep = []
        for r in data[table]:
            row = {}
            for name, kind in cols:
                v = r.get(name)
                if v in ("", None):
                    v = None
                elif kind == F:
                    try:
                        v = float(v)
                    except (TypeError, ValueError):
                        v = None
                elif kind == I:
                    try:
                        v = int(v)
                    except (TypeError, ValueError):
                        v = None
                elif kind == B:
                    v = bool(v)
                elif kind == D:
                    v = str(v)[:10]
                else:
                    v = str(v)
                row[name] = v
            keep.append(row)
        out[table] = keep
    return out


def _client(settings: Settings):
    from google.cloud import bigquery

    return bigquery.Client(project=settings.gcp_project)


def export(store: Store, settings: Settings, client=None) -> dict:
    """Replace the dataset's tables with a snapshot, then refresh the BigQuery ML forecast. Returns counts."""
    if not settings.bigquery_dataset:
        return {"skipped": "BIGQUERY_DATASET is not set."}
    from google.cloud import bigquery

    client = client or _client(settings)
    ds_id = f"{client.project}.{settings.bigquery_dataset}"
    ds = bigquery.Dataset(ds_id)
    ds.location = settings.bigquery_location
    client.create_dataset(ds, exists_ok=True)
    counts = {}
    for table, cols in TABLES.items():
        data = rows(store)[table] if table not in counts else []
        job = client.load_table_from_json(data, f"{ds_id}.{table}", job_config=bigquery.LoadJobConfig(
            schema=[bigquery.SchemaField(n, k) for n, k in cols], write_disposition="WRITE_TRUNCATE"))
        job.result()
        counts[table] = len(data)
    out = {"dataset": ds_id, "tables": counts, "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    try:
        out["ml_forecast"] = ml_forecast(store, settings, client)
    except Exception as e:  # noqa: BLE001 - the export stands even if the model cannot train yet
        log.warning("BigQuery ML forecast failed", exc_info=True)
        out["ml_forecast"] = {"error": str(e)[:300]}
    store.set("campaigns", "current", {"bigquery_export": {k: v for k, v in out.items() if k != "ml_forecast"}}, merge=True)
    return out


def ml_forecast(store: Store, settings: Settings, client) -> dict:
    """Train ARIMA_PLUS on daily net deliveries per crop and save the next HORIZON_DAYS days in the store."""
    ds = f"`{client.project}.{settings.bigquery_dataset}`"
    client.query(f"""
        CREATE OR REPLACE MODEL {ds}.supply_arima
        OPTIONS(model_type = 'ARIMA_PLUS', time_series_timestamp_col = 'day', time_series_data_col = 'kg',
                time_series_id_col = 'crop', horizon = {HORIZON_DAYS}, auto_arima = TRUE, data_frequency = 'DAILY') AS
        SELECT date AS day, crop, SUM(net_kg) AS kg FROM {ds}.deliveries
        WHERE date IS NOT NULL AND net_kg IS NOT NULL GROUP BY day, crop""").result()
    result = client.query(f"""
        SELECT crop, DATE(forecast_timestamp) AS day, forecast_value AS kg,
               prediction_interval_lower_bound AS low, prediction_interval_upper_bound AS high
        FROM ML.FORECAST(MODEL {ds}.supply_arima, STRUCT({HORIZON_DAYS} AS horizon, 0.8 AS confidence_level))
        ORDER BY crop, day""").result()
    made = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    n = 0
    for old in store.list("ml_forecast"):
        store.delete("ml_forecast", old["id"])
    for r in result:
        store.set("ml_forecast", f"{r['crop']}-{r['day']}", {"crop": r["crop"], "day": str(r["day"]), "kg": max(0.0, round(float(r["kg"]))),
                                                              "low": max(0.0, round(float(r["low"]))), "high": round(float(r["high"])), "made_at": made})
        n += 1
    return {"days": n, "made_at": made}
