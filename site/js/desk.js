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
  function banner(rows) {
    const bad = statusOf(rows);
    if (!bad) return "";
    const note = bad.note || "";
    return '<div class="banner ' + (bad.data_status === "MISSING" ? "miss" : "part") + '"><b>' +
      esc(bad.data_status) + "</b> " + esc(note) + "</div>";
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
  function tickerHtml(v) {
    if (isBlank(v)) return na();
    return '<a class="tk" href="scorecard.html?t=' + encodeURIComponent(v) + '">' + esc(v) + "</a>";
  }
  function colored(text, color) {
    if (isBlank(text)) return na();
    return '<span class="pill" style="color:' + color + '">' + esc(text) + "</span>";
  }
  function verdictHtml(v) {
    const map = { BUY: UP, HOLD: AM, AVOID: DN };
    return colored(v, map[v] || TX);
  }
  function trendHtml(v) {
    const map = { Uptrend: UP, Downtrend: DN, Extended: AM, Sideways: MU, Mixed: MU };
    return colored(v, map[v] || TX);
  }
  function setupHtml(v) {
    const map = { "BROKEN OUT today": UP, READY: AM, WATCHING: MU };
    return colored(v, map[v] || TX);
  }
  function freshHtml(v) {
    const map = { FRESH: MU, PARTIAL: AM, STALE: DN, OK: MU, CACHED: MU, MISSING: AM };
    return colored(v, map[v] || TX);
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
  function pointsHtml(v) {
    const n = num(v);
    if (n == null) return na();
    const label = Number.isInteger(n) ? String(n) : fmt(n, 1);
    return '<span class="pill" style="color:' + (ptsColor(n) || TX) + '">' + esc(label) + "</span>";
  }
  function pointsLabelHtml(v) {
    if (isBlank(v) || v === "n/a") return na();
    let color = TX;
    if (v.indexOf("plus") === 0) color = v.indexOf("2") >= 0 ? "#166534" : "#14532D";
    else if (v === "zero") color = "#283146";
    else if (v.indexOf("minus") === 0) color = v.indexOf("2") >= 0 ? "#B91C1C" : "#7F1D1D";
    return '<span class="pill" style="color:' + color + '">' + esc(v) + "</span>";
  }
  function gradeHtml(v) {
    const fills = { A: "#166534", B: "#14532D", C: "#283146", D: "#7F1D1D", F: "#B91C1C" };
    if (isBlank(v)) return na();
    return '<span class="scorepill" style="background:' + (fills[v] || "#283146") + ';min-width:36px;height:28px;font-size:14px">' + esc(v) + "</span>";
  }
  function holdHtml(v) {
    const map = { "Below stop": DN, Weakening: AM, "Earnings soon": AC, "On track": MU };
    return colored(v, map[v] || TX);
  }
  function kindHtml(v) {
    const map = { breakout: UP, entry_zone: AC, verdict_change: AM, score_jump: TX, score_cross: TX, info: MU, new_stock: AC };
    return colored(v, map[v] || TX);
  }
  function zoneHtml(v) {
    const map = { Fear: DN, Greed: UP, Neutral: AM, "Risk on": UP, "Risk off": DN };
    return colored(v, map[v] || AM);
  }
  function toneHtml(v) {
    const n = num(v);
    if (n == null) return na();
    const color = n > 0 ? UP : n < 0 ? DN : MU;
    return '<span class="pill" style="color:' + color + '">' + esc(String(n)) + "</span>";
  }
  function flagHtml(v) {
    if (isBlank(v)) return na();
    const n = num(v);
    if (n === 1 || v === "yes" || v === "true") return colored("Yes", UP);
    if (n === 0 || v === "no" || v === "false") return colored("No", MU);
    return esc(v);
  }
  function moneyHtml(v, d, colorRet) {
    const n = num(v);
    if (n == null) return na();
    const text = (n < 0 ? "-$" : "$") + fmt(Math.abs(n), d == null ? 2 : d);
    if (!colorRet) return esc(text);
    return '<span style="color:' + retColor(n) + '">' + esc(text) + "</span>";
  }
  function pctHtml(v, d, colorRet) {
    const n = num(v);
    if (n == null) return na();
    const text = fmt(n, d == null ? 2 : d) + "%";
    if (!colorRet) return esc(text);
    return '<span style="color:' + retColor(n) + '">' + esc(text) + "</span>";
  }
  function heatPct(v, d) {
    const n = num(v);
    if (n == null) return na();
    const mag = Math.min(Math.abs(n) / 5, 1);
    const bg = n > 0 ? "rgba(34,197,94," + (0.18 + mag * 0.55) + ")" : n < 0 ? "rgba(239,68,68," + (0.18 + mag * 0.55) + ")" : "transparent";
    return '<span style="color:' + retColor(n) + ";background:" + bg + ';padding:2px 4px;border-radius:4px">' + esc(fmt(n, d == null ? 1 : d) + "%") + "</span>";
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
      case "score": return scoreHtml(v);
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
      case "flag": return flagHtml(v);
      case "money": return moneyHtml(v, d, !!col.color);
      case "compact": return isBlank(v) ? na() : esc(compact(v));
      case "pct": return pctHtml(v, d, col.color !== false);
      case "heatpct": return heatPct(v, d);
      case "dist": return distHtml(v);
      case "num": return num(v) == null ? na() : esc(fmt(v, d));
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
    const numeric = ["num", "pct", "money", "compact", "dist", "score", "points", "tone", "signal", "flag", "heatpct"].indexOf(col.kind) >= 0;
    let c = 0;
    if (numeric) {
      const na = num(va);
      const nb = num(vb);
      if (na == null && nb == null) c = 0;
      else if (na == null) c = 1;
      else if (nb == null) c = -1;
      else c = na - nb;
    } else {
      c = String(va || "").localeCompare(String(vb || ""), undefined, { numeric: true, sensitivity: "base" });
    }
    return dir === "asc" ? c : -c;
  }

  function drawTable(host, opts) {
    const rows = opts.rows || [];
    const columns = opts.columns;
    const state = opts.state;
    const pageSize = opts.pageSize || 25;
    const sorted = rows.slice().sort((a, b) => compare(a, b, columns.find((c) => c.key === state.sort) || columns[0], state.dir));
    const pages = Math.max(1, Math.ceil(sorted.length / pageSize));
    if (state.page >= pages) state.page = pages - 1;
    if (state.page < 0) state.page = 0;
    const start = state.page * pageSize;
    const view = sorted.slice(start, start + pageSize);
    const head = columns.map((c) => {
      const mark = state.sort === c.key ? '<span class="sort">' + (state.dir === "asc" ? "▲" : "▼") + "</span>" : "";
      return '<th class="' + align(c) + '" data-k="' + esc(c.key) + '">' + esc(c.label) + mark + "</th>";
    }).join("");
    const body = view.map((r, i) => {
      const tds = columns.map((c) => {
        const cls = [align(c), c.wrap ? "wrap" : ""].filter(Boolean).join(" ");
        return "<td class=\"" + cls + "\">" + cell(r, c) + "</td>";
      }).join("");
      const on = opts.pick && opts.pick === (r.ticker || "") && opts.pick !== "" ? " selrow" : "";
      return '<tr data-i="' + (start + i) + '" class="' + on + '">' + tds + "</tr>";
    }).join("");
    const empty = rows.length ? "" : '<div class="empty">' + esc(opts.empty || "No rows match these filters.") + "</div>";
    const from = rows.length ? start + 1 : 0;
    const to = Math.min(start + pageSize, rows.length);
    host.innerHTML =
      (opts.title ? '<div class="pad" style="padding-bottom:0"><div class="ptitle">' + esc(opts.title) + "</div>" +
        (opts.sub ? '<div class="psub">' + esc(opts.sub) + "</div>" : "") + "</div>" : "") +
      '<div class="scroll"><table><thead><tr>' + head + "</tr></thead><tbody>" + body + "</tbody></table></div>" +
      empty +
      '<div class="foot"><span>' + from + "–" + to + " of " + rows.length + '</span><div class="pg">' +
      '<button type="button" data-pg="prev"' + (state.page <= 0 ? " disabled" : "") + ">‹</button>" +
      '<button type="button" data-pg="next"' + (state.page >= pages - 1 ? " disabled" : "") + ">›</button></div></div>";
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
    const shown = !set || set.size === options.length ? "All" : set.size === 0 ? "None" : set.size + " picked";
    return '<div class="filter" data-id="' + esc(id) + '"><button type="button" class="dd">' + esc(label) +
      ' <span class="dmut">' + esc(shown) + '</span></button><div class="pop" data-filter="' + esc(id) + '">' + checks + "</div></div>";
  }
  function selectHtml(id, label, options, value) {
    const opts = ['<option value="">All</option>'].concat(options.map((o) =>
      '<option value="' + esc(o) + '"' + (o === value ? " selected" : "") + ">" + esc(o) + "</option>"));
    return '<label class="m2" style="font-size:12px">' + esc(label) + '<br><select class="dd" data-filter="' + esc(id) + '">' + opts.join("") + "</select></label>";
  }
  function searchHtml(id, label, listId, values) {
    const opts = values.slice(0, 800).map((v) => "<option value=\"" + esc(v) + "\"></option>").join("");
    return '<label class="m2" style="font-size:12px">' + esc(label) +
      '<br><input class="dd" data-filter="' + esc(id) + '" list="' + esc(listId) + '" placeholder="All">' +
      '<datalist id="' + esc(listId) + '">' + opts + "</datalist></label>";
  }
  function rangeHtml(id, label, min, max, value, step) {
    return '<label class="m2" style="font-size:12px">' + esc(label) +
      '<br><input class="dd" type="number" data-filter="' + esc(id) + '" min="' + min + '" max="' + max +
      '" step="' + (step || "any") + '" value="' + value + '" style="width:120px"></label>';
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
          if (!on.length) label.textContent = "None";
          else if (on.length === all.length) label.textContent = "All";
          else label.textContent = on.length + " picked";
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
  function lineChart(canvas, labels, series, extra) {
    extra = extra || {};
    makeChart(canvas, {
      type: "line",
      data: {
        labels: labels,
        datasets: series.map((s) => ({
          label: s.label,
          data: s.data,
          borderColor: s.color,
          backgroundColor: "transparent",
          spanGaps: !!s.spanGaps,
          borderWidth: 2,
          pointRadius: 0,
          tension: 0,
        })),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: Object.assign(basePlugins(extra.legend !== false), extra.plugins || {}),
        scales: {
          x: axis(),
          y: Object.assign(axis(), extra.y || {}),
        },
      },
    });
  }
  function barChart(canvas, labels, data, colors, extra) {
    extra = extra || {};
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
        indexAxis: extra.horizontal ? "y" : "x",
        responsive: true,
        maintainAspectRatio: false,
        plugins: basePlugins(false),
        scales: { x: axis(), y: Object.assign(axis(), extra.y || {}) },
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
        ctx.font = "11px Roboto, Arial";
        ctx.fillText(ln.label || "", area.left + 6, yy - 4);
        ctx.restore();
      });
    },
  };
  if (typeof Chart !== "undefined") Chart.register(hlines);

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
      const links = open ? items.map((it) =>
        '<a class="item' + (it[2] === page.id ? " sel" : "") + '" href="' + it[1] + '">' + esc(it[0]) + "</a>").join("") : "";
      return '<div class="group" data-open="' + (open ? "1" : "0") + '">' +
        '<button type="button" class="grp" aria-expanded="' + (open ? "true" : "false") + '"><span class="chev">' +
        (open ? "▾" : "▸") + "</span>" + esc(name) + '<span class="cnt">' + items.length + "</span></button>" +
        '<div class="items"' + (open ? "" : ' hidden') + ">" + links + "</div></div>";
    }).join("");
    document.getElementById("app").innerHTML =
      '<div class="scrim" id="scrim"></div>' +
      '<div class="app"><nav class="nav" id="nav"><a class="brand" href="index.html"><span class="logo">N</span>Nick\'s Stock Desk</a>' +
      groups + "</nav><div class=\"main\"><div class=\"hdr\"><div><button type=\"button\" class=\"menu-btn\" id=\"menu\">Menu</button>" +
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
          items.innerHTML = spec[1].map((it) =>
            '<a class="item' + (it[2] === page.id ? " sel" : "") + '" href="' + it[1] + '">' + esc(it[0]) + "</a>").join("");
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

  async function boot() {
    const id = document.body.dataset.page;
    const meta = findPage(id);
    const spec = (window.DESK_PAGES || {})[id];
    if (!meta || !spec) {
      document.body.dataset.ready = "error";
      return;
    }
    renderShell(meta);
    try {
      const names = ["updates_log.csv"].concat(spec.files || []);
      const unique = Array.from(new Set(names));
      const loaded = {};
      await Promise.all(unique.map(async (n) => { loaded[n] = await loadCsv(n); }));
      const mt = loaded["market_today.csv"];
      const stamp = (mt && mt[0] && mt[0].updated_pt) || latestChecked(loaded["updates_log.csv"]);
      document.getElementById("updated").textContent = formatUpdated(stamp);
      spec.render({ page: document.getElementById("page"), files: loaded });
      document.body.dataset.ready = "1";
    } catch (err) {
      console.error(err);
      const host = document.getElementById("page");
      if (host) host.innerHTML = '<div class="banner miss">This page could not read its data file.</div>';
      document.body.dataset.ready = "error";
    }
  }

  window.Desk = {
    UP: UP, DN: DN, AM: AM, AC: AC, MU: MU, TX: TX, SPD: SPD,
    num: num, isBlank: isBlank, esc: esc, na: na, fmt: fmt, compact: compact,
    realRows: realRows, banner: banner, noteOf: noteOf, statusOf: statusOf,
    scoreHtml: scoreHtml, tickerHtml: tickerHtml, pctHtml: pctHtml, moneyHtml: moneyHtml,
    verdictHtml: verdictHtml, trendHtml: trendHtml, pointsHtml: pointsHtml, zoneHtml: zoneHtml,
    drawTable: drawTable, uniq: uniq, indexTokens: indexTokens,
    selectedMulti: selectedMulti, fieldVal: fieldVal,
    multiHtml: multiHtml, selectHtml: selectHtml, searchHtml: searchHtml, rangeHtml: rangeHtml,
    wireFilters: wireFilters, matchMulti: matchMulti, matchContains: matchContains,
    matchText: matchText, matchMin: matchMin,
    destroyCharts: destroyCharts, lineChart: lineChart, barChart: barChart, makeChart: makeChart,
    lastNDays: lastNDays, seriesNum: seriesNum, retColor: retColor, band: band,
    boot: boot,
  };
})();
