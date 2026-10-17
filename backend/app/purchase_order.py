"""Purchase orders as PDF files, from what the farmer agreed on the call.

- An approved offer gives a purchase order: quantity, agreed price per kg, total, delivery week.
- A call that only saved a harvest (no deal yet) gives a draft at today's reference price, marked as a draft:
  the price is indicative until a deal is approved.
The PO number is fixed for each offer or harvest, so downloading again gives the same number.
"""

from __future__ import annotations

import datetime as dt

from fpdf import FPDF

from . import forecast as fc
from . import services
from .config import Settings
from .rules_engine import crop_label
from .store import Store


class PurchaseOrderError(services.ServiceError):
    pass


def _txt(value) -> str:
    """The built-in PDF fonts only cover Latin-1: anything else becomes '?' instead of failing."""
    return str(value if value is not None else "").encode("latin-1", "replace").decode("latin-1")


def _money(amount: float, currency: str) -> str:
    if currency == "IDR":
        return "Rp " + f"{round(amount):,}".replace(",", ".")
    return f"{amount:,.2f} {currency}"


def _kg(kg: float) -> str:
    return f"{round(kg):,}".replace(",", ".") + " kg"


def _day(value) -> str:
    try:
        return dt.date.fromisoformat(str(value)[:10]).strftime("%d %B %Y")
    except ValueError:
        return "-"


def _number(prefix: str, created: str | None, ref: str) -> str:
    day = (created or "")[:10].replace("-", "") or dt.date.today().strftime("%Y%m%d")
    tail = "".join(ch for ch in ref.upper() if ch.isalnum())[-6:]
    return f"{prefix}-{day}-{tail}"


def for_offer(store: Store, settings: Settings, offer_id: str) -> tuple[str, bytes]:
    offer = store.get("offers", offer_id)
    if not offer:
        raise PurchaseOrderError("Offer not found.", status=404)
    if offer.get("status") != "approved":
        raise PurchaseOrderError("A purchase order is made once the offer is approved.")
    farmer = store.get("farmers", offer.get("farmer_id")) or {}
    week_start = offer.get("deliver_week_start") or (
        fc.week_start(int(offer["deliver_week"]), settings.plan_start).isoformat() if offer.get("deliver_week") else None)
    lines = {
        "number": _number("PO", offer.get("decided_at") or offer.get("created_at"), offer_id),
        "draft": False,
        "date": offer.get("decided_at") or offer.get("created_at"),
        "farmer": farmer, "farmer_name": offer.get("farmer_name") or farmer.get("name", ""),
        "village": offer.get("village") or farmer.get("village", ""),
        "crop": offer.get("crop"), "kg": float(offer.get("kg") or 0),
        "price": float(offer.get("price_per_kg") or 0), "currency": offer.get("currency", "IDR"),
        "reference": offer.get("reference_price"),
        "delivery": (f"Week from {_day(week_start)} to {_day(dt.date.fromisoformat(week_start) + dt.timedelta(days=6))}"
                     if week_start else "To be agreed"),
        "approved": f"{offer.get('decided_by') or 'Planner'}, {_day(offer.get('decided_at'))}",
        "voice": "Yes" if offer.get("confirmed_by_voice") else "Not yet (confirmation call waiting)",
        "source": "Rival supplier quote" if str(offer.get("source", "")).startswith("rival_quote")
                  else f"AI agent call {offer.get('call_id')}" if offer.get("call_id") else "Planner",
    }
    return f"{lines['number']}.pdf", _render(settings, lines)


def for_call(store: Store, settings: Settings, call_id: str) -> tuple[str, bytes]:
    """The purchase order of a finished call: its approved deal, else a draft from the harvest it saved."""
    call = store.get("calls", call_id)
    if not call:
        raise PurchaseOrderError("Call not found.", status=404)
    offers = [o for o in store.list("offers") if o.get("call_id") == call_id or o["id"] == call.get("offer_id")]
    approved = next((o for o in offers if o.get("status") == "approved"), None)
    if approved:
        return for_offer(store, settings, approved["id"])
    harvest = next((h for h in store.list("harvests") if h.get("call_id") == call_id), None)
    if not harvest:
        raise PurchaseOrderError("This call has no approved deal and saved no harvest, so there is nothing to order yet.")
    return for_harvest(store, settings, harvest)


def for_harvest(store: Store, settings: Settings, harvest: dict) -> tuple[str, bytes]:
    farmer = store.get("farmers", harvest.get("farmer_id")) or {}
    try:
        limits = services.get_limits(store, harvest.get("crop") or settings.demo_crop)
        price, currency = float(limits.reference), limits.currency
    except services.ServiceError:
        raise PurchaseOrderError("Set the price range for this crop first: the draft uses its reference price.") from None
    lines = {
        "number": _number("PO-DRAFT", harvest.get("updated_at"), harvest["id"]),
        "draft": True,
        "date": harvest.get("updated_at"),
        "farmer": farmer, "farmer_name": farmer.get("name", harvest.get("farmer_id", "")), "village": farmer.get("village", ""),
        "crop": harvest.get("crop"), "kg": float(harvest.get("kg") or 0), "price": price, "currency": currency,
        "reference": price,
        "delivery": f"Harvest ready {_day(harvest.get('ready_date'))}"
                    + (" (the farmer was unsure)" if harvest.get("confidence") == "unsure" else ""),
        "approved": "Not approved: draft",
        "voice": "Harvest confirmed on the call (read back)" if harvest.get("call_id") else "Entered by a planner",
        "source": f"AI agent call {harvest.get('call_id')}" if harvest.get("call_id") else "Planner",
    }
    return f"{lines['number']}.pdf", _render(settings, lines)


def for_delivery(store: Store, settings: Settings, delivery_id: str) -> tuple[str, bytes]:
    """Goods receipt and payment for one weighbridge delivery: gross weight, grading deductions, net weight, the
    price (from the purchase order it was matched to, else the reference price) and the amount to pay."""
    d = store.get("deliveries", delivery_id)
    if not d:
        raise PurchaseOrderError("Delivery not found.", status=404)
    farmer = store.get("farmers", d.get("farmer_id")) or {}
    cur = d.get("currency", "IDR")
    price = d.get("price_per_kg")
    number = _number("GR", d.get("recorded_at") or d.get("date"), delivery_id)
    pdf = FPDF(format="A4")
    pdf.add_page()
    pdf.set_margins(18, 18, 18)
    w = pdf.w - 36
    pdf.set_xy(18, 18)
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*LEAF)
    pdf.cell(w / 2, 9, _txt(settings.mill_name))
    pdf.set_font("Helvetica", "B", 15)
    pdf.set_text_color(*INK)
    pdf.cell(w / 2, 9, "GOODS RECEIPT AND PAYMENT", align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*MUTED)
    pdf.cell(w / 2, 6, "Weighbridge")
    pdf.cell(w / 2, 6, _txt(f"No. {number}"), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(w / 2, 6, "")
    pdf.cell(w / 2, 6, _txt(f"Delivered: {_day(d.get('date'))}"), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_draw_color(*LINE)
    pdf.line(18, pdf.get_y(), 18 + w, pdf.get_y())
    pdf.ln(6)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*MUTED)
    pdf.cell(w, 5, "SUPPLIER", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(*INK)
    pdf.cell(w, 7, _txt(d.get("farmer_name") or farmer.get("name", "")), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    plot = (f"Plot {farmer['plot_lat']}, {farmer['plot_lng']}" if farmer.get("plot_lat") is not None else "Plot not mapped")
    pdf.cell(w, 6, _txt(" | ".join(x for x in (farmer.get("village"), plot, farmer.get("certification")) if x)),
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    def row(label, value, bold=False):
        pdf.set_font("Helvetica", "B" if bold else "", 11)
        pdf.set_text_color(*(INK if bold else MUTED))
        pdf.cell(w * 0.6, 8, _txt(label), border="B")
        pdf.set_text_color(*INK)
        pdf.cell(w * 0.4, 8, _txt(value), border="B", align="R", new_x="LMARGIN", new_y="NEXT")

    crop = crop_label(d.get("crop") or settings.demo_crop)
    row(f"{crop}, gross weight", _kg(d.get("kg", 0)))
    names = {"unripe": "Unripe bunches", "dirt": "Dirt and trash", "other": "Other (stalks, water...)"}
    for k, pct in (d.get("deductions") or {}).items():
        row(f"Deduction: {names.get(k, k)} {pct:g}%", "- " + _kg(float(d.get("kg", 0)) * pct / 100))
    row("Net weight paid for", _kg(d.get("net_kg", d.get("kg", 0))), bold=True)
    row("Price per kg", _money(price, cur) if price is not None else "No price set")
    row("Amount to pay", _money(d["amount"], cur) if d.get("amount") is not None else "-", bold=True)
    pdf.ln(6)
    pdf.set_font("Helvetica", "", 10)
    if d.get("po_number"):
        ordered = d.get("ordered_kg") or 0
        received = sum(float(x.get("net_kg", x.get("kg", 0))) for x in store.list("deliveries") if x.get("offer_id") == d.get("offer_id"))
        text = (f"Matched to purchase order {d['po_number']}: ordered {_kg(ordered)}, received so far {_kg(received)} net"
                + (f" ({_kg(received - ordered)} over)." if received > ordered else
                   f" ({_kg(ordered - received)} still to come)." if received < ordered else " (complete)."))
    else:
        text = "No purchase order for this farmer and week: paid at the market reference price on the delivery day."
    pdf.multi_cell(w, 6, _txt(text), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(12)
    half = (w - 10) / 2
    y = pdf.get_y()
    pdf.set_draw_color(*INK)
    pdf.line(18, y, 18 + half, y)
    pdf.line(28 + half, y, 18 + w, y)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*MUTED)
    pdf.cell(half + 10, 6, _txt(f"Weighbridge, {settings.mill_name} (recorded by {d.get('recorded_by', 'Planner')})"))
    pdf.cell(half, 6, _txt(f"Supplier: {d.get('farmer_name', '')}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)
    pdf.set_font("Helvetica", "I", 8)
    pdf.multi_cell(w, 4.5, "Generated by Harvest-Call. Hackathon demo: synthetic data.", new_x="LMARGIN", new_y="NEXT")
    return f"{number}.pdf", bytes(pdf.output())


INK = (17, 24, 20)
MUTED = (100, 110, 104)
LEAF = (31, 122, 82)
AMBER = (176, 120, 20)
LINE = (220, 224, 221)


def _render(settings: Settings, p: dict) -> bytes:
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(True, margin=18)
    pdf.add_page()
    pdf.set_margins(18, 18, 18)
    w = pdf.w - 36

    # Header: the mill, the document and its number
    pdf.set_xy(18, 18)
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*LEAF)
    pdf.cell(w / 2, 9, _txt(settings.mill_name))
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(*INK)
    pdf.cell(w / 2, 9, "DRAFT PURCHASE ORDER" if p["draft"] else "PURCHASE ORDER", align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*MUTED)
    pdf.cell(w / 2, 6, "Buyer: the mill's procurement desk")
    pdf.cell(w / 2, 6, _txt(f"No. {p['number']}"), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(w / 2, 6, "")
    pdf.cell(w / 2, 6, _txt(f"Date: {_day(p['date'])}"), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_draw_color(*LINE)
    pdf.line(18, pdf.get_y(), 18 + w, pdf.get_y())
    pdf.ln(6)

    if p["draft"]:
        pdf.set_fill_color(253, 243, 222)
        pdf.set_text_color(*AMBER)
        pdf.set_font("Helvetica", "B", 10)
        pdf.multi_cell(w, 6, "Draft: the price is today's market reference price and is not agreed. The order is final "
                             "only after the planner approves a deal with this farmer.", fill=True, padding=3,
                       new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

    # Supplier
    pdf.set_text_color(*MUTED)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(w, 5, "SUPPLIER", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*INK)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(w, 7, _txt(p["farmer_name"]), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    farmer = p["farmer"]
    detail = " | ".join(x for x in (p["village"], farmer.get("language"),
                                    f"Farmer ID {farmer['id']}" if farmer.get("id") else None) if x)
    pdf.cell(w, 6, _txt(detail or "-"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    # The order line
    cols = [w * 0.34, w * 0.18, w * 0.22, w * 0.26]
    pdf.set_fill_color(240, 244, 241)
    pdf.set_font("Helvetica", "B", 10)
    for text, cw, align in zip(("Item", "Quantity", "Price per kg", "Total"), cols, ("L", "R", "R", "R")):
        pdf.cell(cw, 9, text, border="B", align=align, fill=True)
    pdf.ln()
    pdf.set_font("Helvetica", "", 11)
    total = p["kg"] * p["price"]
    item = f"{crop_label(p['crop'] or settings.demo_crop)}"
    for text, cw, align in zip((item, _kg(p["kg"]), _money(p["price"], p["currency"]), _money(total, p["currency"])),
                               cols, ("L", "R", "R", "R")):
        pdf.cell(cw, 10, _txt(text), border="B", align=align)
    pdf.ln()
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(sum(cols[:3]), 11, "Total" + (" (indicative)" if p["draft"] else ""), align="R")
    pdf.cell(cols[3], 11, _txt(_money(total, p["currency"])), align="R", new_x="LMARGIN", new_y="NEXT")
    if p.get("reference") and not p["draft"] and p["price"] != p["reference"]:
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*MUTED)
        pct = (p["price"] - p["reference"]) / p["reference"] * 100
        pdf.cell(w, 5, _txt(f"Market reference price {_money(p['reference'], p['currency'])} per kg; this price is "
                            f"{pct:+.1f}% against it."), align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(*INK)
    pdf.ln(6)

    # Terms
    rows = [
        ("Delivery", p["delivery"]),
        ("Deliver to", f"{settings.mill_name} weighbridge"),
        ("Payment", "On the weight recorded at the mill weighbridge, at the price above"),
        ("Approved by", p["approved"]),
        ("Farmer confirmed", p["voice"]),
        ("Source", p["source"]),
    ]
    for label, value in rows:
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*MUTED)
        pdf.cell(42, 7, label)
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(*INK)
        pdf.multi_cell(w - 42, 7, _txt(value), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(14)

    # Signatures
    half = (w - 10) / 2
    y = pdf.get_y()
    pdf.set_draw_color(*INK)
    pdf.line(18, y, 18 + half, y)
    pdf.line(28 + half, y, 18 + w, y)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*MUTED)
    pdf.cell(half + 10, 6, _txt(f"For {settings.mill_name}"))
    pdf.cell(half, 6, _txt(f"Supplier: {p['farmer_name']}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(10)
    pdf.set_font("Helvetica", "I", 8)
    pdf.multi_cell(w, 4.5, "Generated by Harvest-Call from the AI agent's call record. Prices come only from the mill's "
                           "approved price range. Hackathon demo: synthetic data.", new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
