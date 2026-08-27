"""Multi-year payback estimate for olive land — both existing groves and
raw land you'd plant yourself.

Deliberately GROSS only: no ongoing operating costs (harvest labor,
pruning, pest control, transport, taxes) are netted out — only the
one-time planting/establishment cost for raw land, since that's needed
for a fair existing-orchard-vs-raw-land comparison. Not a full ROI or
financial projection — meant for comparing captured listings against
each other.

Price/cost assumptions live in the `settings` table (db.py
DEFAULT_SETTINGS), editable from the dashboard, not hardcoded here:

- olive_wholesale_price_try_per_kg: seeded at 150 TL/kg — the low end of a
  "150-400 TL/kg, green olives at opening" range reported for Manisa/
  Salihli (matches a captured listing's location) on tarimziraat.com, a
  crowdsourced farmer/trader price board, dated 16 Apr 2026. Cross-checked
  against Aydın Ticaret Borsası (an official, verifiable exchange), which
  recorded "Siyah Salamura Zeytin" (processed/brined — a different product
  stage) at 34 TL/kg on 15 Dec 2025, only 200kg traded that day — too thin
  and off-season to use directly, but broadly consistent once you account
  for the different product stage. Table-olive trading is seasonal
  (~Oct-Dec harvest); revisit once new-season exchange data is flowing.
- trees_per_donum: seeded at 25 — general web sources ranged 15-30/dönüm
  depending on spacing; 25 is a rough middle.
- planting_cost_try_per_tree: seeded at 600 TL/tree (~15,000 TL/dönüm at
  25 trees/dönüm) — sources disagreed by 2-3x (one implied ~25,000-90,000
  TL/dönüm all-in, another only quantified sapling+irrigation-infrastructure
  at ~7,000-9,500 TL/dönüm with labor unquantified). This is a rough
  starting midpoint, not a verified figure — the settings panel exists
  specifically so you can override it with real local knowledge.
- default_mature_age_years: seeded at 10 — used ONLY when a listing's
  description uses qualitative "already producing" language
  (config.MATURE_TREE_LANGUAGE — "olgun", "hasada hazır", etc.) but states
  no actual age anywhere. This is a guess at "old enough to be described as
  productive," not a real estimate — always overridden by a stated age or
  your own manual tree_age_years_override when either is available.

The yield-by-age curve itself (config.OLIVE_YIELD_BY_AGE_KG) stays in
config.py since it's a more complex structure less suited to a simple
settings input.
"""
from __future__ import annotations

from config import MATURE_TREE_LANGUAGE, OLIVE_YIELD_BY_AGE_KG
from extract import _turkish_lower

MAX_PROJECTION_YEARS = 40


def _yield_per_tree_kg(age_years: float) -> float:
    points = OLIVE_YIELD_BY_AGE_KG
    if age_years <= points[0][0]:
        return points[0][1]
    for (age1, y1), (age2, y2) in zip(points, points[1:]):
        if age1 <= age_years <= age2:
            if age2 == age1:
                return y2
            frac = (age_years - age1) / (age2 - age1)
            return y1 + frac * (y2 - y1)
    return points[-1][1]


def _project_payback_years(
    tree_count: float, starting_age: float, total_investment: float, price_per_kg: float
) -> float | None:
    """Simulates yearly production ramping up per the age->yield curve,
    starting from `starting_age`, until cumulative revenue covers
    `total_investment`. Returns a fractional year (linearly interpolated
    within the year it's paid back), or None if not paid back within
    MAX_PROJECTION_YEARS."""
    cumulative = 0.0
    for year in range(MAX_PROJECTION_YEARS):
        annual_revenue = tree_count * _yield_per_tree_kg(starting_age + year) * price_per_kg
        cumulative += annual_revenue
        if cumulative >= total_investment:
            prev_cumulative = cumulative - annual_revenue
            remaining = total_investment - prev_cumulative
            frac = (remaining / annual_revenue) if annual_revenue > 0 else 1.0
            return round(year + frac, 1)
    return None


def _has_maturity_language(description: str) -> bool:
    lowered = _turkish_lower(description or "")
    return any(kw in lowered for kw in MATURE_TREE_LANGUAGE)


def estimate_olive_roi(listing: dict, settings: dict) -> dict | None:
    """Returns None if there's not enough data to estimate anything for
    this listing. Returns {"missing_settings": [...]} naming which
    settings need a value, so the dashboard can prompt for them instead of
    silently showing nothing."""
    price = listing.get("price")
    size_donum = listing.get("size_donum")
    land_type = listing.get("land_type")
    if not price:
        return None

    price_per_kg = settings.get("olive_wholesale_price_try_per_kg")

    if land_type == "existing_orchard" and "olive" in (listing.get("tree_species") or ""):
        tree_count = listing.get("tree_count")
        tree_age = listing.get("tree_age_years")
        tree_count_estimated = False

        # The seller often doesn't state a count, but if we know the plot
        # size, fall back to the same density assumption used for raw-land
        # planting projections — a rough estimate is more useful than
        # nothing, as long as it's clearly flagged as one (not a stated
        # number).
        if not tree_count and size_donum and settings.get("trees_per_donum"):
            tree_count = round(size_donum * settings["trees_per_donum"])
            tree_count_estimated = True

        # Age isn't a function of area, so it has no size-based fallback —
        # but a description often still has a clue even without a number
        # ("olgun", "hasada hazır", etc.). Much lower confidence than a
        # stated number; only used as a last resort.
        tree_age_estimated = False
        if tree_age is None and _has_maturity_language(listing.get("description")):
            tree_age = settings.get("default_mature_age_years")
            tree_age_estimated = tree_age is not None

        if not tree_count or tree_age is None:
            # Distinct from the generic "not applicable" None below — this
            # IS an olive orchard, there's just nothing to project from yet.
            missing_fields = []
            if not tree_count:
                missing_fields.append("tree count")
            if tree_age is None:
                missing_fields.append("tree age")
            return {"missing_tree_data": missing_fields}
        missing = [k for k in ("olive_wholesale_price_try_per_kg",) if not settings.get(k)]
        if missing:
            return {"missing_settings": missing}
        scenario = "existing"
        starting_age = tree_age
        extra_upfront_cost = 0.0

    elif land_type in ("raw_land", "mixed") and size_donum:
        # No confirmed existing productive trees — project what planting
        # olives here now would look like, including the establishment cost.
        trees_per_donum = settings.get("trees_per_donum")
        planting_cost_per_tree = settings.get("planting_cost_try_per_tree")
        missing = [
            k for k, v in {
                "olive_wholesale_price_try_per_kg": price_per_kg,
                "trees_per_donum": trees_per_donum,
                "planting_cost_try_per_tree": planting_cost_per_tree,
            }.items() if not v
        ]
        if missing:
            return {"missing_settings": missing}
        scenario = "if_planted"
        tree_count = round(size_donum * trees_per_donum)
        tree_count_estimated = False  # "scenario" already conveys this is a projection
        tree_age_estimated = False    # starting_age is always 0 here, nothing to flag
        starting_age = 0
        extra_upfront_cost = tree_count * planting_cost_per_tree

    else:
        return None

    total_investment = price + extra_upfront_cost
    payback_years = _project_payback_years(tree_count, starting_age, total_investment, price_per_kg)
    year1_production_kg = round(tree_count * _yield_per_tree_kg(starting_age))

    return {
        "scenario": scenario,
        "tree_count_used": tree_count,
        "tree_count_estimated": tree_count_estimated,
        "starting_age_used": starting_age,
        "tree_age_estimated": tree_age_estimated,
        "extra_upfront_cost_try": round(extra_upfront_cost) if extra_upfront_cost else 0,
        "total_investment_try": round(total_investment),
        "year1_production_kg": year1_production_kg,
        "payback_years": payback_years,
    }
