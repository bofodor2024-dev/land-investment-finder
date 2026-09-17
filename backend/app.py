import json
import os
import signal
import threading
import time

from flask import Flask, jsonify, render_template, request

import db
from extract import normalize
from scoring import score_all

app = Flask(__name__)


@app.after_request
def add_cors_headers(resp):
    # Allow the Chrome extension (chrome-extension:// origin) to POST here.
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


@app.route("/api/capture", methods=["POST", "OPTIONS"])
def capture():
    if request.method == "OPTIONS":
        return "", 204

    payload = request.get_json(force=True)
    if not payload or not payload.get("url"):
        return jsonify({"error": "missing url"}), 400

    fields = normalize(payload)
    # Store the full raw payload alongside the derived fields, so scoring-logic
    # fixes (keyword lists, parsing rules, etc.) can be re-applied to every
    # already-captured listing later via /api/reprocess — no re-visiting and
    # re-clicking "Capture" on every listing each time the logic improves.
    fields["raw_payload_json"] = json.dumps(payload, ensure_ascii=False)
    listing_id, is_new, price_changed = db.upsert_listing(fields)
    return jsonify({"id": listing_id, "is_new": is_new, "price_changed": price_changed})


@app.route("/api/reprocess", methods=["POST"])
def reprocess():
    """Re-run normalize() against every stored raw payload and update the
    derived fields in place. Use this after fixing extraction/scoring logic,
    instead of re-capturing every listing in the browser again."""
    listings = db.all_listings_any_status()
    updated, skipped = 0, 0
    for listing in listings:
        raw = listing.get("raw_payload_json")
        if not raw:
            skipped += 1
            continue
        payload = json.loads(raw)
        fields = normalize(payload)
        fields["raw_payload_json"] = raw
        # track_price_history=False: re-deriving from the same raw payload,
        # so any price difference is a parsing correction, not a real
        # market event — see db.upsert_listing's docstring.
        db.upsert_listing(fields, track_price_history=False)
        updated += 1
    return jsonify({"updated": updated, "skipped": skipped})


def _attach_price_history(listings):
    """Adds price_history (full list), first_price, price_change_pct, and
    last_price_change_at to each listing — the price_history table already
    records a new entry every time a recapture sees a different price, this
    just surfaces it."""
    history_by_id = db.all_price_history()
    for l in listings:
        history = history_by_id.get(l["id"], [])
        l["price_history"] = history
        if len(history) >= 2 and history[0]["price"]:
            first_price = history[0]["price"]
            current_price = history[-1]["price"]
            l["first_price"] = first_price
            l["price_change_pct"] = round((current_price - first_price) / first_price * 100, 1)
            l["last_price_change_at"] = history[-1]["captured_at"]
        else:
            l["first_price"] = None
            l["price_change_pct"] = None
            l["last_price_change_at"] = None
    return listings


def _top_price_drops(scored, limit=5):
    """Listings with a net price decrease, most recent change first — a
    fresh drop is a stronger negotiation signal than an old one. Doesn't
    reorder the main table; this is a separate highlight only."""
    drops = [l for l in scored if l.get("price_change_pct") is not None and l["price_change_pct"] < 0]
    drops.sort(key=lambda l: l["last_price_change_at"], reverse=True)
    return drops[:limit]


@app.route("/api/listings")
def api_listings():
    listings = db.all_listings()
    listings = _attach_price_history(listings)
    scored = score_all(listings, db.get_settings())
    scored = _apply_filters(scored, request.args)
    return jsonify(scored)


@app.route("/api/settings", methods=["GET", "POST"])
def settings():
    if request.method == "GET":
        return jsonify(db.get_settings())

    payload = request.get_json(force=True) or {}
    updates = {}
    for key in (
        "olive_wholesale_price_try_per_kg", "trees_per_donum",
        "planting_cost_try_per_tree", "default_mature_age_years",
    ):
        if key in payload:
            updates[key] = payload[key]
    db.set_settings(updates)
    return jsonify(db.get_settings())


@app.route("/api/listings/<int:listing_id>/archive", methods=["POST"])
def archive_listing(listing_id):
    db.set_status(listing_id, "archived")
    return jsonify({"ok": True})


@app.route("/api/restart", methods=["POST"])
def restart():
    """Exits this process shortly after responding. Only meaningful because
    the LaunchAgent (com.landinvestmentfinder.server, KeepAlive=true) brings
    it right back up — without that, this would just stop the server with
    no way to start it again from the page itself."""

    def do_exit():
        time.sleep(0.5)  # let the HTTP response flush before the process dies
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=do_exit).start()
    return jsonify({"restarting": True})


@app.route("/api/listings/<int:listing_id>/tree_override", methods=["POST"])
def tree_override(listing_id):
    payload = request.get_json(force=True) or {}

    def parse_int(v):
        return int(v) if v not in (None, "") else None

    tree_count = parse_int(payload.get("tree_count"))
    tree_age_years = parse_int(payload.get("tree_age_years"))
    db.set_tree_overrides(listing_id, tree_count, tree_age_years)
    return jsonify({"ok": True})


def _apply_filters(scored, args):
    province = args.get("province") or ""
    district = args.get("district") or ""
    if province:
        scored = [l for l in scored if (l.get("province") or "") == province]
    if district:
        scored = [l for l in scored if (l.get("district") or "") == district]
    return scored


SORT_FIELDS = {
    "score": "composite",
    "price": "price",
    "price_per_donum": "price_per_donum",
    "size": "size_donum",
}


def _apply_sort(scored, args):
    field = SORT_FIELDS.get(args.get("sort", "score"), "composite")
    ascending = args.get("dir") == "asc"

    def sort_key(listing):
        value = listing.get(field)
        # None values always sort last, regardless of direction.
        if value is None:
            return (1, 0)
        return (0, value if ascending else -value)

    return sorted(scored, key=sort_key)


@app.route("/")
def dashboard():
    listings = db.all_listings()
    listings = _attach_price_history(listings)
    scored = score_all(listings, db.get_settings())  # scored against the full captured set, before filtering

    provinces = sorted({l["province"] for l in scored if l.get("province")})

    selected_province = request.args.get("province") or ""
    selected_district = request.args.get("district") or ""
    selected_sort = request.args.get("sort", "score")
    selected_dir = request.args.get("dir", "desc")

    district_pool = [l for l in scored if not selected_province or l.get("province") == selected_province]
    districts = sorted({l["district"] for l in district_pool if l.get("district")})

    filtered = _apply_filters(scored, request.args)
    filtered = _apply_sort(filtered, request.args)

    return render_template(
        "dashboard.html",
        listings=filtered,
        total_count=len(scored),
        provinces=provinces,
        districts=districts,
        selected_province=selected_province,
        selected_district=selected_district,
        selected_sort=selected_sort,
        selected_dir=selected_dir,
        settings=db.get_settings(),
        price_drops=_top_price_drops(scored),
    )


if __name__ == "__main__":
    db.init_db()
    app.run(port=5001, debug=True)
