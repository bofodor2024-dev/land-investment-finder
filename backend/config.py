import os

# No hardcoded province/city list: the extension captures whatever
# province/district/neighborhood sahibinden's own breadcrumb says (see
# extractListingData in extension/popup.js), so any city works without
# needing to be added here. The dashboard's province/district filter
# dropdowns are populated dynamically from whatever's actually captured.

ORCHARD_TREE_KEYWORDS = {
    "zeytin": "olive",
    "zeytinlik": "olive",
    "incir": "fig",
    "nar": "pomegranate",
    "badem": "almond",
    "kiraz": "cherry",
    "erik": "plum",
    "elma": "apple",
    "portakal": "orange",
    "mandalina": "mandarin",
    "limon": "lemon",
    "ceviz": "walnut",
    "bağ": "vineyard",
    "üzüm": "grape",
    "bahçe": "orchard/garden",
    "meyve bahçesi": "mixed orchard",
}

# Words that alone mean an established planting already exists — "place"
# nouns (zeytinlik = "olive grove", bağ = "vineyard") rather than bare fruit
# names (zeytin = "olive", the fruit — could just mean "suitable for olives").
# These count as an existing orchard without needing a tree count or age;
# the bare-fruit-name keywords above need that corroboration instead.
STRONG_ORCHARD_KEYWORDS = {"zeytinlik", "bağ", "bahçe", "meyve bahçesi"}

IRRIGATION_POSITIVE = [
    "sulama var", "sulu tarım", "sulanabilir", "kuyu var", "kuyulu",
    "damla sulama", "artezyen", "suyu var", "su var", "suyu mevcut",
]
IRRIGATION_NEGATIVE = ["sulama yok", "susuz", "kuru tarım", "suyu yok", "su yok"]

TAPU_SHARED_KEYWORDS = ["hisseli tapu", "hisseli", "hisse tapu"]
TAPU_CLEAN_KEYWORDS = ["müstakil tapu", "mustakil tapu", "ferdi tapu"]
TAPU_NONE_KEYWORDS = ["tapu kaydı yok", "tapu kaydi yok", "tapu yok", "tapusuz"]
LIEN_KEYWORDS = ["ipotekli", "ipotek var", "haciz", "hacizli", "rehinli"]

ROAD_ACCESS_KEYWORDS = [
    "yola cephe", "yol cepheli", "asfalt yol", "yola sıfır", "yolu var", "yol var", "yolu mevcut",
]
ELECTRICITY_KEYWORDS = ["elektrik var", "elektrik mevcut"]

SCORE_WEIGHTS = {
    "value": 0.35,
    "maturity": 0.25,
    "irrigation": 0.15,
    "tapu": 0.15,
    "access": 0.10,
}

# No title deed record or a lien/mortgage are legal dealbreakers, not just
# "less attractive" factors — cap the composite score hard regardless of how
# good everything else looks, rather than letting them just be one weighted
# input among five (which let a listing with no title deed still land at 55).
TAPU_HARD_CAP = 25.0

# --- Olive production estimate (gross only, no operating costs netted out) ---
#
# Rough fruit yield by tree age, in kg/tree/year. Linearly interpolated
# between points, plateaus after the last one. This is a GENERAL Aegean
# semi-intensive-grove approximation, not sourced from any specific
# regional/cultivar dataset — actual yield varies hugely by variety,
# irrigation, care, and microclimate. It's meant for comparing listings
# against each other, not as a forecast. Tune freely as you learn more.
OLIVE_YIELD_BY_AGE_KG = [
    (0, 0),      # not yet bearing
    (3, 0),
    (4, 5),      # coming into bearing
    (6, 15),
    (8, 25),
    (10, 35),
    (15, 45),
    (20, 55),    # approaching/at full maturity
    (30, 55),    # plateau
]

# TL per kg, wholesale raw (table) olives — NOT olive oil. No live price
# source is wired up (nothing reliable to scrape, and prices move fast with
# TL inflation) — update this manually with a current number periodically.
#
# Current value: 150 TL/kg — the low end of a "150-400 TL/kg, green olives
# at opening" range reported for the Manisa/Salihli market (same location
# as a captured listing) on tarimziraat.com, dated 16 Apr 2026. That site is
# a crowdsourced farmer/trader price board, not an official exchange, so
# treat this as a rough starting point, not a verified benchmark.
#
# For comparison, Aydın Ticaret Borsası (an official, verifiable exchange)
# recorded "Siyah Salamura Zeytin" (processed/brined, a different product
# stage) at 34 TL/kg on 15 Dec 2025, only 200kg traded that day — too thin
# and off-season-adjacent to use directly, but a useful sanity check.
# Table-olive trading is seasonal (~Oct-Dec harvest); revisit this figure
# once the new season's exchange data is flowing for something more solid.
OLIVE_WHOLESALE_PRICE_TL_PER_KG = 150.0

# Override with LAND_FINDER_DB=/path/to/other.db for testing/dev work, so
# real captured data is never at risk of being reset or overwritten.
DB_PATH = os.environ.get("LAND_FINDER_DB", "land_finder.db")
