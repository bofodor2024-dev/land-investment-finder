"""Rough gross production-value estimate for existing olive orchards.

Deliberately NOT a full ROI: no operating costs (harvest labor, pruning,
pest control, transport, taxes) are netted out yet — this is gross revenue
only. Wholesale price must be set manually in config.py since there's no
live price source. Meant for comparing listings against each other, not as
a financial projection or investment advice.
"""
from __future__ import annotations

from config import OLIVE_WHOLESALE_PRICE_TL_PER_KG, OLIVE_YIELD_BY_AGE_KG


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


def estimate_olive_roi(listing: dict) -> dict | None:
    """Returns None if this listing isn't an olive orchard with enough data
    to estimate anything. Returns {"missing_price": True} if the wholesale
    price hasn't been configured yet, so the dashboard can prompt for it
    instead of silently showing nothing."""
    if listing.get("land_type") != "existing_orchard":
        return None
    if "olive" not in (listing.get("tree_species") or ""):
        return None

    tree_count = listing.get("tree_count")
    tree_age = listing.get("tree_age_years")
    price = listing.get("price")
    if not tree_count or tree_age is None or not price:
        return None

    if not OLIVE_WHOLESALE_PRICE_TL_PER_KG:
        return {"missing_price": True}

    yield_per_tree = _yield_per_tree_kg(tree_age)
    annual_kg = tree_count * yield_per_tree
    annual_revenue = annual_kg * OLIVE_WHOLESALE_PRICE_TL_PER_KG
    gross_yield_pct = (annual_revenue / price) * 100 if price else None
    payback_years = price / annual_revenue if annual_revenue > 0 else None

    return {
        "yield_per_tree_kg": round(yield_per_tree, 1),
        "annual_production_kg": round(annual_kg),
        "annual_revenue_try": round(annual_revenue),
        "gross_yield_pct": round(gross_yield_pct, 1) if gross_yield_pct is not None else None,
        "simple_payback_years": round(payback_years, 1) if payback_years else None,
    }
