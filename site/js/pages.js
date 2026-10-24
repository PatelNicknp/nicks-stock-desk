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

  function standardFilters(box, all, opts) {
    opts = opts || {};
    const parts = [];
    if (opts.passes) parts.push(D.selectHtml("passes", "Passes screen", ["yes", "no"], opts.passes));
    if (opts.status) {
      const statuses = D.uniq(all, "status");
      const picked = (opts.statusDefault || []).filter((s) => statuses.indexOf(s) >= 0);
      parts.push(D.multiHtml("status", "Status", statuses, picked));
    }
    if (opts.single) opts.single.forEach((s) => parts.push(D.selectHtml(s.key, s.label, D.uniq(all, s.key), s.value || "")));
    if (opts.sector) parts.push(D.multiHtml("sector", "Sector", D.uniq(all, "sector")));
    if (opts.verdict) parts.push(D.multiHtml("verdict", "Verdict", D.uniq(all, "verdict")));
    if (opts.confidence) parts.push(D.multiHtml("confidence", "Confidence", D.uniq(all, "confidence")));
    if (opts.index) parts.push(D.multiHtml("index", "Index", D.indexTokens(all)));
    if (opts.trend) parts.push(D.multiHtml("timing", "Trend", D.uniq(all, "timing")));
    if (opts.ticker) parts.push(D.searchHtml("ticker", "Ticker", "tick-list", D.uniq(all, "ticker")));
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
        ctx.page.innerHTML = D.banner(raw) + '<div id="notice"></div><div class="ctrls" id="ctrls"></div>' +
          '<div class="cards" id="cards"></div><div class="panel" id="tbl"></div><p class="cap"></p>';
        const notice = cfg.notice ? cfg.notice(all, raw) : "";
        document.getElementById("notice").innerHTML = notice || "";
        ctx.page.querySelector(".cap").textContent = cfg.caption;
        const box = document.getElementById("ctrls");
        standardFilters(box, all, cfg.filters);
        document.getElementById("cards").innerHTML = cfg.cards(all);
        const state = { sort: cfg.sort || "score", dir: cfg.dir || "desc", page: 0 };
        const draw = () => {
          const rows = all.filter((r) => readCommon(box, r) && (!cfg.match || cfg.match(r, box)));
          D.drawTable(document.getElementById("tbl"), {
            rows: rows, columns: cfg.columns, state: state, pageSize: cfg.pageSize || 25,
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
        ctx.page.innerHTML = D.banner(raw) + (cfg.strip ? '<div id="strip"></div>' : "") +
          '<div class="ctrls" id="ctrls"></div><div class="cards" id="cards"></div>' +
          '<div class="panel" id="tbl"></div><div id="detail"></div><p class="cap"></p>';
        if (cfg.strip) document.getElementById("strip").innerHTML = cfg.strip(all);
        ctx.page.querySelector(".cap").textContent = cfg.caption || D.noteOf(raw);
        const box = document.getElementById("ctrls");
        standardFilters(box, all, cfg.filters);
        document.getElementById("cards").innerHTML = cfg.cards(all);
        const state = { sort: "strength", dir: "desc", page: 0 };
        let pick = null;
        const drawDetail = (row) => {
          const host = document.getElementById("detail");
          if (!row) { host.innerHTML = ""; return; }
          host.innerHTML = cfg.detail(row);
        };
        const strongest = (rows) => rows.slice().sort((a, b) => (D.num(b.strength) || 0) - (D.num(a.strength) || 0))[0] || null;
        const draw = () => {
          const rows = all.filter((r) => readCommon(box, r) && (!cfg.match || cfg.match(r, box)));
          if (pick && !rows.some((r) => r.ticker === pick)) pick = null;
          const selected = rows.find((r) => r.ticker === pick) || strongest(rows);
          pick = selected ? selected.ticker : null;
          D.drawTable(document.getElementById("tbl"), {
            rows: rows, columns: cfg.columns, state: state, pageSize: 12, pick: pick,
            empty: "No names match. Open Status and tick WATCHING to see names still forming.",
            onPick: (row) => { pick = row.ticker; draw(); },
          });
          drawDetail(selected);
        };
        hook(box, state, draw);
        draw();
      },
    };
  }

  function reasonBlock(row, extraCols) {
    let rules = "";
    if (extraCols) {
      rules = '<div class="panel" style="margin-top:12px"><div class="pad"><div class="ptitle">' + D.esc(row.ticker) +
        " rules</div></div><div class=\"scroll\"><table><tr>" +
        extraCols.map((c) => "<th>" + D.esc(c.label) + "</th>").join("") + "</tr><tr>" +
        extraCols.map((c) => "<td class=\"c wrap\">" + (c.kind === "pass" ? (D.isBlank(row[c.key]) ? D.na() : (String(row[c.key]).toUpperCase() === "PASS" ? '<span class="pill" style="color:#22C55E">PASS</span>' : String(row[c.key]).toUpperCase() === "FAIL" ? '<span class="pill" style="color:#EF4444">FAIL</span>' : D.esc(row[c.key]))) : D.esc(row[c.key] || "–")) + "</td>").join("") +
        "</tr></table></div></div>";
    }
    return '<div class="panel pad" style="margin-top:12px"><div class="ptitle">' + D.tickerHtml(row.ticker) +
      ' · why this name</div><p class="cap" style="margin-top:8px">' + D.esc(row.reason || "") + "</p></div>" + rules;
  }

  const readyDefault = ["READY", "BROKEN OUT today"];

  function renderToday(ctx) {
    const mt = (ctx.files["market_today.csv"] || [])[0] || {};
    const breadth = D.lastNDays(D.realRows(ctx.files["breadth_history.csv"]), "date", 182);
    const sectors = D.realRows(ctx.files["sectors.csv"]);
    const alerts = D.realRows(ctx.files["alerts.csv"]).filter((r) => r.kind && r.kind !== "info").slice(0, 8);
    const day = D.num(mt.spy_day_pct);
    const dayHtml = day == null ? D.na() : '<span style="color:' + D.retColor(day) + '">' + (day < 0 ? "▼ " : "▲ ") + D.fmt(Math.abs(day), 2) + "% today</span>";
    const b = D.num(mt.breadth_sma50);
    const w = D.num(mt.breadth_sma50_week_ago);
    const delta = b != null && w != null ? b - w : null;
    const deltaHtml = delta == null ? '<span class="na">vs week ago –</span>' : '<span style="color:' + D.retColor(delta) + '">' + (delta >= 0 ? "+" : "") + D.fmt(delta, 1) + " pts vs week ago</span>";
    const zone = mt.put_call_zone || "";
    const zoneColor = /Greed|Fear/.test(zone) ? "#F59E0B" : "#E6EBF5";
    const y10 = D.num(mt.fred_dgs10);
    const curve = D.num(mt.fred_t10y2y);
    const chips = [
      ["20-day", mt.breadth_sma20, "#7C9CFF"],
      ["50-day", mt.breadth_sma50, "#E6EBF5"],
      ["100-day", mt.breadth_sma100, "#F59E0B"],
      ["200-day", mt.breadth_sma200, "#8B96AD"],
    ].map((c) => '<span class="chip"><i class="dot" style="background:' + c[2] + '"></i>' + c[0] + " <b>" +
      (D.num(c[1]) == null ? "–" : D.fmt(c[1], 1) + "%") + "</b></span>").join("");
    ctx.page.innerHTML = D.banner(ctx.files["market_today.csv"]) +
      '<div class="cards">' +
      card("S&P 500 (SPY)", D.num(mt.spy_price) == null ? D.na() : D.esc(D.fmt(mt.spy_price, 2)), dayHtml) +
      card("% above 50-day", b == null ? D.na() : D.esc(D.fmt(b, 1) + "%"), deltaHtml) +
      card("Advancers / decliners",
        '<span style="color:#22C55E">' + D.esc(mt.advancers || "–") + '</span><span style="color:#5B6680"> / </span><span style="color:#EF4444">' + D.esc(mt.decliners || "–") + "</span>",
        "of " + D.esc(mt.universe_n || "–") + " stocks") +
      card("New 52-week highs", D.esc(mt.highs_52w || "–"), D.esc(mt.lows_52w || "–") + " new lows") +
      card("Put/call mood", D.isBlank(zone) ? D.na() : '<span style="color:' + zoneColor + '">' + D.esc(zone) + "</span>",
        (D.num(mt.put_call) == null ? "–" : D.fmt(mt.put_call, 2)) + " today · 5-day " + (D.num(mt.put_call_ma5) == null ? "–" : D.fmt(mt.put_call_ma5, 2))) +
      card("VIX", D.num(mt.vix) == null ? D.na() : D.esc(D.fmt(mt.vix, 2)), "fear gauge") +
      card("10-year yield", y10 == null ? D.na() : D.esc(D.fmt(y10, 2) + "%"), curve == null ? "10y–2y n/a" : "10y–2y " + D.fmt(curve, 2)) +
      "</div>" +
      '<div class="split"><div class="panel pad"><div class="rowhead"><div><div class="ptitle">Market breadth</div><div class="psub">% of the desk stocks above each average, 6 months</div></div><div class="chips">' + chips + '</div></div><div class="chart-box"><canvas id="br"></canvas></div><div class="psub">Gaps = days with no breadth data (shown as breaks, not 0)</div></div>' +
      '<div class="panel pad"><div class="ptitle">Sectors today</div><div class="psub">Day % change, 11 S&P sector ETFs</div><div class="chart-box"><canvas id="sec"></canvas></div></div></div>' +
      '<div class="split"><div class="panel" id="top5"></div><div class="panel" id="alerts"></div></div>';
    const labels = breadth.map((r) => r.date);
    D.lineChart(document.getElementById("br"), labels, [
      { label: "20-day", data: D.seriesNum(breadth, "pct_above_sma20"), color: "#7C9CFF" },
      { label: "50-day", data: D.seriesNum(breadth, "pct_above_sma50"), color: "#E6EBF5" },
      { label: "100-day", data: D.seriesNum(breadth, "pct_above_sma100"), color: "#F59E0B" },
      { label: "200-day", data: D.seriesNum(breadth, "pct_above_sma200"), color: "#8B96AD" },
    ], { y: { min: 0, max: 100 }, legend: false });
    const eleven = sectors.filter((r) => D.SPD[r.ticker]).slice().sort((a, b) => (D.num(b.day_pct) || -999) - (D.num(a.day_pct) || -999));
    D.barChart(document.getElementById("sec"), eleven.map((r) => D.SPD[r.ticker]), eleven.map((r) => D.num(r.day_pct)),
      eleven.map((r) => (D.num(r.day_pct) || 0) >= 0 ? "#1F9D55" : "#D14343"),
      { horizontal: true, y: { reverse: false } });
    const top = sectors.slice().sort((a, b) => (D.num(b.day_pct) || -999) - (D.num(a.day_pct) || -999)).slice(0, 5);
    D.drawTable(document.getElementById("top5"), {
      title: "Top 5 sectors today", sub: "Best day % of the 19 sector and industry ETFs",
      rows: top, columns: [T("name", "Sector"), T("day_pct", "Day %", "pct", { dec: 2 })],
      state: { sort: "day_pct", dir: "desc", page: 0 }, pageSize: 5,
    });
    D.drawTable(document.getElementById("alerts"), {
      title: "Latest alerts", sub: "Changes since the previous run. Nothing is emailed and nothing is sent to a broker.",
      rows: alerts, columns: [TK, T("text", "What changed", "text", { wrap: true }), SC, VE],
      state: { sort: "score", dir: "desc", page: 0 }, pageSize: 8,
    });
  }

  function renderTop(ctx) {
    const raw = ctx.files["scores.csv"];
    const all = D.realRows(raw);
    ctx.page.innerHTML = D.banner(raw) + '<div class="ctrls" id="ctrls"></div><div class="panel" id="tbl"></div>';
    const box = document.getElementById("ctrls");
    standardFilters(box, all, { verdict: true, sector: true, confidence: true, index: true, ticker: true });
    const state = { sort: "score", dir: "desc", page: 0 };
    const cols = [T("rank", "Rank", "num", { dec: 0 }), TK, CO, SE, SC, VE, PR, T("day_pct", "Day %", "pct", { dec: 2 }),
      T("timing", "Trend", "trend"), T("entry_low", "Entry low", "num", { dec: 2 }), T("entry_high", "Entry high", "num", { dec: 2 }),
      T("stop", "Stop", "num", { dec: 2 }), T("trade_target", "Target", "num", { dec: 2 })];
    const draw = () => {
      D.drawTable(document.getElementById("tbl"), {
        rows: all.filter((r) => readCommon(box, r)), columns: cols, state: state, pageSize: 25,
      });
    };
    hook(box, state, draw);
    draw();
  }

  function renderScorecard(ctx) {
    const scores = D.realRows(ctx.files["scores.csv"]);
    const params = new URLSearchParams(location.search);
    const rank1 = (scores.find((r) => String(r.rank) === "1") || scores[0] || {}).ticker || "";
    let ticker = (params.get("t") || rank1 || "").toUpperCase();
    ctx.page.innerHTML = D.banner(ctx.files["scores.csv"]) +
      '<div class="ctrls" id="ctrls"></div><div id="body"></div>';
    const box = document.getElementById("ctrls");
    box.innerHTML = D.searchHtml("ticker", "Ticker", "sc-tickers", D.uniq(scores, "ticker")) +
      D.selectHtml("kind", "News type", ["headline", "desk_note"], "headline");
    const input = box.querySelector("[data-filter=ticker]");
    input.value = ticker;
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
      const prices = (ctx.files["prices.csv"] || []).filter((r) => r.ticker === ticker);
      const earn = (ctx.files["earnings_history.csv"] || []).filter((r) => r.ticker === ticker && !D.isBlank(r.eps_actual))
        .sort((a, b) => a.earnings_date < b.earnings_date ? -1 : 1).slice(-8);
      const news = (ctx.files["news.csv"] || []).filter((r) => r.ticker === ticker && (kind === "" || r.kind === kind));
      const avoid = row.verdict === "AVOID";
      host.innerHTML =
        '<div class="panel pad identity"><div class="id-main"><div class="big">' + D.esc(row.ticker) + "</div><div>" + D.esc(row.company) +
        '</div><div class="m2">' + D.esc(row.sector) + (row.industry ? " · " + D.esc(row.industry) : "") + "</div></div>" +
        '<div class="stat"><div class="l">Price</div><div class="v">' + (D.num(row.price) == null ? D.na() : D.esc(D.fmt(row.price, 2))) + "</div></div>" +
        '<div class="stat"><div class="l">Day %</div><div class="v" style="color:' + D.retColor(day) + '">' + (day == null ? D.na() : D.esc(D.fmt(day, 2) + "%")) + "</div></div>" +
        '<div class="stat"><div class="l">Verdict</div><div class="v">' + D.verdictHtml(row.verdict) + '</div><div class="m2">Confidence ' + D.esc(row.confidence || "–") + "</div></div>" +
        '<div class="stat"><div class="l">Desk score</div><div class="v">' + D.scoreHtml(row.score) + "</div></div></div>" +
        '<div class="panel pad"><div class="ptitle">Reason</div><p style="margin-top:8px">' + D.esc(row.reason || "") + "</p></div>" +
        '<div class="split"><div class="panel pad"><div class="ptitle">Plan</div><div class="cards">' +
        card("Entry low", D.num(row.entry_low) == null ? D.na() : D.esc(D.fmt(row.entry_low, 2))) +
        card("Entry high", D.num(row.entry_high) == null ? D.na() : D.esc(D.fmt(row.entry_high, 2))) +
        card("Stop", D.num(row.stop) == null ? D.na() : '<span style="color:#EF4444">' + D.esc(D.fmt(row.stop, 2)) + "</span>") +
        card("Target", D.num(row.trade_target) == null ? D.na() : '<span style="color:#22C55E">' + D.esc(D.fmt(row.trade_target, 2)) + "</span>") +
        card("Reward / risk", D.num(row.reward_risk) == null ? D.na() : D.esc(D.fmt(row.reward_risk, 2))) +
        '</div><p class="cap">AVOID leaves entry and the trade target blank on purpose.</p></div>' +
        '<div class="panel pad"><div class="ptitle">Valuation</div><div class="cards">' +
        card("Analyst target", D.num(row.target_analyst) == null ? D.na() : D.esc(D.fmt(row.target_analyst, 2)), D.esc(row.target_analyst_kind || "")) +
        card("Cash-flow target", D.num(row.target_pfcf) == null ? D.na() : D.esc(D.fmt(row.target_pfcf, 2))) +
        card("PEG target", D.num(row.target_peg) == null ? D.na() : D.esc(D.fmt(row.target_peg, 2))) +
        card("Blended target", D.num(row.target_blended) == null ? D.na() : '<span style="color:#7C9CFF">' + D.esc(D.fmt(row.target_blended, 2)) + "</span>", (row.target_blend_n || "0") + " inputs") +
        "</div></div></div>" +
        '<div class="cards">' +
        card("Technical", D.pointsHtml(row.pts_tech)) + card("Financials", D.pointsHtml(row.pts_fin)) +
        card("Sentiment", D.pointsHtml(row.pts_sent)) + card("Earnings", D.pointsHtml(row.pts_earnings)) +
        card("Sector", D.pointsHtml(row.pts_sector)) + card("Total score", D.scoreHtml(row.score)) + "</div>" +
        '<div class="split"><div class="panel pad"><div class="ptitle">Price and averages</div><div class="chart-box"><canvas id="px"></canvas></div></div>' +
        '<div class="panel pad"><div class="ptitle">Last reports</div><div class="psub">EPS surprise and the next-session move</div><div class="chart-box"><canvas id="eh"></canvas></div></div></div>' +
        '<div class="panel" id="break"></div><div class="panel" id="news"></div>' +
        '<p class="cap">Basis ' + D.esc(row.fundamentals_basis || "–") + " · filed " + D.esc(row.fundamentals_filed || "–") +
        " · average years " + D.esc(row.fin_avg_years || "–") + ". " + D.esc(row.forward_pe_avg_basis || "") +
        (row.missing_fields ? " Missing: " + row.missing_fields + "." : "") + "</p>";
      const hlines = [
        { value: D.num(row.entry_low), color: "#F59E0B", label: "Entry low" },
        { value: D.num(row.entry_high), color: "#F59E0B", label: "Entry high" },
        { value: D.num(row.stop), color: "#EF4444", label: "Stop" },
        { value: D.num(row.trade_target), color: "#22C55E", label: "Target" },
      ].filter((x) => x.value != null);
      D.makeChart(document.getElementById("px"), {
        type: "line",
        data: {
          labels: prices.map((r) => r.date),
          datasets: [
            { label: "Close", data: D.seriesNum(prices, "close"), borderColor: "#E6EBF5", backgroundColor: "transparent", spanGaps: true, pointRadius: 0, borderWidth: 2 },
            { label: "20-day avg", data: D.seriesNum(prices, "sma20"), borderColor: "#7C9CFF", backgroundColor: "transparent", spanGaps: true, pointRadius: 0, borderWidth: 2 },
            { label: "50-day avg", data: D.seriesNum(prices, "sma50"), borderColor: "#8B96AD", backgroundColor: "transparent", spanGaps: true, pointRadius: 0, borderWidth: 2 },
          ],
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { labels: { color: "#8B96AD", boxWidth: 12 } }, hlines: hlines },
          scales: {
            x: { ticks: { color: "#8B96AD", maxRotation: 0, autoSkip: true }, grid: { color: "#1E293B" } },
            y: { ticks: { color: "#8B96AD" }, grid: { color: "#1E293B" } },
          },
        },
      });
      D.makeChart(document.getElementById("eh"), {
        type: "bar",
        data: {
          labels: earn.map((r) => r.earnings_date),
          datasets: [
            { label: "EPS surprise %", data: D.seriesNum(earn, "surprise_pct"), backgroundColor: "#7C9CFF" },
            { label: "Next-day move %", data: D.seriesNum(earn, "move_1d_pct"), backgroundColor: "#8B96AD" },
          ],
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { labels: { color: "#8B96AD", boxWidth: 12 } } },
          scales: {
            x: { ticks: { color: "#8B96AD", maxRotation: 0, autoSkip: true }, grid: { color: "#1E293B" } },
            y: { ticks: { color: "#8B96AD" }, grid: { color: "#1E293B" } },
          },
        },
      });
      D.drawTable(document.getElementById("break"), {
        title: "Score breakdown",
        rows: details,
        columns: [T("group_name", "Group"), T("item", "Item", "text", { wrap: true }), T("points_label", "Points", "plabel"),
          T("now_value", "Now", "text"), T("avg_value", "Own average", "text"), T("vs_industry", "Vs sector", "text", { wrap: true })],
        state: { sort: "group_name", dir: "asc", page: 0 }, pageSize: 20,
      });
      D.drawTable(document.getElementById("news"), {
        title: "News", sub: "Focus list only. A desk note repeats the reason.",
        rows: news,
        columns: [T("headline", "Headline", "text", { wrap: true }), T("publisher", "Source"), T("published", "Published")],
        state: { sort: "published", dir: "desc", page: 0 }, pageSize: 8,
      });
    };
    box.addEventListener("change", draw);
    draw();
  }

  function renderWatch(ctx) {
    const port = D.realRows(ctx.files["portfolio.csv"]);
    const sum = (ctx.files["portfolio_summary.csv"] || [])[0] || {};
    const watch = D.realRows(ctx.files["watchlist.csv"]);
    ctx.page.innerHTML = D.banner(ctx.files["portfolio.csv"]) +
      (sum.example_warning ? '<div class="warn">' + D.esc(sum.example_warning) + "</div>" : "") +
      '<div class="cards" id="cards"></div><div class="ctrls" id="ctrls"></div>' +
      '<div class="panel" id="hold"></div><div class="panel" id="watch"></div>' +
      '<p class="cap">Week-ago score stays blank until a score is seven days old. A dash is missing, not zero. These files are the published output of input/holdings.csv and input/my_watchlist.csv.</p>';
    const pnl = D.num(sum.day_pnl);
    const gain = D.num(sum.total_gain);
    document.getElementById("cards").innerHTML =
      card("Portfolio value", D.num(sum.value) == null ? D.na() : D.esc("$" + D.fmt(sum.value, 0)), D.esc(sum.n_holdings || "0") + " holdings") +
      card("Day P/L", pnl == null ? D.na() : '<span style="color:' + D.retColor(pnl) + '">' + D.esc((pnl < 0 ? "-$" : "$") + D.fmt(Math.abs(pnl), 2)) + "</span>",
        D.num(sum.day_pnl_pct) == null ? D.na() : '<span style="color:' + D.retColor(D.num(sum.day_pnl_pct)) + '">' + D.fmt(sum.day_pnl_pct, 2) + "%</span>") +
      card("Total gain", gain == null ? D.na() : '<span style="color:' + D.retColor(gain) + '">' + D.esc((gain < 0 ? "-$" : "$") + D.fmt(Math.abs(gain), 0)) + "</span>",
        D.num(sum.total_gain_pct) == null ? "" : '<span style="color:' + D.retColor(D.num(sum.total_gain_pct)) + '">' + D.fmt(sum.total_gain_pct, 2) + "%</span>") +
      card("Average desk score", D.num(sum.avg_score) == null ? D.na() : D.esc(D.fmt(sum.avg_score, 1)),
        '<span style="color:#F59E0B">' + D.esc(sum.needs_attention || "0") + "</span> need attention");
    const box = document.getElementById("ctrls");
    standardFilters(box, port, { verdict: true, ticker: true });
    box.insertAdjacentHTML("beforeend", D.multiHtml("status", "Holding status", D.uniq(port, "status")));
    const hs = { sort: "weight_pct", dir: "desc", page: 0 };
    const ws = { sort: "score", dir: "desc", page: 0 };
    const draw = () => {
      const rows = port.filter((r) => readCommon(box, r) && D.matchMulti(r, "status", D.selectedMulti(box, "status")));
      const q = (D.fieldVal(box, "ticker") || "").trim();
      D.drawTable(document.getElementById("hold"), {
        title: "Holdings", rows: rows,
        columns: [TK, T("shares", "Shares", "num", { dec: 0 }), T("avg_cost", "Avg cost", "num", { dec: 2 }), PR,
          T("value", "Value", "money", { dec: 0 }), T("gain", "Gain", "money", { dec: 0, color: true }),
          T("gain_pct", "Gain %", "pct"), T("weight_pct", "Weight %", "pct"), SC,
          T("score_week_ago", "Score week ago", "score"), T("score_week_change", "Week change", "num", { dec: 1 }),
          VE, T("stop", "Stop", "num", { dec: 2 }), T("status", "Status", "hold")],
        state: hs, pageSize: 25,
      });
      D.drawTable(document.getElementById("watch"), {
        title: "Watchlist", rows: watch.filter((r) => D.matchText(r, "ticker", q) && D.matchMulti(r, "verdict", D.selectedMulti(box, "verdict"))),
        columns: [TK, CO, PR, T("day_pct", "Day %", "pct"), SC, VE,
          T("entry_low", "Entry low", "num", { dec: 2 }), T("entry_high", "Entry high", "num", { dec: 2 }),
          T("distance_to_entry_pct", "Vs entry %", "dist"), T("timing", "Trend", "trend")],
        state: ws, pageSize: 25,
      });
    };
    hook(box, hs, draw);
    draw();
  }

  function renderAlerts(ctx) {
    const raw = ctx.files["alerts.csv"];
    const all = D.realRows(raw);
    const changes = D.realRows(ctx.files["score_changes.csv"]).map((r) => Object.assign({}, r, {
      abs_change: String(Math.abs(D.num(r.score_change) || 0)),
    }));
    const live = all.filter((r) => r.kind !== "info");
    ctx.page.innerHTML = D.banner(raw) + '<div class="ctrls" id="ctrls"></div>' +
      '<p class="cap">These are changes since the previous run. Nothing is emailed and nothing is sent to a broker.</p>' +
      '<div class="cards" id="cards"></div><div class="panel" id="tbl"></div><div class="panel" id="chg"></div>';
    document.getElementById("cards").innerHTML =
      card("Changes this run", String(live.length)) +
      card("Verdict changes", String(countWhere(live, (r) => r.kind === "verdict_change"))) +
      card("Breakouts", String(countWhere(live, (r) => r.kind === "breakout"))) +
      card("Entry-zone arrivals", String(countWhere(live, (r) => r.kind === "entry_zone")));
    const box = document.getElementById("ctrls");
    box.innerHTML = D.multiHtml("kind", "Alert type", D.uniq(all, "kind")) +
      D.multiHtml("verdict", "Verdict now", D.uniq(all, "verdict")) +
      D.searchHtml("ticker", "Ticker", "al-tk", D.uniq(all, "ticker"));
    const state = { sort: "score", dir: "desc", page: 0 };
    const st2 = { sort: "abs_change", dir: "desc", page: 0 };
    const draw = () => {
      const rows = all.filter((r) => D.matchMulti(r, "kind", D.selectedMulti(box, "kind")) &&
        D.matchMulti(r, "verdict", D.selectedMulti(box, "verdict")) &&
        D.matchText(r, "ticker", D.fieldVal(box, "ticker")));
      D.drawTable(document.getElementById("tbl"), {
        title: "Alerts", rows: rows,
        columns: [TK, T("kind", "Type", "kind"), T("text", "What changed", "text", { wrap: true }),
          T("score", "Score", "score"), T("score_prev", "Score before", "num", { dec: 0 }),
          VE, T("verdict_prev", "Verdict before", "verdict"), PR],
        state: state, pageSize: 25,
      });
      const q = (D.fieldVal(box, "ticker") || "").trim();
      D.drawTable(document.getElementById("chg"), {
        title: "Score changes", rows: changes.filter((r) => D.matchText(r, "ticker", q) && D.matchMulti(r, "verdict", D.selectedMulti(box, "verdict"))),
        columns: [TK, CO, SC, T("score_prev", "Score before", "num", { dec: 0 }), T("score_change", "Change", "num", { dec: 0 }),
          VE, T("day_pct", "Day %", "pct"), PR],
        state: st2, pageSize: 25,
      });
    };
    hook(box, state, draw);
    draw();
  }

  function renderBacktest(ctx) {
    const summary = D.realRows(ctx.files["backtest_summary.csv"]);
    const equity = D.realRows(ctx.files["backtest_equity.csv"]);
    const buckets = D.realRows(ctx.files["backtest_buckets.csv"]);
    const yearly = D.realRows(ctx.files["backtest_yearly.csv"]);
    const notes = ctx.files["backtest_notes.csv"] || [];
    const labelOf = (r) => {
      const twins = summary.filter((x) => x.window === r.window).length;
      return twins > 1 ? (r.start + " to " + r.end) : (r.window || r.start);
    };
    summary.forEach((r) => { r._label = labelOf(r); });
    const prefer = summary.find((r) => r.window === "5y") || summary.slice().sort((a, b) => (D.num(b.months) || 0) - (D.num(a.months) || 0))[0];
    ctx.page.innerHTML = D.banner(ctx.files["backtest_summary.csv"]) +
      '<div class="ctrls" id="ctrls"></div><div class="panel pad" id="head"></div><div class="cards" id="cards"></div>' +
      '<div class="split"><div class="panel pad"><div class="ptitle">Growth of 10,000</div><div class="chart-box tall"><canvas id="eq"></canvas></div></div>' +
      '<div class="panel pad"><div class="ptitle">Excess by bucket</div><div class="chart-box tall"><canvas id="bk"></canvas></div></div></div>' +
      '<div class="split"><div class="panel" id="btbl"></div><div class="panel" id="ytbl"></div></div><div class="panel" id="notes"></div>';
    const box = document.getElementById("ctrls");
    const windows = summary.map((r) => r._label);
    const horizons = D.uniq(buckets, "horizon");
    box.innerHTML = D.selectHtml("window", "Test window", windows, prefer ? prefer._label : "") +
      D.selectHtml("horizon", "Horizon", horizons, horizons.indexOf("12w") >= 0 ? "12w" : (horizons[0] || ""));
    const bstate = { sort: "bucket_order", dir: "asc", page: 0 };
    const ystate = { sort: "year", dir: "asc", page: 0 };
    const draw = () => {
      const w = D.fieldVal(box, "window");
      const row = summary.find((r) => r._label === w) || prefer || summary[0] || {};
      const head = summary.find((r) => r.is_headline === "yes") || row;
      document.getElementById("head").innerHTML = '<div style="font-size:20px">' + D.esc((head && head.headline) || row.headline || "") + "</div>";
      const dd = D.num(row.top20_max_drawdown_pct);
      document.getElementById("cards").innerHTML =
        card("Top-20 yearly pace %", ntext(D.num(row.top20_cagr_pct), 1)) +
        card("S&P 500 yearly pace %", ntext(D.num(row.spy_cagr_pct), 1)) +
        card("Worst drop, top 20 %", dd == null ? D.na() : '<span style="color:#EF4444">' + D.esc(D.fmt(dd, 1)) + "</span>") +
        card("12-week hit rate %", ntext(D.num(row.hit_rate_12w_pct), 1));
      const hz = D.fieldVal(box, "horizon") || "12w";
      const brows = buckets.filter((r) => r.horizon === hz).slice().sort((a, b) => (D.num(a.bucket_order) || 0) - (D.num(b.bucket_order) || 0));
      D.destroyCharts();
      D.lineChart(document.getElementById("eq"), equity.map((r) => r.date), [
        { label: "Top 20 by score", data: D.seriesNum(equity, "top20"), color: "#22C55E", spanGaps: true },
        { label: "S&P 500", data: D.seriesNum(equity, "spy"), color: "#E6EBF5", spanGaps: true },
        { label: "Bottom 20", data: D.seriesNum(equity, "bottom20"), color: "#EF4444", spanGaps: true },
      ], {});
      D.barChart(document.getElementById("bk"), brows.map((r) => r.bucket), brows.map((r) => D.num(r.excess_pct)),
        brows.map((r) => (D.num(r.excess_pct) || 0) >= 0 ? "#22C55E" : "#EF4444"));
      D.drawTable(document.getElementById("btbl"), {
        title: "Buckets", rows: brows,
        columns: [T("bucket", "Score bucket"), T("bucket_order", "Order", "num", { dec: 0 }), T("n", "Signals", "num", { dec: 0 }),
          T("avg_return_pct", "Avg return %", "pct"), T("avg_spy_pct", "S&P same period %", "pct"),
          T("excess_pct", "Excess %", "pct"), T("hit_rate_pct", "Hit rate %", "pct", { dec: 1 })],
        state: bstate, pageSize: 10,
      });
      D.drawTable(document.getElementById("ytbl"), {
        title: "Year by year", rows: yearly,
        columns: [T("year", "Year"), T("top20_pct", "Top 20 %", "pct"), T("spy_pct", "S&P 500 %", "pct"),
          T("difference_pct", "Difference %", "pct"), T("signals", "Signals", "num", { dec: 0 })],
        state: ystate, pageSize: 12,
      });
    };
    hook(box, bstate, draw);
    draw();
    D.drawTable(document.getElementById("notes"), {
      title: "Test limits, read before trusting a number",
      rows: notes, columns: [T("item", "What was tested", "text"), T("detail", "Detail", "text", { wrap: true })],
      state: { sort: "item", dir: "asc", page: 0 }, pageSize: 20,
    });
  }

  const growth = passesPage({
    file: "scanner_growth.csv",
    caption: "Passes when revenue growth is at least the desk's growth level and the label is not AVOID. Blank growth means the filing did not have it.",
    filters: { passes: "yes", sector: true, verdict: true, ticker: true },
    columns: [TK, CO, SE, PR, SC, VE, T("rev_growth", "Revenue growth %", "pct", { dec: 1 }), T("eps_growth", "EPS growth %", "pct", { dec: 1 }), T("rs_spy_3m", "3-month vs S&P %", "pct", { dec: 1 })],
    cards(all) {
      const pass = all.filter((r) => r.passes === "yes");
      return card("Passing the screen", String(pass.length)) +
        card("Of those, BUY", String(countWhere(pass, (r) => r.verdict === "BUY"))) +
        card("Average revenue growth %, passing", ntext(avg(pass, "rev_growth"), 1)) +
        card("Average 3-month vs S&P %, passing", ntext(avg(pass, "rs_spy_3m"), 1));
    },
  });

  const quality = passesPage({
    file: "scanner_quality.csv",
    caption: "Passes when return on equity is high and debt/equity is at most the desk's limit, and the label is not AVOID.",
    filters: { passes: "yes", sector: true, verdict: true, ticker: true },
    columns: [TK, CO, SE, T("roe", "Return on equity %", "pct", { dec: 1, color: false }), T("de", "Debt / equity", "num", { dec: 2 }),
      T("pts_roe", "ROE points", "points"), T("pts_de", "Debt points", "points"), SC, VE],
    notice(all) {
      const roe = countWhere(all, (r) => D.num(r.roe) != null);
      const de = countWhere(all, (r) => D.num(r.de) != null);
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
    caption: "Passes when the yield is at least the desk's level and the label is not AVOID. A yield of 0 is real (no dividend). A dash means the yield could not be read.",
    filters: { passes: "yes", sector: true, verdict: true, ticker: true },
    columns: [TK, CO, SE, PR, T("div_yield", "Yield %", "pct"), T("div_yield_avg", "Own avg yield %", "pct", { color: false }),
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
    caption: "Stock screen only. This is not an option contract. No strikes, expiries or premiums are shown or suggested.",
    filters: { passes: "yes", sector: true, trend: true, ticker: true },
    columns: [TK, CO, SE, PR, SC, VE, T("timing", "Trend", "trend"), T("rsi14", "RSI-14", "num", { dec: 1 }),
      T("above_sma200", "Above 200-day", "flag"), T("dollar_volume", "Dollar volume", "compact")],
    cards(all) {
      const pass = all.filter((r) => r.passes === "yes");
      return card("Passing the screen", String(pass.length)) +
        card("Of those, BUY", String(countWhere(pass, (r) => r.verdict === "BUY"))) +
        card("Average RSI-14, passing", ntext(avg(pass, "rsi14"), 1)) +
        card("Median daily dollar volume", D.num(median(pass, "dollar_volume")) == null ? D.na() : D.esc(D.compact(median(pass, "dollar_volume"))));
    },
  });

  const vcpRules = ["r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8"].map((k, i) => T(k, "Rule " + (i + 1), "pass"));
  const vcp = patternPage({
    file: "scanner_vcp.csv",
    caption: "",
    filters: { status: true, statusDefault: readyDefault, index: true, ticker: true, single: [{ key: "in_trade", label: "In a trade" }] },
    columns: [TK, T("index_membership", "Index"), T("status", "Status", "setup"), PR, T("pivot", "Buy point", "num", { dec: 2 }),
      T("stop", "Stop", "num", { dec: 2 }), T("target", "Target", "num", { dec: 2 }), T("trail", "20-day trail", "num", { dec: 2 }),
      T("trend_score", "Trend template"), T("strength", "Strength", "num", { dec: 0 }), T("freshness", "Freshness", "fresh")],
    cards(all) {
      return card("Broken out today", String(countWhere(all, (r) => r.status === "BROKEN OUT today"))) +
        card("Ready", String(countWhere(all, (r) => r.status === "READY"))) +
        card("Watching", String(countWhere(all, (r) => r.status === "WATCHING"))) +
        card("In a trade", String(countWhere(all, (r) => r.in_trade === "yes")));
    },
    detail(row) {
      const cols = [
        T("r1", "Above 150d & 200d", "pass"), T("r2", "150d over 200d", "pass"), T("r3", "200d rising", "pass"), T("r4", "Higher lows", "pass"),
        T("r5", "Tight ranges", "pass"), T("r6", "Volume dry", "pass"), T("r7", "Strong prior trend", "pass"), T("r8", "Pivot nearby", "pass"),
      ];
      return reasonBlock(row, cols) + '<p class="cap">' + D.esc(row.note || "") + " Trend score " + D.esc(row.trend_score || "–") +
        ". Contractions " + D.esc(row.contractions || "–") + ". Depths " + D.esc(row.depths || "–") + ".</p>";
    },
  });
  vcp.render = (function (orig) {
    return function (ctx) {
      const note = D.noteOf(ctx.files["scanner_vcp.csv"]);
      orig(ctx);
      const cap = ctx.page.querySelector(".cap");
      if (cap && !cap.textContent) cap.textContent = note;
    };
  })(vcp.render);

  const canslim = patternPage({
    file: "scanner_canslim.csv",
    caption: "Stop and target are blank on every row on purpose. A dash is missing, not zero. Product, float and industry rank are not verified.",
    filters: { status: true, statusDefault: readyDefault, index: true, sector: true, ticker: true, single: [{ key: "qualify", label: "Qualify", value: "strict" }] },
    strip(all) {
      const row = all[0] || {};
      return '<div class="panel pad" style="margin-bottom:12px"><span class="m2">Market (SPY)</span> <b>' + D.esc(row.m_market || "–") +
        '</b> <span class="m2" style="margin-left:16px">QQQ</span> <span class="m2">' + D.esc(row.m_qqq || "–") + "</span></div>";
    },
    columns: [TK, T("index_membership", "Index"), T("status", "Status", "setup"), T("pivot", "Buy point", "num", { dec: 2 }),
      T("strength", "Strength", "num", { dec: 0 }), T("qualify", "Qualify", "pass"),
      T("c_quarterly_eps", "C: quarter EPS", "text", { wrap: true }), T("a_annual_eps", "A: annual EPS", "text", { wrap: true })],
    cards(all) {
      return card("Ready", String(countWhere(all, (r) => r.status === "READY"))) +
        card("Broken out today", String(countWhere(all, (r) => r.status === "BROKEN OUT today"))) +
        card("Strict qualify", String(countWhere(all, (r) => r.qualify === "strict"))) +
        card("Watching", String(countWhere(all, (r) => r.status === "WATCHING")));
    },
    detail(row) {
      return reasonBlock(row, [
        T("c_status", "C"), T("a_status", "A"), T("n_status", "N"), T("s_status", "S"), T("l_status", "L"), T("i_status", "I"), T("m_status", "M"),
      ].map((c) => T(c.key, c.label, "text")));
    },
  });

  function simplePattern(file, caption, extraCols) {
    return patternPage({
      file: file,
      caption: caption,
      filters: { status: true, statusDefault: readyDefault, index: true, sector: true, ticker: true },
      columns: [TK, CO, T("index_membership", "Index"), T("status", "Status", "setup"), PR,
        T("pivot", "Buy point", "num", { dec: 2 }), T("stop", "Stop", "num", { dec: 2 }), T("target", "Target", "num", { dec: 2 }),
        T("strength", "Strength", "num", { dec: 0 })].concat(extraCols),
      cards(all) {
        return card("Broken out today", String(countWhere(all, (r) => r.status === "BROKEN OUT today"))) +
          card("Ready", String(countWhere(all, (r) => r.status === "READY"))) +
          card("Watching", String(countWhere(all, (r) => r.status === "WATCHING")));
      },
      detail(row) { return reasonBlock(row); },
    });
  }

  const box = simplePattern("scanner_box.csv",
    "Desk rule: a 15 to 40 day range no wider than 10% whose first and last closes drift by 5% or less, then a close through the range high.",
    [T("range_days", "Range days", "num", { dec: 0 }), T("range_width_pct", "Width %", "pct", { dec: 1, color: false }), T("volume_ratio", "Volume vs 50-day", "num", { dec: 2 })]);
  const flag = simplePattern("scanner_flag.csv",
    "Desk rule: a pole of at least 15% in 3 to 12 sessions, then a 3 to 15 day flag that retraces less than half the pole, then a close through the flag high.",
    [T("pole_pct", "Pole %", "pct", { dec: 1 }), T("flag_bars", "Flag bars", "num", { dec: 0 }), T("retrace_pct", "Retrace %", "pct", { dec: 1, color: false }), T("volume_ratio", "Volume ratio", "num", { dec: 2 })]);

  const leaders = patternPage({
    file: "scanner_leaders.csv",
    caption: "Leaders is the overlap of a ready or just-broken VCP and a strict CANSLIM qualify. A name on only one of those still appears.",
    filters: { status: true, statusDefault: readyDefault, ticker: true, single: [{ key: "on_vcp", label: "On VCP" }, { key: "on_canslim", label: "On CANSLIM" }] },
    columns: [TK, T("index_membership", "Index"), T("status", "Status", "setup"), T("on_vcp", "VCP", "flag"), T("on_canslim", "CANSLIM", "flag"),
      T("pivot", "Buy point", "num", { dec: 2 }), T("stop", "Stop", "num", { dec: 2 }), T("target", "Target", "num", { dec: 2 }),
      T("strength", "Strength", "num", { dec: 0 })],
    cards(all) {
      return card("On both scans", String(countWhere(all, (r) => r.on_vcp === "yes" && r.on_canslim === "yes"))) +
        card("VCP only", String(countWhere(all, (r) => r.on_vcp === "yes" && r.on_canslim === "no"))) +
        card("CANSLIM only", String(countWhere(all, (r) => r.on_vcp === "no" && r.on_canslim === "yes"))) +
        card("Ready", String(countWhere(all, (r) => r.status === "READY")));
    },
    detail(row) { return reasonBlock(row); },
  });

  function renderCalendar(ctx) {
    const raw = ctx.files["earnings_calendar.csv"];
    const all = D.realRows(raw);
    ctx.page.innerHTML = D.banner(raw) + '<div class="ctrls" id="ctrls"></div><div class="cards" id="cards"></div><div class="panel" id="tbl"></div>' +
      '<p class="cap">The one-day move is the next session after a report that hit at or after 4pm Eastern, otherwise the session of the report. The average is the last eight reports.</p>';
    const box = document.getElementById("ctrls");
    box.innerHTML = D.rangeHtml("min", "Days away, from", 0, 400, 0, 1) + D.rangeHtml("max", "Days away, to", 0, 400, 14, 1) +
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
    document.getElementById("cards").innerHTML =
      card("Reporting in 0 to 14 days", String(countWhere(all, (r) => { const d = D.num(r.days_away); return d != null && d >= 0 && d <= 14; }))) +
      card("Nick's holdings", String(countWhere(all, (r) => r.owns === "yes"))) +
      card("After the close", String(countWhere(all, (r) => r.when_hint === "after close")));
    const state = { sort: "days_away", dir: "asc", page: 0 };
    const draw = () => D.drawTable(document.getElementById("tbl"), {
      rows: windowRows(),
      columns: [TK, CO, T("next_earnings", "Report date", "date"), T("when_hint", "When"), T("days_away", "Days away", "num", { dec: 0 }),
        T("last_eps_actual", "Last EPS", "num", { dec: 2 }), T("last_eps_estimate", "Last estimate", "num", { dec: 2 }),
        T("last_surprise_pct", "Last surprise %", "pct", { dec: 1 }), T("avg_1d_move_pct", "Avg 1-day move %", "pct", { dec: 1 })],
      state: state, pageSize: 25,
    });
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
    ctx.page.innerHTML = D.banner(raw) + '<div class="ctrls" id="ctrls"></div>' +
      '<p class="cap">Green = EPS beat, red = miss, grey = in line. Revenue is n/a in this free feed, so a double beat cannot be shown.</p>' +
      '<div class="panel" id="pivot"></div><div class="panel" id="detail"></div>';
    const end = maxDate(all, "quarter");
    const box = document.getElementById("ctrls");
    box.innerHTML = '<label class="m2" style="font-size:12px">From<br><input class="dd" type="date" data-filter="from" value="' + shift(end, -730) + '"></label>' +
      '<label class="m2" style="font-size:12px">To<br><input class="dd" type="date" data-filter="to" value="' + end + '"></label>' +
      D.searchHtml("ticker", "Ticker", "hm-tk", D.uniq(all, "ticker"));
    const state = { page: 0 };
    const draw = () => {
      const from = D.fieldVal(box, "from");
      const to = D.fieldVal(box, "to");
      const q = (D.fieldVal(box, "ticker") || "").trim().toLowerCase();
      const rows = all.filter((r) => (!from || r.quarter >= from) && (!to || r.quarter <= to) && (!q || r.ticker.toLowerCase().indexOf(q) >= 0));
      const quarters = Array.from(new Set(rows.map((r) => yq(r.quarter)))).sort();
      const by = {};
      rows.forEach((r) => {
        const k = r.ticker + "|" + yq(r.quarter);
        by[k] = r;
      });
      const tickers = Array.from(new Set(rows.map((r) => r.ticker))).sort();
      const pageSize = 20;
      const pages = Math.max(1, Math.ceil(tickers.length / pageSize));
      if (state.page >= pages) state.page = 0;
      const slice = tickers.slice(state.page * pageSize, state.page * pageSize + pageSize);
      const head = "<th>Ticker</th>" + quarters.map((qtr) => "<th class=\"c\">" + D.esc(qtr) + "</th>").join("");
      const body = slice.map((t) => "<tr><td>" + D.tickerHtml(t) + "</td>" + quarters.map((qtr) => {
        const r = by[t + "|" + qtr];
        if (!r) return "<td class=\"c\">" + D.na() + "</td>";
        const h = D.num(r.heat);
        const color = h > 0 ? "#22C55E" : h < 0 ? "#EF4444" : "#8B96AD";
        const word = h > 0 ? "beat" : h < 0 ? "miss" : "inline";
        return '<td class="c"><span class="heat" style="color:' + color + '">' + word + "</span></td>";
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
      const detail = rows.slice().sort((a, b) => a.quarter < b.quarter ? 1 : -1).slice(0, 25);
      D.drawTable(document.getElementById("detail"), {
        title: "Quarter detail", rows: detail,
        columns: [TK, T("quarter", "Quarter", "date"), T("label", "Result", "text", { wrap: true }), T("eps_flag", "EPS", "text"), T("rev_flag", "Revenue", "text")],
        state: { sort: "quarter", dir: "desc", page: 0 }, pageSize: 25,
      });
    };
    hook(box, state, draw);
    draw();
  }

  function renderCards(ctx) {
    const raw = ctx.files["earnings_cards.csv"];
    const all = D.realRows(raw);
    ctx.page.innerHTML = D.banner(raw) + '<div class="ctrls" id="ctrls"></div>' +
      '<p class="cap">Grades are a fixed rule on the last few earnings beats and revenue growth versus the company\'s own history. They are not a write-up from a person, and they are not a trade.</p>' +
      '<div class="cards" id="cards"></div><div class="panel" id="tbl"></div><p class="cap" id="src"></p>';
    const fills = { A: "#166534", B: "#14532D", C: "#283146", D: "#7F1D1D", F: "#B91C1C" };
    document.getElementById("cards").innerHTML = "ABCDF".split("").map((g) =>
      card("Grade " + g, String(countWhere(all, (r) => r.grade === g)), "", fills[g])).join("");
    const src = (all[0] && all[0].sources) || "Yahoo Finance earnings dates. Revenue vs estimate is not in that free feed, so revenue is left blank.";
    document.getElementById("src").textContent = src;
    const box = document.getElementById("ctrls");
    box.innerHTML = D.multiHtml("grade", "Grade", ["A", "B", "C", "D", "F"]) + D.searchHtml("ticker", "Ticker", "gc", D.uniq(all, "ticker"));
    const state = { sort: "grade", dir: "asc", page: 0 };
    const draw = () => D.drawTable(document.getElementById("tbl"), {
      rows: all.filter((r) => D.matchMulti(r, "grade", D.selectedMulti(box, "grade")) && D.matchText(r, "ticker", D.fieldVal(box, "ticker"))),
      columns: [TK, CO, T("grade", "Grade", "grade"), T("summary", "Summary", "text", { wrap: true })],
      state: state, pageSize: 25,
    });
    hook(box, state, draw);
    draw();
  }

  function renderPutCall(ctx) {
    const raw = (ctx.files["put_call.csv"] || []).filter((r) => r.name === "EQUITY PUT/CALL RATIO" && r.data_status !== "MISSING");
    const end = maxDate(raw, "date");
    ctx.page.innerHTML = D.banner(ctx.files["put_call.csv"]) + '<div class="ctrls" id="ctrls"></div>' +
      '<p class="cap">Market mood only. Not an option position.</p>' +
      '<div class="cards" id="latest"></div><div class="panel pad"><div class="ptitle">Put/call and its 5-day average</div><div class="chart-box tall"><canvas id="pc"></canvas></div></div><div class="panel" id="tbl"></div>';
    const box = document.getElementById("ctrls");
    box.innerHTML = '<label class="m2" style="font-size:12px">From<br><input class="dd" type="date" data-filter="from" value="' + shift(end, -90) + '"></label>' +
      D.selectHtml("zone", "Zone", D.uniq(raw, "zone"), "");
    const latest = raw.slice().sort((a, b) => a.date < b.date ? 1 : -1)[0] || {};
    document.getElementById("latest").innerHTML =
      card("Date", D.esc(latest.date || "–")) +
      card("Put/call", D.num(latest.value) == null ? D.na() : D.esc(D.fmt(latest.value, 3))) +
      card("5-day avg", D.num(latest.ma5) == null ? D.na() : D.esc(D.fmt(latest.ma5, 3))) +
      card("Today's zone", D.zoneHtml(latest.zone));
    const state = { sort: "date", dir: "desc", page: 0 };
    const draw = () => {
      const from = D.fieldVal(box, "from");
      const series = raw.filter((r) => !from || r.date >= from).sort((a, b) => a.date < b.date ? -1 : 1);
      const zone = D.fieldVal(box, "zone");
      D.destroyCharts();
      const fear = D.num((series[0] || {}).fear_line);
      const greed = D.num((series[0] || {}).greed_line);
      D.makeChart(document.getElementById("pc"), {
        type: "line",
        data: {
          labels: series.map((r) => r.date),
          datasets: [
            { label: "Put/call", data: D.seriesNum(series, "value"), borderColor: "#7C9CFF", pointRadius: 0, borderWidth: 2, spanGaps: false },
            { label: "5-day avg", data: D.seriesNum(series, "ma5"), borderColor: "#E6EBF5", pointRadius: 0, borderWidth: 2, spanGaps: true },
          ],
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: {
            legend: { labels: { color: "#8B96AD", boxWidth: 12 } },
            hlines: [
              { value: fear, color: "#EF4444", label: "Fear" },
              { value: greed, color: "#22C55E", label: "Greed" },
            ],
          },
          scales: {
            x: { ticks: { color: "#8B96AD", maxRotation: 0 }, grid: { color: "#1E293B" } },
            y: { ticks: { color: "#8B96AD" }, grid: { color: "#1E293B" } },
          },
        },
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
    const tickers = D.uniq(raw, "ticker");
    const start = tickers.indexOf("NVDA") >= 0 ? "NVDA" : (tickers[0] || "");
    ctx.page.innerHTML = D.banner(ctx.files["option_walls.csv"]) + '<div class="ctrls" id="ctrls"></div>' +
      '<p class="cap">Open interest by strike. Sentiment only. Not a contract to trade. Chains refresh once a day for the focus list, so most of the universe is not on this page.</p>' +
      '<div class="panel pad"><div class="chart-box tall"><canvas id="oi"></canvas></div></div><div class="split"><div class="panel" id="walls"></div><div class="panel pad" id="note"></div></div>';
    const box = document.getElementById("ctrls");
    box.innerHTML = D.searchHtml("ticker", "Ticker", "wtk", tickers) + '<label class="m2" style="font-size:12px">Expiry<br><select class="dd" data-filter="expiry"></select></label>';
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
      const rows = raw.filter((r) => r.ticker === t && r.expiry === exp);
      const strikes = D.uniq(rows, "strike");
      const call = strikes.map((s) => { const r = rows.find((x) => x.strike === s && x.side === "call"); return r ? D.num(r.open_interest) : 0; });
      const put = strikes.map((s) => { const r = rows.find((x) => x.strike === s && x.side === "put"); return r ? D.num(r.open_interest) : 0; });
      D.destroyCharts();
      D.makeChart(document.getElementById("oi"), {
        type: "bar",
        data: { labels: strikes, datasets: [
          { label: "Calls", data: call, backgroundColor: "#22C55E" },
          { label: "Puts", data: put, backgroundColor: "#EF4444" },
        ] },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { labels: { color: "#8B96AD", boxWidth: 12 } } },
          scales: {
            x: { ticks: { color: "#8B96AD", maxRotation: 0, autoSkip: true }, grid: { color: "#1E293B" } },
            y: { ticks: { color: "#8B96AD" }, grid: { color: "#1E293B" } },
          },
        },
      });
      D.drawTable(document.getElementById("walls"), {
        title: "Wall strikes", rows: rows.filter((r) => r.is_wall === "yes"),
        columns: [T("side", "Side"), T("strike", "Strike", "num", { dec: 2 }), T("open_interest", "Open interest", "num", { dec: 0 }), T("volume", "Volume today", "num", { dec: 0 })],
        state: { sort: "side", dir: "asc", page: 0 }, pageSize: 8,
      });
      document.getElementById("note").innerHTML = '<div class="ptitle">Note</div><p class="cap">' + D.esc(D.noteOf(ctx.files["option_walls.csv"]) || "Open interest only, for the focus list, once a day. Not an option pick.") + "</p>";
    };
    D.wireFilters(box, draw);
    draw();
  }

  function renderAnalysts(ctx) {
    const raw = ctx.files["analyst_ratings.csv"];
    const all = D.realRows(raw);
    ctx.page.innerHTML = D.banner(raw) + '<div class="ctrls" id="ctrls"></div><div class="cards" id="cards"></div><div class="panel" id="tbl"></div>' +
      '<p class="cap">Targets are the median analyst target. Mean rating runs from 1 (strong buy) to 5 (sell). Upside is the target divided by price, minus one, in percent.</p>';
    const fills = { "2": "#166534", "1": "#14532D", "0": "#283146" };
    document.getElementById("cards").innerHTML = ["2", "1", "0"].map((p) =>
      card("Analyst points " + p, String(countWhere(all, (r) => String(D.num(r.pts_analyst)) === p)), "", fills[p])).join("");
    const box = document.getElementById("ctrls");
    box.innerHTML = D.multiHtml("pts", "Analyst points", D.uniq(all, "pts_analyst")) +
      D.rangeHtml("min", "Min. analysts", 0, 80, 0, 1) +
      D.searchHtml("ticker", "Ticker", "an-tk", D.uniq(all, "ticker"));
    const state = { sort: "pts_analyst", dir: "desc", page: 0 };
    const draw = () => D.drawTable(document.getElementById("tbl"), {
      rows: all.filter((r) => D.matchMulti(r, "pts_analyst", D.selectedMulti(box, "pts")) &&
        D.matchMin(r, "analyst_count", D.fieldVal(box, "min")) && D.matchText(r, "ticker", D.fieldVal(box, "ticker"))),
      columns: [TK, CO, T("analyst_mean", "Mean rating", "num", { dec: 2 }), T("analyst_count", "Analysts", "num", { dec: 0 }),
        T("pts_analyst", "Analyst points", "points"), T("target_analyst", "Median target", "num", { dec: 2 }), PR,
        T("upside_pct", "Upside %", "pct", { dec: 1 })],
      state: state, pageSize: 25,
    });
    hook(box, state, draw);
    draw();
  }

  function render13f(ctx) {
    const raw = ctx.files["institutional_13f.csv"];
    const all = D.realRows(raw);
    const summary = all.filter((r) => r.row_type === "summary");
    const holders = all.filter((r) => r.row_type === "top_holder");
    ctx.page.innerHTML = D.banner(raw) + '<div class="ctrls" id="ctrls"></div>' +
      '<p class="cap">Summary of the latest public holdings file, plus the largest holders. Not every fund. Built this way so the page stays fast.</p>' +
      '<div class="panel" id="sum"></div><div class="panel" id="top"></div>';
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
      D.drawTable(document.getElementById("sum"), {
        title: "Summary", rows: sums,
        columns: [TK, T("increased_shares", "Shares added", "compact"), T("decreased_shares", "Shares cut", "compact"),
          T("holders", "Holders", "num", { dec: 0 }), T("ownership_pct", "Ownership %", "pct", { dec: 2, color: false }),
          T("pts_institutional", "Points", "points")],
        state: s1, pageSize: 25,
      });
      D.drawTable(document.getElementById("top"), {
        title: "Largest holders", rows: holders.filter((r) => !q || names.has(r.ticker)),
        columns: [TK, T("owner", "Holder", "text", { wrap: true }), T("shares", "Shares", "compact"), T("share_change", "Change", "compact"), T("as_of", "As of", "date")],
        state: s2, pageSize: 10,
      });
    };
    hook(box, s1, draw);
    draw();
  }

  function renderAaii(ctx) {
    const raw = ctx.files["aaii_sentiment.csv"] || [];
    const row = raw[0] || {};
    ctx.page.innerHTML = D.banner(raw) +
      '<div class="panel pad" style="max-width:740px"><div class="m2">Status</div><div style="font-size:18px;font-weight:700;color:#F59E0B;margin:8px 0">' +
      D.esc(row.data_status || "MISSING") + "</div><p>" + D.esc(row.note || "") + "</p></div>" +
      '<p style="margin-top:16px"><a class="linkish" href="put-call.html">The free mood gauge is the put/call ratio.</a></p>';
  }

  function renderInsiders(ctx) {
    const raw = ctx.files["insider_trading.csv"];
    const all = D.realRows(raw);
    ctx.page.innerHTML = D.banner(raw) + '<div class="ctrls" id="ctrls"></div>' +
      '<p class="cap">Open-market buy and sell counts over three months, from Nasdaq\'s public insider summary.</p>' +
      '<div class="cards" id="cards"></div><div class="split"><div class="panel" id="tbl"></div><div class="panel pad"><div class="ptitle">Most insider buys, 3 months</div><div class="chart-box tall"><canvas id="ib"></canvas></div></div></div>';
    const fills = { "1": "#14532D", "0": "#283146", "-1": "#7F1D1D" };
    document.getElementById("cards").innerHTML = ["1", "0", "-1"].map((p) =>
      card("Points " + p, String(countWhere(all, (r) => String(D.num(r.pts_insider)) === p)), "", fills[p])).join("");
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
        columns: [TK, T("buys_3m", "Buys, 3 mo", "num", { dec: 0 }), T("sells_3m", "Sells, 3 mo", "num", { dec: 0 }), T("pts_insider", "Points", "points")],
        state: state, pageSize: 25,
      });
      const top = all.slice().sort((a, b) => (D.num(b.buys_3m) || 0) - (D.num(a.buys_3m) || 0)).slice(0, 10);
      D.destroyCharts();
      D.barChart(document.getElementById("ib"), top.map((r) => r.ticker), top.map((r) => D.num(r.buys_3m)), top.map(() => "#22C55E"), { horizontal: true });
    };
    hook(box, state, draw);
    draw();
  }

  function renderHeadlines(ctx) {
    const raw = ctx.files["headline_sentiment.csv"];
    const all = D.realRows(raw);
    ctx.page.innerHTML = D.banner(raw) + '<div class="ctrls" id="ctrls"></div>' +
      '<p class="cap">Tone is a word rule on the headline (beat, upgrade, probe, layoff, and similar). It is not added into the desk score.</p>' +
      '<div class="cards" id="cards"></div><div class="panel" id="tbl"></div>';
    const fills = { "1": "#14532D", "0": "#283146", "-1": "#7F1D1D" };
    document.getElementById("cards").innerHTML = [["1", "Positive"], ["0", "Neutral"], ["-1", "Negative"]].map((p) =>
      card(p[1], String(countWhere(all, (r) => String(D.num(r.tone)) === p[0])), "", fills[p[0]])).join("");
    const box = document.getElementById("ctrls");
    box.innerHTML = D.multiHtml("tone", "Tone (1 positive, -1 negative)", D.uniq(all, "tone")) +
      D.searchHtml("ticker", "Ticker", "hd-tk", D.uniq(all, "ticker")) +
      D.multiHtml("pub", "Publisher", D.uniq(all, "publisher"));
    const state = { sort: "published", dir: "desc", page: 0 };
    const draw = () => D.drawTable(document.getElementById("tbl"), {
      rows: all.filter((r) => D.matchMulti(r, "tone", D.selectedMulti(box, "tone")) &&
        D.matchMulti(r, "publisher", D.selectedMulti(box, "pub")) && D.matchText(r, "ticker", D.fieldVal(box, "ticker"))),
      columns: [TK, T("tone", "Tone", "tone"), T("headline", "Headline", "text", { wrap: true }), T("publisher", "Source"),
        T("published", "Published"), T("tone_note", "Why this tone", "text", { wrap: true })],
      state: state, pageSize: 25,
    });
    hook(box, state, draw);
    draw();
  }

  function renderXly(ctx) {
    const raw = D.realRows(ctx.files["xly_xlp.csv"]);
    const end = maxDate(raw, "date");
    ctx.page.innerHTML = D.banner(ctx.files["xly_xlp.csv"]) + '<div class="ctrls" id="ctrls"></div>' +
      '<p class="cap">Consumer discretionary divided by consumer staples. Above the 50-day average of the ratio is labeled risk on.</p>' +
      '<div class="cards" id="latest"></div><div class="panel pad"><div class="ptitle">XLY / XLP ratio and its 50-day average</div><div class="chart-box tall"><canvas id="xx"></canvas></div></div><div class="panel" id="tbl"></div>';
    const latest = raw.slice().sort((a, b) => a.date < b.date ? 1 : -1)[0] || {};
    document.getElementById("latest").innerHTML =
      card("Date", D.esc(latest.date || "–")) +
      card("Ratio", D.num(latest.ratio) == null ? D.na() : D.esc(D.fmt(latest.ratio, 3))) +
      card("50-day avg", D.num(latest.ratio_sma50) == null ? D.na() : D.esc(D.fmt(latest.ratio_sma50, 3))) +
      card("Today's zone", D.zoneHtml(latest.zone));
    const box = document.getElementById("ctrls");
    box.innerHTML = '<label class="m2" style="font-size:12px">From<br><input class="dd" type="date" data-filter="from" value="' + shift(end, -182) + '"></label>' +
      D.selectHtml("zone", "Zone", D.uniq(raw, "zone"), "");
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
    ctx.page.innerHTML = D.banner(raw) + '<div class="ctrls" id="ctrls"></div><div id="who"></div><div class="panel" id="tbl"></div>' +
      '<p class="cap">Direction says whether a lower or a higher number earns the point. The industry median needs four peers.</p>';
    const box = document.getElementById("ctrls");
    box.innerHTML = D.searchHtml("ticker", "Ticker", "fn-tk", tickers) + D.multiHtml("metric", "Metric", D.uniq(all, "metric"));
    box.querySelector("[data-filter=ticker]").value = start;
    const state = { sort: "metric", dir: "asc", page: 0 };
    const draw = () => {
      const t = (D.fieldVal(box, "ticker") || start).trim().toUpperCase();
      const rows = all.filter((r) => r.ticker === t && D.matchMulti(r, "metric", D.selectedMulti(box, "metric")));
      const one = rows[0] || {};
      document.getElementById("who").innerHTML = '<div class="big" style="color:#7C9CFF;font-size:24px;font-weight:700">' + D.tickerHtml(t) +
        '</div><div class="m2">' + D.esc(one.sector || "") + "</div>";
      D.drawTable(document.getElementById("tbl"), {
        rows: rows,
        columns: [T("metric", "Metric"), T("direction", "Better when"), T("now_value", "Now", "num", { dec: 2 }),
          T("avg_3y", "Own 3-yr avg", "num", { dec: 2 }), T("pts_vs_self", "Points vs own history", "points"),
          T("industry_median", "Sector median", "num", { dec: 2 }), T("pts_vs_industry", "Points vs sector", "points")],
        state: state, pageSize: 20,
      });
    };
    hook(box, state, draw);
    draw();
  }

  function renderTracker(ctx) {
    const raw = ctx.files["earnings_tracker.csv"];
    const all = D.realRows(raw);
    const end = maxDate(all, "earnings_date");
    ctx.page.innerHTML = D.banner(raw) + '<div class="ctrls" id="ctrls"></div><div class="split">' +
      '<div class="panel pad"><div class="ptitle">EPS surprise %</div><div class="chart-box"><canvas id="su"></canvas></div></div>' +
      '<div class="cards" id="cards"></div></div><div class="panel" id="tbl"></div>';
    const box = document.getElementById("ctrls");
    box.innerHTML = '<label class="m2" style="font-size:12px">From<br><input class="dd" type="date" data-filter="from" value="' + shift(end, -365) + '"></label>' +
      '<label class="m2" style="font-size:12px">To<br><input class="dd" type="date" data-filter="to" value="' + shift(end, 90) + '"></label>' +
      D.searchHtml("ticker", "Ticker", "tr-tk", D.uniq(all, "ticker"));
    const state = { sort: "earnings_date", dir: "desc", page: 0 };
    const draw = () => {
      const from = D.fieldVal(box, "from");
      const to = D.fieldVal(box, "to");
      const q = (D.fieldVal(box, "ticker") || "").trim();
      const rows = all.filter((r) => (!from || r.earnings_date >= from) && (!to || r.earnings_date <= to) && D.matchText(r, "ticker", q));
      document.getElementById("cards").innerHTML =
        card("Beats", String(countWhere(rows, (r) => (D.num(r.surprise_pct) || 0) > 0 && D.num(r.surprise_pct) != null))) +
        card("Misses", String(countWhere(rows, (r) => (D.num(r.surprise_pct) || 0) < 0))) +
        card("Upcoming (no actual yet)", String(countWhere(rows, (r) => D.isBlank(r.eps_actual))));
      const chartRows = rows.filter((r) => D.num(r.surprise_pct) != null).slice().sort((a, b) => a.earnings_date < b.earnings_date ? -1 : 1).slice(-12);
      D.destroyCharts();
      D.barChart(document.getElementById("su"), chartRows.map((r) => r.ticker + " " + r.earnings_date),
        chartRows.map((r) => D.num(r.surprise_pct)),
        chartRows.map((r) => (D.num(r.surprise_pct) || 0) >= 0 ? "#22C55E" : "#EF4444"));
      D.drawTable(document.getElementById("tbl"), {
        rows: rows,
        columns: [TK, T("earnings_date", "Report date", "date"), T("eps_estimate", "EPS estimate", "num", { dec: 2 }),
          T("eps_actual", "EPS actual", "num", { dec: 2 }), T("surprise_pct", "Surprise %", "pct", { dec: 1 }), T("result", "Result", "text")],
        state: state, pageSize: 25,
      });
    };
    hook(box, state, draw);
    draw();
  }

  function renderCompany(ctx) {
    const raw = ctx.files["company_financials.csv"];
    const all = D.realRows(raw);
    const tickers = D.uniq(all, "ticker");
    const start = tickers.indexOf("ADSK") >= 0 ? "ADSK" : (tickers[0] || "");
    const end = maxDate(all, "fy_end");
    ctx.page.innerHTML = D.banner(raw) + '<div class="ctrls" id="ctrls"></div>' +
      '<p class="cap">Annual figures from SEC filings. Margins are blank when the filing did not include that line.</p>' +
      '<div class="split"><div class="panel pad"><div class="ptitle">Revenue and net income</div><div class="chart-box"><canvas id="rev"></canvas></div></div>' +
      '<div class="panel pad"><div class="ptitle">Margins</div><div class="chart-box"><canvas id="mg"></canvas></div></div></div><div class="panel" id="tbl"></div>';
    const box = document.getElementById("ctrls");
    box.innerHTML = D.searchHtml("ticker", "Ticker", "co-tk", tickers) +
      '<label class="m2" style="font-size:12px">From<br><input class="dd" type="date" data-filter="from" value="' + shift(end, -3650) + '"></label>';
    box.querySelector("[data-filter=ticker]").value = start;
    const state = { sort: "fy_end", dir: "desc", page: 0 };
    const draw = () => {
      const t = (D.fieldVal(box, "ticker") || start).trim().toUpperCase();
      const from = D.fieldVal(box, "from");
      const rows = all.filter((r) => r.ticker === t && (!from || r.fy_end >= from)).sort((a, b) => a.fy_end < b.fy_end ? -1 : 1);
      D.destroyCharts();
      D.makeChart(document.getElementById("rev"), {
        type: "bar",
        data: { labels: rows.map((r) => (r.fy_end || "").slice(0, 4)), datasets: [
          { label: "Revenue", data: D.seriesNum(rows, "revenue"), backgroundColor: "#7C9CFF" },
          { label: "Net income", data: D.seriesNum(rows, "net_income"), backgroundColor: "#8B96AD" },
        ] },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { color: "#8B96AD", boxWidth: 12 } } },
          scales: { x: { ticks: { color: "#8B96AD" }, grid: { color: "#1E293B" } }, y: { ticks: { color: "#8B96AD" }, grid: { color: "#1E293B" } } } },
      });
      D.lineChart(document.getElementById("mg"), rows.map((r) => (r.fy_end || "").slice(0, 4)), [
        { label: "Gross margin", data: D.seriesNum(rows, "gross_margin"), color: "#E6EBF5", spanGaps: false },
        { label: "Operating margin", data: D.seriesNum(rows, "operating_margin"), color: "#7C9CFF", spanGaps: false },
        { label: "Net margin", data: D.seriesNum(rows, "net_margin"), color: "#8B96AD", spanGaps: false },
      ], {});
      D.drawTable(document.getElementById("tbl"), {
        rows: rows,
        columns: [T("fy_end", "Fiscal year end", "date"), T("revenue", "Revenue", "compact"), T("gross_profit", "Gross profit", "compact"),
          T("op_income", "Operating income", "compact"), T("net_income", "Net income", "compact"), T("eps", "EPS", "num", { dec: 2 }),
          T("gross_margin", "Gross margin %", "pct", { dec: 1, color: false }), T("operating_margin", "Operating margin %", "pct", { dec: 1, color: false }),
          T("net_margin", "Net margin %", "pct", { dec: 1, color: false }), T("pe", "P/E", "num", { dec: 1 }), T("ps", "P/S", "num", { dec: 2 }), T("pfcf", "P/FCF", "num", { dec: 1 })],
        state: state, pageSize: 12,
      });
    };
    hook(box, state, draw);
    draw();
  }

  function renderDivFund(ctx) {
    const raw = ctx.files["dividend_scanner.csv"];
    const all = D.realRows(raw);
    ctx.page.innerHTML = D.banner(raw) + '<div class="ctrls" id="ctrls"></div><div class="cards" id="cards"></div><div class="panel" id="tbl"></div>' +
      '<p class="cap">A yield of 0 is real: the company does not pay. A dash means the yield could not be read. The Data updates page shows how many are unknown.</p>';
    const payers = all.filter((r) => (D.num(r.div_yield) || 0) > 0);
    document.getElementById("cards").innerHTML =
      card("Payers", String(payers.length)) +
      card("Yield is zero", String(countWhere(all, (r) => D.num(r.div_yield) === 0))) +
      card("Yield unknown", String(countWhere(all, (r) => D.num(r.div_yield) == null))) +
      card("Average yield %, payers", ntext(avg(payers, "div_yield"), 2));
    const box = document.getElementById("ctrls");
    standardFilters(box, all, { sector: true, verdict: true, ticker: true });
    box.insertAdjacentHTML("afterbegin", D.rangeHtml("min", "Min. yield %", 0, 20, 0.01, 0.01));
    const state = { sort: "div_yield", dir: "desc", page: 0 };
    const draw = () => D.drawTable(document.getElementById("tbl"), {
      rows: all.filter((r) => readCommon(box, r) && D.matchMin(r, "div_yield", D.fieldVal(box, "min"))),
      columns: [TK, CO, SE, PR, T("div_yield", "Yield %", "pct"), T("div_yield_avg", "Own avg yield %", "pct", { color: false }),
        T("dps", "Dividend per share", "num", { dec: 2 }), T("pts_div_yield", "Points", "points"), VE],
      state: state, pageSize: 25,
    });
    hook(box, state, draw);
    draw();
  }

  function renderMacro(ctx) {
    const raw = ctx.files["macro_screener.csv"];
    const all = D.realRows(raw);
    ctx.page.innerHTML = D.banner(raw) + '<div class="ctrls" id="ctrls"></div>' +
      '<p class="cap">Signal is +1 when the surprise is in the direction that usually helps stocks (for unemployment and jobless claims, lower is the helpful direction). It is a label, not a forecast.</p>' +
      '<div class="cards" id="cards"></div><div class="panel" id="tbl"></div>';
    const fills = { "1": "#14532D", "0": "#283146", "-1": "#7F1D1D" };
    document.getElementById("cards").innerHTML = ["1", "0", "-1"].map((s) =>
      card("Signal " + s, String(countWhere(all, (r) => String(D.num(r.signal)) === s)), "", fills[s])).join("");
    const box = document.getElementById("ctrls");
    box.innerHTML = D.multiHtml("cat", "Category", D.uniq(all, "category")) +
      D.multiHtml("ind", "Indicator", D.uniq(all, "indicator")) +
      D.multiHtml("sig", "Signal", D.uniq(all, "signal"));
    const state = { sort: "date", dir: "desc", page: 0 };
    const draw = () => D.drawTable(document.getElementById("tbl"), {
      rows: all.filter((r) => D.matchMulti(r, "category", D.selectedMulti(box, "cat")) &&
        D.matchMulti(r, "indicator", D.selectedMulti(box, "ind")) && D.matchMulti(r, "signal", D.selectedMulti(box, "sig"))),
      columns: [T("date", "Date", "date"), T("category", "Category"), T("indicator", "Indicator", "text", { wrap: true }),
        T("actual", "Actual"), T("forecast", "Forecast"), T("surprise", "Surprise"), T("signal", "Signal", "signal")],
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
    ctx.page.innerHTML = D.banner(ctx.files["sector_macro.csv"]) + '<div class="ctrls" id="ctrls"></div><p class="cap">' + D.esc(plain) +
      " Weights are fixed in the job (for example, hotter inflation helps energy and hurts growth sectors).</p>" +
      '<div class="split"><div class="panel" id="mac"></div><div class="panel" id="px"></div></div>';
    const box = document.getElementById("ctrls");
    box.innerHTML = D.multiHtml("score", "Macro score", D.uniq(macro, "macro_score")) +
      D.multiHtml("etf", "Sector ETF", D.uniq(macro, "ticker"));
    const draw = () => {
      const etf = D.selectedMulti(box, "etf");
      const score = D.selectedMulti(box, "score");
      D.drawTable(document.getElementById("mac"), {
        title: "Macro scores", rows: macro.filter((r) => D.matchMulti(r, "ticker", etf) && D.matchMulti(r, "macro_score", score)),
        columns: [T("ticker", "ETF", "ticker"), T("name", "Sector"), T("macro_growth", "Growth", "num", { dec: 0 }),
          T("macro_inflation", "Inflation", "num", { dec: 0 }), T("macro_jobs", "Jobs", "num", { dec: 0 }), T("macro_score", "Total", "num", { dec: 0 })],
        state: { sort: "macro_score", dir: "desc", page: 0 }, pageSize: 19,
      });
      D.drawTable(document.getElementById("px"), {
        title: "Price change (sorted by YTD)", rows: sectors.filter((r) => D.matchMulti(r, "ticker", etf)),
        columns: [T("ticker", "ETF", "ticker"), T("day_pct", "Day %", "pct"), T("week_pct", "Week %", "pct"),
          T("month_pct", "Month %", "pct"), T("ytd_pct", "YTD %", "pct")],
        state: { sort: "ytd_pct", dir: "desc", page: 0 }, pageSize: 19,
      });
    };
    hook(box, { page: 0 }, draw);
    draw();
  }

  function renderHist(ctx) {
    const raw = ctx.files["historical_pe.csv"] || [];
    const all = D.realRows(raw);
    const end = maxDate(all, "date");
    const official = (raw[0] && raw[0].official_status) || "MISSING";
    ctx.page.innerHTML = D.banner(raw) + '<div class="ctrls" id="ctrls"></div>' +
      '<div class="panel pad" style="max-width:640px"><div class="m2">Official S&P 500 P/E</div><div style="font-size:18px;font-weight:700;color:#F59E0B">' + D.esc(official) + "</div>" +
      '<p class="cap">The line below is this desk\'s median trailing P/E. The official series has no free source, so it stays blank.</p></div>' +
      '<div class="panel pad"><div class="ptitle">Desk median trailing P/E</div><div class="chart-box tall"><canvas id="pe"></canvas></div></div><div class="panel" id="tbl"></div>';
    const box = document.getElementById("ctrls");
    box.innerHTML = '<label class="m2" style="font-size:12px">From<br><input class="dd" type="date" data-filter="from" value="' + shift(end, -1825) + '"></label>';
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
          T("n", "Stocks in the median", "num", { dec: 0 }), T("official_sp500_pe", "Official P/E", "num", { dec: 1 })],
        state: state, pageSize: 12,
      });
    };
    hook(box, state, draw);
    draw();
  }

  function renderBreakouts(ctx) {
    const raw = ctx.files["breakouts.csv"];
    const all = D.realRows(raw);
    ctx.page.innerHTML = D.banner(raw) + '<div class="ctrls" id="ctrls"></div><div class="cards" id="cards"></div><div class="panel" id="tbl"></div>' +
      '<p class="cap">Within 1% of the 52-week closing high. If the list is empty, nobody is near a high today: that is a result, and the note above says so.</p>';
    document.getElementById("cards").innerHTML =
      card("Near a high", String(all.length)) +
      card("Volume at least average", String(countWhere(all, (r) => (D.num(r.volume_ratio) || 0) >= 1))) +
      card("BUY", String(countWhere(all, (r) => r.verdict === "BUY")));
    const box = document.getElementById("ctrls");
    standardFilters(box, all, { sector: true, verdict: true, ticker: true });
    const state = { sort: "dist_52w_high_pct", dir: "desc", page: 0 };
    const draw = () => D.drawTable(document.getElementById("tbl"), {
      rows: all.filter((r) => readCommon(box, r)),
      columns: [TK, CO, SE, PR, T("dist_52w_high_pct", "From 52-week high %", "pct", { dec: 2 }),
        T("volume_ratio", "Volume vs 50-day", "num", { dec: 2 }), SC, VE],
      state: state, pageSize: 25,
    });
    hook(box, state, draw);
    draw();
  }

  function renderTrends(ctx) {
    const raw = ctx.files["trends.csv"];
    const all = D.realRows(raw);
    ctx.page.innerHTML = D.banner(raw) + '<div class="ctrls" id="ctrls"></div><div class="cards" id="cards"></div><div class="panel" id="tbl"></div>' +
      '<p class="cap">Uptrend means the price is above all four averages. Downtrend means it is below all four.</p>';
    const colors = { Uptrend: "#22C55E", Mixed: "#8B96AD", Downtrend: "#EF4444" };
    document.getElementById("cards").innerHTML = ["Uptrend", "Mixed", "Downtrend"].map((lab) =>
      card(lab, '<span style="color:' + colors[lab] + '">' + countWhere(all, (r) => r.trend_label === lab) + "</span>")).join("");
    const box = document.getElementById("ctrls");
    const labels = D.uniq(all, "trend_label");
    box.innerHTML = D.multiHtml("trend", "Trend", labels, ["Uptrend"]) + D.multiHtml("sector", "Sector", D.uniq(all, "sector")) +
      D.searchHtml("ticker", "Ticker", "trd", D.uniq(all, "ticker"));
    const state = { sort: "ticker", dir: "asc", page: 0 };
    const draw = () => D.drawTable(document.getElementById("tbl"), {
      rows: all.filter((r) => D.matchMulti(r, "trend_label", D.selectedMulti(box, "trend")) &&
        D.matchMulti(r, "sector", D.selectedMulti(box, "sector")) && D.matchText(r, "ticker", D.fieldVal(box, "ticker"))),
      columns: [TK, CO, T("trend_label", "Trend", "trend"), T("sma_alignment", "Moving averages", "text", { wrap: true }),
        T("above_sma20", "Above 20d", "flag"), T("above_sma50", "Above 50d", "flag"), T("above_sma100", "Above 100d", "flag"),
        T("above_sma200", "Above 200d", "flag"), SC],
      state: state, pageSize: 25,
    });
    hook(box, state, draw);
    draw();
  }

  const pullbacks = passesPage({
    file: "pullbacks.csv",
    caption: "An uptrend (above the 50-day and the 200-day) with price back in the pullback or entry area, and RSI under 70.",
    filters: { passes: "yes", sector: true, verdict: true, ticker: true },
    columns: [TK, CO, PR, T("rsi14", "RSI-14", "num", { dec: 1 }), T("entry_low", "Entry low", "num", { dec: 2 }),
      T("entry_high", "Entry high", "num", { dec: 2 }), SC, VE],
    cards(all) {
      const pass = all.filter((r) => r.passes === "yes");
      return card("Passing the screen", String(pass.length)) +
        card("Of those, BUY", String(countWhere(pass, (r) => r.verdict === "BUY"))) +
        card("Average RSI-14, passing", ntext(avg(pass, "rsi14"), 1));
    },
  });

  function renderGainers(ctx) {
    const raw = ctx.files["gainers_losers.csv"];
    const all = D.realRows(raw);
    ctx.page.innerHTML = D.banner(raw) + '<div class="ctrls" id="ctrls"></div>' +
      '<p class="cap">Day % is the latest session\'s change, for stocks on the desk only.</p><div class="split"><div class="panel" id="up"></div><div class="panel" id="dn"></div></div>';
    const box = document.getElementById("ctrls");
    standardFilters(box, all, { sector: true, verdict: true });
    const cols = [TK, CO, PR, T("day_pct", "Day %", "pct"), SC, VE];
    const draw = () => {
      const rows = all.filter((r) => readCommon(box, r));
      D.drawTable(document.getElementById("up"), {
        title: "Biggest gainers today", rows: rows.filter((r) => r.side === "gainer"), columns: cols,
        state: { sort: "day_pct", dir: "desc", page: 0 }, pageSize: 15,
      });
      D.drawTable(document.getElementById("dn"), {
        title: "Biggest losers today", rows: rows.filter((r) => r.side === "loser"), columns: cols,
        state: { sort: "day_pct", dir: "asc", page: 0 }, pageSize: 15,
      });
    };
    hook(box, { page: 0 }, draw);
    draw();
  }

  function renderBreadth(ctx) {
    const raw = D.realRows(ctx.files["breadth_history.csv"]);
    const mt = (ctx.files["market_today.csv"] || [])[0] || {};
    const end = maxDate(raw, "date");
    ctx.page.innerHTML = D.banner(ctx.files["breadth_history.csv"]) + '<div class="ctrls" id="ctrls"></div><div class="cards" id="cards"></div>' +
      '<div class="panel pad"><div class="ptitle">Share of the desk above each average</div><div class="chart-box tall"><canvas id="br"></canvas></div></div>' +
      '<p class="cap">A blank point is a session that did not have enough prices. The gap is left open, never drawn as zero.</p>';
    const keys = [["breadth_sma20", "% above 20-day"], ["breadth_sma50", "% above 50-day"], ["breadth_sma100", "% above 100-day"], ["breadth_sma200", "% above 200-day"]];
    document.getElementById("cards").innerHTML = keys.map((k) => card(k[1], D.num(mt[k[0]]) == null ? D.na() : D.esc(D.fmt(mt[k[0]], 1) + "%"))).join("");
    const box = document.getElementById("ctrls");
    box.innerHTML = '<label class="m2" style="font-size:12px">From<br><input class="dd" type="date" data-filter="from" value="' + shift(end, -182) + '"></label>';
    const draw = () => {
      const from = D.fieldVal(box, "from");
      const rows = raw.filter((r) => !from || r.date >= from);
      D.destroyCharts();
      D.lineChart(document.getElementById("br"), rows.map((r) => r.date), [
        { label: "Above 20-day", data: D.seriesNum(rows, "pct_above_sma20"), color: "#7C9CFF" },
        { label: "Above 50-day", data: D.seriesNum(rows, "pct_above_sma50"), color: "#22C55E" },
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
    ctx.page.innerHTML = D.banner(raw) + '<div class="ctrls" id="ctrls"></div>' +
      '<p class="cap">Equal weight across the desk\'s stocks in each sector, not the sector ETF. The ETF view is on Today.</p>' +
      '<div class="panel pad"><div class="ptitle">Past month, equal-weight %</div><div class="chart-box"><canvas id="sp"></canvas></div></div><div class="panel" id="tbl"></div>';
    const box = document.getElementById("ctrls");
    box.innerHTML = D.multiHtml("sector", "Sector", D.uniq(all, "sector")) + D.rangeHtml("min", "Min. stocks", 1, 200, 5, 1);
    const state = { sort: "month_pct", dir: "desc", page: 0 };
    const draw = () => {
      const rows = all.filter((r) => D.matchMulti(r, "sector", D.selectedMulti(box, "sector")) && D.matchMin(r, "n", D.fieldVal(box, "min")));
      const ordered = rows.slice().sort((a, b) => (D.num(b.month_pct) || -999) - (D.num(a.month_pct) || -999));
      D.destroyCharts();
      D.barChart(document.getElementById("sp"), ordered.map((r) => r.sector), ordered.map((r) => D.num(r.month_pct)),
        ordered.map((r) => (D.num(r.month_pct) || 0) >= 0 ? "#22C55E" : "#EF4444"));
      D.drawTable(document.getElementById("tbl"), {
        rows: rows,
        columns: [SE, T("day_pct", "Day %", "pct"), T("week_pct", "Week %", "pct"), T("month_pct", "Month %", "pct"),
          T("month3_pct", "3 months %", "pct"), T("ytd_pct", "YTD %", "pct"), T("pct_above_sma50", "% above 50-day", "pct", { dec: 1, color: false }),
          T("score_avg", "Average score", "num", { dec: 1 }), T("n", "Stocks", "num", { dec: 0 })],
        state: state, pageSize: 20,
      });
    };
    hook(box, state, draw);
    draw();
  }

  function renderHeatmaps(ctx) {
    const raw = ctx.files["heatmaps.csv"];
    const all = D.realRows(raw);
    ctx.page.innerHTML = D.banner(raw) + '<div class="ctrls" id="ctrls"></div>' +
      '<p class="cap">Each cell is that stock\'s own return. The sector column on the right is the plain average of the desk\'s stocks, not the ETF.</p>' +
      '<div class="split"><div class="panel" id="tbl"></div><div class="panel" id="avg"></div></div>';
    const box = document.getElementById("ctrls");
    box.innerHTML = D.multiHtml("sector", "Sector", D.uniq(all, "sector")) +
      D.selectHtml("above", "Above 200-day", ["1", "0"], "") +
      D.searchHtml("ticker", "Ticker", "ht", D.uniq(all, "ticker"));
    const state = { sort: "ret_1d", dir: "desc", page: 0 };
    const draw = () => {
      const above = D.fieldVal(box, "above");
      const rows = all.filter((r) => D.matchMulti(r, "sector", D.selectedMulti(box, "sector")) &&
        D.matchText(r, "ticker", D.fieldVal(box, "ticker")) && (!above || String(D.num(r.above_sma200)) === above || r.above_sma200 === above));
      D.drawTable(document.getElementById("tbl"), {
        rows: rows,
        columns: [TK, CO, T("ret_1d", "1 day %", "heatpct", { dec: 1 }), T("ret_1w", "1 week %", "heatpct", { dec: 1 }),
          T("ret_1m", "1 month %", "heatpct", { dec: 1 }), T("ret_ytd", "YTD %", "heatpct", { dec: 1 }),
          T("above_sma20", "20d", "flag"), T("above_sma50", "50d", "flag"), T("above_sma100", "100d", "flag"), T("above_sma200", "200d", "flag")],
        state: state, pageSize: 25,
      });
      const sectors = D.uniq(rows, "sector").map((s) => {
        const sub = rows.filter((r) => r.sector === s);
        return { sector: s, ret_1d: avg(sub, "ret_1d") == null ? "" : String(avg(sub, "ret_1d")) };
      });
      D.drawTable(document.getElementById("avg"), {
        title: "Average of the stocks above, 1 day %", rows: sectors,
        columns: [SE, T("ret_1d", "1 day %", "heatpct", { dec: 2 })],
        state: { sort: "ret_1d", dir: "desc", page: 0 }, pageSize: 15,
      });
    };
    hook(box, state, draw);
    draw();
  }

  function renderUpdates(ctx) {
    const log = ctx.files["updates_log.csv"] || [];
    const fresh = D.realRows(ctx.files["freshness.csv"]);
    ctx.page.innerHTML = '<div class="ctrls" id="ctrls"></div><div class="split"><div class="panel" id="log"></div><div class="panel" id="fr"></div></div>';
    const box = document.getElementById("ctrls");
    box.innerHTML = D.multiHtml("status", "Status", D.uniq(log, "status"));
    const draw = () => {
      D.drawTable(document.getElementById("log"), {
        title: "Updates log",
        rows: log.filter((r) => D.matchMulti(r, "status", D.selectedMulti(box, "status"))),
        columns: [T("checked_pt", "Checked (PT)"), T("source", "Source", "text", { wrap: true }), T("status", "Status", "fresh"),
          T("latest", "Latest"), T("note", "Note", "text", { wrap: true })],
        state: { sort: "checked_pt", dir: "desc", page: 0 }, pageSize: 25,
      });
      const host = document.getElementById("fr");
      const rows = fresh.slice().sort((a, b) => (D.num(b.n_missing) || 0) - (D.num(a.n_missing) || 0));
      host.innerHTML = '<div class="pad" style="padding-bottom:0"><div class="ptitle">How many names are filled in</div></div><div class="scroll"><table><thead><tr><th>Field</th><th class="num">On file</th><th class="num">Missing</th></tr></thead><tbody>' +
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
    ctx.page.innerHTML = '<div class="ctrls" id="ctrls"></div><div class="panel" id="help"></div><div class="panel" id="set"></div>';
    const box = document.getElementById("ctrls");
    box.innerHTML = D.searchHtml("topic", "Topic", "topics", D.uniq(help, "topic")) +
      '<label class="m2" style="font-size:12px">Setting contains<br><input class="dd" data-filter="setting" placeholder="scoring."></label>';
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
        title: "Settings",
        rows: settings.filter((r) => !setting || (r.setting || "").toLowerCase().indexOf(setting) >= 0),
        columns: [T("setting", "Setting"), T("value", "Value", "text", { wrap: true })],
        state: { sort: "setting", dir: "asc", page: 0 }, pageSize: 10,
      });
    };
    hook(box, { page: 0 }, draw);
    draw();
  }

  window.DESK_PAGES = {
    today: { files: ["market_today.csv", "breadth_history.csv", "sectors.csv", "alerts.csv"], render: renderToday },
    top: { files: ["scores.csv"], render: renderTop },
    scorecard: { files: ["scores.csv", "score_details.csv", "prices.csv", "news.csv", "earnings_history.csv"], render: renderScorecard },
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
    calendar: { files: ["earnings_calendar.csv"], render: renderCalendar },
    heatmap: { files: ["earnings_heatmap.csv"], render: renderHeat },
    cards: { files: ["earnings_cards.csv"], render: renderCards },
    putcall: { files: ["put_call.csv"], render: renderPutCall },
    walls: { files: ["option_walls.csv"], render: renderWalls },
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
