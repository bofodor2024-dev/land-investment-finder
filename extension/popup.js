const BACKEND_URL = "http://localhost:5001/api/capture";

function extractListingData() {
  const specs = {};

  function addSpec(label, value) {
    label = (label || "").trim().replace(/:\s*$/, "");
    value = (value || "").trim();
    // Multi-line values are almost always a footer/nav menu swept up by the
    // generic "li with 2 children" scan below, not a real spec row.
    if (label && value && label.length < 40 && value.length < 200 && label !== value && !value.includes("\n")) {
      specs[label] = value;
    }
  }

  document.querySelectorAll("tr").forEach((tr) => {
    const cells = tr.querySelectorAll("td, th");
    if (cells.length === 2) addSpec(cells[0].innerText, cells[1].innerText);
  });

  document.querySelectorAll("dl").forEach((dl) => {
    const dts = dl.querySelectorAll("dt");
    const dds = dl.querySelectorAll("dd");
    dts.forEach((dt, i) => { if (dds[i]) addSpec(dt.innerText, dds[i].innerText); });
  });

  document.querySelectorAll("li").forEach((li) => {
    if (li.children.length === 2) addSpec(li.children[0].innerText, li.children[1].innerText);
  });

  const title = document.querySelector("h1")?.innerText?.trim() || document.title;

  let priceRaw = null;
  const priceEl = document.querySelector('[itemprop="price"], .classifiedInfoPrice, .price');
  if (priceEl) priceRaw = priceEl.getAttribute("content") || priceEl.innerText;
  if (!priceRaw) {
    const m = document.body.innerText.match(/([\d.]{4,})\s*TL/);
    if (m) priceRaw = m[1];
  }

  // Location: sahibinden's breadcrumb is always
  // "Anasayfa > Emlak > Arsa > Satılık > <province> > <district> > <neighborhood>".
  // Rather than matching province/district names against a hardcoded city
  // list (which just means missing whatever city we didn't think to list —
  // e.g. Çanakkale isn't "Aegean" by strict geography but plenty of olive
  // land is there), anchor on the taxonomy words instead: they're a small,
  // stable set sahibinden itself defines, and whatever links immediately
  // follow a run of them are the location trail, whatever it says.
  const BREADCRUMB_MARKERS = new Set([
    "Anasayfa", "Emlak", "Arsa", "Satılık", "Kiralık", "Tarla", "Konut",
    "İşyeri", "Bağ", "Bahçe", "Devremülk", "Turistik Tesis",
  ]);
  const linkText = (a) => (a?.innerText || "").trim();
  const links = Array.from(document.querySelectorAll("a"));

  let bestRunEnd = -1, bestRunLen = 0;
  for (let i = 0; i < links.length; ) {
    if (!BREADCRUMB_MARKERS.has(linkText(links[i]))) { i++; continue; }
    let j = i;
    while (j < links.length && BREADCRUMB_MARKERS.has(linkText(links[j]))) j++;
    if (j - i > bestRunLen) { bestRunLen = j - i; bestRunEnd = j; }
    i = j;
  }

  let province = null, district = null, neighborhood = null;
  if (bestRunLen >= 2) {
    province = linkText(links[bestRunEnd]) || null;
    district = linkText(links[bestRunEnd + 1]) || null;
    neighborhood = linkText(links[bestRunEnd + 2]) || null;
  }

  return {
    url: location.href,
    title,
    price_raw: priceRaw,
    specs,
    province,
    district,
    neighborhood,
    description: "",
    page_text: document.body.innerText.slice(0, 20000),
  };
}

const btn = document.getElementById("capture");
const status = document.getElementById("status");

btn.addEventListener("click", async () => {
  btn.disabled = true;
  status.textContent = "Reading page...";

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.url?.includes("sahibinden.com")) {
      status.textContent = "Not a sahibinden.com tab.";
      btn.disabled = false;
      return;
    }

    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: extractListingData,
    });

    status.textContent = "Sending to dashboard...";

    const res = await fetch(BACKEND_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(result),
    });

    if (!res.ok) throw new Error(`Server responded ${res.status}`);
    const data = await res.json();

    status.textContent = data.is_new
      ? "Captured as a new listing."
      : data.price_changed
      ? "Updated — price changed."
      : "Already captured, refreshed.";
  } catch (err) {
    status.textContent = `Failed: ${err.message}. Is the local app running?`;
  } finally {
    btn.disabled = false;
  }
});
