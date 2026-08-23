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
"""


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
