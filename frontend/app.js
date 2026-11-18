/* STOCKSHOCK v3 — landing globe + command centre. Vanilla JS, no libraries: nothing to download before the first paint. */
(() => {
  "use strict";
  const API = (window.STOCKSHOCK_API || "") + "/api";
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const UNIT = { hotel: "nights", flight: "seats", transfer: "seats", activity: "passes" };
  const ICON = { hotel: "🏨", flight: "✈", transfer: "🚆", activity: "🎟" };
  const SEG = { business: ["Business", "--violet"], transit: ["Airport", "--cyan"], leisure: ["Leisure", "--pink"], air: ["Air", "--volt"], experience: ["Experiences", "--orange"], ground: ["Ground", "--good"] };
  const RISK_TXT = {
    careful: "Careful protects the downside: worst-5% loss capped 35% below today's rule, every rupee of risk penalised.",
    balanced: "Balanced keeps the worst case no worse than today's rule, with a light penalty on downside risk.",
    bold: "Bold chases expected profit: no cap, pre-buys more to serve every peak.",
  };
  const RISK_COL = { careful: "--cyan", balanced: "--volt", bold: "--pink" };
  const MODS = {
    flights: { title: "Flights", kinds: ["flight"], icon: "✈" },
    hotels: { title: "Hotels", kinds: ["hotel"], icon: "🏨" },
    experiences: { title: "Experiences", kinds: ["activity", "transfer"], icon: "🎟" },
  };

  // ---------- formatting ----------
  function inr(x, signed = false) {
    const s = x < 0 ? "−" : signed ? "+" : "", a = Math.abs(x);
    if (a >= 1e7) return `${s}₹${(a / 1e7).toFixed(2)} Cr`;
    if (a >= 1e5) return `${s}₹${(a / 1e5).toFixed(1)} L`;
    return `${s}₹${Math.round(a).toLocaleString("en-IN")}`;
  }
  const fmtDate = (d) => new Date(d + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short" });
  const pct = (a, b) => (b === 0 ? 0 : ((a - b) / Math.abs(b)) * 100);
  const flag = (cc) => (cc && cc.length === 2 ? String.fromCodePoint(...[...cc.toUpperCase()].map((c) => 0x1f1a5 + c.charCodeAt(0))) : "📍");
  const fmtPop = (p) => (p >= 1e6 ? (p / 1e6).toFixed(1) + " M" : p >= 1e3 ? Math.round(p / 1e3) + " k" : "—");
  const pathOf = (pts) => pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join("");
  const lineLen = (pts) => { let s = 0; for (let i = 1; i < pts.length; i++) s += Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]); return Math.ceil(s); };
  const niceMax = (v) => { const m = Math.pow(10, Math.floor(Math.log10(Math.max(v, 1)))); for (const k of [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (k * m >= v) return k * m; return v; };
  function toast(msg) { const t = $("#toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove("show"), 2400); }
  function countUp(el, to, fmt, dur = 800) {
    if (!el) return;
    if (REDUCED) { el.textContent = fmt(to); return; }
    const t0 = performance.now();
    const step = (t) => { const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3); el.textContent = fmt(to * e); if (k < 1) requestAnimationFrame(step); };
    requestAnimationFrame(step);
  }

  // ---------- API with response cache and per-channel cancel ----------
  const cache = new Map(), inflight = {};
  let lastMs = null;
  async function api(path, { channel, body } = {}) {
    const key = path + (body ? JSON.stringify(body) : "");
    if (cache.has(key)) return cache.get(key);
    if (channel && inflight[channel]) inflight[channel].abort();
    const ctl = new AbortController(); if (channel) inflight[channel] = ctl;
    const t0 = performance.now();
    tele("busy");
    try {
      const res = await fetch(API + path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: ctl.signal } : { signal: ctl.signal });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || data.error || res.statusText);
      lastMs = Math.round(performance.now() - t0); tele("ok");
      if (cache.size > 120) cache.delete(cache.keys().next().value);
      cache.set(key, data);
      return data;
    } catch (e) { if (e.name !== "AbortError") tele("err"); throw e; }
    finally { if (channel && inflight[channel] === ctl) delete inflight[channel]; }
  }
  // fire-and-forget: have the server pre-compute forecasts for destinations the user is likely to open next
  const warmed = new Set();
  function prewarm(ids) {
    ids = ids.filter((i) => i && !warmed.has(i)); if (!ids.length) return;
    ids.forEach((i) => warmed.add(i));
    fetch(API + "/warm?ids=" + encodeURIComponent(ids.join(","))).catch(() => {});
  }
  function tele(kind) {
    const d = $("#teleDot"), t = $("#teleTxt"), p = $("#livePill");
    if (d) d.className = "dot " + kind;
    if (t) t.textContent = kind === "busy" ? "engine · computing" : kind === "err" ? "engine · offline" : `engine · ${lastMs ?? "–"} ms`;
    if (p && kind === "ok") { p.classList.add("on"); $("#liveTxt").textContent = `Engine online · ${lastMs} ms`; }
  }

  // ---------- orders (kept in this browser) ----------
  const Orders = {
    list: [], seq: 0,
    load() { try { this.list = JSON.parse(localStorage.getItem("ss_orders") || "[]"); } catch { this.list = []; } },
    save() { try { localStorage.setItem("ss_orders", JSON.stringify(this.list)); } catch { /* storage off: keep in memory */ } updateCart(); },
    key: (o) => [o.mod, o.where, o.item, o.week].join("|"),
    has(k) { return this.list.some((o) => o.key === k && o.status !== "cancelled"); },
    add(o) {
      const key = this.key(o);
      if (this.has(key)) return false;
      this.list.unshift({ ...o, key, id: "SS-" + (Date.now().toString(36) + (++this.seq).toString(36)).toUpperCase().slice(-7), status: "pending", at: Date.now() });
      return true;
    },
  };
  function updateCart() {
    const live = Orders.list.filter((o) => o.status !== "cancelled"), pend = live.filter((o) => o.status === "pending");
    $("#cartTotal").textContent = inr(live.reduce((a, o) => a + o.total, 0));
    $("#cartCount").textContent = live.length;
    $("#railCount").hidden = !pend.length; $("#railCount").textContent = pend.length;
    const c = $(".cart"); c.classList.remove("bump"); void c.offsetWidth; c.classList.add("bump");
  }

  // ---------- background streaks ----------
  function streaks() {
    if (REDUCED) return;
    const c = $("#streaks"), g = c.getContext("2d"), cols = ["#9d7bff", "#ff3d81", "#ffd21f", "#2ee6f0"];
    let W, H, L;
    const reset = () => { W = c.width = innerWidth; H = c.height = innerHeight; L = Array.from({ length: 16 }, () => ({ x: Math.random() * W * 1.6 - W * .3, sp: .15 + Math.random() * .4, w: 1 + Math.random() * 2, a: .04 + Math.random() * .12, c: cols[(Math.random() * 4) | 0], len: H * (.5 + Math.random()) })); };
    reset(); addEventListener("resize", reset);
    (function f() {
      if (!document.hidden) {
        g.clearRect(0, 0, W, H);
        for (const l of L) {
          l.x += l.sp; if (l.x > W * 1.4) l.x = -W * .4;
          const gr = g.createLinearGradient(l.x, H, l.x + l.len * .55, 0); gr.addColorStop(0, "transparent"); gr.addColorStop(.5, l.c); gr.addColorStop(1, "transparent");
          g.globalAlpha = l.a; g.strokeStyle = gr; g.lineWidth = l.w; g.beginPath(); g.moveTo(l.x, H); g.lineTo(l.x + l.len * .55, H - l.len); g.stroke();
        }
      }
      requestAnimationFrame(f);
    })();
  }

  // ---------- landing sparks: twinkling star points that throw tiny electric arcs ----------
  function sparks() {
    const c = $("#sparks"); if (!c || REDUCED) return;
    const g = c.getContext("2d"), DPR = Math.min(devicePixelRatio || 1, 2), COL = ["#ffd21f", "#2ee6f0", "#ffffff", "#9d7bff", "#ff3d81"];
    let W = 0, H = 0, stars = [], bolts = [], embers = [], last = 0, nextBolt = 0, mouse = null;
    const size = () => {
      const r = c.getBoundingClientRect(); W = r.width; H = r.height; c.width = W * DPR; c.height = H * DPR; g.setTransform(DPR, 0, 0, DPR, 0, 0);
      stars = Array.from({ length: Math.round(Math.min(90, W * H / 14000)) }, () => ({ x: Math.random() * W, y: Math.random() * H, r: .5 + Math.random() * 1.3,
        ph: Math.random() * 6.28, sp: .6 + Math.random() * 1.8, c: COL[(Math.random() * 3) | 0], cross: Math.random() < .28 }));
    };
    const bolt = (x, y) => {   // a jagged 3-5 segment arc, 8-22 px long
      const n = 3 + ((Math.random() * 3) | 0), ang = Math.random() * 6.28, len = 12 + Math.random() * 16, pts = [[x, y]];
      for (let i = 1; i <= n; i++) { const d = len * i / n, j = (Math.random() - .5) * 9; pts.push([x + Math.cos(ang) * d - Math.sin(ang) * j, y + Math.sin(ang) * d + Math.cos(ang) * j]); }
      const col = Math.random() < .6 ? "#ffd21f" : "#2ee6f0";
      bolts.push({ pts, col, life: 0, max: 180 + Math.random() * 160 });
      for (let i = 0; i < 3; i++) embers.push({ x, y, vx: (Math.random() - .5) * .09, vy: (Math.random() - .5) * .09, life: 0, max: 380 + Math.random() * 300, col });
    };
    size(); addEventListener("resize", size);
    $("#landing").addEventListener("pointermove", (e) => { const r = c.getBoundingClientRect(); mouse = { x: e.clientX - r.left, y: e.clientY - r.top, t: performance.now() }; });
    (function f(t) {
      requestAnimationFrame(f);
      if (document.hidden || $("#landing").hidden) { last = t; return; }
      const dt = Math.min(50, t - (last || t)); last = t;
      g.clearRect(0, 0, W, H);
      for (const s of stars) {   // twinkle
        const a = .25 + .75 * Math.max(0, Math.sin(s.ph + t / 1000 * s.sp)) ** 3;
        g.globalAlpha = a; g.fillStyle = s.c; g.beginPath(); g.arc(s.x, s.y, s.r, 0, 6.283); g.fill();
        if (s.cross && a > .6) { g.strokeStyle = s.c; g.lineWidth = .7; g.globalAlpha = (a - .6) * 1.8; const k = s.r * 5 * a;
          g.beginPath(); g.moveTo(s.x - k, s.y); g.lineTo(s.x + k, s.y); g.moveTo(s.x, s.y - k); g.lineTo(s.x, s.y + k); g.stroke(); }
      }
      if (t > nextBolt && stars.length) {   // a spark jumps off a random star every ~0.3 s
        const s = stars[(Math.random() * stars.length) | 0]; bolt(s.x, s.y); nextBolt = t + 120 + Math.random() * 260;
      }
      if (mouse && t - mouse.t < 120 && Math.random() < .25) bolt(mouse.x + (Math.random() - .5) * 30, mouse.y + (Math.random() - .5) * 30);
      g.lineCap = "round"; g.lineJoin = "round";
      bolts = bolts.filter((b) => (b.life += dt) < b.max);
      for (const b of bolts) {
        const p = b.life / b.max, flick = Math.random() < .25 ? .35 : 1;
        g.globalAlpha = (1 - p) * flick; g.strokeStyle = b.col; g.shadowColor = b.col; g.shadowBlur = 12; g.lineWidth = 1.6;
        g.beginPath(); b.pts.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y))); g.stroke();
        g.shadowBlur = 0; g.strokeStyle = "#fff"; g.lineWidth = .5; g.globalAlpha *= .9; g.stroke();
      }
      embers = embers.filter((e) => (e.life += dt) < e.max);
      for (const e of embers) { e.x += e.vx * dt; e.y += e.vy * dt; g.globalAlpha = (1 - e.life / e.max) * .9; g.fillStyle = e.col; g.fillRect(e.x - .6, e.y - .6, 1.2, 1.2); }
      g.globalAlpha = 1; g.shadowBlur = 0;
    })(0);
  }

  // ---------- globe: drag follows the mouse, with inertia ----------
  const geo = { dots: [], lights: [], top: [] };
  class Globe {
    constructor(canvas, opts = {}) {
      this.c = canvas; this.g = canvas.getContext("2d"); this.o = opts;
      this.rot = -78; this.tilt = -16; this.vr = 0; this.vt = 0; this.drag = null; this.idle = 0; this.target = null; this.mark = null; this.visible = true;
      const HUB = [[28.56, 77.1], [19.09, 72.87], [13.2, 77.7]];
      this.newArc = () => { const h = HUB[(Math.random() * 3) | 0], d = geo.top[(Math.random() * Math.min(160, geo.top.length)) | 0] || [0, "", "", 25, 55]; return { a: h, b: [d[3], d[4]], t: 0, sp: .004 + Math.random() * .004 }; };
      this.arcs = opts.arcs === false ? [] : Array.from({ length: 9 }, () => ({ ...this.newArc(), t: Math.random() }));
      this.size(); addEventListener("resize", () => this.size());
      if (opts.interactive) this.bind();
      new IntersectionObserver((es) => { this.visible = es[0].isIntersecting; if (this.visible) this.loop(); }).observe(canvas);
    }
    size() { const r = this.c.getBoundingClientRect(), dpr = Math.min(devicePixelRatio, 2); this.c.width = Math.max(1, r.width * dpr); this.c.height = Math.max(1, r.height * dpr); this.dpr = dpr; }
    bind() {
      const c = this.c;
      c.addEventListener("pointerdown", (e) => { this.drag = { x: e.clientX, y: e.clientY, t: performance.now() }; this.vr = this.vt = 0; this.target = null; c.setPointerCapture(e.pointerId); c.classList.add("dragging"); const h = $("#dragHint"); if (h) h.style.opacity = 0; });
      c.addEventListener("pointermove", (e) => {
        if (!this.drag) return;
        const now = performance.now(), dt = Math.max(8, now - this.drag.t), dx = e.clientX - this.drag.x, dy = e.clientY - this.drag.y;
        const k = 180 / (c.getBoundingClientRect().width * .9);  // a drag across the globe turns it about half a revolution
        this.rot += dx * k; this.tilt = Math.max(-70, Math.min(70, this.tilt + dy * k));
        this.vr = (dx * k) / dt * 16; this.vt = (dy * k) / dt * 16;
        this.drag = { x: e.clientX, y: e.clientY, t: now };
      });
      const up = () => { if (!this.drag) return; this.drag = null; this.idle = performance.now(); c.classList.remove("dragging"); };
      c.addEventListener("pointerup", up); c.addEventListener("pointercancel", up);
    }
    proj(lat, lon, R, cx, cy) {
      const l = (lon + this.rot) * Math.PI / 180, p = lat * Math.PI / 180, t = this.tilt * Math.PI / 180;
      const x = Math.cos(p) * Math.sin(l), y0 = Math.sin(p), z0 = Math.cos(p) * Math.cos(l);
      return [cx + R * x, cy - R * (y0 * Math.cos(t) - z0 * Math.sin(t)), y0 * Math.sin(t) + z0 * Math.cos(t)];
    }
    slerp(a, b, t) {
      const v = (la, lo) => { la *= Math.PI / 180; lo *= Math.PI / 180; return [Math.cos(la) * Math.cos(lo), Math.cos(la) * Math.sin(lo), Math.sin(la)]; };
      const A = v(...a), B = v(...b), d = Math.acos(Math.min(1, A[0] * B[0] + A[1] * B[1] + A[2] * B[2])) || 1e-6, s1 = Math.sin((1 - t) * d) / Math.sin(d), s2 = Math.sin(t * d) / Math.sin(d);
      const w = [A[0] * s1 + B[0] * s2, A[1] * s1 + B[1] * s2, A[2] * s1 + B[2] * s2];
      return [Math.asin(w[2]) * 180 / Math.PI, Math.atan2(w[1], w[0]) * 180 / Math.PI, Math.sin(Math.PI * t) * d];
    }
    focus(lat, lon) { this.target = [-lon, Math.max(-50, Math.min(50, -lat * .6))]; this.mark = [lat, lon]; }
    loop() {
      if (this.running) return; this.running = true;
      const f = () => {
        if (!this.visible || this.c.offsetParent === null) { this.running = false; return; }
        this.draw(); requestAnimationFrame(f);
      };
      requestAnimationFrame(f);
    }
    draw() {
      const { g } = this, W = this.c.width, H = this.c.height, R = Math.min(W, H) * .44, cx = W / 2, cy = H / 2, dp = this.dpr;
      if (!this.drag) {
        if (this.target) {
          const dr = ((this.target[0] - this.rot + 540) % 360) - 180, dt = this.target[1] - this.tilt;
          this.rot += dr * .07; this.tilt += dt * .07; if (Math.abs(dr) < .2 && Math.abs(dt) < .2) this.target = null;
        } else {
          this.rot += this.vr; this.tilt = Math.max(-70, Math.min(70, this.tilt + this.vt)); this.vr *= .95; this.vt *= .9;
          if (!REDUCED && Math.abs(this.vr) < .05 && performance.now() - this.idle > 1200) this.rot += .07;
        }
      }
      g.clearRect(0, 0, W, H);
      const sph = g.createRadialGradient(cx - R * .35, cy - R * .4, R * .1, cx, cy, R); sph.addColorStop(0, "#241b4d"); sph.addColorStop(1, "#090716");
      g.fillStyle = sph; g.beginPath(); g.arc(cx, cy, R, 0, 7); g.fill(); g.strokeStyle = "rgba(157,123,255,.4)"; g.lineWidth = 1.2 * dp; g.stroke();
      const bands = [new Path2D(), new Path2D(), new Path2D(), new Path2D()], ds = (this.o.dot || 1.8) * dp;
      for (const [la, lo] of geo.dots) { const [x, y, z] = this.proj(la, lo, R, cx, cy); if (z > 0) bands[Math.min(3, (z * 4) | 0)].rect(x - ds / 2, y - ds / 2, ds, ds); }
      bands.forEach((b, i) => { g.fillStyle = `rgba(157,123,255,${.22 + i * .17})`; g.fill(b); });
      const lp = new Path2D();
      for (const [la, lo, pop] of geo.lights) { const [x, y, z] = this.proj(la, lo, R, cx, cy); if (z > .08) { const r = (pop > 5e6 ? 2.6 : pop > 1e6 ? 1.9 : 1.3) * dp * (this.o.dot ? .7 : 1); lp.moveTo(x + r, y); lp.arc(x, y, r, 0, 7); } }
      g.fillStyle = "rgba(255,210,31,.85)"; g.fill(lp);
      for (const a of this.arcs) {
        a.t += REDUCED ? 0 : a.sp; if (a.t > 1.25) Object.assign(a, this.newArc());
        const head = Math.min(a.t, 1), tail = Math.max(0, a.t - .35);
        g.beginPath(); let on = false;
        for (let k = 0; k <= 28; k++) { const [la, lo, h] = this.slerp(a.a, a.b, tail + (head - tail) * (k / 28)), [x, y, z] = this.proj(la, lo, R * (1 + h * .18), cx, cy); if (z <= 0) { on = false; continue; } on ? g.lineTo(x, y) : g.moveTo(x, y); on = true; }
        const gr = g.createLinearGradient(0, 0, W, H); gr.addColorStop(0, "#2ee6f0"); gr.addColorStop(1, "#ff3d81"); g.strokeStyle = gr; g.lineWidth = 1.8 * dp; g.stroke();
      }
      if (this.mark) { const [x, y, z] = this.proj(this.mark[0], this.mark[1], R, cx, cy); if (z > 0) { const p = (performance.now() / 900) % 1; g.strokeStyle = `rgba(255,61,129,${1 - p})`; g.lineWidth = 2 * dp; g.beginPath(); g.arc(x, y, (4 + p * 18) * dp, 0, 7); g.stroke(); g.fillStyle = "#ff3d81"; g.beginPath(); g.arc(x, y, 4 * dp, 0, 7); g.fill(); } }
    }
  }

  // ---------- search box (cities + airports) ----------
  function bindSearch(input, box, onPick, { airportsFirst = false } = {}) {
    let items = [], act = -1, timer, seq = 0;
    const local = (q) => {
      const f = q.trim().toLowerCase(); if (f.length < 2) return [];
      const feat = (state.catalog?.destinations || []).filter((d) => d.name.toLowerCase().startsWith(f)).map((d) => ({ id: d.id, name: d.name, region: d.region, country: d.country, cc: d.cc || "", airport: d.airport, featured: true }));
      const top = geo.top.filter((t) => t[1].toLowerCase().startsWith(f) || (f.length === 3 && t[6].toLowerCase() === f)).slice(0, 8).map((t) => ({ id: "w" + t[0], name: t[1], cc: t[2], airport: t[6], population: t[5] }));
      return [...feat, ...top];
    };
    const draw = () => {
      box.innerHTML = items.map((r, i) => `<button class="sug${i === act ? " act" : ""}" type="button" role="option" data-i="${i}"><span class="fl">${flag(r.cc)}</span><span><b>${esc(r.name)}${r.featured ? '<span class="feat">featured</span>' : ""}</b><small>${esc([r.region, r.country].filter(Boolean).join(" · ") || (r.population ? fmtPop(r.population) + " people" : ""))}</small></span><span class="apt">✈ ${esc(r.airport || "")}${r.airport_km != null ? `<em>${r.airport_km} km</em>` : ""}</span></button>`).join("") || (input.value.trim().length >= 2 ? '<div class="sug"><span></span><span class="muted">No match yet…</span></div>' : "");
      box.classList.toggle("open", !!box.innerHTML && document.activeElement === input);
    };
    const run = async () => {
      const q = input.value, my = ++seq;
      items = local(q); act = items.length ? 0 : -1; draw();
      if (q.trim().length < 2) return;
      try {
        const r = await api("/search?q=" + encodeURIComponent(q) + "&limit=9");
        if (my !== seq) return;
        const seen = new Set(r.results.map((x) => x.id));
        items = [...r.results, ...items.filter((x) => !seen.has(x.id) && !r.results.some((y) => y.name === x.name && y.cc === x.cc))].slice(0, 9);
        act = items.length ? 0 : -1; draw();
      } catch { /* local results stay */ }
    };
    input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(run, 90); });
    input.addEventListener("focus", () => { input.select(); if (items.length) draw(); });
    input.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") { act = Math.min(items.length - 1, act + 1); draw(); e.preventDefault(); }
      else if (e.key === "ArrowUp") { act = Math.max(0, act - 1); draw(); e.preventDefault(); }
      else if (e.key === "Enter") { e.preventDefault(); if (items[act]) pick(items[act]); }
      else if (e.key === "Escape") { box.classList.remove("open"); input.blur(); }
    });
    box.addEventListener("mousedown", (e) => { const b = e.target.closest(".sug[data-i]"); if (b) { e.preventDefault(); pick(items[+b.dataset.i]); } });
    input.addEventListener("blur", () => setTimeout(() => box.classList.remove("open"), 120));
    function pick(r) { box.classList.remove("open"); input.value = r.name; input.blur(); onPick(r); }
  }

  // ---------- state ----------
  const blank = (sel, extra = {}) => ({ sel, weeks: 8, budget: 100, bmode: "pct", budgetInr: 5000000, risk: "balanced", start: "", plan: null, prod: 0, week: 0, ...extra });
  const state = {
    catalog: null, mod: "overview",
    m: {
      flights: blank({ dest: "dubai", name: "Dubai", cc: "AE", airport: "DXB" }, { origin: { code: "DEL", name: "New Delhi", cc: "IN" } }),
      hotels: blank({ dest: "dubai", name: "Dubai", cc: "AE", airport: "DXB" }, { segs: { business: true, transit: true, leisure: true } }),
      experiences: blank({ dest: "goa", name: "Goa", cc: "IN", airport: "GOI" }),
    },
  };
  const cur = () => state.m[state.mod];
  function params(m, mod) {
    const p = { weeks: m.weeks, budget: m.budget, risk: m.risk, kinds: MODS[mod].kinds.join(",") };
    if (m.bmode === "inr") p.budget_inr = Math.round(m.budgetInr);
    if (m.start) p.start = m.start;
    if (m.sel.city) p.city = m.sel.city; else p.dest = m.sel.dest;
    if (mod === "flights" && m.origin) p.origin = m.origin.code;
    return p;
  }
  const qs = (p) => "?" + Object.entries(p).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");

  // ---------- router ----------
  let globeBig, globeMini;
  function route() {
    const h = location.hash.replace(/^#\/?/, "");
    const m = h.match(/^console\/(\w+)/);
    if (!m) {
      document.body.classList.add("on-landing"); $("#console").hidden = true; $("#landing").hidden = false; document.body.classList.remove("leaving");
      if (globeBig) globeBig.loop();
      return;
    }
    const mod = ["overview", "radar", "portfolio", "flights", "hotels", "experiences", "orders"].includes(m[1]) ? m[1] : "overview";
    const show = () => {
      document.body.classList.remove("on-landing", "leaving"); $("#landing").hidden = true; $("#console").hidden = false;
      openModule(mod); scrollTo({ top: 0 });
    };
    if (!$("#landing").hidden && !REDUCED) { document.body.classList.add("leaving"); setTimeout(show, 480); } else show();
  }
  function openModule(mod) {
    state.mod = mod;
    $$(".rail nav a").forEach((a) => a.classList.toggle("on", a.dataset.mod === mod));
    $("#crumb").textContent = { overview: "Overview", orders: "Orders", radar: "Opportunity radar", portfolio: "Portfolio" }[mod] || MODS[mod].title;
    const view = MODS[mod] ? "planner" : mod;
    $$(".view").forEach((v) => v.classList.toggle("on", v.dataset.view === view));
    if (mod === "overview") renderOverview();
    else if (mod === "orders") renderOrders();
    else if (mod === "radar") loadRadar();
    else if (mod === "portfolio") { renderPfDests(); loadPortfolio(); }
    else { renderPickers(); syncControls(); loadPlan(); }
  }

  // ---------- planner: pickers + controls ----------
  function pickBox(id, label, value, code, ph) {
    return `<div class="pick"><label for="${id}">${label}</label><div class="pick-box"><span class="code" id="${id}Code">${esc(code || "—")}</span><input id="${id}" type="search" autocomplete="off" value="${esc(value)}" placeholder="${ph}"><div class="suggest" id="${id}Sug" role="listbox"></div></div></div>`;
  }
  function renderPickers() {
    const m = cur(), row = $("#pickRow");
    if (state.mod === "flights") {
      row.innerHTML = pickBox("pFrom", "From", m.origin.name, m.origin.code, "Any city or airport…") + `<button class="swap" id="swap" type="button" aria-label="Swap origin and destination">⇄</button>` + pickBox("pTo", "To", m.sel.name, m.sel.airport, "Any city or airport…");
      bindSearch($("#pFrom"), $("#pFromSug"), (r) => { m.origin = { code: r.airport, name: r.name, cc: r.cc }; $("#pFromCode").textContent = r.airport; loadPlan(); });
      bindSearch($("#pTo"), $("#pToSug"), (r) => { setSel(m, r); $("#pToCode").textContent = r.airport; loadPlan(); });
      $("#swap").addEventListener("click", () => {
        const o = m.origin, s = m.sel;
        m.origin = { code: s.airport, name: s.name, cc: s.cc };
        const hit = geo.top.find((t) => t[6] === o.code && t[1].toLowerCase().startsWith(o.name.toLowerCase().slice(0, 4))) || geo.top.find((t) => t[6] === o.code);
        const feat = state.catalog.destinations.find((d) => d.airport === o.code);
        if (feat) setSel(m, { id: feat.id, featured: true, name: feat.name, cc: feat.cc, airport: feat.airport });
        else if (hit) setSel(m, { id: "w" + hit[0], name: hit[1], cc: hit[2], airport: hit[6] });
        else { toast("Search the new destination"); return; }
        renderPickers(); loadPlan();
      });
    } else {
      const label = state.mod === "hotels" ? "Hotel city" : "Experience city";
      let html = pickBox("pCity", label, m.sel.name, m.sel.airport, "Search any of 171,567 cities…");
      if (state.mod === "hotels") html += `<div class="chipset" id="segChips">${["business", "transit", "leisure"].map((s) => `<button class="fchip" type="button" data-s="${s}" style="--c:var(${SEG[s][1]})" aria-pressed="${m.segs[s]}">${s === "business" ? "💼 Business" : s === "transit" ? "🛫 Airport" : "🌴 Leisure"}</button>`).join("")}</div>`;
      row.innerHTML = html;
      bindSearch($("#pCity"), $("#pCitySug"), (r) => { setSel(m, r); $("#pCityCode").textContent = r.airport; loadPlan(); });
      if (state.mod === "hotels") $$("#segChips .fchip").forEach((b) => b.addEventListener("click", () => {
        const s = b.dataset.s; if (Object.values(m.segs).filter(Boolean).length === 1 && m.segs[s]) return toast("Keep at least one hotel type");
        m.segs[s] = !m.segs[s]; b.setAttribute("aria-pressed", m.segs[s]); m.prod = 0; if (m.plan) renderPlan();
      }));
    }
  }
  function setSel(m, r) { m.sel = r.featured ? { dest: r.id, name: r.name, cc: r.cc, airport: r.airport } : { city: r.id, name: r.name, cc: r.cc, airport: r.airport }; m.prod = 0; m.week = 0; }
  function syncControls() {
    const m = cur();
    $$("#weeksSeg button").forEach((b) => b.setAttribute("aria-checked", +b.dataset.v === m.weeks));
    $$("#riskSeg button").forEach((b) => b.setAttribute("aria-checked", b.dataset.v === m.risk));
    $("#budget").value = m.budget; $("#budgetOut").textContent = m.budget + "%";
    $("#start").value = m.start || state.catalog?.default_start || "";
    $("#riskNote").textContent = RISK_TXT[m.risk];
    $$("#bmodeSeg button").forEach((b) => b.setAttribute("aria-checked", b.dataset.v === m.bmode));
    $("#pctCtrl").hidden = m.bmode !== "pct"; $("#inrCtrl").hidden = m.bmode !== "inr";
    const unit = m.budgetInr >= 1e7 && m.budgetInr % 1e7 === 0 ? 1e7 : 1e5;
    $("#inrUnit").value = String(unit); $("#budgetInr").value = +(m.budgetInr / unit).toFixed(2); $("#inrOut").textContent = inr(m.budgetInr);
  }
  function bindControls() {
    $$("#weeksSeg button").forEach((b) => b.addEventListener("click", () => { cur().weeks = +b.dataset.v; syncControls(); loadPlan(); }));
    $$("#riskSeg button").forEach((b) => b.addEventListener("click", () => setRisk(b.dataset.v)));
    let t; $("#budget").addEventListener("input", (e) => { cur().budget = +e.target.value; $("#budgetOut").textContent = e.target.value + "%"; clearTimeout(t); t = setTimeout(loadPlan, 220); });
    $("#start").addEventListener("change", (e) => { cur().start = e.target.value; loadPlan(); });
    $$("#bmodeSeg button").forEach((b) => b.addEventListener("click", () => { cur().bmode = b.dataset.v; syncControls(); loadPlan(); }));
    let ti; const inrChange = () => { const v = Math.max(1, +$("#budgetInr").value || 1) * +$("#inrUnit").value; cur().budgetInr = v; $("#inrOut").textContent = inr(v); clearTimeout(ti); ti = setTimeout(loadPlan, 350); };
    $("#budgetInr").addEventListener("input", inrChange); $("#inrUnit").addEventListener("change", inrChange);
    $("#riskGrid").addEventListener("click", (e) => { const b = e.target.closest(".rk"); if (b) setRisk(b.dataset.v); });
    $("#bookWeek").addEventListener("click", () => bookMany((p, w, wi) => wi === cur().week && w.action === "BUY"));
    $("#bookAll").addEventListener("click", () => bookMany((p, w) => w.q > 0));
  }
  function setRisk(v) { cur().risk = v; syncControls(); loadPlan(); }

  // ---------- load + render a module plan ----------
  async function loadPlan() {
    const mod = state.mod, m = cur(), p = params(m, mod);
    $("#stage").classList.add("loading");
    $("#status").innerHTML = `<i class="dot busy"></i><span>forecasting · optimising</span>`;
    try {
      const plan = await api("/plan" + qs(p), { channel: "plan" });
      if (state.mod !== mod) return;
      m.plan = plan; m.prod = Math.min(m.prod, plan.products.length - 1);
      if (!m.start) $("#start").value = plan.start;
      renderPlan();
      $("#status").innerHTML = `<i class="dot ok"></i><span>${plan.scenarios} scenarios · ${plan.seconds}s server</span>`;
      const d = plan.destination; if (globeMini) globeMini.focus(d.lat, d.lon); if (globeBig) globeBig.focus(d.lat, d.lon);
      loadExtras(mod, p);
    } catch (e) {
      if (e.name === "AbortError") return;
      $("#status").innerHTML = `<i class="dot err"></i><span>${esc(e.message || "engine unreachable")}</span>`;
      if (/no flight/i.test(e.message)) toast("Too close to fly. Try another city, or Experiences for ground transfers.");
    } finally { $("#stage").classList.remove("loading"); }
  }
  async function loadExtras(mod, p) {
    $("#replay").innerHTML = `<p class="eyebrow">Proof · replay on last year</p><div class="shimmer-line"></div><div class="shimmer-line short"></div>`;
    $("#frontierChart").innerHTML = `<text x="380" y="150" text-anchor="middle">Tracing the risk–return curve…</text>`;
    try { const r = await api("/replay" + qs(p), { channel: "replay" }); if (state.mod === mod) renderReplay(r); } catch { /* optional panel */ }
    try { const f = await api("/frontier" + qs(p), { channel: "frontier" }); if (state.mod === mod) { cur().frontier = f; drawFrontier(); } } catch { /* optional panel */ }
  }
  function visibleProducts() {
    const m = cur();
    if (state.mod !== "hotels") return m.plan.products;
    const ps = m.plan.products.filter((p) => m.segs[p.segment] !== false);
    return ps.length ? ps : m.plan.products;
  }
  function renderPlan() { renderContext(); renderKPIs(); renderSignals(); renderRisk(); renderProdTabs(); drawDemand(); renderWeekTabs(); renderPlanList(); renderDonut(); renderStress("#stressChart", cur().plan.stress, "#stressNote"); renderPricing(); }

  function renderContext() {
    const m = cur(), d = m.plan.destination, b = Math.round((d.business ?? .15) * 100);
    const s = d.season || [], mx = Math.max(...s, 1), mn = Math.min(...s, 1), sm = new Date(m.plan.start + "T00:00:00").getMonth(), months = Math.ceil(m.plan.weeks / 4.3);
    const X = (i) => 12 + i * 25, Y = (v) => 44 - ((v - mn) / (mx - mn || 1)) * 36, pts = s.map((v, i) => [X(i), Y(v)]);
    let sv = ""; for (let k = 0; k < months; k++) sv += `<rect x="${X((sm + k) % 12) - 12}" y="2" width="25" height="44" rx="5" fill="rgba(255,210,31,.1)"/>`;
    sv += `<path class="draw" style="--len:${lineLen(pts)}" d="${pathOf(pts)}" fill="none" stroke="${css("--pink")}" stroke-width="2.4"/>` + "JFMAMJJASOND".split("").map((c, i) => `<text x="${X(i)}" y="56" text-anchor="middle">${c}</text>`).join("");
    $("#ctx").innerHTML = `<div class="flag">${flag(d.cc)}</div><div><p class="eyebrow">${esc(d.type_label)}${d.featured ? " · featured" : ""}</p><h3>${esc(d.name)}</h3><span class="muted small">${esc([d.region, d.country].filter((x, i, a) => x && a.indexOf(x) === i).join(" · "))}</span></div>
      <div class="facts">
        <div class="fact"><span>Airport</span><b>${esc(d.airport)}</b><small>${esc(d.airport_name || "")}${d.airport_km != null ? " · " + d.airport_km + " km" : ""}</small></div>
        <div class="fact"><span>Price level</span><b>${(+d.price_level).toFixed(1)}×</b><small>vs Indian domestic</small></div>
        <div class="fact"><span>Market</span><b>${d.population ? fmtPop(d.population) : d.featured ? "Top 34" : "Town"}</b><small>${d.population ? "residents" : "destination"}</small></div>
        <div class="fact"><span>Plan window</span><b>${m.plan.weeks} wks</b><small>from ${fmtDate(m.plan.start)}</small></div>
      </div>
      <div class="mixrow"><div><div class="mix-head"><span>Travel mix</span><span>${b}% business · ${100 - b}% leisure</span></div><div class="mix-bar"><i style="width:${b}%;background:linear-gradient(90deg,var(--violet),var(--cyan))"></i><i style="width:${100 - b}%;background:linear-gradient(90deg,var(--pink),var(--volt))"></i></div></div>
      <div class="season"><div class="mix-head"><span>Seasonality</span><span>highlight = your window</span></div><svg viewBox="0 0 300 60">${sv}</svg></div></div>`;
    const rc = $("#routeCard");
    if (state.mod === "flights") {
      const f = m.plan.products.find((p) => p.kind === "flight");
      const intl = d.cc !== d.hub_cc;
      rc.className = "card route";
      rc.innerHTML = `<div class="card-head"><h4>Route</h4><span class="muted small">${intl ? "International" : "Domestic"}</span></div>
        <svg viewBox="0 0 320 90" aria-hidden="true"><path class="draw" style="--len:330" d="M30 70 Q160 -10 290 70" fill="none" stroke="${css("--volt")}" stroke-width="2.5" stroke-dasharray="6 6"/>
        <circle cx="30" cy="70" r="7" fill="${css("--volt")}"/><circle cx="290" cy="70" r="7" fill="${css("--pink")}"/>
        <text x="30" y="88" text-anchor="middle" style="fill:var(--fg);font:800 13px var(--mono)">${esc(d.hub)}</text><text x="290" y="88" text-anchor="middle" style="fill:var(--fg);font:800 13px var(--mono)">${esc(d.airport)}</text>
        <text x="160" y="30" text-anchor="middle" style="font-size:20px">✈</text></svg>
        <div class="route-meta"><div class="fact"><span>Distance</span><b>${(d.flight_km || 0).toLocaleString("en-IN")} km</b><small>${esc(d.hub_city || "")} → ${esc(d.name)}</small></div>
        <div class="fact"><span>Cost / seat</span><b>${f ? inr(f.unit_cost) : "—"}</b><small>sells ${f ? inr(f.sell_price) : "—"}</small></div>
        <div class="fact"><span>Seats planned</span><b>${f ? f.weeks.reduce((a, w) => a + w.q, 0).toLocaleString("en-IN") : 0}</b><small>over ${m.plan.weeks} weeks</small></div></div>`;
    } else {
      rc.className = "card";
      rc.innerHTML = `<div class="card-head"><h4>${state.mod === "hotels" ? "Hotels in this plan" : "Experiences in this plan"}</h4><span class="muted small">cost → sell</span></div>` +
        m.plan.products.map((p) => `<div class="seg-row" style="margin-bottom:9px"><i style="background:var(${(SEG[p.segment] || SEG.leisure)[1]})"></i><span>${ICON[p.kind]} ${esc(p.name)}</span><b>${inr(p.unit_cost)} → ${inr(p.sell_price)}</b></div>`).join("");
    }
  }

  function renderKPIs() {
    const m = cur(), s = m.plan.kpis.stockshock, t = m.plan.kpis.today, pc = pct(s.expected_profit, t.expected_profit), sp = pct(s.spend, t.spend);
    const worst = (x) => (x <= 0 ? `${inr(-x)} profit` : `${inr(x)} loss`);
    const cards = [
      ["--cyan", "Expected profit", s.expected_profit, (x) => inr(x), `today's rule <b>${inr(t.expected_profit)}</b><span class="delta ${pc >= 0 ? "up" : "down"}">${pc >= 0 ? "+" : ""}${pc.toFixed(0)}%</span>`],
      ["--volt", "Worst 5% of outcomes", -s.worst5_loss, (x) => (x >= 0 ? inr(x) + " profit" : inr(-x) + " loss"), `today's rule <b>${worst(t.worst5_loss)}</b>`],
      ["--pink", "Cash tied up", s.spend, (x) => inr(x), `today's rule <b>${inr(t.spend)}</b><span class="delta ${sp <= 0 ? "up" : "down"}">${sp >= 0 ? "+" : ""}${sp.toFixed(0)}%</span>`],
      ["--violet", "Bookings served", s.served_pct, (x) => x.toFixed(1) + "%", `today's rule <b>${t.served_pct.toFixed(1)}%</b> · ${Math.round(s.unsold_units)} vs ${Math.round(t.unsold_units)} unsold`],
    ];
    $("#kpis").innerHTML = cards.map((c, i) => `<div class="kpi st" style="--c:var(${c[0]});animation-delay:${i * 50}ms"><div class="k">${c[1]}</div><div class="v" id="kv${i}">–</div><div class="d">${c[4]}</div></div>`).join("");
    cards.forEach((c, i) => countUp($("#kv" + i), c[2], c[3]));
  }
  function renderRisk() {
    const m = cur(), rc = m.plan.risk_compare, ks = ["careful", "balanced", "bold"], maxP = Math.max(...ks.map((k) => rc[k].expected_profit), 1), maxU = Math.max(...ks.map((k) => rc[k].units), 1);
    const ws = ks.map((k) => rc[k].worst5_loss), wmin = Math.min(...ws), wmax = Math.max(...ws), nm = { careful: "🛡 Careful", balanced: "⚖ Balanced", bold: "🚀 Bold" };
    $("#riskGrid").innerHTML = ks.map((k, i) => { const r = rc[k], safe = wmax === wmin ? 1 : 1 - ((r.worst5_loss - wmin) / (wmax - wmin)) * .75;
      return `<button class="rk st${k === m.risk ? " on" : ""}" data-v="${k}" type="button" style="--c:var(${RISK_COL[k]});animation-delay:${i * 50}ms"><h5>${nm[k]}</h5>
        <div class="row">Expected profit<b>${inr(r.expected_profit)}</b><div class="bar"><i style="width:${Math.max(4, (r.expected_profit / maxP) * 100)}%"></i></div></div>
        <div class="row">Worst 5%<b>${r.worst5_loss <= 0 ? inr(-r.worst5_loss) + " profit" : inr(r.worst5_loss) + " loss"}</b><div class="bar"><i style="width:${safe * 100}%"></i></div></div>
        <div class="row">Units pre-bought<b>${r.units.toLocaleString("en-IN")}</b><div class="bar"><i style="width:${(r.units / maxU) * 100}%"></i></div></div>
        <div class="row">Bookings served<b>${r.served_pct}%</b></div></button>`; }).join("");
  }
  const ACT = { BUY: "BUY", WAIT: "LOCK+LIVE", SKIP: "LIVE ONLY" };
  function renderReplay(r) {
    const m = cur();
    const won = r.profit_gain >= 0;
    $("#replay").innerHTML = `<p class="eyebrow">Proof · replay on last year</p><div class="big"${won ? "" : ' style="color:var(--orange)"'}>${inr(r.profit_gain, true)}</div>
      ${won ? "" : `<p><b>Honest miss:</b> demand last year came in above the forecast, so the cautious buy left money on the table. Try <b>Bold</b> to see the upside, or keep the safer plan.</p>`}
      <p>Same ${m.plan.weeks} weeks a year earlier (from ${fmtDate(r.start)}), planned only with data available then, scored on what actually sold.</p>
      <p>Profit <b>${inr(r.stockshock.expected_profit)}</b> vs ${inr(r.today.expected_profit)} with today's rule · unsold ${Math.round(r.today.unsold_units)} → <b>${Math.round(r.stockshock.unsold_units)}</b> · served <b>${r.stockshock.served_pct}%</b> vs ${r.today.served_pct}%</p>`;
  }
  function renderProdTabs() {
    const m = cur(), ps = visibleProducts();
    if (!ps.includes(m.plan.products[m.prod])) m.prod = m.plan.products.indexOf(ps[0]);
    $("#prodTabs").innerHTML = ps.map((p) => { const i = m.plan.products.indexOf(p); return `<button class="tab" role="tab" aria-selected="${i === m.prod}" data-i="${i}"><span class="sg" style="background:var(${(SEG[p.segment] || SEG.leisure)[1]})"></span>${ICON[p.kind]} ${esc(p.name)}</button>`; }).join("");
    $$("#prodTabs .tab").forEach((b) => b.addEventListener("click", () => { m.prod = +b.dataset.i; renderProdTabs(); drawDemand(); }));
  }
  function drawDemand() {
    const m = cur(), p = m.plan.products[m.prod], w = p.weeks, n = w.length, W = 760, H = 290, L = 48, R = 14, T = 22, B = 34;
    const ymax = niceMax(Math.max(...w.map((x) => Math.max(x.p90, x.q, x.q_today, x.last_year || 0))) * 1.05), step = (W - L - R) / n, X = (i) => L + step * (i + .5), Y = (v) => T + (H - T - B) * (1 - v / ymax);
    let g = "";
    for (let k = 0; k <= 4; k++) { const v = (ymax * k) / 4; g += `<line class="grid" x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}"/><text x="${L - 8}" y="${Y(v) + 4}" text-anchor="end">${Math.round(v)}</text>`; }
    w.forEach((x, i) => { g += `<text x="${X(i)}" y="${H - 12}" text-anchor="middle">${fmtDate(x.week)}</text>`; if (x.festival) g += `<rect x="${X(i) - step / 2}" y="${T}" width="${step}" height="${H - T - B}" fill="${css("--volt")}" fill-opacity=".06"/><text x="${X(i)}" y="${T + 12}" text-anchor="middle" style="fill:${css("--volt")};font-size:10px">★ ${esc(x.festival.split(" ")[0])}</text>`; });
    g += `<path class="fade-in" d="${pathOf(w.map((x, i) => [X(i), Y(x.p90)]))}${w.slice().reverse().map((x, j) => `L${X(n - 1 - j).toFixed(1)} ${Y(x.p10).toFixed(1)}`).join("")}Z" fill="${css("--violet")}" fill-opacity=".22"/>`;
    const bw = Math.min(28, step * .42);
    w.forEach((x, i) => { g += `<rect class="grow-bar" style="animation-delay:${i * 50}ms" x="${X(i) - bw / 2}" y="${Y(x.q)}" width="${bw}" height="${Math.max(0, Y(0) - Y(x.q))}" rx="4" fill="${css("--cyan")}" fill-opacity=".85"/><line x1="${X(i) - step * .38}" x2="${X(i) + step * .38}" y1="${Y(x.q_today)}" y2="${Y(x.q_today)}" stroke="${css("--pink")}" stroke-width="3" stroke-linecap="round"/>`; });
    const ly = w.map((x, i) => (x.last_year != null ? [X(i), Y(x.last_year)] : null)).filter(Boolean);
    if (ly.length > 1) g += `<path d="${pathOf(ly)}" fill="none" stroke="${css("--muted")}" stroke-width="1.6" stroke-dasharray="2 4"/>`;
    const lk = w.map((x, i) => [X(i), Y(x.p50)]);
    g += `<path class="draw" style="--len:${lineLen(lk)}" d="${pathOf(lk)}" fill="none" stroke="${css("--volt")}" stroke-width="2.6"/>` + lk.map((q) => `<circle cx="${q[0]}" cy="${q[1]}" r="3.5" fill="${css("--volt")}"/>`).join("");
    g += w.map((x, i) => `<rect class="hit" data-i="${i}" x="${X(i) - step / 2}" y="${T}" width="${step}" height="${H - T - B}" fill="transparent"/>`).join("") + `<text x="${W - R}" y="12" text-anchor="end">${UNIT[p.kind]} per week</text>`;
    const svg = $("#demandChart"), tip = $("#tip"); svg.innerHTML = g;
    svg.onmousemove = (e) => {
      const r = e.target.closest(".hit"); if (!r) { tip.style.opacity = 0; return; }
      $$(".hit", svg).forEach((h) => h.classList.toggle("hover-col", h === r));
      const x = w[+r.dataset.i], wrap = svg.parentElement.getBoundingClientRect();
      tip.innerHTML = `<b>${fmtDate(x.week)}${x.festival ? " · ★ " + esc(x.festival) : ""}</b><br><span>Likely</span> <b>${x.p50}</b> <span>(${x.p10}–${x.p90})</span><br><span>STOCKSHOCK</span> <b>${x.q}</b> · <span>today</span> <b>${x.q_today}</b>${x.last_year != null ? `<br><span>Last year</span> <b>${x.last_year}</b>` : ""}`;
      tip.style.left = Math.min(e.clientX - wrap.left + 14, wrap.width - 210) + "px"; tip.style.top = Math.max(0, e.clientY - wrap.top - 70) + "px"; tip.style.opacity = 1;
    };
    svg.onmouseleave = () => { tip.style.opacity = 0; $$(".hit", svg).forEach((h) => h.classList.remove("hover-col")); };
  }
  function renderWeekTabs() {
    const m = cur(), w = m.plan.products[0].weeks; m.week = Math.min(m.week, w.length - 1);
    $("#weekTabs").innerHTML = w.map((x, i) => `<button class="tab" role="tab" aria-selected="${i === m.week}" data-i="${i}">${fmtDate(x.week)}${x.festival ? " ★" : ""}</button>`).join("");
    $$("#weekTabs .tab").forEach((b) => b.addEventListener("click", () => { m.week = +b.dataset.i; renderWeekTabs(); renderPlanList(); }));
  }
  function orderFor(p, w) {
    const m = cur(), d = m.plan.destination;
    return { mod: state.mod, item: p.name, kind: p.kind, segment: p.segment, where: state.mod === "flights" ? `${d.hub} → ${d.airport} · ${d.name}` : `${d.name}, ${d.country}`, cc: d.cc, week: w.week, qty: w.q, unit: UNIT[p.kind], unit_cost: w.unit_cost, sell_price: w.sell_price, total: w.q * w.unit_cost };
  }
  function renderPlanList() {
    const m = cur(), wi = m.week;
    $("#planList").innerHTML = visibleProducts().map((p, k) => {
      const pi = m.plan.products.indexOf(p), x = p.weeks[wi], o = orderFor(p, x), booked = Orders.has(Orders.key(o)), sg = SEG[p.segment] || SEG.leisure;
      return `<div class="line${booked ? " booked" : ""}" style="animation-delay:${k * 50}ms">
        <div><b>${ICON[p.kind]} ${esc(p.name)}</b><small>${inr(x.unit_cost)} cost this week</small><span class="segtag" style="background:color-mix(in srgb,var(${sg[1]}) 18%,transparent);color:var(${sg[1]})">${sg[0]}</span></div>
        <span class="badge ${x.action}">${ACT[x.action] || x.action}</span>
        <div class="qty">${x.q} ${UNIT[p.kind]}<small>today's rule ${x.q_today} · likely ${x.p50} (${x.p10}–${x.p90})</small><small>sell ${inr(x.sell_price)} <span class="${x.price_change_pct > 0 ? "up-t" : x.price_change_pct < 0 ? "down-t" : ""}">${x.price_change_pct ? (x.price_change_pct > 0 ? "+" : "") + x.price_change_pct + "%" : "rate card"}</span> · ~${x.cancellations} cancel</small></div>
        <div class="why">${esc(x.reason)}<div class="chips">${(x.drivers || []).map((c) => `<span class="chip${c === x.festival ? " fest" : ""}">${esc(c)}</span>`).join("")}</div></div>
        <button class="bk${booked ? " done" : ""}" type="button" data-p="${pi}" ${x.q <= 0 || booked ? "disabled" : ""}>${booked ? "✓ Booked" : x.q > 0 ? `Book · ${inr(x.q * x.unit_cost)}` : "Nothing to book"}</button></div>`;
    }).join("");
    $$("#planList .bk").forEach((b) => b.addEventListener("click", () => {
      const p = m.plan.products[+b.dataset.p];
      if (Orders.add(orderFor(p, p.weeks[m.week]))) { Orders.save(); toast(`Booked ${p.weeks[m.week].q} ${UNIT[p.kind]} · ${p.name}`); renderPlanList(); }
    }));
  }
  function bookMany(test) {
    const m = cur(); let n = 0, sum = 0;
    visibleProducts().forEach((p) => p.weeks.forEach((w, wi) => { if (w.q > 0 && test(p, w, wi)) { const o = orderFor(p, w); if (Orders.add(o)) { n++; sum += o.total; } } }));
    if (!n) return toast("Already booked — nothing new to add");
    Orders.save(); renderPlanList(); toast(`${n} lines booked · ${inr(sum)}`);
  }
  function renderDonut() {
    const by = {}; visibleProducts().forEach((p) => { by[p.segment] = (by[p.segment] || 0) + p.weeks.reduce((a, w) => a + w.q * w.unit_cost, 0); });
    const tot = Object.values(by).reduce((a, b) => a + b, 0) || 1, R = 80, C = 2 * Math.PI * R, rows = Object.entries(by).sort((a, b) => b[1] - a[1]);
    let off = 0, g = `<circle cx="110" cy="110" r="${R}" fill="none" stroke="${css("--line")}" stroke-width="26"/>`;
    rows.forEach(([k, v]) => { const len = (v / tot) * C; g += `<circle class="donut-arc" cx="110" cy="110" r="${R}" fill="none" stroke="var(${(SEG[k] || SEG.leisure)[1]})" stroke-width="26" stroke-dasharray="0 ${C}" data-d="${len} ${C - len}" stroke-dashoffset="${-off}" transform="rotate(-90 110 110)"/>`; off += len; });
    g += `<text x="110" y="104" text-anchor="middle" style="font:800 21px var(--display);fill:var(--fg)">${inr(tot)}</text><text x="110" y="126" text-anchor="middle">pre-buy spend</text>`;
    $("#donut").innerHTML = g; setTimeout(() => $$("#donut .donut-arc").forEach((a) => a.setAttribute("stroke-dasharray", a.dataset.d)), 40);
    $("#segList").innerHTML = rows.map(([k, v]) => `<div class="seg-row"><i style="background:var(${(SEG[k] || SEG.leisure)[1]})"></i><span>${(SEG[k] || SEG.leisure)[0]}</span><b>${inr(v)} · ${Math.round((v / tot) * 100)}%</b></div>`).join("");
  }
  function drawFrontier() {
    const m = cur(), f = m.frontier, rp = f.risk_points || {}, pts = f.points.map((p) => [p.worst5_loss, p.expected_profit]), today = [f.today.worst5_loss, f.today.expected_profit];
    const all = [...pts, today, ...Object.values(rp).map((p) => [p.worst5_loss, p.expected_profit])], xs = all.map((p) => p[0]), ys = all.map((p) => p[1]);
    const W = 760, H = 300, L = 76, R = 24, T = 24, B = 50, sx = Math.max(...xs) - Math.min(...xs) || 1, sy = Math.max(...ys) - Math.min(...ys) || 1;
    const x0 = Math.min(...xs) - sx * .1, x1 = Math.max(...xs) + sx * .12, y0 = Math.min(...ys) - sy * .15, y1 = Math.max(...ys) + sy * .18;
    const X = (v) => L + ((W - L - R) * (v - x0)) / (x1 - x0), Y = (v) => T + (H - T - B) * (1 - (v - y0) / (y1 - y0));
    let g = "";
    for (let k = 0; k <= 4; k++) { const v = y0 + ((y1 - y0) * k) / 4; g += `<line class="grid" x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}"/><text x="${L - 8}" y="${Y(v) + 4}" text-anchor="end">${inr(v)}</text>`; }
    for (let k = 0; k <= 4; k++) { const v = x0 + ((x1 - x0) * k) / 4; g += `<text x="${X(v)}" y="${H - B + 18}" text-anchor="middle">${v <= 0 ? inr(-v) + " profit" : inr(v) + " loss"}</text>`; }
    g += `<text x="${(L + W - R) / 2}" y="${H - 8}" text-anchor="middle">Worst 5% of outcomes → more risk</text><text transform="translate(16 ${(T + H - B) / 2}) rotate(-90)" text-anchor="middle">Expected profit</text>`;
    const fp = pts.map((p) => [X(p[0]), Y(p[1])]);
    if (fp.length > 1) { const mid = fp[Math.floor((fp.length - 1) / 2)]; g += `<path class="draw" style="--len:${lineLen(fp)}" d="${pathOf(fp)}" fill="none" stroke="${css("--cyan")}" stroke-width="3"/><text x="${mid[0] + 10}" y="${mid[1] + 26}" style="fill:${css("--cyan")};font-weight:800">Best possible plans ↗</text>`; }
    g += fp.map((p) => `<circle cx="${p[0]}" cy="${p[1]}" r="3.5" fill="${css("--cyan")}"/>`).join("");
    g += `<circle cx="${X(today[0])}" cy="${Y(today[1])}" r="9" fill="${css("--pink")}" stroke="#fff" stroke-width="2"/><text x="${X(today[0])}" y="${Y(today[1]) + 26}" text-anchor="middle" style="fill:${css("--pink")};font-weight:800">Today's rule</text>`;
    for (const k of ["careful", "balanced", "bold"]) { const p = rp[k]; if (!p) continue; const on = k === m.risk, x = X(p.worst5_loss), y = Y(p.expected_profit);
      g += `<circle cx="${x}" cy="${y}" r="${on ? 10 : 6}" fill="var(${RISK_COL[k]})" stroke="${css("--ink")}" stroke-width="2"/><text x="${x}" y="${y - (on ? 16 : 11)}" text-anchor="middle" style="fill:var(${RISK_COL[k]});font-weight:${on ? 900 : 700}">${on ? "★ " : ""}${k[0].toUpperCase() + k.slice(1)}</text>`; }
    if (rp[m.risk]) g += `<line x1="${X(today[0])}" y1="${Y(today[1])}" x2="${X(rp[m.risk].worst5_loss)}" y2="${Y(rp[m.risk].expected_profit)}" stroke="#fff" stroke-opacity=".5" stroke-dasharray="4 5"/>`;
    $("#frontierChart").innerHTML = g;
    $("#frontierNote").textContent = rp[m.risk] ? `Your ${m.risk} plan: ${inr(rp[m.risk].expected_profit)} expected vs ${inr(f.today.expected_profit)} with today's rule.` : "";
  }

  // ---------- overview + orders ----------
  function orderKpis(el, list) {
    const live = list.filter((o) => o.status !== "cancelled"), pend = live.filter((o) => o.status === "pending"), conf = live.filter((o) => o.status === "confirmed");
    const cards = [["--volt", "Pending lines", pend.length, (x) => Math.round(x), inr(pend.reduce((a, o) => a + o.total, 0)) + " reserved"],
      ["--good", "Confirmed", conf.reduce((a, o) => a + o.total, 0), inr, conf.length + " lines placed"],
      ["--violet", "Units booked", live.reduce((a, o) => a + o.qty, 0), (x) => Math.round(x).toLocaleString("en-IN"), "nights, seats and passes"],
      ["--cyan", "Destinations", new Set(live.map((o) => o.where)).size, (x) => Math.round(x), new Set(live.map((o) => o.mod)).size + " modules used"]];
    el.innerHTML = cards.map((c, i) => `<div class="kpi st" style="--c:var(${c[0]});animation-delay:${i * 50}ms"><div class="k">${c[1]}</div><div class="v" id="${el.id}${i}">0</div><div class="d">${c[4]}</div></div>`).join("");
    cards.forEach((c, i) => countUp($(`#${el.id}${i}`), c[2], c[3]));
  }
  function renderOverview() {
    const h = new Date().toLocaleString("en-IN", { timeZone: "Asia/Kolkata", hour: "numeric", hour12: false });
    $("#greet").textContent = h < 12 ? "morning" : h < 17 ? "afternoon" : "evening";
    orderKpis($("#ovKpis"), Orders.list);
    const recent = Orders.list.filter((o) => o.status !== "cancelled").slice(0, 5);
    $("#ovOrders").innerHTML = recent.length ? `<table class="orders"><tbody>${recent.map((o) => `<tr><td>${ICON[o.kind]} <b>${esc(o.item)}</b><br><small class="muted">${esc(o.where)}</small></td><td>${fmtDate(o.week)}</td><td class="r">${o.qty} ${o.unit}</td><td class="r">${inr(o.total)}</td><td><span class="st-chip ${o.status}">${o.status}</span></td></tr>`).join("")}</tbody></table>`
      : `<div class="empty">No orders yet. Open Flights, Hotels or Experiences and press <b>Book</b> on any line.</div>`;
    loadAlerts();
    if (!globeMini) globeMini = new Globe($("#miniGlobe"), { dot: 1.3, arcs: true });
    else globeMini.loop();
  }
  let ordFilter = "all";
  function renderOrders() {
    orderKpis($("#ordKpis"), Orders.list);
    const list = Orders.list.filter((o) => ordFilter === "all" || o.mod === ordFilter);
    $("#ordBody").innerHTML = list.length ? list.map((o, i) => `<tr style="animation-delay:${Math.min(i, 12) * 40}ms"><td class="mono">${o.id}</td><td>${ICON[o.kind]} <b>${esc(o.item)}</b></td><td>${flag(o.cc)} ${esc(o.where)}</td><td>${fmtDate(o.week)}</td><td class="r">${o.qty} ${o.unit}</td><td class="r">${o.sell_price ? inr(o.sell_price) : "—"}</td><td class="r">${inr(o.total)}</td><td><span class="st-chip ${o.status}">${o.status}</span></td>
      <td class="r">${o.status === "pending" ? `<button class="mini-btn" data-a="confirm" data-id="${o.id}">Confirm</button><button class="mini-btn" data-a="cancel" data-id="${o.id}">Cancel</button>` : o.status === "confirmed" ? `<button class="mini-btn" data-a="cancel" data-id="${o.id}">Cancel</button>` : ""}</td></tr>`).join("")
      : `<tr><td colspan="9"><div class="empty">Nothing here yet. Book lines from any module and they land here.</div></td></tr>`;
  }
  function bindOrders() {
    $("#ordBody").addEventListener("click", (e) => {
      const b = e.target.closest(".mini-btn"); if (!b) return;
      const o = Orders.list.find((x) => x.id === b.dataset.id); if (!o) return;
      o.status = b.dataset.a === "confirm" ? "confirmed" : "cancelled"; Orders.save(); renderOrders();
      toast(o.status === "confirmed" ? `${o.id} confirmed` : `${o.id} cancelled`);
    });
    $$("#ordFilter .tab").forEach((t) => t.addEventListener("click", () => { ordFilter = t.dataset.f; $$("#ordFilter .tab").forEach((x) => x.setAttribute("aria-selected", x === t)); renderOrders(); }));
    $("#confirmAll").addEventListener("click", () => { let n = 0; Orders.list.forEach((o) => { if (o.status === "pending" && (ordFilter === "all" || o.mod === ordFilter)) { o.status = "confirmed"; n++; } }); Orders.save(); renderOrders(); toast(n ? `${n} lines confirmed` : "Nothing pending"); });
    $("#clearCancelled").addEventListener("click", () => { Orders.list = Orders.list.filter((o) => o.status !== "cancelled"); Orders.save(); renderOrders(); });
  }

  // ---------- signals, stress test, pricing ----------
  function spark(vals, color) {
    const mx = Math.max(...vals), mn = Math.min(...vals), X = (i) => 4 + (i * 112) / Math.max(1, vals.length - 1), Y = (v) => 26 - ((v - mn) / (mx - mn || 1)) * 22;
    return `<svg viewBox="0 0 120 30"><path d="${pathOf(vals.map((v, i) => [X(i), Y(v)]))}" fill="none" stroke="${color}" stroke-width="2"/></svg>`;
  }
  const sgn = (v, unit = "%") => `<span class="${v > 0 ? "up-t" : v < 0 ? "down-t" : ""}">${v > 0 ? "+" : ""}${v}${unit}</span>`;
  function renderSignals() {
    const s = cur().plan.signals, pi = s.price_idx, pavg = Math.round((pi.reduce((a, b) => a + b, 0) / pi.length - 1) * 100);
    $("#signals").innerHTML = `<div class="card-head"><h4>Market signals</h4><span class="muted small">what the engine is reading for this ${cur().plan.weeks}-week window</span></div><div class="sig-grid">
      <div class="sig"><span>Search momentum</span><b>${sgn(s.search_momentum)}</b><small>searches vs same weeks last year</small></div>
      <div class="sig"><span>Look-to-book</span><b>${s.look_to_book}</b><small>searches per booking · ${sgn(s.ltb_change)} vs LY</small></div>
      <div class="sig"><span>Cancellations</span><b>${s.cancel_rate}%</b><small>of bookings cancel; netted out of demand</small></div>
      <div class="sig"><span>Sell-outs last year</span><b>${s.sold_out_weeks_ly} wk</b><small>weeks the market ran out in this window</small></div>
      <div class="sig"><span>Buy price index</span><b>${sgn(pavg)}</b><small>vs yearly average, week by week</small>${spark(pi, css("--volt"))}</div>
      <div class="sig"><span>Recommended price</span><b>${sgn(s.avg_price_change)}</b><small>average vs rate card</small></div></div>`;
  }
  function renderStress(sel, st, noteSel) {
    if (!st) return;
    const W = 380, H = 220, L = 58, R = 12, T = 16, B = 34, vals = st.flatMap((x) => [x.stockshock, x.today]);
    const y0 = Math.min(0, ...vals), y1 = Math.max(...vals) * 1.12, X = (i) => L + (i * (W - L - R)) / (st.length - 1), Y = (v) => T + (H - T - B) * (1 - (v - y0) / (y1 - y0 || 1));
    let g = "";
    for (let k = 0; k <= 3; k++) { const v = y0 + ((y1 - y0) * k) / 3; g += `<line class="grid" x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}"/><text x="${L - 6}" y="${Y(v) + 4}" text-anchor="end">${inr(v)}</text>`; }
    if (y0 < 0) g += `<line x1="${L}" x2="${W - R}" y1="${Y(0)}" y2="${Y(0)}" stroke="${css("--muted")}" stroke-dasharray="3 3"/>`;
    st.forEach((x, i) => (g += `<text x="${X(i)}" y="${H - 12}" text-anchor="middle">${x.shock_pct > 0 ? "+" : ""}${x.shock_pct}%</text>`));
    for (const [k, c] of [["today", "--pink"], ["stockshock", "--cyan"]]) {
      const pts = st.map((x, i) => [X(i), Y(x[k])]);
      g += `<path class="draw" style="--len:${lineLen(pts)}" d="${pathOf(pts)}" fill="none" stroke="var(${c})" stroke-width="3"/>` + pts.map((p) => `<circle cx="${p[0]}" cy="${p[1]}" r="4" fill="var(${c})"/>`).join("");
    }
    g += `<text x="${L + 6}" y="${T + 6}" style="fill:var(--cyan);font-weight:800">● STOCKSHOCK</text><text x="${L + 110}" y="${T + 6}" style="fill:var(--pink);font-weight:800">● Today's rule</text>`;
    g += `<text x="${(L + W - R) / 2}" y="${H}" text-anchor="middle">demand vs forecast</text>`;
    $(sel).innerHTML = g;
    if (noteSel) { const lo = st[0]; $(noteSel).innerHTML = `If demand comes in <b>30% below</b> forecast: STOCKSHOCK ${inr(lo.stockshock)} vs ${inr(lo.today)} with today's rule (${lo.stockshock_unsold} vs ${lo.today_unsold} units unsold).`; }
  }
  function renderPricing() {
    const ps = visibleProducts();
    $("#pricing").innerHTML = `<div class="price-row muted small"><span>Product</span><span>Rate card</span><span>Recommended</span><span>Buy-price timing</span></div>` + ps.map((p) => {
      const w = p.weeks, rc = w.reduce((a, x) => a + x.sell_list, 0) / w.length, rec = w.reduce((a, x) => a + x.sell_price, 0) / w.length, ch = Math.round((rec / rc - 1) * 100);
      const cheap = w.reduce((b, x) => (x.price_idx < b.price_idx ? x : b), w[0]);
      return `<div class="price-row"><span>${ICON[p.kind]} ${esc(p.name)}</span><b>${inr(rc)}</b><b>${inr(rec)} ${sgn(ch)}</b><span class="small">cheapest week to buy: <b>${fmtDate(cheap.week)}</b> (${sgn(Math.round((cheap.price_idx - 1) * 100))})</span></div>`;
    }).join("") + `<p class="muted small" style="margin:10px 0 0">Prices react to demand: peak weeks carry a premium, quiet weeks a discount to fill inventory. Cancellation rates: ${ps.map((p) => `${esc(p.name.split(" ")[0])} ${p.cancel_rate}%`).join(" · ")}.</p>`;
  }

  // ---------- overview alerts ----------
  async function loadAlerts() {
    try {
      const r = await api("/radar?weeks=8&limit=8");
      $("#ovAlerts").innerHTML = r.alerts.map((a, i) => `<div class="alert" style="animation-delay:${i * 50}ms"><span class="lv ${a.level}">${a.level.toUpperCase()}</span><span>${esc(a.text)}</span><a class="link" href="#/console/${a.kind === "flight" ? "flights" : a.kind === "hotel" ? "hotels" : "experiences"}" data-d="${a.dest_id}">Plan →</a></div>`).join("") || '<div class="empty">No alerts right now.</div>';
      $("#ovTop").innerHTML = r.rows.slice(0, 6).map((x) => `<div class="hbar"><span>${flag(x.cc)} ${esc(x.dest)}</span><i><b style="width:${x.score}%;background:linear-gradient(90deg,var(--violet),var(--pink))"></b></i><em>${ICON[x.kind]} ${x.score}</em></div>`).join("");
      $$("#ovAlerts a[data-d]").forEach((a) => a.addEventListener("click", () => openFromRadar(a.dataset.d, a.getAttribute("href").split("/").pop())));
      prewarm([...new Set(r.rows.map((x) => x.dest_id))].slice(0, 5));
    } catch { $("#ovAlerts").innerHTML = '<div class="empty">Alerts unavailable right now.</div>'; }
  }
  function openFromRadar(destId, mod) {
    const d = (state.catalog?.destinations || []).find((x) => x.id === destId), m = state.m[mod];
    if (!m) return;
    if (d) m.sel = { dest: d.id, name: d.name, cc: d.cc, airport: d.airport };
    else { const t = radar.extra.find((x) => x.id === destId); if (t) m.sel = { city: t.id, name: t.name, cc: t.cc, airport: t.airport }; }
    m.prod = 0; m.week = 0;
  }

  // ---------- opportunity radar ----------
  const radar = { kinds: "", weeks: 8, extra: [], rows: [] };
  function bindRadar() {
    $$("#rdKinds button").forEach((b) => b.addEventListener("click", () => { radar.kinds = b.dataset.v; $$("#rdKinds button").forEach((x) => x.setAttribute("aria-checked", x === b)); loadRadar(); }));
    $$("#rdWeeks button").forEach((b) => b.addEventListener("click", () => { radar.weeks = +b.dataset.v; $$("#rdWeeks button").forEach((x) => x.setAttribute("aria-checked", x === b)); loadRadar(); }));
    bindSearch($("#rdAdd"), $("#rdAddSug"), (r) => { $("#rdAdd").value = ""; if (!r.featured && !radar.extra.some((x) => x.id === r.id)) radar.extra.push({ id: r.id, name: r.name, cc: r.cc, airport: r.airport }); renderRdExtra(); loadRadar(); });
    $("#rdBody").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-a]"); if (!b) return;
      const r = radar.rows[+b.dataset.i];
      if (b.dataset.a === "plan") { const mod = r.kind === "flight" ? "flights" : r.kind === "hotel" ? "hotels" : "experiences"; openFromRadar(r.dest_id, mod); location.hash = "#/console/" + mod; }
      else { addPfDest({ id: r.dest_id, name: r.dest, cc: r.cc }); toast(`${r.dest} added to portfolio`); }
    });
  }
  function renderRdExtra() { $("#rdExtra").innerHTML = radar.extra.map((x) => `<span class="chip">${flag(x.cc)} ${esc(x.name)}</span>`).join(""); }
  async function loadRadar() {
    $("#rdStatus").innerHTML = `<i class="dot busy"></i><span>scanning…</span>`;
    const ids = radar.extra.length ? [...(state.catalog?.destinations || []).map((d) => d.id), ...radar.extra.map((x) => x.id)].join(",") : "";
    try {
      const r = await api("/radar" + qs({ weeks: radar.weeks, limit: 30, ...(radar.kinds ? { kinds: radar.kinds } : {}), ...(ids ? { ids } : {}) }), { channel: "radar" });
      radar.rows = r.rows;
      $("#rdStatus").innerHTML = `<i class="dot ok"></i><span>${r.scanned} destinations · ${r.seconds}s</span>`;
      $("#rdBody").innerHTML = r.rows.map((x, i) => `<tr style="animation-delay:${Math.min(i, 14) * 35}ms"><td><div class="scorebar"><em>${x.score}</em><i><b style="width:${x.score}%"></b></i></div></td>
        <td>${flag(x.cc)} <b>${esc(x.dest)}</b><br><small class="muted">${esc(x.type)}</small></td><td>${ICON[x.kind]} ${esc(x.product)}</td><td>${fmtDate(x.best_week)}</td>
        <td class="r">${x.demand.toLocaleString("en-IN")}</td><td class="r">${sgn(x.search_momentum)}</td><td class="r">${x.sold_out_weeks || "—"}</td>
        <td>${x.price_idx <= 0.97 ? '<span class="up-t">cheap</span>' : x.price_idx >= 1.08 ? '<span class="down-t">peak</span>' : "normal"} <small class="muted">${Math.round((x.price_idx - 1) * 100)}%</small></td>
        <td class="r">${x.margin_pct}%</td><td><div class="chips">${x.why.map((w) => `<span class="chip">${esc(w)}</span>`).join("")}</div></td>
        <td class="r"><button class="mini-btn" data-a="plan" data-i="${i}">Plan</button><button class="mini-btn" data-a="pf" data-i="${i}">+ Portfolio</button></td></tr>`).join("") || `<tr><td colspan="11"><div class="empty">No opportunities for this filter.</div></td></tr>`;
    } catch (e) { if (e.name !== "AbortError") $("#rdStatus").innerHTML = `<i class="dot err"></i><span>${esc(e.message)}</span>`; }
  }

  // ---------- portfolio ----------
  const pf = { budget: 3e7, dests: [{ id: "goa", name: "Goa", cc: "IN" }, { id: "dubai", name: "Dubai", cc: "AE" }, { id: "bali", name: "Bali", cc: "ID" }, { id: "london", name: "London", cc: "GB" }],
    kinds: { flight: true, hotel: true, "activity,transfer": true }, weeks: 8, risk: "balanced", data: null };
  function addPfDest(d) {
    if (pf.dests.some((x) => x.id === d.id)) return;
    if (pf.dests.length >= 8) return toast("Up to 8 destinations per portfolio");
    pf.dests.push({ id: d.id, name: d.name, cc: d.cc || "" }); renderPfDests();
    if (state.mod === "portfolio") loadPortfolio(); else prewarm([d.id]);
  }
  function renderPfDests() {
    $("#pfDests").innerHTML = pf.dests.map((d) => `<span class="dchip">${flag(d.cc)} ${esc(d.name)}<button type="button" data-id="${d.id}" aria-label="Remove ${esc(d.name)}">×</button></span>`).join("") || '<span class="muted small">Add destinations to build a portfolio.</span>';
  }
  function bindPortfolio() {
    const upd = () => { pf.budget = Math.max(1, +$("#pfBudget").value || 1) * +$("#pfUnit").value; $("#pfOut").textContent = inr(pf.budget); clearTimeout(upd.t); upd.t = setTimeout(loadPortfolio, 400); };
    $("#pfBudget").addEventListener("input", upd); $("#pfUnit").addEventListener("change", upd);
    bindSearch($("#pfAdd"), $("#pfAddSug"), (r) => { $("#pfAdd").value = ""; addPfDest({ id: r.id, name: r.name, cc: r.cc }); });
    $("#pfDests").addEventListener("click", (e) => { const b = e.target.closest("button[data-id]"); if (!b) return; pf.dests = pf.dests.filter((d) => d.id !== b.dataset.id); renderPfDests(); loadPortfolio(); });
    $$("#pfKinds .fchip").forEach((b) => b.addEventListener("click", () => { const k = b.dataset.k; if (Object.values(pf.kinds).filter(Boolean).length === 1 && pf.kinds[k]) return toast("Keep at least one product type"); pf.kinds[k] = !pf.kinds[k]; b.setAttribute("aria-pressed", pf.kinds[k]); loadPortfolio(); }));
    $$("#pfWeeks button").forEach((b) => b.addEventListener("click", () => { pf.weeks = +b.dataset.v; $$("#pfWeeks button").forEach((x) => x.setAttribute("aria-checked", x === b)); loadPortfolio(); }));
    $$("#pfRisk button").forEach((b) => b.addEventListener("click", () => setPfRisk(b.dataset.v)));
    $("#pfRiskGrid").addEventListener("click", (e) => { const b = e.target.closest(".rk"); if (b) setPfRisk(b.dataset.v); });
    $("#pfFromRadar").addEventListener("click", async () => {
      try {
        const r = await api("/radar?weeks=" + pf.weeks + "&limit=30"), seen = new Set();
        r.rows.forEach((x) => { if (seen.size < 5 && !seen.has(x.dest_id)) { seen.add(x.dest_id); if (!pf.dests.some((d) => d.id === x.dest_id) && pf.dests.length < 8) pf.dests.push({ id: x.dest_id, name: x.dest, cc: x.cc }); } });
        renderPfDests(); loadPortfolio(); toast("Radar's top destinations added");
      } catch { toast("Radar unavailable"); }
    });
    $("#pfBookAll").addEventListener("click", () => {
      if (!pf.data) return; let n = 0, sum = 0;
      pf.data.lines.forEach((l) => { const o = pfOrder(l); if (Orders.add(o)) { n++; sum += o.total; } });
      if (!n) return toast("Already booked"); Orders.save(); renderPfLines(); toast(`${n} lines booked · ${inr(sum)}`);
    });
    $("#pfLines").addEventListener("click", (e) => {
      const b = e.target.closest(".bk"); if (!b) return; const l = pf.data.lines[+b.dataset.i];
      if (Orders.add(pfOrder(l))) { Orders.save(); renderPfLines(); toast(`Booked ${l.q} · ${l.product}`); }
    });
  }
  function setPfRisk(v) { pf.risk = v; $$("#pfRisk button").forEach((x) => x.setAttribute("aria-checked", x.dataset.v === v)); loadPortfolio(); }
  const pfOrder = (l) => ({ mod: "portfolio", item: l.product, kind: l.kind, segment: l.segment, where: l.dest, cc: l.cc, week: l.week, qty: l.q, unit: UNIT[l.kind], unit_cost: l.unit_cost, sell_price: l.sell_price, total: l.spend });
  async function loadPortfolio() {
    if (!pf.dests.length) { $("#pfStatus").innerHTML = ""; return; }
    const kinds = Object.entries(pf.kinds).filter(([, v]) => v).map(([k]) => k).join(",");
    $("#pfStatus").innerHTML = `<i class="dot busy"></i><span>optimising ${pf.dests.length} destinations…</span>`;
    try {
      const d = await api("/portfolio" + qs({ ids: pf.dests.map((x) => x.id).join(","), budget_inr: Math.round(pf.budget), weeks: pf.weeks, risk: pf.risk, kinds }), { channel: "portfolio" });
      pf.data = d; renderPortfolio();
      $("#pfStatus").innerHTML = `<i class="dot ok"></i><span>${d.lines.length} lines · ${d.seconds}s</span>`;
    } catch (e) { if (e.name !== "AbortError") $("#pfStatus").innerHTML = `<i class="dot err"></i><span>${esc(e.message)}</span>`; }
  }
  const DCOL = ["--cyan", "--pink", "--volt", "--violet", "--good", "--orange", "--cyan", "--pink"];
  function renderPortfolio() {
    const d = pf.data, s = d.kpis.stockshock, t = d.kpis.today, pc = pct(s.expected_profit, t.expected_profit);
    const cards = [["--cyan", "Expected profit", s.expected_profit, (x) => inr(x), `today's rule <b>${inr(t.expected_profit)}</b><span class="delta ${pc >= 0 ? "up" : "down"}">${pc >= 0 ? "+" : ""}${pc.toFixed(0)}%</span>`],
      ["--good", "Return on spend", s.roi_pct, (x) => x.toFixed(0) + "%", `today's rule <b>${t.roi_pct.toFixed(0)}%</b>`],
      ["--volt", "Worst 5% of outcomes", -s.worst5_loss, (x) => (x >= 0 ? inr(x) + " profit" : inr(-x) + " loss"), `today's rule <b>${t.worst5_loss <= 0 ? inr(-t.worst5_loss) + " profit" : inr(t.worst5_loss) + " loss"}</b>`],
      ["--violet", "Budget used", s.spend, (x) => inr(x), `of ${inr(d.budget)} maximum · ${Math.round((100 * s.spend) / d.budget)}%`]];
    $("#pfKpis").innerHTML = cards.map((c, i) => `<div class="kpi st" style="--c:var(${c[0]});animation-delay:${i * 50}ms"><div class="k">${c[1]}</div><div class="v" id="pk${i}">–</div><div class="d">${c[4]}</div></div>`).join("");
    cards.forEach((c, i) => countUp($("#pk" + i), c[2], c[3]));
    const mx = Math.max(...d.by_dest.map((x) => x.spend), 1);
    $("#pfByDest").innerHTML = d.by_dest.map((x, i) => `<div class="hbar"><span>${flag(x.cc)} ${esc(x.name)}</span><i><b style="width:${(x.spend / mx) * 100}%;background:var(${DCOL[i % 8]})"></b></i><em>${inr(x.spend)}</em></div>`).join("") +
      `<div class="seg-list" style="margin-top:12px">${Object.entries(d.by_kind).map(([k, v]) => `<div class="seg-row"><i style="background:var(${k === "flight" ? "--volt" : k === "hotel" ? "--violet" : "--orange"})"></i><span>${ICON[k]} ${k[0].toUpperCase() + k.slice(1)}</span><b>${inr(v)}</b></div>`).join("")}</div>`;
    $("#pfUsed").textContent = `${inr(s.spend)} of ${inr(d.budget)}`;
    const ws = d.by_week.weeks, names = Object.keys(d.by_week.series), W = 380, H = 220, L = 52, B = 30, T = 10;
    const tot = ws.map((_, i) => names.reduce((a, n) => a + d.by_week.series[n][i], 0)), ymax = niceMax(Math.max(...tot, 1)), bw = (W - L - 10) / ws.length;
    let g = "";
    for (let k = 0; k <= 3; k++) { const v = (ymax * k) / 3, y = T + (H - T - B) * (1 - v / ymax); g += `<line class="grid" x1="${L}" x2="${W - 6}" y1="${y}" y2="${y}"/><text x="${L - 6}" y="${y + 4}" text-anchor="end">${inr(v)}</text>`; }
    ws.forEach((w, i) => {
      let acc = 0;
      names.forEach((n) => { const v = d.by_week.series[n][i], h = ((H - T - B) * v) / ymax, y = T + (H - T - B) * (1 - (acc + v) / ymax); acc += v; if (v > 0) g += `<rect class="grow-bar" style="animation-delay:${i * 40}ms" x="${L + i * bw + bw * .18}" y="${y}" width="${bw * .64}" height="${h}" fill="var(${DCOL[Math.max(0, d.by_dest.findIndex((b) => b.name === n)) % 8]})"/>`; });
      g += `<text x="${L + i * bw + bw / 2}" y="${H - 10}" text-anchor="middle">${fmtDate(w)}</text>`;
    });
    $("#pfWeekChart").innerHTML = g;
    const rc = d.risk_compare, ks = ["careful", "balanced", "bold"], maxP = Math.max(...ks.map((k) => rc[k].expected_profit), 1), nm = { careful: "🛡 Careful", balanced: "⚖ Balanced", bold: "🚀 Bold" };
    $("#pfRiskGrid").innerHTML = ks.map((k) => `<button class="rk${k === pf.risk ? " on" : ""}" data-v="${k}" type="button" style="--c:var(${RISK_COL[k]})"><h5>${nm[k]}</h5><div class="row">Expected profit<b>${inr(rc[k].expected_profit)}</b><div class="bar"><i style="width:${(rc[k].expected_profit / maxP) * 100}%"></i></div></div><div class="row">Worst 5%<b>${rc[k].worst5_loss <= 0 ? inr(-rc[k].worst5_loss) + " profit" : inr(rc[k].worst5_loss) + " loss"}</b></div><div class="row">Spend<b>${inr(rc[k].spend)}</b></div></button>`).join("");
    renderStress("#pfStress", d.stress);
    renderPfLines();
  }
  function renderPfLines() {
    const d = pf.data; $("#pfCount").textContent = `${d.lines.length} lines`;
    $("#pfLines").innerHTML = d.lines.slice(0, 60).map((l, i) => {
      const booked = Orders.has(Orders.key(pfOrder(l)));
      return `<tr style="animation-delay:${Math.min(i, 14) * 30}ms"><td>${flag(l.cc)} ${esc(l.dest)}</td><td>${ICON[l.kind]} ${esc(l.product)}</td><td>${fmtDate(l.week)}</td><td><span class="badge ${l.action}">${ACT[l.action] || l.action}</span></td>
      <td class="r">${l.q} ${UNIT[l.kind]}<br><small class="muted">today ${l.q_today}</small></td><td class="r">${inr(l.sell_price)} ${l.price_change_pct ? sgn(l.price_change_pct) : ""}</td><td class="r">${inr(l.spend)}</td>
      <td class="small">${(l.drivers || []).slice(0, 2).map((x) => `<span class="chip">${esc(x)}</span>`).join(" ")}</td>
      <td class="r"><button class="bk${booked ? " done" : ""}" type="button" data-i="${i}" ${booked ? "disabled" : ""}>${booked ? "✓" : "Book"}</button></td></tr>`;
    }).join("");
  }

  // ---------- landing extras ----------
  function landing() {
    const words = ["flight seats", "business hotels", "airport hotels", "resort nights", "ski passes", "safari lodges"]; let wi = 0; const rot = $("#rotator");
    if (!REDUCED) setInterval(() => { if ($("#landing").hidden) return; wi = (wi + 1) % words.length; const old = rot.firstElementChild; old.classList.add("out"); const n = document.createElement("span"); n.textContent = words[wi]; rot.appendChild(n); setTimeout(() => old.remove(), 460); }, 2300);
    $$("[data-count]").forEach((el) => countUp(el, +el.dataset.count, (x) => Math.round(x).toLocaleString("en-IN"), 1500));
    $$(".rv").forEach((el, i) => (el.style.animationDelay = `${i * 50}ms`));
  }
  function clock() { const t = () => ($("#clock").textContent = new Date().toLocaleTimeString("en-GB", { timeZone: "Asia/Kolkata" }) + " IST"); t(); setInterval(t, 1000); }

  // ---------- boot: landing paints first, data and engine warm up behind it ----------
  async function boot() {
    Orders.load(); updateCart(); streaks(); sparks(); landing(); clock(); bindControls(); bindOrders(); bindRadar(); bindPortfolio();
    const [g, top] = await Promise.all([fetch("data/globe.json").then((r) => r.json()).catch(() => []), fetch("data/top.json").then((r) => r.json()).catch(() => [])]);
    geo.dots = g; geo.top = top; geo.lights = top.slice(0, 420).map((t) => [t[3], t[4], t[5]]);
    globeBig = new Globe($("#globe"), { interactive: true });
    try { state.catalog = await api("/catalog"); } catch { $("#liveTxt").textContent = "Engine offline"; }
    addEventListener("hashchange", route);
    route();
    if (state.catalog) api("/plan" + qs(params(state.m.flights, "flights"))).catch(() => {});   // warm the default route
  }
  boot();
})();
