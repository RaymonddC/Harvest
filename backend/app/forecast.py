"""Weekly supply forecast, gaps and the pull-forward shortlist. Pure functions."""

from __future__ import annotations

import datetime as dt
from typing import Iterable

ACTIVE_OFFER_STATUSES = {"pending", "approved"}
UNSURE_WEIGHT = 0.5  # an unsure answer counts for half


def week_index(ready_date: str | dt.date, plan_start: dt.date, weeks: int) -> int | None:
    """1-based week of the planning horizon, or None when outside it."""
    if isinstance(ready_date, str):
        try:
            ready_date = dt.date.fromisoformat(ready_date[:10])
        except ValueError:
            return None
    delta = (ready_date - plan_start).days
    if delta < 0:
        return None
    index = delta // 7 + 1
    return index if index <= weeks else None


def week_label(index: int) -> str:
    return f"W{index}"


def week_start(index: int, plan_start: dt.date) -> dt.date:
    return plan_start + dt.timedelta(days=7 * (index - 1))


def is_unsure(harvest: dict) -> bool:
    return harvest.get("confidence") == "unsure"


def harvest_weight(harvest: dict) -> float:
    return UNSURE_WEIGHT if is_unsure(harvest) else 1.0


def compute_forecast(
    harvests: Iterable[dict],
    offers: Iterable[dict],
    plan_start: dt.date,
    weeks: int,
    target_kg: int,
    tolerance: float,
) -> list[dict]:
    span = range(1, weeks + 1)
    firm = {i: 0.0 for i in span}
    unsure = {i: 0.0 for i in span}  # already weighted
    unsure_count = {i: 0 for i in span}
    farmers = {i: 0 for i in span}
    moved = {i: 0.0 for i in span}  # approved offers in (+) and out (-)
    pending = {i: 0.0 for i in span}

    for h in harvests:
        w = week_index(h.get("ready_date", ""), plan_start, weeks)
        if not w:
            continue
        kg = float(h.get("kg", 0))
        farmers[w] += 1
        if is_unsure(h):
            unsure[w] += kg * UNSURE_WEIGHT
            unsure_count[w] += 1
        else:
            firm[w] += kg

    for o in offers:
        status = o.get("status")
        kg = float(o.get("kg", 0))
        to_w, from_w = o.get("deliver_week"), o.get("from_week")
        if status == "approved":
            if to_w in moved:
                moved[to_w] += kg
            if from_w in moved:
                moved[from_w] -= kg
        elif status == "pending" and to_w in pending:
            pending[to_w] += kg

    rows = []
    for i in span:
        exp = max(firm[i] + unsure[i] + moved[i], 0.0)
        rows.append({
            "id": week_label(i),
            "week": i,
            "label": week_label(i),
            "week_start": week_start(i, plan_start).isoformat(),
            "expected_kg": round(exp),
            "firm_kg": round(firm[i]),
            "unsure_weighted_kg": round(unsure[i]),
            "unsure_count": unsure_count[i],
            "approved_in_kg": round(max(moved[i], 0)),
            "pending_kg": round(pending[i]),
            "target_kg": target_kg,
            "gap_kg": round(max(target_kg - exp, 0)),
            "is_gap": exp < target_kg * (1 - tolerance),
            "harvest_count": farmers[i],
        })
    return rows


def shortlist(
    gap_week: int,
    farmers: Iterable[dict],
    harvests: Iterable[dict],
    offers: Iterable[dict],
    plan_start: dt.date,
    weeks: int,
    lookahead: int = 2,
    limit: int = 60,
) -> list[dict]:
    """Farmers who can pull a later harvest forward into the gap week, largest first."""
    farmers_by_id = {f["id"]: f for f in farmers}
    busy = {o.get("harvest_id") for o in offers
            if o.get("status") in ACTIVE_OFFER_STATUSES and o.get("harvest_id")}

    picks = []
    for h in harvests:
        farmer = farmers_by_id.get(h.get("farmer_id"))
        if not farmer or not farmer.get("can_pull_forward") or farmer.get("type") == "supplier":
            continue
        w = week_index(h.get("ready_date", ""), plan_start, weeks)
        if not w or not gap_week < w <= gap_week + lookahead or h["id"] in busy:
            continue
        picks.append({
            "farmer_id": farmer["id"],
            "name": farmer.get("name", farmer["id"]),
            "village": farmer.get("village", ""),
            "harvest_id": h["id"],
            "crop": h.get("crop"),
            "kg": round(float(h.get("kg", 0))),
            "from_week": w,
        })
    picks.sort(key=lambda p: (-p["kg"], p["from_week"], p["farmer_id"]))
    return picks[:limit]


def gap_reasons(gap_week: int, harvests: Iterable[dict], plan_start: dt.date, weeks: int) -> dict:
    """Facts behind a short week, for the planner's note."""
    harvests = list(harvests)
    in_week = [h for h in harvests if week_index(h.get("ready_date", ""), plan_start, weeks) == gap_week]
    next_week = [h for h in harvests if week_index(h.get("ready_date", ""), plan_start, weeks) == gap_week + 1]
    return {
        "farmers_in_week": len(in_week),
        "unsure_in_week": sum(1 for h in in_week if is_unsure(h)),
        "farmers_next_week": len(next_week),
        "moved_out": sum(1 for h in next_week if h.get("moved_from_week") == gap_week),
        "moved_reasons": sorted({h["note"] for h in next_week
                                 if h.get("moved_from_week") == gap_week and h.get("note")}),
    }
