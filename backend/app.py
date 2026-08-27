import json

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
        db.upsert_listing(fields)
        updated += 1
    return jsonify({"updated": updated, "skipped": skipped})


@app.route("/api/listings")
def api_listings():
    listings = db.all_listings()
    scored = score_all(listings, db.get_settings())
    scored = _apply_filters(scored, request.args)
    return jsonify(scored)


@app.route("/api/settings", methods=["GET", "POST"])
def settings():
    if request.method == "GET":
        return jsonify(db.get_settings())

    payload = request.get_json(force=True) or {}
    updates = {}
    for key in ("olive_wholesale_price_try_per_kg", "trees_per_donum", "planting_cost_try_per_tree"):
        if key in payload:
            updates[key] = payload[key]
    db.set_settings(updates)
    return jsonify(db.get_settings())


@app.route("/api/listings/<int:listing_id>/archive", methods=["POST"])
def archive_listing(listing_id):
    db.set_status(listing_id, "archived")
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
    )


if __name__ == "__main__":
    db.init_db()
    app.run(port=5001, debug=True)
