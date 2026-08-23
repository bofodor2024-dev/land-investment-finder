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
    return jsonify(scored)


@app.route("/api/listings/<int:listing_id>/archive", methods=["POST"])
def archive_listing(listing_id):
    db.set_status(listing_id, "archived")
    return jsonify({"ok": True})


@app.route("/")
def dashboard():
    listings = db.all_listings()
    scored = score_all(listings)
    return render_template("dashboard.html", listings=scored)


if __name__ == "__main__":
    db.init_db()
    app.run(port=5001, debug=True)
