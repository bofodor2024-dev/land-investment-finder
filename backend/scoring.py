from __future__ import annotations

from statistics import mean

from config import MAX_PLAUSIBLE_PRICE_PER_DONUM, SCORE_WEIGHTS, TAPU_HARD_CAP
from roi import estimate_olive_roi


# Three levels of comparison group, most specific first. A single-listing
# group (itself, no real comparable) isn't useful for "how does this price
# compare" — falling back to a broader level beats defaulting to a flat,
# uninformative 50 just because nothing else matching (province, land_type)
# has been captured yet (the exact gap that hid how cheap a genuinely good
# deal was, since it was the only "Manisa raw_land" listing captured).
_GROUP_LEVELS = [
    ("type", lambda l: (l.get("province"), l.get("land_type"))),
    ("province", lambda l: (l.get("province"),)),
    ("overall", lambda l: ("all",)),
]


def compute_group_averages(listings: list[dict]) -> dict:
    """Returns {level_name: {key: [price_per_donum, ...]}} for all three
    levels — not yet averaged, so score_listing can check each level's
    sample size before trusting it."""
    result = {name: {} for name, _ in _GROUP_LEVELS}
    for l in listings:
        if not l.get("size_donum") or not l.get("price"):
            continue
        price_per_donum = l["price"] / l["size_donum"]
        # A single data-entry error (wrong size/price on the seller's own
        # listing) shouldn't drag every OTHER listing sharing its group
        # into a distorted comparison — see MAX_PLAUSIBLE_PRICE_PER_DONUM.
        if price_per_donum > MAX_PLAUSIBLE_PRICE_PER_DONUM:
            continue
        for name, key_fn in _GROUP_LEVELS:
            result[name].setdefault(key_fn(l), []).append(price_per_donum)
    return result


def _comparable_average(listing: dict, group_lists: dict) -> tuple[float | None, str | None]:
    """First level with at least 2 entries (itself + one real comparable —
    a group of 1 is just the listing being scored, comparing against itself
    would trivially land at the neutral midpoint every time)."""
    for level, key_fn in _GROUP_LEVELS:
        bucket = group_lists.get(level, {}).get(key_fn(listing))
        if bucket and len(bucket) >= 2:
            return mean(bucket), level
    return None, None


def score_listing(listing: dict, group_averages: dict, settings: dict) -> dict:
    breakdown = {}
    red_flags = []

    # --- value: price/donum vs comparable group average (lower is better) ---
    value_score = 50.0
    price_per_donum = None
    value_comparison_note = None
    if listing.get("size_donum") and listing.get("price"):
        price_per_donum = listing["price"] / listing["size_donum"]
        if price_per_donum > MAX_PLAUSIBLE_PRICE_PER_DONUM:
            red_flags.append(
                f"Price/dönüm ({price_per_donum:,.0f} TRY) is implausibly high — "
                "likely a size or price data-entry error on the listing itself. "
                "Verify size/price directly before trusting this listing's numbers."
            )
        else:
            avg, comparison_level = _comparable_average(listing, group_averages)
            if avg:
                ratio = price_per_donum / avg
                # 30% below average -> ~100, at average -> 50, 50% above -> ~0
                value_score = max(0.0, min(100.0, 50 + (1 - ratio) * 150))
                if comparison_level != "type":
                    value_comparison_note = (
                        "vs. all captured land in " + str(listing.get("province"))
                        if comparison_level == "province"
                        else "vs. all captured listings (no comparable in its own province/type yet)"
                    )
    breakdown["value"] = round(value_score, 1)

    # --- maturity: existing productive orchard scores higher than raw land ---
    land_type = listing.get("land_type")
    if land_type == "existing_orchard":
        maturity_score = 70.0
        if listing.get("tree_age_years"):
            maturity_score += min(30.0, listing["tree_age_years"])
    elif land_type == "mixed":
        maturity_score = 55.0
    elif land_type == "raw_land":
        maturity_score = 35.0
    else:
        maturity_score = 30.0
    breakdown["maturity"] = round(min(100.0, maturity_score), 1)

    # --- irrigation ---
    irrigation = (listing.get("irrigation") or "unknown").lower()
    if irrigation in ("var", "kuyu", "artezyen"):
        irrigation_score = 100.0
    elif irrigation == "yok":
        irrigation_score = 10.0
        red_flags.append("No irrigation access noted")
    else:
        irrigation_score = 40.0
    breakdown["irrigation"] = irrigation_score

    # --- tapu / legal cleanliness ---
    tapu = (listing.get("tapu_status") or "unknown").lower()
    tapu_score = 50.0
    if tapu == "mustakil":
        tapu_score = 100.0
    elif tapu == "hisseli":
        tapu_score = 20.0
        red_flags.append("Shared (hisseli) title deed")
    elif tapu == "none":
        tapu_score = 0.0
        red_flags.append(
            "No title deed record (Tapu Kaydı Yok) — often unregistered "
            "forest/treasury/pasture land sold on possession, not real "
            "ownership. Get legal counsel before proceeding."
        )
    if listing.get("has_lien"):
        tapu_score = min(tapu_score, 5.0)
        red_flags.append("Lien/mortgage flagged on listing (ipotek/haciz)")
    breakdown["tapu"] = round(tapu_score, 1)

    # --- access: road + electricity ---
    access_score = 30.0
    if listing.get("road_access"):
        access_score += 40.0
    if listing.get("electricity"):
        access_score += 30.0
    breakdown["access"] = round(min(100.0, access_score), 1)

    composite = sum(breakdown[k] * SCORE_WEIGHTS[k] for k in SCORE_WEIGHTS)

    if (tapu == "none" or listing.get("has_lien")) and composite > TAPU_HARD_CAP:
        red_flags.append(
            f"Score capped at {TAPU_HARD_CAP:.0f} due to serious tapu/legal "
            f"risk (would otherwise be {composite:.1f})"
        )
        composite = TAPU_HARD_CAP

    return {
        "composite": round(composite, 1),
        "breakdown": breakdown,
        "red_flags": red_flags,
        "price_per_donum": round(price_per_donum, 1) if price_per_donum is not None else None,
        "value_comparison_note": value_comparison_note,
        "roi": estimate_olive_roi(listing, settings),
    }


def _apply_tree_overrides(listing: dict) -> dict:
    """tree_count_override/tree_age_years_override are set manually when a
    listing's photos clearly show an established grove but the seller's
    text never states a count/age. Preferred over the extracted value
    whenever present; survive /api/reprocess untouched (see db.py)."""
    resolved = dict(listing)
    if listing.get("tree_count_override") is not None:
        resolved["tree_count"] = listing["tree_count_override"]
    if listing.get("tree_age_years_override") is not None:
        resolved["tree_age_years"] = listing["tree_age_years_override"]
    return resolved


def score_all(listings: list[dict], settings: dict) -> list[dict]:
    averages = compute_group_averages(listings)
    scored = []
    for l in listings:
        resolved = _apply_tree_overrides(l)
        result = score_listing(resolved, averages, settings)
        scored.append({**resolved, **result})
    scored.sort(key=lambda x: x["composite"], reverse=True)
    return scored
