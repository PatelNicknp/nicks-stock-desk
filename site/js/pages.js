/* Per-page layouts. Each page names the CSVs it reads. prices.csv is only on the scorecard. */
(function () {
  const D = window.Desk;
  const T = (key, label, kind, extra) => Object.assign({ key: key, label: label, kind: kind || "text" }, extra || {});
  const TK = T("ticker", "Ticker", "ticker");
  const CO = T("company", "Company", "text");
  const SE = T("sector", "Sector", "text");
  const SC = T("score", "Score", "score");
  const VE = T("verdict", "Verdict", "verdict");
  const PR = T("price", "Price", "num", { dec: 2 });

  function card(label, valueHtml, subHtml, bg) {
    return '<div class="card"' + (bg ? ' style="background:' + bg + '"' : "") + "><div class=\"l\">" +
      D.esc(label) + '</div><div class="v">' + valueHtml + "</div>" +
      (subHtml ? '<div class="s">' + subHtml + "</div>" : "") + "</div>";
  }
  function avg(rows, key) {
    const xs = [];
    rows.forEach((r) => { const n = D.num(r[key]); if (n != null) xs.push(n); });
    if (!xs.length) return null;
    return xs.reduce((a, b) => a + b, 0) / xs.length;
  }
  function median(rows, key) {
    const xs = [];
    rows.forEach((r) => { const n = D.num(r[key]); if (n != null) xs.push(n); });
    if (!xs.length) return null;
    xs.sort((a, b) => a - b);
    const m = Math.floor(xs.length / 2);
    return xs.length % 2 ? xs[m] : (xs[m - 1] + xs[m]) / 2;
  }
  function ntext(n, d) {
    if (n == null || !Number.isFinite(n)) return D.na();
    return D.esc(D.fmt(n, d));
  }
  function countWhere(rows, fn) { return rows.filter(fn).length; }
  function shift(iso, days) {
    const d = new Date(iso + "T00:00:00Z");
    d.setUTCDate(d.getUTCDate() + days);
    return d.toISOString().slice(0, 10);
  }
  function maxDate(rows, key) {
    let m = "";
    rows.forEach((r) => { if (r[key] && r[key] > m) m = r[key]; });
    return m || new Date().toISOString().slice(0, 10);
  }
  function chartHost(title, sub) {
    return '<div class="panel pad"><div class="ptitle">' + D.esc(title) + "</div>" +
      (sub ? '<div class="psub">' + sub + "</div>" : "") +
      '<div class="chart-box tall"><canvas></canvas></div></div>';
  }
  function paintLine(root, labels, series, y) {
    const canvas = root.querySelector("canvas");
    D.lineChart(canvas, labels, series, { y: y || {} });
  }

  const RET = { color: true };
  function standardFilters(box, all, opts) {
    opts = opts || {};
    const bag = {};
    if (opts.passes) bag.passes = D.selectHtml("passes", "Passes screen", ["yes", "no"], opts.passes);
    if (opts.status) {
      const statuses = D.uniq(all, "status");
      const picked = (opts.statusDefault || []).filter((s) => statuses.indexOf(s) >= 0);
      bag.status = D.multiHtml("status", "Status", statuses, picked.length ? picked : null);
    }
    if (opts.single) opts.single.forEach((s) => { bag[s.key] = D.selectHtml(s.key, s.label, D.uniq(all, s.key), s.value || ""); });
    if (opts.sector) bag.sector = D.multiHtml("sector", "Sector", D.uniq(all, "sector"));
    if (opts.verdict) bag.verdict = D.multiHtml("verdict", "Verdict", D.uniq(all, "verdict"));
    if (opts.confidence) bag.confidence = D.multiHtml("confidence", "Confidence", D.uniq(all, "confidence"));
    if (opts.index) bag.index = D.multiHtml("index", "Index", D.indexTokens(all));
    if (opts.trend) bag.timing = D.multiHtml("timing", "Trend", D.uniq(all, "timing"));
    if (opts.ticker) bag.ticker = D.searchHtml("ticker", "Ticker", "tick-list-" + (opts.list || "a"), D.uniq(all, "ticker"));
    const order = opts.order || ["ticker", "passes", "status", "verdict", "sector", "confidence", "index", "timing"];
    const parts = [];
    order.forEach((k) => { if (bag[k]) parts.push(bag[k]); });
    Object.keys(bag).forEach((k) => { if (order.indexOf(k) < 0) parts.push(bag[k]); });
    if (opts.extra) parts.push(opts.extra);
    box.innerHTML = parts.join("");
  }

  function readCommon(box, row) {
    const passes = D.fieldVal(box, "passes");
    const status = D.selectedMulti(box, "status");
    const sector = D.selectedMulti(box, "sector");
    const verdict = D.selectedMulti(box, "verdict");
    const confidence = D.selectedMulti(box, "confidence");
    const index = D.selectedMulti(box, "index");
    const timing = D.selectedMulti(box, "timing");
    const ticker = (D.fieldVal(box, "ticker") || "").trim();
    if (passes && row.passes !== passes) return false;
    if (!D.matchMulti(row, "status", status)) return false;
    if (!D.matchMulti(row, "sector", sector)) return false;
    if (!D.matchMulti(row, "verdict", verdict)) return false;
    if (!D.matchMulti(row, "confidence", confidence)) return false;
    if (!D.matchContains(row, "index_membership", index)) return false;
    if (!D.matchMulti(row, "timing", timing)) return false;
    if (!D.matchText(row, "ticker", ticker)) return false;
    const nodes = box.querySelectorAll("select[data-filter]");
    for (let i = 0; i < nodes.length; i++) {
      const key = nodes[i].getAttribute("data-filter");
      const val = nodes[i].value;
      if (!val || key === "passes") continue;
      if (!Object.prototype.hasOwnProperty.call(row, key)) continue;
      if (String(row[key] == null ? "" : row[key]) !== val) return false;
    }
    return true;
  }

  function hook(box, state, draw) {
    D.wireFilters(box, () => { state.page = 0; draw(); });
  }

  function passesPage(cfg) {
    return {
      files: [cfg.file],
      render(ctx) {
        const raw = ctx.files[cfg.file];
        const all = D.realRows(raw);
        const notice = cfg.notice ? cfg.notice(all, raw) : "";
        const cap = cfg.caption ? '<p class="cap">' + D.esc(cfg.caption) + "</p>" : "";
        ctx.page.innerHTML = (cfg.noticeAbove ? "" : (notice || "")) + '<div class="ctrls" id="ctrls"></div>' +
          (cfg.noticeAbove ? '<div id="notice"></div>' : "") +
          (cfg.captionAbove ? cap : "") +
          '<div class="cards" id="cards"></div><div class="panel" id="tbl"></div>' +
          (cfg.captionAbove ? "" : cap);
        if (cfg.noticeAbove) document.getElementById("notice").innerHTML = notice || "";
        const box = document.getElementById("ctrls");
        standardFilters(box, all, cfg.filters);
        D.placeFeed(box, raw);
        document.getElementById("cards").innerHTML = cfg.cards(all);
        const state = { sort: cfg.sort || "score", dir: cfg.dir || "desc", sort2: cfg.sort2 || "", dir2: cfg.dir2 || "desc", page: 0 };
        const draw = () => {
          const rows = all.filter((r) => readCommon(box, r) && (!cfg.match || cfg.match(r, box)));
          D.drawTable(document.getElementById("tbl"), {
            rows: rows, columns: cfg.columns, state: state, pageSize: cfg.pageSize || 25, foot: cfg.foot, title: cfg.tableTitle, sub: cfg.tableSub,
            expandable: true, lines: cfg.lines, priceSub: cfg.priceSub, detail: cfg.detail,
          });
        };
        hook(box, state, draw);
        draw();
      },
    };
  }

  function patternPage(cfg) {
    return {
      files: [cfg.file],
      render(ctx) {
        const raw = ctx.files[cfg.file];
        const all = D.realRows(raw);
        ctx.page.innerHTML = (cfg.strip ? '<div id="strip"></div>' : "") +
          '<div class="ctrls" id="ctrls"></div><div class="cards" id="cards"></div>' +
          '<div class="panel" id="tbl"></div><p class="cap"></p>';
        if (cfg.strip) document.getElementById("strip").innerHTML = cfg.strip(all);
        ctx.page.querySelector(".cap").textContent = cfg.caption || D.noteOf(raw);
        const box = document.getElementById("ctrls");
        standardFilters(box, all, cfg.filters);
        if (cfg.chips) box.insertAdjacentHTML("afterbegin", cfg.chips(all));
        D.placeFeed(box, raw);
        document.getElementById("cards").innerHTML = cfg.cards(all);
        const state = { sort: cfg.sort || "status", dir: cfg.dir || "asc", sort2: cfg.sort2 || "strength", dir2: "desc", page: 0 };
        const draw = () => {
          const rows = all.filter((r) => readCommon(box, r) && (!cfg.match || cfg.match(r, box)));
          D.drawTable(document.getElementById("tbl"), {
            rows: rows, columns: cfg.columns, state: state, pageSize: 12,
            expandable: true,
            lines: cfg.price || setupLines,
            priceSub: cfg.priceSub || "Buy point, stop, and target when the scan has them",
            detail: cfg.detail ? (row) => cfg.detail(row, rows) : null,
            empty: "No names match. Open Status and tick WATCHING to see names still forming.",
          });
        };
        hook(box, state, draw);
        draw();
      },
    };
  }

  function priceShell(sub) {
    return '<div class="panel pad" data-px-panel><div class="rowhead wrap"><div><div class="ptitle">Price</div><div class="psub">' +
      D.esc(sub || "Daily bars") + '</div></div><div class="pxtools" data-px-tools></div></div><div class="pxmas" data-px-mas></div><div class="chart-box pxchart"><div class="px-host" data-px-host><div class="px-legend" data-px-legend></div></div></div><p class="cap" data-px-cap></p></div>';
  }
  function setupLines(row) {
    const lines = [];
    if (!row) return lines;
    if (D.num(row.pivot) != null) lines.push({ value: D.num(row.pivot), color: "#F59E0B", label: "Buy point " + D.fmt(row.pivot, 2) });
    if (D.num(row.stop) != null) lines.push({ value: D.num(row.stop), color: "#EF4444", label: "Stop " + D.fmt(row.stop, 2) });
    if (D.num(row.target) != null) lines.push({ value: D.num(row.target), color: "#22C55E", label: "Target " + D.fmt(row.target, 2) });
    return lines;
  }
  function zoneLines(row) {
    const lines = [];
    if (!row) return lines;
    const lo = D.num(row.entry_low);
    const hi = D.num(row.entry_high);
    if (lo != null && hi != null) lines.push({ zone: [lo, hi], labelColor: "#F59E0B" });
    if (D.num(row.stop) != null) lines.push({ value: D.num(row.stop), color: "#EF4444", label: "Stop" });
    const tgt = D.num(row.trade_target != null && row.trade_target !== "" ? row.trade_target : row.target);
    if (tgt != null) lines.push({ value: tgt, color: "#22C55E", label: "Target" });
    return lines;
  }
  function weekLines(row) {
    const lines = [];
    if (!row) return lines;
    if (D.num(row.high_52w) != null) lines.push({ value: D.num(row.high_52w), color: "#22C55E", label: "52w high" });
    if (D.num(row.low_52w) != null) lines.push({ value: D.num(row.low_52w), color: "#EF4444", label: "52w low" });
    return lines;
  }
  function targetLine(row) {
    const n = D.num(row && row.target_analyst);
    return n == null ? [] : [{ value: n, color: "#22C55E", label: "Target" }];
  }
  function reasonBlock(row, extraCols) {
    let rules = "";
    if (extraCols) {
      rules = '<div class="panel" style="margin-top:12px"><div class="pad"><div class="ptitle">' + D.esc(row.ticker) +
        " rules</div></div><div class=\"scroll\"><table><tr>" +
        extraCols.map((c) => "<th>" + D.esc(c.label) + "</th>").join("") + "</tr><tr>" +
        extraCols.map((c) => "<td class=\"c wrap\">" + (c.kind === "pass" ? (D.isBlank(row[c.key]) ? D.na() : (String(row[c.key]).toUpperCase() === "PASS" ? '<span class="pill" style="color:#22C55E">PASS</span>' : String(row[c.key]).toUpperCase() === "FAIL" ? '<span class="pill" style="color:#EF4444">FAIL</span>' : D.esc(row[c.key]))) : (D.isBlank(row[c.key]) ? D.na() : D.esc(row[c.key]))) + "</td>").join("") +
        "</tr></table></div></div>";
    }
    return '<div class="panel pad" style="margin-top:12px"><div class="ptitle">' + D.tickerHtml(row.ticker) +
      ' · why this name</div><p class="cap" style="margin-top:8px">' + D.esc(row.reason || "") + "</p></div>" + rules;
  }

  const readyDefault = ["READY", "BROKEN OUT today"];

  function panelOff(key) {
    return !D.featureOn(key);
  }
  function offBox() {
    return '<div class="panel pad m2" style="font-size:12px">Turned off in Settings</div>';
  }
  function renderToday(ctx) {
    const mt = (ctx.files["market_today.csv"] || [])[0] || {};
    const breadth = D.lastNDays(D.realRows(ctx.files["breadth_history.csv"]), "date", 182);
    const sectors = D.realRows(ctx.files["sectors.csv"]);
    const alertRaw = ctx.files["alerts.csv"] || [];
    const alerts = D.alertDataRows(alertRaw);
    const day = D.num(mt.spy_day_pct);
    const dayHtml = day == null ? D.na() : '<span style="color:' + D.retColor(day) + '">' + (day < 0 ? "▼ " : "▲ ") + D.fmt(Math.abs(day), 2) + "% today</span>";
    const b = D.num(mt.breadth_sma50);
    const w = D.num(mt.breadth_sma50_week_ago);
    const delta = b != null && w != null ? b - w : null;
    const deltaHtml = delta == null ? D.na() : '<span style="color:' + D.retColor(delta) + '">' + (delta >= 0 ? "+" : "") + D.fmt(delta, 1) + " pts vs week ago</span>";
    const zone = mt.put_call_zone || "";
    const y10 = D.num(mt.fred_dgs10);
    const curve = D.num(mt.fred_t10y2y);
    const nStocks = mt.universe_n || "523";
    const chips = [
      ["20-day", mt.breadth_sma20, "#7C9CFF"],
      ["50-day", mt.breadth_sma50, "#E6EBF5"],
      ["100-day", mt.breadth_sma100, "#F59E0B"],
      ["200-day", mt.breadth_sma200, "#8B96AD"],
    ].map((c) => '<span class="chip"><i class="dot" style="background:' + c[2] + '"></i>' + c[0] + " <b>" +
      (D.num(c[1]) == null ? D.na() : D.fmt(c[1], 1) + "%") + "</b></span>").join("");
    const adv = D.isBlank(mt.advancers) ? D.na() : '<span style="color:#22C55E">' + D.esc(mt.advancers) + "</span>";
    const dec = D.isBlank(mt.decliners) ? D.na() : '<span style="color:#EF4444">' + D.esc(mt.decliners) + "</span>";
    const pc = D.num(mt.put_call);
    const pc5 = D.num(mt.put_call_ma5);
    ctx.page.innerHTML =
      '<div class="cards seven">' +
      card("SPY", D.num(mt.spy_price) == null ? D.na() : D.esc(D.fmt(mt.spy_price, 2)), "S&P 500 ETF " + (day == null ? D.na() : '<span style="color:' + D.retColor(day) + '">' + (day < 0 ? "▼" : "▲") + D.fmt(Math.abs(day), 2) + "%</span>")) +
      card("% above 50-day", b == null ? D.na() : D.esc(D.fmt(b, 1) + "%"), deltaHtml) +
      card("Advancers / decliners", adv + '<span style="color:#5B6680"> / </span>' + dec, "of " + D.esc(nStocks) + " stocks") +
      card("New 52-week highs", D.isBlank(mt.highs_52w) ? D.na() : D.esc(mt.highs_52w), (D.isBlank(mt.lows_52w) ? D.na() : D.esc(mt.lows_52w)) + " new lows") +
      card("Put/call mood", D.isBlank(zone) ? D.na() : D.zoneHtml(zone),
        (pc == null ? D.na() : D.fmt(pc, 2)) + " today · 5-day " + (pc5 == null ? D.na() : D.fmt(pc5, 2))) +
      card("VIX", D.num(mt.vix) == null ? D.na() : D.esc(D.fmt(mt.vix, 2)), "fear gauge") +
      card("10-year yield", y10 == null ? D.na() : D.esc(D.fmt(y10, 2) + "%"), curve == null ? "10y–2y " + D.na() : "10y–2y " + D.fmt(curve, 2)) +
      "</div>" +
      '<div class="split today-top">' +
      (panelOff("feature.breadth") ? offBox() :
        '<div class="panel pad"><div class="rowhead stack"><div><div class="ptitle">Market breadth</div><div class="psub">% of the ' + D.esc(nStocks) + ' desk stocks above each average, 6 months</div></div><div class="chips nowrap">' + chips + '</div></div><div class="chart-box"><canvas id="br"></canvas></div><div class="psub note">Gaps = days with no breadth data (shown as breaks, not 0)</div></div>') +
      (panelOff("feature.top_sectors") ? offBox() :
        '<div class="panel pad"><div class="ptitle">Sectors today</div><div class="psub">Day % change, 11 S&P sector ETFs</div><div class="chart-box"><canvas id="sec"></canvas></div></div>') +
      "</div>" +
      '<div class="split today-bot">' +
      (panelOff("feature.top_sectors") ? offBox() : '<div class="panel" id="top5"></div>') +
      (panelOff("feature.alerts") ? offBox() : '<div class="panel"><div class="pad" style="padding-bottom:0"><div class="rowhead"><div><div class="ptitle">Latest alerts</div><div class="psub">Changes since the previous run. Nothing is emailed and nothing is sent to a broker.</div></div><a class="more" href="alerts.html">All alerts ›</a></div></div><div id="alerts"></div></div>') +
      "</div>";
    if (!panelOff("feature.breadth")) {
      D.lineChart(document.getElementById("br"), breadth.map((r) => r.date), [
        { label: "20-day", data: D.seriesNum(breadth, "pct_above_sma20"), color: "#7C9CFF" },
        { label: "50-day", data: D.seriesNum(breadth, "pct_above_sma50"), color: "#E6EBF5" },
        { label: "100-day", data: D.seriesNum(breadth, "pct_above_sma100"), color: "#F59E0B" },
        { label: "200-day", data: D.seriesNum(breadth, "pct_above_sma200"), color: "#8B96AD" },
      ], { y: { min: 0, max: 100 }, legend: false });
    }
    if (!panelOff("feature.top_sectors")) {
      const eleven = sectors.filter((r) => D.SPD[r.ticker]).slice().sort((a, b) => (D.num(b.day_pct) || -999) - (D.num(a.day_pct) || -999));
      D.barChart(document.getElementById("sec"), eleven.map((r) => D.SPD[r.ticker]), eleven.map((r) => D.num(r.day_pct)),
        eleven.map((r) => (D.num(r.day_pct) || 0) >= 0 ? "#1F9D55" : "#D14343"),
        { horizontal: true, labels: true, dec: 1, suffix: "%",
          x: { ticks: { color: "#5B6680", callback: (v) => { const n = Number(v); const sign = n > 0 ? "+" : n < 0 ? "−" : ""; return sign + Math.abs(n) + "%"; } }, grid: { color: "#1E293B" } },
          cat: { ticks: { color: "#C3CBDB", autoSkip: false }, grid: { display: false } } });
      const top = sectors.slice().sort((a, b) => (D.num(b.day_pct) || -999) - (D.num(a.day_pct) || -999)).slice(0, 5)
        .map((r, i) => Object.assign({}, r, { n: String(i + 1), day_bar: r.day_pct }));
      D.drawTable(document.getElementById("top5"), {
        title: "Top 5 sectors today", sub: "Best day % of the 19 sector and industry ETFs",
        rows: top, columns: [T("n", "#", "num", { dec: 0 }), T("name", "Sector"), T("day_bar", "", "daybar"), T("day_pct", "Day %", "pct", Object.assign({ dec: 2 }, RET))],
        state: { sort: "day_pct", dir: "desc", page: 0 }, pageSize: 5, foot: false,
      });
    }
    if (!panelOff("feature.alerts")) {
      const host = document.getElementById("alerts");
      if (!alerts.length) D.showQuiet(host, D.quietMessage(alertRaw));
      else D.drawTable(host, {
        rows: alerts, columns: [TK, T("text", "What changed", "text", { wrap: true }), T("score", "Score", "scorejump"), VE],
        state: { sort: "score", dir: "desc", page: 0 }, pageSize: 8, foot: false, expandable: true,
      });
    }
  }

  function renderTop(ctx) {
    const raw = ctx.files["scores.csv"];
    const all = D.realRows(raw);
    ctx.page.innerHTML = D.banner(raw) + '<div class="ctrls" id="ctrls"></div><div class="panel" id="tbl"></div>';
    const box = document.getElementById("ctrls");
    standardFilters(box, all, { verdict: true, sector: true, confidence: true, index: true, ticker: true, order: ["verdict", "sector", "confidence", "index", "ticker"] });
    const state = { sort: "score", dir: "desc", page: 0 };
    const cols = [T("rank", "#", "num", { dec: 0, width: "40px" }), TK, CO, T("sector", "Sector", "text", { hide: "md" }), SC, VE, PR, T("day_pct", "Day %", "pct", Object.assign({ dec: 2 }, RET)),
      T("timing", "Trend", "trend"), T("entry_low", "Entry low", "num", { dec: 2 }), T("entry_high", "Entry high", "num", { dec: 2, hide: "md" }),
      T("stop", "Stop", "num", { dec: 2 }), T("trade_target", "Target", "num", { dec: 2 })];
    const draw = () => {
      D.drawTable(document.getElementById("tbl"), {
        rows: all.filter((r) => readCommon(box, r)), columns: cols, state: state, pageSize: 25,
        expandable: true, lines: zoneLines, priceSub: "Entry zone, stop, and target when the score has them",
      });
    };
    hook(box, state, draw);
    draw();
  }

  function miniStat(label, valueHtml) {
    return '<div><div class="l">' + D.esc(label) + '</div><div class="v">' + valueHtml + "</div></div>";
  }
  function px2(v) {
    return D.num(v) == null ? D.na() : D.esc(D.fmt(v, 2));
  }
  function inTargetBand(value, price) {
    const v = D.num(value);
    const p = D.num(price);
    if (v == null) return false;
    if (p == null || p <= 0) return true;
    const ratio = v / p;
    return ratio >= 0.5 && ratio <= 2;
  }
  function rangeTarget(value, price) {
    if (D.num(value) == null) return D.na();
    if (!inTargetBand(value, price)) return D.na() + '<div class="l">out of range</div>';
    return D.esc(D.fmt(value, 2));
  }
  function blendParts(row) {
    const parts = [];
    if (D.num(row.target_analyst) != null) parts.push(D.num(row.target_analyst));
    if (inTargetBand(row.target_pfcf, row.price) && D.num(row.target_pfcf) != null) parts.push(D.num(row.target_pfcf));
    if (inTargetBand(row.target_peg, row.price) && D.num(row.target_peg) != null) parts.push(D.num(row.target_peg));
    return parts;
  }
  function blendHtml(row) {
    const parts = blendParts(row);
    if (!parts.length) return D.na();
    const avg = parts.reduce((sum, n) => sum + n, 0) / parts.length;
    return '<span style="color:#7C9CFF">' + D.esc(D.fmt(avg, 2)) + "</span>";
  }
  function blendCount(row) {
    const n = blendParts(row).length;
    return n ? D.esc(String(n)) : D.na();
  }
  function ptsCard(label, v) {
    const n = D.num(v);
    const shown = n == null ? D.na() : D.esc(D.signedPts(n));
    return card(label, '<span style="color:#E6EBF5">' + shown + "</span>", "", n == null ? "" : D.ptsColor(n));
  }
  function renderScorecard(ctx) {
    const scores = D.realRows(ctx.files["scores.csv"]);
    const params = new URLSearchParams(location.search);
    const rank1 = (scores.find((r) => String(r.rank) === "1") || scores[0] || {}).ticker || "";
    let ticker = (params.get("t") || rank1 || "").toUpperCase();
    ctx.page.innerHTML = '<div class="ctrls" id="ctrls"></div><div id="body"></div>';
    const box = document.getElementById("ctrls");
    box.innerHTML = D.searchHtml("ticker", "Ticker", "sc-tickers", D.uniq(scores, "ticker")) +
      D.selectHtml("kind", "News type", ["headline", "desk_note"], "headline");
    D.placeFeed(box, ctx.files["scores.csv"]);
    const input = box.querySelector("[data-filter=ticker]");
    input.value = ticker;
    const newsEmpty = "News is fetched for the focus list only. Other tickers show no rows here.";
    const draw = () => {
      ticker = (D.fieldVal(box, "ticker") || rank1).trim().toUpperCase();
      input.value = ticker;
      const url = new URL(location.href);
      url.searchParams.set("t", ticker);
      history.replaceState(null, "", url);
      const row = scores.find((r) => r.ticker === ticker);
      const host = document.getElementById("body");
      D.destroyCharts();
      if (!row) {
        host.innerHTML = '<div class="empty">No scorecard for ' + D.esc(ticker) + ".</div>";
        return;
      }
      const kind = D.fieldVal(box, "kind") || "headline";
      const day = D.num(row.day_pct);
      const details = (ctx.files["score_details.csv"] || []).filter((r) => r.ticker === ticker);
      const earn = (ctx.files["earnings_history.csv"] || []).filter((r) => r.ticker === ticker && !D.isBlank(r.eps_actual))
        .sort((a, b) => a.earnings_date < b.earnings_date ? -1 : 1).slice(-8);
      const news = (ctx.files["news.csv"] || []).filter((r) => r.ticker === ticker && (kind === "" || r.kind === kind));
      const vsRows = [
        ["pts_forward_pe_ind", "Forward P/E"], ["pts_ttm_pe_ind", "Trailing P/E"], ["pts_ps_ind", "Price / sales"],
        ["pts_pfcf_ind", "Price / FCF"], ["pts_rev_growth_ind", "Revenue growth"], ["pts_eps_growth_ind", "EPS growth"],
        ["pts_div_yield_ind", "Dividend yield"],
      ];
      const vs = vsRows.map((pair) => "<tr><td>" + D.esc(pair[1]) + '</td><td class="c">' + D.pointsHtml(row[pair[0]]) + "</td></tr>").join("");
      const basis = [
        ["Fundamentals from", row.fundamentals_basis], ["Filed", row.fundamentals_filed],
        ["Years in own average", row.fin_avg_years], ["Forward P/E average", row.forward_pe_avg_basis],
        ["Missing fields", row.missing_fields],
      ].map((pair) => '<div class="rowhead"><span>' + D.esc(pair[0]) + '</span><span class="m2" style="text-align:right">' +
        (D.isBlank(pair[1]) ? D.na() : D.esc(pair[1])) + "</span></div>").join("");
      const scoreN = D.num(row.score);
      host.innerHTML =
        '<div class="panel pad identity"><div class="id-main"><div class="big">' + D.esc(row.ticker) + "</div><div>" + D.esc(row.company) +
        '</div><div class="m2" style="font-size:12px">' + D.esc(row.sector) + (row.industry ? " · " + D.esc(row.industry) : "") + "</div></div>" +
        '<div class="stat"><div class="l">Price</div><div class="v">' + px2(row.price) + "</div></div>" +
        '<div class="stat"><div class="l">Day %</div><div class="v" style="color:' + D.retColor(day) + '">' + (day == null ? D.na() : D.esc((day > 0 ? "+" : "") + D.fmt(day, 2) + "%")) + "</div></div>" +
        '<div class="stat"><div class="l">Confidence</div><div class="v" style="font-size:16px">' + (D.isBlank(row.confidence) ? D.na() : D.esc(row.confidence)) + '</div><div class="l" style="margin-top:8px">Verdict</div><div class="vpill">' + D.verdictHtml(row.verdict) + "</div></div>" +
        '<div class="stat"><div class="l">Desk score</div><div class="v"><span class="scorepill deskscore" style="background:' + D.band(scoreN || 0) + '">' + D.esc(scoreN == null ? "–" : String(scoreN)) + "</span></div></div></div>" +
        '<div class="panel pad"><p style="font-size:13px;line-height:20px">' + D.esc(row.reason || "") + "</p></div>" +
        '<div class="cards">' +
        ptsCard("Technical", row.pts_tech) + ptsCard("Financials", row.pts_fin) + ptsCard("Sentiment", row.pts_sent) +
        ptsCard("Earnings", row.pts_earnings) + ptsCard("Sector", row.pts_sector) +
        card("Total score", D.scoreHtml(row.score)) + "</div>" +
        '<div class="split plan"><div class="panel pad"><div class="ptitle">Plan</div><div class="mini">' +
        miniStat("Entry low", px2(row.entry_low)) + miniStat("Entry high", px2(row.entry_high)) +
        miniStat("Stop", D.num(row.stop) == null ? D.na() : '<span style="color:#EF4444">' + D.esc(D.fmt(row.stop, 2)) + "</span>") +
        miniStat("Trade target", D.num(row.trade_target) == null ? D.na() : '<span style="color:#22C55E">' + D.esc(D.fmt(row.trade_target, 2)) + "</span>") +
        miniStat("Reward / risk", px2(row.reward_risk)) +
        '</div><p class="cap">AVOID leaves entry and the trade target blank on purpose.</p></div>' +
        '<div class="panel pad"><div class="ptitle">Valuation</div><div class="mini">' +
        miniStat("Analyst target", px2(row.target_analyst)) + miniStat("Cash-flow target", rangeTarget(row.target_pfcf, row.price)) +
        miniStat("PEG target", rangeTarget(row.target_peg, row.price)) + miniStat("Blended target", blendHtml(row)) +
        miniStat("Inputs in blend", blendCount(row)) +
        "</div></div></div>" +
        '<div class="split chartpair">' + priceShell("Plan levels stay on the chart") +
        '<div class="panel pad"><div class="ptitle">EPS surprise %, last 8 reports</div><div class="chart-box"><canvas id="eh"></canvas></div></div></div>' +
        '<div class="split r21"><div class="panel" id="break"></div><div><div class="panel"><div class="pad" style="padding-bottom:0"><div class="ptitle">Versus sector</div></div><div class="scroll"><table><tbody>' + vs +
        '</tbody></table></div></div><div class="panel pad"><div class="ptitle">Data basis</div><div style="font-size:11px;margin-top:8px">' + basis + "</div></div></div></div>" +
        '<div class="panel" id="news"></div><p class="cap">' + D.esc(newsEmpty) + "</p>";
      const entryLo = D.num(row.entry_low);
      const entryHi = D.num(row.entry_high);
      const hlines = [];
      if (entryLo != null && entryHi != null) {
        hlines.push({
          zone: [entryLo, entryHi], color: "rgba(124,156,255,.10)", labelColor: "#F59E0B",
          label: "Entry " + D.fmt(Math.min(entryLo, entryHi), 0) + "–" + D.fmt(Math.max(entryLo, entryHi), 0),
        });
      } else if (entryLo != null || entryHi != null) {
        const one = entryLo != null ? entryLo : entryHi;
        hlines.push({ value: one, color: "#F59E0B", label: "Entry " + D.fmt(one, 2) });
      }
      if (D.num(row.stop) != null) hlines.push({ value: D.num(row.stop), color: "#EF4444", label: "Stop " + D.fmt(row.stop, 2) });
      if (D.num(row.trade_target) != null) hlines.push({ value: D.num(row.trade_target), color: "#22C55E", label: "Target " + D.fmt(row.trade_target, 2) });
      D.drawPriceChart(host.querySelector("[data-px-panel]"), { ticker: ticker, lines: hlines });
      const mon = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
      const earnLabels = earn.map((r) => {
        const m = /^(\d{4})-(\d{2})/.exec(r.earnings_date || "");
        return m ? mon[Number(m[2]) - 1] + " " + m[1].slice(2) : r.earnings_date;
      });
      D.makeChart(document.getElementById("eh"), {
        type: "bar",
        data: {
          labels: earnLabels,
          datasets: [
            { label: "Surprise %", data: D.seriesNum(earn, "surprise_pct"), backgroundColor: "#7C9CFF" },
            { label: "Next-day move %", data: D.seriesNum(earn, "move_1d_pct"), backgroundColor: "#8B96AD" },
          ],
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: Object.assign({}, { legend: { labels: { color: "#8B96AD", boxWidth: 12 } }, barLabels: { dec: 1, suffix: "%" } }),
          scales: {
            x: { ticks: { color: "#8B96AD", maxRotation: 0, autoSkip: false }, grid: { color: "#1E293B" } },
            y: { ticks: { color: "#8B96AD" }, grid: { color: "#1E293B" } },
          },
        },
      });
      D.drawTable(document.getElementById("break"), {
        title: "Score breakdown",
        rows: details,
        columns: [T("group_name", "Group"), T("item", "Item", "text", { wrap: true }), T("points_label", "Points", "plabel"),
          T("now_value", "Now", "num", { dec: 2 }), T("avg_value", "Own 3-yr avg", "num", { dec: 2 }), T("vs_industry", "Vs sector", "points")],
        state: { sort: "group_name", dir: "asc", sort2: "item", dir2: "asc", page: 0 }, pageSize: 20,
      });
      D.drawTable(document.getElementById("news"), {
        title: "News", sub: newsEmpty,
        rows: news,
        columns: [T("headline", "Headline", "text", { wrap: true }), T("publisher", "Source"), T("published", "Published")],
        state: { sort: "published", dir: "desc", page: 0 }, pageSize: 8,
        empty: newsEmpty,
      });
    };
    box.addEventListener("change", draw);
    draw();
  }

  function shortBucket(s) {
    const map = {
      "Scores 0 or below": "≤0",
      "Scores 1 to 3": "1-3",
      "Scores 4 to 5": "4-5",
      "Scores 6 to 7": "6-7",
      "Scores 8 to 9": "8-9",
      "Scores 10 or more": "10+",
    };
    return map[s] || s;
  }
  function passCell(v) {
    const s = String(v || "");
    if (D.isBlank(s)) return D.na();
    if (s.toUpperCase() === "PASS") return '<span class="pill" style="color:#22C55E">PASS</span>';
    if (s.toUpperCase() === "FAIL") return '<span class="pill" style="color:#EF4444">FAIL</span>';
    return D.esc(s);
  }
  function moodColor(text) {
    const s = String(text || "");
    if (s.indexOf("UP") === 0) return "#22C55E";
    if (s.indexOf("DOWN") === 0) return "#EF4444";
    if (s.indexOf("MIXED") === 0) return "#F59E0B";
    return "#8B96AD";
  }
  function moodShort(text) {
    const s = String(text || "");
    const i = s.indexOf(" / ");
    if (!s) return "–";
    return i > 0 ? s.slice(0, i) : s;
  }
  function byStatus(rows) {
    return rows.slice().sort((a, b) => {
      const c = String(a.status || "").localeCompare(String(b.status || ""));
      if (c) return c;
      return (D.num(b.strength) || 0) - (D.num(a.strength) || 0);
    });
  }
  function whyLines(rows) {
    return (rows || []).filter(Boolean).map((r) => '<div class="why"><span>' + D.tickerHtml(r.ticker) +
      '</span><span class="m2">' + D.esc(r.reason || "") + "</span></div>").join("") ||
      '<div class="m2">No names in this view.</div>';
  }

  function renderWatch(ctx) {
    const port = D.realRows(ctx.files["portfolio.csv"]);
    const sum = (ctx.files["portfolio_summary.csv"] || [])[0] || {};
    const watch = D.realRows(ctx.files["watchlist.csv"]);
    const nHold = sum.n_holdings || String(port.length);
    ctx.page.innerHTML = '<div class="ctrls" id="ctrls"></div>' +
      (sum.example_warning ? '<div class="note-strip">' + D.esc(sum.example_warning) + "</div>" : "") +
      '<div class="cards" id="cards"></div><div class="panel" id="hold"></div><div class="panel" id="watch"></div>' +
      '<p class="cap">Week-ago score stays blank until a score is seven days old. A dash is missing, not zero. These files are the published output of input/holdings.csv and input/my_watchlist.csv.</p>';
    const pnl = D.num(sum.day_pnl);
    const gain = D.num(sum.total_gain);
    const attn = String(sum.needs_attention || "0");
    document.getElementById("cards").innerHTML =
      card("Portfolio value", D.num(sum.value) == null ? D.na() : D.esc("$" + D.fmt(sum.value, 0)), D.esc(nHold) + " holdings") +
      card("Day P/L", pnl == null ? D.na() : '<span style="color:' + D.retColor(pnl) + '">' + D.esc((pnl > 0 ? "+$" : pnl < 0 ? "-$" : "$") + D.fmt(Math.abs(pnl), 2)) + "</span>",
        D.num(sum.day_pnl_pct) == null ? D.na() : '<span style="color:' + D.retColor(D.num(sum.day_pnl_pct)) + '">' + (D.num(sum.day_pnl_pct) > 0 ? "+" : "") + D.fmt(sum.day_pnl_pct, 2) + "%</span>") +
      card("Total gain", gain == null ? D.na() : '<span style="color:' + D.retColor(gain) + '">' + D.esc((gain > 0 ? "+$" : gain < 0 ? "-$" : "$") + D.fmt(Math.abs(gain), 0)) + "</span>",
        D.num(sum.total_gain_pct) == null ? "" : '<span style="color:' + D.retColor(D.num(sum.total_gain_pct)) + '">' + (D.num(sum.total_gain_pct) > 0 ? "+" : "") + D.fmt(sum.total_gain_pct, 2) + "%</span>") +
      card("Average desk score", D.num(sum.avg_score) == null ? D.na() : D.esc(D.fmt(sum.avg_score, 1)),
        '<span style="color:#F59E0B">' + D.esc(attn) + "</span> " + (attn === "1" ? "needs" : "need") + " attention");
    const box = document.getElementById("ctrls");
    box.innerHTML = D.multiHtml("verdict", "Verdict", D.uniq(port, "verdict")) +
      D.multiHtml("status", "Holding status", D.uniq(port, "status")) +
      D.searchHtml("ticker", "Ticker", "pf-tk", D.uniq(port.concat(watch), "ticker"));
    const hs = { sort: "weight_pct", dir: "desc", page: 0 };
    const ws = { sort: "score", dir: "desc", page: 0 };
    const draw = () => {
      const rows = port.filter((r) => D.matchMulti(r, "verdict", D.selectedMulti(box, "verdict")) &&
        D.matchMulti(r, "status", D.selectedMulti(box, "status")) && D.matchText(r, "ticker", D.fieldVal(box, "ticker")));
      const q = (D.fieldVal(box, "ticker") || "").trim();
      const example = port.some((r) => r.example === "yes") ? " · example rows" : "";
      D.drawTable(document.getElementById("hold"), {
        title: "My holdings", sub: nHold + " holdings" + example, rows: rows,
        columns: [TK, T("shares", "Shares", "num", { dec: 0 }), T("avg_cost", "Avg cost", "num", { dec: 2 }), PR,
          T("value", "Value", "money", { dec: 0 }), T("gain", "Gain", "money", { dec: 0, color: true }),
          T("gain_pct", "Gain %", "pct", { color: true }), T("weight_pct", "Weight %", "pct", { color: false }), SC,
          T("score_week_change", "Score vs week ago", "delta", { dec: 0 }),
          VE, T("stop", "Stop", "num", { dec: 2, tone: "stop" }), T("status", "Status", "hold")],
        state: hs, pageSize: 25, expandable: true, lines: zoneLines,
        priceSub: "Stop when the holding has one",
      });
      D.drawTable(document.getElementById("watch"), {
        title: "Watchlist, not owned yet",
        rows: watch.filter((r) => D.matchText(r, "ticker", q) && D.matchMulti(r, "verdict", D.selectedMulti(box, "verdict"))),
        columns: [TK, CO, PR, T("day_pct", "Day %", "pct", { color: true }), SC, VE,
          T("entry_low", "Entry low", "num", { dec: 2 }), T("entry_high", "Entry high", "num", { dec: 2 }),
          T("distance_to_entry_pct", "Distance to entry %", "dist"), T("timing", "Trend", "trend"),
          T("note_input", "Nick's note", "muted", { wrap: true })],
        state: ws, pageSize: 25, expandable: true, lines: zoneLines,
        priceSub: "Entry zone when the watchlist has one",
      });
    };
    hook(box, hs, draw);
    draw();
  }

  function renderAlerts(ctx) {
    const raw = ctx.files["alerts.csv"];
    const changeRaw = ctx.files["score_changes.csv"] || [];
    const all = D.alertDataRows(raw);
    const changes = D.realRows(changeRaw);
    const live = all;
    ctx.page.innerHTML = '<div class="ctrls" id="ctrls"></div>' +
      '<p class="cap">These are changes since the previous run. Nothing is emailed and nothing is sent to a broker.</p>' +
      '<div class="cards" id="cards"></div><div class="panel" id="tbl"></div><div class="panel" id="chg" style="margin-top:24px"></div>';
    document.getElementById("cards").innerHTML =
      card("Changes this run", String(live.length)) +
      card("Verdict changes", String(countWhere(live, (r) => r.kind === "verdict_change"))) +
      card("Breakouts", String(countWhere(live, (r) => r.kind === "breakout"))) +
      card("Entry-zone arrivals", String(countWhere(live, (r) => r.kind === "entry_zone")));
    const box = document.getElementById("ctrls");
    box.innerHTML = D.multiHtml("kind", "Alert type", D.uniq(all, "kind")) +
      D.multiHtml("verdict", "Verdict now", D.uniq(all, "verdict")) +
      D.searchHtml("ticker", "Ticker", "al-tk", D.uniq(all, "ticker")) +
      D.pairHtml("lo", "hi", "Score change", "", "");
    const state = { sort: "score", dir: "desc", page: 0 };
    const st2 = { sort: "score_change", dir: "desc", page: 0 };
    const inChange = (r) => {
      const n = D.num(r.score_change);
      const lo = D.fieldVal(box, "lo");
      const hi = D.fieldVal(box, "hi");
      if ((lo !== "" || hi !== "") && n == null) return false;
      if (lo !== "" && n < Number(lo)) return false;
      if (hi !== "" && n > Number(hi)) return false;
      return true;
    };
    const draw = () => {
      const alertHost = document.getElementById("tbl");
      if (!all.length) D.showQuiet(alertHost, D.quietMessage(raw), "Alerts");
      else {
        const rows = all.filter((r) => D.matchMulti(r, "kind", D.selectedMulti(box, "kind")) &&
          D.matchMulti(r, "verdict", D.selectedMulti(box, "verdict")) &&
          D.matchText(r, "ticker", D.fieldVal(box, "ticker")));
        D.drawTable(alertHost, {
          title: "Alerts", rows: rows,
          columns: [TK, T("kind", "Type", "kind"), T("text", "What changed", "text", { wrap: true }),
            SC, T("score_prev", "Score before", "num", { dec: 0 }),
            VE, T("verdict_prev", "Verdict before", "verdict"), PR],
          state: state, pageSize: 12, expandable: true,
        });
      }
      const q = (D.fieldVal(box, "ticker") || "").trim();
      const changeHost = document.getElementById("chg");
      const changeRows = changes.filter((r) => D.matchText(r, "ticker", q) && D.matchMulti(r, "verdict", D.selectedMulti(box, "verdict")) && inChange(r));
      if (!changes.length) D.showQuiet(changeHost, D.quietMessage(changeRaw), "Score changes");
      else D.drawTable(changeHost, {
        title: "Score changes",
        rows: changeRows,
        columns: [TK, CO, SC, T("score_prev", "Score before", "num", { dec: 0 }), T("score_change", "Change", "delta", { dec: 0 }),
          VE, T("day_pct", "Day %", "pct", { color: true }), PR],
        state: st2, pageSize: 12, expandable: true,
      });
    };
    hook(box, state, draw);
    draw();
  }

  function renderBacktest(ctx) {
    const summary = D.realRows(ctx.files["backtest_summary.csv"]);
    const equity = D.realRows(ctx.files["backtest_equity.csv"]);
    const buckets = D.realRows(ctx.files["backtest_buckets.csv"]).map((r) => Object.assign({}, r, { bucket_short: shortBucket(r.bucket) }));
    const yearly = D.realRows(ctx.files["backtest_yearly.csv"]);
    const notes = ctx.files["backtest_notes.csv"] || [];
    function windowLabel(r) {
      const name = r.window || "";
      if (name === "5y" && r.start && r.end) {
        const days = (Date.parse(r.end) - Date.parse(r.start)) / 86400000;
        const years = days / 365.25;
        if (Number.isFinite(years) && years < 4.6) return "Full history (" + years.toFixed(1) + "y)";
      }
      return name || ((r.start || "") + " to " + (r.end || ""));
    }
    summary.forEach((r) => { r._label = windowLabel(r); });
    const prefer = summary.find((r) => r.is_headline === "yes") || summary.slice().sort((a, b) => (D.num(b.months) || 0) - (D.num(a.months) || 0))[0];
    const head = summary.find((r) => r.is_headline === "yes") || prefer || summary[0] || {};
    ctx.page.innerHTML = '<div class="ctrls" id="ctrls"></div><div class="panel pad" id="head"></div><div class="cards" id="cards"></div>' +
      '<div class="split r21"><div class="panel pad"><div class="ptitle">Growth of 10,000, monthly test</div><div class="chart-box tall"><canvas id="eq"></canvas></div><p class="cap" id="eqcap"></p></div>' +
      '<div class="panel pad"><div class="ptitle">Excess return vs S&P 500 by score bucket</div><div class="psub">12-week horizon, % per signal</div><div class="chart-box tall"><canvas id="bk"></canvas></div></div></div>' +
      '<div class="split r21"><div class="panel" id="btbl"></div><div class="panel" id="ytbl"></div></div><div class="panel" id="notes"></div>';
    const spanAvail = String(head._label || "").match(/Full history \(([\d.]+)y\)/);
    document.getElementById("head").innerHTML = '<div style="font-size:20px;line-height:26px">' + D.esc(head.headline || "") + "</div>" +
      '<div class="m2" style="font-size:11px;margin-top:6px">From ' + D.esc(head.start || "") + " to " + D.esc(head.end || "") + " · " +
      D.esc(head.months || "") + " months" + (spanAvail ? " · " + spanAvail[1] + " of 5 years available" : "") +
      " · every month, buy the 20 highest-scoring stocks, compare with the S&P 500.</div>";
    const box = document.getElementById("ctrls");
    const windows = summary.map((r) => r._label);
    const horizons = D.uniq(buckets, "horizon");
    box.innerHTML = D.selectHtml("window", "Test window", windows, prefer ? prefer._label : "", { all: false }) +
      D.selectHtml("horizon", "Horizon", horizons, horizons.indexOf("12w") >= 0 ? "12w" : (horizons[0] || ""), { all: false });
    const bstate = { sort: "bucket_order", dir: "asc", page: 0 };
    const ystate = { sort: "year", dir: "asc", page: 0 };
    const draw = () => {
      const w = D.fieldVal(box, "window");
      const row = summary.find((r) => r._label === w) || prefer || summary[0] || {};
      const dd = D.num(row.top20_max_drawdown_pct);
      document.getElementById("cards").innerHTML =
        card("Top-20 yearly pace %", ntext(D.num(row.top20_cagr_pct), 1)) +
        card("S&P 500 yearly pace %", ntext(D.num(row.spy_cagr_pct), 1)) +
        card("Worst drop, top 20 %", dd == null ? D.na() : '<span style="color:#EF4444">' + D.esc(D.fmt(dd, 1)) + "</span>") +
        card("12-week hit rate %", ntext(D.num(row.hit_rate_12w_pct), 1));
      const hz = D.fieldVal(box, "horizon") || "12w";
      const brows = buckets.filter((r) => r.horizon === hz).slice().sort((a, b) => (D.num(a.bucket_order) || 0) - (D.num(b.bucket_order) || 0));
      const last = equity[equity.length - 1] || {};
      document.getElementById("eqcap").textContent = "Last point: top 20 " + (D.fmt(last.top20, 0) || "–") +
        " · S&P 500 " + (D.fmt(last.spy, 0) || "–") + " · bottom 20 " + (D.fmt(last.bottom20, 0) || "–") + ".";
      D.destroyCharts();
      D.lineChart(document.getElementById("eq"), equity.map((r) => r.date), [
        { label: "Top 20 by score", data: D.seriesNum(equity, "top20"), color: "#22C55E", spanGaps: true },
        { label: "S&P 500", data: D.seriesNum(equity, "spy"), color: "#E6EBF5", spanGaps: true },
        { label: "Bottom 20", data: D.seriesNum(equity, "bottom20"), color: "#EF4444", spanGaps: true },
      ], { y: { ticks: { callback: (v) => D.compact(v) } } });
      D.barChart(document.getElementById("bk"), brows.map((r) => r.bucket_short), brows.map((r) => D.num(r.excess_pct)),
        brows.map((r) => (D.num(r.excess_pct) || 0) >= 0 ? "#22C55E" : "#EF4444"),
        { labels: true, dec: 1, suffix: "%", y: { grace: "10%" } });
      D.drawTable(document.getElementById("btbl"), {
        title: "Score buckets, " + hz.replace("w", " weeks"), rows: brows,
        columns: [T("bucket_order", "", "num", { dec: 0, hidden: true }), T("bucket_short", "Score bucket"), T("n", "Signals", "num", { dec: 0 }),
          T("avg_return_pct", "Avg return %", "pct", { color: true }), T("avg_spy_pct", "S&P same period %", "pct", { color: true }),
          T("excess_pct", "Excess %", "pct", { color: true }), T("hit_rate_pct", "Hit rate %", "pct", { dec: 1, color: false })],
        state: bstate, pageSize: 10, foot: false,
      });
      D.drawTable(document.getElementById("ytbl"), {
        title: "Year by year", sub: "2026 is the year so far.", rows: yearly,
        columns: [T("year", "Year"), T("top20_pct", "Top 20 %", "pct", { color: true }), T("spy_pct", "S&P 500 %", "pct", { color: true }),
          T("difference_pct", "Difference %", "pct", { color: true }), T("signals", "Signals", "num", { dec: 0 })],
        state: ystate, pageSize: 12, foot: false,
      });
    };
    hook(box, bstate, draw);
    draw();
    D.drawTable(document.getElementById("notes"), {
      title: "Test limits, read before trusting the score",
      rows: notes, columns: [T("item", "What was tested", "item", { width: "300px" }), T("detail", "Detail", "text", { wrap: true })],
      state: { sort: "item", dir: "asc", page: 0 }, pageSize: 20, foot: false,
    });
  }

  const growth = passesPage({
    file: "scanner_growth.csv",
    caption: "Passes when revenue growth is at least the desk's growth level (setting scoring.growth_min_pct) and the label is not AVOID. Blank growth means the filing did not have it.",
    sort: "rev_growth",
    filters: { passes: "yes", sector: true, verdict: true, ticker: true },
    columns: [TK, CO, SE, PR, SC, VE, T("rev_growth", "Revenue growth %", "pct", { dec: 1, color: true }), T("eps_growth", "EPS growth %", "pct", { dec: 1, color: true }), T("rs_spy_3m", "vs S&P 500, 3 mo %", "pct", { dec: 1, color: true })],
    cards(all) {
      const pass = all.filter((r) => r.passes === "yes");
      return card("Passing the screen", String(pass.length)) +
        card("Of those, BUY", String(countWhere(pass, (r) => r.verdict === "BUY"))) +
        card("Average revenue growth %, passing", ntext(avg(pass, "rev_growth"), 1)) +
        card("Average 3-month vs S&P 500 %, passing", ntext(avg(pass, "rs_spy_3m"), 1));
    },
  });

  const quality = passesPage({
    file: "scanner_quality.csv",
    caption: "Passes = ROE point +1 and debt/equity under 1.5. Debt points compare to the sector and can be −1.",
    sort: "roe",
    filters: { passes: "yes", sector: true, verdict: true, ticker: true },
    columns: [TK, CO, SE, T("roe", "Return on equity %", "pct", { dec: 1, color: false }), T("de", "Debt / equity", "num", { dec: 2 }),
      T("pts_roe", "ROE points", "points"), T("pts_de", "Debt points", "points"), SC, VE],
    notice(all) {
      const roe = countWhere(all, (r) => D.num(r.roe) != null);
      const pass = countWhere(all, (r) => r.passes === "yes");
      if (pass === 0 && roe === 0) {
        return '<div class="note-strip">No stock passes today: return on equity and debt/equity are not on file (blank, not zero).</div>';
      }
      return "";
    },
    cards(all) {
      return card("Passing the screen", String(countWhere(all, (r) => r.passes === "yes"))) +
        card("ROE on file", String(countWhere(all, (r) => D.num(r.roe) != null))) +
        card("Debt/equity on file", String(countWhere(all, (r) => D.num(r.de) != null)));
    },
  });

  const dividend = passesPage({
    file: "scanner_dividend.csv",
    caption: "Passes when the yield is at least the desk's level (setting scoring.dividend_min_pct) and the label is not AVOID. A yield of 0 is real (no dividend). A dash means the yield could not be read.",
    sort: "div_yield",
    filters: { passes: "yes", sector: true, verdict: true, ticker: true },
    columns: [TK, CO, SE, PR, T("div_yield", "Yield %", "pct", { color: false }), T("div_yield_avg", "Own avg yield %", "pct", { color: false }),
      T("pts_div_yield", "Yield points", "points"), SC, VE],
    cards(all) {
      const pass = all.filter((r) => r.passes === "yes");
      const above = countWhere(pass, (r) => { const a = D.num(r.div_yield), b = D.num(r.div_yield_avg); return a != null && b != null && a > b; });
      return card("Passing the screen", String(pass.length)) +
        card("Of those, BUY", String(countWhere(pass, (r) => r.verdict === "BUY"))) +
        card("Average yield %, passing", ntext(avg(pass, "div_yield"), 2)) +
        card("Yield above own average", String(above));
    },
  });

  const wheel = passesPage({
    file: "scanner_wheel.csv",
    caption: "",
    noticeAbove: true,
    sort2: "dollar_volume",
    notice() {
      return '<p class="cap">Stock screen only. This is not an option contract. No strikes, expiries or premiums are shown or suggested.</p>';
    },
    filters: { passes: "yes", sector: true, trend: true, ticker: true },
    columns: [TK, CO, SE, PR, SC, VE, T("timing", "Trend", "trend"), T("rsi14", "RSI-14", "num", { dec: 1 }),
      T("above_sma200", "Above 200-day", "flag", { no: "#EF4444" }), T("dollar_volume", "Dollar volume", "dollars")],
    cards(all) {
      const pass = all.filter((r) => r.passes === "yes");
      const med = median(pass, "dollar_volume");
      return card("Passing the screen", String(pass.length)) +
        card("Of those, BUY", String(countWhere(pass, (r) => r.verdict === "BUY"))) +
        card("Average RSI-14, passing", ntext(avg(pass, "rsi14"), 1)) +
        card("Median daily dollar volume, passing", med == null ? D.na() : D.esc("$" + String(D.compact(med)).replace(/^-/, "")));
    },
  });

  const vcpRuleLabels = ["Above 150d & 200d", "150d over 200d", "200d rising", "50d over 150d & 200d", "Above 50d", "30%+ over 52w low", "Within 25% of 52w high", "Beats S&P 6m & 12m"];
  const vcp = patternPage({
    file: "scanner_vcp.csv",
    caption: "",
    filters: { status: true, statusDefault: readyDefault, index: true, ticker: true, single: [{ key: "in_trade", label: "In a trade" }] },
    columns: [TK, T("index_membership", "Index"), T("status", "Status", "setup"), PR, T("pivot", "Buy point", "num", { dec: 2 }),
      T("stop", "Stop", "num", { dec: 2, tone: "stop" }), T("target", "Target", "num", { dec: 2, tone: "target" }), T("trail", "20-day trail", "num", { dec: 2 }),
      T("trend_score", "Trend template", "of8"), T("contractions", "Pullbacks"), T("depths", "Pullback depths %"),
      T("strength", "Strength", "strengthbar"), T("freshness", "Freshness", "fresh")],
    price: setupLines,
    priceSub: "Buy point, stop, and target when the scan has them",
    cards(all) {
      return card("Broken out today", String(countWhere(all, (r) => r.status === "BROKEN OUT today"))) +
        card("Ready", String(countWhere(all, (r) => r.status === "READY"))) +
        card("Watching", String(countWhere(all, (r) => r.status === "WATCHING"))) +
        card("In a trade (buy printed)", String(countWhere(all, (r) => r.in_trade === "yes")));
    },
    detail(row) {
      const pills = vcpRuleLabels.map((label, i) => '<span class="rulepill">' + passCell(row["r" + (i + 1)]) + " " + D.esc(label) + "</span>").join("");
      return '<div class="panel pad"><div class="ptitle">Why this name</div>' + whyLines(row ? [row] : []) +
        '<div class="ptitle" style="margin-top:12px">Trend template</div><div class="rulepills">' + pills + "</div></div>";
    },
  });

  const canslim = patternPage({
    file: "scanner_canslim.csv",
    caption: "Stop and target are blank on every row on purpose. A dash is missing, not zero. Product, float and industry rank are not verified.",
    filters: {
      status: true, statusDefault: readyDefault, index: true, ticker: true,
      order: ["status", "qualify", "index", "ticker"],
      single: [{ key: "qualify", label: "Qualify", value: "strict" }],
    },
    chips(all) {
      const row = all[0] || {};
      return '<span class="moodchip">Market: ' + D.esc(moodShort(row.m_market)) + '</span>' +
        '<span class="moodchip">QQQ: ' + D.esc(moodShort(row.m_qqq)) + "</span>";
    },
    columns: [TK, T("index_membership", "Index"), T("status", "Status", "setup"), T("pivot", "Buy point", "num", { dec: 2 }),
      T("strength", "CANSLIM strength (raw)", "num", { dec: 0 }), T("qualify", "Qualify", "pass"),
      T("c_quarterly_eps", "C: quarter EPS vs yr ago %", "pct", { dec: 1 }), T("a_annual_eps", "A: annual EPS %", "pct", { dec: 1 }),
      T("n_pct_from_high", "N: % from 52w high", "pct", { dec: 1 }), T("s_adv", "S: avg daily volume", "compact"),
      T("l_rs_percentile", "L: RS percentile", "num", { dec: 0 }), T("i_trend", "I: holders trend", "itrend"), T("freshness", "Data", "fresh")],
    cards(all) {
      return card("Ready", String(countWhere(all, (r) => r.status === "READY"))) +
        card("Broken out today", String(countWhere(all, (r) => r.status === "BROKEN OUT today"))) +
        card("Strict qualify", String(countWhere(all, (r) => r.qualify === "strict"))) +
        card("Watching", String(countWhere(all, (r) => r.status === "WATCHING")));
    },
    detail(row) {
      const cols = [["c_status", "C"], ["a_status", "A"], ["n_status", "N"], ["s_status", "S"], ["l_status", "L"], ["i_status", "I"]];
      const letters = cols.map((c) => '<p class="whytext"><span class="droplab">' + c[1] + "</span> " +
        (D.isBlank(row[c[0]]) ? D.na() : D.esc(row[c[0]])) + "</p>").join("");
      return letters + '<div class="panel pad"><div class="ptitle">Why this name</div><p class="cap">' +
        D.esc((row && row.reason) || "") + "</p></div>";
    },
  });

  const box = patternPage({
    file: "scanner_box.csv",
    caption: "Desk rule, not the Pine script: a 15 to 40 day range no wider than 10% whose first and last closes drift by 5% or less, then a close through the range high on volume above 1.5 times the 50-day average.",
    filters: { status: true, statusDefault: readyDefault, index: true, sector: true, ticker: true },
    columns: [TK, CO, T("index_membership", "Index"), T("status", "Status", "setup"), PR,
      T("pivot", "Buy point (range high)", "num", { dec: 2 }), T("stop", "Stop (range low)", "num", { dec: 2, tone: "stop" }),
      T("target", "Target", "num", { dec: 2, tone: "target" }), T("strength", "Strength", "strengthbar"),
      T("range_days", "Range days", "num", { dec: 0 }), T("range_width_pct", "Range width %", "pct", { dec: 1, color: false }),
      T("volume_ratio", "Volume vs 50-day", "volx", { dec: 2 }), T("freshness", "Data", "fresh")],
    price: setupLines,
    cards(all) {
      return card("Broken out today", String(countWhere(all, (r) => r.status === "BROKEN OUT today"))) +
        card("Ready", String(countWhere(all, (r) => r.status === "READY"))) +
        card("Watching", String(countWhere(all, (r) => r.status === "WATCHING")));
    },
    detail(row) {
      return '<div class="panel pad"><div class="ptitle">Why this name</div>' + whyLines(row ? [row] : []) + "</div>";
    },
  });

  const flag = patternPage({
    file: "scanner_flag.csv",
    caption: "Desk rule, not the Pine script: a pole of at least 15% in 3 to 12 sessions, then a 3 to 15 day flag that retraces less than half the pole, then a close through the flag high on volume above 1.5 times the 50-day average.",
    filters: { status: true, statusDefault: readyDefault, index: true, sector: true, ticker: true },
    columns: [TK, CO, T("index_membership", "Index"), T("status", "Status", "setup"), PR,
      T("pivot", "Buy point (flag high)", "num", { dec: 2 }), T("stop", "Stop (flag low)", "num", { dec: 2, tone: "stop" }),
      T("target", "Target", "num", { dec: 2, tone: "target" }), T("strength", "Strength", "strengthbar"),
      T("pole_pct", "Pole rise %", "pct", { dec: 1, color: false }), T("flag_bars", "Flag days", "num", { dec: 0 }),
      T("retrace_pct", "Pullback of pole %", "retrace", { dec: 1 }), T("volume_ratio", "Volume vs 50-day", "volx", { dec: 2 }),
      T("freshness", "Data", "fresh")],
    price: setupLines,
    cards(all) {
      return card("Broken out today", String(countWhere(all, (r) => r.status === "BROKEN OUT today"))) +
        card("Ready", String(countWhere(all, (r) => r.status === "READY"))) +
        card("Watching", String(countWhere(all, (r) => r.status === "WATCHING")));
    },
    detail(row) {
      return '<div class="panel pad"><div class="ptitle">Why this name</div>' + whyLines(row ? [row] : []) + "</div>";
    },
  });

  const leaders = patternPage({
    file: "scanner_leaders.csv",
    caption: "Leaders is the overlap of a ready or just-broken VCP and a strict CANSLIM qualify. A name on only one of those still appears.",
    filters: { status: true, statusDefault: readyDefault, ticker: true, single: [{ key: "on_vcp", label: "On VCP" }, { key: "on_canslim", label: "On CANSLIM" }] },
    columns: [TK, T("index_membership", "Index"), T("status", "Status", "setup"),
      T("on_vcp", "VCP", "flag", { width: "60px" }), T("on_canslim", "CANSLIM", "flag", { width: "60px" }),
      T("vcp_status", "VCP status", "setup"), T("canslim_status", "CANSLIM status", "setup"),
      T("pivot", "Buy point", "num", { dec: 2 }), T("stop", "Stop", "num", { dec: 2, tone: "stop" }),
      T("target", "Target", "num", { dec: 2, tone: "target" }), T("strength", "Strength", "strengthbar"), T("freshness", "Data", "fresh")],
    price: setupLines,
    cards(all) {
      return card("On both scans", String(countWhere(all, (r) => r.on_vcp === "yes" && r.on_canslim === "yes"))) +
        card("VCP only", String(countWhere(all, (r) => r.on_vcp === "yes" && r.on_canslim === "no"))) +
        card("CANSLIM only", String(countWhere(all, (r) => r.on_vcp === "no" && r.on_canslim === "yes"))) +
        card("Ready", String(countWhere(all, (r) => r.status === "READY")));
    },
    detail(row) {
      return '<div class="panel pad"><div class="ptitle">Why this name</div>' + whyLines(row ? [row] : []) + "</div>";
    },
  });

  function renderCalendar(ctx) {
    const raw = ctx.files["earnings_calendar.csv"];
    const all = D.realRows(raw);
    ctx.page.innerHTML = '<div class="ctrls" id="ctrls"></div><div class="cards" id="cards"></div><div class="panel" id="tbl"></div>' +
      '<p class="cap">The one-day move is the next session after a report that hit at or after 4pm Eastern, otherwise the session of the report. The average is the last eight reports.</p>';
    const box = document.getElementById("ctrls");
    box.innerHTML = D.pairHtml("min", "max", "Days away 0–14", 0, 14) +
      D.selectHtml("owns", "Holdings only", ["yes", "no"], "") +
      D.searchHtml("ticker", "Ticker", "cal-tk", D.uniq(all, "ticker"));
    const windowRows = () => all.filter((r) => {
      const d = D.num(r.days_away);
      const lo = Number(D.fieldVal(box, "min"));
      const hi = Number(D.fieldVal(box, "max"));
      if (d == null || d < lo || d > hi) return false;
      const owns = D.fieldVal(box, "owns");
      if (owns && r.owns !== owns) return false;
      if (!D.matchText(r, "ticker", D.fieldVal(box, "ticker"))) return false;
      return true;
    });
    const state = { sort: "days_away", dir: "asc", sort2: "ticker", dir2: "asc", page: 0 };
    const draw = () => {
      const rows = windowRows();
      document.getElementById("cards").innerHTML =
        card("Reporting in the window", String(rows.length)) +
        card("Of those, Nick's holdings", String(countWhere(rows, (r) => r.owns === "yes"))) +
        card("After the close", String(countWhere(rows, (r) => r.when_hint === "after close")));
      D.drawTable(document.getElementById("tbl"), {
        rows: rows,
        columns: [TK, CO, T("next_earnings", "Report date", "shortdate"), T("when_hint", "When"), T("days_away", "Days away", "num", { dec: 0 }),
          T("last_eps_actual", "Last EPS", "num", { dec: 2 }), T("last_eps_estimate", "Last estimate", "num", { dec: 2 }),
          T("last_surprise_pct", "Last surprise %", "pct", { dec: 1, color: true }), T("last_1d_move_pct", "Last next-day move %", "pct", { dec: 1, color: true }),
          T("avg_1d_move_pct", "Avg next-day move %", "pct", { dec: 1, color: true }), T("n_past", "Reports on file", "num", { dec: 0 }),
          T("owns", "Held", "owns")],
        state: state, pageSize: 25, expandable: true,
        priceSub: "Daily price. The report date stays in the row.",
      });
    };
    hook(box, state, draw);
    draw();
  }

  function yq(date) {
    const m = /^(\d{4})-(\d{2})/.exec(date || "");
    if (!m) return date || "";
    return m[1] + " Q" + (Math.floor((Number(m[2]) - 1) / 3) + 1);
  }
  function renderHeat(ctx) {
    const raw = ctx.files["earnings_heatmap.csv"];
    const all = D.realRows(raw);
    ctx.page.innerHTML = '<div class="ctrls" id="ctrls"></div>' +
      '<p class="cap">Green = EPS beat, red = miss, grey = in line. Revenue is n/a in this free feed, so a double beat cannot be shown.</p>' +
      '<div class="split r21"><div class="panel" id="pivot"></div><div class="panel" id="detail"></div></div>';
    const quartersAll = Array.from(new Set(all.map((r) => yq(r.quarter)))).sort();
    const filledQ = quartersAll.filter((qtr) => all.some((r) => yq(r.quarter) === qtr && !D.isBlank(r.eps_flag)));
    const last6 = (filledQ.length ? filledQ : quartersAll).slice(-6);
    const q0 = /^(\d{4}) Q(\d)/.exec(last6[0] || "");
    let fromDefault = q0 ? q0[1] + "-" + String((Number(q0[2]) - 1) * 3 + 1).padStart(2, "0") + "-01" : "";
    if (!fromDefault || fromDefault < "2025-10-01") fromDefault = "2025-10-01";
    const end = maxDate(all, "quarter");
    const box = document.getElementById("ctrls");
    box.innerHTML = D.dateHtml("from", "From", fromDefault) + D.dateHtml("to", "To", end) +
      D.selectHtml("eps", "EPS result", ["beat", "miss", "inline"], "") +
      D.searchHtml("ticker", "Ticker", "hm-tk", D.uniq(all, "ticker"));
    const state = { page: 0 };
    const draw = () => {
      const from = D.fieldVal(box, "from");
      const to = D.fieldVal(box, "to");
      const eps = D.fieldVal(box, "eps");
      const q = (D.fieldVal(box, "ticker") || "").trim().toLowerCase();
      const rows = all.filter((r) => (!from || r.quarter >= from) && (!to || r.quarter <= to) &&
        (!eps || r.eps_flag === eps) && (!q || r.ticker.toLowerCase().indexOf(q) >= 0));
      const quarters = Array.from(new Set(rows.map((r) => yq(r.quarter)))).sort()
        .filter((qtr) => rows.some((r) => yq(r.quarter) === qtr && !D.isBlank(r.eps_flag)));
      const by = {};
      rows.forEach((r) => { by[r.ticker + "|" + yq(r.quarter)] = r; });
      const tickers = Array.from(new Set(rows.map((r) => r.ticker))).sort();
      const pageSize = 20;
      const pages = Math.max(1, Math.ceil(tickers.length / pageSize));
      if (state.page >= pages) state.page = 0;
      const slice = tickers.slice(state.page * pageSize, state.page * pageSize + pageSize);
      const head = "<th>Ticker</th>" + quarters.map((qtr) => '<th class="c">' + D.esc(qtr) + "</th>").join("");
      const body = slice.map((t) => "<tr><td>" + D.tickerHtml(t) + "</td>" + quarters.map((qtr) => {
        const r = by[t + "|" + qtr];
        if (!r) return '<td class="hm"><span>' + D.na() + "</span></td>";
        const flag = String(r.eps_flag || "").toLowerCase();
        const fill = flag === "beat" ? "#14532D" : flag === "miss" ? "#7F1D1D" : flag === "inline" ? "#283146" : "";
        if (!fill) return '<td class="hm"><span>' + D.na() + "</span></td>";
        return '<td class="hm"><span style="background:' + fill + '">' + flag + "</span></td>";
      }).join("") + "</tr>").join("");
      document.getElementById("pivot").innerHTML = '<div class="scroll"><table><thead><tr>' + head + "</tr></thead><tbody>" + body +
        '</tbody></table></div><div class="foot"><span>' + (tickers.length ? state.page * pageSize + 1 : 0) + "–" +
        Math.min((state.page + 1) * pageSize, tickers.length) + " of " + tickers.length + " tickers</span>" +
        '<div class="pg"><button type="button" id="hp"' + (state.page <= 0 ? " disabled" : "") + '>‹</button><button type="button" id="hn"' +
        (state.page >= pages - 1 ? " disabled" : "") + ">›</button></div></div>";
      const prev = document.getElementById("hp");
      const next = document.getElementById("hn");
      if (prev) prev.onclick = () => { state.page -= 1; draw(); };
      if (next) next.onclick = () => { state.page += 1; draw(); };
      const detail = rows.slice().sort((a, b) => a.quarter < b.quarter ? 1 : -1);
      D.drawTable(document.getElementById("detail"), {
        title: "Quarter detail", rows: detail,
        columns: [TK, T("quarter", "Quarter", "date"), T("label", "Result", "earnlabel", { wrap: true })],
        state: { sort: "quarter", dir: "desc", page: 0 }, pageSize: 12,
        expandable: true, priceSub: "Daily price around this report",
      });
    };
    hook(box, state, draw);
    draw();
  }

  function renderCards(ctx) {
    const raw = ctx.files["earnings_cards.csv"];
    const all = D.realRows(raw);
    ctx.page.innerHTML = '<div class="ctrls" id="ctrls"></div><div class="cards" id="cards"></div><div class="panel" id="tbl"></div>' +
      '<p class="cap">Grades are a fixed rule on the last few earnings beats and revenue growth versus the company\'s own history. They are not a write-up from a person, and they are not a trade.</p>';
    document.getElementById("cards").innerHTML = "ABCDF".split("").map((g) =>
      card("Grade " + g, String(countWhere(all, (r) => r.grade === g)))).join("");
    const src = (all[0] && all[0].sources) || "Yahoo Finance earnings dates. Revenue vs estimate is not in that free feed, so revenue is left blank.";
    const box = document.getElementById("ctrls");
    box.innerHTML = D.multiHtml("grade", "Grade", ["A", "B", "C", "D", "F"]) + D.searchHtml("ticker", "Ticker", "gc", D.uniq(all, "ticker"));
    const state = { sort: "grade", dir: "asc", sort2: "ticker", dir2: "asc", page: 0 };
    const draw = () => D.drawTable(document.getElementById("tbl"), {
      rows: all.filter((r) => D.matchMulti(r, "grade", D.selectedMulti(box, "grade")) && D.matchText(r, "ticker", D.fieldVal(box, "ticker"))),
      columns: [TK, CO, T("grade", "Grade", "grade"), T("summary", "Summary", "text", { wrap: true })],
      state: state, pageSize: 25, expandable: true,
      priceSub: "Daily price. The grade note is above the chart.",
    });
    hook(box, state, draw);
    draw();
    const cap = document.createElement("p");
    cap.className = "cap";
    cap.textContent = src;
    ctx.page.appendChild(cap);
  }

  function latestBox(bits, zone) {
    return '<div class="split r21"><div class="panel pad"><div class="ptitle">Latest</div><div class="mini">' + bits + "</div></div>" +
      '<div class="panel pad"><div class="ptitle">Today\'s zone</div><div style="margin-top:12px">' + D.zoneHtml(zone) + "</div></div></div>";
  }
  function renderPutCall(ctx) {
    const raw = (ctx.files["put_call.csv"] || []).filter((r) => r.name === "EQUITY PUT/CALL RATIO" && r.data_status !== "MISSING");
    const end = maxDate(raw, "date");
    ctx.page.innerHTML = '<div class="ctrls" id="ctrls"></div><p class="cap">Market mood only. Not an option position.</p>' +
      '<div id="latest"></div><div class="panel pad"><div class="ptitle">Put/call and its 5-day average</div><div class="chart-box tall"><canvas id="pc"></canvas></div></div><div class="panel" id="tbl"></div>';
    const box = document.getElementById("ctrls");
    box.innerHTML = D.dateHtml("from", "From", shift(end, -90)) + D.selectHtml("zone", "Zone", D.uniq(raw, "zone"), "");
    const latest = raw.slice().sort((a, b) => a.date < b.date ? 1 : -1)[0] || {};
    document.getElementById("latest").innerHTML = latestBox(
      '<div><div class="l">Date</div><div class="v">' + D.esc(latest.date || "–") + "</div></div>" +
      '<div><div class="l">Ratio</div><div class="v">' + (D.num(latest.value) == null ? D.na() : D.esc(D.fmt(latest.value, 3))) + "</div></div>" +
      '<div><div class="l">5-day avg</div><div class="v">' + (D.num(latest.ma5) == null ? D.na() : D.esc(D.fmt(latest.ma5, 3))) + "</div></div>",
      latest.zone);
    const state = { sort: "date", dir: "desc", page: 0 };
    const draw = () => {
      const from = D.fieldVal(box, "from");
      const series = raw.filter((r) => !from || r.date >= from).sort((a, b) => a.date < b.date ? -1 : 1);
      const zone = D.fieldVal(box, "zone");
      D.destroyCharts();
      const fear = D.num((series[0] || {}).fear_line);
      const greed = D.num((series[0] || {}).greed_line);
      D.lineChart(document.getElementById("pc"), series.map((r) => r.date), [
        { label: "Put/call", data: D.seriesNum(series, "value"), color: "#7C9CFF", spanGaps: false },
        { label: "5-day avg", data: D.seriesNum(series, "ma5"), color: "#E6EBF5", spanGaps: true },
      ], {
        y: { suggestedMin: 0.3, suggestedMax: 1.1 },
        layout: { padding: { right: 24 } },
        plugins: { hlines: [{ value: fear, color: "#EF4444", label: "Fear" }, { value: greed, color: "#22C55E", label: "Greed" }] },
      });
      D.drawTable(document.getElementById("tbl"), {
        title: "Recent readings",
        rows: series.filter((r) => !zone || r.zone === zone),
        columns: [T("date", "Date", "date"), T("value", "Put/call", "num", { dec: 2 }), T("ma5", "5-day avg", "num", { dec: 3 }), T("zone", "Zone", "zone")],
        state: state, pageSize: 10,
      });
    };
    hook(box, state, draw);
    draw();
  }

  function renderWalls(ctx) {
    const raw = D.realRows(ctx.files["option_walls.csv"]);
    const scores = D.realRows(ctx.files["scores.csv"] || []);
    const tickers = D.uniq(raw, "ticker");
    const start = tickers.indexOf("NVDA") >= 0 ? "NVDA" : (tickers[0] || "");
    ctx.page.innerHTML = '<div class="ctrls" id="ctrls"></div>' +
      '<p class="cap">Open interest by strike. Sentiment only. Not a contract to trade. Chains refresh once a day for the focus list, so most of the universe is not on this page.</p>' +
      '<div class="panel pad"><div class="ptitle" id="oititle">Open interest by strike</div><div class="legend"><span><i style="background:#22C55E"></i>Calls</span><span><i style="background:#EF4444;height:8px"></i>Puts</span></div><div class="chart-box tall"><canvas id="oi"></canvas></div></div><div class="split r21"><div class="panel" id="walls"></div><div class="panel pad" id="note"></div></div>';
    const box = document.getElementById("ctrls");
    box.innerHTML = D.searchHtml("ticker", "Ticker", "wtk", tickers) +
      '<label class="ctl"><span class="lab">Expiry</span><select data-filter="expiry"></select></label>' +
      D.selectHtml("band", "Strike range", [{ value: "near", label: "±25% of spot" }, { value: "all", label: "All strikes" }], "near", { all: false });
    box.querySelector("[data-filter=ticker]").value = start;
    const fillExpiry = () => {
      const t = (D.fieldVal(box, "ticker") || start).trim().toUpperCase();
      const rows = raw.filter((r) => r.ticker === t);
      const dates = D.uniq(rows, "expiry");
      const nearest = (rows.find((r) => r.nearest_expiry === "true") || {}).expiry || dates[0] || "";
      const sel = box.querySelector("[data-filter=expiry]");
      const prev = sel.value;
      sel.innerHTML = dates.map((d) => '<option value="' + D.esc(d) + '">' + D.esc(d) + (d === nearest ? " (nearest)" : "") + "</option>").join("");
      sel.value = dates.indexOf(prev) >= 0 ? prev : nearest;
    };
    const draw = () => {
      fillExpiry();
      const t = (D.fieldVal(box, "ticker") || start).trim().toUpperCase();
      const exp = D.fieldVal(box, "expiry");
      const spot = D.num((scores.find((r) => r.ticker === t) || {}).price);
      const near = D.fieldVal(box, "band") !== "all";
      let rows = raw.filter((r) => r.ticker === t && r.expiry === exp);
      if (near && spot != null) {
        rows = rows.filter((r) => {
          const s = D.num(r.strike);
          return s != null && s >= spot * 0.75 && s <= spot * 1.25;
        });
      }
      const strikes = D.uniq(rows, "strike");
      const call = strikes.map((s) => { const r = rows.find((x) => x.strike === s && x.side === "call"); return r ? D.num(r.open_interest) : 0; });
      const put = strikes.map((s) => { const r = rows.find((x) => x.strike === s && x.side === "put"); return r ? D.num(r.open_interest) : 0; });
      D.destroyCharts();
      const title = document.getElementById("oititle");
      if (title) title.textContent = "Open interest by strike, " + t + (exp ? " " + exp : "");
      D.barChart(document.getElementById("oi"), strikes, call, call.map(() => "#22C55E"), {
        label: "Calls",
        cat: { ticks: { color: "#8B96AD", autoSkip: false, maxRotation: 0, callback(v) {
          const label = this.getLabelForValue(v);
          const n = Number(label);
          return Number.isFinite(n) ? String(n).replace(/\.0$/, "") : label;
        } } },
      });
      const chart = (typeof Chart !== "undefined") ? Chart.getChart(document.getElementById("oi")) : null;
      if (chart) {
        chart.data.datasets.push({ label: "Puts", data: put, backgroundColor: "#EF4444", borderWidth: 0 });
        chart.update();
      }
      D.drawTable(document.getElementById("walls"), {
        title: "The walls: most open interest", rows: rows.filter((r) => r.is_wall === "yes"),
        columns: [T("side", "Side", "side"), T("strike", "Strike", "num", { dec: 2 }), T("open_interest", "Open interest", "num", { dec: 0 }), T("volume", "Volume today", "num", { dec: 0 })],
        state: { sort: "side", dir: "asc", page: 0 }, pageSize: 2, foot: false,
      });
      document.getElementById("note").innerHTML = '<div class="ptitle">Note</div><p class="cap">' + D.esc(D.noteOf(ctx.files["option_walls.csv"]) || "Open interest only, for the focus list, once a day. Not an option pick.") + "</p>";
    };
    D.wireFilters(box, draw);
    draw();
  }

  function renderAnalysts(ctx) {
    const raw = ctx.files["analyst_ratings.csv"];
    const all = D.realRows(raw);
    ctx.page.innerHTML = '<div class="ctrls" id="ctrls"></div><div class="cards" id="cards"></div><div class="panel" id="tbl"></div>' +
      '<p class="cap">Targets are the median analyst target. Mean rating runs from 1 (strong buy) to 5 (sell). Upside is the target divided by price, minus one, in percent.</p>';
    const labels = { "2": "+2 points", "1": "+1 point", "0": "0 points" };
    document.getElementById("cards").innerHTML = ["2", "1", "0"].map((p) =>
      card(labels[p], String(countWhere(all, (r) => String(D.num(r.pts_analyst)) === p)))).join("");
    const box = document.getElementById("ctrls");
    box.innerHTML = D.multiHtml("pts", "Analyst points", D.uniq(all, "pts_analyst")) +
      D.rangeHtml("min", "Min. analysts", 0, 80, 0, 1) +
      D.searchHtml("ticker", "Ticker", "an-tk", D.uniq(all, "ticker"));
    const state = { sort: "pts_analyst", dir: "desc", sort2: "analyst_count", dir2: "desc", page: 0 };
    const draw = () => D.drawTable(document.getElementById("tbl"), {
      rows: all.filter((r) => D.matchMulti(r, "pts_analyst", D.selectedMulti(box, "pts")) &&
        D.matchMin(r, "analyst_count", D.fieldVal(box, "min")) && D.matchText(r, "ticker", D.fieldVal(box, "ticker"))),
      columns: [TK, CO, T("analyst_mean", "Mean rating (1 = strong buy)", "num", { dec: 2 }), T("analyst_count", "Analysts", "num", { dec: 0 }),
        T("pts_analyst", "Analyst points", "points"), T("target_analyst", "Median target", "num", { dec: 2 }), PR,
        T("upside_pct", "Upside %", "pct", { dec: 1, color: true })],
      state: state, pageSize: 25, expandable: true, lines: targetLine,
      priceSub: "Median analyst target",
    });
    hook(box, state, draw);
    draw();
  }

  function render13f(ctx) {
    const raw = ctx.files["institutional_13f.csv"];
    const all = D.realRows(raw);
    const summary = all.filter((r) => r.row_type === "summary");
    const holders = all.filter((r) => r.row_type === "top_holder");
    const capped = summary.some((r) => String(r.note || "").toLowerCase().indexOf("capped") >= 0 || (D.num(r.ownership_pct) || 0) > 100);
    ctx.page.innerHTML = '<div class="ctrls" id="ctrls"></div>' +
      '<p class="cap">Summary of the latest public holdings file, plus the largest holders. Not every fund. Built this way so the page stays fast.' +
      (capped ? " Dash = not shown. The free source counts some holders twice, so the total can top 100%." : "") + "</p>" +
      '<div class="split r21"><div class="panel" id="sum"></div><div class="panel" id="top"></div></div>';
    const box = document.getElementById("ctrls");
    box.innerHTML = D.searchHtml("ticker", "Ticker", "f-tk", D.uniq(summary, "ticker")) +
      D.multiHtml("pts", "Institutional points", D.uniq(summary, "pts_institutional"));
    const s1 = { sort: "holders", dir: "desc", page: 0 };
    const s2 = { sort: "shares", dir: "desc", page: 0 };
    const draw = () => {
      const q = (D.fieldVal(box, "ticker") || "").trim();
      const pts = D.selectedMulti(box, "pts");
      const sums = summary.filter((r) => D.matchText(r, "ticker", q) && D.matchMulti(r, "pts_institutional", pts));
      const names = new Set(sums.map((r) => r.ticker));
      const filingNote = (row) => {
        const note = String(row.note || "").trim();
        return note ? '<p class="whytext">' + D.esc(note) + "</p>" : "";
      };
      D.drawTable(document.getElementById("sum"), {
        title: "Summary", rows: sums,
        columns: [TK, T("increased_shares", "Shares added", "compact"), T("decreased_shares", "Shares cut", "compact"),
          T("holders", "Holders", "num", { dec: 0 }), T("ownership_pct", "Owned by funds %", "owncap", { dec: 1 }),
          T("as_of", "As of", "date"), T("pts_institutional", "Points", "points")],
        state: s1, pageSize: 20, expandable: true, detail: filingNote,
        priceSub: "Daily price",
      });
      D.drawTable(document.getElementById("top"), {
        title: "Largest holders",
        rows: holders.filter((r) => !q || names.has(r.ticker)),
        columns: [TK, T("owner", "Holder", "text", { wrap: true }), T("shares", "Shares", "compact"),
          T("share_change", "Change", "signedcompact"), T("as_of", "As of", "date")],
        state: s2, pageSize: 10, expandable: true, detail: filingNote,
        priceSub: "Daily price. The holder name is above the chart.",
      });
    };
    hook(box, s1, draw);
    draw();
  }

  function renderAaii(ctx) {
    const raw = ctx.files["aaii_sentiment.csv"] || [];
    const row = raw[0] || {};
    ctx.page.innerHTML =
      '<div class="panel pad w740 aaii"><div class="m2" style="font-size:11px">Status</div><div style="font-size:18px;font-weight:700;color:#F59E0B;margin:8px 0">' +
      D.esc(row.data_status || "MISSING") + '</div><p style="font-size:13px">' + D.esc(row.note || "") + "</p></div>" +
      '<p style="margin-top:12px"><a class="linkish" href="put-call.html">Use the put/call ratio as the free mood gauge ›</a></p>';
  }

  function renderInsiders(ctx) {
    const raw = ctx.files["insider_trading.csv"];
    const all = D.realRows(raw);
    ctx.page.innerHTML = '<div class="ctrls" id="ctrls"></div>' +
      '<p class="cap">Open-market buy and sell counts over three months, from Nasdaq\'s public insider summary.</p>' +
      '<div class="cards" id="cards"></div><div class="split r21 top"><div class="panel" id="tbl"></div>' +
      '<div class="panel pad"><div class="ptitle">Most insider buys, 3 months</div><div class="chart-box h300"><canvas id="ib"></canvas></div></div></div>';
    const labels = { "1": "Net buyers (+1)", "0": "Neutral (0)", "-1": "Net sellers (−1)" };
    document.getElementById("cards").innerHTML = ["1", "0", "-1"].map((p) =>
      card(labels[p], String(countWhere(all, (r) => String(D.num(r.pts_insider)) === p)))).join("");
    const box = document.getElementById("ctrls");
    box.innerHTML = D.multiHtml("pts", "Insider points", D.uniq(all, "pts_insider")) +
      D.rangeHtml("min", "Min. buys", 0, 50, 0, 1) +
      D.searchHtml("ticker", "Ticker", "in-tk", D.uniq(all, "ticker"));
    const state = { sort: "buys_3m", dir: "desc", page: 0 };
    const draw = () => {
      const rows = all.filter((r) => D.matchMulti(r, "pts_insider", D.selectedMulti(box, "pts")) &&
        D.matchMin(r, "buys_3m", D.fieldVal(box, "min")) && D.matchText(r, "ticker", D.fieldVal(box, "ticker")));
      D.drawTable(document.getElementById("tbl"), {
        rows: rows,
        columns: [TK, T("buys_3m", "Buys, 3 mo", "count", { up: "#22C55E" }), T("sells_3m", "Sells, 3 mo", "count", { up: "#EF4444" }), T("pts_insider", "Points", "points")],
        state: state, pageSize: 25, expandable: true,
        priceSub: "Daily price. The bar chart stays the 3-month buy count.",
      });
      const top = all.slice().sort((a, b) => (D.num(b.buys_3m) || 0) - (D.num(a.buys_3m) || 0)).slice(0, 10);
      D.destroyCharts();
      D.barChart(document.getElementById("ib"), top.map((r) => r.ticker), top.map((r) => D.num(r.buys_3m)), top.map(() => "#22C55E"), { horizontal: true, labels: true, dec: 0 });
    };
    hook(box, state, draw);
    draw();
  }

  function renderHeadlines(ctx) {
    const raw = ctx.files["headline_sentiment.csv"];
    const all = D.realRows(raw);
    ctx.page.innerHTML = '<div class="ctrls" id="ctrls"></div>' +
      '<p class="cap">Tone is a word rule on the headline (beat, upgrade, probe, layoff, and similar). It is not added into the desk score.</p>' +
      '<div class="cards" id="cards"></div><div class="panel" id="tbl"></div>';
    document.getElementById("cards").innerHTML = [["1", "Positive"], ["0", "Neutral"], ["-1", "Negative"]].map((p) =>
      card(p[1], String(countWhere(all, (r) => String(D.num(r.tone)) === p[0])))).join("");
    const box = document.getElementById("ctrls");
    box.innerHTML = D.selectHtml("tone", "Tone", [{ value: "1", label: "Positive" }, { value: "0", label: "Neutral" }, { value: "-1", label: "Negative" }], "") +
      D.searchHtml("ticker", "Ticker", "hd-tk", D.uniq(all, "ticker")) +
      D.multiHtml("pub", "Publisher", D.uniq(all, "publisher"));
    const state = { sort: "published", dir: "desc", page: 0 };
    const draw = () => {
      const tone = D.fieldVal(box, "tone");
      D.drawTable(document.getElementById("tbl"), {
        rows: all.filter((r) => (!tone || String(D.num(r.tone)) === tone) &&
          D.matchMulti(r, "publisher", D.selectedMulti(box, "pub")) && D.matchText(r, "ticker", D.fieldVal(box, "ticker"))),
        columns: [TK, T("tone", "Tone", "tone"), T("headline", "Headline", "text", { wrap: true }), T("publisher", "Source"),
          T("published", "Published"), T("tone_note", "Why this tone", "muted", { inDetail: true })],
        state: state, pageSize: 20, expandable: true,
        priceSub: "Daily price. The headline and tone note are above the chart.",
      });
    };
    hook(box, state, draw);
    draw();
  }

  function renderXly(ctx) {
    const raw = D.realRows(ctx.files["xly_xlp.csv"]);
    const end = maxDate(raw, "date");
    ctx.page.innerHTML = '<div class="ctrls" id="ctrls"></div>' +
      '<p class="cap">Consumer discretionary divided by consumer staples. Above the 50-day average of the ratio is labeled risk on.</p>' +
      '<div id="latest"></div><div class="panel pad"><div class="ptitle">XLY / XLP ratio and its 50-day average</div><div class="chart-box tall"><canvas id="xx"></canvas></div></div><div class="panel" id="tbl"></div>';
    const latest = raw.slice().sort((a, b) => a.date < b.date ? 1 : -1)[0] || {};
    document.getElementById("latest").innerHTML = latestBox(
      '<div><div class="l">Date</div><div class="v">' + D.esc(latest.date || "–") + "</div></div>" +
      '<div><div class="l">Ratio</div><div class="v">' + (D.num(latest.ratio) == null ? D.na() : D.esc(D.fmt(latest.ratio, 3))) + "</div></div>" +
      '<div><div class="l">50-day avg</div><div class="v">' + (D.num(latest.ratio_sma50) == null ? D.na() : D.esc(D.fmt(latest.ratio_sma50, 3))) + "</div></div>",
      latest.zone);
    const box = document.getElementById("ctrls");
    box.innerHTML = D.dateHtml("from", "From", shift(end, -182)) + D.selectHtml("zone", "Zone", D.uniq(raw, "zone"), "");
    const state = { sort: "date", dir: "desc", page: 0 };
    const draw = () => {
      const from = D.fieldVal(box, "from");
      const series = raw.filter((r) => !from || r.date >= from).sort((a, b) => a.date < b.date ? -1 : 1);
      const zone = D.fieldVal(box, "zone");
      D.destroyCharts();
      D.lineChart(document.getElementById("xx"), series.map((r) => r.date), [
        { label: "XLY / XLP", data: D.seriesNum(series, "ratio"), color: "#7C9CFF", spanGaps: true },
        { label: "50-day avg", data: D.seriesNum(series, "ratio_sma50"), color: "#8B96AD", spanGaps: true },
      ], {});
      D.drawTable(document.getElementById("tbl"), {
        title: "Recent days",
        rows: series.filter((r) => !zone || r.zone === zone),
        columns: [T("date", "Date", "date"), T("xly", "XLY", "num", { dec: 2 }), T("xlp", "XLP", "num", { dec: 2 }),
          T("ratio", "Ratio", "num", { dec: 3 }), T("ratio_sma50", "50-day avg", "num", { dec: 3 }), T("zone", "Zone", "zone")],
        state: state, pageSize: 10,
      });
    };
    hook(box, state, draw);
    draw();
  }

  function renderFinancials(ctx) {
    const raw = ctx.files["financials_summary.csv"];
    const all = D.realRows(raw);
    const tickers = D.uniq(all, "ticker");
    const start = tickers.indexOf("ADSK") >= 0 ? "ADSK" : (tickers[0] || "");
    ctx.page.innerHTML = '<div class="ctrls" id="ctrls"></div><div class="panel pad" id="who"></div><div class="panel" id="tbl"></div>' +
      '<p class="cap">Direction says whether a lower or a higher number earns the point. The sector median needs four peers.</p>';
    const box = document.getElementById("ctrls");
    box.innerHTML = D.searchHtml("ticker", "Ticker", "fn-tk", tickers) + D.multiHtml("metric", "Metric", D.uniq(all, "metric"));
    box.querySelector("[data-filter=ticker]").value = start;
    const state = { sort: "metric", dir: "asc", page: 0 };
    const draw = () => {
      const t = (D.fieldVal(box, "ticker") || start).trim().toUpperCase();
      const rows = all.filter((r) => r.ticker === t && D.matchMulti(r, "metric", D.selectedMulti(box, "metric")));
      const one = rows[0] || all.find((r) => r.ticker === t) || {};
      document.getElementById("who").innerHTML = '<div style="font-size:24px;font-weight:700"><a class="tk" href="scorecard.html?t=' +
        encodeURIComponent(t) + '">' + D.esc(t) + '</a></div><div class="m2" style="font-size:13px;margin-top:4px">' + D.esc(one.sector || "") + "</div>";
      D.drawTable(document.getElementById("tbl"), {
        rows: rows,
        columns: [T("metric", "Metric"), T("direction", "Better when"), T("now_value", "Now", "num", { dec: 2 }),
          T("avg_3y", "Own 3-yr avg", "num", { dec: 2 }), T("pts_vs_self", "Points vs own history", "ownpts"),
          T("industry_median", "Sector median", "num", { dec: 2 }), T("pts_vs_industry", "Points vs sector", "points")],
        state: state, pageSize: 12, foot: false,
      });
    };
    hook(box, state, draw);
    draw();
  }

  function renderTracker(ctx) {
    const raw = ctx.files["earnings_tracker.csv"];
    const all = D.realRows(raw);
    const end = maxDate(all, "earnings_date");
    const tickers = D.uniq(all, "ticker");
    const start = tickers.indexOf("ADSK") >= 0 ? "ADSK" : (tickers[0] || "");
    ctx.page.innerHTML = '<div class="ctrls" id="ctrls"></div><div class="split r21">' +
      '<div class="panel pad"><div class="ptitle">EPS surprise %, last 8 reports</div><div class="chart-box"><canvas id="su"></canvas></div></div>' +
      '<div class="cards col" id="cards"></div></div><div class="panel" id="tbl"></div>';
    const box = document.getElementById("ctrls");
    let upcoming = false;
    box.innerHTML = D.dateHtml("from", "From", shift(end, -365 * 3)) + D.dateHtml("to", "To", end) +
      D.searchHtml("ticker", "Ticker", "tr-tk", tickers) +
      '<button type="button" class="dd" id="upbtn">Show upcoming</button>';
    box.querySelector("[data-filter=ticker]").value = start;
    const state = { sort: "earnings_date", dir: "desc", page: 0 };
    const draw = () => {
      const from = D.fieldVal(box, "from");
      const to = D.fieldVal(box, "to");
      const q = (D.fieldVal(box, "ticker") || start).trim().toUpperCase();
      const rows = all.filter((r) => r.ticker === q && (!from || r.earnings_date >= from) && (!to || r.earnings_date <= to) &&
        (upcoming || !D.isBlank(r.eps_actual)));
      document.getElementById("cards").innerHTML =
        card("Beats", String(countWhere(rows, (r) => r.result === "beat"))) +
        card("Misses", String(countWhere(rows, (r) => r.result === "miss"))) +
        card("Upcoming (no actual yet)", String(countWhere(all, (r) => r.ticker === q && D.isBlank(r.eps_actual))));
      const chartRows = all.filter((r) => r.ticker === q && D.num(r.surprise_pct) != null)
        .sort((a, b) => a.earnings_date < b.earnings_date ? -1 : 1).slice(-8);
      D.destroyCharts();
      const mon = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
      D.barChart(document.getElementById("su"), chartRows.map((r) => {
        const m = /^(\d{4})-(\d{2})/.exec(r.earnings_date || "");
        return m ? mon[Number(m[2]) - 1] + " " + m[1].slice(2) : r.earnings_date;
      }), chartRows.map((r) => D.num(r.surprise_pct)),
      chartRows.map((r) => (D.num(r.surprise_pct) || 0) >= 0 ? "#22C55E" : "#EF4444"),
      { labels: true, dec: 1, suffix: "%" });
      D.drawTable(document.getElementById("tbl"), {
        rows: rows,
        columns: [TK, T("earnings_date", "Report date", "date"), T("eps_estimate", "EPS estimate", "num", { dec: 2 }),
          T("eps_actual", "EPS actual", "num", { dec: 2 }), T("surprise_pct", "Surprise %", "pct", { dec: 1, color: true }), T("result", "Result", "result")],
        state: state, pageSize: 12,
      });
    };
    box.querySelector("#upbtn").addEventListener("click", () => {
      upcoming = !upcoming;
      box.querySelector("#upbtn").textContent = upcoming ? "Hide upcoming" : "Show upcoming";
      state.page = 0;
      draw();
    });
    hook(box, state, draw);
    draw();
  }

  function fyLabel(v) {
    const m = /^(\d{4})/.exec(String(v || ""));
    return m ? "FY" + m[1].slice(2) : "";
  }
  function renderCompany(ctx) {
    const raw = ctx.files["company_financials.csv"];
    const all = D.realRows(raw);
    const tickers = D.uniq(all, "ticker");
    const start = tickers.indexOf("ADSK") >= 0 ? "ADSK" : (tickers[0] || "");
    const end = maxDate(all, "fy_end");
    ctx.page.innerHTML = '<div class="ctrls" id="ctrls"></div>' +
      '<p class="cap">Annual figures from SEC filings. Margins are blank when the filing did not include that line.</p>' +
      '<div class="split"><div class="panel pad"><div class="ptitle">Revenue and net income</div><div class="chart-box"><canvas id="rev"></canvas></div><p class="cap" id="nicap"></p></div>' +
      '<div class="panel pad"><div class="ptitle">Margins</div><div class="chart-box"><canvas id="mg"></canvas></div></div></div><div class="panel" id="tbl"></div>';
    const box = document.getElementById("ctrls");
    box.innerHTML = D.searchHtml("ticker", "Ticker", "co-tk", tickers) +
      D.selectHtml("years", "Years", [{ value: "5", label: "Last 5 years" }, { value: "10", label: "Last 10 years" }], "10", { all: false });
    box.querySelector("[data-filter=ticker]").value = start;
    const state = { sort: "fy_end", dir: "desc", page: 0 };
    const moneyTick = (v) => {
      const n = Number(v);
      if (!Number.isFinite(n)) return v;
      const body = D.compact(Math.abs(n));
      return (n < 0 ? "-$" : "$") + String(body || "").replace(/^-/, "");
    };
    const draw = () => {
      const t = (D.fieldVal(box, "ticker") || start).trim().toUpperCase();
      const nYears = Number(D.fieldVal(box, "years") || 10);
      const mine = all.filter((r) => r.ticker === t).sort((a, b) => a.fy_end < b.fy_end ? -1 : 1);
      const rows = mine.slice(-nYears);
      const labels = rows.map((r) => fyLabel(r.fy_end));
      const missingNi = rows.some((r) => D.num(r.revenue) != null && D.num(r.net_income) == null);
      const note = document.getElementById("nicap");
      if (note) note.textContent = missingNi ? "Net income not parsed for these years." : "";
      D.destroyCharts();
      D.makeChart(document.getElementById("rev"), {
        type: "bar",
        data: { labels: labels, datasets: [
          { label: "Revenue", data: D.seriesNum(rows, "revenue"), backgroundColor: "#7C9CFF" },
          { label: "Net income", data: D.seriesNum(rows, "net_income"), backgroundColor: "#8B96AD" },
        ] },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { labels: { color: "#8B96AD", boxWidth: 12 } }, barLabels: { level: true, money: true, dec: 1 } },
          scales: {
            x: { ticks: { color: "#8B96AD", maxRotation: 0, autoSkip: false }, grid: { display: false } },
            y: { ticks: { color: "#8B96AD", callback: moneyTick }, grid: { color: "#1E293B" } },
          },
        },
      });
      D.lineChart(document.getElementById("mg"), labels, [
        { label: "Gross margin", data: D.seriesNum(rows, "gross_margin"), color: "#E6EBF5", spanGaps: false },
        { label: "Operating margin", data: D.seriesNum(rows, "operating_margin"), color: "#7C9CFF", spanGaps: false },
        { label: "Net margin", data: D.seriesNum(rows, "net_margin"), color: "#8B96AD", spanGaps: false },
      ], { x: { ticks: { autoSkip: false, maxRotation: 0, color: "#8B96AD" } }, plugins: { barLabels: { level: true, suffix: "%", dec: 1 } } });
      D.drawTable(document.getElementById("tbl"), {
        rows: rows,
        columns: [T("fy_end", "Fiscal year", "fy"), T("revenue", "Revenue", "compact"), T("gross_profit", "Gross profit", "compact"),
          T("op_income", "Operating income", "compact"), T("net_income", "Net income", "compact"), T("eps", "EPS", "num", { dec: 2 }),
          T("gross_margin", "Gross margin %", "pct", { dec: 1, color: false }), T("operating_margin", "Operating margin %", "pct", { dec: 1, color: false }),
          T("net_margin", "Net margin %", "pct", { dec: 1, color: false }), T("pe", "P/E", "multiple", { dec: 1 }), T("ps", "P/S", "num", { dec: 2 }),
          T("pfcf", "P/FCF", "multiple", { dec: 1 })],
        state: state, pageSize: 12,
      });
    };
    hook(box, state, draw);
    draw();
  }

  function renderDivFund(ctx) {
    const raw = ctx.files["dividend_scanner.csv"];
    const all = D.realRows(raw);
    ctx.page.innerHTML = '<div class="ctrls" id="ctrls"></div><div class="cards" id="cards"></div><div class="panel" id="tbl"></div>' +
      '<p class="cap">A yield of 0 is real: the company does not pay. A dash means the yield could not be read. The Data updates page shows how many are unknown.</p>';
    const payers = all.filter((r) => (D.num(r.div_yield) || 0) > 0);
    document.getElementById("cards").innerHTML =
      card("Pay a dividend", String(payers.length)) +
      card("Pay none (yield 0)", String(countWhere(all, (r) => D.num(r.div_yield) === 0))) +
      card("Yield unknown", String(countWhere(all, (r) => D.num(r.div_yield) == null))) +
      card("Average yield of payers", ntext(avg(payers, "div_yield"), 2));
    const box = document.getElementById("ctrls");
    standardFilters(box, all, { sector: true, verdict: true, ticker: true, order: ["pays", "sector", "verdict", "ticker"] });
    box.insertAdjacentHTML("afterbegin", D.selectHtml("pays", "Pays a dividend", ["yes", "no"], ""));
    const state = { sort: "div_yield", dir: "desc", page: 0 };
    const draw = () => {
      const pays = D.fieldVal(box, "pays");
      D.drawTable(document.getElementById("tbl"), {
        rows: all.filter((r) => {
          if (!readCommon(box, r)) return false;
          const y = D.num(r.div_yield);
          if (pays === "yes" && !(y > 0)) return false;
          if (pays === "no" && y !== 0) return false;
          return true;
        }),
        columns: [TK, CO, SE, PR, T("div_yield", "Yield %", "pct", { color: false }), T("div_yield_avg", "Own avg yield %", "pct", { color: false }),
          T("dps", "Dividend per share", "num", { dec: 2 }), T("pts_div_yield", "Points", "points"), VE],
        state: state, pageSize: 25, expandable: true,
        priceSub: "Daily price",
      });
    };
    hook(box, state, draw);
    draw();
  }

  function renderMacro(ctx) {
    const raw = ctx.files["macro_screener.csv"];
    const all = D.realRows(raw);
    ctx.page.innerHTML = '<div class="ctrls" id="ctrls"></div>' +
      '<p class="cap">Signal is +1 when the surprise is in the direction that usually helps stocks (for unemployment and jobless claims, lower is the helpful direction). It is a label, not a forecast.</p>' +
      '<div class="cards" id="cards"></div><div class="panel" id="tbl"></div>';
    document.getElementById("cards").innerHTML =
      card("Helpful surprises (+1)", String(countWhere(all, (r) => String(D.num(r.signal)) === "1"))) +
      card("Neutral (0)", String(countWhere(all, (r) => String(D.num(r.signal)) === "0"))) +
      card("Unhelpful (−1)", String(countWhere(all, (r) => String(D.num(r.signal)) === "-1")));
    const countline = all.length + " releases in the last 14 days";
    const box = document.getElementById("ctrls");
    box.innerHTML = D.multiHtml("cat", "Category", D.uniq(all, "category")) +
      D.multiHtml("ind", "Indicator", D.uniq(all, "indicator")) +
      D.multiHtml("sig", "Signal", D.uniq(all, "signal"));
    const state = { sort: "date", dir: "desc", page: 0 };
    const draw = () => D.drawTable(document.getElementById("tbl"), {
      title: "Releases", sub: countline,
      rows: all.filter((r) => D.matchMulti(r, "category", D.selectedMulti(box, "cat")) &&
        D.matchMulti(r, "indicator", D.selectedMulti(box, "ind")) && D.matchMulti(r, "signal", D.selectedMulti(box, "sig"))),
      columns: [T("date", "Date", "date"), T("category", "Category"), T("indicator", "Indicator", "text", { wrap: true }),
        T("actual", "Actual"), T("forecast", "Forecast"), T("surprise", "Surprise", "surprise"), T("signal", "Signal", "tone")],
      state: state, pageSize: 25,
      empty: all.length ? "No rows match." : "No releases on file.",
    });
    hook(box, state, draw);
    draw();
  }

  function renderSecMacro(ctx) {
    const macro = D.realRows(ctx.files["sector_macro.csv"]);
    const sectors = D.realRows(ctx.files["sectors.csv"]);
    const plain = (macro[0] && macro[0].plain_english) || "Rule of thumb from the latest surprises. It is not a forecast.";
    ctx.page.innerHTML = '<div class="ctrls" id="ctrls"></div><p class="cap">' + D.esc(plain) +
      " Weights are fixed in the job (for example, hotter inflation helps energy and hurts growth sectors).</p>" +
      '<div class="split sm"><div class="panel" id="mac"></div><div class="panel" id="px"></div></div>';
    const box = document.getElementById("ctrls");
    box.innerHTML = D.multiHtml("score", "Macro score", D.uniq(macro, "macro_score")) +
      D.multiHtml("etf", "Sector ETF", D.uniq(macro, "ticker"));
    const draw = () => {
      const etf = D.selectedMulti(box, "etf");
      const score = D.selectedMulti(box, "score");
      D.drawTable(document.getElementById("mac"), {
        title: "Macro scores", rows: macro.filter((r) => D.matchMulti(r, "ticker", etf) && D.matchMulti(r, "macro_score", score)),
        columns: [T("ticker", "ETF", "etf"), T("name", "Sector"), T("macro_growth", "Growth", "points"),
          T("macro_inflation", "Inflation", "points"), T("macro_jobs", "Jobs", "points"), T("macro_score", "Total", "points")],
        state: { sort: "macro_score", dir: "desc", page: 0 }, pageSize: 25, foot: false,
      });
      D.drawTable(document.getElementById("px"), {
        title: "Price change (sorted by YTD)", rows: sectors.filter((r) => D.matchMulti(r, "ticker", etf)),
        columns: [T("ticker", "ETF", "etf"), T("day_pct", "Day %", "pct", { color: true }), T("week_pct", "Week %", "pct", { color: true }),
          T("month_pct", "Month %", "pct", { color: true }), T("ytd_pct", "YTD %", "pct", { color: true })],
        state: { sort: "ytd_pct", dir: "desc", page: 0 }, pageSize: 25, foot: false,
      });
    };
    hook(box, { page: 0 }, draw);
    draw();
  }

  function renderHist(ctx) {
    const raw = ctx.files["historical_pe.csv"] || [];
    const all = D.realRows(raw);
    const end = maxDate(all, "date");
    ctx.page.innerHTML = '<div class="ctrls" id="ctrls"></div>' +
      '<p class="cap">Median trailing P/E of the stocks on this desk. There is no free official S&P 500 P/E series, so that line is not drawn.</p>' +
      '<div class="panel pad"><div class="ptitle">Desk median trailing P/E</div><div class="chart-box tall"><canvas id="pe"></canvas></div></div><div class="panel" id="tbl"></div>';
    const box = document.getElementById("ctrls");
    box.innerHTML = D.dateHtml("from", "From", shift(end, -1825));
    const state = { sort: "date", dir: "desc", page: 0 };
    const draw = () => {
      const from = D.fieldVal(box, "from");
      const rows = all.filter((r) => !from || r.date >= from).sort((a, b) => a.date < b.date ? -1 : 1);
      D.destroyCharts();
      D.lineChart(document.getElementById("pe"), rows.map((r) => r.date), [
        { label: "Desk median trailing P/E", data: D.seriesNum(rows, "desk_median_trailing_pe"), color: "#7C9CFF", spanGaps: true },
      ], { legend: false });
      D.drawTable(document.getElementById("tbl"), {
        rows: rows, columns: [T("date", "Month end", "date"), T("desk_median_trailing_pe", "Median P/E", "num", { dec: 1 }),
          T("n", "Stocks in the median", "num", { dec: 0 })],
        state: state, pageSize: 12,
      });
    };
    hook(box, state, draw);
    draw();
  }

  function renderWeek52(ctx) {
    const raw = ctx.files["scanner_52w.csv"];
    const all = D.realRows(raw);
    const hist = D.realRows(ctx.files["highs_lows_history.csv"]).slice().sort((a, b) => a.date < b.date ? -1 : 1);
    const yes = (r, key) => String(r[key] || "").toLowerCase() === "yes";
    const nHigh = countWhere(all, (r) => yes(r, "new_high_today"));
    const nLow = countWhere(all, (r) => yes(r, "new_low_today"));
    const nNear = countWhere(all, (r) => yes(r, "near_high"));
    const nVol = countWhere(all, (r) => yes(r, "high_on_volume"));
    const net = nHigh - nLow;
    const netText = net < 0 ? "−" + Math.abs(net) : String(net);
    const netColor = net > 0 ? "#22C55E" : net < 0 ? "#EF4444" : "#8B96AD";
    ctx.page.innerHTML =
      '<p class="cap">A 52-week high is the highest intraday price of the last 252 trading days, and a 52-week low is the lowest. New highs and new lows on this page use the close, so a name can touch a new high during the day and still not count if it does not close there. Near the high means the close is within 5% of that high. That band is the zone Minervini prefers. A high on big volume also needs volume at least 1.5 times the 50-day average. Research only. This page does not place trades or send alerts.</p>' +
      '<div class="cards" id="cards"></div>' +
      '<div class="panel pad"><div class="rowhead wrap"><div style="min-width:0;flex:1"><div class="ptitle">Highs and lows</div><div class="psub">Green bars are new highs. Red bars are new lows. The line is highs minus lows.</div></div>' +
      '<div class="seg" id="hlrange"><button type="button" data-d="92">3M</button><button type="button" data-d="183" class="on">6M</button><button type="button" data-d="365">1Y</button></div></div>' +
      '<div class="chart-box tall"><canvas id="hl"></canvas></div></div>' +
      '<div class="ctrls" id="ctrls"></div><div class="panel" id="tbl"></div>';
    document.getElementById("cards").innerHTML =
      card("New 52w highs today", '<span style="color:#22C55E">' + nHigh + "</span>") +
      card("New 52w lows today", '<span style="color:#EF4444">' + nLow + "</span>") +
      card("Near high (within 5%)", '<span style="color:#F59E0B">' + nNear + "</span>") +
      card("New highs on big volume", '<span style="color:#22C55E">' + nVol + "</span>", "At least 1.5× the 50-day average") +
      card("Net highs minus lows", '<span style="color:' + netColor + '">' + netText + "</span>");
    const tabs = [
      ["highs", "New highs"],
      ["lows", "New lows"],
      ["near", "Near high"],
      ["vol", "On volume"],
      ["all", "All"],
    ];
    const titles = {
      highs: "New highs today",
      lows: "New lows today",
      near: "Near the high",
      vol: "Breakout to a new high on volume",
      all: "All stocks",
    };
    const box = document.getElementById("ctrls");
    standardFilters(box, all, { index: true, sector: true, verdict: true, ticker: true, order: ["index", "sector", "verdict", "ticker"], list: "w52" });
    box.insertAdjacentHTML("afterbegin", '<div class="w52tabs" id="w52tabs">' + tabs.map((t, i) =>
      '<button type="button" data-tab="' + t[0] + '"' + (i === 0 ? ' class="on"' : "") + ">" + t[1] + "</button>").join("") + "</div>");
    D.placeFeed(box, raw);
    let tab = "highs";
    let days = 183;
    const state = { sort: "range_position_pct", dir: "desc", sort2: "score", dir2: "desc", page: 0 };
    const columns = [TK, CO, SE, PR,
      T("high_52w", "52w high", "num", { dec: 2 }), T("low_52w", "52w low", "num", { dec: 2 }),
      T("pct_from_high", "% from high", "pct", { dec: 1, color: true }),
      T("pct_above_low", "% above low", "pct", { dec: 1, color: true }),
      T("range_position_pct", "Range", "rangepos"),
      T("volume_ratio", "Vol ×", "volx", { dec: 2 }), SC, VE];
    const inTab = (r) => {
      if (tab === "highs") return yes(r, "new_high_today");
      if (tab === "lows") return yes(r, "new_low_today");
      if (tab === "near") return yes(r, "near_high");
      if (tab === "vol") return yes(r, "high_on_volume");
      return true;
    };
    const applySort = () => {
      if (tab === "lows") {
        state.sort = "pct_from_high"; state.dir = "asc"; state.sort2 = "score"; state.dir2 = "desc";
      } else {
        state.sort = "range_position_pct"; state.dir = "desc"; state.sort2 = "score"; state.dir2 = "desc";
      }
      state.page = 0;
    };
    const paint = () => {
      const rows = D.lastNDays(hist, "date", days).slice().sort((a, b) => a.date < b.date ? -1 : 1);
      D.destroyCharts();
      if (!rows.length) return;
      D.comboChart(document.getElementById("hl"), rows.map((r) => r.date), [
        { label: "New highs", data: D.seriesNum(rows, "new_highs"), color: "#22C55E" },
        { label: "New lows", data: D.seriesNum(rows, "new_lows"), color: "#EF4444" },
      ], { label: "Net", data: D.seriesNum(rows, "net"), color: "#7C9CFF" });
    };
    const draw = () => {
      D.drawTable(document.getElementById("tbl"), {
        title: titles[tab],
        rows: all.filter((r) => inTab(r) && readCommon(box, r)),
        columns: columns,
        state: state,
        pageSize: 25,
        expandable: true,
        lines: weekLines,
        priceSub: "52-week high and 52-week low",
        empty: "No names in this group.",
      });
    };
    box.querySelectorAll("#w52tabs button").forEach((btn) => {
      btn.addEventListener("click", () => {
        tab = btn.getAttribute("data-tab");
        box.querySelectorAll("#w52tabs button").forEach((b) => b.classList.toggle("on", b === btn));
        applySort();
        draw();
      });
    });
    document.getElementById("hlrange").addEventListener("click", (ev) => {
      const btn = ev.target.closest("button");
      if (!btn) return;
      days = Number(btn.getAttribute("data-d"));
      document.querySelectorAll("#hlrange button").forEach((b) => b.classList.toggle("on", b === btn));
      paint();
    });
    hook(box, state, draw);
    paint();
    draw();
  }

  function buyDetailHtml(row) {
    const px = (key) => {
      const n = D.num(row[key]);
      return n == null ? D.na() : D.esc(D.fmt(n, 2));
    };
    const gain = (key) => {
      const entry = D.num(row.entry);
      const value = D.num(row[key]);
      if (entry == null || value == null || entry === 0) return "";
      const pct = (value - entry) / entry * 100;
      const sign = pct > 0 ? "+" : pct < 0 ? "−" : "";
      return D.esc(sign + D.fmt(Math.abs(pct), 1) + "%");
    };
    const risk = D.num(row.risk_pct);
    const riskText = risk == null ? "" : D.esc(D.fmt(Math.abs(risk), 1) + "% risk");
    const rr = D.num(row.reward_risk);
    const rrText = rr == null || Math.abs(rr) > 500 ? D.na() : D.esc(D.fmt(rr, 2));
    const plan = (label, value, sub, tone) =>
      '<div class="tp' + (tone ? " " + tone : "") + '"><div class="l">' + D.esc(label) +
      '</div><div class="v">' + value + "</div>" + (sub ? '<div class="s">' + sub + "</div>" : "") + "</div>";
    const fact = (label, value) =>
      '<div class="fact"><div class="l">' + D.esc(label) + '</div><div class="v">' + value + "</div></div>";
    const rangeN = D.num(row.range_position_52w);
    let range = D.na();
    if (rangeN != null) {
      const clamped = Math.max(0, Math.min(100, rangeN));
      const w = Math.max(0, Math.round(clamped / 100 * 88));
      const color = clamped >= 95 ? "#22C55E" : clamped <= 15 ? "#EF4444" : "#7C9CFF";
      range = '<span class="track" title="' + D.esc(D.fmt(rangeN, 0)) + '"><span class="fill" style="width:' + w +
        'px;background:' + color + '"></span></span> ' + D.esc(D.fmt(rangeN, 0));
    }
    const asOfMatch = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(row.price_as_of || ""));
    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const asOf = asOfMatch ? D.esc(months[Number(asOfMatch[2]) - 1] + " " + Number(asOfMatch[3]) + ", " + asOfMatch[1]) :
      (D.isBlank(row.price_as_of) ? D.na() : D.esc(row.price_as_of));
    const mkt = String(row.market_ok || "").toLowerCase();
    const mktHtml = mkt === "yes" ? '<span style="color:#22C55E">yes</span>' :
      mkt === "no" ? '<span style="color:#EF4444">no</span>' :
      (D.isBlank(row.market_ok) ? D.na() : D.esc(row.market_ok));
    const count = D.num(row.sources_count);
    const why = String(row.reason || "").trim();
    return '<p class="whytext">' + (why ? D.esc(why) : '<span class="m2">No reason was saved for this name.</span>') + "</p>" +
      '<div class="tradeplan">' +
        plan("Entry", px("entry"), "", "") +
        plan("Stop", px("stop"), riskText, "stop") +
        plan("Target 1", px("target1"), gain("target1"), "tgt") +
        plan("Target 2", px("target2"), gain("target2"), "tgt") +
        plan("Reward/risk", rrText, "", "") +
      "</div>" +
      '<div class="buyfacts">' +
        fact("Sector", D.isBlank(row.sector) ? D.na() : D.esc(row.sector)) +
        fact("Index", D.isBlank(row.index_membership) ? D.na() : D.esc(row.index_membership)) +
        fact("Price", px("price")) +
        fact("As of", asOf) +
        fact("Count", count == null ? D.na() : D.esc(D.fmt(count, 0))) +
        fact("52w range", range) +
        fact("% from 52w high", D.pctHtml(row.pct_from_high_52w, 1, true)) +
        fact("Market ok", mktHtml) +
      "</div>";
  }
  function buyLines(row) {
    const lines = [];
    if (!row) return lines;
    const add = (key, color, label) => {
      const n = D.num(row[key]);
      if (n != null) lines.push({ value: n, color: color, label: label });
    };
    add("entry", "#F59E0B", "Entry");
    add("stop", "#EF4444", "Stop");
    add("target1", "#22C55E", "Target1");
    add("target2", "#7C9CFF", "Target2");
    return lines;
  }
  function renderBuySetups(ctx) {
    const raw = ctx.files["buy_setups.csv"];
    const fileRows = D.realRows(raw);
    const missing = (raw || []).some((r) => r.data_status === "MISSING");
    const named = fileRows.filter((r) => String(r.ticker || "").trim()).map((r) => {
      r.status = r.best_status;
      return r;
    });
    const market = fileRows[0] || {};
    const yes = (v) => String(v || "").toLowerCase() === "yes";
    const spyUp = yes(market.spy_uptrend || market.market_ok);
    const qqqUp = yes(market.qqq_uptrend);
    const filterOn = D.featureOn("buy_setups.market_filter");
    const marketDown = !missing && filterOn && !spyUp;
    const yn = (on) => on ? '<span style="color:#22C55E">yes</span>' : '<span style="color:#EF4444">no</span>';
    ctx.page.innerHTML =
      '<p class="cap">Research list, not a recommendation. This desk never places trades.</p>' +
      '<div id="buybanner" class="buybanner"></div>' +
      '<div class="cards" id="cards"></div>' +
      '<div class="ctrls" id="ctrls"></div>' +
      '<div class="panel" id="tbl"></div>' +
      '<p class="cap">A name is listed when at least one of VCP, Box, Flag, and CANSLIM is ready or broke out today, the desk verdict is BUY, the close is above the 50-day and 200-day averages, and the risk from the entry to the stop is 8% or less. Setup is which of those scanners agree. Count is how many agree. Status is the strongest one. Entry is that scanner\'s buy point. VCP uses the Minervini pivot. Stop is the tighter of 7% under the entry or the setup\'s own stop, and it is never above the entry. Target 1 is 20% above the entry, or 20% above today\'s close after a breakout. Target 2 is the entry plus three times the dollar risk. Reward/risk compares target 1 with that risk. Distance is how far the price is from the entry. The 52-week columns match the 52-week page. Tap a row for the reason, the trade plan, and the price chart. Many breakouts fail, which is why the stop is always shown. Nothing here is an alert.</p>';
    const box = document.getElementById("ctrls");
    box.innerHTML =
      D.multiHtml("index", "Index", D.indexTokens(named)) +
      D.multiHtml("sector", "Sector", D.uniq(named, "sector")) +
      D.multiHtml("source", "Setup", ["VCP", "Box", "Flag", "CANSLIM"]) +
      D.multiHtml("status", "Status", D.uniq(named, "status")) +
      D.searchHtml("ticker", "Ticker", "tick-list-buy", D.uniq(named, "ticker"));
    D.placeFeed(box, raw);
    let showAnyway = false;
    const state = { sort: "_ord", dir: "asc", page: 0 };
    const columns = [
      T("_ord", "", "num", { hidden: true }),
      TK, T("company", "Company", "text", { ellipsis: true }),
      T("setup_sources", "Setup", "text", { ellipsis: true }),
      T("best_status", "Status", "setup", { ellipsis: true }),
      T("entry", "Entry", "num", { dec: 2 }),
      T("stop", "Stop", "num", { dec: 2, tone: "stop" }),
      T("target1", "Target 1", "num", { dec: 2, tone: "target" }),
      T("target2", "Target 2", "num", { dec: 2, tone: "target" }),
      T("risk_pct", "Risk %", "pct", { dec: 1 }),
      T("reward_risk", "Reward/risk", "multiple", { dec: 2 }),
      T("dist_to_entry_pct", "Dist. to entry", "pct", { dec: 1, color: true }),
      SC, VE,
    ];
    const sourceOk = (row) => {
      const picked = D.selectedMulti(box, "source");
      if (!picked) return true;
      const parts = String(row.setup_sources || "").split("+").map((s) => s.trim());
      return picked.some((p) => parts.indexOf(p) >= 0);
    };
    const specOrder = (rows) => {
      const ranked = rows.slice().sort((a, b) => {
        const status = (r) => r.best_status === "BROKEN OUT today" ? 0 : 1;
        if (status(a) !== status(b)) return status(a) - status(b);
        const count = (r) => D.num(r.sources_count) || 0;
        if (count(a) !== count(b)) return count(b) - count(a);
        const dist = (r) => {
          const n = D.num(r.dist_to_entry_pct);
          return n == null ? Infinity : Math.abs(n);
        };
        if (dist(a) !== dist(b)) return dist(a) - dist(b);
        const score = (r) => {
          const n = D.num(r.score);
          return n == null ? -Infinity : n;
        };
        if (score(a) !== score(b)) return score(b) - score(a);
        return String(a.ticker || "").localeCompare(String(b.ticker || ""));
      });
      ranked.forEach((r, i) => { r._ord = i; });
      return ranked;
    };
    const draw = () => {
      const grey = marketDown && showAnyway;
      const pool = (marketDown && !showAnyway) ? [] : named.filter((r) => readCommon(box, r) && sourceOk(r));
      const rows = specOrder(pool);
      const kpis = (marketDown && !showAnyway) ? [] : named;
      const broken = countWhere(kpis, (r) => r.best_status === "BROKEN OUT today");
      const multi = countWhere(kpis, (r) => (D.num(r.sources_count) || 0) >= 2);
      const rr = avg(kpis, "reward_risk");
      document.getElementById("cards").innerHTML =
        card("Setups today", String(kpis.length)) +
        card("Broken out today", String(broken)) +
        card("Multi-scanner setups", String(multi), "At least two scanners agree") +
        card("Market status", missing ? D.na() : "SPY " + yn(spyUp), missing ? "" : "QQQ " + yn(qqqUp)) +
        card("Average reward-to-risk", rr == null ? D.na() : D.esc(D.fmt(rr, 2)), "Target 1 versus the stop");
      const banner = document.getElementById("buybanner");
      if (marketDown) {
        banner.hidden = false;
        banner.innerHTML = '<span>Market not in an uptrend today, so no buy setups are listed</span>' +
          '<button type="button" id="showanyway">' + (showAnyway ? "Hide greyed names" : "Show anyway") + "</button>";
        banner.querySelector("#showanyway").addEventListener("click", () => { showAnyway = !showAnyway; draw(); });
      } else {
        banner.hidden = true;
        banner.innerHTML = "";
      }
      const host = document.getElementById("tbl");
      host.classList.toggle("dimmed", grey);
      D.drawTable(host, {
        rows: rows,
        columns: columns,
        state: state,
        pageSize: 25,
        expandable: true,
        fit: true,
        lines: buyLines,
        priceSub: "Entry, stop, and both targets. The stop stays on the chart because many breakouts fail.",
        detail: buyDetailHtml,
        empty: marketDown && !showAnyway ? "No buy setups are listed." : (named.length ? "No names match these filters." : "No stock passed the buy-setup rules today."),
      });
    };
    hook(box, state, draw);
    draw();
  }

  function renderBreakouts(ctx) {
    const raw = ctx.files["breakouts.csv"];
    const all = D.realRows(raw);
    ctx.page.innerHTML = '<div class="ctrls" id="ctrls"></div><div class="cards" id="cards"></div><div class="panel" id="tbl"></div>' +
      '<p class="cap">Within 1% of the 52-week closing high. If the list is empty, nobody is near a high today: that is a result, and the note above says so.</p>';
    document.getElementById("cards").innerHTML =
      card("Near a 52-week high", String(all.length)) +
      card("With volume above average", String(countWhere(all, (r) => (D.num(r.volume_ratio) || 0) >= 1))) +
      card("Of those, BUY", String(countWhere(all, (r) => r.verdict === "BUY")));
    const box = document.getElementById("ctrls");
    standardFilters(box, all, { sector: true, verdict: true, ticker: true });
    const state = { sort: "dist_52w_high_pct", dir: "asc", page: 0 };
    const draw = () => D.drawTable(document.getElementById("tbl"), {
      rows: all.filter((r) => readCommon(box, r)),
      columns: [TK, CO, SE, PR, T("dist_52w_high_pct", "From 52-week high %", "pct", { dec: 2, color: false, abs: true }),
        T("volume_ratio", "Volume vs 50-day", "volx", { dec: 2 }), SC, VE],
      state: state, pageSize: 15, expandable: true,
      priceSub: "Daily price. Distance to the 52-week high stays in the row.",
    });
    hook(box, state, draw);
    draw();
  }

  function renderTrends(ctx) {
    const raw = ctx.files["trends.csv"];
    const all = D.realRows(raw);
    ctx.page.innerHTML = '<div class="ctrls" id="ctrls"></div><div class="cards" id="cards"></div><div class="panel" id="tbl"></div>' +
      '<p class="cap">Uptrend means the price is above all four averages. Downtrend means it is below all four.</p>';
    const colors = { Uptrend: "#22C55E", Mixed: "#8B96AD", Downtrend: "#EF4444" };
    document.getElementById("cards").innerHTML = ["Uptrend", "Mixed", "Downtrend"].map((lab) =>
      card(lab, '<span style="color:' + colors[lab] + '">' + countWhere(all, (r) => r.trend_label === lab) + "</span>")).join("");
    const box = document.getElementById("ctrls");
    const labels = ["Uptrend", "Mixed", "Downtrend"];
    box.innerHTML = '<div class="toggles" data-filter="trend">' + labels.map((o) =>
      '<button type="button" data-v="' + o + '"' + (o === "Uptrend" ? ' class="on"' : "") + ">" + o + "</button>").join("") + "</div>" +
      D.multiHtml("sector", "Sector", D.uniq(all, "sector")) +
      D.searchHtml("ticker", "Ticker", "trd", D.uniq(all, "ticker"));
    box.querySelectorAll(".toggles button").forEach((btn) => {
      btn.addEventListener("click", () => {
        btn.classList.toggle("on");
        state.page = 0;
        draw();
      });
    });
    const state = { sort: "score", dir: "desc", page: 0 };
    const pickedTrend = () => Array.from(box.querySelectorAll(".toggles button.on")).map((b) => b.getAttribute("data-v"));
    const draw = () => {
      const on = pickedTrend();
      D.drawTable(document.getElementById("tbl"), {
        rows: all.filter((r) => (on.length === labels.length || on.indexOf(r.trend_label) >= 0) &&
          D.matchMulti(r, "sector", D.selectedMulti(box, "sector")) && D.matchText(r, "ticker", D.fieldVal(box, "ticker"))),
        columns: [TK, CO, T("trend_label", "Trend", "trend"),
          T("above_sma20", "Above 20d", "flag", { no: "#EF4444" }), T("above_sma50", "Above 50d", "flag", { no: "#EF4444" }),
          T("above_sma100", "Above 100d", "flag", { no: "#EF4444" }), T("above_sma200", "Above 200d", "flag", { no: "#EF4444" }), SC],
        state: state, pageSize: 25, expandable: true,
        priceSub: "Daily price. Turn the moving averages on or off above the chart.",
      });
    };
    hook(box, state, draw);
    draw();
  }

  const pullbacks = passesPage({
    file: "pullbacks.csv",
    caption: "An uptrend (above the 50-day and the 200-day) with price back in the pullback or entry area, and RSI under 70.",
    captionAbove: true,
    pageSize: 20,
    filters: { passes: "yes", sector: true, verdict: true, ticker: true },
    lines: zoneLines,
    priceSub: "Pullback entry zone",
    columns: [TK, CO, PR, T("rsi14", "RSI-14", "num", { dec: 1 }), T("entry_low", "Entry low", "num", { dec: 2 }),
      T("entry_high", "Entry high", "num", { dec: 2 }), SC, VE],
    cards(all) {
      const pass = all.filter((r) => r.passes === "yes");
      return card("Pullback setups", String(pass.length)) +
        card("Of those, BUY", String(countWhere(pass, (r) => r.verdict === "BUY"))) +
        card("Average RSI-14, passing", ntext(avg(pass, "rsi14"), 1));
    },
  });

  function renderGainers(ctx) {
    const raw = ctx.files["gainers_losers.csv"];
    const all = D.realRows(raw);
    ctx.page.innerHTML = '<div class="ctrls" id="ctrls"></div><div class="split"><div class="panel" id="up"></div><div class="panel" id="dn"></div></div>' +
      '<p class="cap">Day % is the latest session\'s change, for stocks on the desk only.</p>';
    const box = document.getElementById("ctrls");
    standardFilters(box, all, { sector: true, verdict: true });
    const cols = [TK, CO, PR, T("day_pct", "Day %", "pct", { color: true }), SC, VE];
    const draw = () => {
      const rows = all.filter((r) => readCommon(box, r));
      D.drawTable(document.getElementById("up"), {
        title: "Biggest gainers today", rows: rows.filter((r) => r.side === "gainer"), columns: cols,
        state: { sort: "day_pct", dir: "desc", page: 0 }, pageSize: 15, expandable: true,
        priceSub: "Daily price",
      });
      D.drawTable(document.getElementById("dn"), {
        title: "Biggest losers today", rows: rows.filter((r) => r.side === "loser"), columns: cols,
        state: { sort: "day_pct", dir: "asc", page: 0 }, pageSize: 15, expandable: true,
        priceSub: "Daily price",
      });
    };
    hook(box, { page: 0 }, draw);
    draw();
  }

  function renderBreadth(ctx) {
    const raw = D.realRows(ctx.files["breadth_history.csv"]);
    const mt = (ctx.files["market_today.csv"] || [])[0] || {};
    const end = maxDate(raw, "date");
    ctx.page.innerHTML = '<div class="ctrls" id="ctrls"></div><div class="cards" id="cards"></div>' +
      '<div class="panel pad"><div class="ptitle">Share of the desk above each average</div><div class="chart-box htall"><canvas id="br"></canvas></div></div>' +
      '<p class="cap">A blank point is a session that did not have enough prices. The gap is left open, never drawn as zero.</p>';
    const now50 = D.num(mt.breadth_sma50);
    const prev50 = D.num(mt.breadth_sma50_week_ago);
    const delta = now50 != null && prev50 != null ? now50 - prev50 : null;
    const keys = [["breadth_sma20", "% above 20-day", ""], ["breadth_sma50", "% above 50-day", "week"], ["breadth_sma100", "% above 100-day", ""], ["breadth_sma200", "% above 200-day", ""]];
    document.getElementById("cards").innerHTML = keys.map((k) => {
      const sub = k[2] && delta != null ? '<span style="color:' + D.retColor(delta) + '">' + (delta > 0 ? "+" : "") + D.fmt(delta, 1) + " pts vs week ago</span>" : "";
      return card(k[1], D.num(mt[k[0]]) == null ? D.na() : D.esc(D.fmt(mt[k[0]], 1) + "%"), sub);
    }).join("");
    const box = document.getElementById("ctrls");
    box.innerHTML = D.dateHtml("from", "From", shift(end, -182));
    const draw = () => {
      const from = D.fieldVal(box, "from");
      const rows = raw.filter((r) => !from || r.date >= from);
      D.destroyCharts();
      D.lineChart(document.getElementById("br"), rows.map((r) => r.date), [
        { label: "Above 20-day", data: D.seriesNum(rows, "pct_above_sma20"), color: "#7C9CFF" },
        { label: "Above 50-day", data: D.seriesNum(rows, "pct_above_sma50"), color: "#E6EBF5" },
        { label: "Above 100-day", data: D.seriesNum(rows, "pct_above_sma100"), color: "#F59E0B" },
        { label: "Above 200-day", data: D.seriesNum(rows, "pct_above_sma200"), color: "#8B96AD" },
      ], { y: { min: 0, max: 100 } });
    };
    D.wireFilters(box, draw);
    draw();
  }

  function renderSecPerf(ctx) {
    const raw = ctx.files["sector_performance.csv"];
    const all = D.realRows(raw);
    ctx.page.innerHTML = '<div class="ctrls" id="ctrls"></div>' +
      '<p class="cap">Equal weight across the desk\'s stocks in each sector, not the sector ETF. The ETF view is on Today.</p>' +
      '<div class="panel pad"><div class="ptitle">Past month, equal-weight %</div><div class="chart-box h300"><canvas id="sp"></canvas></div></div><div class="panel" id="tbl"></div>';
    const box = document.getElementById("ctrls");
    box.innerHTML = D.multiHtml("sector", "Sector", D.uniq(all, "sector")) + D.rangeHtml("min", "Min. stocks", 1, 200, 5, 1);
    const state = { sort: "month_pct", dir: "desc", page: 0 };
    const draw = () => {
      const rows = all.filter((r) => D.matchMulti(r, "sector", D.selectedMulti(box, "sector")) && D.matchMin(r, "n", D.fieldVal(box, "min")));
      const ordered = rows.slice().sort((a, b) => (D.num(b.month_pct) || -999) - (D.num(a.month_pct) || -999));
      D.destroyCharts();
      D.barChart(document.getElementById("sp"), ordered.map((r) => r.sector), ordered.map((r) => D.num(r.month_pct)),
        ordered.map((r) => (D.num(r.month_pct) || 0) >= 0 ? "#1F9D55" : "#D14343"),
        { horizontal: true, labels: true, dec: 1, suffix: "%",
          x: { ticks: { color: "#5B6680", callback: (v) => { const n = Number(v); const sign = n > 0 ? "+" : n < 0 ? "−" : ""; return sign + Math.abs(n) + "%"; } }, grid: { color: "#1E293B" } } });
      D.drawTable(document.getElementById("tbl"), {
        rows: rows,
        columns: [SE, T("day_pct", "Day %", "pct", { color: true }), T("week_pct", "Week %", "pct", { color: true }), T("month_pct", "Month %", "pct", { color: true }),
          T("month3_pct", "3 months %", "pct", { color: true }), T("ytd_pct", "YTD %", "pct", { color: true }), T("pct_above_sma50", "% above 50-day", "pct", { dec: 1, color: false }),
          T("score_avg", "Average score", "num", { dec: 1 }), T("n", "Stocks", "num", { dec: 0 })],
        state: state, pageSize: 15, foot: false,
      });
    };
    hook(box, state, draw);
    draw();
  }

  function renderHeatmaps(ctx) {
    const raw = ctx.files["heatmaps.csv"];
    const all = D.realRows(raw);
    ctx.page.innerHTML = '<div class="ctrls" id="ctrls"></div>' +
      '<p class="cap">Each cell is that stock\'s own return. The sector column on the right is the plain average of the desk\'s stocks, not the ETF.</p>' +
      '<div class="split hm"><div class="panel" id="tbl"></div><div class="panel" id="avg"></div></div>';
    const box = document.getElementById("ctrls");
    box.innerHTML = D.multiHtml("sector", "Sector", D.uniq(all, "sector")) +
      D.selectHtml("above", "Above 200-day", [{ value: "1", label: "Yes" }, { value: "0", label: "No" }], "") +
      D.searchHtml("ticker", "Ticker", "ht", D.uniq(all, "ticker"));
    const state = { sort: "ret_1d", dir: "desc", page: 0 };
    const draw = () => {
      const above = D.fieldVal(box, "above");
      const rows = all.filter((r) => D.matchMulti(r, "sector", D.selectedMulti(box, "sector")) &&
        D.matchText(r, "ticker", D.fieldVal(box, "ticker")) &&
        (!above || String(D.num(r.above_sma200)) === above || r.above_sma200 === (above === "1" ? "yes" : "no")));
      D.drawTable(document.getElementById("tbl"), {
        rows: rows,
        columns: [TK, CO, T("ret_1d", "1 day %", "heatpct", { dec: 1 }), T("ret_1w", "1 week %", "heatpct", { dec: 1 }),
          T("ret_1m", "1 month %", "heatpct", { dec: 1 }), T("ret_ytd", "YTD %", "heatpct", { dec: 1 }),
          T("above_sma20", "20d", "flag"), T("above_sma50", "50d", "flag"), T("above_sma100", "100d", "flag"), T("above_sma200", "200d", "flag")],
        state: state, pageSize: 25, expandable: true,
        priceSub: "Daily price",
      });
      const sectors = D.uniq(rows, "sector").map((s) => {
        const sub = rows.filter((r) => r.sector === s);
        return { sector: s, ret_1d: avg(sub, "ret_1d") == null ? "" : String(avg(sub, "ret_1d")) };
      });
      D.drawTable(document.getElementById("avg"), {
        title: "Sector average, 1 day %", rows: sectors,
        columns: [SE, T("ret_1d", "1 day %", "heatpct", { dec: 2 })],
        state: { sort: "ret_1d", dir: "desc", page: 0 }, pageSize: 15, foot: false,
      });
    };
    hook(box, state, draw);
    draw();
  }

  function renderRotation(ctx) {
    const raw = ctx.files["sector_rotation.csv"] || [];
    const rows = D.realRows(raw);
    const tails = D.realRows(ctx.files["sector_rotation_tails.csv"] || []);
    const scores = D.realRows(ctx.files["scores.csv"] || []);
    const colors = {
      XLK: "#7C9CFF", XLV: "#22C55E", XLF: "#F59E0B", XLI: "#38BDF8", XLC: "#A78BFA",
      XLY: "#FB7185", XLP: "#FBBF24", XLE: "#EF4444", XLU: "#2DD4BF", XLRE: "#C084FC", XLB: "#94A3B8",
    };
    const ranked = rows.slice().sort((a, b) => (D.num(a.rank) || 99) - (D.num(b.rank) || 99) || String(a.ticker).localeCompare(b.ticker));
    let tf = "W";
    let tailN = 8;
    let pick = ranked[0] ? ranked[0].ticker : "";
    const head = ranked[0] || {};
    const weeklyChanges = rows.filter((r) => String(r.change_weekly || "").indexOf("moved from") >= 0);
    const dailyChanges = rows.filter((r) => String(r.change_daily || "").indexOf("moved from") >= 0);
    const sample = rows[0] || {};
    ctx.page.innerHTML =
      '<div class="ctrls" id="ctrls"></div>' +
      '<p class="cap">RS is the sector ETF divided by SPY. RS-Ratio is 100 plus the z-score of that ratio, smoothed, versus its rolling mean. RS-Momentum is 100 plus the z-score of how fast RS-Ratio is changing. 100 is the center. This is a desk calculation, not the commercial JdK indicator. Research only. This desk never places trades and it does not send a notification.</p>' +
      '<div class="cards" id="cards"></div>' +
      '<div class="panel pad"><div class="ptitle">Relative rotation</div><div class="chart-box rrg-box"><canvas id="rrg"></canvas></div><div class="rrglegend" id="rrglegend"></div><div class="rrgread" id="rrgread">Tap a point to read RS-Ratio and RS-Momentum.</div></div>' +
      '<div class="split"><div class="panel pad" id="macro"></div><div class="panel pad" id="changed"></div></div>' +
      '<div class="panel" id="tbl"></div><div class="panel" id="names"></div>';
    document.getElementById("ctrls").innerHTML =
      '<div class="rrgtabs" id="rrgtf">' +
      '<button type="button" data-tf="D">Daily</button><button type="button" data-tf="W" class="on">Weekly</button><button type="button" data-tf="M">Monthly</button></div>' +
      '<div class="rrgtabs" id="rrgtail"><span class="lab">Tail</span>' +
      '<button type="button" data-n="4">4</button><button type="button" data-n="8" class="on">8</button><button type="button" data-n="12">12</button></div>';
    D.placeFeed(document.getElementById("ctrls"), raw);
    const leadN = countWhere(rows, (r) => r.quadrant_w === "Leading");
    const lagN = countWhere(rows, (r) => r.quadrant_w === "Lagging");
    document.getElementById("cards").innerHTML =
      card("Top sector", D.esc(head.name || "n/a"), head.score != null && head.score !== "" ? "Score " + D.fmt(D.num(head.score), 1) : "") +
      card("Leading", String(leadN), "Weekly") +
      card("Lagging", String(lagN), "Weekly") +
      card("Quadrant changes", String(weeklyChanges.length), "Versus last week") +
      card("10-year yield", D.esc(sample.dgs10_trend || "missing"), "About 3 months");
    function tendency(trend, downText, upText, flatText, missingText) {
      if (trend === "down") return downText;
      if (trend === "up") return upText;
      if (trend === "flat") return flatText;
      return missingText;
    }
    const yTrend = sample.dgs10_trend || "missing";
    const cTrend = sample.t10y2y_trend || "missing";
    const yLast = D.num(sample.dgs10_last);
    const cLast = D.num(sample.t10y2y_last);
    document.getElementById("macro").innerHTML =
      '<div class="ptitle">Macro backdrop</div>' +
      '<p class="cap">General tendencies, not a forecast. The trend is the latest reading versus about 63 observations earlier. Dollar, oil, and gold are not in the cached prices or the FRED files this desk already keeps.</p>' +
      '<p><strong>10-year yield</strong> ' + D.esc(yTrend) + (yLast == null ? "" : " · " + D.fmt(yLast, 2)) + ". " +
      D.esc(tendency(yTrend,
        "Falling rates have historically tended to favor Technology, Real Estate, and Utilities.",
        "Rising rates have historically tended to favor Financials.",
        "Falling rates have historically tended to favor Technology, Real Estate, and Utilities. Rising rates have historically tended to favor Financials.",
        "The 10-year yield is not on file.")) + "</p>" +
      '<p style="margin-top:8px"><strong>10-year minus 2-year</strong> ' + D.esc(cTrend) + (cLast == null ? "" : " · " + D.fmt(cLast, 2)) + ". " +
      D.esc(tendency(cTrend,
        "A flatter or more negative curve has historically tended to favor Consumer Staples, Utilities, and Health Care.",
        "A steeper curve has historically tended to favor Financials and Industrials.",
        "A steeper curve has historically tended to favor Financials and Industrials. A flatter curve has historically tended to favor Consumer Staples, Utilities, and Health Care.",
        "The yield curve is not on file.")) + "</p>" +
      '<p class="cap" style="margin-top:8px">Dollar: not on file. A strong dollar has historically tended to favor domestic companies over multinationals. There is no current reading.</p>' +
      '<p class="cap">Oil: not on file. Rising oil has historically tended to favor Energy. There is no current reading.</p>' +
      '<p class="cap">Gold: not on file. This desk has no gold series, so there is no current reading and no sector map for it.</p>';
    const lines = [];
    dailyChanges.forEach((r) => lines.push(r.change_daily + " since yesterday."));
    weeklyChanges.forEach((r) => lines.push(r.change_weekly + " since last week."));
    document.getElementById("changed").innerHTML = '<div class="ptitle">What changed</div>' +
      (lines.length ? '<ul class="changed">' + lines.map((t) => "<li>" + D.esc(t) + "</li>").join("") + "</ul>"
        : '<p class="cap">No sector changed quadrant versus yesterday or last week.</p>');
    document.getElementById("rrglegend").innerHTML = ranked.map((r) =>
      '<span><i class="rrgdot" style="background:' + (colors[r.ticker] || "#8B96AD") + '"></i>' + D.esc(r.ticker) + "</span>").join("") +
      '<span><i class="rrgdot" style="background:#22C55E"></i>Leading</span>' +
      '<span><i class="rrgdot" style="background:#F59E0B"></i>Weakening</span>' +
      '<span><i class="rrgdot" style="background:#EF4444"></i>Lagging</span>' +
      '<span><i class="rrgdot" style="background:#7C9CFF"></i>Improving</span>';
    const state = { sort: "rank", dir: "asc", page: 0 };
    function pointsFor(ticker) {
      return tails.filter((r) => r.timeframe === tf && r.ticker === ticker)
        .sort((a, b) => (D.num(a.tail_index) || 0) - (D.num(b.tail_index) || 0))
        .slice(-tailN)
        .map((r) => ({ x: D.num(r.rs_ratio), y: D.num(r.rs_momentum), date: r.date, name: r.name, ticker: r.ticker }))
        .filter((p) => p.x != null && p.y != null);
    }
    function showReadout(p) {
      const q = p.x >= 100 && p.y >= 100 ? "Leading" : p.x >= 100 ? "Weakening" : p.y >= 100 ? "Improving" : "Lagging";
      document.getElementById("rrgread").textContent =
        p.ticker + " · " + (p.name || "") + " · " + p.date + " · RS-Ratio " + D.fmt(p.x, 2) + " · RS-Momentum " + D.fmt(p.y, 2) + " · " + q;
    }
    function drawChart() {
      D.destroyCharts();
      const canvas = document.getElementById("rrg");
      const sets = ranked.map((r) => {
        const data = pointsFor(r.ticker);
        const color = colors[r.ticker] || "#8B96AD";
        return { label: r.ticker, data: data, color: color, name: r.name };
      }).filter((s) => s.data.length);
      let minX = 100, maxX = 100, minY = 100, maxY = 100;
      sets.forEach((s) => s.data.forEach((p) => {
        minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x);
        minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y);
      }));
      const padX = Math.max(2, (maxX - minX) * 0.14);
      const padY = Math.max(2, (maxY - minY) * 0.14);
      const quadPlugin = {
        id: "rrgQuad",
        beforeDatasetsDraw(chart) {
          const area = chart.chartArea;
          const xs = chart.scales.x;
          const ys = chart.scales.y;
          if (!area || !xs || !ys) return;
          const x0 = xs.getPixelForValue(100);
          const y0 = ys.getPixelForValue(100);
          const ctx2 = chart.ctx;
          ctx2.save();
          function fill(x1, y1, x2, y2, color) {
            ctx2.fillStyle = color;
            ctx2.globalAlpha = 0.28;
            ctx2.fillRect(Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1), Math.abs(y2 - y1));
          }
          fill(x0, area.top, area.right, y0, "#22C55E");
          fill(x0, y0, area.right, area.bottom, "#F59E0B");
          fill(area.left, y0, x0, area.bottom, "#EF4444");
          fill(area.left, area.top, x0, y0, "#7C9CFF");
          ctx2.globalAlpha = 1;
          ctx2.strokeStyle = "#94A3B8";
          ctx2.lineWidth = 1.25;
          ctx2.beginPath();
          ctx2.moveTo(x0, area.top); ctx2.lineTo(x0, area.bottom);
          ctx2.moveTo(area.left, y0); ctx2.lineTo(area.right, y0);
          ctx2.stroke();
          ctx2.font = "11px Roboto, Arial, sans-serif";
          ctx2.fillStyle = "#8B96AD";
          ctx2.textAlign = "left";
          ctx2.fillText("Improving", area.left + 6, area.top + 14);
          ctx2.textAlign = "right";
          ctx2.fillText("Leading", area.right - 6, area.top + 14);
          ctx2.fillText("Weakening", area.right - 6, area.bottom - 6);
          ctx2.textAlign = "left";
          ctx2.fillText("Lagging", area.left + 6, area.bottom - 6);
          ctx2.restore();
        },
        afterDatasetsDraw(chart) {
          const ctx2 = chart.ctx;
          ctx2.save();
          ctx2.font = "11px Roboto, Arial, sans-serif";
          ctx2.fillStyle = "#E6EBF5";
          ctx2.textAlign = "left";
          const n = chart.data.datasets.length || 1;
          chart.data.datasets.forEach((ds, i) => {
            const meta = chart.getDatasetMeta(i);
            if (!meta.data.length) return;
            const pt = meta.data[meta.data.length - 1];
            const ang = (-Math.PI / 2) + (i / n) * Math.PI * 2;
            ctx2.fillText(ds.label, pt.x + Math.cos(ang) * 16, pt.y + Math.sin(ang) * 14);
          });
          ctx2.restore();
        },
      };
      D.makeChart(canvas, {
        type: "scatter",
        data: {
          datasets: sets.map((s) => ({
            label: s.label,
            data: s.data,
            showLine: true,
            borderColor: s.color,
            backgroundColor: s.color,
            borderWidth: 1.5,
            pointRadius: s.data.map((_, i) => i === s.data.length - 1 ? 6 : 2.5),
            pointHoverRadius: 8,
            pointHitRadius: 16,
            tension: 0,
          })),
        },
        plugins: [quadPlugin],
        options: {
          responsive: true,
          maintainAspectRatio: false,
          animation: false,
          interaction: { mode: "nearest", intersect: false },
          plugins: { legend: { display: false }, tooltip: { enabled: false } },
          layout: { padding: { top: 16, right: 28, bottom: 4, left: 4 } },
          scales: {
            x: { min: minX - padX, max: maxX + padX, ticks: { color: "#8B96AD" }, grid: { color: "#1E293B" }, title: { display: true, text: "RS-Ratio", color: "#8B96AD" } },
            y: { min: minY - padY, max: maxY + padY, ticks: { color: "#8B96AD" }, grid: { color: "#1E293B" }, title: { display: true, text: "RS-Momentum", color: "#8B96AD" } },
          },
          onHover(evt, els, chart) {
            if (!els.length || !chart) return;
            const ds = chart.data.datasets[els[0].datasetIndex];
            showReadout(ds.data[els[0].index]);
          },
          onClick(evt, els, chart) {
            if (!els.length || !chart) return;
            const ds = chart.data.datasets[els[0].datasetIndex];
            showReadout(ds.data[els[0].index]);
          },
        },
      });
      if (!sets.length) {
        document.getElementById("rrgread").textContent = "No rotation points for this bar size yet.";
      }
    }
    function drawNames() {
      const row = ranked.find((r) => r.ticker === pick) || ranked[0];
      const host = document.getElementById("names");
      if (!row) {
        host.innerHTML = "";
        return;
      }
      const names = scores.filter((r) => r.sector === row.sector)
        .sort((a, b) => (D.num(b.score) || -999) - (D.num(a.score) || -999))
        .slice(0, 12);
      D.drawTable(host, {
        title: "Top stocks in " + row.name,
        sub: row.reason || "",
        rows: names,
        columns: [T("ticker", "Ticker", "ticker"), T("company", "Company", "text"), T("score", "Score", "num", { dec: 0 }), T("verdict", "Verdict", "verdict")],
        state: { sort: "score", dir: "desc", page: 0 },
        pageSize: 12,
        foot: false,
        expandable: true,
        lines: zoneLines,
        priceSub: "Entry zone, stop, and target when the score has them",
        empty: "No scored stocks in this sector.",
      });
    }
    function drawTable() {
      D.drawTable(document.getElementById("tbl"), {
        title: "Sectors",
        rows: ranked,
        columns: [
          T("rank", "Rank", "num", { dec: 0 }),
          T("ticker", "ETF", "etf"),
          T("name", "Sector"),
          T("score", "Score", "num", { dec: 1 }),
          T("quadrant_d", "D", "quad"),
          T("quadrant_w", "W", "quad"),
          T("quadrant_m", "M", "quad"),
          T("rs_1m", "RS 1m", "pct", { dec: 1, color: true }),
          T("rs_3m", "RS 3m", "pct", { dec: 1, color: true }),
          T("rs_6m", "RS 6m", "pct", { dec: 1, color: true }),
          T("breadth_sma50", "Above 50d", "pct", { dec: 0 }),
          T("breadth_sma200", "Above 200d", "pct", { dec: 0 }),
          T("near_high_count", "Near high", "num", { dec: 0 }),
          T("buy_setup_count", "Buy setups", "num", { dec: 0 }),
          T("score_avg", "Desk avg", "num", { dec: 1 }),
          T("buy_share", "BUY %", "pct", { dec: 0 }),
          T("reason", "Reason", "text", { ellipsis: true }),
        ],
        state: state,
        pageSize: 15,
        foot: false,
        pick: pick,
        onPick(row) { pick = row.ticker; drawTable(); drawNames(); },
        empty: "No sector rotation on file.",
      });
    }
    document.getElementById("rrgtf").querySelectorAll("button").forEach((btn) => {
      btn.addEventListener("click", () => {
        tf = btn.getAttribute("data-tf");
        document.querySelectorAll("#rrgtf button").forEach((b) => b.classList.toggle("on", b === btn));
        drawChart();
      });
    });
    document.getElementById("rrgtail").querySelectorAll("button").forEach((btn) => {
      btn.addEventListener("click", () => {
        tailN = Number(btn.getAttribute("data-n"));
        document.querySelectorAll("#rrgtail button").forEach((b) => b.classList.toggle("on", b === btn));
        drawChart();
      });
    });
    drawChart();
    drawTable();
    drawNames();
  }

  function renderUpdates(ctx) {
    const log = ctx.files["updates_log.csv"] || [];
    const fresh = D.realRows(ctx.files["freshness.csv"]);
    const featureName = {
      "aaii sentiment": "AAII",
      "institutional 13f": "13F tracker",
      "historical pe": "Historical P/E",
      "xly xlp": "XLY/XLP",
      "put call": "Put/call",
      "option walls": "Put and call walls",
      "analyst ratings": "Analyst ratings",
      "insider trading": "Insider trading",
      "headline sentiment": "Headline sentiment",
      "financials summary": "Financials summary",
      "company financials": "Company financials",
      "earnings tracker": "Earnings tracker",
      "earnings calendar": "Calendar",
      "earnings heatmap": "Strength heatmap",
      "verdicts": "Verdicts",
      "backtest": "Backtest",
      "alerts": "Alerts",
      "universe": "Universe",
      "scorecard": "Stock scorecard",
      "breakouts": "52-week breakouts",
      "trends": "Trends",
      "pullbacks": "Pullbacks",
      "gainers losers": "Gainers and losers",
      "breadth": "Breadth",
      "sector performance": "Sector performance",
      "heatmaps": "Heatmaps",
      "updates log": "Data updates",
      "help": "Help",
      "earnings cards": "Report cards",
      "dividend scanner": "Dividend fundamentals",
      "macro screener": "Macro screener",
      "sector rotation": "Sector rotation",
      "scanner growth": "Growth",
      "scanner quality": "Quality",
      "scanner dividend": "Dividend",
      "scanner wheel": "Wheel",
      "scanner vcp": "VCP",
      "scanner canslim": "CANSLIM",
      "scanner box": "Box breakout",
      "scanner flag": "Flag breakout",
      "scanner leaders": "Leaders",
      "scanner 52w": "52-week",
      "top stocks": "Top stocks",
      "buy setups": "Buy setups",
      "top sectors": "Today's sectors",
      "watchlist portfolio": "Watchlist and portfolio",
      "score breakdown": "Score breakdown",
      "freshness flags": "Freshness",
      "news earnings summaries": "News",
      "momentum timing": "Timing",
    };
    const features = (ctx.settings || []).filter((r) => String(r.setting || "").indexOf("feature.") === 0).map((r) => {
      const key = String(r.setting).replace(/^feature\./, "").replace(/_/g, " ");
      const on = String(r.value || "").toLowerCase();
      const live = on === "true" || on === "yes" || on === "1";
      return { name: featureName[key] || key, on: live };
    });
    ctx.page.innerHTML = '<div class="ctrls" id="ctrls"></div><div class="panel pad"><div class="ptitle">Feature switches</div><div class="featgrid">' +
      features.map((f) => '<div><span>' + D.esc(f.name) + '</span><span style="color:' + (f.on ? "#22C55E" : "#8B96AD") + '">' + (f.on ? "On" : "Off") + "</span></div>").join("") +
      '</div></div><div class="split r21"><div class="panel" id="log"></div><div class="panel" id="fr"></div></div>';
    const box = document.getElementById("ctrls");
    box.innerHTML = D.multiHtml("status", "Status", D.uniq(log, "status"));
    const draw = () => {
      D.drawTable(document.getElementById("log"), {
        title: "Updates log",
        rows: log.filter((r) => D.matchMulti(r, "status", D.selectedMulti(box, "status"))),
        columns: [T("checked_pt", "Checked", "checked"), T("source", "Source", "text", { width: "160px" }), T("status", "Status", "fresh"),
          T("latest", "Latest"), T("note", "Note", "text", { wrap: true })],
        state: { sort: "checked_pt", dir: "desc", page: 0 }, pageSize: 25,
      });
      const host = document.getElementById("fr");
      const rows = fresh.slice().sort((a, b) => (D.num(b.n_missing) || 0) - (D.num(a.n_missing) || 0));
      host.innerHTML = '<div class="pad" style="padding-bottom:0"><div class="ptitle">Fields filled in, of 523</div></div><div class="scroll"><table><thead><tr><th>Field</th><th class="num">On file</th><th class="num">Missing</th></tr></thead><tbody>' +
        rows.map((r) => {
          const miss = D.num(r.n_missing) || 0;
          return "<tr><td>" + D.esc(r.field) + '</td><td class="num">' + D.esc(r.n_present) + '</td><td class="num" style="color:' +
            (miss > 0 ? "#F59E0B" : "#8B96AD") + '">' + D.esc(String(miss)) + "</td></tr>";
        }).join("") + "</tbody></table></div>";
    };
    hook(box, { page: 0 }, draw);
    draw();
  }

  function renderHelp(ctx) {
    const help = ctx.files["help.csv"] || [];
    const settings = ctx.files["settings.csv"] || [];
    ctx.page.innerHTML = '<div class="ctrls" id="ctrls"></div><div class="panel" id="help"></div><div class="panel w740" id="set"></div>';
    const box = document.getElementById("ctrls");
    box.innerHTML = D.searchHtml("topic", "Topic", "topics", D.uniq(help, "topic")) +
      '<label class="ctl"><span class="lab">Setting contains</span><input data-filter="setting" placeholder="Search settings"></label>';
    const draw = () => {
      const topic = (D.fieldVal(box, "topic") || "").trim().toLowerCase();
      const setting = (D.fieldVal(box, "setting") || "").trim().toLowerCase();
      D.drawTable(document.getElementById("help"), {
        title: "What the words mean",
        rows: help.filter((r) => !topic || (r.topic || "").toLowerCase().indexOf(topic) >= 0),
        columns: [T("topic", "Topic", "text"), T("plain_english", "What it means", "text", { wrap: true })],
        state: { sort: "topic", dir: "asc", page: 0 }, pageSize: 25,
      });
      D.drawTable(document.getElementById("set"), {
        title: "Settings", sub: "Edit these in the sheet's settings tab.",
        rows: settings.filter((r) => !setting || (r.setting || "").toLowerCase().indexOf(setting) >= 0),
        columns: [T("setting", "Setting"), T("value", "Value", "onoff", { wrap: true })],
        state: { sort: "setting", dir: "asc", page: 0 }, pageSize: 12,
      });
    };
    hook(box, { page: 0 }, draw);
    draw();
  }

  window.DESK_PAGES = {
    today: { files: ["market_today.csv", "breadth_history.csv", "sectors.csv", "alerts.csv"], render: renderToday },
    top: { files: ["scores.csv"], render: renderTop },
    buysetups: { files: ["buy_setups.csv"], render: renderBuySetups },
    scorecard: { files: ["scores.csv", "score_details.csv", "news.csv", "earnings_history.csv"], render: renderScorecard },
    watchlist: { files: ["portfolio.csv", "portfolio_summary.csv", "watchlist.csv"], render: renderWatch },
    alerts: { files: ["alerts.csv", "score_changes.csv"], render: renderAlerts },
    backtest: { files: ["backtest_summary.csv", "backtest_equity.csv", "backtest_buckets.csv", "backtest_yearly.csv", "backtest_notes.csv"], render: renderBacktest },
    growth: growth,
    quality: quality,
    dividend: dividend,
    wheel: wheel,
    vcp: vcp,
    canslim: canslim,
    box: box,
    flag: flag,
    leaders: leaders,
    week52: { files: ["scanner_52w.csv", "highs_lows_history.csv"], render: renderWeek52 },
    calendar: { files: ["earnings_calendar.csv"], render: renderCalendar },
    heatmap: { files: ["earnings_heatmap.csv"], render: renderHeat },
    cards: { files: ["earnings_cards.csv"], render: renderCards },
    putcall: { files: ["put_call.csv"], render: renderPutCall },
    walls: { files: ["option_walls.csv", "scores.csv"], render: renderWalls },
    analysts: { files: ["analyst_ratings.csv"], render: renderAnalysts },
    thirteen: { files: ["institutional_13f.csv"], render: render13f },
    aaii: { files: ["aaii_sentiment.csv"], render: renderAaii },
    insiders: { files: ["insider_trading.csv"], render: renderInsiders },
    headlines: { files: ["headline_sentiment.csv"], render: renderHeadlines },
    xly: { files: ["xly_xlp.csv"], render: renderXly },
    financials: { files: ["financials_summary.csv"], render: renderFinancials },
    tracker: { files: ["earnings_tracker.csv"], render: renderTracker },
    company: { files: ["company_financials.csv"], render: renderCompany },
    divfund: { files: ["dividend_scanner.csv"], render: renderDivFund },
    rotation: { files: ["sector_rotation.csv", "sector_rotation_tails.csv", "scores.csv"], render: renderRotation },
    macro: { files: ["macro_screener.csv"], render: renderMacro },
    secmacro: { files: ["sector_macro.csv", "sectors.csv"], render: renderSecMacro },
    histpe: { files: ["historical_pe.csv"], render: renderHist },
    breakouts: { files: ["breakouts.csv"], render: renderBreakouts },
    trends: { files: ["trends.csv"], render: renderTrends },
    pullbacks: pullbacks,
    gainers: { files: ["gainers_losers.csv"], render: renderGainers },
    breadth: { files: ["breadth_history.csv", "market_today.csv"], render: renderBreadth },
    secperf: { files: ["sector_performance.csv"], render: renderSecPerf },
    heatmaps: { files: ["heatmaps.csv"], render: renderHeatmaps },
    updates: { files: ["updates_log.csv", "freshness.csv"], render: renderUpdates },
    help: { files: ["help.csv", "settings.csv"], render: renderHelp },
  };

  D.boot();
})();
