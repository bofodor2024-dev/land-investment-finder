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
    AEGEAN_PROVINCES,
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

# Matches the "İzmir / Torbalı / Ahmetli Mh." breadcrumb-style line sahibinden
# shows next to the price, since İl/İlçe/Mahalle aren't reliably in the spec table.
_LOCATION_RE = re.compile(
    r"(" + "|".join(re.escape(p) for p in sorted(set(AEGEAN_PROVINCES), key=len, reverse=True)) + r")"
    r"\s*/\s*([^\n/,]{2,40}?)\s*/\s*([^\n/,]{2,40})"
)

# Total price is shown as "12.250.000 TL"; the per-m² price nearby ("69 TL/m²")
# has no thousands separator and is followed by "/", so this pattern skips it.
_PRICE_TL_RE = re.compile(r"(\d{1,3}(?:\.\d{3})+)\s*TL(?!\s*/)")


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(k in text for k in keywords)


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


def _extract_location(text: str) -> tuple[str | None, str | None, str | None]:
    m = _LOCATION_RE.search(text)
    if not m:
        return None, None, None
    return tuple(g.strip() for g in m.groups())


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

    province, district, neighborhood = _extract_location(raw_text)

    tree_count = _extract_tree_count(specs, full_text)
    tree_age = _extract_tree_age(specs, full_text)
    tree_species = _extract_tree_species(full_text)
    land_type = _classify_land_type(full_text, tree_count)

    if _contains_any(full_text, IRRIGATION_POSITIVE):
        irrigation = "var"
    elif _contains_any(full_text, IRRIGATION_NEGATIVE):
        irrigation = "yok"
    else:
        irrigation = "unknown"

    if _contains_any(full_text, TAPU_NONE_KEYWORDS):
        tapu_status = "none"
    elif _contains_any(full_text, TAPU_SHARED_KEYWORDS):
        tapu_status = "hisseli"
    elif _contains_any(full_text, TAPU_CLEAN_KEYWORDS):
        tapu_status = "mustakil"
    else:
        tapu_status = "unknown"

    has_lien = _contains_any(full_text, LIEN_KEYWORDS)
    road_access = _contains_any(full_text, ROAD_ACCESS_KEYWORDS)
    electricity = _contains_any(full_text, ELECTRICITY_KEYWORDS)

    return {
        "url": payload["url"],
        "title": payload.get("title"),
        "price": price,
        "currency": payload.get("currency", "TRY"),
        "size_m2": size_m2,
        "size_donum": size_donum,
        "province": specs.get("İl") or province or payload.get("province"),
        "district": specs.get("İlçe") or district or payload.get("district"),
        "neighborhood": specs.get("Mahalle") or neighborhood or payload.get("neighborhood"),
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
