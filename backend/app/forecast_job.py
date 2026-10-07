"""Cloud Run job: recompute the weekly forecast from Firestore.

The service already recomputes after every saved harvest and every decision; the job
is the scheduled safety net (and the way to rebuild after editing data by hand).
"""

from __future__ import annotations

from . import services
from .config import get_settings
from .store import make_store


def main() -> None:
    settings = get_settings()
    store = make_store(settings.store_backend, settings.gcp_project)
    rows = services.recompute_forecast(store, settings)
    for r in rows:
        flag = "GAP" if r["is_gap"] else "ok"
        print(f"{r['label']} {r['week_start']} expected {r['expected_kg']} kg, "
              f"target {r['target_kg']} kg, {flag}")


if __name__ == "__main__":
    main()
