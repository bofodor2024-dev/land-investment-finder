const BACKEND_URL = "http://localhost:5001/api/capture";

function extractListingData() {
  const specs = {};

  function addSpec(label, value) {
    label = (label || "").trim().replace(/:\s*$/, "");
    value = (value || "").trim();
    if (label && value && label.length < 40 && value.length < 200 && label !== value) {
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

  const descEl = document.querySelector(
    '.classifiedDescription, #classifiedDescription, [class*="description"]'
  );
  const description = descEl ? descEl.innerText : "";

  return {
    url: location.href,
    title,
    price_raw: priceRaw,
    specs,
    description,
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
