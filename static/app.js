/* STOCKSHOCK website: talks to /api, draws the planner. No build step, no framework. */
(() => {
  "use strict";
  const API = (window.STOCKSHOCK_API || "") + "/api";
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const UNIT = { hotel: "nights", flight: "seats", transfer: "seats", activity: "passes" };
  const KIND_ICON = { hotel: "🏨", flight: "✈️", transfer: "🚌", activity: "🎟️" };

  const state = {
    catalog: null, dest: "goa", custom: null, weeks: 8, budget: 100, risk: "balanced", start: null,
    plan: null, frontier: null, prod: 0, week: 0, decisions: {}, reqId: 0, addMode: false, pin: null,
  };

  // ---------- formatting ----------
  function inr(x, signed = false) {
    const s = x < 0 ? "−" : signed ? "+" : "";
    const a = Math.abs(x);
    if (a >= 1e7) return `${s}₹${(a / 1e7).toFixed(2)} Cr`;
    if (a >= 1e5) return `${s}₹${(a / 1e5).toFixed(1)} L`;
    return `${s}₹${Math.round(a).toLocaleString("en-IN")}`;
  }
  const fmtDate = (d) => new Date(d + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short" });
  const pctChange = (a, b) => (b === 0 ? 0 : ((a - b) / Math.abs(b)) * 100);

  function toast(msg) {
    const t = $("#toast"); t.textContent = msg; t.classList.add("show");
    clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("show"), 2600);
  }

  function setStatus(kind, text) {
    const s = $("#status"); s.className = "status " + kind;
    s.innerHTML = `<span class="dot"></span><span>${esc(text)}</span>`;
  }

  let firstCall = true;
  async function api(path, body) {
    const ctl = new AbortController();
    const wake = firstCall; firstCall = false;
    const slow = setTimeout(() => setStatus("busy", wake ? "Waking the server up (free hosting naps when idle)…" : "Still crunching the numbers…"), wake ? 3500 : 6000);
    const kill = setTimeout(() => ctl.abort(), 90000);
    try {
      const res = await fetch(API + path, body ? {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: ctl.signal,
      } : { signal: ctl.signal });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
      return await res.json();
    } finally { clearTimeout(slow); clearTimeout(kill); }
  }

  // ---------- background streaks (echo the deck's neon diagonals) ----------
  function streaks() {
    const c = $("#streaks"), g = c.getContext("2d");
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const cols = ["#9d7bff", "#ff3d81", "#ffd21f", "#2ee6f0"];
    let W, H, lines;
    const reset = () => {
      W = c.width = innerWidth * devicePixelRatio; H = c.height = innerHeight * devicePixelRatio;
      lines = Array.from({ length: 22 }, () => ({ x: Math.random() * W * 1.6 - W * .3, sp: .15 + Math.random() * .45, w: (1 + Math.random() * 2.5) * devicePixelRatio,
        a: .05 + Math.random() * .16, c: cols[(Math.random() * 4) | 0], len: H * (.5 + Math.random()) }));
    };
    reset(); addEventListener("resize", reset);
    (function frame() {
      g.clearRect(0, 0, W, H);
      for (const l of lines) {
        l.x += l.sp * devicePixelRatio; if (l.x > W * 1.4) l.x = -W * .4;
        const grd = g.createLinearGradient(l.x, H, l.x + l.len * .55, 0);
        grd.addColorStop(0, "transparent"); grd.addColorStop(.5, l.c); grd.addColorStop(1, "transparent");
        g.globalAlpha = l.a; g.strokeStyle = grd; g.lineWidth = l.w;
        g.beginPath(); g.moveTo(l.x, H); g.lineTo(l.x + l.len * .55, H - l.len); g.stroke();
      }
      requestAnimationFrame(frame);
    })();
  }

  // ---------- map + list ----------
  let map, markers = {}, customMarker = null;
  function initMap() {
    if (!window.L) {
      const tag = $("#leafletjs");
      $("#map").innerHTML = '<p class="muted" style="padding:12px">Loading map…</p>';
      if (tag && !tag.dataset.waiting) {
        tag.dataset.waiting = "1";
        tag.addEventListener("load", () => { $("#map").innerHTML = ""; initMap(); drawMarkers(); });
        tag.addEventListener("error", () => { $("#map").innerHTML = '<p class="muted" style="padding:12px">Map unavailable. Pick from the list below.</p>'; });
      }
      return;
    }
    map = L.map("map", { zoomControl: true, worldCopyJump: true, attributionControl: true }).setView([20, 60], 2);
    L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
      maxZoom: 10, subdomains: "abcd",
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
    }).addTo(map);
    map.on("click", (e) => {
      if (!state.addMode) return;
      state.pin = [e.latlng.lat, e.latlng.lng];
      $("#cPin").textContent = `Pin at ${state.pin[0].toFixed(2)}, ${state.pin[1].toFixed(2)}`;
      if (customMarker) customMarker.remove();
      customMarker = L.marker(state.pin, { icon: pinIcon(true) }).addTo(map);
      $("#cityDialog").showModal();
    });
  }
  const pinIcon = (sel) => L.divIcon({ className: "", html: `<div class="pinicon${sel ? " sel" : ""}"></div>`, iconSize: [14, 14], iconAnchor: [7, 7] });

  function renderDestList(filter = "") {
    const f = filter.trim().toLowerCase();
    const list = state.catalog.destinations.filter((d) => !f || `${d.name} ${d.region} ${d.country} ${d.type_label}`.toLowerCase().includes(f));
    $("#destList").innerHTML = list.map((d) => `
      <button class="dest" role="option" data-id="${d.id}" aria-selected="${!state.custom && d.id === state.dest}">
        <span><b>${esc(d.name)}</b><br><small>${esc(d.region)}</small></span><span class="tag">${esc(d.type_label)}</span>
      </button>`).join("") || '<p class="muted">No match. Add it as your own city.</p>';
  }

  function drawMarkers() {
    if (!map) return;
    Object.values(markers).forEach((m) => m.remove()); markers = {};
    for (const d of state.catalog.destinations) {
      const m = L.marker([d.lat, d.lon], { icon: pinIcon(!state.custom && d.id === state.dest), title: d.name, keyboard: false })
        .addTo(map).bindTooltip(`${d.name} · ${d.type_label}`, { direction: "top" });
      m.on("click", () => { if (!state.addMode) selectDest(d.id); });
      markers[d.id] = m;
    }
  }

  function selectDest(id) {
    state.dest = id; state.custom = null; state.decisions = {};
    if (customMarker) { customMarker.remove(); customMarker = null; }
    renderDestList($("#search").value); drawMarkers();
    const d = state.catalog.destinations.find((x) => x.id === id);
    if (map && d) map.flyTo([d.lat, d.lon], Math.max(map.getZoom(), 4), { duration: .8 });
    loadPlan();
  }

  // ---------- controls ----------
  function bindSeg(id, key) {
    $$(`#${id} button`).forEach((b) => b.addEventListener("click", () => {
      $$(`#${id} button`).forEach((x) => x.setAttribute("aria-checked", x === b));
      state[key] = key === "weeks" ? +b.dataset.v : b.dataset.v; loadPlan();
    }));
  }

  let budgetTimer;
  function bindControls() {
    bindSeg("weeksSeg", "weeks"); bindSeg("riskSeg", "risk");
    $("#budget").addEventListener("input", (e) => {
      state.budget = +e.target.value; $("#budgetOut").textContent = state.budget + "%";
      clearTimeout(budgetTimer); budgetTimer = setTimeout(loadPlan, 350);
    });
    $("#start").addEventListener("change", (e) => { state.start = e.target.value; loadPlan(); });
    $("#search").addEventListener("input", (e) => renderDestList(e.target.value));
    $("#destList").addEventListener("click", (e) => { const b = e.target.closest(".dest"); if (b) selectDest(b.dataset.id); });
    $("#approveAll").addEventListener("click", () => {
      if (!state.plan) return;
      state.plan.products.forEach((p, pi) => p.weeks.forEach((w, wi) => { if (w.action === "BUY") state.decisions[`${pi}:${wi}`] = "yes"; }));
      renderPlanList(); toast("All BUY lines approved");
    });
    $("#csvBtn").addEventListener("click", downloadCSV);
    $("#copyCurl").addEventListener("click", async () => {
      try { await navigator.clipboard.writeText($("#curl").textContent); toast("Copied"); }
      catch { const r = document.createRange(); r.selectNodeContents($("#curl")); getSelection().removeAllRanges(); getSelection().addRange(r); toast("Selected, press Ctrl+C"); }
    });
  }

  // ---------- custom city dialog ----------
  function bindDialog() {
    const dlg = $("#cityDialog");
    $("#cType").innerHTML = state.catalog.types.map((t) => `<option value="${t.id}">${esc(t.label)}</option>`).join("");
    $("#cType").value = "hills";
    const spark = () => {
      const t = state.catalog.types.find((x) => x.id === $("#cType").value), m = t.season, mx = Math.max(...m);
      const pts = m.map((v, i) => `${10 + i * 20},${44 - (v / mx) * 36}`).join(" ");
      $("#cSpark").innerHTML = `<polyline points="${pts}" fill="none" stroke="${css("--volt")}" stroke-width="2" stroke-linejoin="round"/>` +
        "JFMAMJJASOND".split("").map((c, i) => `<text x="${10 + i * 20}" y="47" text-anchor="middle" style="font-size:8px">${c}</text>`).join("");
    };
    $("#cType").addEventListener("change", spark); spark();
    $("#cPop").addEventListener("input", (e) => ($("#cPopOut").textContent = e.target.value));
    $("#cPrice").addEventListener("input", (e) => ($("#cPriceOut").textContent = (+e.target.value).toFixed(1) + "×"));
    $("#addCityBtn").addEventListener("click", () => {
      state.addMode = true; dlg.returnValue = ""; $("#map").classList.add("adding");
      $("#mapHint").textContent = "Click the map to drop your city's pin, or skip it in the form.";
      dlg.showModal(); $("#cName").focus();
    });
    const close = () => { state.addMode = false; $("#map").classList.remove("adding"); $("#mapHint").textContent = "Click a pin to plan for that destination."; };
    $("#cCancel").addEventListener("click", () => { dlg.close(); close(); });
    dlg.addEventListener("close", () => { if (dlg.returnValue !== "pin") close(); });
    // let people drop a pin: hide the dialog until they click the map
    $("#cPin").addEventListener("click", () => { dlg.close("pin"); });
    $("#cPin").title = "Click, then click the map to drop a pin";
    $("#cPin").style.cursor = "pointer";
    $("#cityForm").addEventListener("submit", (e) => {
      e.preventDefault();
      const name = $("#cName").value.trim(); if (!name) return;
      state.custom = { name, type: $("#cType").value, popularity: +$("#cPop").value, price_level: +$("#cPrice").value,
        hub: $("#cHub").value, airport: $("#cApt").value || null, lat: state.pin ? state.pin[0] : null, lon: state.pin ? state.pin[1] : null };
      state.decisions = {}; dlg.close(); close(); renderDestList($("#search").value); drawMarkers();
      if (map && state.pin) { customMarker && customMarker.remove(); customMarker = L.marker(state.pin, { icon: pinIcon(true) }).addTo(map); map.flyTo(state.pin, 5); }
      loadPlan();
    });
  }

  // ---------- load + render ----------
  function body() {
    const b = { weeks: state.weeks, budget: state.budget, risk: state.risk, start: state.start || null };
    if (state.custom) b.custom = state.custom; else b.dest = state.dest;
    return b;
  }

  async function loadPlan() {
    const id = ++state.reqId;
    setStatus("busy", "Forecasting and optimising…");
    $("#kpis").classList.add("skeleton");
    try {
      const t0 = performance.now();
      const plan = await api("/plan", body());
      if (id !== state.reqId) return;
      state.plan = plan; state.prod = Math.min(state.prod, plan.products.length - 1); state.week = 0;
      renderAll();
      setStatus("", `Plan ready in ${((performance.now() - t0) / 1000).toFixed(1)} s · ${plan.scenarios} demand scenarios`);
      loadFrontier(id);
    } catch (err) {
      if (id !== state.reqId) return;
      setStatus("err", "Couldn't reach the planner API. " + (err.message || ""));
      $("#kpis").classList.remove("skeleton");
    }
  }

  async function loadFrontier(id) {
    $("#frontierChart").innerHTML = `<text x="380" y="150" text-anchor="middle">Tracing the risk–return curve…</text>`;
    try {
      const f = await api("/frontier", body());
      if (id !== state.reqId) return;
      state.frontier = f; drawFrontier();
    } catch { $("#frontierChart").innerHTML = `<text x="380" y="150" text-anchor="middle">Curve unavailable right now.</text>`; }
  }

  function renderAll() {
    const p = state.plan, d = p.destination;
    $("#destName").textContent = d.name;
    $("#destMeta").textContent = `${d.type_label} · ${d.region}${d.country && d.country !== d.region ? " · " + d.country : ""}`;
    if (!state.start) $("#start").value = p.start;
    renderKPIs(); renderReplay(); renderProdTabs(); drawDemand(); renderWeekTabs(); renderPlanList(); renderTicker(); renderCurl(); heroProof();
  }

  function countUp(el, to, fmt) {
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) { el.textContent = fmt(to); return; }
    const t0 = performance.now(), from = 0, dur = 900;
    const step = (t) => { const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3); el.textContent = fmt(from + (to - from) * e); if (k < 1) requestAnimationFrame(step); };
    requestAnimationFrame(step);
  }

  function renderKPIs() {
    const s = state.plan.kpis.stockshock, t = state.plan.kpis.today;
    const pc = pctChange(s.expected_profit, t.expected_profit), sp = pctChange(s.spend, t.spend);
    const worst = (x) => (x <= 0 ? `${inr(-x)} profit` : `${inr(x)} loss`);
    const cards = [
      { c: "--cyan", k: "Expected profit", v: s.expected_profit, f: (x) => inr(x), d: `today's rule <b>${inr(t.expected_profit)}</b><span class="delta ${pc >= 0 ? "up" : "down"}">${pc >= 0 ? "+" : ""}${pc.toFixed(0)}%</span>` },
      { c: "--volt", k: "Worst 5% of outcomes", v: -s.worst5_loss, f: (x) => (x >= 0 ? inr(x) + " profit" : inr(-x) + " loss"), d: `today's rule <b>${worst(t.worst5_loss)}</b>` },
      { c: "--pink", k: "Cash tied up in pre-buys", v: s.spend, f: (x) => inr(x), d: `today's rule <b>${inr(t.spend)}</b><span class="delta ${sp <= 0 ? "up" : "down"}">${sp >= 0 ? "+" : ""}${sp.toFixed(0)}%</span>` },
      { c: "--violet", k: "Bookings served", v: s.served_pct, f: (x) => x.toFixed(1) + "%", d: `today's rule <b>${t.served_pct.toFixed(1)}%</b> · ${Math.round(s.unsold_units)} vs ${Math.round(t.unsold_units)} unsold` },
    ];
    $("#kpis").classList.remove("skeleton");
    $("#kpis").innerHTML = cards.map((c, i) => `<div class="kpi" style="--c:var(${c.c})"><div class="k">${c.k}</div><div class="v" id="kv${i}">–</div><div class="d">${c.d}</div></div>`).join("");
    cards.forEach((c, i) => countUp($("#kv" + i), c.v, c.f));
  }

  function renderReplay() {
    const r = state.plan.replay, el = $("#replay");
    if (!r) { el.hidden = true; return; }
    el.hidden = false;
    const g = r.profit_gain;
    el.innerHTML = `<div><p class="eyebrow">Proof · replay on last year</p><div class="big">${inr(g, true)}</div></div>
      <p>Same ${state.plan.weeks} weeks one year earlier (from ${fmtDate(r.start)}), planned with only the data available then and scored on what actually sold:
      profit ${inr(r.stockshock.expected_profit)} vs ${inr(r.today.expected_profit)} with today's rule,
      ${Math.round(r.today.unsold_units)} → ${Math.round(r.stockshock.unsold_units)} unsold units, bookings served ${r.stockshock.served_pct}% vs ${r.today.served_pct}%.</p>`;
  }

  function renderProdTabs() {
    $("#prodTabs").innerHTML = state.plan.products.map((p, i) =>
      `<button class="tab" role="tab" aria-selected="${i === state.prod}" data-i="${i}">${KIND_ICON[p.kind] || ""} ${esc(p.name)}</button>`).join("");
    $$("#prodTabs .tab").forEach((b) => b.addEventListener("click", () => { state.prod = +b.dataset.i; renderProdTabs(); drawDemand(); }));
  }

  function niceMax(v) { const m = Math.pow(10, Math.floor(Math.log10(Math.max(v, 1)))); for (const k of [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (k * m >= v) return k * m; return v; }
  const pathOf = (pts) => pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join("");
  function lineLen(pts) { let s = 0; for (let i = 1; i < pts.length; i++) s += Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]); return Math.ceil(s); }

  function drawDemand() {
    const p = state.plan.products[state.prod], w = p.weeks, n = w.length;
    const W = 760, H = 300, L = 48, R = 14, T = 22, B = 34;
    const ymax = niceMax(Math.max(...w.map((x) => Math.max(x.p90, x.q, x.q_today, x.last_year || 0))) * 1.05);
    const step = (W - L - R) / n, X = (i) => L + step * (i + .5), Y = (v) => T + (H - T - B) * (1 - v / ymax);
    let g = "";
    for (let k = 0; k <= 4; k++) { const v = (ymax * k) / 4; g += `<line class="grid" x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}"/><text x="${L - 8}" y="${Y(v) + 4}" text-anchor="end">${Math.round(v)}</text>`; }
    w.forEach((x, i) => {
      g += `<text x="${X(i)}" y="${H - 14}" text-anchor="middle">${fmtDate(x.week)}</text>`;
      if (x.festival) g += `<rect x="${X(i) - step / 2}" y="${T}" width="${step}" height="${H - T - B}" fill="${css("--volt")}" fill-opacity=".06"/><text x="${X(i)}" y="${T + 12}" text-anchor="middle" style="fill:${css("--volt")};font-size:10px">★ ${esc(x.festival.split(" ")[0])}</text>`;
    });
    const band = pathOf(w.map((x, i) => [X(i), Y(x.p90)])) + w.slice().reverse().map((x, j) => `L${X(n - 1 - j).toFixed(1)} ${Y(x.p10).toFixed(1)}`).join("") + "Z";
    g += `<path class="fade-in" d="${band}" fill="${css("--violet")}" fill-opacity=".22"/>`;
    const bw = Math.min(28, step * .42);
    w.forEach((x, i) => {
      g += `<rect class="grow-bar" style="animation-delay:${i * 40}ms" x="${X(i) - bw / 2}" y="${Y(x.q)}" width="${bw}" height="${Y(0) - Y(x.q)}" rx="4" fill="${css("--cyan")}" fill-opacity=".85"><title>STOCKSHOCK pre-buy ${x.q}</title></rect>`;
      g += `<line x1="${X(i) - step * .38}" x2="${X(i) + step * .38}" y1="${Y(x.q_today)}" y2="${Y(x.q_today)}" stroke="${css("--pink")}" stroke-width="3" stroke-linecap="round"><title>Today's rule ${x.q_today}</title></line>`;
    });
    const ly = w.map((x, i) => (x.last_year != null ? [X(i), Y(x.last_year)] : null)).filter(Boolean);
    if (ly.length > 1) g += `<path d="${pathOf(ly)}" fill="none" stroke="${css("--muted")}" stroke-width="1.6" stroke-dasharray="2 4"/>`;
    const lk = w.map((x, i) => [X(i), Y(x.p50)]);
    g += `<path class="draw" style="--len:${lineLen(lk)}" d="${pathOf(lk)}" fill="none" stroke="${css("--volt")}" stroke-width="2.6" stroke-linejoin="round"/>`;
    lk.forEach((pt, i) => (g += `<circle cx="${pt[0]}" cy="${pt[1]}" r="3.5" fill="${css("--volt")}"><title>Likely ${w[i].p50} (range ${w[i].p10}–${w[i].p90})</title></circle>`));
    g += `<text x="${W - R}" y="12" text-anchor="end">${UNIT[p.kind]} per week</text>`;
    $("#demandChart").innerHTML = g;
  }

  function renderWeekTabs() {
    const w = state.plan.products[0].weeks;
    $("#weekTabs").innerHTML = w.map((x, i) => `<button class="tab" role="tab" aria-selected="${i === state.week}" data-i="${i}">${fmtDate(x.week)}${x.festival ? " ★" : ""}</button>`).join("");
    $$("#weekTabs .tab").forEach((b) => b.addEventListener("click", () => { state.week = +b.dataset.i; renderWeekTabs(); renderPlanList(); }));
  }

  function renderPlanList() {
    const wi = state.week;
    $("#planList").innerHTML = state.plan.products.map((p, pi) => {
      const x = p.weeks[wi], key = `${pi}:${wi}`, dec = state.decisions[key];
      const chips = (x.drivers || []).map((c) => `<span class="chip${c === x.festival ? " fest" : ""}">${esc(c)}</span>`).join("");
      return `<div class="line ${dec === "yes" ? "ok" : dec === "no" ? "no" : ""}">
        <div class="p"><b>${KIND_ICON[p.kind] || ""} ${esc(p.name)}</b><small>${inr(p.unit_cost)} cost · sells ${inr(p.sell_price)}</small></div>
        <span class="badge ${x.action}">${x.action}</span>
        <div class="qty">${x.q} ${UNIT[p.kind]}<small>today's rule ${x.q_today} · likely ${x.p50} (${x.p10}–${x.p90})</small></div>
        <div class="why">${esc(x.reason)}<div class="chips">${chips}</div></div>
        <div class="acts">
          <button class="icon-btn yes" type="button" aria-label="Approve ${esc(p.name)}" aria-pressed="${dec === "yes"}" data-k="${key}" data-v="yes">✓</button>
          <button class="icon-btn nope" type="button" aria-label="Reject ${esc(p.name)}" aria-pressed="${dec === "no"}" data-k="${key}" data-v="no">✕</button>
        </div></div>`;
    }).join("");
    $$("#planList .icon-btn").forEach((b) => b.addEventListener("click", () => {
      const k = b.dataset.k, v = b.dataset.v; state.decisions[k] = state.decisions[k] === v ? undefined : v; renderPlanList();
    }));
    updateApproved();
  }

  function updateApproved() {
    let n = 0, spend = 0;
    for (const [k, v] of Object.entries(state.decisions)) {
      if (v !== "yes") continue;
      const [pi, wi] = k.split(":").map(Number), p = state.plan.products[pi]; if (!p) continue;
      n++; spend += p.weeks[wi].q * p.unit_cost;
    }
    $("#apprCount").textContent = n; $("#apprSpend").textContent = inr(spend);
  }

  function downloadCSV() {
    if (!state.plan) return;
    const rows = [["destination", "week", "product", "decision", "pre_buy_units", "todays_rule_units", "likely_demand", "low", "high", "unit_cost", "approved", "reason"]];
    state.plan.products.forEach((p, pi) => p.weeks.forEach((x, wi) => rows.push([state.plan.destination.name, x.week, p.name, x.action, x.q, x.q_today, x.p50, x.p10, x.p90, p.unit_cost, state.decisions[`${pi}:${wi}`] || "", x.reason])));
    const csv = rows.map((r) => r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",")).join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = `stockshock_${state.plan.destination.id}_${state.plan.start}.csv`; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }

  function drawFrontier() {
    const f = state.frontier, s = state.plan.kpis.stockshock;
    const pts = f.points.map((p) => [p.worst5_loss, p.expected_profit]);
    const today = [f.today.worst5_loss, f.today.expected_profit], pick = [s.worst5_loss, s.expected_profit];
    const xs = [...pts.map((p) => p[0]), today[0], pick[0], 0], ys = [...pts.map((p) => p[1]), today[1], pick[1], 0];
    const W = 760, H = 300, L = 70, R = 24, T = 20, B = 46;
    const span = Math.max(...xs) - Math.min(...xs) || 1, x0 = Math.min(...xs) - span * .08, x1 = Math.max(...xs) + span * .08;
    const y0 = Math.min(0, Math.min(...ys)), y1 = niceMax(Math.max(...ys) * 1.08);
    const X = (v) => L + ((W - L - R) * (v - x0)) / (x1 - x0), Y = (v) => T + (H - T - B) * (1 - (v - y0) / (y1 - y0));
    let g = "";
    for (let k = 0; k <= 4; k++) { const v = y0 + ((y1 - y0) * k) / 4; g += `<line class="grid" x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}"/><text x="${L - 8}" y="${Y(v) + 4}" text-anchor="end">${inr(v)}</text>`; }
    for (let k = 0; k <= 4; k++) { const v = x0 + ((x1 - x0) * k) / 4; g += `<text x="${X(v)}" y="${H - B + 18}" text-anchor="middle">${inr(v)}</text>`; }
    g += `<line x1="${X(0)}" x2="${X(0)}" y1="${T}" y2="${H - B}" stroke="${css("--muted")}" stroke-dasharray="3 4" stroke-opacity=".5"/>`;
    g += `<text x="${(L + W - R) / 2}" y="${H - 8}" text-anchor="middle">Worst-5% loss (left of the dashed line = still in profit)</text>`;
    g += `<text transform="translate(16 ${(T + H - B) / 2}) rotate(-90)" text-anchor="middle">Expected profit</text>`;
    const fp = pts.map((p) => [X(p[0]), Y(p[1])]);
    if (fp.length > 1) g += `<path class="draw" style="--len:${lineLen(fp)}" d="${pathOf(fp)}" fill="none" stroke="${css("--cyan")}" stroke-width="2.4"/>`;
    fp.forEach((p) => (g += `<circle class="fade-in" cx="${p[0]}" cy="${p[1]}" r="4.5" fill="${css("--cyan")}"/>`));
    g += `<circle cx="${X(today[0])}" cy="${Y(today[1])}" r="8" fill="${css("--pink")}"/><text x="${X(today[0])}" y="${Y(today[1]) - 14}" text-anchor="middle" style="fill:${css("--pink")};font-weight:700">Today's rule</text>`;
    g += `<circle cx="${X(pick[0])}" cy="${Y(pick[1])}" r="9" fill="${css("--volt")}" stroke="${css("--ink")}" stroke-width="2"/><text x="${X(pick[0])}" y="${Y(pick[1]) + 26}" text-anchor="middle" style="fill:${css("--volt")};font-weight:700">STOCKSHOCK plan</text>`;
    $("#frontierChart").innerHTML = g;
    $("#frontierNote").textContent = `Today's rule: ${inr(f.today.expected_profit)} expected, ${f.today.worst5_loss > 0 ? inr(f.today.worst5_loss) + " loss" : inr(-f.today.worst5_loss) + " profit"} in the worst 5%.`;
  }

  function renderTicker() {
    const p = state.plan, items = [];
    p.products.forEach((pr) => pr.weeks.slice(0, 3).forEach((w) => items.push(
      `<span>${esc(p.destination.name)} · ${esc(pr.name)} · ${fmtDate(w.week)} <b style="color:${w.action === "BUY" ? css("--cyan") : w.action === "WAIT" ? css("--volt") : css("--pink")}">${w.action} ${w.q}</b> <span class="muted">(today ${w.q_today})</span></span>`)));
    $("#ticker").innerHTML = items.join("") + items.join("");
  }

  function renderCurl() {
    const origin = window.STOCKSHOCK_API || location.origin;
    const b = body(); delete b.start;
    $("#curl").textContent = state.custom
      ? `curl -X POST ${origin}/api/plan \\\n  -H "Content-Type: application/json" \\\n  -d '${JSON.stringify(b)}'`
      : `curl "${origin}/api/plan?dest=${state.dest}&weeks=${state.weeks}&budget=${state.budget}&risk=${state.risk}"`;
  }

  function heroProof() {
    const r = state.plan.replay; if (!r) return;
    $('[data-k="gain"]').textContent = inr(r.profit_gain, true);
    $("#heroGainLabel").textContent = `${state.plan.destination.name}, same ${state.plan.weeks} weeks last year, vs today's rule`;
    $('[data-k="secs"]').textContent = `${state.plan.seconds.toFixed(1)} s`;
  }

  // ---------- boot ----------
  async function boot() {
    streaks(); bindControls();
    setStatus("busy", "Loading destinations…");
    try {
      state.catalog = await api("/catalog");
    } catch (e) {
      setStatus("err", "Couldn't reach the planner API. Start it with: python dev_server.py");
      return;
    }
    $('[data-k="dest"]').textContent = state.catalog.destinations.length;
    $("#search").placeholder = `Search ${state.catalog.destinations.length} destinations…`;
    initMap(); renderDestList(); drawMarkers(); bindDialog();
    const fromHash = location.hash.slice(1);
    if (state.catalog.destinations.some((d) => d.id === fromHash)) state.dest = fromHash;
    loadPlan();
  }
  boot();
})();
