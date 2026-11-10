/* Nick 360 workspace. Reads the desk files already on this site. No new price requests. */
(function () {
  "use strict";
  const E = window.N360;
  const Chart = window.N360Chart;
  const root = document.getElementById("n360");
  const view = document.getElementById("view");
  const PAGES = ["dashboard", "charting", "focus", "grader", "analytics"];
  const RANGES = ["5Y", "1Y", "6M", "3M", "1M"];
  const state = {
    page: "charting",
    left: "screens",
    right: "alerts",
    symbol: "",
    tf: "D",
    range: "1Y",
    hover: null,
    geom: null,
    open: {},
    sortKey: "rank",
    sortDir: -1,
    query: "",
    alertDays: 15,
    alertFilter: "all",
    marksOn: true,
    menuOpen: false,
    grader: "trades",
    cap: false,
    lossShift: 0,
    phase: "Loading stored files",
    progress: 0,
    error: "",
    missing: 0,
    meta: {},
    market: {},
    news: [],
    earnings: {},
    calendar: {},
    desk: null,
    by: new Map(),
    ready: false,
  };

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[c]));
  }
  function num(v) {
    if (v == null || v === "") return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  function pct(x, d) {
    if (!E.finite(x)) return "—";
    return (x > 0 ? "+" : "") + (x * 100).toFixed(d == null ? 2 : d) + "%";
  }
  function px(x) {
    return E.finite(x) ? x.toFixed(2) : "—";
  }
  function delay(ms) { return new Promise((r) => setTimeout(r, ms)); }
  function csvUrl(name) {
    if (location.hostname.endsWith("github.io")) {
      return "https://raw.githubusercontent.com/PatelNicknp/nicks-stock-desk/main/data/" + name;
    }
    return new URL("../../data/" + name, location.href).href;
  }
  function loadCsv(name) {
    return new Promise((resolve, reject) => {
      if (typeof Papa === "undefined") { reject(new Error("PapaParse did not load")); return; }
      Papa.parse(csvUrl(name), {
        download: true, header: true, skipEmptyLines: "greedy",
        complete: (res) => resolve(res.data || []),
        error: (err) => reject(err || new Error(name)),
      });
    });
  }
  function parseOhlc(text) {
    const lines = text.split(/\n/);
    const rows = [];
    for (let i = 1; i < lines.length; i++) {
      if (!lines[i]) continue;
      const p = lines[i].split(",");
      rows.push({ date: p[0], open: p[1], high: p[2], low: p[3], close: p[4], volume: p[5] });
    }
    return rows;
  }
  function store(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (err) { /* private mode */ }
  }
  function readStore(key, fallback) {
    try {
      const raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (err) { return fallback; }
  }
  function loadList(key) { return readStore(key, []); }
  function loadPaper() { return readStore("n360-paper", []); }
  function loadMissed() { return readStore("n360-missed", []); }
  function loadCash() {
    const n = num(readStore("n360-cash", null));
    return n;
  }
  function uid() { return "n" + Math.random().toString(36).slice(2, 10); }
  function current() { return state.by.get(state.symbol) || (state.indexes && state.indexes.get(state.symbol)) || null; }
  function prices() {
    const out = {};
    state.by.forEach((s, t) => { if (E.finite(s.close)) out[t] = s.close; });
    return out;
  }
  function stats() {
    return E.paperStats(loadPaper(), {
      startingCash: loadCash(),
      year: String((state.meta && state.meta.price_as_of) || "").slice(0, 4) || null,
      prices: prices(),
      capLossPct: state.cap ? -0.10 : null,
      lossShiftPct: state.lossShift || 0,
    });
  }
  function gradeLetter(s) {
    if (!s || s.last < 0) return null;
    const g = s.grade[s.last];
    return g && g.letter ? g.letter : null;
  }
  function rankOf(s) { return s && s.last >= 0 ? s.rank[s.last] : null; }
  function setHash() {
    const sym = state.symbol ? "/" + state.symbol : "";
    history.replaceState(null, "", "#" + state.page + sym);
  }
  function readHash() {
    const raw = location.hash.replace(/^#/, "");
    const bits = raw.split("/");
    if (PAGES.indexOf(bits[0]) >= 0) state.page = bits[0];
    if (bits[1]) state.symbol = bits[1].toUpperCase();
  }

  function weekly(stock) {
    const bars = E.toWeekly(stock.bars);
    const s = E.analyzeBars(bars);
    const idx = new Map();
    stock.bars.forEach((b, i) => idx.set(b.d, i));
    bars.forEach((b, i) => {
      const di = idx.get(b.d);
      if (di == null) return;
      s.rank[i] = stock.rank[di];
      s.grade[i] = stock.grade[di];
    });
    s.ticker = stock.ticker;
    s.company = stock.company;
    s.recent = [];
    return s;
  }
  function levelsFor(s) {
    const out = [];
    const sc = s.score || {};
    [["entry_low", E.ENTRY_COLOR], ["entry_high", E.ENTRY_COLOR], ["stop", E.STOP_COLOR], ["trade_target", E.TARGET_COLOR]].forEach((pair) => {
      const n = num(sc[pair[0]]);
      if (n != null) out.push({ price: n, color: pair[1] });
    });
    if (E.finite(s.pivot20)) out.push({ price: s.pivot20, color: E.PIVOT_COLOR });
    return out;
  }
  function marksFor(s) {
    const marks = [];
    if (state.marksOn) {
      (state.earnings[s.ticker] || []).forEach((row) => {
        if (row.eps_actual) marks.push({ date: row.earnings_date, text: "E", color: "#a5b4fc" });
      });
    }
    loadPaper().forEach((f) => {
      if (f.ticker !== s.ticker) return;
      marks.push({ date: f.date, text: f.side === "sell" ? "Sell" : "Buy", color: f.side === "sell" ? "#f97316" : "#22c55e" });
    });
    return marks;
  }
  let drawnKey = "";
  function drawActive() {
    if (!Chart) return;
    const cv = document.getElementById("cv");
    const gcv = document.getElementById("gcv");
    const key = [state.page, state.symbol, state.range, state.tf, state.hover, state.marksOn, cv ? cv.clientWidth + "x" + cv.clientHeight : "", gcv ? gcv.clientWidth + "x" + gcv.clientHeight : ""].join("|");
    if (key === drawnKey) return;
    drawnKey = key;
    const stock = current();
    if (cv && stock) {
      const shown = state.tf === "W" ? weekly(stock) : stock;
      state.geom = Chart.drawChart(cv, shown, {
        range: state.range, hover: state.hover, weekly: state.tf === "W",
        levels: levelsFor(stock), marks: marksFor(stock),
      });
    }
    if (gcv && stock) {
      Chart.drawChart(gcv, stock, { range: "1Y", levels: levelsFor(stock), marks: marksFor(stock) });
    }
    drawAnalytics();
  }
  function drawAnalytics() {
    if (!Chart || state.page !== "analytics") return;
    const book = stats();
    const closed = book.closed || [];
    const seq = document.getElementById("gl");
    const gain = document.getElementById("gmag");
    const loss = document.getElementById("lmag");
    if (seq) Chart.drawBars(seq, closed.map((t) => ({ v: t.pnlPct || 0, color: t.pnl >= 0 ? "#22c55e" : "#ef4444" })));
    if (gain) Chart.drawBars(gain, magnitude(closed, 1));
    if (loss) Chart.drawBars(loss, magnitude(closed, -1));
  }
  function magnitude(closed, sign) {
    const rows = closed.filter((t) => sign > 0 ? t.pnl > 0 : t.pnl < 0);
    if (!rows.length) return [];
    const bins = [0, 0, 0, 0, 0];
    const edges = [0.05, 0.10, 0.20, 0.40, Infinity];
    rows.forEach((t) => {
      const a = Math.abs(t.pnlPct || 0);
      for (let i = 0; i < edges.length; i++) {
        if (a < edges[i] || i === edges.length - 1) { bins[i] += 1; break; }
      }
    });
    const color = sign > 0 ? "#22c55e" : "#ef4444";
    return bins.map((v) => ({ v: v, color: color }));
  }

  function sortVal(s, key) {
    if (key === "ticker") return s.ticker;
    if (key === "chg") return s.chg;
    if (key === "last") return s.close;
    if (key === "rank") return rankOf(s);
    if (key === "grade") return gradeLetter(s) ? "DCBA".indexOf(gradeLetter(s)) : null;
    if (key === "off") return s.offHigh;
    return s.ticker;
  }
  function screenRows(screen) {
    let list = (screen.matches || []).map((t) => state.by.get(t)).filter(Boolean);
    const q = state.query.trim().toUpperCase();
    if (q) list = list.filter((s) => s.ticker.indexOf(q) >= 0 || String(s.company).toUpperCase().indexOf(q) >= 0);
    const dir = state.sortDir;
    list.sort((a, b) => {
      const av = sortVal(a, state.sortKey);
      const bv = sortVal(b, state.sortKey);
      if (av == null && bv == null) return a.ticker < b.ticker ? -1 : 1;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (av < bv) return -1 * dir;
      if (av > bv) return 1 * dir;
      return a.ticker < b.ticker ? -1 : 1;
    });
    return list;
  }
  function rowHtml(s, screen) {
    const g = gradeLetter(s);
    const ch = s.chg;
    const vcpMark = screen && screen.id === "vcp" && s.vcp && s.vcp.count
      ? " " + s.vcp.count + (s.vcp.strict ? "S" : "") + (s.vcp.brokenOut ? "\u2191" : "")
      : "";
    const tip = screen && screen.id === "vcp" && s.vcp ? ' title="' + esc(s.vcp.reason) + '"' : "";
    return '<button type="button" class="srow' + (s.ticker === state.symbol ? " sel" : "") + '" data-act="pick" data-ticker="' + esc(s.ticker) + '"' + tip + ">" +
      "<b>" + esc(s.ticker) + esc(vcpMark) + "</b><span class=\"" + (ch == null ? "mut" : ch >= 0 ? "up" : "dn") + "\">" + pct(ch, 2) + "</span><span>" + px(s.close) +
      "</span><span>" + (E.finite(rankOf(s)) ? rankOf(s) : "—") + "</span><span class=\"g" + esc(g || "") + "\">" + esc(g || "—") +
      "</span><span class=\"" + (s.offHigh != null && s.offHigh < 0 ? "dn" : "mut") + "\">" + pct(s.offHigh, 1) + "</span></button>";
  }
  function chips(list) {
    if (!list.length) return '<span class="mut">None</span>';
    return list.map((e) => '<span class="chip ' + (e.side === "neg" ? "neg" : e.side === "pos" ? "pos" : "neu") + '" title="' + esc(e.date || "") + '">' + esc(e.text) + "</span>").join("");
  }
  function aggregated(s) {
    const pos = [];
    const neg = [];
    const seen = {};
    s.recent.slice(-state.alertDays).forEach((block) => {
      block.events.forEach((e) => {
        const key = e.side + e.text;
        if (seen[key]) return;
        seen[key] = true;
        const item = { text: e.text, side: e.side, date: block.date };
        if (e.side === "neg") neg.push(item);
        else if (e.side === "pos") pos.push(item);
      });
    });
    return { pos: pos, neg: neg };
  }

  function screensHtml() {
    const screens = (state.desk && state.desk.screens) || [];
    const mans = state.manifest || [];
    const live = mans.filter((r) => r.role && r.role !== "unavailable");
    const gaps = mans.filter((r) => r.role === "unavailable");
    const indexBox = '<div class="pad"><div class="ph" style="padding:0 0 6px">Index series</div>' +
      live.map((r) => '<button type="button" class="scr' + (state.symbol === r.symbol ? " open" : "") + '" data-act="pick" data-ticker="' + esc(r.symbol) + '">' + esc(r.symbol) + " · " + esc(r.name) + "</button>").join("") +
      '<p class="note">' + gaps.map((r) => esc(r.symbol) + " unavailable. " + esc(r.note)).join(" ") + "</p></div>";
    const head = indexBox + '<div class="ph">Screens <input id="qsym" aria-label="Filter symbols" placeholder="Filter" value="' + esc(state.query) + '"></div>' +
      '<div class="legend">Rank is our 1–99 twelve-month score. Grade is our A–D checklist. Neither is a third-party rating. A screen with missing inputs is counted as not evaluated, not as a miss.</div>' +
      '<div class="cols"><button type="button" data-act="sort" data-key="ticker">Symbol</button><button type="button" data-act="sort" data-key="chg">Chg %</button><button type="button" data-act="sort" data-key="last">Last</button><button type="button" data-act="sort" data-key="rank">Rank</button><button type="button" data-act="sort" data-key="grade">Grade</button><button type="button" data-act="sort" data-key="off">% off high</button></div>';
    const body = screens.map((screen) => {
      const open = !!state.open[screen.id];
      if (screen.status !== "enabled") {
        return '<button type="button" class="scr off' + (open ? " open" : "") + '" data-act="toggle" data-screen="' + esc(screen.id) + '"><span class="car">▸</span>' + esc(screen.ourName) + '<span class="cnt">Unavailable</span></button>' +
          (open ? '<div class="pad note">' + esc(screen.evidence) + " " + esc(screen.formula) + "</div>" : "");
      }
      const rows = open ? screenRows(screen) : [];
      const vcpNote = screen.id === "vcp" ? '<div class="pad note">The number after the symbol is how many contractions are in the run. Two is the minimum, and four or more stay listed. An S means the last 10 sessions are also at or below 75% of the prior 50. An arrow means the close is above that name\'s pivot. The run must tighten by at least 20% each step, start at most 35% deep, finish under 10%, and cover at least 15 sessions. The last contraction must print lower volume than the one before it. The last 10 sessions must average at most 90% of the prior 50, or that last contraction must sit below the 50-session average. The last 10 sessions stay inside an 8% range with the close near the pivot. Breakout volume is a separate screen.</div>' : "";
      return '<button type="button" class="scr' + (open ? " open" : "") + '" data-act="toggle" data-screen="' + esc(screen.id) + '" title="' + esc(screen.formula) + '"><span class="car">▸</span>' + esc(screen.ourName) +
        '<span class="cnt">' + screen.matches.length + "</span></button>" +
        (open ? '<div>' + vcpNote + (rows.length ? rows.map((s) => rowHtml(s, screen)).join("") : '<div class="pad note">No names passed. ' + screen.skipped + " not evaluated because an input was missing. " + screen.evaluated + " were evaluated.</div>") + "</div>" : "");
    }).join("");
    return head + '<div class="scroll" id="screencroll">' + body + "</div>";
  }
  function listHtml(kind) {
    const rows = loadList(kind === "focus" ? "n360-focus" : "n360-watch");
    if (!rows.length) return '<div class="pad note">Nothing saved in this browser yet. Use Actions on a chart, or add a symbol on Focus List. This list does not sync to another device.</div>';
    return '<div class="scroll">' + rows.map((row) => {
      const s = state.by.get(row.ticker);
      return s ? rowHtml(s) : '<button type="button" class="srow" data-act="pick" data-ticker="' + esc(row.ticker) + '"><b>' + esc(row.ticker) + '</b><span class="mut">No stored bars</span></button>';
    }).join("") + "</div>";
  }
  function portfolioSide() {
    const book = stats();
    const groups = [["full", "Full positions"], ["half", "Half positions"], ["quarter", "Quarter positions"], ["other", "Unclassified"]];
    const any = groups.some((g) => book.groups[g[0]].length);
    if (!any) return '<div class="pad note">No paper positions in this browser. Add a buy on Analytics. The desk example portfolio is not copied in, and nothing here is a live account.</div>';
    return '<div class="scroll">' + groups.map((g) => {
      const rows = book.groups[g[0]];
      if (!rows.length) return "";
      return '<div class="grp">' + g[1] + " (" + rows.length + ")</div>" + rows.map((row) => {
        const s = state.by.get(row.ticker);
        return s ? rowHtml(s) : '<div class="pad">' + esc(row.ticker) + "</div>";
      }).join("");
    }).join("") + "</div>";
  }
  function alertReport() {
    const focus = {};
    const watch = {};
    loadList("n360-focus").forEach((r) => { focus[r.ticker] = true; });
    loadList("n360-watch").forEach((r) => { watch[r.ticker] = true; });
    const groups = { focus: [], watch: [], other: [] };
    state.desk.stocks.forEach((s) => {
      const bag = aggregated(s);
      if (state.alertFilter === "pos" && !bag.pos.length) return;
      if (state.alertFilter === "neg" && !bag.neg.length) return;
      if (!bag.pos.length && !bag.neg.length) return;
      const bucket = focus[s.ticker] ? "focus" : watch[s.ticker] ? "watch" : "other";
      groups[bucket].push({ s: s, bag: bag });
    });
    const shownOther = groups.other.slice(0, 60);
    function block(title, rows, extra) {
      if (!rows.length && !extra) return "";
      return '<div class="grp">' + title + "</div>" + rows.map((row) => {
        const g = gradeLetter(row.s);
        const r = rankOf(row.s);
        return '<button type="button" class="arow' + (row.s.ticker === state.symbol ? " sel" : "") + '" data-act="pick" data-ticker="' + esc(row.s.ticker) + '"><span><b>' + esc(row.s.ticker) +
          '</b><div class="mut">' + (E.finite(r) ? "Rank " + r : "Rank —") + (g ? " · Grade " + esc(g) : "") + "</div></span><span>" + chips(row.bag.pos) + "</span><span>" + chips(row.bag.neg) + "</span></button>";
      }).join("") + (extra || "");
    }
    return '<div class="ph">Alert report <span><select id="adays" aria-label="Sessions">' +
      [5, 15, 30, 60].map((n) => '<option value="' + n + '"' + (state.alertDays === n ? " selected" : "") + ">" + n + " sessions</option>").join("") +
      '</select></span></div><div class="alerthead"><span>Symbol</span><button type="button" data-act="afilter" data-filter="pos">Good signs</button><button type="button" data-act="afilter" data-filter="neg">Warnings</button></div><div class="scroll">' +
      block("Focus list (" + groups.focus.length + ")", groups.focus) +
      block("Watchlist (" + groups.watch.length + ")", groups.watch) +
      block("Other names (" + groups.other.length + ")", shownOther, groups.other.length > shownOther.length ? '<div class="pad note">Showing 60 of ' + groups.other.length + ".</div>" : "") +
      (!groups.focus.length && !groups.watch.length && !groups.other.length ? '<div class="pad note">No good signs or warnings in this window.</div>' : "") +
      "</div>";
  }
  function leftHtml() {
    if (state.left === "portfolio") return portfolioSide();
    if (state.left === "watch") return listHtml("watch");
    if (state.left === "alerts") return alertReport();
    return screensHtml();
  }
  function quoteHtml(s) {
    const b = s.bars[s.last];
    const rv = s.relVol[s.last];
    const ma20 = s.sma[20][s.last];
    const vs20 = E.finite(ma20) ? s.close / ma20 - 1 : null;
    const p = s.pressure[s.last];
    const risk = s.risk[s.last];
    const g = gradeLetter(s);
    const badge = (text, cls) => '<span class="bd ' + cls + '">' + text + "</span>";
    return "<span>O <b>" + px(b.o) + "</b></span><span>H <b>" + px(b.h) + "</b></span><span>L <b>" + px(b.l) + "</b></span><span>C <b>" + px(b.c) + "</b> <span class=\"" + (s.chg != null && s.chg < 0 ? "dn" : "up") + "\">" + pct(s.chg, 2) + "</span></span>" +
      "<span>Vol <b>" + (b.v == null ? "—" : Math.round(b.v).toLocaleString()) + "</b></span>" +
      "<span>V/50d <b>" + (E.finite(rv) ? rv.toFixed(2) + "× (" + pct(rv - 1, 0) + ")" : "—") + "</b></span>" +
      "<span>vs MA20 <b>" + pct(vs20, 2) + "</b></span><span>252w high <b>" + pct(s.offHigh, 1) + "</b></span>" +
      '<span class="badges">' +
      badge(s.stage.stage ? "Stage " + s.stage.stage : "Stage —", "bp") +
      badge(p ? "Pressure " + p.color : "Pressure —", p && p.color === "red" ? "br" : p && p.color === "yellow" ? "by" : "bg") +
      badge(risk ? "Entry " + risk.color : "Entry —", risk && risk.color === "red" ? "br" : risk && risk.color === "yellow" ? "by" : "bg") +
      badge(E.finite(rankOf(s)) ? "Rank " + rankOf(s) : "Rank —", "bp") +
      badge(g ? "Grade " + g : "Grade —", g === "D" ? "br" : g === "C" ? "by" : "bg") +
      "</span>";
  }
  function toolHtml(s) {
    return '<input class="symbox" id="jump" aria-label="Symbol" value="' + esc(s ? s.ticker : state.symbol) + '">' +
      '<button type="button" data-act="tf" data-tf="D" class="' + (state.tf === "D" ? "on" : "") + '">D</button>' +
      '<button type="button" data-act="tf" data-tf="W" class="' + (state.tf === "W" ? "on" : "") + '">W</button>' +
      '<button type="button" data-act="marks" class="' + (state.marksOn ? "on" : "") + '">Earnings</button>' +
      '<button type="button" id="actions" data-act="actions" aria-haspopup="menu" aria-expanded="' + (state.menuOpen ? "true" : "false") + '">Actions</button>' +
      '<button type="button" data-act="right" data-tab="summary">Summary</button>';
  }
  function earnHtml(s) {
    const rows = (state.earnings[s.ticker] || []).filter((r) => r.eps_actual).slice().sort((a, b) => a.earnings_date < b.earnings_date ? 1 : -1).slice(0, 4);
    const next = state.calendar[s.ticker];
    const bits = rows.map((r) => "<span><b>" + esc(r.earnings_date) + "</b> EPS " + esc(r.eps_actual) + (r.surprise_pct ? " (" + esc(r.surprise_pct) + "% vs estimate)" : "") + "</span>");
    if (next && next.next_earnings) bits.push("<span>Next stored date <b>" + esc(next.next_earnings) + "</b></span>");
    bits.push("<span>Quarterly sales are not in the stored files.</span>");
    return bits.join("");
  }
  function planHtml(s) {
    const sc = s.score || {};
    const lines = [];
    lines.push("Our buy point is the highest high of the prior 20 sessions, which excludes today" + (E.finite(s.pivot20) ? ": " + px(s.pivot20) + "." : ". It is unavailable.") );
    if (s.patterns && s.patterns.near && E.finite(s.patterns.near.dist)) lines.push("The close is " + pct(-s.patterns.near.dist, 2) + " versus that high.");
    if (s.vcp && s.vcp.candidate) lines.push("Tight base / VCP candidate, " + s.vcp.count + " contraction" + (s.vcp.count === 1 ? "" : "s") + ", pivot " + px(s.vcp.pivot) + ". " + (s.vcp.brokenOut ? "Flagged: the close is above that pivot. " : "") + s.vcp.reason);
    else if (s.vcp) lines.push((s.vcp.count ? s.vcp.count + " contraction" + (s.vcp.count === 1 ? "" : "s") + ". " : "") + s.vcp.reason);
    if (num(sc.entry_low) != null || num(sc.stop) != null) {
      lines.push("Stock box plan, unchanged from the desk file: entry " + px(num(sc.entry_low)) + "–" + px(num(sc.entry_high)) + ", stop " + px(num(sc.stop)) + ", target " + px(num(sc.trade_target)) + ". Amber is that entry, red is that stop, green is that target. The indigo line is our 20-session high.");
    } else lines.push("This symbol has no stock-box entry and stop on the score file, so those lines are not drawn.");
    lines.push("No stop is suggested from a payoff ratio.");
    return lines.map((t) => "<p>" + esc(t) + "</p>").join("");
  }
  function summaryHtml(s) {
    const sum = E.summarize(s);
    const role = s.role ? "<p class=\"note\">" + esc(s.company) + ". " + esc(s.role) + ". " + esc(s.note || "") + " Stock screens do not apply. This is not a SPY 25, QQQ 33, or STEM reading.</p>" : "";
    const today = s.recent.length ? s.recent[s.recent.length - 1] : null;
    return '<h3>' + esc(s.ticker) + " summary</h3><p class=\"note\">Computed from stored bars through " + esc(s.date) + ". Not a language model.</p>" + role + '<div class="story"><p>' + esc(sum.text) + "</p>" +
      (today ? "<p>" + chips(today.events) + "</p>" : "") + planHtml(s) + "</div>";
  }
  function newsHtml(s) {
    const rows = state.news.filter((r) => String(r.ticker || "").toUpperCase() === s.ticker);
    const next = state.calendar[s.ticker];
    let html = "<h3>" + esc(s.ticker) + " news</h3>";
    if (next && next.next_earnings) html += '<p class="note">Next earnings date on file: ' + esc(next.next_earnings) + (next.when_hint ? " · " + esc(next.when_hint) : "") + ".</p>";
    if (!rows.length) html += '<p class="note">No stored headline for this symbol. Nothing is invented to fill the gap.</p>';
    else html += rows.slice(0, 8).map((r) => '<div class="newsitem"><a href="' + esc(r.link || "#") + '" target="_blank" rel="noopener noreferrer">' + esc(r.headline || "Headline") + "</a><div class=\"mut\">" + esc(r.publisher || "") + " · " + esc(r.published || "") + "</div><p>" + esc(r.summary || "") + "</p></div>").join("");
    return html;
  }
  function rightAlerts(s) {
    const blocks = s.recent.slice(-state.alertDays).slice().reverse();
    if (!blocks.length) return '<p class="note">No stored sessions to score.</p>';
    return blocks.map((block) => '<div class="newsitem"><div class="ph" style="padding:0"><b>' + esc(block.date) + '</b><span class="' + (block.net < 0 ? "dn" : "up") + '">Net ' + (block.net > 0 ? "+" : "") + block.net + "</span></div>" +
      (block.events.length ? chips(block.events) : '<span class="mut">No named sign this session.</span>') + "</div>").join("");
  }
  function rightHtml(s) {
    if (!s) return '<div class="pad note">Choose a symbol.</div>';
    if (state.right === "watch") return '<div class="pad"><button type="button" class="btn" data-act="add" data-list="n360-watch">Add ' + esc(s.ticker) + " to watchlist</button></div>" + listHtml("watch");
    if (state.right === "news") return '<div class="rightbody">' + newsHtml(s) + "</div>";
    if (state.right === "summary") return '<div class="rightbody">' + summaryHtml(s) + "</div>";
    return '<div class="rightbody"><h3>' + esc(s.ticker) + " alerts</h3><p class=\"note\">Last " + state.alertDays + " stored sessions. Dates are the bar dates.</p>" + rightAlerts(s) + "</div>";
  }
  function chartingHtml() {
    const s = current();
    const tabs = [["portfolio", "Portfolio"], ["watch", "Watchlist"], ["screens", "Screens"], ["alerts", "Alert Report"]];
    const rt = [["alerts", "Alerts"], ["watch", "Watchlist"], ["news", "News"], ["summary", "Summary"]];
    return '<div class="workspace"><section class="pnl left"><div class="tabs">' + tabs.map((t) => '<button type="button" data-act="left" data-tab="' + t[0] + '" class="' + (state.left === t[0] ? "on" : "") + '">' + t[1] + "</button>").join("") + "</div>" + leftHtml() +
      '</section><section class="pnl center"><div class="quote">' + (s ? quoteHtml(s) : "Choose a symbol") + '</div><div class="tool">' + toolHtml(s) + '</div><div class="chartwrap"><canvas id="cv" aria-label="Daily chart"></canvas></div><div class="ranges">' +
      RANGES.map((r) => '<button type="button" data-act="range" data-range="' + r + '" class="' + (state.range === r ? "on" : "") + '">' + r.toLowerCase() + "</button>").join("") +
      '</div><div class="earn">' + (s ? earnHtml(s) : "") + "</div></section><section class=\"pnl right\"><div class=\"tabs\">" +
      rt.map((t) => '<button type="button" data-act="right" data-tab="' + t[0] + '" class="' + (state.right === t[0] ? "on" : "") + '">' + t[1] + "</button>").join("") + "</div>" + rightHtml(s) + "</section></div>";
  }

  function noteList() {
    const regime = E.regimeFromMarket(state.market || {});
    const notes = [];
    if (regime.status === "ok") notes.push("Breadth above the 50-day is " + regime.b50 + "%. Above the 200-day is " + regime.b200 + "%.");
    else notes.push(regime.reason);
    if (regime.adv != null && regime.dec != null) notes.push("Advancers " + regime.adv + ", decliners " + regime.dec + ".");
    if (regime.spyDay != null) notes.push("Stored SPY day move " + regime.spyDay.toFixed(2) + "%. This is the desk's published day figure, not a timing model.");
    if (regime.qqqDay != null) notes.push("Stored QQQ day move " + regime.qqqDay.toFixed(2) + "%.");
    const template = state.desk.screens.find((s) => s.id === "template");
    const gradeA = state.desk.screens.find((s) => s.id === "gradeA");
    if (template && template.matches) notes.push("Trend template matches: " + template.matches.length + ". Not evaluated: " + template.skipped + ".");
    if (gradeA && gradeA.matches) notes.push("Grade A: " + gradeA.matches.length + ".");
    const dated = state.news.map((r) => r.published).filter(Boolean).sort();
    if (dated.length) notes.push("Newest stored headline time: " + dated[dated.length - 1] + ".");
    else notes.push("No stored headlines in news.csv.");
    const fills = loadPaper().filter((f) => f.date === (state.meta.price_as_of || ""));
    if (fills.length) notes.push("Your paper log has " + fills.length + " fill(s) on the price date.");
    return notes;
  }
  function indexCards() {
    const mans = state.manifest || [];
    const gaps = mans.filter((r) => r.role === "unavailable");
    let cards = "";
    if (state.indexes) state.indexes.forEach((s) => {
      const t = s.indexTrend || E.indexTrend(s);
      cards += '<section class="card"><h3>' + esc(s.ticker) + " <small>" + esc(s.role) + '</small></h3><div class="big">' + px(s.close) + "</div><p class=\"note\">" +
        (t.day == null ? "Day —" : pct(t.day, 2)) + " · 50-day " + (t.above50 == null ? "—" : t.above50 ? "above" : "below") +
        " · 200-day " + (t.above200 == null ? "—" : t.above200 ? "above" : "below") +
        (t.higherVolume == null ? " · volume blank, not zero" : " · volume " + (t.higherVolume ? "above" : "not above") + " the prior day") +
        "</p><p class=\"note\">" + esc(s.note || "") + "</p></section>";
    });
    const gap = gaps.length ? '<section class="card"><h3>Index gaps</h3><p class="note">' + gaps.map((r) => "<b>" + esc(r.symbol) + "</b> " + esc(r.note)).join(" ") + "</p></section>" : "";
    if (!cards && !gap) return "";
    return '<div class="dash">' + cards + gap + "</div>";
  }

  function dashHtml() {
    const regime = E.regimeFromMarket(state.market || {});
    const hint = stats().stopHint;
    const book = stats();
    const groups = [["full", "Full positions"], ["half", "Half positions"], ["quarter", "Quarter positions"], ["other", "Unclassified"]];
    const with252 = state.desk.stocks.filter((s) => s.bars.length >= 252).length;
    const stale = state.desk.stocks.filter((s) => s.stale).length;
    const port = groups.map((g) => {
      const rows = book.groups[g[0]];
      if (!rows.length) return "";
      return '<tr class="band"><td colspan="12">' + g[1] + " (" + rows.length + ")</td></tr>" + rows.map((row) => {
        const s = state.by.get(row.ticker);
        const bag = s ? aggregated(s) : { pos: [], neg: [] };
        return "<tr><td><button type=\"button\" data-act=\"pick\" data-ticker=\"" + esc(row.ticker) + "\">" + esc(row.ticker) + "</button></td><td class=\"" + (s && s.chg < 0 ? "dn" : "up") + "\">" + (s ? pct(s.chg, 2) : "—") +
          "</td><td>" + px(row.last) + "</td><td>" + (s && E.finite(rankOf(s)) ? rankOf(s) : "—") + "</td><td>" + esc(s ? gradeLetter(s) || "—" : "—") + "</td><td>" + esc(row.date) + "</td><td>" + px(row.avg) +
          "</td><td>" + px(row.stop) + "</td><td>" + pct(row.stopPct, 1) + "</td><td class=\"" + (row.pnlPct < 0 ? "dn" : "up") + "\">" + pct(row.pnlPct, 1) + "</td><td>" + (E.finite(row.r) ? row.r.toFixed(1) : "—") +
          "</td><td>" + bag.pos.length + " / " + bag.neg.length + "</td></tr>";
      }).join("");
    }).join("");
    return '<div class="page">' + indexCards() + '<div class="dash"><section class="card"><h3>Market status <small>Our regime</small></h3><div class="big ' + (regime.label === "DEFENSIVE" ? "dn" : regime.label === "UPTREND" ? "up" : "") + '">' + esc(regime.label) + "</div><p class=\"note\">" + esc(regime.reason || regime.note) + "</p><p class=\"note\">" + esc(regime.note) + "</p></section>" +
      '<section class="card"><h3>From your paper log <small>not a universal stop</small></h3>' + (hint.available ? '<div class="big">' + pct(hint.pct, 1) + "</div>" : '<div class="big mut">—</div>') + '<p class="note">' + esc(hint.reason) + "</p></section>" +
      '<section class="card"><h3>Desk notes <small>stored facts</small></h3>' + noteList().map((n) => '<p class="note">' + esc(n) + "</p>").join("") + "</section></div>" +
      '<div class="split2"><section class="card"><h3>Paper portfolio <small>this browser only</small></h3>' + (port ? '<div class="scroll"><table><thead><tr><th>Symbol</th><th>Chg</th><th>Last</th><th>Rank</th><th>Grade</th><th>Entry</th><th>Avg cost</th><th>Stop</th><th>Stop %</th><th>P&amp;L %</th><th>R</th><th>Alerts</th></tr></thead><tbody>' + port + "</tbody></table></div>" : '<p class="note">No paper positions yet. Groups appear when a fill is marked full, half, or quarter. Unmarked fills stay under Unclassified. No stop is filled in for you.</p>') +
      '<p class="note">Coverage: ' + state.desk.stocks.length + " symbols, " + with252 + " with 252 sessions, " + state.missing + " files missing, " + stale + " older than " + esc(state.meta.price_as_of || "the desk date") + ".</p></section>" +
      '<section class="card"><h3>Focus list <small>this browser</small></h3>' + focusTable() + "</section></div></div>";
  }
  function focusTable() {
    const focus = loadList("n360-focus");
    return '<form id="focusadd" class="form" style="grid-template-columns:1fr auto;margin-bottom:8px"><label>Symbol<input name="ticker" aria-label="Focus symbol"></label><button class="btn" type="submit">Add</button></form>' +
      (focus.length ? '<table><thead><tr><th>Symbol</th><th>Last</th><th>Rank</th><th>Grade</th><th>Entry risk</th><th>Note</th><th></th></tr></thead><tbody>' + focus.map((row) => {
        const s = state.by.get(row.ticker);
        const risk = s && s.last >= 0 ? s.risk[s.last] : null;
        return "<tr><td><button type=\"button\" data-act=\"pick\" data-ticker=\"" + esc(row.ticker) + "\">" + esc(row.ticker) + "</button></td><td>" + (s ? px(s.close) : "—") + "</td><td>" + (s && E.finite(rankOf(s)) ? rankOf(s) : "—") + "</td><td>" + esc(s ? gradeLetter(s) || "—" : "—") + "</td><td>" + (risk ? esc(risk.color) : "—") + "</td><td>" + esc(row.note || "") + '</td><td><button type="button" data-act="remove" data-list="n360-focus" data-ticker="' + esc(row.ticker) + '">Remove</button></td></tr>';
      }).join("") + "</tbody></table>" : '<p class="note">No focus names yet. Add a symbol here or from Actions on a chart. Saved in this browser only.</p>');
  }
  function focusHtml() {
    return '<div class="page"><section class="card"><h3>Focus list <small>saved in this browser only</small></h3><p class="note">Names you want within reach. This is not synced to another device.</p>' + focusTable() + "</section></div>";
  }
  function feedbackHtml(trade, bars) {
    const graded = E.gradeTrade({
      side: "long", entry: trade.entry, exit: trade.exit, stop: trade.stop, pivot: trade.pivot,
      entryDate: trade.entryDate, exitDate: trade.exitDate,
    }, bars);
    return graded.notes.map((n) => '<p class="' + (n.tone === "pos" ? "up" : n.tone === "neg" ? "dn" : "note") + '">' + esc(n.text) + "</p>").join("");
  }
  function graderHtml() {
    const paper = loadPaper();
    const missed = loadMissed();
    const book = E.roundTrips(paper);
    const symbols = {};
    paper.forEach((f) => { symbols[f.ticker] = (symbols[f.ticker] || 0) + 1; });
    missed.forEach((f) => { symbols[f.ticker] = symbols[f.ticker] || 0; });
    const names = Object.keys(symbols).sort();
    const s = current();
    const closedHere = book.closed.filter((t) => t.ticker === state.symbol);
    const openHere = book.open.filter((t) => t.ticker === state.symbol);
    const missedHere = missed.filter((t) => t.ticker === state.symbol);
    const bars = s ? s.bars : [];
    const check = s ? checklist(s) : "";
    return '<div class="two"><section class="pnl lib"><div class="ph">Trade library <button type="button" class="' + (state.grader === "check" ? "on" : "") + '" data-act="gmode" data-mode="' + (state.grader === "check" ? "trades" : "check") + '">' + (state.grader === "check" ? "Trades" : "Checklist") + "</button></div>" +
      (names.length ? names.map((t) => '<button type="button" class="' + (t === state.symbol ? "sel" : "") + '" data-act="pick" data-ticker="' + esc(t) + '"><b>' + esc(t) + "</b><div class=\"mut\">" + symbols[t] + " fills</div></button>").join("") : '<p class="pad note">No paper fills yet.</p>') +
      '<div class="pad"><button type="button" class="btn" data-act="modal" data-modal="trade">Add fill</button> <button type="button" class="btn ghost" data-act="modal" data-modal="missed">Log a miss</button></div></section>' +
      (state.grader === "check" ? '<section class="pnl"><div class="pad"><h3>Stock checklist</h3><p class="note">Pass, fail, or missing for ' + esc(state.symbol || "the selected symbol") + ". Missing is not a fail.</p>" + check + "</div></section>" : '<section class="pnl"><div class="chartwrap" style="min-height:calc(100vh - 140px)"><canvas id="gcv" aria-label="Trade review chart"></canvas></div></section>') +
      '<section class="pnl"><div class="pad"><p class="note">Grades use the entry, exit, stop, and pivot you typed. A 2R note only looks at bars between those dates and is not a live screen.</p>' +
      "<h3>Graded " + closedHere.filter((t) => t.exit).length + "</h3>" + (closedHere.length ? closedHere.map((t) => "<div class=\"newsitem\"><b>" + esc(t.entryDate) + " → " + esc(t.exitDate) + "</b> " + px(t.entry) + " to " + px(t.exit) + feedbackHtml(t, bars) + "</div>").join("") : '<p class="note">No closed round trip for this symbol.</p>') +
      "<h3>Missed " + missedHere.length + "</h3>" + (missedHere.length ? missedHere.map((m) => {
        const measured = s ? E.missedResult(m, s.bars) : { available: false, reason: "No stored bars." };
        return "<div class=\"newsitem\"><b>" + esc(m.date) + "</b> " + esc(m.note || "") + "<p class=\"note\">" + (measured.available ? pct(measured.pct, 1) + " from " + esc(measured.from) + " to " + esc(measured.to) + ". " : "") + esc(measured.reason) + "</p></div>";
      }).join("") : '<p class="note">No missed names logged.</p>') +
      "<h3>Ungraded " + openHere.length + "</h3>" + (openHere.length ? openHere.map((t) => "<p>" + esc(t.date) + " buy " + t.shares + " @ " + px(t.price) + " still open.</p>").join("") : '<p class="note">No open lots.</p>') +
      '<p class="note">Long paper lots only. Short sales are not tracked, and this desk sends no orders.</p></div></section></div>';
  }
  function checklist(s) {
    const items = (s.template.items || []).concat((s.grade[s.last] && s.grade[s.last].checks) || []);
    items.push({ label: "Stage", state: s.stage.stage ? "pass" : "missing", detail: s.stage.stage ? "Stage " + s.stage.stage : s.stage.reason });
    const risk = s.risk[s.last];
    items.push({ label: "Entry risk", state: risk ? "pass" : "missing", detail: risk ? risk.label : "50-day average missing" });
    const p = s.pressure[s.last];
    items.push({ label: "Pressure", state: p ? "pass" : "missing", detail: p ? p.color + ", " + (p.buy * 100).toFixed(1) + "% up-volume" : "20-session volume missing" });
    return '<div class="checks">' + items.map((item) => '<div class="check"><span>' + esc(item.label) + (item.detail ? " — " + esc(item.detail) : "") + '</span><span class="' + (item.state === "pass" ? "pass" : item.state === "fail" ? "fail" : "miss") + '">' + esc(item.state) + "</span></div>").join("") + "</div>";
  }
  function kpi(label, value, cls) {
    return '<section class="card"><div class="mut">' + label + '</div><div class="big ' + (cls || "") + '">' + value + "</div></section>";
  }
  function analyticsHtml() {
    const book = stats();
    const bins = book.bins ? book.bins.rows.filter((r) => r.gains || r.losses || (r.lo >= 0 && r.lo < 36)) : [];
    const hold = book.avgHold == null ? "—" : book.avgHold.toFixed(1) + " days" + (book.avgHoldWins != null ? " (wins " + book.avgHoldWins.toFixed(1) + (book.avgHoldLosses != null ? " · losses " + book.avgHoldLosses.toFixed(1) : "") + ")" : "");
    return '<div class="page"><div class="btns"><button type="button" data-act="forecast">Send to forecast</button><button type="button" data-act="export">Export</button><label class="btn ghost" style="display:inline-flex;align-items:center">Import<input id="importf" type="file" accept="application/json" hidden></label><button type="button" data-act="clear" class="ghost">Clear</button><button type="button" data-act="cap" class="' + (state.cap ? "on" : "ghost") + '">Cap losses at 10%</button><button type="button" data-act="modal" data-modal="trade">Add fill</button></div>' +
      (state.cap || state.lossShift ? '<p class="warn">Scenario is on. Stored fills are unchanged.' + (state.cap ? " Losses are capped at −10% in these figures." : "") + (state.lossShift ? " Each loss is eased by " + (state.lossShift * 100).toFixed(1) + " points." : "") + "</p>" : "") +
      '<div class="kpis">' +
      kpi("Closed trades", book.closedN ? String(book.closedN) : "—") +
      kpi("Batting average", book.batting == null ? "—" : (book.batting * 100).toFixed(1) + "%") +
      kpi("Average gain", book.avgGain == null ? "—" : pct(book.avgGain, 2), "up") +
      kpi("Average loss", book.avgLoss == null ? "—" : pct(book.avgLoss, 2), "dn") +
      kpi("Win/loss count", book.countRatio == null ? "—" : book.countRatio.toFixed(2)) +
      kpi("Payoff ratio", book.payoff == null ? "—" : book.payoff.toFixed(2)) +
      kpi("Expectancy", book.expectancy == null ? "—" : pct(book.expectancy, 2)) +
      kpi("Avg hold", hold) +
      kpi("Exposure", book.exposure == null ? "—" : (book.exposure * 100).toFixed(0) + "%") +
      kpi("Cash", book.cash == null ? "—" : "$" + book.cash.toFixed(0)) +
      kpi("Equity (paper)", book.equity == null ? "—" : "$" + book.equity.toFixed(0)) +
      kpi("YTD realized", book.ytdN ? "$" + book.ytdPnl.toFixed(0) : "—", book.ytdPnl > 0 ? "up" : "dn") +
      "</div><p class=\"note\">YTD is the sum of closed-trade dollars with an exit in " + esc(String((state.meta.price_as_of || "")).slice(0, 4) || "the desk year") + ". Drawdown on the realized cash path" + (book.drawdown == null ? " needs a starting cash balance." : " is " + pct(book.drawdown, 1) + ".") + " Mean expectancy is not a forecast. " + esc(book.cashWarning || "") + "</p>" +
      '<div class="form"><label>Starting cash<input id="cash" inputmode="decimal" value="' + (loadCash() == null ? "" : loadCash()) + '"></label><label>Ease each loss by points<input id="shift" inputmode="decimal" value="' + (state.lossShift ? state.lossShift * 100 : "") + '"></label><button type="button" class="btn ghost" data-act="applyshift">Apply scenario</button><button type="button" class="btn" data-act="savecash">Save cash</button></div>' +
      '<div class="split2"><section class="card"><h3>Gains and losses <small>per closed trade</small></h3><canvas class="mini" id="gl"></canvas><div class="split2"><div><h3>Gain magnitude</h3><canvas class="mini" id="gmag"></canvas></div><div><h3>Loss magnitude</h3><canvas class="mini" id="lmag"></canvas></div></div></section>' +
      '<section class="card"><h3>Return by size range <small>our bin math, not a third-party tool</small></h3><div class="scroll"><table><thead><tr><th>Range</th><th># Gains</th><th># Losses</th><th>% up</th><th>% down</th><th>Net</th><th>Contribution</th></tr></thead><tbody>' +
      bins.map((r) => "<tr><td>" + esc(r.label) + "</td><td>" + r.gains + "</td><td>" + r.losses + "</td><td class=\"up\">" + (r.up * 100).toFixed(0) + "%</td><td class=\"dn\">" + (r.down * 100).toFixed(0) + "%</td><td>" + (r.net * 100).toFixed(0) + "%</td><td>" + r.contribution.toFixed(2) + "</td></tr>").join("") +
      "</tbody></table></div><p class=\"note\">Contribution = bin midpoint in percent points × (gains − losses) / closed trades. Empty bins are zeros because no fill landed there.</p></section></div>" +
      calculators() + '<p id="calcmsg" class="note"></p></div>';
  }
  function calculators() {
    return '<div class="split2"><section class="card" id="riskbox"><h3>Position size</h3><div class="form"><label>Account<input id="eq" inputmode="decimal"></label><label>Entry<input id="en" inputmode="decimal"></label><label>Stop<input id="st" inputmode="decimal"></label><label>Risk %<input id="rk" inputmode="decimal" value="1"></label><label>Fee / share<input id="fee" inputmode="decimal" value="0"></label><button type="button" class="btn" data-act="size">Size</button></div><p id="sizemsg" class="note"></p></section>' +
      '<section class="card"><h3>Partial sale to cover the stop</h3><div class="form"><label>Entry<input id="se" inputmode="decimal"></label><label>Stop<input id="ss" inputmode="decimal"></label><label>Sale<input id="sp" inputmode="decimal"></label><label>Shares<input id="sh" inputmode="decimal"></label><label>Fee / share<input id="sf" inputmode="decimal" value="0"></label><button type="button" class="btn" data-act="sbe">Calculate</button></div><p id="sbemsg" class="note"></p></section></div>' +
      '<section class="card" id="rbaf"><h3>Scenario trade count</h3><p class="note">Linear form matches the quoted 25 / 40 / 14 / 7 / 46 example at about 60 trades. Compounding the same inputs does not. Neither is a forecast. A non-positive edge returns no count.</p><div class="form"><label>Size %<input id="sz" value="25"></label><label>Target %<input id="tg" value="40"></label><label>Avg gain %<input id="ag" value="14"></label><label>Avg loss %<input id="al" value="7"></label><label>Win %<input id="wn" value="46"></label><label>Fee %<input id="fe" value="0"></label><button type="button" class="btn" data-act="rbaf">Run scenario</button></div><p id="rbafmsg" class="note"></p></section>';
  }

  function footer() {
    const regime = state.desk ? E.regimeFromMarket(state.market || {}) : null;
    const asof = (state.meta && state.meta.price_as_of) || "";
    document.getElementById("foot").innerHTML = '<span><i class="dot ' + (state.error ? "dr" : state.ready ? "dg" : "dy") + '"></i>' + (regime && regime.label ? esc(regime.label) : "Regime —") + "</span>" +
      "<span>Signals only · no trading · not a broker</span><span>Our version · no third-party affiliation</span>" +
      '<span class="rt">' + (asof ? "Stored through " + esc(asof) : "") + " · " + (state.ready ? "FILES LOADED" : "LOADING") + "</span>";
  }
  function banner() {
    const host = document.getElementById("status");
    if (state.error) { host.className = "statusline"; host.textContent = state.error; return; }
    const s = current();
    if (state.ready && s && s.stale) {
      host.className = "statusline";
      host.textContent = s.ticker + " last bar " + s.date + " is older than the desk price date " + (state.meta.price_as_of || "") + ". Figures use that file. This is not a live quote.";
      return;
    }
    host.className = "";
    host.textContent = "";
  }
  function render() {
    document.querySelectorAll("#n360 nav button").forEach((btn) => {
      btn.setAttribute("aria-current", btn.getAttribute("data-page") === state.page ? "page" : "false");
    });
    if (!state.ready) {
      view.innerHTML = '<div class="page"><div class="card load"><h3>' + esc(state.phase) + '</h3><div class="bar"><i style="width:' + Math.round(state.progress * 100) + '%"></i></div><p class="note">Reading the OHLC files already published for the chart viewer. No new download is requested.</p></div></div>';
      footer();
      return;
    }
    if (state.page === "dashboard") view.innerHTML = dashHtml();
    else if (state.page === "focus") view.innerHTML = focusHtml();
    else if (state.page === "grader") view.innerHTML = graderHtml();
    else if (state.page === "analytics") view.innerHTML = analyticsHtml();
    else view.innerHTML = chartingHtml();
    banner();
    footer();
    const q = document.getElementById("qsym");
    if (q) q.value = state.query;
    requestAnimationFrame(() => requestAnimationFrame(drawActive));
  }

  function openMenu(x, y) {
    const menu = document.getElementById("menu");
    const items = [
      ["Summary", "summary"],
      ["News", "news"],
      ["Toggle earnings marks", "marks"],
      ["Reset view", "reset"],
      ["Copy last price", "copy"],
      ["Add to focus list", "focus"],
      ["Add to watchlist", "watch"],
      ["Log a paper buy", "trade"],
    ];
    menu.className = "menu";
    menu.hidden = false;
    menu.innerHTML = items.map((item, i) => '<button type="button" role="menuitem" data-act="menu" data-item="' + item[1] + '"' + (i === 0 ? " id=\"menufirst\"" : "") + ">" + item[0] + "</button>").join("");
    menu.style.left = Math.max(8, Math.min(window.innerWidth - 240, x)) + "px";
    menu.style.top = Math.max(8, Math.min(window.innerHeight - 280, y)) + "px";
    state.menuOpen = true;
    const first = document.getElementById("menufirst");
    if (first) first.focus();
  }
  function hideMenu() {
    const menu = document.getElementById("menu");
    menu.hidden = true;
    menu.innerHTML = "";
    state.menuOpen = false;
  }
  function openModal(kind) {
    const host = document.getElementById("modal");
    host.className = "modalbg";
    host.hidden = false;
    const ticker = state.symbol || "";
    if (kind === "missed") {
      host.innerHTML = '<div class="modal" role="dialog" aria-modal="true"><h3>Log a name you did not buy</h3><div class="form"><label>Symbol<input id="mt" value="' + esc(ticker) + '"></label><label>Date<input id="md" type="date"></label><label>Note<input id="mn"></label></div><p class="note">The later price change is measured after this date and is labeled as such. It does not enter a live screen.</p><div class="btns"><button type="button" class="btn" data-act="savemissed">Save</button><button type="button" class="btn ghost" data-act="closemodal">Close</button></div></div>';
      return;
    }
    if (kind === "defs") {
      host.innerHTML = '<div class="modal" role="dialog" aria-modal="true"><h3>Definitions</h3><div class="scroll" style="max-height:70vh"><table><thead><tr><th>Reference</th><th>Our name</th><th>Status</th><th>Formula</th></tr></thead><tbody>' +
        E.COVERAGE.map((c) => "<tr><td>" + esc(c.ref) + "</td><td>" + esc(c.ourName) + "</td><td>" + esc(c.status) + "</td><td>" + esc(c.formula) + " " + esc(c.evidence) + "</td></tr>").join("") +
        '</tbody></table></div><button type="button" class="btn" data-act="closemodal">Close</button></div>';
      return;
    }
    host.innerHTML = '<div class="modal" role="dialog" aria-modal="true"><h3>Paper fill</h3><div class="form"><label>Symbol<input id="pt" value="' + esc(ticker) + '"></label><label>Date<input id="pd" type="date"></label><label>Side<select id="pside"><option value="buy">Buy</option><option value="sell">Sell</option></select></label><label>Shares<input id="psh" inputmode="decimal"></label><label>Price<input id="pp" inputmode="decimal"></label><label>Fee $<input id="pf" inputmode="decimal" value="0"></label><label>Stop<input id="pst" inputmode="decimal"></label><label>Pivot<input id="ppv" inputmode="decimal"></label><label>Size<select id="psz"><option value="">Unclassified</option><option value="full">Full</option><option value="half">Half</option><option value="quarter">Quarter</option></select></label><label>Note<input id="pn"></label></div><p id="pmsg" class="note">Stored in this browser only. Selling more than you hold is rejected.</p><div class="btns"><button type="button" class="btn" data-act="savefill">Save fill</button><button type="button" class="btn ghost" data-act="closemodal">Close</button></div></div>';
  }
  function hideModal() {
    const host = document.getElementById("modal");
    host.hidden = true;
    host.className = "";
    host.innerHTML = "";
  }
  function addList(key, ticker) {
    ticker = String(ticker || "").toUpperCase();
    if (!ticker) return;
    const list = loadList(key);
    if (!list.some((row) => row.ticker === ticker)) list.push({ ticker: ticker, note: "", added: (state.meta.price_as_of || "") });
    store(key, list);
  }
  function removeList(key, ticker) {
    store(key, loadList(key).filter((row) => row.ticker !== ticker));
  }

  async function boot() {
    readHash();
    try {
      const packed = await Promise.all([
        loadCsv("scores.csv"),
        loadCsv("nick360/listings.csv").catch(() => []),
        loadCsv("index_ohlc/manifest.csv").catch(() => []),
        fetch(csvUrl("meta.json")).then((r) => r.json()),
        loadCsv("market_today.csv"),
        loadCsv("news.csv"),
        loadCsv("earnings_history.csv"),
        loadCsv("earnings_calendar.csv"),
      ]);
      const scores = packed[0];
      const listings = packed[1] || [];
      const manifest = packed[2] || [];
      state.meta = packed[3] || {};
      state.market = (packed[4] && packed[4][0]) || {};
      state.news = packed[5] || [];
      (packed[6] || []).forEach((row) => {
        const t = String(row.ticker || "").toUpperCase();
        if (!t) return;
        if (!state.earnings[t]) state.earnings[t] = [];
        state.earnings[t].push(row);
      });
      (packed[7] || []).forEach((row) => {
        const t = String(row.ticker || "").toUpperCase();
        if (t) state.calendar[t] = row;
      });
      state.manifest = manifest;
      state.listingRows = listings;
      const scoreBy = new Map();
      scores.forEach((row) => {
        const t = String(row.ticker || "").toUpperCase();
        if (t) scoreBy.set(t, row);
      });
      const tickers = Array.from(scoreBy.keys());
      const records = [];
      let done = 0;
      const workers = 8;
      let cursor = 0;
      async function worker() {
        while (cursor < tickers.length) {
          const t = tickers[cursor++];
          try {
            const res = await fetch(csvUrl("ohlc/" + t + ".csv"));
            if (!res.ok) { state.missing += 1; }
            else {
              const text = await res.text();
              const row = scoreBy.get(t);
              records.push({ ticker: t, company: row.company || "", sector: row.sector || "", score: row, bars: parseOhlc(text) });
            }
          } catch (err) { state.missing += 1; }
          done += 1;
          if (done % 20 === 0 || done === tickers.length) {
            state.progress = done / tickers.length;
            state.phase = "Reading stored bars " + done + " / " + tickers.length;
            render();
            await delay(0);
          }
        }
      }
      await Promise.all(Array.from({ length: workers }, worker));
      state.phase = "Calculating ranks";
      state.progress = 1;
      render();
      await delay(20);
      const listingMap = {};
      listings.forEach((row) => {
        const t = String(row.ticker || "").toUpperCase();
        if (!t) return;
        listingMap[t] = { offerDate: row.offer_date, name: row.ipo_name, adr: row.adr, source: row.source, dateKind: row.date_kind, note: row.note };
      });
      const desk = E.buildDesk(records, state.meta, listingMap);
      state.indexes = new Map();
      for (let i = 0; i < manifest.length; i++) {
        const row = manifest[i];
        if (!row.symbol || row.role === "unavailable") continue;
        try {
          const res = await fetch(csvUrl("index_ohlc/" + row.symbol + ".csv"));
          if (!res.ok) continue;
          const parsed = E.parseBars(parseOhlc(await res.text()));
          const series = E.analyzeBars(parsed.bars);
          E.finalizeStock(series, state.meta);
          series.ticker = row.symbol;
          series.company = row.name || row.symbol;
          series.role = row.role;
          series.note = row.note || "";
          series.indexTrend = E.indexTrend(series);
          state.indexes.set(row.symbol, series);
        } catch (err) { /* one series missing does not stop the desk */ }
      }
      if (!records.length) throw new Error("None of the published OHLC files could be read.");
      state.desk = desk;
      desk.stocks.forEach((s) => state.by.set(s.ticker, s));
      if (!state.symbol || !state.by.has(state.symbol)) {
        const first = desk.screens.find((s) => s.matches && s.matches.length);
        state.symbol = first ? first.matches[0] : (desk.stocks[0] ? desk.stocks[0].ticker : "");
      }
      const open = desk.screens.find((s) => s.matches && s.matches.length);
      if (open) state.open[open.id] = true;
      state.ready = true;
      root.setAttribute("data-ready", "1");
      const flag = document.createElement("div");
      flag.id = "n360-ready";
      flag.hidden = true;
      root.appendChild(flag);
      setHash();
      render();
    } catch (err) {
      state.error = "Nick 360 could not read the stored desk files. " + (err && err.message ? err.message : "");
      render();
    }
  }

  let press = null;
  root.addEventListener("pointerdown", (e) => {
    if (e.target.id !== "cv" && e.target.id !== "gcv") return;
    press = setTimeout(() => openMenu(e.clientX, e.clientY), 550);
  });
  root.addEventListener("pointerup", () => clearTimeout(press));
  root.addEventListener("pointermove", (e) => {
    if (e.target.id !== "cv" || !state.geom) return;
    const rect = e.target.getBoundingClientRect();
    const idx = state.geom.indexAt(e.clientX - rect.left);
    if (idx !== state.hover) {
      state.hover = idx;
      drawActive();
    }
  });
  root.addEventListener("contextmenu", (e) => {
    if (e.target.id !== "cv" && e.target.id !== "gcv") return;
    e.preventDefault();
    openMenu(e.clientX, e.clientY);
  });
  root.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { hideMenu(); hideModal(); }
    if (e.key === "ContextMenu" || (e.key === "F10" && e.shiftKey)) {
      const btn = document.getElementById("actions");
      if (!btn) return;
      const r = btn.getBoundingClientRect();
      openMenu(r.left, r.bottom);
      e.preventDefault();
    }
    if (!state.menuOpen) return;
    const items = Array.from(document.querySelectorAll("#menu button"));
    const i = items.indexOf(document.activeElement);
    if (e.key === "ArrowDown") { items[(i + 1) % items.length].focus(); e.preventDefault(); }
    if (e.key === "ArrowUp") { items[(i - 1 + items.length) % items.length].focus(); e.preventDefault(); }
  });
  root.addEventListener("change", (e) => {
    if (e.target.id === "adays") { state.alertDays = Number(e.target.value); render(); }
    if (e.target.id === "importf" && e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      file.text().then((text) => {
        const data = JSON.parse(text);
        if (data.paper) store("n360-paper", data.paper);
        if (data.focus) store("n360-focus", data.focus);
        if (data.watch) store("n360-watch", data.watch);
        if (data.missed) store("n360-missed", data.missed);
        if (data.cash != null) store("n360-cash", data.cash);
        render();
      }).catch(() => { state.error = "That file is not a Nick 360 JSON log."; banner(); });
    }
  });
  root.addEventListener("input", (e) => {
    if (e.target.id === "qsym") {
      state.query = e.target.value;
      const box = document.getElementById("screencroll");
      if (!box) return;
      const keep = e.target;
      const start = keep.selectionStart;
      render();
      const again = document.getElementById("qsym");
      if (again) { again.focus(); again.selectionStart = again.selectionEnd = start; }
    }
  });
  root.addEventListener("submit", (e) => {
    if (e.target.id !== "focusadd") return;
    e.preventDefault();
    const ticker = String(new FormData(e.target).get("ticker") || "").toUpperCase();
    addList("n360-focus", ticker);
    if (state.by.has(ticker)) state.symbol = ticker;
    render();
  });
  root.addEventListener("click", (e) => {
    const t = e.target.closest("[data-act]");
    if (!t) {
      if (!e.target.closest("#menu")) hideMenu();
      return;
    }
    const act = t.getAttribute("data-act");
    if (act === "page") { state.page = t.getAttribute("data-page"); setHash(); render(); return; }
    if (act === "left") { state.left = t.getAttribute("data-tab"); render(); return; }
    if (act === "right") { state.right = t.getAttribute("data-tab"); state.page = "charting"; render(); return; }
    if (act === "pick") { state.symbol = t.getAttribute("data-ticker"); state.page = state.page === "grader" ? "grader" : "charting"; state.hover = null; setHash(); render(); return; }
    if (act === "toggle") {
      const id = t.getAttribute("data-screen");
      state.open[id] = !state.open[id];
      render();
      return;
    }
    if (act === "sort") {
      const key = t.getAttribute("data-key");
      state.sortDir = state.sortKey === key ? -state.sortDir : (key === "ticker" ? 1 : -1);
      state.sortKey = key;
      render();
      return;
    }
    if (act === "tf") { state.tf = t.getAttribute("data-tf"); drawActive(); root.querySelectorAll("[data-act=tf]").forEach((b) => b.classList.toggle("on", b === t)); return; }
    if (act === "range") { state.range = t.getAttribute("data-range"); render(); return; }
    if (act === "marks") { state.marksOn = !state.marksOn; render(); return; }
    if (act === "actions") {
      const r = t.getBoundingClientRect();
      openMenu(r.left, r.bottom + 4);
      return;
    }
    if (act === "afilter") { state.alertFilter = state.alertFilter === t.getAttribute("data-filter") ? "all" : t.getAttribute("data-filter"); render(); return; }
    if (act === "add") { addList(t.getAttribute("data-list"), state.symbol); render(); return; }
    if (act === "remove") { removeList(t.getAttribute("data-list"), t.getAttribute("data-ticker")); render(); return; }
    if (act === "gmode") { state.grader = t.getAttribute("data-mode"); render(); return; }
    if (act === "modal") { openModal(t.getAttribute("data-modal")); return; }
    if (act === "defs") { openModal("defs"); return; }
    if (act === "closemodal") { hideModal(); return; }
    if (act === "menu") {
      const item = t.getAttribute("data-item");
      hideMenu();
      if (item === "summary" || item === "news") { state.right = item; state.page = "charting"; render(); }
      if (item === "marks") { state.marksOn = !state.marksOn; render(); }
      if (item === "reset") { state.range = "1Y"; state.hover = null; render(); }
      if (item === "copy") {
        const s = current();
        const text = s ? String(s.close) : "";
        if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text);
      }
      if (item === "focus") { addList("n360-focus", state.symbol); render(); }
      if (item === "watch") { addList("n360-watch", state.symbol); render(); }
      if (item === "trade") openModal("trade");
      return;
    }
    if (act === "savefill") {
      const fill = {
        id: uid(), ticker: val("pt"), date: val("pd"), side: val("pside") || "buy",
        shares: val("psh"), price: val("pp"), fee: val("pf") || "0", stop: val("pst"), pivot: val("ppv"), size: val("psz"), note: val("pn"),
      };
      const next = loadPaper().concat([fill]);
      const before = E.roundTrips(loadPaper()).ordered.length;
      const trial = E.roundTrips(next);
      const msg = document.getElementById("pmsg");
      if (!fill.ticker || !fill.date) { if (msg) msg.textContent = "Symbol and date are required."; return; }
      if (trial.ordered.length === before) { if (msg) msg.textContent = "Shares and price have to be above zero."; return; }
      if (trial.errors.some((err) => err.id === fill.id)) { if (msg) msg.textContent = trial.errors.filter((err) => err.id === fill.id)[0].text; return; }
      store("n360-paper", next);
      state.symbol = fill.ticker;
      hideModal();
      render();
      return;
    }
    if (act === "savemissed") {
      const row = { id: uid(), ticker: val("mt"), date: val("md"), note: val("mn") };
      if (!row.ticker || !row.date) return;
      store("n360-missed", loadMissed().concat([row]));
      state.symbol = row.ticker;
      hideModal();
      state.page = "grader";
      render();
      return;
    }
    if (act === "clear") {
      if (window.confirm("Clear the paper log stored in this browser?")) {
        store("n360-paper", []);
        store("n360-missed", []);
        render();
      }
      return;
    }
    if (act === "cap") { state.cap = !state.cap; render(); return; }
    if (act === "savecash") { store("n360-cash", num(val("cash"))); render(); return; }
    if (act === "applyshift") {
      const n = num(val("shift"));
      state.lossShift = n == null ? 0 : n / 100;
      render();
      return;
    }
    if (act === "export") {
      const blob = new Blob([JSON.stringify({ paper: loadPaper(), focus: loadList("n360-focus"), watch: loadList("n360-watch"), missed: loadMissed(), cash: loadCash() }, null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "nick360-paper.json";
      a.click();
      return;
    }
    if (act === "forecast") {
      const book = stats();
      state.page = "analytics";
      render();
      const msg = document.getElementById("rbafmsg");
      if (!book.closedN || book.batting == null || book.avgGain == null || book.avgLoss == null) {
        if (msg) msg.textContent = "Forecast inputs stay blank until there is a closed winner and a closed loser.";
        return;
      }
      setVal("ag", (book.avgGain * 100).toFixed(2));
      setVal("al", Math.abs(book.avgLoss * 100).toFixed(2));
      setVal("wn", (book.batting * 100).toFixed(2));
      const box = document.getElementById("rbaf");
      if (box) box.scrollIntoView();
      return;
    }
    if (act === "size") {
      const result = E.positionSize({ equity: val("eq"), entry: val("en"), stop: val("st"), riskPct: val("rk"), feePerShare: val("fee") });
      const msg = document.getElementById("sizemsg");
      if (!msg) return;
      msg.textContent = result.ok ? (result.shares + " shares, about $" + result.value.toFixed(0) + " (" + (result.valuePct * 100).toFixed(1) + "% of the account). Cash at risk to the stop $" + result.dollarRisk.toFixed(0) + ". " + result.warnings.join(" ")) : result.reason;
      return;
    }
    if (act === "sbe") {
      const result = E.sbeFraction({ entry: val("se"), stop: val("ss"), sale: val("sp"), shares: val("sh"), feePerShare: val("sf") });
      const msg = document.getElementById("sbemsg");
      if (!msg) return;
      msg.textContent = result.ok ? ("Sell " + (result.fraction * 100).toFixed(1) + "% (" + result.sharesToSell.toFixed(2) + " shares). " + result.assumption) : result.reason;
      return;
    }
    if (act === "rbaf") {
      const result = E.rbafScenario({ sizePct: val("sz"), targetPct: val("tg"), avgGainPct: val("ag"), avgLossPct: val("al"), winPct: val("wn"), feePct: val("fe") });
      const msg = document.getElementById("rbafmsg");
      if (!msg) return;
      msg.textContent = result.ok ? ("Linear trades " + result.linearTrades.toFixed(1) + ". Compound trades " + result.compoundTrades.toFixed(1) + ". " + result.note) : result.reason;
    }
  });
  function val(id) {
    const el = document.getElementById(id);
    return el ? el.value.trim() : "";
  }
  function setVal(id, value) {
    const el = document.getElementById(id);
    if (el) el.value = value;
  }
  window.addEventListener("resize", () => drawActive());
  if (window.ResizeObserver) new ResizeObserver(() => drawActive()).observe(view);
  boot();
})();
