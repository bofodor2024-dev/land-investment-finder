# Land Investment Finder

Personal tool for evaluating Aegean farmland (existing olive/orchard land or
raw land you'd plant yourself) as investment candidates from sahibinden.com
listings.

Because sahibinden runs Cloudflare bot-detection, this does **not** scrape
automatically. Instead: you browse listings normally in Chrome, click
"Capture Listing" in the extension when you find one worth logging, and the
local app scores it against your criteria.

## Setup

### 1. Backend + dashboard

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

Runs at http://localhost:5001 — this is both the dashboard and the API the
extension posts to. Leave it running while you browse.

### 2. Chrome extension

1. Go to `chrome://extensions`
2. Enable "Developer mode" (top right)
3. Click "Load unpacked", select the `extension/` folder
4. Pin the extension to your toolbar

## Usage

1. Start the backend (`python app.py`).
2. Browse to any land/orchard listing on sahibinden.com.
3. Click the extension icon → "Capture Listing".
4. Open http://localhost:5001 to see it scored alongside everything else.

Re-capturing the same URL later updates the listing and records the price
change in history (useful for spotting listings that have been reduced or
sitting unsold).

## Scoring model

Composite score (0–100) weighted from:

- **Value (35%)** — price per dönüm vs. the average of other captured
  listings in the same province and land-type bucket (existing orchard vs.
  raw land are compared separately, since a bearing orchard should cost
  more than bare land).
- **Maturity (25%)** — existing productive trees score higher than raw
  land, since raw land needs several years before olive/fruit trees bear.
- **Irrigation (15%)** — sulama/kuyu mentions are a strong positive; no
  irrigation is a real risk for establishing an orchard in the Aegean
  summer.
- **Tapu / legal (15%)** — clean (müstakil) title deed scores well; shared
  (hisseli) title or any ipotek/haciz (lien) mention is flagged as a red
  flag and tanks the score.
- **Access (10%)** — road frontage and electricity availability.

Red flags (hisseli tapu, liens, no irrigation) are also surfaced explicitly
in the dashboard regardless of score — don't rely on the composite number
alone for dealbreakers.

## Known limitations / things to verify

- **Selectors are best-effort.** I could not load sahibinden.com myself
  (Cloudflare blocked the automated browser session used to build this), so
  the extension's field extraction is written to be resilient — it scans
  generic label/value table and list structures, plus regex over the full
  page text — rather than hardcoded to exact CSS classes. If a field comes
  through empty for a real listing, check `page_text`/`specs` in the
  captured record and tell me what the actual label text looks like so I
  can tighten the parser.
- **Group averages need a handful of listings first.** The "value" score
  is meaningless until you've captured several listings per
  province/land-type — everything defaults to 50 until then.
- **This is single-user, unauthenticated, localhost-only.** Don't expose
  port 5001 beyond your machine as-is.
- Province/district are pulled from the spec table when sahibinden exposes
  them there (`İl`/`İlçe`/`Mahalle`); if that table isn't found, capture
  will store them as empty and you can backfill later.
