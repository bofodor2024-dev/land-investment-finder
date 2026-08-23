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
    "meyve bahçesi": "mixed orchard",
}

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

# Override with LAND_FINDER_DB=/path/to/other.db for testing/dev work, so
# real captured data is never at risk of being reset or overwritten.
DB_PATH = os.environ.get("LAND_FINDER_DB", "land_finder.db")
