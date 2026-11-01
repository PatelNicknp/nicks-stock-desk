/* Nick's Stock Desk. Reads published CSVs. No broker calls and no new market requests. */
(function () {
  const UP = "#22C55E";
  const DN = "#EF4444";
  const AM = "#F59E0B";
  const AC = "#7C9CFF";
  const MU = "#8B96AD";
  const TX = "#E6EBF5";
  // ---------- Light mode ----------
  // The CSS swaps its color variables on html[data-theme=light]. Colors written by the page scripts (inline styles,
  // Chart.js and price-chart canvases) are swapped through LIGHT_MAP, so every page and chart reads on white.
  const LIGHT_MAP = {
    "#0b0f17": "#FFFFFF", "#121826": "#FFFFFF", "#0f1420": "#F8FAFC", "#1a2236": "#EAF0FB", "#1e293b": "#E2E8F0", "#161e2e": "#EEF1F6",
    "#2a3550": "#CBD5E1", "#334155": "#CBD5E1", "#3a4560": "#A0AEC0", "#3a4a6b": "#94A3B8",
    "#e6ebf5": "#111827", "#c3cbdb": "#475569", "#8b96ad": "#566176", "#5b6680": "#6B7280", "#94a3b8": "#64748B",
    "#7c9cff": "#3355D1", "#f59e0b": "#A44A06", "#22c55e": "#137336", "#ef4444": "#C81E1E", "#d6a64a": "#8A5A06",
    "#1f9d55": "#16A34A", "#d14343": "#C81E1E",
    "#166534": "#86EFAC", "#14532d": "#BBF7D0", "#283146": "#E5E7EB", "#7f1d1d": "#FECACA", "#b91c1c": "#FCA5A5",
    "#e879f9": "#C026D3", "#38bdf8": "#0284C7", "#f472b6": "#DB2777", "#34d399": "#059669", "#fb923c": "#EA580C",
    "#a78bfa": "#7C3AED", "#fb7185": "#E11D48", "#fbbf24": "#CA8A04", "#2dd4bf": "#0D9488", "#c084fc": "#9333EA",
  };
  const THEME_KEY = "desk-theme";
  let LIGHT = false;
  function lightColor(v) {
    if (!LIGHT || typeof v !== "string" || v.indexOf("#") < 0) return v;
    return v.replace(/#[0-9a-fA-F]{6}(?![0-9a-fA-F])/g, (m) => LIGHT_MAP[m.toLowerCase()] || m);
  }
  function themed(obj) {
    if (!LIGHT) return obj;
    if (typeof obj === "string") return lightColor(obj);
    if (typeof obj === "function") {
      const fn = obj;
      return function () { return themed(fn.apply(this, arguments)); };
    }
    if (Array.isArray(obj)) return obj.map(themed);
    if (obj && typeof obj === "object" && Object.getPrototypeOf(obj) === Object.prototype) {
      const out = {};
      Object.keys(obj).forEach((k) => { out[k] = themed(obj[k]); });
      return out;
    }
    return obj;
  }
  // A price chart whose series and price lines take light colors too.
  function themedChart(chart) {
    if (!LIGHT || !chart || chart._themed) return chart;
    chart._themed = true;
    const add = chart.addSeries.bind(chart);
    chart.addSeries = function (type, opts, pane) {
      const series = pane == null ? add(type, themed(opts || {})) : add(type, themed(opts || {}), pane);
      const line = series.createPriceLine && series.createPriceLine.bind(series);
      if (line) series.createPriceLine = (o) => line(themed(o));
      const apply = series.applyOptions.bind(series);
      series.applyOptions = (o) => apply(themed(o));
      return series;
    };
    return chart;
  }
  function storedTheme() {
    try {
      const v = localStorage.getItem(THEME_KEY);
      if (v === "dark" || v === "light" || v === "auto") return v;
    } catch (e) { /* storage can be blocked */ }
    return "";
  }
  const deviceLight = typeof window.matchMedia === "function" ? window.matchMedia("(prefers-color-scheme: light)") : null;
  function resolveTheme(choice) {
    if (choice === "light") return "light";
    if (choice === "auto") return deviceLight && deviceLight.matches ? "light" : "dark";
    return "dark";
  }
  function applyTheme(choice) {
    LIGHT = resolveTheme(choice) === "light";
    document.documentElement.setAttribute("data-theme", LIGHT ? "light" : "dark");
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", LIGHT ? "#F4F6FA" : "#0B0F17");
    if (LIGHT) recolor(document.body);
  }
  function recolorEl(el) {
    const st = el.getAttribute && el.getAttribute("style");
    if (!st || st.indexOf("#") < 0) return;
    const next = lightColor(st);
    if (next !== st) el.setAttribute("style", next);
  }
  function recolor(root) {
    if (!LIGHT || !root || root.nodeType !== 1) return;
    recolorEl(root);
    root.querySelectorAll("[style]").forEach(recolorEl);
  }
  // Canvas drawing (Chart.js, the price charts, custom plugins) goes through these setters.
  (function patchCanvas() {
    if (typeof CanvasRenderingContext2D === "undefined") return;
    ["fillStyle", "strokeStyle", "shadowColor"].forEach((prop) => {
      const d = Object.getOwnPropertyDescriptor(CanvasRenderingContext2D.prototype, prop);
      if (!d || !d.set || !d.configurable) return;
      Object.defineProperty(CanvasRenderingContext2D.prototype, prop, {
        configurable: true,
        enumerable: d.enumerable,
        get: d.get,
        set: function (v) { d.set.call(this, lightColor(v)); },
      });
    });
  })();
  if (typeof MutationObserver !== "undefined") {
    new MutationObserver((list) => {
      if (!LIGHT) return;
      list.forEach((m) => {
        if (m.type === "attributes") recolorEl(m.target);
        else m.addedNodes.forEach((n) => recolor(n));
      });
    }).observe(document.documentElement, { subtree: true, childList: true, attributes: true, attributeFilter: ["style"] });
  }
  applyTheme(storedTheme() || "dark");

  const RESEARCH = "Research only. Not a recommendation to buy or sell. This desk never places trades. Stocks only, no option contracts.";
  const NAV = [
    ["Overview", [
      ["Today", "index.html", "today"],
      ["Top stocks", "top-stocks.html", "top"],
      ["Buy setups", "buy-setups.html", "buysetups"],
      ["Stock scorecard", "scorecard.html", "scorecard"],
      ["Watchlist and portfolio", "watchlist.html", "watchlist"],
      ["Alerts", "alerts.html", "alerts"],
      ["Backtest", "backtest.html", "backtest"],
    ]],
    ["Chart Viewer", [
      ["Chart Viewer", "chart-viewer.html", "chartviewer"],
    ]],
    ["Scanners", [
      ["Growth", "growth.html", "growth"],
      ["Quality", "quality.html", "quality"],
      ["Dividend", "dividend.html", "dividend"],
      ["Wheel (stocks only)", "wheel.html", "wheel"],
      ["VCP", "vcp.html", "vcp"],
      ["CANSLIM", "canslim.html", "canslim"],
      ["Box breakout", "box.html", "box"],
      ["Flag breakout", "flag.html", "flag"],
      ["Qullamaggie breakout", "qullamaggie.html", "qullamaggie"],
      ["Marios breakout", "marios.html", "marios"],
      ["Episodic pivot", "episodic-pivot.html", "ep"],
      ["Gap Up", "gap-up.html", "gapup"],
      ["Breakdowns", "breakdowns.html", "breakdowns"],
      ["High volume", "volume.html", "volume"],
      ["Leaders", "leaders.html", "leaders"],
      ["52-week", "52-week.html", "week52"],
    ]],
    ["Options", [
      ["Debit spreads", "options.html", "options"],
    ]],
    ["Earnings", [
      ["Calendar", "earnings-calendar.html", "calendar"],
      ["Strength heatmap", "earnings-heatmap.html", "heatmap"],
      ["Report cards", "earnings-cards.html", "cards"],
    ]],
    ["Sentiment", [
      ["Put/call ratio", "put-call.html", "putcall"],
      ["Put and call walls", "walls.html", "walls"],
      ["Analyst ratings", "analysts.html", "analysts"],
      ["13F tracker", "thirteen-f.html", "thirteen"],
      ["AAII", "aaii.html", "aaii"],
      ["Insider trading", "insiders.html", "insiders"],
      ["Headline sentiment", "headlines.html", "headlines"],
      ["XLY/XLP", "xly-xlp.html", "xly"],
    ]],
    ["Financials", [
      ["Summary", "financials.html", "financials"],
      ["Earnings tracker", "earnings-tracker.html", "tracker"],
      ["Company financials", "company-financials.html", "company"],
      ["Dividend fundamentals", "dividend-fundamentals.html", "divfund"],
    ]],
    ["Macro", [
      ["Sector rotation", "sector-rotation.html", "rotation"],
      ["Macro screener", "macro.html", "macro"],
      ["Sector macro scores", "sector-macro.html", "secmacro"],
      ["Historical P/E", "historical-pe.html", "histpe"],
    ]],
    ["Technicals", [
      ["52-week breakouts", "breakouts.html", "breakouts"],
      ["Trends", "trends.html", "trends"],
      ["Pullbacks", "pullbacks.html", "pullbacks"],
      ["Gainers and losers", "gainers.html", "gainers"],
      ["Breadth", "breadth.html", "breadth"],
      ["Sector performance", "sector-performance.html", "secperf"],
      ["Heatmaps", "heatmaps.html", "heatmaps"],
    ]],
    ["System", [
      ["Data updates", "updates.html", "updates"],
      ["Help", "help.html", "help"],
    ]],
  ];

  const cache = new Map();
  const charts = [];
  const SPD = {
    XLK: "Technology", XLV: "Health Care", XLF: "Financials", XLI: "Industrials",
    XLC: "Communication", XLY: "Discretionary", XLP: "Staples", XLE: "Energy",
    XLU: "Utilities", XLRE: "Real Estate", XLB: "Materials",
  };

  function csvUrl(name) {
    if (location.hostname.endsWith("github.io")) {
      return "https://raw.githubusercontent.com/PatelNicknp/nicks-stock-desk/main/data/" + name;
    }
    return new URL("../data/" + name, location.href).href;
  }

  function loadCsv(name) {
    if (!cache.has(name)) {
      cache.set(name, new Promise((resolve, reject) => {
        if (typeof Papa === "undefined") {
          reject(new Error("PapaParse did not load"));
          return;
        }
        Papa.parse(csvUrl(name), {
          download: true,
          header: true,
          skipEmptyLines: "greedy",
          complete: (res) => {
            const fatal = (res.errors || []).filter((e) => e.code !== "UndetectableDelimiter");
            if ((!res.data || !res.data.length) && fatal.length) {
              reject(new Error(name + ": " + fatal[0].message));
              return;
            }
            resolve((res.data || []).map(cleanRow));
          },
          error: (err) => reject(err instanceof Error ? err : new Error(String(err))),
        });
      }));
    }
    return cache.get(name);
  }

  function cleanRow(row) {
    const o = {};
    Object.keys(row).forEach((k) => {
      const key = String(k).replace(/^\uFEFF/, "").trim();
      let v = row[k];
      if (v == null) { o[key] = ""; return; }
      v = String(v).trim();
      const low = v.toLowerCase();
      if (!v || low === "nan" || low === "none" || low === "null" || low === "nat") o[key] = "";
      else o[key] = v;
    });
    return o;
  }

  function isBlank(v) {
    return v == null || String(v).trim() === "";
  }

  // One-line plain-English company descriptions from data/company_blurbs.csv.
  // Static file, loaded once per visit and kept in sessionStorage. Never fetched from a market API.
  let BLURBS = {};
  function blurbsOn() { return featureOn("feature.company_blurbs"); }
  function loadBlurbs() {
    if (!blurbsOn()) return Promise.resolve(BLURBS);
    try {
      const saved = sessionStorage.getItem("desk-blurbs-v1");
      if (saved) { BLURBS = JSON.parse(saved) || {}; return Promise.resolve(BLURBS); }
    } catch (e) { /* ignore */ }
    return loadCsv("company_blurbs.csv").then((rows) => {
      const map = {};
      (rows || []).forEach((r) => {
        const t = String(r.ticker || "").trim().toUpperCase();
        if (t && !isBlank(r.blurb)) map[t] = String(r.blurb).trim();
      });
      BLURBS = map;
      try { sessionStorage.setItem("desk-blurbs-v1", JSON.stringify(map)); } catch (e) { /* ignore */ }
      return BLURBS;
    }).catch(() => BLURBS);
  }
  function blurbOf(ticker) {
    if (!blurbsOn()) return "";
    return BLURBS[String(ticker || "").trim().toUpperCase()] || "";
  }
  function blurbHtml(ticker) {
    const text = blurbOf(ticker);
    return text ? '<p class="blurb">' + esc(text) + "</p>" : "";
  }
  function num(v) {
    if (isBlank(v)) return null;
    const n = Number(String(v).replace(/,/g, ""));
    return Number.isFinite(n) ? n : null;
  }
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function na() { return '<span class="na">–</span>'; }
  function fmt(v, d) {
    const n = num(v);
    if (n == null) return null;
    return n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  }
  function compact(v) {
    const n = num(v);
    if (n == null) return null;
    const a = Math.abs(n);
    const sign = n < 0 ? "-" : "";
    if (a >= 1e12) return sign + (a / 1e12).toFixed(1) + "T";
    if (a >= 1e9) return sign + (a / 1e9).toFixed(1) + "B";
    if (a >= 1e6) return sign + (a / 1e6).toFixed(1) + "M";
    if (a >= 1e3) return sign + (a / 1e3).toFixed(1) + "K";
    return fmt(n, a >= 100 ? 0 : 2);
  }
  function band(s) {
    if (s >= 12) return "#166534";
    if (s >= 9) return "#14532D";
    if (s >= 5) return "#283146";
    if (s >= 1) return "#7F1D1D";
    return "#B91C1C";
  }
  function ptsColor(v) {
    if (v == null) return null;
    if (v >= 2) return "#166534";
    if (v >= 1) return "#14532D";
    if (v > -1) return "#283146";
    if (v > -2) return "#7F1D1D";
    return "#B91C1C";
  }
  function retColor(n) {
    if (n == null) return MU;
    if (n > 0) return UP;
    if (n < 0) return DN;
    return TX;
  }
  function formatUpdated(s) {
    const m = String(s || "").match(/(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
    if (!m) return s || "n/a";
    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    let h = Number(m[4]);
    const ap = h >= 12 ? "PM" : "AM";
    h = h % 12 || 12;
    return months[Number(m[2]) - 1] + " " + Number(m[3]) + ", " + h + ":" + m[5] + " " + ap + " PT";
  }
  function latestChecked(rows) {
    let best = "";
    (rows || []).forEach((r) => { if ((r.checked_pt || "") > best) best = r.checked_pt; });
    return best;
  }
  function realRows(rows) {
    return (rows || []).filter((r) => r.data_status !== "MISSING");
  }
  function statusOf(rows) {
    const bad = (rows || []).find((r) => r.data_status === "MISSING" || r.data_status === "PARTIAL");
    return bad || null;
  }
  function banner() {
    // Loud PARTIAL and MISSING banners are retired. A failed file load uses .banner.miss in boot.
    return "";
  }
  function feedHtml(rows) {
    const bad = statusOf(rows);
    if (!bad || bad.data_status !== "MISSING") return "";
    const note = bad.note ? " · " + bad.note : "";
    return '<div class="feed">' + esc(bad.data_status + note) + "</div>";
  }
  function placeFeed(box, rows) {
    if (!box) return;
    const html = feedHtml(rows);
    if (html) box.insertAdjacentHTML("beforeend", html);
  }
  function noteOf(rows) {
    const r = (rows || []).find((x) => x.note);
    return r ? r.note : "";
  }

  function scoreHtml(v) {
    const n = num(v);
    if (n == null) return na();
    const shown = Number.isInteger(n) ? String(n) : fmt(n, 1);
    return '<span class="scorepill" style="background:' + band(n) + '">' + esc(shown) + "</span>";
  }
  function scoreFill(v) {
    const n = num(v);
    if (n == null) return na();
    const shown = Number.isInteger(n) ? String(n) : fmt(n, 1);
    return '<span class="scorefill" style="background:' + band(n) + '">' + esc(shown) + "</span>";
  }
  function tickerHtml(v) {
    if (isBlank(v)) return na();
    return '<a class="tk" href="scorecard.html?t=' + encodeURIComponent(v) + '">' + esc(v) + "</a>";
  }
  function etfHtml(v) {
    if (isBlank(v)) return na();
    return '<span class="tk">' + esc(v) + "</span>";
  }
  function colored(text, color, lite) {
    if (isBlank(text)) return na();
    return '<span class="pill' + (lite ? " lite" : "") + '" style="color:' + color + '">' + esc(text) + "</span>";
  }
  function verdictHtml(v) {
    const map = { BUY: UP, HOLD: AM, AVOID: DN };
    return colored(v, map[v] || TX);
  }
  function trendHtml(v) {
    const map = {
      Uptrend: UP, Downtrend: DN, Extended: AM, Sideways: MU, Mixed: MU,
      "In entry zone": AC, Breakout: TX, Pullback: TX,
    };
    return colored(v, map[v] || TX, true);
  }
  function setupHtml(v) {
    const map = { "BROKEN OUT today": UP, READY: AM, WATCHING: MU, "WATCHING (trend not 8/8)": MU, "IN TRADE": AC, CLOSED: MU, SELL: DN, "SELL 1/3": AM, EXIT: DN, STOPPED: DN, HOLD: MU,
      "EP TODAY - FORMING": AM, "EP TODAY - CONFIRMED": UP, "DAY 2-5 WATCH": AM, "DELAYED EP WATCH": MU, "EP FADED": DN,
      "SELL PART": AM, "NO FOLLOW-THROUGH": AM };
    return colored(v, map[v] || TX);
  }
  function freshHtml(v) {
    const map = { FRESH: MU, PARTIAL: AM, STALE: DN, OK: MU, CACHED: MU, MISSING: AM };
    const label = v === "FRESH" ? "Fresh" : v;
    return colored(label, map[v] || TX, true);
  }
  function passHtml(v) {
    const s = String(v || "");
    if (isBlank(s)) return na();
    const up = s.toUpperCase();
    if (up === "PASS" || s === "yes" || s === "strict") return colored(s, UP);
    if (up === "FAIL" || s === "no") return colored(s, DN);
    if (s === "soft") return colored(s, AM);
    return esc(s);
  }
  function signedPts(n) {
    if (n > 0) return "+" + (Number.isInteger(n) ? String(n) : fmt(n, 1));
    if (n < 0) return "−" + (Number.isInteger(n) ? String(Math.abs(n)) : fmt(Math.abs(n), 1));
    return "0";
  }
  function pointsHtml(v) {
    const n = num(v);
    if (n == null) return na();
    const bg = ptsColor(n) || "#283146";
    return '<span class="pts" style="background:' + bg + '">' + esc(signedPts(n)) + "</span>";
  }
  function pointsLabelHtml(v) {
    if (isBlank(v) || v === "n/a") return na();
    const map = { "plus 2": 2, "plus 1": 1, "zero": 0, "minus 1": -1, "minus 2": -2 };
    if (Object.prototype.hasOwnProperty.call(map, v)) return pointsHtml(map[v]);
    const n = num(v);
    if (n == null) return na();
    return pointsHtml(n);
  }
  function gradeHtml(v) {
    const fills = { A: "#166534", B: "#14532D", C: "#283146", D: "#7F1D1D", F: "#B91C1C" };
    if (isBlank(v)) return na();
    return '<span class="gradechip" style="background:' + (fills[v] || "#283146") + '">' + esc(v) + "</span>";
  }
  function holdHtml(v) {
    const map = { "Below stop": DN, Weakening: AM, "Earnings soon": AC, "On track": MU };
    return colored(v, map[v] || TX);
  }
  function kindHtml(v) {
    const map = {
      score_jump: ["Score jump", "#C3CBDB"],
      verdict_change: ["Verdict change", AM],
      score_cross: ["Crossed buy line", "#C3CBDB"],
      entry_zone: ["Entry zone", AC],
      breakout: ["Breakout", UP],
      new_stock: ["New stock", "#C3CBDB"],
      info: ["Note", MU],
    };
    const pair = map[v] || [v, "#C3CBDB"];
    return colored(pair[0], pair[1], true);
  }
  function zoneHtml(v) {
    const map = { Fear: DN, Greed: UP, Neutral: AM, "Risk on": UP, "Risk off": DN };
    return colored(v, map[v] || AM);
  }
  function toneHtml(v) {
    const n = num(v);
    if (n == null) return na();
    const bg = n > 0 ? "#14532D" : n < 0 ? "#7F1D1D" : "#283146";
    return '<span class="pts" style="background:' + bg + '">' + esc(signedPts(n)) + "</span>";
  }
  function flagHtml(v, col) {
    if (isBlank(v)) return na();
    const yes = (col && col.yes) || UP;
    const no = (col && col.no) || MU;
    const n = num(v);
    if (n === 1 || v === "yes" || v === "true") return colored("Yes", yes);
    if (n === 0 || v === "no" || v === "false") return colored("No", no);
    return esc(v);
  }
  function moneyHtml(v, d, colorRet) {
    const n = num(v);
    if (n == null) return na();
    const sign = n < 0 ? "-$" : (colorRet && n > 0 ? "+$" : "$");
    const text = sign + fmt(Math.abs(n), d == null ? 2 : d);
    if (!colorRet) return esc(text);
    return '<span style="color:' + retColor(n) + '">' + esc(text) + "</span>";
  }
  function pctHtml(v, d, colorRet) {
    const n = num(v);
    if (n == null) return na();
    const text = (colorRet && n > 0 ? "+" : "") + fmt(n, d == null ? 2 : d) + "%";
    if (!colorRet) return esc(text);
    return '<span style="color:' + retColor(n) + '">' + esc(text) + "</span>";
  }
  function heatPct(v, d) {
    const n = num(v);
    if (n == null) return na();
    const mag = Math.min(Math.abs(n) / 5, 1);
    const bg = n > 0 ? "rgba(34,197,94," + (0.18 + mag * 0.55) + ")" : n < 0 ? "rgba(239,68,68," + (0.18 + mag * 0.55) + ")" : "transparent";
    const text = (n > 0 ? "+" : "") + fmt(n, d == null ? 1 : d) + "%";
    return '<span class="heat" style="background:' + bg + '">' + esc(text) + "</span>";
  }
  function distHtml(v) {
    const n = num(v);
    if (n == null) return na();
    const color = n > 0 ? AM : n < 0 ? DN : UP;
    return '<span style="color:' + color + '">' + esc(fmt(n, 2) + "%") + "</span>";
  }

  function cell(row, col) {
    const v = row[col.key];
    const d = col.dec == null ? 2 : col.dec;
    switch (col.kind) {
      case "ticker": return tickerHtml(v);
      case "etf": return etfHtml(v);
      case "score": return scoreFill(v);
      case "scorejump": {
        const a = isBlank(row.score_prev) ? na() : esc(String(row.score_prev).replace(/\.0$/, ""));
        const b = isBlank(row.score) ? na() : esc(String(row.score).replace(/\.0$/, ""));
        return a + " → " + b;
      }
      case "verdict": return verdictHtml(v);
      case "trend": return trendHtml(v);
      case "quad": {
        const map = { Leading: "#22C55E", Weakening: "#F59E0B", Lagging: "#EF4444", Improving: "#7C9CFF" };
        return colored(v, map[v] || TX, true);
      }
      case "setup": return setupHtml(v);
      case "fresh": return freshHtml(v);
      case "pass": return passHtml(v);
      case "points": return pointsHtml(v);
      case "plabel": return pointsLabelHtml(v);
      case "grade": return gradeHtml(v);
      case "hold": return holdHtml(v);
      case "kind": return kindHtml(v);
      case "zone": return zoneHtml(v);
      case "tone": return toneHtml(v);
      case "signal": return toneHtml(v);
      case "flag": return flagHtml(v, col);
      case "owns": {
        if (v === "yes") return '<span style="color:#F59E0B;font-weight:700">yes</span>';
        if (v === "no") return '<span style="color:#5B6680">no</span>';
        return na();
      }
      case "delta": {
        const n = num(v);
        if (n == null) return na();
        const text = n > 0 ? "+" + fmt(n, d) : (n < 0 ? "−" + fmt(Math.abs(n), d) : "0");
        return '<span style="color:' + retColor(n) + '">' + esc(text) + "</span>";
      }
      case "money": return moneyHtml(v, d, !!col.color);
      case "compact": return isBlank(v) ? na() : esc(compact(v));
      case "dollars": {
        const c = compact(v);
        if (c == null) return na();
        const n = num(v);
        return esc((n < 0 ? "-$" : "$") + String(c).replace(/^-/, ""));
      }
      case "pct": return pctHtml(v, d, col.color === true);
      case "multiple": {
        const n = num(v);
        if (n == null || Math.abs(n) > 500) return na();
        return esc(fmt(n, d));
      }
      case "volx": {
        const n = num(v);
        if (n == null) return na();
        const text = fmt(n, d);
        return n >= 1.5 ? '<span style="color:#22C55E;font-weight:700">' + esc(text) + "</span>" : esc(text);
      }
      case "retrace": {
        const n = num(v);
        if (n == null) return na();
        const color = n >= 50 ? AM : TX;
        return '<span style="color:' + color + '">' + esc(fmt(n, d) + "%") + "</span>";
      }
      case "strengthbar": {
        const n = num(v);
        if (n == null) return na();
        const w = Math.max(4, Math.min(72, n * 0.72));
        return '<span class="bar" style="width:' + w + 'px"></span>' + esc(fmt(n, 0));
      }
      case "daybar": {
        const n = num(v);
        if (n == null) return na();
        const w = Math.max(4, Math.min(88, Math.abs(n) / 3 * 88));
        const color = n >= 0 ? "#1F9D55" : "#D14343";
        return '<span class="track"><span class="fill" style="width:' + w + 'px;background:' + color + '"></span></span>';
      }
      case "rangepos": {
        const n = num(v);
        if (n == null) return na();
        const clamped = Math.max(0, Math.min(100, n));
        const w = Math.max(0, Math.round(clamped / 100 * 88));
        const color = clamped >= 95 ? UP : clamped <= 15 ? DN : AC;
        return '<span class="track" title="' + esc(fmt(n, 0)) + '"><span class="fill" style="width:' + w + 'px;background:' + color + '"></span></span> ' + esc(fmt(n, 0));
      }
      case "shortdate": {
        const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(v || ""));
        if (!m) return isBlank(v) ? na() : esc(v);
        const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
        return esc(months[Number(m[2]) - 1] + " " + Number(m[3]));
      }
      case "fy": {
        const m = /^(\d{4})/.exec(String(v || ""));
        return m ? esc("FY" + m[1].slice(2)) : na();
      }
      case "of8": {
        const m = String(v || "").match(/(\d+)\s*of\s*(\d+)/i);
        if (m) return esc(m[1] + "/" + m[2]);
        return isBlank(v) ? na() : esc(v);
      }
      case "itrend": {
        const s = String(v || "").toLowerCase();
        if (!s) return na();
        const color = s === "up" ? UP : s === "down" ? DN : MU;
        return '<span style="color:' + color + '">' + esc(v) + "</span>";
      }
      case "heatpct": return heatPct(v, d);
      case "dist": return distHtml(v);
      case "num": {
        if (num(v) == null) return na();
        const text = fmt(v, d);
        if (col.tone === "stop") return '<span style="color:#EF4444">' + esc(text) + "</span>";
        if (col.tone === "target") return '<span style="color:#22C55E">' + esc(text) + "</span>";
        return esc(text);
      }
      case "count": {
        const cn = num(v);
        if (cn == null) return na();
        const text = fmt(cn, 0);
        if (cn > 0 && col.up) return '<span style="color:' + col.up + ';font-weight:700">' + esc(text) + "</span>";
        return esc(text);
      }
      case "buysell": {
        const s = String(v || "").toUpperCase();
        if (s === "BUYING") return '<span style="color:' + UP + ';font-weight:700">BUYING</span>';
        if (s === "SELLING") return '<span style="color:' + DN + ';font-weight:700">SELLING</span>';
        return isBlank(v) ? na() : '<span style="color:' + MU + '">' + esc(v) + "</span>";
      }
      case "updown": {
        const s = String(v || "").toUpperCase();
        if (s === "BUYING") return '<span style="color:' + UP + '">▲ Up</span>';
        if (s === "SELLING") return '<span style="color:' + DN + '">▼ Down</span>';
        return isBlank(v) ? na() : '<span style="color:' + MU + '">Flat</span>';
      }
      case "abovebelow": {
        const s = String(v || "").toLowerCase();
        if (s === "above") return '<span style="color:' + UP + '">Above</span>';
        if (s === "below") return '<span style="color:' + DN + '">Below</span>';
        return na();
      }
      case "side": {
        const s = String(v || "").toLowerCase();
        if (s === "call") return '<span style="color:#22C55E;font-weight:700">Call</span>';
        if (s === "put") return '<span style="color:#EF4444;font-weight:700">Put</span>';
        return isBlank(v) ? na() : esc(v);
      }
      case "result": {
        const s = String(v || "").toLowerCase();
        if (!s) return na();
        const color = s === "beat" ? UP : s === "miss" ? DN : MU;
        return '<span style="color:' + color + '">' + esc(v) + "</span>";
      }
      case "earnlabel": {
        const s = String(v || "").toLowerCase();
        if (!s) return na();
        let color = TX;
        if (s.indexOf("incomplete") >= 0) color = "#D6A64A";
        else if (s.indexOf("miss") >= 0) color = DN;
        else if (s.indexOf("beat") >= 0) color = UP;
        else if (s.indexOf("inline") >= 0 || s.indexOf("in line") >= 0) color = MU;
        return '<span style="color:' + color + '">' + esc(v) + "</span>";
      }
      case "surprise": {
        const n = num(v);
        if (n == null) return na();
        const sig = num(row.signal);
        const color = sig == null ? MU : sig > 0 ? UP : sig < 0 ? DN : MU;
        const body = compact(Math.abs(n));
        const sign = n > 0 ? "+" : n < 0 ? "−" : "";
        return '<span style="color:' + color + '">' + esc(sign + body) + "</span>";
      }
      case "signedcompact": {
        const n = num(v);
        if (n == null) return na();
        const body = compact(Math.abs(n));
        const sign = n > 0 ? "+" : n < 0 ? "−" : "";
        return '<span style="color:' + retColor(n) + '">' + esc(sign + body) + "</span>";
      }
      case "onoff": {
        const s = String(v || "").toLowerCase();
        if (s === "true" || s === "yes" || s === "1") return '<span style="color:#22C55E">On</span>';
        if (s === "false" || s === "no" || s === "0") return '<span style="color:#8B96AD">Off</span>';
        return isBlank(v) ? na() : esc(v);
      }
      case "checked": return isBlank(v) ? na() : esc(formatUpdated(v).replace(/ PT$/, ""));
      case "item": return isBlank(v) ? na() : '<span style="font-weight:700;color:#E6EBF5">' + esc(v) + "</span>";
      case "muted": return isBlank(v) ? na() : '<span style="color:#8B96AD">' + esc(v) + "</span>";
      case "date": {
        const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(v || ""));
        if (!m) return isBlank(v) ? na() : esc(v);
        const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
        return esc(months[Number(m[2]) - 1] + " " + Number(m[3]) + ", " + m[1]);
      }
      case "ownpts": {
        const sector = String(row.note || "").toLowerCase().indexOf("sector") >= 0;
        if (sector || isBlank(v)) {
          return na() + (sector ? ' <span class="tag">sector used</span>' : "");
        }
        return pointsHtml(v);
      }
      case "owncap": {
        const n = num(v);
        if (n == null) return na();
        if (n >= 100 || String(row.note || "").toLowerCase().indexOf("capped") >= 0) {
          return '<span style="color:#8B96AD" title="Dash = not shown. The free source counts some holders twice, so the total can top 100%.">–</span>';
        }
        return esc(fmt(n, d) + "%");
      }
      default:
        return isBlank(v) ? na() : esc(v);
    }
  }

  function align(col) {
    if (col.align) return col.align;
    if (["num", "pct", "money", "compact", "dist", "heatpct"].indexOf(col.kind) >= 0) return "num";
    if (["score", "points", "plabel", "grade", "flag", "tone", "signal"].indexOf(col.kind) >= 0) return "c";
    return "";
  }

  function compare(a, b, col, dir) {
    const va = a[col.key];
    const vb = b[col.key];
    const numeric = ["num", "pct", "money", "compact", "dollars", "dist", "score", "points", "tone", "signal", "flag", "heatpct", "delta", "multiple", "volx", "retrace", "strengthbar", "daybar", "rangepos", "scorejump", "count", "signedcompact", "of8", "owncap"].indexOf(col.kind) >= 0;
    let c = 0;
    if (numeric) {
      const pull = (value) => {
        if (col.kind === "of8") {
          const m = String(value || "").match(/(\d+)/);
          return m ? Number(m[1]) : null;
        }
        if (col.kind === "owncap") {
          const n = num(value);
          if (n != null && n >= 100) return null;
          return n;
        }
        return num(value);
      };
      const na_ = pull(va);
      const nb_ = pull(vb);
      if (na_ == null && nb_ == null) return 0;
      if (na_ == null) return 1;
      if (nb_ == null) return -1;
      c = col.abs ? Math.abs(na_) - Math.abs(nb_) : na_ - nb_;
    } else {
      const ea = String(va == null ? "" : va).trim();
      const eb = String(vb == null ? "" : vb).trim();
      if (!ea && !eb) return 0;
      if (!ea) return 1;
      if (!eb) return -1;
      c = ea.localeCompare(eb, undefined, { numeric: true, sensitivity: "base" });
    }
    return dir === "asc" ? c : -c;
  }

  let expandSlot = null;
  function pricePanel(sub) {
    return '<div class="panel pad" data-px-panel><div class="rowhead wrap"><div><div class="ptitle">Price</div><div class="psub">' +
      esc(sub || "Daily bars") + '</div></div><div class="pxtools" data-px-tools></div></div><div class="pxmas" data-px-mas></div><div class="chart-box pxchart"><div class="px-host" data-px-host><div class="px-legend" data-px-legend></div></div></div><p class="cap" data-px-cap></p></div>';
  }
  function expandKeyOf(row, opts) {
    if (opts.expandKey) return String(opts.expandKey(row) || "");
    return [row.ticker || "", row.kind || "", row.published || "", row.quarter || "", row.owner || "", row.earnings_date || "",
      String(row.headline || "").slice(0, 80), String(row.text || "").slice(0, 80)].join("|");
  }
  function fitOpenDrop(host) {
    const sc = host.querySelector(".buy-scroll");
    const drop = host.querySelector(".buydrop");
    if (sc && drop) drop.style.width = sc.clientWidth + "px";
  }
  function paintOpenChart(host, row, opts) {
    const panel = host.querySelector("[data-px-panel]");
    if (!panel || !row) return;
    fitOpenDrop(host);
    const lines = typeof opts.lines === "function" ? (opts.lines(row) || []) : (opts.lines || []);
    const sub = typeof opts.priceSub === "function" ? opts.priceSub(row) : opts.priceSub;
    requestAnimationFrame(() => {
      if (!panel.isConnected) return;
      fitOpenDrop(host);
      drawPriceChart(panel, { ticker: row.ticker, lines: lines, volAvg: opts.volAvg || 0 });
    });
  }
  function expandNotes(row, parked) {
    return parked.map((c) => {
      const v = row[c.key];
      if (isBlank(v)) return "";
      return '<p class="whytext"><span class="droplab">' + esc(c.label) + "</span> " + esc(v) + "</p>";
    }).join("");
  }
  function expandStory(row, opts, parked) {
    if (typeof opts.detail === "function") return "";
    const parkedKeys = {};
    parked.forEach((c) => { parkedKeys[c.key] = true; });
    return ["why", "reason"].map((key) => {
      if (parkedKeys[key] || isBlank(row[key])) return "";
      return '<p class="whytext">' + esc(row[key]) + "</p>";
    }).join("");
  }
  function expandHtml(row, opts, parked) {
    const custom = typeof opts.detail === "function" ? (opts.detail(row) || "") : "";
    const sub = typeof opts.priceSub === "function" ? opts.priceSub(row) : (opts.priceSub || "Daily bars from the saved prices.");
    const company = isBlank(row.company) ? "" : ' <span class="mut">' + esc(row.company) + "</span>";
    return '<div class="buydrop"><div class="buyid">' + tickerHtml(row.ticker) + company + "</div>" + blurbHtml(row.ticker) +
      viewerLinkHtml(row.ticker) + expandNotes(row, parked) + expandStory(row, opts, parked) + custom + pricePanel(sub) + "</div>";
  }
  if (typeof window !== "undefined" && !window.__rowDropFit) {
    window.__rowDropFit = true;
    window.addEventListener("resize", () => {
      document.querySelectorAll(".buydrop").forEach((drop) => {
        const sc = drop.closest(".buy-scroll");
        if (sc) drop.style.width = sc.clientWidth + "px";
      });
    });
  }

  function drawTable(host, opts) {
    const rows = opts.rows || [];
    const columns = opts.columns;
    const state = opts.state;
    const pageSize = opts.pageSize || 25;
    const expandable = !!opts.expandable;
    const hasDetail = expandable || typeof opts.detail === "function";
    host._tableOpts = opts;
    if (expandSlot && !expandSlot.host.isConnected) expandSlot = null;
    const openKey = expandable && expandSlot && expandSlot.host === host ? expandSlot.key : "";
    if (typeof opts.beforeDraw === "function") opts.beforeDraw();
    const oldPanel = host.querySelector("[data-px-panel]");
    if (oldPanel) dropTv(oldPanel);
    const sorted = rows.slice().sort((a, b) => {
      const col = columns.find((c) => c.key === state.sort) || columns[0];
      let c = compare(a, b, col, state.dir);
      if (c === 0 && state.sort2) {
        const col2 = columns.find((x) => x.key === state.sort2);
        if (col2) c = compare(a, b, col2, state.dir2 || "asc");
      }
      return c;
    });
    const pages = Math.max(1, Math.ceil(sorted.length / pageSize));
    if (state.page >= pages) state.page = pages - 1;
    if (state.page < 0) state.page = 0;
    const start = state.page * pageSize;
    const view = sorted.slice(start, start + pageSize);
    const parked = expandable ? columns.filter((c) => !c.hidden && (c.wrap || c.inDetail)) : [];
    const shown = columns.filter((c) => !c.hidden && parked.indexOf(c) < 0);
    if (expandable && openKey && !rows.some((r) => expandKeyOf(r, opts) === openKey)) expandSlot = null;
    const liveKey = expandable && expandSlot && expandSlot.host === host ? expandSlot.key : "";
    const head = (hasDetail ? '<th class="exp"></th>' : "") + shown.map((c) => {
      const mark = state.sort === c.key ? '<span class="sort">' + (state.dir === "asc" ? "▲" : "▼") + "</span>" : "";
      const cls = [align(c), c.hide === "md" ? "hide-md" : "", c.ellipsis ? "ellip" : ""].filter(Boolean).join(" ");
      return '<th class="' + cls + '" data-k="' + esc(c.key) + '">' + esc(c.label) + mark + "</th>";
    }).join("");
    const body = view.map((r, i) => {
      const tds = shown.map((c) => {
        const cls = [align(c), c.wrap ? "wrap" : "", c.kind === "score" ? "score" : "", c.hide === "md" ? "hide-md" : "", c.ellipsis ? "ellip" : ""].filter(Boolean).join(" ");
        const width = c.width ? " style=\"width:" + c.width + "\"" : "";
        const raw = r[c.key];
        const tip = c.ellipsis && raw != null && String(raw).trim() !== "" ? ' title="' + esc(String(raw)) + '"' : "";
        return "<td class=\"" + cls + "\"" + width + tip + ">" + cell(r, c) + "</td>";
      }).join("");
      const picked = opts.pick && opts.pick === (r.ticker || "") && opts.pick !== "";
      const mine = expandKeyOf(r, opts);
      const opened = expandable ? (!!liveKey && mine === liveKey) : (hasDetail && opts.open && opts.open === (r.ticker || "") && opts.open !== "");
      const on = (picked || opened) ? " selrow" : "";
      if (!hasDetail) return '<tr data-i="' + (start + i) + '" class="' + on + '">' + tds + "</tr>";
      const zebra = i % 2 === 0 ? "z0" : "z1";
      const extra = typeof opts.rowClass === "function" ? (" " + (opts.rowClass(r) || "")) : "";
      const name = r.ticker || "details";
      const exp = '<td class="exp"><button type="button" class="rowexp" aria-expanded="' + (opened ? "true" : "false") +
        '" aria-label="' + esc((opened ? "Hide " : "Show ") + name) + '"><span class="rowchev' + (opened ? " open" : "") + '"></span></button></td>';
      let html = '<tr data-i="' + (start + i) + '" class="datarow ' + zebra + on + extra + '">' + exp + tds + "</tr>";
      if (opened) {
        const inner = expandable ? expandHtml(r, opts, parked) : opts.detail(r);
        html += '<tr class="detailrow"><td colspan="' + (shown.length + 1) + '">' + inner + "</td></tr>";
      }
      return html;
    }).join("");
    const empty = rows.length ? "" : '<div class="empty">' + esc(opts.empty || "No rows match these filters.") + "</div>";
    const from = rows.length ? start + 1 : 0;
    const to = Math.min(start + pageSize, rows.length);
    const showFoot = opts.foot !== false && rows.length > pageSize;
    host.innerHTML =
      (opts.title ? '<div class="pad headrow" style="padding-bottom:0"><div class="ptitle">' + esc(opts.title) + "</div>" +
        (opts.sub ? '<div class="psub">' + esc(opts.sub) + "</div>" : "") + "</div>" : "") +
      '<div class="scroll' + (hasDetail ? " buy-scroll" : "") + '"><table' + (hasDetail ? (' class="buys' + (opts.fit ? " buyfit" : "") + '"') : "") + '><thead><tr>' + head + "</tr></thead><tbody>" + body + "</tbody></table></div>" +
      empty +
      (showFoot ? '<div class="foot"><span>' + from + "–" + to + " of " + rows.length + '</span><div class="pg">' +
      '<button type="button" data-pg="prev"' + (state.page <= 0 ? " disabled" : "") + ">‹</button>" +
      '<button type="button" data-pg="next"' + (state.page >= pages - 1 ? " disabled" : "") + ">›</button></div></div>" : "");
    host.querySelectorAll("th[data-k]").forEach((th) => {
      th.addEventListener("click", () => {
        const k = th.getAttribute("data-k");
        if (!k) return;
        if (state.sort === k) state.dir = state.dir === "asc" ? "desc" : "asc";
        else { state.sort = k; state.dir = "desc"; }
        drawTable(host, opts);
      });
    });
    host.querySelectorAll("[data-pg]").forEach((b) => {
      b.addEventListener("click", () => {
        state.page += b.getAttribute("data-pg") === "next" ? 1 : -1;
        drawTable(host, opts);
      });
    });
    if (expandable) {
      host.querySelectorAll("tbody tr.datarow").forEach((tr) => {
        tr.addEventListener("click", (ev) => {
          const link = ev.target.closest("a");
          if (link) ev.preventDefault();
          const row = sorted[Number(tr.getAttribute("data-i"))];
          if (!row) return;
          const key = expandKeyOf(row, opts);
          const next = liveKey === key ? "" : key;
          const prev = expandSlot && expandSlot.host;
          expandSlot = next ? { host: host, key: next } : null;
          if (prev && prev !== host && prev.isConnected && prev._tableOpts) drawTable(prev, prev._tableOpts);
          drawTable(host, opts);
        });
      });
    } else if (opts.onPick) {
      host.querySelectorAll(hasDetail ? "tbody tr.datarow" : "tbody tr").forEach((tr) => {
        tr.addEventListener("click", (ev) => {
          const link = ev.target.closest("a");
          if (link && !opts.activateRow) return;
          if (link && opts.activateRow) ev.preventDefault();
          const i = Number(tr.getAttribute("data-i"));
          opts.onPick(sorted[i]);
        });
      });
    }
    host._sorted = sorted;
    if (typeof opts.afterDraw === "function") opts.afterDraw(host);
    if (expandable && liveKey) {
      const row = view.find((r) => expandKeyOf(r, opts) === liveKey);
      if (row) paintOpenChart(host, row, opts);
    }
  }

  function uniq(rows, key) {
    const s = new Set();
    rows.forEach((r) => { if (!isBlank(r[key])) s.add(r[key]); });
    return Array.from(s).sort((a, b) => String(a).localeCompare(String(b), undefined, { numeric: true }));
  }
  function indexTokens(rows) {
    const s = new Set();
    rows.forEach((r) => {
      String(r.index_membership || "").split("/").forEach((p) => {
        const t = p.trim();
        if (t) s.add(t);
      });
    });
    return Array.from(s).sort();
  }
  function selectedMulti(root, id) {
    const box = root.querySelector('[data-filter="' + id + '"]');
    if (!box) return null;
    const all = Array.from(box.querySelectorAll("input[type=checkbox]"));
    const on = all.filter((x) => x.checked).map((x) => x.value);
    if (on.length === all.length) return null;
    return on;
  }
  function fieldVal(root, id) {
    const el = root.querySelector('[data-filter="' + id + '"]');
    if (!el) return "";
    return el.value;
  }

  function multiHtml(id, label, options, picked) {
    const set = picked ? new Set(picked) : null;
    const checks = options.map((o) => {
      const on = !set || set.has(o);
      return '<label><input type="checkbox" value="' + esc(o) + '"' + (on ? " checked" : "") + "> " + esc(o) + "</label>";
    }).join("");
    const shown = multiLabel(options, set);
    return '<div class="filter" data-id="' + esc(id) + '"><button type="button" class="dd">' + esc(label) +
      ' <span class="dmut">' + esc(shown) + '</span></button><div class="pop" data-filter="' + esc(id) + '">' + checks + "</div></div>";
  }
  function prettyOpt(s) {
    if (s === "BROKEN OUT today") return "broken out";
    if (s === "READY") return "Ready";
    const text = String(s || "");
    return text.charAt(0).toUpperCase() + text.slice(1).toLowerCase();
  }
  function multiLabel(options, set) {
    if (!set || set.size === options.length) return "All";
    if (!set.size) return "None";
    if (set.size === 2 && set.has("READY") && set.has("BROKEN OUT today")) return "Ready + broken out";
    if (set.size <= 2) return Array.from(set).map(prettyOpt).join(", ");
    return set.size + " selected";
  }
  function selectHtml(id, label, options, value, opt) {
    opt = opt || {};
    const items = options.map((o) => (o && typeof o === "object") ? o : { value: o, label: o });
    const opts = (opt.all === false ? [] : ['<option value="">All</option>']).concat(items.map((o) =>
      '<option value="' + esc(o.value) + '"' + (String(o.value) === String(value) ? " selected" : "") + ">" + esc(o.label) + "</option>"));
    return '<label class="ctl"><span class="lab">' + esc(label) + '</span><select data-filter="' + esc(id) + '">' + opts.join("") + "</select></label>";
  }
  function searchHtml(id, label, listId, values) {
    const opts = values.slice(0, 800).map((v) => "<option value=\"" + esc(v) + "\"></option>").join("");
    return '<label class="ctl"><span class="lab">' + esc(label) +
      '</span><input data-filter="' + esc(id) + '" list="' + esc(listId) + '" placeholder="All">' +
      '<datalist id="' + esc(listId) + '">' + opts + "</datalist></label>";
  }
  function rangeHtml(id, label, min, max, value, step) {
    return '<label class="ctl"><span class="lab">' + esc(label) +
      '</span><input type="number" data-filter="' + esc(id) + '" min="' + min + '" max="' + max +
      '" step="' + (step || "any") + '" value="' + value + '"></label>';
  }
  function pairHtml(idLo, idHi, label, lo, hi) {
    return '<label class="ctl wide"><span class="lab">' + esc(label) +
      '</span><input type="number" data-filter="' + esc(idLo) + '" value="' + lo + '">' +
      '<input type="number" data-filter="' + esc(idHi) + '" value="' + hi + '"></label>';
  }
  function dateHtml(id, label, value) {
    return '<label class="ctl"><span class="lab">' + esc(label) +
      '</span><input type="date" data-filter="' + esc(id) + '" value="' + esc(value || "") + '"></label>';
  }

  function wireFilters(root, onChange) {
    root.addEventListener("change", onChange);
    root.addEventListener("input", (e) => {
      if (e.target.matches("input[type=number], input[type=text], input.dd")) onChange();
    });
    root.querySelectorAll(".filter > button").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const parent = btn.parentElement;
        const open = parent.classList.contains("open");
        document.querySelectorAll(".filter.open").forEach((n) => n.classList.remove("open"));
        if (!open) parent.classList.add("open");
      });
    });
    root.querySelectorAll(".pop").forEach((pop) => {
      pop.addEventListener("click", (e) => e.stopPropagation());
    });
    root.querySelectorAll(".filter").forEach((box) => {
      box.addEventListener("change", () => {
        const all = Array.from(box.querySelectorAll("input[type=checkbox]"));
        const on = all.filter((x) => x.checked);
        const label = box.querySelector(".dmut");
        if (label) {
          const picked = new Set(on.map((x) => x.value));
          label.textContent = multiLabel(all.map((x) => x.value), on.length === all.length ? null : picked);
        }
      });
    });
  }
  document.addEventListener("click", () => {
    document.querySelectorAll(".filter.open").forEach((n) => n.classList.remove("open"));
  });

  function matchMulti(row, key, picked) {
    if (!picked) return true;
    return picked.indexOf(row[key]) >= 0;
  }
  function matchContains(row, key, picked) {
    if (!picked) return true;
    const v = row[key] || "";
    return picked.some((p) => v.indexOf(p) >= 0);
  }
  function matchText(row, key, q) {
    if (!q) return true;
    return String(row[key] || "").toLowerCase().indexOf(String(q).trim().toLowerCase()) >= 0;
  }
  function matchMin(row, key, min) {
    if (min == null || min === "" || Number.isNaN(Number(min))) return true;
    const n = num(row[key]);
    if (n == null) return false;
    return n >= Number(min);
  }

  const tvCharts = [];
  function tvStillOnScreen(chart) {
    try {
      if (typeof chart.chartElement !== "function") return false;
      const el = chart.chartElement();
      return !!(el && el.isConnected);
    } catch (e) {
      return false;
    }
  }
  function destroyCharts() {
    while (charts.length) {
      const c = charts.pop();
      try { c.destroy(); } catch (e) { /* already gone */ }
    }
    for (let i = tvCharts.length - 1; i >= 0; i--) {
      const c = tvCharts[i];
      if (tvStillOnScreen(c)) continue;
      tvCharts.splice(i, 1);
      try { c.remove(); } catch (e) { /* already gone */ }
    }
  }
  function basePlugins(legend) {
    return {
      legend: legend === false ? { display: false } : {
        display: true,
        labels: { color: MU, boxWidth: 12, font: { size: 12 } },
      },
      tooltip: { intersect: false },
    };
  }
  function axis() {
    return {
      ticks: { color: MU, maxRotation: 0, autoSkip: true },
      grid: { color: "#1E293B" },
    };
  }
  function makeChart(canvas, config) {
    if (!canvas || typeof Chart === "undefined") return null;
    config.options = config.options || {};
    // Draw the final values immediately. The default entrance animation
    // starts every point at 0, so a breadth line of 68% first appears near 15%.
    config.options.animation = false;
    const c = new Chart(canvas, config);
    charts.push(c);
    return c;
  }
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function monthLabel(s, spanYears) {
    const m = /^(\d{4})-(\d{2})/.exec(String(s || ""));
    if (!m) return s;
    if (spanYears >= 3) return m[1];
    return MONTHS[Number(m[2]) - 1];
  }
  function dateTicks(labels) {
    let span = 0;
    if (labels && labels.length > 1) {
      const a = Date.parse(labels[0]);
      const b = Date.parse(labels[labels.length - 1]);
      if (Number.isFinite(a) && Number.isFinite(b)) span = (b - a) / (365.25 * 86400000);
    }
    return {
      maxRotation: 0,
      autoSkip: false,
      color: MU,
      callback(v) {
        const a = monthLabel(this.getLabelForValue(v), span);
        const b = v > 0 ? monthLabel(this.getLabelForValue(v - 1), span) : null;
        return a !== b ? a : null;
      },
    };
  }
  function lineLegend() {
    return {
      display: true,
      position: "top",
      align: "end",
      labels: { usePointStyle: true, pointStyle: "line", boxWidth: 14, color: MU, font: { size: 11 } },
    };
  }
  function lineChart(canvas, labels, series, extra) {
    extra = extra || {};
    const x = Object.assign(axis(), { ticks: dateTicks(labels) }, extra.x || {});
    makeChart(canvas, {
      type: "line",
      data: {
        labels: labels,
        datasets: series.map((s) => ({
          label: s.label,
          data: s.data,
          borderColor: s.color,
          backgroundColor: s.color,
          spanGaps: !!s.spanGaps,
          borderWidth: 2,
          pointRadius: 0,
          tension: 0,
        })),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        layout: extra.layout || {},
        plugins: Object.assign({ legend: extra.legend === false ? { display: false } : lineLegend(), tooltip: { intersect: false } }, extra.plugins || {}),
        scales: {
          x: x,
          y: Object.assign(axis(), extra.y || {}),
        },
      },
    });
  }
  function barChart(canvas, labels, data, colors, extra) {
    extra = extra || {};
    const horizontal = !!extra.horizontal;
    const category = labels.length <= 20 ? { ticks: { autoSkip: false, color: MU, maxRotation: 0 } } : {};
    const nums = (data || []).map(Number).filter((n) => Number.isFinite(n));
    const lo = nums.length ? Math.min.apply(null, nums.concat([0])) : 0;
    const hi = nums.length ? Math.max.apply(null, nums.concat([0])) : 0;
    const valueExtra = Object.assign({}, extra.y || {});
    const xExtra = Object.assign({}, extra.x || {});
    if (horizontal && extra.labels) {
      const span = Math.max(hi - lo, 1e-9);
      const pad = span * 0.15;
      if (xExtra.suggestedMin == null) xExtra.suggestedMin = lo - pad;
      if (xExtra.suggestedMax == null) xExtra.suggestedMax = hi + pad;
    } else if (horizontal && lo < 0 && xExtra.suggestedMin == null) xExtra.suggestedMin = lo * 1.35;
    if (!horizontal && lo < 0 && valueExtra.suggestedMin == null) valueExtra.suggestedMin = lo * 1.35;
    const valueAxis = Object.assign(axis(), valueExtra);
    const catAxis = Object.assign(axis(), category, extra.cat || {});
    const plugins = Object.assign(basePlugins(false), extra.labels ? { barLabels: { dec: extra.dec == null ? 1 : extra.dec, suffix: extra.suffix || "", level: !!extra.level, money: !!extra.money } } : {});
    makeChart(canvas, {
      type: "bar",
      data: {
        labels: labels,
        datasets: [{
          label: extra.label || "",
          data: data,
          backgroundColor: colors,
          borderWidth: 0,
        }],
      },
      options: {
        indexAxis: horizontal ? "y" : "x",
        responsive: true,
        maintainAspectRatio: false,
        plugins: plugins,
        scales: horizontal
          ? { x: Object.assign(valueAxis, xExtra), y: catAxis }
          : { x: Object.assign(catAxis, extra.x || {}), y: valueAxis },
      },
    });
  }
  function comboChart(canvas, labels, bars, line) {
    const datasets = (bars || []).map((b) => ({
      type: "bar",
      label: b.label,
      data: b.data,
      backgroundColor: b.color,
      borderWidth: 0,
      order: 2,
      maxBarThickness: 8,
    }));
    if (line) {
      datasets.push({
        type: "line",
        label: line.label,
        data: line.data,
        borderColor: line.color,
        backgroundColor: line.color,
        borderWidth: 2,
        pointRadius: 0,
        tension: 0,
        order: 1,
      });
    }
    makeChart(canvas, {
      type: "bar",
      data: { labels: labels, datasets: datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: { legend: lineLegend(), tooltip: { intersect: false } },
        scales: {
          x: Object.assign(axis(), { ticks: dateTicks(labels) }),
          y: axis(),
        },
      },
    });
  }

  const hlines = {
    id: "hlines",
    afterDraw(chart) {
      const raw = chart.options.plugins && chart.options.plugins.hlines;
      const lines = Array.isArray(raw) ? raw : [];
      const area = chart.chartArea;
      const y = chart.scales.y;
      if (!area || !y) return;
      const ctx = chart.ctx;
      const labels = [];
      lines.forEach((ln) => {
        if (ln.zone && ln.zone.length === 2 && Number.isFinite(ln.zone[0]) && Number.isFinite(ln.zone[1])) {
          const y1 = y.getPixelForValue(ln.zone[0]);
          const y2 = y.getPixelForValue(ln.zone[1]);
          const top = Math.max(area.top, Math.min(y1, y2));
          const bot = Math.min(area.bottom, Math.max(y1, y2));
          ctx.save();
          ctx.fillStyle = ln.color || "rgba(124,156,255,.10)";
          ctx.fillRect(area.left, top, area.right - area.left, Math.max(1, bot - top));
          ctx.restore();
          labels.push({ yy: (top + bot) / 2, text: ln.label || "", color: ln.labelColor || "#7C9CFF" });
          return;
        }
        if (ln.value == null || !Number.isFinite(ln.value)) return;
        const yy = y.getPixelForValue(ln.value);
        if (yy < area.top || yy > area.bottom) return;
        ctx.save();
        ctx.strokeStyle = ln.color;
        ctx.setLineDash([5, 4]);
        ctx.beginPath();
        ctx.moveTo(area.left, yy);
        ctx.lineTo(area.right, yy);
        ctx.stroke();
        ctx.restore();
        labels.push({ yy: yy, text: ln.label || "", color: ln.color || MU });
      });
      labels.sort((a, b) => a.yy - b.yy);
      let last = -1e9;
      ctx.save();
      ctx.font = "11px Roboto, Arial, sans-serif";
      ctx.textAlign = "right";
      ctx.textBaseline = "bottom";
      labels.forEach((lb) => {
        let yy = lb.yy;
        if (yy - last < 13) yy = last + 13;
        if (yy > area.bottom) yy = area.bottom;
        last = yy;
        ctx.fillStyle = lb.color;
        ctx.fillText(lb.text, area.right - 6, yy);
      });
      ctx.restore();
    },
  };
  function levelText(v, opt) {
    const dec = opt.dec == null ? 1 : opt.dec;
    const abs = Math.abs(v);
    const body = abs >= 1000 ? String(compact(abs) || "").replace(/^-/, "") : abs.toFixed(dec);
    if (opt.money) return (v < 0 ? "−$" : "$") + String(body).replace(/\.0(?=[KMBT]|$)/, "");
    return body + (opt.suffix || "");
  }
  const barLabels = {
    id: "barLabels",
    afterDatasetsDraw(chart) {
      const opt = chart.options.plugins && chart.options.plugins.barLabels;
      if (!opt) return;
      const indexes = opt.lines ? chart.data.datasets.map((_, i) => i) : [0];
      const ctx = chart.ctx;
      const horizontal = chart.options.indexAxis === "y";
      const area = chart.chartArea;
      ctx.save();
      ctx.font = "11px Roboto, Arial, sans-serif";
      ctx.textBaseline = "middle";
      indexes.forEach((di) => {
        const meta = chart.getDatasetMeta(di);
        const ds = chart.data.datasets[di];
        if (!meta || !meta.data || meta.data.length >= 15 || !ds) return;
        meta.data.forEach((el, i) => {
          const v = Number(ds.data[i]);
          if (!Number.isFinite(v) || !el) return;
          const dec = opt.dec == null ? 1 : opt.dec;
          let text;
          if (opt.level) {
            text = levelText(v, opt);
            ctx.fillStyle = "#C3CBDB";
          } else {
            const body = Math.abs(v) >= 1000 ? compact(v) : v.toFixed(dec);
            text = (v > 0 ? "+" : v < 0 ? "−" : "") + String(body).replace(/^-/, "") + (opt.suffix || "");
            ctx.fillStyle = v > 0 ? UP : v < 0 ? DN : MU;
          }
          if (horizontal && area) {
            // Light grey, just outside the bar tip, so a red bar does not hide red text.
            ctx.fillStyle = "#C3CBDB";
            const textW = ctx.measureText(text).width;
            if (v < 0) {
              ctx.textAlign = "right";
              const x = Math.max(area.left + textW, el.x - 4);
              ctx.fillText(text, x, el.y);
            } else {
              ctx.textAlign = "left";
              const x = Math.min(area.right - textW, el.x + 4);
              ctx.fillText(text, x, el.y);
            }
          } else {
            ctx.textAlign = "center";
            ctx.textBaseline = "bottom";
            ctx.fillText(text, el.x, el.y - 2);
          }
        });
      });
      ctx.restore();
    },
  };
  if (typeof Chart !== "undefined") {
    Chart.defaults.animation = false;
    if (Chart.defaults.transitions && Chart.defaults.transitions.active && Chart.defaults.transitions.active.animation) {
      Chart.defaults.transitions.active.animation.duration = 0;
    }
    Chart.defaults.font.family = "Roboto, Arial, sans-serif";
    Chart.defaults.font.size = 11;
    Chart.defaults.color = MU;
    Chart.register(hlines, barLabels);
  }

  function lastNDays(rows, dateKey, days) {
    const dates = rows.map((r) => r[dateKey]).filter(Boolean).sort();
    if (!dates.length) return rows;
    const end = dates[dates.length - 1];
    const cut = new Date(end + "T00:00:00Z");
    cut.setUTCDate(cut.getUTCDate() - days);
    const iso = cut.toISOString().slice(0, 10);
    return rows.filter((r) => r[dateKey] >= iso);
  }
  function seriesNum(rows, key) {
    return rows.map((r) => num(r[key]));
  }

  function alertDataRows(rows) {
    return realRows(rows).filter((r) => r.kind && r.kind !== "info");
  }
  function quietMessage(rows) {
    const list = rows || [];
    const info = list.find((r) => String(r.kind || "") === "info");
    const fromInfo = info ? String(info.text || info.note || "").trim() : "";
    if (fromInfo) return fromInfo;
    const noted = list.find((r) => String(r.note || "").trim());
    if (noted) return String(noted.note).trim();
    return "No changes since the last run.";
  }
  function showQuiet(host, text, title) {
    if (!host) return;
    host.innerHTML = (title ? '<div class="pad" style="padding-bottom:0"><div class="ptitle">' + esc(title) + "</div></div>" : "") +
      '<div class="empty">' + esc(text) + "</div>";
  }

  const MA_DEFS = [
    { id: "sma21", label: "SMA 21", kind: "sma", n: 21, color: "#7C9CFF" },
    { id: "sma50", label: "SMA 50", kind: "sma", n: 50, color: "#C3CBDB" },
    { id: "sma150", label: "SMA 150", kind: "sma", n: 150, color: "#F59E0B" },
    { id: "sma200", label: "SMA 200", kind: "sma", n: 200, color: "#E879F9" },
    { id: "ema21", label: "EMA 21", kind: "ema", n: 21, color: "#38BDF8" },
    { id: "ema50", label: "EMA 50", kind: "ema", n: 50, color: "#F472B6" },
    { id: "ema150", label: "EMA 150", kind: "ema", n: 150, color: "#34D399" },
    { id: "ema200", label: "EMA 200", kind: "ema", n: 200, color: "#FB923C" },
  ];
  const MA_DEFAULT = { sma21: false, sma50: true, sma150: false, sma200: true, ema21: true, ema50: false, ema150: false, ema200: false };

  let tvPromise = null;
  function tvReady() {
    return typeof LightweightCharts !== "undefined" && !!LightweightCharts.createChart;
  }
  function ensureTv() {
    if (tvReady()) return Promise.resolve();
    if (!tvPromise) {
      tvPromise = new Promise((resolve, reject) => {
        const s = document.createElement("script");
        s.src = "vendor/lightweight-charts/lightweight-charts.standalone.production.js";
        s.onload = () => { if (tvReady()) resolve(); else reject(new Error("price chart did not load")); };
        s.onerror = () => reject(new Error("price chart failed to load"));
        document.head.appendChild(s);
      });
    }
    return tvPromise;
  }
  function maState() {
    const out = Object.assign({}, MA_DEFAULT);
    try {
      const raw = JSON.parse(localStorage.getItem("desk-ma") || "");
      if (raw && typeof raw === "object") {
        MA_DEFS.forEach((d) => { if (typeof raw[d.id] === "boolean") out[d.id] = raw[d.id]; });
      }
    } catch (e) { /* storage can be blocked or hold an older value */ }
    return out;
  }
  function storeMa(state) {
    try { localStorage.setItem("desk-ma", JSON.stringify(state)); } catch (e) { /* ignore */ }
  }
  function storedChoice(key, fallback, allowed) {
    try {
      const v = localStorage.getItem(key);
      if (allowed.indexOf(v) >= 0) return v;
    } catch (e) { /* storage can be blocked */ }
    return fallback;
  }
  function storeChoice(key, value) {
    try { localStorage.setItem(key, value); } catch (e) { /* ignore */ }
  }
  function priceStyle() { return storedChoice("desk-price-style", "candles", ["line", "candles"]); }
  function priceRange() { return storedChoice("desk-price-range", "6M", ["3M", "6M", "1Y", "All"]); }
  function dropTv(panel) {
    const c = panel._tv;
    if (!c) return;
    const i = tvCharts.indexOf(c);
    if (i >= 0) tvCharts.splice(i, 1);
    try { c.remove(); } catch (e) { /* already gone */ }
    panel._tv = null;
  }
  function barsFromRows(rows) {
    const sorted = (rows || []).filter((r) => num(r.close) != null).slice()
      .sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
    let prev = null;
    return sorted.map((r) => {
      const c = num(r.close);
      let o = num(r.open);
      let prior = false;
      if (o == null) {
        if (prev != null) { o = prev; prior = true; }
        else o = c;
      }
      const h0 = num(r.high);
      const l0 = num(r.low);
      const bar = {
        date: r.date, o: o, h: h0 == null ? Math.max(o, c) : h0, l: l0 == null ? Math.min(o, c) : l0, c: c,
        v: num(r.volume), prior: prior,
      };
      prev = c;
      return bar;
    });
  }
  function smaValues(closes, n) {
    const out = new Array(closes.length).fill(null);
    let sum = 0;
    for (let i = 0; i < closes.length; i++) {
      sum += closes[i];
      if (i >= n) sum -= closes[i - n];
      if (i >= n - 1) out[i] = sum / n;
    }
    return out;
  }
  function emaValues(closes, n) {
    const out = new Array(closes.length).fill(null);
    const k = 2 / (n + 1);
    let prev = null;
    let seed = 0;
    for (let i = 0; i < closes.length; i++) {
      if (i < n) {
        seed += closes[i];
        if (i === n - 1) {
          prev = seed / n;
          out[i] = prev;
        }
        continue;
      }
      prev = closes[i] * k + prev * (1 - k);
      out[i] = prev;
    }
    return out;
  }
  function maSeries(closes, def) {
    return def.kind === "ema" ? emaValues(closes, def.n) : smaValues(closes, def.n);
  }
  function timeKey(t) {
    if (!t) return "";
    if (typeof t === "string") return t.slice(0, 10);
    if (typeof t === "object" && t.year) {
      return t.year + "-" + String(t.month).padStart(2, "0") + "-" + String(t.day).padStart(2, "0");
    }
    return "";
  }
  function levelSpecs(lines) {
    const out = [];
    (lines || []).forEach((line) => {
      if (line.zone && line.zone.length === 2) {
        const lo = Math.min(line.zone[0], line.zone[1]);
        const hi = Math.max(line.zone[0], line.zone[1]);
        const color = line.labelColor || AM;
        out.push({ price: lo, color: color, title: "Entry low" });
        out.push({ price: hi, color: color, title: "Entry high" });
      } else if (line.value != null && isFinite(line.value)) {
        const title = String(line.label || "Level").replace(/\s+[\d.,–+-]+$/, "").trim() || "Level";
        out.push({ price: line.value, color: line.color || AM, title: title });
      }
    });
    return out;
  }
  function rangeWindow(bars, range) {
    const end = bars[bars.length - 1].date;
    if (range === "All") return { from: bars[0].date, to: end, fit: true };
    const months = range === "3M" ? 3 : range === "1Y" ? 12 : 6;
    const cut = new Date(end + "T00:00:00Z");
    cut.setUTCMonth(cut.getUTCMonth() - months);
    const iso = cut.toISOString().slice(0, 10);
    let from = bars[0].date;
    for (let i = 0; i < bars.length; i++) {
      if (bars[i].date >= iso) { from = bars[i].date; break; }
    }
    return { from: from, to: end, fit: from === end };
  }
  function applyRange(chart, bars, range) {
    if (!bars.length) return;
    const win = rangeWindow(bars, range);
    try {
      chart.panes().forEach((pane) => {
        try { pane.priceScale("right").applyOptions({ autoScale: true }); } catch (e) { /* pane has no scale yet */ }
      });
      if (win.fit) chart.timeScale().fitContent();
      else chart.timeScale().setVisibleRange({ from: win.from, to: win.to });
    } catch (e) {
      try { chart.timeScale().fitContent(); } catch (err) { /* chart is gone */ }
    }
  }
  function legendHtml(bar, prevClose, averages) {
    if (!bar) return "";
    const up = prevClose == null ? bar.c >= bar.o : bar.c >= prevClose;
    const cls = up ? "up" : "dn";
    const px = (n) => esc(fmt(n, 2) || "–");
    let html = "<div><b class=\"" + cls + "\">O</b> " + px(bar.o) +
      "  <b class=\"" + cls + "\">H</b> " + px(bar.h) +
      "  <b class=\"" + cls + "\">L</b> " + px(bar.l) +
      "  <b class=\"" + cls + "\">C</b> " + px(bar.c) +
      "  <b>V</b> " + esc(compact(bar.v) || "–") + "</div>";
    if (averages.length) {
      html += "<div>" + averages.map((a) =>
        '<span style="color:' + a.color + '">' + esc(a.label) + " " + px(a.value) + "</span>"
      ).join("  ") + "</div>";
    }
    return html;
  }
  function priorAvgVolume(bars, n) {
    const out = new Array(bars.length).fill(null);
    let sum = 0;
    let count = 0;
    for (let i = 0; i < bars.length; i++) {
      if (i >= n) {
        let ok = true;
        sum = 0;
        count = 0;
        for (let j = i - n; j < i; j++) {
          const v = bars[j].v;
          if (v == null) { ok = false; break; }
          sum += v;
          count++;
        }
        if (ok && count === n) out[i] = sum / n;
      }
    }
    return out;
  }
  function paintPrice(panel, bars, lines, token, volAvg) {
    if (panel._token !== token || !panel.isConnected) return;
    const cap = panel.querySelector("[data-px-cap]");
    const host = panel.querySelector("[data-px-host]");
    const legend = panel.querySelector("[data-px-legend]");
    dropTv(panel);
    if (!host || !bars.length) {
      if (legend) legend.innerHTML = "";
      if (cap) cap.textContent = "No saved daily bars for this name.";
      return;
    }
    const draw = () => {
      if (panel._token !== token || !panel.isConnected || !tvReady()) return;
      const LC = LightweightCharts;
      const style = priceStyle();
      const mas = maState();
      const closes = bars.map((b) => b.c);
      const averages = {};
      MA_DEFS.forEach((def) => { averages[def.id] = maSeries(closes, def); });
      const byDate = new Map();
      bars.forEach((b, i) => byDate.set(b.date, i));
      const chart = themedChart(LC.createChart(host, themed({
        autoSize: true,
        layout: {
          background: { type: "solid", color: "#121826" },
          textColor: MU,
          fontFamily: "Roboto, Arial, sans-serif",
          fontSize: 12,
          attributionLogo: true,
          panes: { separatorColor: "#1E293B", enableResize: true },
        },
        grid: { vertLines: { color: "#1E293B" }, horzLines: { color: "#1E293B" } },
        crosshair: { mode: LC.CrosshairMode.Magnet },
        rightPriceScale: { borderColor: "#1E293B" },
        timeScale: { borderColor: "#1E293B", rightOffset: 4 },
        handleScroll: { mouseWheel: false, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
        handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: true, axisDoubleClickReset: true },
        kineticScroll: { touch: true, mouse: false },
      })));
      panel._tv = chart;
      tvCharts.push(chart);
      const priceOpts = { priceLineVisible: false, lastValueVisible: true };
      let priceSeries;
      if (style === "line") {
        priceSeries = chart.addSeries(LC.LineSeries, Object.assign({ color: TX, lineWidth: 2 }, priceOpts));
        priceSeries.setData(bars.map((b) => ({ time: b.date, value: b.c })));
      } else {
        priceSeries = chart.addSeries(LC.CandlestickSeries, Object.assign({
          upColor: UP, downColor: DN, borderUpColor: UP, borderDownColor: DN, wickUpColor: UP, wickDownColor: DN,
        }, priceOpts));
        priceSeries.setData(bars.map((b) => ({ time: b.date, open: b.o, high: b.h, low: b.l, close: b.c })));
      }
      const vol = chart.addSeries(LC.HistogramSeries, {
        priceFormat: { type: "volume" }, priceLineVisible: false, lastValueVisible: false,
      }, 1);
      vol.setData(bars.filter((b) => b.v != null).map((b) => ({
        time: b.date, value: b.v, color: b.c >= b.o ? (LIGHT ? "rgba(21,128,61,.6)" : "rgba(34,197,94,.65)") : (LIGHT ? "rgba(220,38,38,.6)" : "rgba(239,68,68,.65)"),
      })));
      if (volAvg) {
        const avgLine = chart.addSeries(LC.LineSeries, {
          color: AM, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
          priceFormat: { type: "volume" },
        }, 1);
        const avgData = [];
        priorAvgVolume(bars, volAvg).forEach((value, i) => {
          if (value != null) avgData.push({ time: bars[i].date, value: value });
        });
        avgLine.setData(avgData);
      }
      const panes = chart.panes();
      if (panes[0]) panes[0].setStretchFactor(3);
      if (panes[1]) panes[1].setStretchFactor(1);
      levelSpecs(lines).forEach((level) => {
        priceSeries.createPriceLine({
          price: level.price, color: level.color, lineWidth: 1, lineStyle: LC.LineStyle.Dashed,
          axisLabelVisible: true, title: level.title,
        });
      });
      MA_DEFS.forEach((def) => {
        if (!mas[def.id]) return;
        const series = chart.addSeries(LC.LineSeries, {
          color: def.color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
        });
        const data = [];
        averages[def.id].forEach((value, i) => {
          if (value != null) data.push({ time: bars[i].date, value: value });
        });
        series.setData(data);
      });
      const showLegend = (key) => {
        if (!legend) return;
        let i = key ? byDate.get(key) : bars.length - 1;
        if (i == null) i = bars.length - 1;
        const bar = bars[i];
        const prev = i > 0 ? bars[i - 1].c : null;
        const shown = MA_DEFS.filter((def) => mas[def.id] && averages[def.id][i] != null).map((def) => ({
          label: def.label, color: def.color, value: averages[def.id][i],
        }));
        legend.innerHTML = legendHtml(bar, prev, shown);
      };
      showLegend("");
      chart.subscribeCrosshairMove((param) => {
        if (panel._token !== token) return;
        showLegend(param && param.time ? timeKey(param.time) : "");
      });
      if (host._fit) host.removeEventListener("dblclick", host._fit);
      host._fit = (event) => {
        event.preventDefault();
        applyRange(chart, bars, priceRange());
      };
      host.addEventListener("dblclick", host._fit);
      requestAnimationFrame(() => {
        if (panel._token !== token || !panel.isConnected) return;
        applyRange(chart, bars, priceRange());
      });
      if (!cap) return;
      let text = style === "line"
        ? "Close, with volume underneath."
        : "Green is an up day and red is a down day. Volume sits underneath.";
      if (bars.some((b) => b.prior)) {
        text += " Opens are not in the saved prices yet, so each candle starts at the prior close.";
      }
      if (volAvg) text += " The amber line on the volume bars is the " + volAvg + "-day average volume.";
      text += " Averages are calculated in the browser from the saved daily bars.";
      cap.innerHTML = esc(text) + ' Charting by <a href="https://www.tradingview.com/">TradingView</a> Lightweight Charts™.';
    };
    ensureTv().then(draw).catch(() => {
      if (panel._token !== token) return;
      if (cap) cap.textContent = "The price chart could not load.";
    });
  }
  function drawPriceChart(panel, opts) {
    if (!panel) return;
    opts = opts || {};
    const tools = panel.querySelector("[data-px-tools]");
    const chips = panel.querySelector("[data-px-mas]");
    const cap = panel.querySelector("[data-px-cap]");
    if (!tools) return;
    const style = priceStyle();
    const range = priceRange();
    const mas = maState();
    const btn = (group, value, label, on) =>
      '<button type="button" data-g="' + group + '" data-v="' + esc(value) + '"' + (on ? ' class="on"' : "") + ">" + esc(label) + "</button>";
    tools.innerHTML =
      '<div class="seg">' + btn("style", "line", "Line", style === "line") + btn("style", "candles", "Candles", style === "candles") + "</div>" +
      '<div class="seg">' + ["3M", "6M", "1Y", "All"].map((r) => btn("range", r, r, range === r)).join("") + "</div>" +
      '<div class="seg"><button type="button" data-g="reset" data-v="reset">Reset</button></div>';
    if (chips) {
      chips.innerHTML = MA_DEFS.map((def) =>
        '<button type="button" class="machip' + (mas[def.id] ? " on" : "") + '" data-ma="' + def.id + '" aria-pressed="' + (mas[def.id] ? "true" : "false") + '">' +
        '<i style="background:' + def.color + '"></i>' + esc(def.label) + "</button>"
      ).join("");
    }
    const rerun = () => drawPriceChart(panel, opts);
    tools.querySelectorAll("button").forEach((button) => {
      button.addEventListener("click", () => {
        const group = button.getAttribute("data-g");
        const value = button.getAttribute("data-v");
        if (group === "style") storeChoice("desk-price-style", value);
        if (group === "range") storeChoice("desk-price-range", value);
        if (group === "reset" && panel._tv && panel._bars) {
          applyRange(panel._tv, panel._bars, priceRange());
          return;
        }
        rerun();
      });
    });
    if (chips) {
      chips.querySelectorAll("button").forEach((button) => {
        button.addEventListener("click", () => {
          const next = maState();
          const id = button.getAttribute("data-ma");
          next[id] = !next[id];
          storeMa(next);
          rerun();
        });
      });
    }
    const ticker = String(opts.ticker || "").trim().toUpperCase();
    const token = (panel._token || 0) + 1;
    panel._token = token;
    const show = (rows) => {
      if (panel._token !== token || !panel.isConnected) return;
      const bars = barsFromRows(rows);
      panel._bars = bars;
      paintPrice(panel, bars, opts.lines || [], token, opts.volAvg || 0);
    };
    if (panel._ticker === ticker && panel._rows) {
      show(panel._rows);
      return;
    }
    if (cap) cap.textContent = "";
    if (!ticker) {
      dropTv(panel);
      if (cap) cap.textContent = "No saved daily bars for this name.";
      return;
    }
    loadCsv("ohlc/" + ticker + ".csv").then((rows) => {
      if (panel._token !== token) return;
      panel._ticker = ticker;
      panel._rows = rows || [];
      show(panel._rows);
    }).catch(() => {
      if (panel._token !== token) return;
      dropTv(panel);
      if (cap) cap.textContent = "No saved daily bars for " + ticker + ".";
    });
  }

  // ---------- Technical | Fundamental (features.split_tech_fund) ----------
  // Defaults match the scanner_groups block in config.json; a settings.csv row wins. Keys are page ids.
  const SCANNER_GROUPS = {
    vcp: "technical", box: "technical", flag: "technical", qullamaggie: "technical", marios: "technical", ep: "technical",
    gapup: "technical", week52: "technical", breakouts: "technical", volume: "technical", pullbacks: "technical",
    breakdowns: "technical", trends: "technical", wheel: "technical",
    canslim: "fundamental", leaders: "fundamental", growth: "fundamental", quality: "fundamental", dividend: "fundamental",
    scorecard: "fundamental", top: "fundamental",
  };
  // Off unless settings.csv says true, so a settings file from before the split keeps the old menu and viewer.
  function splitOn() {
    const v = settingVal("feature.split_tech_fund");
    return v != null && String(v).trim().toLowerCase() === "true";
  }
  function groupOf(id) {
    const v = settingVal("scanner_groups." + id);
    if (v != null && String(v).trim() !== "") {
      const g = String(v).trim().toLowerCase();
      return g === "technical" || g === "fundamental" ? g : "";
    }
    return SCANNER_GROUPS[id] || "";
  }
  // Page ids in the order of the scanner_groups rows in settings.csv, then any default not listed there.
  function groupOrder() {
    const out = [];
    SETTINGS.forEach((r) => {
      const m = /^scanner_groups\.(.+)$/.exec(String(r.setting || ""));
      if (m && out.indexOf(m[1]) < 0) out.push(m[1]);
    });
    Object.keys(SCANNER_GROUPS).forEach((id) => { if (out.indexOf(id) < 0) out.push(id); });
    return out;
  }
  // The menu. Split off: NAV as it was. Split on: every screener page moves under a Technical or a Fundamental
  // heading where Scanners was, in scanner_groups order; the rest stay put, and the leftover Technicals group
  // (market-wide pages) is called Market so it is not mixed up with Technical.
  function navGroups() {
    if (!splitOn()) return NAV;
    const byId = {};
    NAV.forEach((g) => g[1].forEach((it) => { byId[it[2]] = it; }));
    const pick = (grp) => groupOrder().filter((id) => byId[id] && groupOf(id) === grp).map((id) => byId[id]);
    const tech = pick("technical");
    const fund = pick("fundamental");
    const out = [];
    NAV.forEach(([name, items]) => {
      const rest = items.filter((it) => !groupOf(it[2]));
      if (name === "Scanners") {
        out.push(["Technical", tech], ["Fundamental", fund]);
        if (rest.length) out.push(["Scanners", rest]);
        return;
      }
      if (rest.length) out.push([name === "Technicals" ? "Market" : name, rest]);
    });
    return out;
  }
  let NAV_NOW = NAV;
  function navOn(items) {
    return items.filter((it) => !FEATURE[it[2]] || featureOn(FEATURE[it[2]]));
  }
  const SEARCH_ICON = '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><circle cx="11" cy="11" r="6.5" fill="none" stroke="currentColor" stroke-width="2"/><path d="M16 16.5L20.5 21" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';
  let deskNames = null;
  function deskList() {
    if (deskNames) return Promise.resolve(deskNames);
    return loadCsv("scores.csv").then((rows) => {
      deskNames = realRows(rows).filter((r) => r.ticker).map((r) => ({
        ticker: String(r.ticker).trim().toUpperCase(),
        company: String(r.company || ""),
        score: r.score,
        verdict: String(r.verdict || ""),
      }));
      return deskNames;
    });
  }
  function searchRank(q, row) {
    const query = q.toLowerCase();
    const ticker = row.ticker.toLowerCase();
    const company = row.company.toLowerCase();
    if (ticker.startsWith(query)) return 0;
    if (company.startsWith(query)) return 1;
    if (company.split(/[^a-z0-9]+/).some((w) => w && w.startsWith(query))) return 2;
    if (ticker.indexOf(query) >= 0) return 3;
    if (company.indexOf(query) >= 0) return 4;
    return -1;
  }
  function searchHits(q, rows) {
    const ranked = [];
    rows.forEach((row) => {
      const rank = searchRank(q, row);
      if (rank >= 0) ranked.push([rank, row]);
    });
    ranked.sort((a, b) => a[0] - b[0] || (a[1].ticker < b[1].ticker ? -1 : a[1].ticker > b[1].ticker ? 1 : 0));
    return ranked.slice(0, 8).map((pair) => pair[1]);
  }
  function wireSearch(setNav) {
    const input = document.getElementById("q");
    const pop = document.getElementById("qlist");
    const btn = document.getElementById("qbtn");
    const narrowQ = window.matchMedia("(max-width: 1179px)");
    let active = 0;
    let hits = [];
    function place() {
      const search = document.getElementById("search");
      if (narrowQ.matches) document.querySelector(".hdr").insertBefore(search, document.querySelector(".titles"));
      else {
        document.getElementById("qslot").appendChild(search);
        document.body.classList.remove("search-open");
        btn.setAttribute("aria-expanded", "false");
      }
    }
    function position() {
      if (!pop || pop.hidden) return;
      const rect = input.getBoundingClientRect();
      const width = Math.min(360, Math.max(rect.width, 260), window.innerWidth - 16);
      let left = rect.left;
      if (left + width > window.innerWidth - 8) left = Math.max(8, window.innerWidth - width - 8);
      pop.style.left = left + "px";
      pop.style.top = Math.round(rect.bottom + 4) + "px";
      pop.style.width = Math.round(width) + "px";
    }
    function paint(message, rows) {
      hits = rows || [];
      if (!input.value.trim() && !message) {
        pop.hidden = true;
        pop.innerHTML = "";
        input.setAttribute("aria-expanded", "false");
        input.removeAttribute("aria-activedescendant");
        return;
      }
      if (message) {
        pop.innerHTML = '<div class="qmiss">' + esc(message) + "</div>";
        pop.hidden = false;
        input.setAttribute("aria-expanded", "true");
        input.removeAttribute("aria-activedescendant");
        position();
        return;
      }
      if (!hits.length) {
        pop.hidden = true;
        pop.innerHTML = "";
        input.setAttribute("aria-expanded", "false");
        return;
      }
      if (active >= hits.length) active = 0;
      pop.innerHTML = hits.map((row, i) => {
        const color = row.verdict === "BUY" ? UP : row.verdict === "HOLD" ? AM : row.verdict === "AVOID" ? DN : TX;
        const score = num(row.score);
        const scoreText = score == null ? "–" : (Number.isInteger(score) ? String(score) : fmt(score, 1));
        return '<button type="button" class="qrow' + (i === active ? " on" : "") + '" role="option" id="qopt' + i + '" data-t="' + esc(row.ticker) + '" aria-selected="' + (i === active ? "true" : "false") + '">' +
          '<span class="tk">' + esc(row.ticker) + '</span><span class="qname">' + esc(row.company || "") + "</span>" +
          '<span class="qscore">' + esc(scoreText) + '</span><span class="pill" style="color:' + color + '">' + esc(row.verdict || "–") + "</span></button>";
      }).join("");
      pop.hidden = false;
      input.setAttribute("aria-expanded", "true");
      input.setAttribute("aria-activedescendant", "qopt" + active);
      const current = document.getElementById("qopt" + active);
      if (current) {
        const top = current.offsetTop;
        if (top < pop.scrollTop) pop.scrollTop = top;
        else if (top + current.offsetHeight > pop.scrollTop + pop.clientHeight) pop.scrollTop = top + current.offsetHeight - pop.clientHeight;
      }
      position();
    }
    function renderList() {
      const q = input.value.trim();
      if (!q) { paint("", []); return; }
      deskList().then((rows) => {
        if (input.value.trim() !== q) return;
        const found = searchHits(q, rows);
        if (!found.length) paint("Not in the desk's " + rows.length + " stocks", []);
        else paint("", found);
      }).catch(() => {
        if (input.value.trim() !== q) return;
        paint("The desk list could not load.", []);
      });
    }
    function openSearch() {
      if (narrowQ.matches) {
        setNav(false);
        document.body.classList.add("search-open");
        btn.setAttribute("aria-expanded", "true");
      }
      input.focus();
      if (input.value.trim()) renderList();
    }
    function closeSearch() {
      document.body.classList.remove("search-open");
      btn.setAttribute("aria-expanded", "false");
      paint("", []);
    }
    place();
    if (narrowQ.addEventListener) narrowQ.addEventListener("change", () => { place(); position(); });
    btn.addEventListener("click", () => {
      if (document.body.classList.contains("search-open")) closeSearch();
      else openSearch();
    });
    input.addEventListener("input", () => { active = 0; renderList(); });
    input.addEventListener("focus", () => { if (input.value.trim()) renderList(); });
    input.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown" && hits.length) {
        e.preventDefault();
        active = (active + 1) % hits.length;
        paint("", hits);
      } else if (e.key === "ArrowUp" && hits.length) {
        e.preventDefault();
        active = (active - 1 + hits.length) % hits.length;
        paint("", hits);
      } else if (e.key === "Enter") {
        e.preventDefault();
        if (hits[active]) location.href = "scorecard.html?t=" + encodeURIComponent(hits[active].ticker);
      } else if (e.key === "Escape") {
        e.preventDefault();
        input.value = "";
        closeSearch();
        input.blur();
      }
    });
    pop.addEventListener("mousedown", (e) => { e.preventDefault(); });
    pop.addEventListener("click", (e) => {
      const row = e.target.closest(".qrow");
      if (row) location.href = "scorecard.html?t=" + encodeURIComponent(row.getAttribute("data-t"));
    });
    document.addEventListener("keydown", (e) => {
      const tag = (e.target && e.target.tagName || "").toLowerCase();
      const typing = tag === "input" || tag === "textarea" || (e.target && e.target.isContentEditable);
      const slash = e.key === "/" && !typing && !e.metaKey && !e.ctrlKey && !e.altKey;
      const chord = (e.metaKey || e.ctrlKey) && !e.altKey && (e.key === "k" || e.key === "K");
      if (slash || chord) {
        e.preventDefault();
        openSearch();
      }
    });
    document.addEventListener("click", (e) => {
      if (e.target.closest("#search") || e.target.closest("#qbtn") || e.target.closest("#qlist")) return;
      if (narrowQ.matches) closeSearch();
      else paint("", []);
    });
    window.addEventListener("resize", position);
    deskList().catch(() => {});
  }
  function themeChoice() {
    if (!featureOn("feature.light_mode")) return "dark";
    const saved = storedTheme();
    const def = String(settingVal("light_mode.default_theme") || "dark").toLowerCase();
    let choice = saved || (def === "light" ? "light" : def === "device" || def === "auto" ? "auto" : "dark");
    if (choice === "auto" && !themeDeviceOn()) choice = "dark";
    return choice;
  }
  function themeDeviceOn() {
    const v = settingVal("light_mode.match_device_option");
    return v == null || String(v).toLowerCase() !== "false";
  }
  function themeHtml() {
    if (!featureOn("feature.light_mode")) return "";
    const choice = themeChoice();
    const btn = (v, label) => '<button type="button" data-theme-pick="' + v + '" aria-pressed="' + (choice === v ? "true" : "false") + '"' +
      (choice === v ? ' class="on"' : "") + ">" + esc(label) + "</button>";
    return '<div class="themebox"><span class="themelab">Theme</span><div class="themeseg" role="group" aria-label="Theme">' +
      btn("dark", "Dark") + btn("light", "Light") + (themeDeviceOn() ? btn("auto", "Match device") : "") + "</div></div>";
  }
  function wireTheme() {
    const box = document.querySelector(".themeseg");
    if (box) box.addEventListener("click", (e) => {
      const b = e.target.closest("[data-theme-pick]");
      if (!b) return;
      const v = b.getAttribute("data-theme-pick");
      try { localStorage.setItem(THEME_KEY, v); } catch (err) { /* ignore */ }
      // Charts are already drawn in the old colors, so redraw the page. The data files come back from the browser cache.
      if (resolveTheme(v) !== (LIGHT ? "light" : "dark")) location.reload();
      else {
        box.querySelectorAll("[data-theme-pick]").forEach((x) => {
          const onNow = x === b;
          x.classList.toggle("on", onNow);
          x.setAttribute("aria-pressed", onNow ? "true" : "false");
        });
      }
    });
    if (deviceLight && deviceLight.addEventListener) {
      deviceLight.addEventListener("change", () => {
        if (themeChoice() === "auto" && resolveTheme("auto") !== (LIGHT ? "light" : "dark")) location.reload();
      });
    }
  }
  function renderShell(page) {
    NAV_NOW = navGroups();
    const groups = NAV_NOW.map(([name, items]) => {
      const shown = navOn(items);
      if (!shown.length) return "";
      const open = shown.some((it) => it[2] === page.id);
      const links = open ? shown.map((it) => {
        return '<a class="item' + (it[2] === page.id ? " sel" : "") + '" href="' + it[1] + '">' + esc(it[0]) + "</a>";
      }).join("") : "";
      return '<div class="group" data-open="' + (open ? "1" : "0") + '">' +
        '<button type="button" class="grp" aria-expanded="' + (open ? "true" : "false") + '"><span class="chev">' +
        (open ? "▾" : "▸") + "</span>" + esc(name) + '<span class="cnt">' + shown.length + "</span></button>" +
        '<div class="items"' + (open ? "" : ' hidden') + ">" + links + "</div></div>";
    }).join("");
    document.getElementById("app").innerHTML =
      '<div class="scrim" id="scrim"></div>' +
      '<div class="app"><nav class="nav" id="nav"><a class="brand" href="index.html"><span class="logo">N</span>Nick\'s Stock Desk</a>' +
      '<div id="qslot"><div class="qwrap" id="search"><input id="q" type="search" placeholder="Search stocks" autocomplete="off" spellcheck="false" enterkeyhint="search" aria-label="Search stocks" role="combobox" aria-autocomplete="list" aria-controls="qlist" aria-expanded="false" title="Search stocks. Press / or Ctrl+K">' +
      '<div class="qpop" id="qlist" role="listbox" hidden></div></div></div>' +
      themeHtml() + groups + "</nav><div class=\"main\"><div class=\"hdr\">" +
      '<button type="button" class="menu-btn" id="menu" aria-label="Open menu" aria-controls="nav" aria-expanded="false">☰</button>' +
      '<button type="button" class="search-btn" id="qbtn" aria-label="Search stocks" aria-expanded="false" aria-controls="q">' + SEARCH_ICON + "</button>" +
      "<div class=\"titles\"><h1>" + esc(page.title) + "</h1><div class=\"rl\">" + esc(RESEARCH) + "</div></div>" +
      '<div class="upd">Updated <b id="updated">…</b></div></div><div id="page"></div></div></div>';
    document.getElementById("nav").addEventListener("click", (e) => {
      const btn = e.target.closest(".grp");
      if (!btn) {
        if (e.target.closest("a.item")) document.body.classList.remove("nav-open");
        return;
      }
      const group = btn.parentElement;
      const items = group.querySelector(".items");
      const open = items.hasAttribute("hidden");
      if (open) {
        const name = btn.textContent.replace(/[▾▸]/g, "").replace(/\d+$/, "").trim();
        const spec = NAV_NOW.find((g) => g[0] === name);
        if (spec && !items.childElementCount) {
          items.innerHTML = navOn(spec[1]).map((it) => {
            return '<a class="item' + (it[2] === page.id ? " sel" : "") + '" href="' + it[1] + '">' + esc(it[0]) + "</a>";
          }).join("");
        }
        items.removeAttribute("hidden");
        btn.querySelector(".chev").textContent = "▾";
        btn.setAttribute("aria-expanded", "true");
      } else {
        items.setAttribute("hidden", "");
        btn.querySelector(".chev").textContent = "▸";
        btn.setAttribute("aria-expanded", "false");
      }
    });
    const menu = document.getElementById("menu");
    const scrim = document.getElementById("scrim");
    const setNav = (open) => {
      document.body.classList.toggle("nav-open", open);
      menu.setAttribute("aria-expanded", open ? "true" : "false");
      menu.setAttribute("aria-label", open ? "Close menu" : "Open menu");
    };
    menu.addEventListener("click", () => {
      const open = !document.body.classList.contains("nav-open");
      setNav(open);
      if (open) document.body.classList.remove("search-open");
    });
    scrim.addEventListener("click", () => setNav(false));
    document.getElementById("nav").addEventListener("click", (e) => {
      if (e.target.closest("a.item")) setNav(false);
    });
    wireSearch(setNav);
    wireTheme();
  }

  function findPage(id) {
    for (let i = 0; i < NAV.length; i++) {
      for (let j = 0; j < NAV[i][1].length; j++) {
        if (NAV[i][1][j][2] === id) return { id: id, title: NAV[i][1][j][0], href: NAV[i][1][j][1] };
      }
    }
    return null;
  }

  const FEATURE = {
    top: "feature.top_stocks",
    buysetups: "feature.buy_setups",
    scorecard: "feature.scorecard",
    watchlist: "feature.watchlist_portfolio",
    alerts: "feature.alerts",
    backtest: "feature.backtest",
    growth: "feature.scanner_growth",
    quality: "feature.scanner_quality",
    dividend: "feature.scanner_dividend",
    wheel: "feature.scanner_wheel",
    vcp: "feature.scanner_vcp",
    canslim: "feature.scanner_canslim",
    box: "feature.scanner_box",
    flag: "feature.scanner_flag",
    qullamaggie: "feature.scanner_qullamaggie",
    marios: "feature.scanner_marios",
    ep: "feature.scanner_ep",
    gapup: "feature.scanner_gap_up",
    breakdowns: "feature.scanner_breakdown",
    volume: "feature.scanner_volume",
    leaders: "feature.scanner_leaders",
    options: "feature.options",
    week52: "feature.scanner_52w",
    calendar: "feature.earnings_calendar",
    heatmap: "feature.earnings_heatmap",
    cards: "feature.earnings_cards",
    putcall: "feature.put_call",
    walls: "feature.option_walls",
    analysts: "feature.analyst_ratings",
    thirteen: "feature.institutional_13f",
    aaii: "feature.aaii_sentiment",
    insiders: "feature.insider_trading",
    headlines: "feature.headline_sentiment",
    xly: "feature.xly_xlp",
    financials: "feature.financials_summary",
    tracker: "feature.earnings_tracker",
    company: "feature.company_financials",
    divfund: "feature.dividend_scanner",
    rotation: "feature.sector_rotation",
    macro: "feature.macro_screener",
    secmacro: "feature.macro_screener",
    histpe: "feature.historical_pe",
    breakouts: "feature.breakouts",
    trends: "feature.trends",
    pullbacks: "feature.pullbacks",
    gainers: "feature.gainers_losers",
    breadth: "feature.breadth",
    secperf: "feature.sector_performance",
    heatmaps: "feature.heatmaps",
    updates: "feature.updates_log",
    help: "feature.help",
    chartviewer: "feature.chart_viewer",
  };
  // Lists the Chart Viewer can open. The key is the page id, so a scanner page links to its own list.
  const VIEWER_LISTS = ["buysetups", "watchlist", "growth", "quality", "dividend", "wheel", "vcp", "canslim", "box", "flag",
    "qullamaggie", "marios", "ep", "gapup", "breakdowns", "volume", "leaders", "week52"];
  function settingVal(key) {
    const row = SETTINGS.find((r) => r.setting === key);
    return row ? row.value : null;
  }
  function viewerOn(key) {
    if (!featureOn("feature.chart_viewer")) return false;
    if (!key) return true;
    const v = settingVal("chart_viewer." + key);
    return v == null || String(v).toLowerCase() !== "false";
  }
  function viewerHref(list, ticker) {
    let href = "chart-viewer.html?list=" + encodeURIComponent(list || "all");
    if (ticker) href += "&t=" + encodeURIComponent(String(ticker).trim().toUpperCase());
    return href;
  }
  function viewerLinkHtml(ticker) {
    const page = typeof document !== "undefined" && document.body ? document.body.dataset.page : "";
    if (!ticker || VIEWER_LISTS.indexOf(page) < 0 || !viewerOn("scanner_links")) return "";
    return '<p class="cvrow"><a class="cvlink" href="' + esc(viewerHref(page, ticker)) + '">Open in Chart Viewer</a></p>';
  }
  let SETTINGS = [];
  function featureOn(key) {
    if (!key) return true;
    const row = SETTINGS.find((r) => r.setting === key);
    if (!row) return true;
    return String(row.value).toLowerCase() !== "false";
  }
  function markReady(value) {
    requestAnimationFrame(() => requestAnimationFrame(() => { document.body.dataset.ready = value; }));
  }

  async function boot() {
    const id = document.body.dataset.page;
    const meta = findPage(id);
    const spec = (window.DESK_PAGES || {})[id];
    if (!meta || !spec) {
      document.body.dataset.ready = "error";
      return;
    }
    try {
      const names = ["updates_log.csv", "market_today.csv", "settings.csv"].concat(spec.files || []);
      const unique = Array.from(new Set(names));
      const loaded = {};
      await Promise.all(unique.map(async (n) => { loaded[n] = await loadCsv(n); }));
      SETTINGS = loaded["settings.csv"] || [];
      applyTheme(themeChoice());
      await loadBlurbs();
      renderShell(meta);
      const mt = loaded["market_today.csv"];
      const stamp = (mt && mt[0] && mt[0].updated_pt) || latestChecked(loaded["updates_log.csv"]);
      document.getElementById("updated").textContent = formatUpdated(stamp);
      if (FEATURE[id] && !featureOn(FEATURE[id])) {
        document.getElementById("page").innerHTML = '<div class="panel pad m2" style="font-size:12px">Turned off in Settings</div>';
        markReady("1");
        return;
      }
      spec.render({ page: document.getElementById("page"), files: loaded, settings: SETTINGS });
      markReady("1");
    } catch (err) {
      console.error(err);
      if (!document.getElementById("nav")) renderShell(meta || { id: id, title: "Nick's Stock Desk" });
      const host = document.getElementById("page");
      if (host) host.innerHTML = '<div class="banner miss">This page could not read its data file.</div>';
      document.body.dataset.ready = "error";
    }
  }

  window.Desk = {
    UP: UP, DN: DN, AM: AM, AC: AC, MU: MU, TX: TX, SPD: SPD,
    num: num, isBlank: isBlank, esc: esc, na: na, fmt: fmt, compact: compact,
    realRows: realRows, alertDataRows: alertDataRows, quietMessage: quietMessage, showQuiet: showQuiet,
    banner: banner, noteOf: noteOf, statusOf: statusOf, drawPriceChart: drawPriceChart,
    scoreHtml: scoreHtml, scoreFill: scoreFill, tickerHtml: tickerHtml, etfHtml: etfHtml, pctHtml: pctHtml, moneyHtml: moneyHtml,
    verdictHtml: verdictHtml, trendHtml: trendHtml, pointsHtml: pointsHtml, zoneHtml: zoneHtml, signedPts: signedPts,
    drawTable: drawTable, uniq: uniq, indexTokens: indexTokens,
    selectedMulti: selectedMulti, fieldVal: fieldVal,
    multiHtml: multiHtml, selectHtml: selectHtml, searchHtml: searchHtml, rangeHtml: rangeHtml,
    pairHtml: pairHtml, dateHtml: dateHtml, feedHtml: feedHtml, placeFeed: placeFeed,
    featureOn: featureOn, blurbOf: blurbOf, blurbHtml: blurbHtml, monthLabel: monthLabel, ptsColor: ptsColor,
    wireFilters: wireFilters, matchMulti: matchMulti, matchContains: matchContains,
    matchText: matchText, matchMin: matchMin,
    destroyCharts: destroyCharts, lineChart: lineChart, barChart: barChart, comboChart: comboChart, makeChart: makeChart,
    lastNDays: lastNDays, seriesNum: seriesNum, retColor: retColor, band: band,
    loadCsv: loadCsv, forgetCsv: (name) => { cache.delete(name); }, ensureTv: ensureTv, barsFromRows: barsFromRows, smaValues: smaValues, timeKey: timeKey,
    themed: themed, themedChart: themedChart, isLight: () => LIGHT,
    settingVal: settingVal, splitOn: splitOn, groupOf: groupOf, navGroups: navGroups, SCANNER_GROUPS: SCANNER_GROUPS, viewerOn: viewerOn, viewerHref: viewerHref, VIEWER_LISTS: VIEWER_LISTS,
    boot: boot,
  };
})();
