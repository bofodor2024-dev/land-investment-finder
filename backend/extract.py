"""Normalizes the raw payload sent by the Chrome extension into DB fields.

The extension does light extraction in the page (spec table + visible text).
This module does the heavier keyword/classification work server-side so the
extension content script can stay simple and easy to patch when sahibinden's
markup changes.
"""
from __future__ import annotations

import json
import re

from config import (
    ELECTRICITY_KEYWORDS,
    IRRIGATION_NEGATIVE,
    IRRIGATION_POSITIVE,
    LIEN_KEYWORDS,
    ORCHARD_TREE_KEYWORDS,
    ROAD_ACCESS_KEYWORDS,
    TAPU_CLEAN_KEYWORDS,
    TAPU_NONE_KEYWORDS,
    TAPU_SHARED_KEYWORDS,
)

# Total price is shown as "12.250.000 TL"; the per-m² price nearby ("69 TL/m²")
# has no thousands separator and is followed by "/", so this pattern skips it.
_PRICE_TL_RE = re.compile(r"(\d{1,3}(?:\.\d{3})+)\s*TL(?!\s*/)")


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(k in text for k in keywords)


# Turkish negation typically follows the keyword ("hisseli olarak alamazsınız"
# = "you CANNOT buy it as shared" — the opposite of a plain "hisseli" match).
_NEGATION_FOLLOWERS = [
    "alamazsınız", "alamaz", "alınamaz", "satılmaz", "olamaz",
    "değildir", "değil", "verilmez", "yapılmaz", "bulunmamaktadır", "yoktur",
]


def _contains_unnegated(text: str, keyword: str) -> bool:
    """Like `keyword in text`, but False if a Turkish negation word follows
    the match within a short window — see _NEGATION_FOLLOWERS."""
    for m in re.finditer(re.escape(keyword), text):
        window = text[m.end(): m.end() + 40]
        if any(neg in window for neg in _NEGATION_FOLLOWERS):
            continue
        return True
    return False


def _contains_any_unnegated(text: str, keywords: list[str]) -> bool:
    return any(_contains_unnegated(text, k) for k in keywords)


def _word_followed_by_var(text: str, word_pattern: str, max_chars: int = 40) -> bool:
    """True if `word_pattern` is followed (within a short character window,
    not crossing a sentence boundary) by "var" or "mevcut" — handles
    Turkish's shared-verb enumeration, e.g. "yolu ve suyu var" (road AND
    water both exist) or "yolu, suyu ve elektriği var", where the target
    word and "var" aren't adjacent because other nouns share the same
    trailing "var". A plain substring check for "yolu var" misses this
    common construction entirely. A character window (rather than
    word-tokenizing) avoids breaking on punctuation like "Yolu, suyu...".
    """
    pattern = re.compile(word_pattern + r"([^.!?\n]{0," + str(max_chars) + r"}?)\b(var|mevcut)\b")
    for m in pattern.finditer(text):
        between = m.group(1)
        if "yok" in between or "değil" in between:
            # The target word's own clause was negated before reaching this
            # "var" — it belongs to a different, later noun.
            continue
        after = text[m.end(): m.end() + 40]
        if any(neg in after for neg in _NEGATION_FOLLOWERS):
            continue
        return True
    return False


def _parse_price(raw) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = re.sub(r"[^\d,\.]", "", str(raw))
    s = s.replace(".", "").replace(",", ".") if "," in s else s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def _extract_price_from_text(text: str) -> float | None:
    """Total listing price, picked as the largest properly-thousands-separated
    'X.XXX TL' amount on the page. Preferred over the element-selector guess
    because sahibinden also shows a much smaller per-m² price nearby, and
    which CSS class holds which figure isn't something we could verify."""
    candidates = []
    for m in _PRICE_TL_RE.finditer(text):
        try:
            candidates.append(float(m.group(1).replace(".", "")))
        except ValueError:
            continue
    return max(candidates) if candidates else None


def _parse_size_m2(specs: dict, text: str) -> float | None:
    for key in ("m2", "m²", "Alan", "Metrekare"):
        if key in specs:
            val = re.sub(r"[^\d,\.]", "", specs[key])
            val = val.replace(".", "").replace(",", ".")
            try:
                return float(val)
            except ValueError:
                pass
    m = re.search(r"([\d\.]+)\s*m²", text)
    if m:
        try:
            return float(m.group(1).replace(".", ""))
        except ValueError:
            return None
    return None


def _classify_land_type(text: str, tree_count: int | None) -> str:
    has_tree_keyword = any(kw in text for kw in ORCHARD_TREE_KEYWORDS)
    if has_tree_keyword and (tree_count and tree_count > 0):
        return "existing_orchard"
    if has_tree_keyword:
        return "mixed"
    return "raw_land"


def _extract_tree_species(text: str) -> str | None:
    found = [name for kw, name in ORCHARD_TREE_KEYWORDS.items() if kw in text]
    return ", ".join(sorted(set(found))) if found else None


def _extract_tree_count(specs: dict, text: str) -> int | None:
    for key in ("Ağaç Sayısı", "Agac Sayisi"):
        if key in specs:
            m = re.search(r"\d+", specs[key])
            if m:
                return int(m.group())
    m = re.search(r"(\d+)\s*(adet\s*)?(zeytin|meyve)\s*ağac", text)
    return int(m.group(1)) if m else None


def _extract_tree_age(specs: dict, text: str) -> int | None:
    for key in ("Ağaç Yaşı", "Agac Yasi"):
        if key in specs:
            m = re.search(r"\d+", specs[key])
            if m:
                return int(m.group())
    m = re.search(r"(\d+)\s*yaşında", text)
    return int(m.group(1)) if m else None


def normalize(payload: dict) -> dict:
    """payload comes from the extension: {url, title, price_raw, specs: {label: value}, description, page_text}"""
    specs = payload.get("specs", {}) or {}
    description = payload.get("description", "") or ""
    page_text = payload.get("page_text", "") or ""
    raw_text = f"{description}\n{page_text}"
    full_text = raw_text.lower()

    price = _extract_price_from_text(raw_text) or _parse_price(payload.get("price_raw"))
    size_m2 = _parse_size_m2(specs, full_text)
    size_donum = round(size_m2 / 1000, 3) if size_m2 else None

    tree_count = _extract_tree_count(specs, full_text)
    tree_age = _extract_tree_age(specs, full_text)
    tree_species = _extract_tree_species(full_text)
    land_type = _classify_land_type(full_text, tree_count)

    if _contains_any_unnegated(full_text, IRRIGATION_POSITIVE) or _word_followed_by_var(full_text, r"\bsuyu?\b"):
        irrigation = "var"
    elif _contains_any(full_text, IRRIGATION_NEGATIVE):
        irrigation = "yok"
    else:
        irrigation = "unknown"

    # Prefer the "Tapu Durumu" spec value directly when we have it — it's a
    # short, authoritative field. Scanning the whole page for these keywords
    # risks false positives from unrelated text elsewhere (footer links,
    # sidebar filters, similar-listings sections, etc.).
    tapu_value = (specs.get("Tapu Durumu") or specs.get("Tapu Durum") or "").lower()
    tapu_source = tapu_value or full_text

    if _contains_any_unnegated(tapu_source, TAPU_NONE_KEYWORDS):
        tapu_status = "none"
    elif _contains_any_unnegated(tapu_source, TAPU_SHARED_KEYWORDS):
        tapu_status = "hisseli"
    elif _contains_any_unnegated(tapu_source, TAPU_CLEAN_KEYWORDS):
        tapu_status = "mustakil"
    else:
        tapu_status = "unknown"

    has_lien = _contains_any_unnegated(tapu_value, LIEN_KEYWORDS) or _contains_any_unnegated(full_text, LIEN_KEYWORDS)
    road_access = _contains_any_unnegated(full_text, ROAD_ACCESS_KEYWORDS) or _word_followed_by_var(full_text, r"\byolu?\b")
    electricity = _contains_any_unnegated(full_text, ELECTRICITY_KEYWORDS) or _word_followed_by_var(full_text, r"\belektri(?:k|ği)\b")

    province = payload.get("province") or specs.get("İl")
    district = payload.get("district") or specs.get("İlçe")
    neighborhood = payload.get("neighborhood") or specs.get("Mahalle")
    if district and province and district.lower() == province.lower():
        # Degenerate case — a district can't be the same as its own
        # province, so the breadcrumb walker likely latched onto the
        # wrong link chain. Discard rather than store obviously-wrong data.
        district = None
        neighborhood = None

    return {
        "url": payload["url"],
        "title": payload.get("title"),
        "price": price,
        "currency": payload.get("currency", "TRY"),
        "size_m2": size_m2,
        "size_donum": size_donum,
        "province": province,
        "district": district,
        "neighborhood": neighborhood,
        "land_type": land_type,
        "tree_species": tree_species,
        "tree_count": tree_count,
        "tree_age_years": tree_age,
        "irrigation": irrigation,
        "tapu_status": tapu_status,
        "has_lien": int(has_lien),
        "road_access": int(road_access),
        "electricity": int(electricity),
        "description": description,
        "raw_specs_json": json.dumps(specs, ensure_ascii=False),
    }
