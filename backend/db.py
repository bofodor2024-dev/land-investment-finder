from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE NOT NULL,
    title TEXT,
    price REAL,
    currency TEXT DEFAULT 'TRY',
    size_m2 REAL,
    size_donum REAL,
    province TEXT,
    district TEXT,
    neighborhood TEXT,
    land_type TEXT,
    tree_species TEXT,
    tree_count INTEGER,
    tree_age_years INTEGER,
    irrigation TEXT,
    tapu_status TEXT,
    has_lien INTEGER DEFAULT 0,
    road_access INTEGER DEFAULT 0,
    electricity INTEGER DEFAULT 0,
    description TEXT,
    raw_specs_json TEXT,
    raw_payload_json TEXT,
    status TEXT DEFAULT 'active',
    captured_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL REFERENCES listings(id),
    price REAL NOT NULL,
    captured_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

# Seeded on first use only — never overwrites a value you've already set.
# These are rough starting points from web research (see roi.py), not
# verified benchmarks; edit them in the dashboard settings panel any time.
DEFAULT_SETTINGS = {
    "olive_wholesale_price_try_per_kg": "150",
    "trees_per_donum": "25",
    "planting_cost_try_per_tree": "600",
}


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        # Migration-safe column additions for existing databases — never
        # drops or recreates the table, so real captured data is untouched.
        existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(listings)")}
        if "raw_payload_json" not in existing_cols:
            conn.execute("ALTER TABLE listings ADD COLUMN raw_payload_json TEXT")
        # Separate from tree_count/tree_age_years (which normalize() derives
        # from listing text and overwrites on every /api/reprocess run) —
        # these hold a value YOU supply when the seller doesn't state one
        # but it's visible in photos, and survive reprocessing untouched.
        if "tree_count_override" not in existing_cols:
            conn.execute("ALTER TABLE listings ADD COLUMN tree_count_override INTEGER")
        if "tree_age_years_override" not in existing_cols:
            conn.execute("ALTER TABLE listings ADD COLUMN tree_age_years_override INTEGER")


def upsert_listing(fields: dict) -> tuple[int, bool, bool]:
    """Insert or update a listing by URL.

    Returns (listing_id, is_new, price_changed).
    """
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id, price FROM listings WHERE url = ?", (fields["url"],)
        ).fetchone()

        if existing is None:
            cols = ", ".join(fields.keys())
            placeholders = ", ".join(["?"] * len(fields))
            cur = conn.execute(
                f"INSERT INTO listings ({cols}) VALUES ({placeholders})",
                list(fields.values()),
            )
            listing_id = cur.lastrowid
            conn.execute(
                "INSERT INTO price_history (listing_id, price) VALUES (?, ?)",
                (listing_id, fields.get("price")),
            )
            return listing_id, True, False

        listing_id = existing["id"]
        price_changed = fields.get("price") is not None and fields.get("price") != existing["price"]

        set_clause = ", ".join(f"{k} = ?" for k in fields.keys())
        conn.execute(
            f"UPDATE listings SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            list(fields.values()) + [listing_id],
        )

        if price_changed:
            conn.execute(
                "INSERT INTO price_history (listing_id, price) VALUES (?, ?)",
                (listing_id, fields.get("price")),
            )

        return listing_id, False, price_changed


def all_listings(status: str = "active") -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM listings WHERE status = ? ORDER BY captured_at DESC", (status,)
        ).fetchall()
        return [dict(r) for r in rows]


def all_listings_any_status() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM listings ORDER BY captured_at DESC").fetchall()
        return [dict(r) for r in rows]


def set_tree_overrides(listing_id: int, tree_count: int | None, tree_age_years: int | None):
    """NULL clears an override, letting the extracted value show through
    again. Untouched by /api/reprocess, which only sets columns derived
    from normalize()."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE listings SET tree_count_override = ?, tree_age_years_override = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (tree_count, tree_age_years, listing_id),
        )


def price_history_for(listing_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT price, captured_at FROM price_history WHERE listing_id = ? ORDER BY captured_at",
            (listing_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def set_status(listing_id: int, status: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE listings SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, listing_id),
        )


def get_settings() -> dict:
    """Returns settings as floats (or None if a value is blank), seeding any
    missing keys with DEFAULT_SETTINGS on first call so the ROI feature works
    out of the box while staying fully editable from the dashboard."""
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        current = {r["key"]: r["value"] for r in rows}
        missing = {k: v for k, v in DEFAULT_SETTINGS.items() if k not in current}
        for k, v in missing.items():
            conn.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (k, v))
        current.update(missing)

    result = {}
    for k, v in current.items():
        try:
            result[k] = float(v) if v not in (None, "") else None
        except ValueError:
            result[k] = None
    return result


def set_settings(updates: dict):
    with get_conn() as conn:
        for k, v in updates.items():
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (k, str(v) if v is not None else None),
            )
