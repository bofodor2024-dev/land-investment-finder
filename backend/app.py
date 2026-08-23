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
    listing_id, is_new, price_changed = db.upsert_listing(fields)
    return jsonify({"id": listing_id, "is_new": is_new, "price_changed": price_changed})


@app.route("/api/listings")
def api_listings():
    listings = db.all_listings()
    scored = score_all(listings)
    scored = _apply_filters(scored, request.args)
    return jsonify(scored)


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
    scored = score_all(listings)  # scored against the full captured set, before filtering

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
    )


if __name__ == "__main__":
    db.init_db()
    app.run(port=5001, debug=True)
