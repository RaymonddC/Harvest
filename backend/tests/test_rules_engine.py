import pytest

from app.rules_engine import Limits, LimitsError, check_offer, normalize_crop, offer_ladder

LIMITS = Limits(crop="palm", floor=2900, ceiling=3350, reference=3100, currency="IDR",
                first_premium_pct=4.0, step_pct=2.0, increment=10)


def test_ladder_starts_above_reference_and_ends_at_ceiling():
    assert offer_ladder(LIMITS) == [3220.0, 3290.0, 3350.0]


def test_ladder_never_leaves_limits_and_rounds_to_increment():
    for ref in (2900, 3000, 3100, 3300, 3350):
        limits = Limits("palm", 2900, 3350, ref, increment=10).validate()
        ladder = offer_ladder(limits)
        assert ladder == sorted(set(ladder))
        assert all(limits.within(p) and p % 10 == 0 for p in ladder)


def test_cent_increment_for_baht():
    limits = Limits("rubber", 50, 60, 55, currency="THB", first_premium_pct=2, step_pct=2, increment=0.01)
    assert offer_ladder(limits) == [56.1, 57.2, 58.3, 59.4, 60.0]


@pytest.mark.parametrize("floor,ref,ceiling", [(0, 5, 10), (60, 55, 70), (50, 65, 60)])
def test_invalid_limits_rejected(floor, ref, ceiling):
    with pytest.raises(LimitsError):
        Limits("palm", floor, ceiling, ref).validate()


def test_first_offer_is_reference_plus_premium():
    d = check_offer(LIMITS, -1, 1600)
    assert d.decision == "offer" and d.allowed and d.price == 3220.0 and d.rung_index == 0


def test_offers_without_counter_climb_and_stop_at_ceiling():
    rung, prices = -1, []
    for _ in range(6):
        d = check_offer(LIMITS, rung, 1600)
        prices.append(d.price)
        rung = d.rung_index
    assert prices == [3220, 3290, 3350, 3350, 3350, 3350]


def test_counter_inside_limits_is_accepted():
    # The design's example: offer 3,220, farmer asks 3,300, inside the ceiling.
    d = check_offer(LIMITS, 0, 1600, counter_price=3300)
    assert d.decision == "accept" and d.allowed and d.price == 3300


def test_counter_above_ceiling_escalates_with_best_price():
    d = check_offer(LIMITS, 0, 1600, counter_price=3500)
    assert d.decision == "escalate" and not d.allowed and d.price == 3350 and d.at_ceiling


def test_counter_below_floor_pays_floor():
    d = check_offer(LIMITS, -1, 1600, counter_price=2500)
    assert d.decision == "accept" and d.price == 2900


@pytest.mark.parametrize("kg", [0, -5, 10_000_000])
def test_invalid_volume(kg):
    assert check_offer(LIMITS, -1, kg).decision == "invalid"


def test_no_decision_ever_gives_price_outside_limits():
    for rung in range(-1, 4):
        for counter in (None, 1, 2899, 2900, 3100, 3349, 3350, 3351, 9999):
            d = check_offer(LIMITS, rung, 1000, counter)
            if d.price is not None:
                assert LIMITS.within(d.price)


@pytest.mark.parametrize("spoken,canonical", [
    ("Palm FFB", "palm"), ("kelapa sawit", "palm"), ("TBS", "palm"), ("tandan buah segar", "palm"),
    ("karet", "rubber"), ("palm_ffb", "palm"), ("durian", "durian")])
def test_crop_aliases(spoken, canonical):
    assert normalize_crop(spoken) == canonical
