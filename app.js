const API = "http://localhost:8000";

// ── State ──────────────────────────────────────────────────────────────────
let allRows = [];
let sortCol = null;
let sortAsc = true;
let activeTab = "summary";

const TABS = {
  summary: [
    { key: "date",    label: "Date" },
    { key: "ticker",  label: "Ticker" },
    { key: "company", label: "Company" },
    { key: "insider", label: "Insider" },
    { key: "role",    label: "Role" },
    { key: "code",    label: "Code" },
    { key: "shares",  label: "Shares" },
    { key: "price",   label: "Price" },
  ],
  returns: [
    { key: "date",    label: "Date" },
    { key: "ticker",  label: "Ticker" },
    { key: "code",    label: "Code" },
    { key: "shares",  label: "Shares" },
    { key: "price",   label: "Price" },
    { key: "ret_1m",  label: "1-mo ret" },
    { key: "ret_3m",  label: "3-mo ret" },
    { key: "ret_6m",  label: "6-mo ret" },
    { key: "ret_12m", label: "12-mo ret" },
    { key: "exc_1m",  label: "1-mo vs SPY" },
    { key: "exc_3m",  label: "3-mo vs SPY" },
    { key: "exc_6m",  label: "6-mo vs SPY" },
    { key: "exc_12m", label: "12-mo vs SPY" },
  ],
  all: [
    { key: "id",        label: "ID" },
    { key: "date",      label: "Date" },
    { key: "ticker",    label: "Ticker" },
    { key: "company",   label: "Company" },
    { key: "insider",   label: "Insider" },
    { key: "role",      label: "Role" },
    { key: "code",      label: "Code" },
    { key: "shares",    label: "Shares" },
    { key: "price",     label: "Price" },
    { key: "accession", label: "Accession" },
    { key: "ret_1m",    label: "Ret 1m" },
    { key: "ret_3m",    label: "Ret 3m" },
    { key: "ret_6m",    label: "Ret 6m" },
    { key: "ret_12m",   label: "Ret 12m" },
    { key: "exc_1m",    label: "Exc 1m" },
    { key: "exc_3m",    label: "Exc 3m" },
    { key: "exc_6m",    label: "Exc 6m" },
    { key: "exc_12m",   label: "Exc 12m" },
  ],
};

const PCT_KEYS = new Set(["ret_1m","ret_3m","ret_6m","ret_12m","exc_1m","exc_3m","exc_6m","exc_12m"]);
const NUM_KEYS  = new Set([...PCT_KEYS, "shares", "price"]);

// ── Helpers ────────────────────────────────────────────────────────────────
function pct(v) {
  if (v == null) return "—";
  return (v >= 0 ? "+" : "") + (v * 100).toFixed(1) + "%";
}

function animateCount(el, target) {
  if (typeof target !== "number") { el.textContent = String(target); return; }
  const duration = 700;
  const t0 = performance.now();
  (function tick(now) {
    const p = Math.min((now - t0) / duration, 1);
    const ease = 1 - Math.pow(1 - p, 3);
    el.textContent = Math.round(target * ease).toLocaleString();
    if (p < 1) requestAnimationFrame(tick);
  })(t0);
}

function setApiStatus(ok, msg) {
  document.getElementById("status-dot").className = ok ? "ok" : "err";
  document.getElementById("status-text").textContent = msg;
  document.getElementById("guide").className = "guide" + (ok ? "" : " visible");
}

// ── Stats ──────────────────────────────────────────────────────────────────
async function loadStats() {
  try {
    const r = await fetch(`${API}/summary`);
    if (!r.ok) return;
    const s = await r.json();
    animateCount(document.getElementById("s-total"),    s.total    ?? 0);
    animateCount(document.getElementById("s-tickers"),  s.tickers  ?? 0);
    animateCount(document.getElementById("s-insiders"), s.insiders ?? 0);
    animateCount(document.getElementById("s-returns"),  s.with_returns ?? 0);
    const range = s.date_min && s.date_max ? `${s.date_min} → ${s.date_max}` : "—";
    document.getElementById("s-range").textContent = range;

    if (s.top_tickers?.length) {
      const wrap = document.getElementById("top-tickers-wrap");
      const el   = document.getElementById("top-tickers");
      el.innerHTML = s.top_tickers.map(t =>
        `<div class="ticker-chip" onclick="filterByTicker('${t.ticker}')">${t.ticker}<span>${t.n}</span></div>`
      ).join("");
      wrap.style.display = "block";
    }
  } catch {}
}

function filterByTicker(ticker) {
  document.getElementById("f-ticker").value = ticker;
  loadTransactions();
}

// ── Transactions ───────────────────────────────────────────────────────────
async function loadTransactions() {
  const feedback = document.getElementById("feedback");
  const table    = document.getElementById("main-table");
  feedback.innerHTML = '<span class="spinner"></span> Loading…';
  feedback.style.display = "block";
  table.style.display = "none";

  const params = new URLSearchParams();
  const add = (id, key) => { const v = document.getElementById(id).value.trim(); if (v) params.set(key, v); };
  add("f-ticker",    "ticker");
  add("f-company",   "company");
  add("f-insider",   "insider");
  add("f-role",      "role");
  add("f-code",      "code");
  add("f-date-from", "date_from");
  add("f-date-to",   "date_to");
  const limit = document.getElementById("f-limit").value || "200";
  params.set("limit", limit);

  try {
    const res = await fetch(`${API}/transactions?${params}`);
    if (!res.ok) throw new Error(res.statusText);
    allRows = await res.json();
    setApiStatus(true, "API connected");
    renderTable();
  } catch (err) {
    setApiStatus(false, "API unreachable");
    feedback.innerHTML = '<div class="empty-state"><div class="empty-icon">⚡</div><div class="empty-text">Could not reach the API</div><div class="empty-sub">See the startup guide at the top of the page</div></div>';
    console.error(err);
  }
}

// ── Render ─────────────────────────────────────────────────────────────────
function renderTable() {
  const feedback = document.getElementById("feedback");
  const table    = document.getElementById("main-table");
  const thead    = document.getElementById("thead");
  const tbody    = document.getElementById("tbody");

  const cols = TABS[activeTab];
  const rows = sortedRows();

  const rc = document.getElementById("result-count");
  if (rc) rc.textContent = rows.length ? `${rows.length.toLocaleString()} row${rows.length !== 1 ? "s" : ""}` : "";

  if (rows.length === 0) {
    feedback.innerHTML = '<div class="empty-state"><div class="empty-icon">🔍</div><div class="empty-text">No transactions match those filters</div><div class="empty-sub">Try relaxing or clearing the filters in Step 1</div></div>';
    feedback.style.display = "block";
    table.style.display = "none";
    return;
  }

  // Header
  thead.innerHTML = "";
  const tr = document.createElement("tr");
  for (const col of cols) {
    const th = document.createElement("th");
    th.dataset.key = col.key;
    const isSorted = sortCol === col.key;
    if (isSorted) th.classList.add(sortAsc ? "sorted-asc" : "sorted-desc");
    if (NUM_KEYS.has(col.key)) th.classList.add("num");
    th.innerHTML = `${col.label}<span class="sort-arrow"></span>`;
    th.onclick = () => toggleSort(col.key);
    tr.appendChild(th);
  }
  thead.appendChild(tr);

  // Body — staggered fade-in, capped at 250 ms so large sets don't drag
  tbody.innerHTML = "";
  for (const [i, row] of rows.entries()) {
    const tr = document.createElement("tr");
    tr.style.animation = `fadeUp .2s ease ${Math.min(i * 14, 250)}ms both`;
    for (const col of cols) {
      const td = document.createElement("td");
      const v  = row[col.key];

      if (col.key === "ticker") {
        td.innerHTML = v ? `<span class="ticker-badge">${v}</span>` : "—";
      } else if (col.key === "code") {
        const cls = v === "P" ? "code-P" : v === "S" ? "code-S" : v === "A" ? "code-A" : "code-other";
        td.innerHTML = v ? `<span class="code-badge ${cls}">${v}</span>` : "—";
      } else if (PCT_KEYS.has(col.key)) {
        td.textContent = pct(v);
        if (v != null) td.className = v >= 0 ? "pos num" : "neg num";
        else td.className = "muted num";
      } else if (col.key === "shares") {
        td.textContent = v != null ? Number(v).toLocaleString() : "—";
        td.classList.add("num");
      } else if (col.key === "price") {
        td.textContent = v != null ? "$" + Number(v).toFixed(2) : "—";
        td.classList.add("num");
      } else {
        td.textContent = v ?? "—";
        if (v == null) td.className = "muted";
      }
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }

  feedback.style.display = "none";
  table.style.display = "";
}

function sortedRows() {
  if (!sortCol) return allRows;
  return [...allRows].sort((a, b) => {
    const av = a[sortCol], bv = b[sortCol];
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    const cmp = av < bv ? -1 : av > bv ? 1 : 0;
    return sortAsc ? cmp : -cmp;
  });
}

function toggleSort(key) {
  if (sortCol === key) {
    sortAsc = !sortAsc;
  } else {
    sortCol = key;
    sortAsc = false;
  }
  renderTable();
}

// ── Tabs ───────────────────────────────────────────────────────────────────
function switchTab(tab, btn) {
  activeTab = tab;
  document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
  btn.classList.add("active");
  sortCol = null;
  renderTable();
}

// ── Misc ───────────────────────────────────────────────────────────────────
function clearFilters() {
  ["f-ticker","f-company","f-insider","f-role","f-date-from","f-date-to"].forEach(id => {
    document.getElementById(id).value = "";
  });
  document.getElementById("f-code").value = "";
  document.getElementById("f-limit").value = "200";
  loadTransactions();
}

document.addEventListener("keydown", e => {
  if (e.key === "Enter") loadTransactions();
});

// ── Pattern Stats ─────────────────────────────────────────────────────────
async function loadPatternStats() {
  const body = document.getElementById("pattern-body");
  const btn  = document.getElementById("run-stats-btn");

  btn.disabled = true;
  body.innerHTML = '<div class="feedback"><span class="spinner"></span> Calculating…</div>';

  const params = new URLSearchParams();
  const add = (id, key) => { const v = document.getElementById(id).value.trim(); if (v) params.set(key, v); };
  add("f-ticker",  "ticker");
  add("f-role",    "role");
  add("f-insider", "insider");

  try {
    const res = await fetch(`${API}/stats?${params}`);
    if (!res.ok) throw new Error(res.statusText);
    const data = await res.json();
    renderPatternStats(data);
  } catch (err) {
    body.innerHTML = '<div class="feedback">Could not load pattern stats.</div>';
    console.error(err);
  } finally {
    btn.disabled = false;
  }
}

function renderPatternStats(data) {
  const body    = document.getElementById("pattern-body");
  const anyWarn = data.horizons.some(h => h.n > 0 && h.n < 10);

  const rows = data.horizons.map(h => {
    const noData = h.n === 0 || h.n == null;
    const warnN  = !noData && h.n < 10;
    const avgRet = h.avg_ret  != null ? pct(h.avg_ret)  : "—";
    const avgExc = h.avg_exc  != null ? pct(h.avg_exc)  : "—";
    const excCls = h.avg_exc  != null ? (h.avg_exc >= 0 ? "pos" : "neg") : "";
    const hitTxt = h.hit_rate != null ? (h.hit_rate * 100).toFixed(1) + "%" : "—";
    const hitCls = h.hit_rate != null ? (h.hit_rate > 0.5 ? "pos" : h.hit_rate < 0.5 ? "neg" : "") : "";
    return `
      <tr>
        <td class="horizon-label">${h.label}</td>
        <td class="num${warnN ? " warn" : ""}">${noData ? "—" : warnN ? h.n + " ⚠" : h.n}</td>
        <td class="num">${avgRet}</td>
        <td class="num ${excCls}">${avgExc}</td>
        <td class="num ${hitCls}">${hitTxt}</td>
      </tr>`;
  }).join("");

  body.innerHTML = `
    <div class="pattern-total">Based on <strong style="color:var(--text)">${data.total.toLocaleString()}</strong> matching transaction${data.total !== 1 ? "s" : ""}</div>
    <div style="overflow-x:auto">
      <table style="min-width:500px">
        <thead>
          <tr>
            <th>Horizon</th>
            <th class="num">Sample (n)</th>
            <th class="num">Avg Return</th>
            <th class="num">Avg vs SPY</th>
            <th class="num">Hit Rate vs SPY</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
    ${anyWarn ? '<div class="pattern-warn-note">⚠ Highlighted rows have fewer than 10 samples — interpret with caution.</div>' : ""}`;
}

// ── Boot ───────────────────────────────────────────────────────────────────
(async () => {
  await Promise.all([loadStats(), loadTransactions()]);
})();
