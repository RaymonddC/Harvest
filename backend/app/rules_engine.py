"""Price rules. Floor, ceiling and the offer ladder live here, in code, not in the prompt.

The model never picks a price. It asks check_offer, which answers with the only
price it may say next. save_offer then refuses any price check_offer did not hand out.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

MAX_OFFER_KG = 200_000

CROP_ALIASES = {
    "palm": "palm", "palm ffb": "palm", "palm oil": "palm", "oil palm": "palm", "ffb": "palm",
    "fresh fruit bunches": "palm", "fresh fruit bunch": "palm", "sawit": "palm",
    "kelapa sawit": "palm", "tbs": "palm", "tandan buah segar": "palm", "buah sawit": "palm",
    "rubber": "rubber", "karet": "rubber", "latex": "rubber", "getah": "rubber",
    "coffee": "coffee", "kopi": "coffee",
}
CROP_LABELS = {"palm": "Palm FFB", "rubber": "Rubber", "coffee": "Coffee"}


def normalize_crop(crop: str) -> str:
    key = " ".join((crop or "").strip().lower().replace("_", " ").split())
    return CROP_ALIASES.get(key, key)


def crop_label(crop: str) -> str:
    return CROP_LABELS.get(crop, crop.title())


class LimitsError(ValueError):
    pass


@dataclass(frozen=True)
class Limits:
    crop: str
    floor: float
    ceiling: float
    reference: float
    currency: str = "IDR"
    unit: str = "kg"
    first_premium_pct: float = 4.0
    step_pct: float = 2.0
    increment: float = 10.0  # prices are rounded to this unit (10 rupiah, or 0.01 baht)

    def validate(self) -> "Limits":
        if self.floor <= 0:
            raise LimitsError("Floor price must be above zero.")
        if not self.floor <= self.reference <= self.ceiling:
            raise LimitsError("Prices must satisfy floor <= reference <= ceiling.")
        if self.first_premium_pct < 0 or self.step_pct <= 0:
            raise LimitsError("Premium must be zero or more and the step above zero.")
        if self.increment <= 0:
            raise LimitsError("Price increment must be above zero.")
        return self

    @classmethod
    def from_doc(cls, doc: dict) -> "Limits":
        return cls(
            crop=doc["crop"],
            floor=float(doc["floor_price"]),
            ceiling=float(doc["ceiling_price"]),
            reference=float(doc["reference_price"]),
            currency=doc.get("currency", "IDR"),
            unit=doc.get("unit", "kg"),
            first_premium_pct=float(doc.get("first_premium_pct", 4.0)),
            step_pct=float(doc.get("step_pct", 2.0)),
            increment=float(doc.get("price_increment", 10.0)),
        ).validate()

    def to_doc(self) -> dict:
        return {
            "crop": self.crop,
            "floor_price": self.floor,
            "ceiling_price": self.ceiling,
            "reference_price": self.reference,
            "currency": self.currency,
            "unit": self.unit,
            "first_premium_pct": self.first_premium_pct,
            "step_pct": self.step_pct,
            "price_increment": self.increment,
        }

    def within(self, price: float) -> bool:
        return self.floor - 1e-9 <= price <= self.ceiling + 1e-9

    def round(self, price: float) -> float:
        return round(round(price / self.increment + 1e-9) * self.increment, 2)


def offer_ladder(limits: Limits) -> list[float]:
    """Rungs from reference plus the first premium, in fixed steps, ending at the ceiling."""
    step = limits.reference * limits.step_pct / 100
    price = limits.reference * (1 + limits.first_premium_pct / 100)
    rungs: list[float] = []
    while limits.round(price) < limits.ceiling - 1e-9:
        rung = max(limits.round(price), limits.floor)
        if not rungs or rung > rungs[-1]:
            rungs.append(rung)
        price += step
    rungs.append(round(limits.ceiling, 2))
    return rungs


def premium_pct(limits: Limits, price: float) -> float:
    return round((price - limits.reference) / limits.reference * 100, 1)


@dataclass(frozen=True)
class OfferDecision:
    decision: str  # "offer", "accept", "escalate", "invalid"
    allowed: bool  # True when `price` is what the farmer asked for (or the next rung) and may be agreed
    price: float | None  # the price the agent may say
    rung_index: int  # ladder position after this decision
    at_ceiling: bool
    premium_pct: float | None
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def check_offer(
    limits: Limits,
    rung_index: int,
    kg: float,
    counter_price: float | None = None,
) -> OfferDecision:
    """Decide the next price.

    rung_index is the last ladder rung already offered on this call (-1 for none).
    Without a counter, the next rung is offered (the first offer is reference plus a
    small premium). A counter inside the floor and ceiling may be accepted. A counter
    below the floor is raised to the floor. Above the ceiling the agent may offer the
    ceiling as its best price, for less volume, or hand the request to the planner.
    """
    ladder = offer_ladder(limits)
    last = len(ladder) - 1

    if kg is None or kg <= 0 or kg > MAX_OFFER_KG:
        return OfferDecision("invalid", False, None, rung_index, False, None,
                             f"Volume must be between 1 and {MAX_OFFER_KG} kg.")

    if counter_price is None:
        next_index = min(rung_index + 1, last)
        price = ladder[next_index]
        return OfferDecision("offer", True, price, next_index, next_index == last,
                             premium_pct(limits, price),
                             "First offer." if next_index == 0 else "Next step of the offer ladder.")

    if counter_price <= 0:
        return OfferDecision("invalid", False, None, rung_index, False, None,
                             "Counter price must be above zero.")

    if counter_price < limits.floor:
        # Fair-price floor: never buy below it, even if the farmer asks for less.
        price = round(limits.floor, 2)
        return OfferDecision("accept", True, price, rung_index, False, premium_pct(limits, price),
                             "Counter is below the floor price; pay the floor price instead.")

    if counter_price <= limits.ceiling + 1e-9:
        price = round(counter_price, 2)
        return OfferDecision("accept", True, price, rung_index, price >= limits.ceiling - 1e-9,
                             premium_pct(limits, price),
                             "Counter is inside the limits, so the agent may accept it.")

    return OfferDecision("escalate", False, round(limits.ceiling, 2), last, True,
                         premium_pct(limits, limits.ceiling),
                         "Counter is above the ceiling. Offer the best price returned here, or a smaller "
                         "volume at it, or hand the request to the planner.")
