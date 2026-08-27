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
    STRONG_ORCHARD_KEYWORDS,
    TAPU_CLEAN_KEYWORDS,
    TAPU_NONE_KEYWORDS,
    TAPU_SHARED_KEYWORDS,
)

# Total price is shown as "12.250.000 TL"; the per-m² price nearby ("69 TL/m²")
# has no thousands separator and is followed by "/", so this pattern skips it.
_PRICE_TL_RE = re.compile(r"(\d{1,3}(?:\.\d{3})+)\s*TL(?!\s*/)")


def _turkish_lower(s: str) -> str:
    """Python's default str.lower() isn't Turkish-aware: 'İ' becomes 'i' plus
    an invisible combining-dot mark (two characters), not plain 'i'. Since
    many listing titles are in ALL CAPS ("ZEYTİNLİK"), this silently broke
    every keyword containing 'i' when matched against such text. Map the
    Turkish-specific letters explicitly before falling back to str.lower()
    for everything else (ç/ğ/ş/ö/ü already lowercase correctly by default).
    """
    return s.replace("İ", "i").replace("I", "ı").lower()


# Turkish is agglutinative: suffixes attach directly onto the stem with no
# space ("var"+"dır"="vardır", "mevcut"+"tur"="mevcuttur", "tapu"+"lu"=
# "tapulu" meaning "deeded/has a title deed" — this exact suffix is what
# sahibinden's own "Tapu Durumu" spec field uses, e.g. "Müstakil Tapulu").
# A strict \b immediately after these words misses the continuation
# entirely, so give each a flexible optional suffix instead.
_SUFFIX_FLEXIBLE_ENDINGS = {
    "var": ("dır", "dir", "dur", "dür"),
    "mevcut": ("tur", "tır", "tir", "tür"),
    "tapu": ("lu", "lı", "li", "lü", "ludur", "lıdır", "lidir", "lüdür"),
}


def _keyword_pattern(keyword: str) -> re.Pattern:
    """Word-boundary-wrapped pattern for a keyword/phrase. Plain substring
    matching ("erik" in text) false-positives on fragments inside unrelated
    words — e.g. "erik" (plum) matched inside "içerik" (content), "bağ"
    (vineyard) matched inside "Bağlantı" (link), both from page footer
    boilerplate. \b works correctly with Turkish characters (verified).
    Keywords ending in a word from _SUFFIX_FLEXIBLE_ENDINGS get a flexible
    suffix instead of a strict trailing boundary."""
    for base, suffixes in _SUFFIX_FLEXIBLE_ENDINGS.items():
        if keyword.endswith(base):
            prefix = re.escape(keyword[: -len(base)])
            suffix_group = "|".join(suffixes)
            return re.compile(r"\b" + prefix + re.escape(base) + r"(?:" + suffix_group + r")?\b")
    return re.compile(r"\b" + re.escape(keyword) + r"\b")


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(_keyword_pattern(k).search(text) for k in keywords)


# Turkish negation typically follows the keyword ("hisseli olarak alamazsınız"
# = "you CANNOT buy it as shared" — the opposite of a plain "hisseli" match).
_NEGATION_FOLLOWERS = [
    "alamazsınız", "alamaz", "alınamaz", "satılmaz", "olamaz",
    "değildir", "değil", "verilmez", "yapılmaz", "bulunmamaktadır", "yoktur",
]


def _contains_unnegated(text: str, keyword: str) -> bool:
    """Like `keyword in text`, but False if a Turkish negation word follows
    the match within a short window — see _NEGATION_FOLLOWERS."""
    for m in _keyword_pattern(keyword).finditer(text):
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
    pattern = re.compile(
        word_pattern + r"([^.!?\n]{0," + str(max_chars) + r"}?)"
        r"\b(var(?:dır|dir|dur|dür)?|mevcut(?:tur|tır|tir|tür)?)\b"
    )
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


MIN_PLAUSIBLE_PRICE = 100_000  # TL — real listings here are always in the millions

def _extract_price_from_text(text: str) -> float | None:
    """Total listing price. Preferred over the element-selector guess
    because sahibinden also shows a much smaller per-m² price nearby, and
    which CSS class holds which figure isn't something we could verify.

    Takes the FIRST plausible ("X.XXX.XXX TL" formatted, >= MIN_PLAUSIBLE_PRICE)
    amount on the page, not the largest. A real listing had an "agency's
    other listings" sidebar widget further down the page containing a
    LARGER price than the listing's own — picking the max grabbed that
    instead. First-plausible isn't foolproof either on its own: another
    real listing's own TITLE contained a small decoy number ("... 8.800 TL
    ...", an apparent seller typo/shorthand, ahead of the real price in
    page order) — the >= MIN_PLAUSIBLE_PRICE filter excludes that kind of
    small figure before "first" is applied. Verified against 4 real
    captures, including both of these specific failure cases."""
    for m in _PRICE_TL_RE.finditer(text):
        try:
            value = float(m.group(1).replace(".", ""))
        except ValueError:
            continue
        if value >= MIN_PLAUSIBLE_PRICE:
            return value
    return None


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


# The seller's free-text description sits between an "Açıklama" heading and
# an "Özellikler" (Features) heading in sahibinden's page text. The
# extension's guessed CSS selector for this kept grabbing the wrong element
# (an unrelated messaging widget) — this direct text-marker approach doesn't
# depend on any CSS class at all.
_DESCRIPTION_RE = re.compile(r"Açıklama\s*\n+(.*?)(?:\n+Özellikler\b|\Z)", re.DOTALL)


def _extract_description(page_text: str) -> str | None:
    m = _DESCRIPTION_RE.search(page_text)
    if not m:
        return None
    desc = m.group(1).strip()
    return desc or None


def _classify_land_type(text: str, tree_count: int | None, tree_age: int | None) -> str:
    has_strong_keyword = any(_keyword_pattern(kw).search(text) for kw in STRONG_ORCHARD_KEYWORDS)
    has_any_tree_keyword = any(_keyword_pattern(kw).search(text) for kw in ORCHARD_TREE_KEYWORDS)
    if has_strong_keyword or (has_any_tree_keyword and (tree_count or tree_age)):
        return "existing_orchard"
    if has_any_tree_keyword:
        return "mixed"
    return "raw_land"


def _extract_tree_species(text: str) -> str | None:
    found = [name for kw, name in ORCHARD_TREE_KEYWORDS.items() if _keyword_pattern(kw).search(text)]
    return ", ".join(sorted(set(found))) if found else None


def _extract_tree_count(specs: dict, text: str) -> int | None:
    for key in ("Ağaç Sayısı", "Agac Sayisi"):
        if key in specs:
            m = re.search(r"\d+", specs[key])
            if m:
                return int(m.group())
    # Allows a variety name between the count and the species word, e.g.
    # "2650 adet Trilye cinsi zeytin ağacı" (Trilye is an olive cultivar) —
    # a tight "(adet)? zeytin" adjacency requirement misses this entirely.
    # The [^.\n\d]{0,30} window stops at sentence/line breaks or another
    # digit, so it won't reach across into an unrelated number elsewhere.
    m = re.search(r"(\d+)\s*(?:adet)?[^.\n\d]{0,30}?(?:zeytin|meyve)\s*ağac", text)
    if m:
        return int(m.group(1))
    # A different, very common construction: "<N> ağaçlı" (adjective,
    # "having N trees") with the species named separately/non-adjacently,
    # e.g. a title like "430 Agacli ... Zeytinlik" — note also the informal
    # ASCII spelling "agacli" without ğ/ç, which real listings do use.
    m = re.search(r"(\d+)\s*a[ğg]a[çc](?:lı|li)\b", text)
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
    page_text = payload.get("page_text", "") or ""
    description = _extract_description(page_text) or payload.get("description", "") or ""
    raw_text = f"{description}\n{page_text}"
    full_text = _turkish_lower(raw_text)

    price = _extract_price_from_text(raw_text) or _parse_price(payload.get("price_raw"))
    size_m2 = _parse_size_m2(specs, full_text)
    size_donum = round(size_m2 / 1000, 3) if size_m2 else None

    tree_count = _extract_tree_count(specs, full_text)
    tree_age = _extract_tree_age(specs, full_text)
    tree_species = _extract_tree_species(full_text)
    land_type = _classify_land_type(full_text, tree_count, tree_age)

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
    tapu_value = _turkish_lower(specs.get("Tapu Durumu") or specs.get("Tapu Durum") or "")
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
