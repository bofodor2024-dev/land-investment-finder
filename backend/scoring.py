from __future__ import annotations

from statistics import mean

from config import SCORE_WEIGHTS


def _group_key(listing: dict) -> tuple:
    return (listing.get("province"), listing.get("land_type"))


def compute_group_averages(listings: list[dict]) -> dict:
    groups: dict[tuple, list[float]] = {}
    for l in listings:
        if l.get("size_donum") and l.get("price"):
            price_per_donum = l["price"] / l["size_donum"]
            groups.setdefault(_group_key(l), []).append(price_per_donum)
    return {k: mean(v) for k, v in groups.items() if v}


def score_listing(listing: dict, group_averages: dict) -> dict:
    breakdown = {}
    red_flags = []

    # --- value: price/donum vs comparable group average (lower is better) ---
    value_score = 50.0
    if listing.get("size_donum") and listing.get("price"):
        price_per_donum = listing["price"] / listing["size_donum"]
        avg = group_averages.get(_group_key(listing))
        if avg:
            ratio = price_per_donum / avg
            # 30% below average -> ~100, at average -> 50, 50% above -> ~0
            value_score = max(0.0, min(100.0, 50 + (1 - ratio) * 150))
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

    return {
        "composite": round(composite, 1),
        "breakdown": breakdown,
        "red_flags": red_flags,
    }


def score_all(listings: list[dict]) -> list[dict]:
    averages = compute_group_averages(listings)
    scored = []
    for l in listings:
        result = score_listing(l, averages)
        scored.append({**l, **result})
    scored.sort(key=lambda x: x["composite"], reverse=True)
    return scored
