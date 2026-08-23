AEGEAN_PROVINCES = [
    "İzmir", "Izmir", "Manisa", "Aydın", "Aydin", "Denizli",
    "Muğla", "Mugla", "Uşak", "Usak", "Kütahya", "Kutahya",
    "Afyonkarahisar", "Balıkesir", "Balikesir",
]

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

IRRIGATION_POSITIVE = ["sulama var", "sulu tarım", "sulanabilir", "kuyu var", "kuyulu", "damla sulama", "artezyen"]
IRRIGATION_NEGATIVE = ["sulama yok", "susuz", "kuru tarım"]

TAPU_SHARED_KEYWORDS = ["hisseli tapu", "hisseli", "hisse tapu"]
TAPU_CLEAN_KEYWORDS = ["müstakil tapu", "mustakil tapu", "ferdi tapu"]
TAPU_NONE_KEYWORDS = ["tapu kaydı yok", "tapu kaydi yok", "tapu yok", "tapusuz"]
LIEN_KEYWORDS = ["ipotekli", "ipotek var", "haciz", "hacizli", "rehinli"]

ROAD_ACCESS_KEYWORDS = ["yola cephe", "yol cepheli", "asfalt yol", "yola sıfır"]
ELECTRICITY_KEYWORDS = ["elektrik var", "elektrik mevcut"]

SCORE_WEIGHTS = {
    "value": 0.35,
    "maturity": 0.25,
    "irrigation": 0.15,
    "tapu": 0.15,
    "access": 0.10,
}

DB_PATH = "land_finder.db"
