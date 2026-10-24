/* Nick's Stock Desk. Reads published CSVs. No broker calls and no new market requests. */
(function () {
  const UP = "#22C55E";
  const DN = "#EF4444";
  const AM = "#F59E0B";
  const AC = "#7C9CFF";
  const MU = "#8B96AD";
  const TX = "#E6EBF5";
  const RESEARCH = "Research only. Not a recommendation to buy or sell. This desk never places trades. Stocks only, no option contracts.";
  const NAV = [
    ["Overview", [
      ["Today", "index.html", "today"],
      ["Top stocks", "top-stocks.html", "top"],
      ["Stock scorecard", "scorecard.html", "scorecard"],
      ["Watchlist and portfolio", "watchlist.html", "watchlist"],
      ["Alerts", "alerts.html", "alerts"],
      ["Backtest", "backtest.html", "backtest"],
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
      ["Leaders", "leaders.html", "leaders"],
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
    const map = { "BROKEN OUT today": UP, READY: AM, WATCHING: MU };
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
      case "date": return isBlank(v) ? na() : esc(v);
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
    const numeric = ["num", "pct", "money", "compact", "dollars", "dist", "score", "points", "tone", "signal", "flag", "heatpct", "delta", "multiple", "volx", "retrace", "strengthbar"].indexOf(col.kind) >= 0;
    let c = 0;
    if (numeric) {
      const na_ = num(va);
      const nb_ = num(vb);
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

  function drawTable(host, opts) {
    const rows = opts.rows || [];
    const columns = opts.columns;
    const state = opts.state;
    const pageSize = opts.pageSize || 25;
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
    const shown = columns.filter((c) => !c.hidden);
    const head = shown.map((c) => {
      const mark = state.sort === c.key ? '<span class="sort">' + (state.dir === "asc" ? "▲" : "▼") + "</span>" : "";
      const cls = [align(c), c.hide === "md" ? "hide-md" : ""].filter(Boolean).join(" ");
      return '<th class="' + cls + '" data-k="' + esc(c.key) + '">' + esc(c.label) + mark + "</th>";
    }).join("");
    const body = view.map((r, i) => {
      const tds = shown.map((c) => {
        const cls = [align(c), c.wrap ? "wrap" : "", c.kind === "score" ? "score" : "", c.hide === "md" ? "hide-md" : ""].filter(Boolean).join(" ");
        const width = c.width ? " style=\"width:" + c.width + "\"" : "";
        return "<td class=\"" + cls + "\"" + width + ">" + cell(r, c) + "</td>";
      }).join("");
      const on = opts.pick && opts.pick === (r.ticker || "") && opts.pick !== "" ? " selrow" : "";
      return '<tr data-i="' + (start + i) + '" class="' + on + '">' + tds + "</tr>";
    }).join("");
    const empty = rows.length ? "" : '<div class="empty">' + esc(opts.empty || "No rows match these filters.") + "</div>";
    const from = rows.length ? start + 1 : 0;
    const to = Math.min(start + pageSize, rows.length);
    host.innerHTML =
      (opts.title ? '<div class="pad headrow" style="padding-bottom:0"><div class="ptitle">' + esc(opts.title) + "</div>" +
        (opts.sub ? '<div class="psub">' + esc(opts.sub) + "</div>" : "") + "</div>" : "") +
      '<div class="scroll"><table><thead><tr>' + head + "</tr></thead><tbody>" + body + "</tbody></table></div>" +
      empty +
      (opts.foot === false ? "" :
      '<div class="foot"><span>' + from + "–" + to + " of " + rows.length + '</span><div class="pg">' +
      '<button type="button" data-pg="prev"' + (state.page <= 0 ? " disabled" : "") + ">‹</button>" +
      '<button type="button" data-pg="next"' + (state.page >= pages - 1 ? " disabled" : "") + ">›</button></div></div>");
    host.querySelectorAll("th").forEach((th) => {
      th.addEventListener("click", () => {
        const k = th.getAttribute("data-k");
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
    if (opts.onPick) {
      host.querySelectorAll("tbody tr").forEach((tr) => {
        tr.addEventListener("click", (ev) => {
          if (ev.target.closest("a")) return;
          const i = Number(tr.getAttribute("data-i"));
          opts.onPick(sorted[i]);
        });
      });
    }
    host._sorted = sorted;
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
  function shortOpt(s) {
    return s === "BROKEN OUT today" ? "BROKEN OUT" : s;
  }
  function multiLabel(options, set) {
    if (!set || set.size === options.length) return "All";
    if (!set.size) return "None";
    if (set.size <= 2) return Array.from(set).map(shortOpt).join(", ");
    return set.size + " picked";
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

  function destroyCharts() {
    while (charts.length) {
      const c = charts.pop();
      try { c.destroy(); } catch (e) { /* already gone */ }
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
      maxTicksLimit: 7,
      maxRotation: 0,
      autoSkip: true,
      color: MU,
      callback(v) {
        return monthLabel(this.getLabelForValue(v), span);
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
    const valueAxis = Object.assign(axis(), extra.y || {});
    const catAxis = Object.assign(axis(), category, extra.cat || {});
    const plugins = Object.assign(basePlugins(false), extra.labels ? { barLabels: { dec: extra.dec == null ? 1 : extra.dec, suffix: extra.suffix || "" } } : {});
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
          ? { x: Object.assign(valueAxis, extra.x || {}), y: catAxis }
          : { x: Object.assign(catAxis, extra.x || {}), y: valueAxis },
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
      lines.forEach((ln) => {
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
        ctx.fillStyle = ln.color;
        ctx.font = "11px Roboto, Arial, sans-serif";
        ctx.textAlign = "right";
        ctx.fillText(ln.label || "", area.right - 6, yy - 4);
        ctx.restore();
      });
    },
  };
  const barLabels = {
    id: "barLabels",
    afterDatasetsDraw(chart) {
      const opt = chart.options.plugins && chart.options.plugins.barLabels;
      if (!opt) return;
      const meta = chart.getDatasetMeta(0);
      const ds = chart.data.datasets[0];
      if (!meta || !meta.data || meta.data.length >= 15 || !ds) return;
      const ctx = chart.ctx;
      const horizontal = chart.options.indexAxis === "y";
      ctx.save();
      ctx.font = "11px Roboto, Arial, sans-serif";
      ctx.textBaseline = "middle";
      meta.data.forEach((el, i) => {
        const v = Number(ds.data[i]);
        if (!Number.isFinite(v)) return;
        const dec = opt.dec == null ? 1 : opt.dec;
        const body = Math.abs(v) >= 1000 ? compact(v) : v.toFixed(dec);
        const text = (v > 0 ? "+" : v < 0 ? "−" : "") + String(body).replace(/^-/, "") + (opt.suffix || "");
        ctx.fillStyle = v > 0 ? UP : v < 0 ? DN : MU;
        if (horizontal) {
          ctx.textAlign = v >= 0 ? "left" : "right";
          ctx.fillText(text, el.x + (v >= 0 ? 4 : -4), el.y);
        } else {
          ctx.textAlign = "center";
          ctx.textBaseline = "bottom";
          ctx.fillText(text, el.x, el.y - 2);
        }
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

  function renderShell(page) {
    const groups = NAV.map(([name, items]) => {
      const open = items.some((it) => it[2] === page.id);
      const links = open ? items.map((it) => {
        const off = FEATURE[it[2]] && !featureOn(FEATURE[it[2]]);
        return '<a class="item' + (it[2] === page.id ? " sel" : "") + (off ? " off" : "") + '" href="' + it[1] + '">' + esc(it[0]) + "</a>";
      }).join("") : "";
      return '<div class="group" data-open="' + (open ? "1" : "0") + '">' +
        '<button type="button" class="grp" aria-expanded="' + (open ? "true" : "false") + '"><span class="chev">' +
        (open ? "▾" : "▸") + "</span>" + esc(name) + '<span class="cnt">' + items.length + "</span></button>" +
        '<div class="items"' + (open ? "" : ' hidden') + ">" + links + "</div></div>";
    }).join("");
    document.getElementById("app").innerHTML =
      '<div class="scrim" id="scrim"></div>' +
      '<div class="app"><nav class="nav" id="nav"><a class="brand" href="index.html"><span class="logo">N</span>Nick\'s Stock Desk</a>' +
      groups + "</nav><div class=\"main\"><div class=\"hdr\"><div><button type=\"button\" class=\"menu-btn\" id=\"menu\">☰</button>" +
      "<h1>" + esc(page.title) + "</h1><div class=\"rl\">" + esc(RESEARCH) + "</div></div>" +
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
        const spec = NAV.find((g) => g[0] === name);
        if (spec && !items.childElementCount) {
          items.innerHTML = spec[1].map((it) => {
            const off = FEATURE[it[2]] && !featureOn(FEATURE[it[2]]);
            return '<a class="item' + (it[2] === page.id ? " sel" : "") + (off ? " off" : "") + '" href="' + it[1] + '">' + esc(it[0]) + "</a>";
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
    menu.addEventListener("click", () => document.body.classList.toggle("nav-open"));
    scrim.addEventListener("click", () => document.body.classList.remove("nav-open"));
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
    leaders: "feature.scanner_leaders",
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
  };
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
    realRows: realRows, banner: banner, noteOf: noteOf, statusOf: statusOf,
    scoreHtml: scoreHtml, scoreFill: scoreFill, tickerHtml: tickerHtml, etfHtml: etfHtml, pctHtml: pctHtml, moneyHtml: moneyHtml,
    verdictHtml: verdictHtml, trendHtml: trendHtml, pointsHtml: pointsHtml, zoneHtml: zoneHtml, signedPts: signedPts,
    drawTable: drawTable, uniq: uniq, indexTokens: indexTokens,
    selectedMulti: selectedMulti, fieldVal: fieldVal,
    multiHtml: multiHtml, selectHtml: selectHtml, searchHtml: searchHtml, rangeHtml: rangeHtml,
    pairHtml: pairHtml, dateHtml: dateHtml, feedHtml: feedHtml, placeFeed: placeFeed,
    featureOn: featureOn, monthLabel: monthLabel, ptsColor: ptsColor,
    wireFilters: wireFilters, matchMulti: matchMulti, matchContains: matchContains,
    matchText: matchText, matchMin: matchMin,
    destroyCharts: destroyCharts, lineChart: lineChart, barChart: barChart, makeChart: makeChart,
    lastNDays: lastNDays, seriesNum: seriesNum, retColor: retColor, band: band,
    boot: boot,
  };
})();
