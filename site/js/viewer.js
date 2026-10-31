/* Chart Viewer: one big chart at a time, swipe to the next. Reads saved CSVs only. No new market requests. */
(function () {
  // ---------- Lists (plain functions, also run by tests/chart_viewer_logic.js under node) ----------
  const LISTS = [
    { id: "buysetups", label: "Buy setups", short: "Buy setup", file: "buy_setups.csv", kind: "buy", feature: "feature.buy_setups", scanner: false },
    { id: "watchlist", label: "Watchlist", short: "Watchlist", file: "watchlist.csv", kind: "watch", feature: "feature.watchlist_portfolio", scanner: false },
    { id: "vcp", label: "VCP", short: "VCP", file: "scanner_vcp.csv", kind: "pattern", feature: "feature.scanner_vcp", scanner: true },
    { id: "canslim", label: "CANSLIM", short: "CANSLIM", file: "scanner_canslim.csv", kind: "pattern", feature: "feature.scanner_canslim", scanner: true },
    { id: "box", label: "Box breakout", short: "Box", file: "scanner_box.csv", kind: "pattern", feature: "feature.scanner_box", scanner: true },
    { id: "flag", label: "Flag breakout", short: "Flag", file: "scanner_flag.csv", kind: "pattern", feature: "feature.scanner_flag", scanner: true },
    { id: "qullamaggie", label: "Qullamaggie breakout", short: "Qullamaggie", file: "scanner_qullamaggie.csv", kind: "pattern", feature: "feature.scanner_qullamaggie", scanner: true },
    { id: "marios", label: "Marios breakout", short: "Marios", file: "scanner_marios.csv", kind: "pattern", feature: "feature.scanner_marios", scanner: true },
    { id: "ep", label: "Episodic pivot", short: "EP", file: "scanner_ep.csv", kind: "pattern", feature: "feature.scanner_ep", scanner: true },
    { id: "leaders", label: "Leaders", short: "Leaders", file: "scanner_leaders.csv", kind: "pattern", feature: "feature.scanner_leaders", scanner: true },
    { id: "breakdowns", label: "Breakdowns", short: "Breakdown", file: "scanner_breakdown.csv", kind: "pattern", feature: "feature.scanner_breakdown", scanner: true },
    { id: "volume", label: "High volume", short: "High volume", file: "scanner_volume.csv", kind: "volume", feature: "feature.scanner_volume", scanner: true },
    { id: "week52", label: "52-week", short: "52-week", file: "scanner_52w.csv", kind: "w52", feature: "feature.scanner_52w", scanner: true },
    { id: "growth", label: "Growth", short: "Growth", file: "scanner_growth.csv", kind: "pass", feature: "feature.scanner_growth", scanner: true },
    { id: "quality", label: "Quality", short: "Quality", file: "scanner_quality.csv", kind: "pass", feature: "feature.scanner_quality", scanner: true },
    { id: "dividend", label: "Dividend", short: "Dividend", file: "scanner_dividend.csv", kind: "pass", feature: "feature.scanner_dividend", scanner: true },
    { id: "wheel", label: "Wheel (stocks only)", short: "Wheel", file: "scanner_wheel.csv", kind: "pass", feature: "feature.scanner_wheel", scanner: true },
  ];
  const STATUS_RANK = {
    "BROKEN OUT today": 0, "BROKEN DOWN today": 0, "EP TODAY - CONFIRMED": 0, "NEW HIGH ON VOLUME": 0,
    "READY": 1, "EP TODAY - FORMING": 1, "DAY 2-5 WATCH": 1, "NEW HIGH": 1, "PASSES": 1, "BUYING": 1,
    "IN TRADE": 2, "NEAR HIGH": 2, "SELLING": 2, "ON WATCHLIST": 2,
    "DELAYED EP WATCH": 3, "NEW LOW": 3, "WATCHING": 4, "EP FADED": 5, "CLOSED": 6,
  };
  function rankOf(status) {
    const r = STATUS_RANK[String(status || "")];
    return r == null ? 3 : r;
  }
  function txt(v) {
    if (v == null) return "";
    const s = String(v).trim();
    const low = s.toLowerCase();
    return low === "nan" || low === "none" || low === "null" ? "" : s;
  }
  function numOf(v) {
    const s = txt(v).replace(/,/g, "");
    if (!s) return null;
    const n = Number(s);
    return Number.isFinite(n) ? n : null;
  }
  function yes(v) { return txt(v).toLowerCase() === "yes"; }
  // Short version of a long reason: whole sentences while they fit, then a clean word cut.
  function shorten(text, max) {
    const s = txt(text).replace(/\s+/g, " ");
    max = max > 0 ? max : 110;
    if (s.length <= max) return s;
    // A sentence ends at . ! or ? followed by a space and a capital letter, so 1373.7 or (63d) never splits.
    const parts = s.split(/(?<=[.!?])\s+(?=[A-Z])/);
    let out = "";
    for (let i = 0; i < parts.length; i++) {
      const next = out ? out + " " + parts[i] : parts[i];
      if (next.length > max) break;
      out = next;
    }
    if (out.length >= Math.min(40, max * 0.5)) return out;
    const cut = s.slice(0, max);
    const sp = cut.lastIndexOf(" ");
    return (sp > max * 0.5 ? cut.slice(0, sp) : cut).replace(/[\s,;:.]+$/, "") + "...";
  }
  function fmt2(n) { return n == null ? "" : (Math.round(n * 100) / 100).toFixed(2); }
  // One row on one list becomes { status, reason }, or null when that row is not on the list.
  function entryFor(list, row, opts) {
    opts = opts || {};
    if (!row || !txt(row.ticker) || txt(row.data_status) === "MISSING") return null;
    if (list.kind === "pattern") {
      const status = txt(row.status);
      if (!status) return null;
      if (status === "CLOSED" && !opts.includeClosed) return null;
      if (status === "WATCHING" && !opts.includeWatching) return null;
      return { status: status, reason: txt(row.reason) };
    }
    if (list.kind === "pass") {
      if (!yes(row.passes)) return null;
      return { status: "PASSES", reason: txt(row.why) };
    }
    if (list.kind === "volume") {
      if (!yes(row.spike) && !yes(row.streak) && !yes(row.quiet)) return null;
      const dir = txt(row.direction).toUpperCase();
      return { status: yes(row.quiet) && !yes(row.spike) ? "QUIET" : (dir || "HIGH VOLUME"), reason: txt(row.reason) };
    }
    if (list.kind === "w52") {
      if (yes(row.new_high_today)) {
        const onVol = yes(row.high_on_volume);
        return { status: onVol ? "NEW HIGH ON VOLUME" : "NEW HIGH", reason: "Closed at a new 52-week high today" + (onVol ? ", on big volume." : ".") };
      }
      if (yes(row.new_low_today)) return { status: "NEW LOW", reason: "Closed at a new 52-week low today." };
      if (yes(row.near_high)) {
        const gap = numOf(row.pct_from_high);
        return { status: "NEAR HIGH", reason: "Within 5% of its 52-week high" + (gap == null ? "." : " (" + fmt2(Math.abs(gap)) + "% under it).") };
      }
      return null;
    }
    if (list.kind === "buy") {
      return { status: txt(row.best_status) || "READY", reason: txt(row.reason) || (txt(row.setup_sources) ? "From " + txt(row.setup_sources) + "." : "") };
    }
    if (list.kind === "watch") {
      const note = txt(row.note_input);
      const trend = txt(row.timing);
      return { status: "ON WATCHLIST", reason: note || ("On your watchlist." + (trend ? " Trend: " + trend + "." : "")) };
    }
    return null;
  }
  function compareTickers(a, b) { return a < b ? -1 : a > b ? 1 : 0; }
  // files: { "scanner_vcp.csv": [rows], ... }. opts.featureOn(key) says if a list is turned on.
  function buildLists(files, opts) {
    opts = opts || {};
    const on = opts.featureOn || (() => true);
    const info = {};
    const scores = {};
    (files["scores.csv"] || []).forEach((r) => {
      const t = txt(r.ticker).toUpperCase();
      if (t) scores[t] = r;
    });
    const touch = (t, row) => {
      if (!info[t]) {
        const s = scores[t] || {};
        info[t] = { ticker: t, company: txt(s.company) || txt(row && row.company), score: numOf(s.score), price: numOf(s.price),
          dayPct: numOf(s.day_pct), strength: null, count: 0, entries: [] };
      }
      if (!info[t].company && row) info[t].company = txt(row.company);
      return info[t];
    };
    const lists = [];
    LISTS.forEach((list, order) => {
      if (!on(list.feature)) return;
      if (list.kind === "buy" && opts.includeBuySetups === false) return;
      if (list.kind === "watch" && opts.includeWatchlist === false) return;
      const rows = files[list.file] || [];
      const items = [];
      const seen = {};
      rows.forEach((row) => {
        const e = entryFor(list, row, opts);
        if (!e) return;
        const t = txt(row.ticker).toUpperCase();
        if (seen[t]) return;
        seen[t] = true;
        const it = touch(t, row);
        it.entries.push({ list: list.id, label: list.short, status: e.status, reason: e.reason, order: order });
        if (list.scanner) it.count += 1;
        const st = numOf(row.strength);
        if (list.kind === "pattern" && st != null && (it.strength == null || st > it.strength)) it.strength = st;
        items.push({ t: t, rank: rankOf(e.status), strength: numOf(row.strength), vol: numOf(row.volume_ratio) });
      });
      if (list.kind === "watch" && !items.length) return;
      items.sort((a, b) => {
        if (a.rank !== b.rank) return a.rank - b.rank;
        const sa = list.kind === "volume" ? a.vol : a.strength;
        const sb = list.kind === "volume" ? b.vol : b.strength;
        if (sa != null || sb != null) {
          if (sa == null) return 1;
          if (sb == null) return -1;
          if (sb !== sa) return sb - sa;
        }
        const ca = (info[a.t] || {}).score;
        const cb = (info[b.t] || {}).score;
        if ((cb == null ? -1e9 : cb) !== (ca == null ? -1e9 : ca)) return (cb == null ? -1e9 : cb) - (ca == null ? -1e9 : ca);
        return compareTickers(a.t, b.t);
      });
      lists.push({ id: list.id, label: list.label, scanner: list.scanner, items: items.map((x) => x.t) });
    });
    const all = Object.keys(info).filter((t) => info[t].count > 0);
    const big = (v) => (v == null ? -1e9 : v);
    all.sort((a, b) => {
      const A = info[a], B = info[b];
      if (B.count !== A.count) return B.count - A.count;
      if (big(B.strength) !== big(A.strength)) return big(B.strength) - big(A.strength);
      if (big(B.score) !== big(A.score)) return big(B.score) - big(A.score);
      return compareTickers(a, b);
    });
    Object.keys(info).forEach((t) => {
      info[t].entries.sort((x, y) => rankOf(x.status) - rankOf(y.status) || x.order - y.order);
    });
    lists.unshift({ id: "all", label: "All scanner stocks", scanner: true, items: all });
    return { lists: lists, info: info };
  }
  // Which way a finished touch went: "next", "prev", or "" (not a swipe).
  function swipeDirection(dx, dy, ms, opts) {
    opts = opts || {};
    const minPx = opts.minPx > 0 ? opts.minPx : 50;
    const ratio = opts.ratio > 0 ? opts.ratio : 1.5;
    const maxMs = opts.maxMs > 0 ? opts.maxMs : 700;
    if (Math.abs(dx) < minPx) return "";
    if (Math.abs(dx) < ratio * Math.abs(dy)) return "";
    if (opts.touchPan && ms > maxMs) return "";
    const right = dx > 0;
    const rightIsNext = opts.rightIsNext !== false;
    return right === rightIsNext ? "next" : "prev";
  }
  // How many empty bars to leave on the right so a box of boxPx does not cover the last candles.
  function padBars(visibleBars, plotPx, boxPx) {
    if (!(visibleBars > 0) || !(plotPx > 0) || !(boxPx > 0)) return 3;
    if (plotPx - boxPx < plotPx * 0.35) boxPx = plotPx * 0.65;
    return Math.max(3, (boxPx * visibleBars) / (plotPx - boxPx));
  }
  const api = { LISTS: LISTS, entryFor: entryFor, buildLists: buildLists, shorten: shorten, swipeDirection: swipeDirection, padBars: padBars, rankOf: rankOf };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (typeof window === "undefined") return;

  // ---------- Page ----------
  const D = window.Desk;
  const MAS = [
    { n: 10, color: "#38BDF8" },
    { n: 20, color: "#7C9CFF" },
    { n: 50, color: "#C3CBDB" },
    { n: 150, color: "#F59E0B" },
    { n: 200, color: "#E879F9" },
  ];
  const GOOD = /BROKEN OUT|READY|CONFIRMED|PASSES|BUYING|NEW HIGH|IN TRADE|FORMING/;
  const WARN = /WATCH|NEAR HIGH|QUIET|ON WATCHLIST|DAY 2-5/;
  const BAD = /BROKEN DOWN|SELLING|NEW LOW|FADED/;
  function statusColor(s) {
    if (BAD.test(s)) return D.DN;
    if (GOOD.test(s)) return D.UP;
    if (WARN.test(s)) return D.AM;
    return D.MU;
  }
  // Defaults match config.json, so a settings file from before this page still behaves the same.
  const OFF_BY_DEFAULT = { include_closed: true, chart_touch_pan: true, ma_10: true, ma_20: true };
  function on(key) {
    if (!D.featureOn("feature.chart_viewer")) return false;
    const v = D.settingVal("chart_viewer." + key);
    if (v == null || String(v).trim() === "") return !OFF_BY_DEFAULT[key];
    return String(v).toLowerCase() !== "false";
  }
  function cfgNum(key, fallback) {
    const v = Number(D.settingVal("chart_viewer." + key));
    return Number.isFinite(v) && v > 0 ? v : fallback;
  }
  function stored(key, fallback) {
    try {
      const v = localStorage.getItem(key);
      if (v === "1") return true;
      if (v === "0") return false;
    } catch (e) { /* storage can be blocked */ }
    return fallback;
  }
  function store(key, value) {
    try { localStorage.setItem(key, value ? "1" : "0"); } catch (e) { /* ignore */ }
  }
  function maState() {
    const out = {};
    let saved = null;
    try { saved = JSON.parse(localStorage.getItem("desk-cv-ma") || "null"); } catch (e) { saved = null; }
    MAS.forEach((m) => {
      const def = on("ma_" + m.n);
      out[m.n] = saved && typeof saved[m.n] === "boolean" ? saved[m.n] : def;
    });
    return out;
  }
  function saveMa(state) {
    try { localStorage.setItem("desk-cv-ma", JSON.stringify(state)); } catch (e) { /* ignore */ }
  }

  function render(ctx) {
    const built = buildLists(ctx.files, {
      featureOn: D.featureOn,
      includeWatching: on("include_watching"),
      includeClosed: on("include_closed"),
      includeBuySetups: on("include_buy_setups"),
      includeWatchlist: on("include_watchlist"),
    });
    const params = new URLSearchParams(location.search);
    let list = built.lists.find((l) => l.id === params.get("list")) || built.lists[0];
    let items = list.items.slice();
    const startTicker = String(params.get("t") || "").trim().toUpperCase();
    if (startTicker && items.indexOf(startTicker) < 0) items.unshift(startTicker);
    let index = Math.max(0, items.indexOf(startTicker));
    const touchPan = on("chart_touch_pan");
    const state = {
      ma: maState(),
      vol: on("volume_toggle") ? stored("desk-cv-vol", on("volume")) : on("volume"),
      why: on("reason_box") && (on("reason_box_toggle") ? stored("desk-cv-why", true) : true),
      rightIsNext: on("flip_toggle") ? stored("desk-cv-right-next", on("swipe_right_is_next")) : on("swipe_right_is_next"),
      open: false,
    };

    const shownLists = built.lists.filter((l) => l.items.length || l.id === list.id || l.id === "all");
    const picker = on("list_picker")
      ? '<label class="ctl wide cvpick"><span class="lab">List</span><select id="cvlist" aria-label="Pick a list">' +
        shownLists.map((l) => '<option value="' + D.esc(l.id) + '"' + (l.id === list.id ? " selected" : "") + ">" +
          D.esc(l.label + " (" + l.items.length + ")") + "</option>").join("") + "</select></label>"
      : "";
    const fsBtn = on("fullscreen") ? '<button type="button" class="cvbtn cvgo" id="cvgo">Full screen</button>' : "";
    const chips = (on("ma_chips") ? MAS.map((m) =>
      '<button type="button" class="cvchip" data-ma="' + m.n + '" aria-pressed="false"><i style="background:' + m.color + '"></i>MA ' + m.n + "</button>").join("") : "") +
      (on("volume_toggle") ? '<button type="button" class="cvchip" data-tool="vol" aria-pressed="false">Vol</button>' : "") +
      (on("reason_box") && on("reason_box_toggle") ? '<button type="button" class="cvchip" data-tool="why" aria-pressed="false">Why</button>' : "") +
      (on("swipe") && on("flip_toggle") ? '<button type="button" class="cvchip" data-tool="flip" title="Swap which way you swipe for the next chart"></button>' : "");
    ctx.page.innerHTML =
      '<div class="ctrls cvctrls">' + picker + fsBtn + "</div>" +
      '<p class="cap" id="cvsum"></p>' +
      '<div class="cv" id="cv" tabindex="-1">' +
        '<div class="cv-top">' +
          '<div class="cv-id"><div class="cv-line"><span class="cv-tk" id="cvtk"></span><span class="cv-co" id="cvco"></span></div>' +
          (on("company_line") ? '<div class="cv-blurb" id="cvblurb"></div>' : "") + "</div>" +
          '<div class="cv-px" id="cvpx"></div>' +
          (on("counter") ? '<div class="cv-count" id="cvcount"></div>' : "") +
          '<button type="button" class="cv-x" id="cvx" aria-label="Close full screen">✕</button>' +
        "</div>" +
        (chips ? '<div class="cv-tools" id="cvtools">' + chips + "</div>" : "") +
        '<div class="cv-body" id="cvbody">' +
          '<div class="cv-chart" id="cvchart"></div>' +
          '<div class="cv-msg" id="cvmsg" hidden></div>' +
          (on("reason_box") ? '<div class="cv-why" id="cvwhy" role="button" tabindex="0" aria-expanded="false"></div>' : "") +
          (on("arrows") ? '<button type="button" class="cv-arrow cv-prev" id="cvprev" aria-label="Previous chart">‹</button>' +
            '<button type="button" class="cv-arrow cv-next" id="cvnext" aria-label="Next chart">›</button>' : "") +
        "</div>" +
      "</div>" +
      '<p class="cap">Daily bars saved by the desk. Averages are worked out in your browser. Charting by <a href="https://www.tradingview.com/">TradingView</a> Lightweight Charts™.</p>';

    const cv = document.getElementById("cv");
    const body = document.getElementById("cvbody");
    const host = document.getElementById("cvchart");
    const msg = document.getElementById("cvmsg");
    const why = document.getElementById("cvwhy");
    let chart = null;
    let maSeries = {};
    let bars = [];
    let token = 0;

    function syncTools() {
      document.querySelectorAll("#cvtools [data-ma]").forEach((b) => {
        const v = !!state.ma[b.getAttribute("data-ma")];
        b.classList.toggle("on", v);
        b.setAttribute("aria-pressed", v ? "true" : "false");
      });
      const vol = document.querySelector('#cvtools [data-tool="vol"]');
      if (vol) { vol.classList.toggle("on", state.vol); vol.setAttribute("aria-pressed", state.vol ? "true" : "false"); }
      const w = document.querySelector('#cvtools [data-tool="why"]');
      if (w) { w.classList.toggle("on", state.why); w.setAttribute("aria-pressed", state.why ? "true" : "false"); }
      const flip = document.querySelector('#cvtools [data-tool="flip"]');
      if (flip) flip.textContent = state.rightIsNext ? "Swipe right: next" : "Swipe left: next";
      if (why) why.hidden = !state.why;
    }
    function summary() {
      const sum = document.getElementById("cvsum");
      if (!sum) return;
      sum.textContent = items.length
        ? list.label + ": " + items.length + " stock" + (items.length === 1 ? "" : "s") + (list.id === "all" ? ", the ones on the most scanners first." : ".")
        : "No stocks on this list today.";
    }
    function reasonHtml(t) {
      const it = built.info[t];
      const entries = (it && it.entries) || [];
      if (!entries.length) return '<div class="cv-why-h">Why it is here</div><div class="cv-why-r">Not on a scanner list today.</div>';
      const max = cfgNum("reason_max_chars", 110);
      const count = it.count;
      const keep = cfgNum("reason_collapsed_items", 3);
      const hidden = state.open ? 0 : Math.max(0, entries.length - keep);
      return '<div class="cv-why-h">Why it is here' + (count ? " (" + count + " scanner" + (count === 1 ? "" : "s") + ")" : "") + "</div>" +
        (state.open ? entries : entries.slice(0, keep)).map((e) => '<div class="cv-why-i"><span class="cv-why-l">' + D.esc(e.label) +
          '</span> <span class="cv-why-s" style="color:' + statusColor(e.status) + '">' + D.esc(e.status) + '</span><div class="cv-why-r">' +
          D.esc(state.open ? e.reason : shorten(e.reason, max)) + "</div></div>").join("") +
        '<div class="cv-why-x">' + (state.open ? "Tap to make it small" : (hidden ? "+ " + hidden + " more. " : "") + "Tap to read all") + "</div>";
    }
    function boxPad() {
      if (!why || why.hidden || !chart) return 0;
      return why.offsetWidth + 14;
    }
    function placeBox() {
      if (!why || !chart) return;
      let psw = 56, tsh = 26;
      try { psw = chart.priceScale("right").width() || psw; } catch (e) { /* not drawn yet */ }
      try { tsh = chart.timeScale().height() || tsh; } catch (e) { /* not drawn yet */ }
      why.style.right = (psw + 6) + "px";
      why.style.bottom = (tsh + 6) + "px";
    }
    function fitView() {
      if (!chart || !bars.length) return;
      placeBox();
      const n = bars.length;
      let plot = 0;
      try { plot = chart.timeScale().width(); } catch (e) { plot = host.clientWidth - 60; }
      const months = plot && plot < 520 ? cfgNum("range_months_phone", 3) : cfgNum("range_months", 6);
      const end = new Date(bars[n - 1].date + "T00:00:00Z");
      end.setUTCMonth(end.getUTCMonth() - months);
      const cut = end.toISOString().slice(0, 10);
      let from = 0;
      for (let i = 0; i < n; i++) { if (bars[i].date >= cut) { from = i; break; } }
      const visible = n - from;
      const pad = padBars(visible, plot, state.open ? Math.min(boxPad(), 260) : boxPad());
      try {
        chart.timeScale().setVisibleLogicalRange({ from: from - 0.5, to: n - 1 + pad });
      } catch (e) { /* chart is gone */ }
    }
    function dropChart() {
      if (chart) { try { chart.remove(); } catch (e) { /* already gone */ } }
      chart = null;
      maSeries = {};
    }
    function header(t, rows) {
      const it = built.info[t] || {};
      document.getElementById("cvtk").textContent = t || "";
      document.getElementById("cvco").textContent = it.company || "";
      const blurb = document.getElementById("cvblurb");
      if (blurb) blurb.textContent = D.blurbOf(t) || "";
      let close = null, change = null;
      if (rows && rows.length) {
        close = rows[rows.length - 1].c;
        const prev = rows.length > 1 ? rows[rows.length - 2].c : null;
        if (prev) change = (close / prev - 1) * 100;
      } else {
        close = it.price;
        change = it.dayPct;
      }
      const px = document.getElementById("cvpx");
      const ch = change == null || !on("day_change") ? "" :
        ' <span class="' + (change >= 0 ? "up" : "dn") + '">' + (change >= 0 ? "+" : "") + D.fmt(change, 2) + "%</span>";
      px.innerHTML = close == null ? "" : '<b>' + D.esc(D.fmt(close, 2)) + "</b>" + ch;
      const count = document.getElementById("cvcount");
      if (count) count.textContent = items.length ? (index + 1) + " of " + items.length : "0 of 0";
      if (why) {
        why.innerHTML = reasonHtml(t);
        why.setAttribute("aria-expanded", state.open ? "true" : "false");
        why.classList.toggle("open", state.open);
      }
    }
    function draw(t, rows, my) {
      if (my !== token) return;
      dropChart();
      bars = D.barsFromRows(rows || []);
      header(t, bars);
      if (!bars.length) {
        msg.hidden = false;
        msg.textContent = "No saved chart for " + t + ". Swipe for the next one.";
        return;
      }
      msg.hidden = true;
      const LC = LightweightCharts;
      chart = LC.createChart(host, {
        autoSize: true,
        layout: { background: { type: "solid", color: "#0B0F17" }, textColor: D.MU, fontFamily: "Roboto, Arial, sans-serif", fontSize: 11,
          attributionLogo: false, panes: { separatorColor: "#1E293B", separatorHoverColor: "rgba(0,0,0,0)", enableResize: false } },
        grid: { vertLines: { color: "#161E2E" }, horzLines: { color: "#161E2E" } },
        crosshair: { mode: LC.CrosshairMode.Magnet },
        rightPriceScale: { borderColor: "#1E293B", scaleMargins: { top: 0.08, bottom: 0.06 } },
        timeScale: { borderColor: "#1E293B", rightOffset: 4 },
        handleScroll: { mouseWheel: false, pressedMouseMove: true, horzTouchDrag: touchPan, vertTouchDrag: false },
        handleScale: { mouseWheel: true, pinch: touchPan, axisPressedMouseMove: true, axisDoubleClickReset: true },
        kineticScroll: { touch: false, mouse: false },
      });
      const price = chart.addSeries(LC.CandlestickSeries, {
        upColor: D.UP, downColor: D.DN, borderUpColor: D.UP, borderDownColor: D.DN, wickUpColor: D.UP, wickDownColor: D.DN,
        priceLineVisible: false, lastValueVisible: true,
      });
      price.setData(bars.map((b) => ({ time: b.date, open: b.o, high: b.h, low: b.l, close: b.c })));
      const closes = bars.map((b) => b.c);
      MAS.forEach((m) => {
        const s = chart.addSeries(LC.LineSeries, { color: m.color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
          crosshairMarkerVisible: false, visible: !!state.ma[m.n] });
        const data = [];
        D.smaValues(closes, m.n).forEach((v, i) => { if (v != null) data.push({ time: bars[i].date, value: v }); });
        s.setData(data);
        maSeries[m.n] = s;
      });
      if (state.vol) {
        const vol = chart.addSeries(LC.HistogramSeries, { priceFormat: { type: "volume" }, priceLineVisible: false, lastValueVisible: false }, 1);
        vol.setData(bars.filter((b) => b.v != null).map((b) => ({ time: b.date, value: b.v,
          color: b.c >= b.o ? "rgba(34,197,94,.55)" : "rgba(239,68,68,.55)" })));
        const panes = chart.panes();
        if (panes[0]) panes[0].setStretchFactor(4);
        if (panes[1]) panes[1].setStretchFactor(1);
      }
      requestAnimationFrame(() => { if (my === token) fitView(); });
    }
    function show() {
      const my = ++token;
      if (!items.length) {
        dropChart();
        header("", null);
        msg.hidden = false;
        msg.textContent = "No stocks on this list today. Pick another list.";
        return;
      }
      index = ((index % items.length) + items.length) % items.length;
      const t = items[index];
      const url = new URL(location.href);
      url.searchParams.set("list", list.id);
      url.searchParams.set("t", t);
      history.replaceState(null, "", url);
      header(t, null);
      Promise.all([D.ensureTv(), D.loadCsv("ohlc/" + t + ".csv").catch(() => [])])
        .then((res) => draw(t, res[1], my))
        .catch(() => {
          if (my !== token) return;
          dropChart();
          msg.hidden = false;
          msg.textContent = "The chart could not load. Swipe for the next one.";
        });
      if (on("preload_next") && items.length > 1) {
        const nxt = items[(index + 1) % items.length];
        D.loadCsv("ohlc/" + nxt + ".csv").catch(() => {});
      }
    }
    function go(step) {
      if (!items.length) return;
      index += step;
      state.open = false;
      show();
    }

    // Full screen: the real Fullscreen API when there is one, else a fixed overlay (iPhone Safari).
    function fsElement() { return document.fullscreenElement || document.webkitFullscreenElement || null; }
    function setFull(v) {
      cv.classList.toggle("full", v);
      document.body.classList.toggle("cv-lock", v);
      requestAnimationFrame(() => fitView());
    }
    function enterFull() {
      const req = cv.requestFullscreen || cv.webkitRequestFullscreen;
      const can = document.fullscreenEnabled || document.webkitFullscreenEnabled;
      if (req && can) {
        try {
          const p = req.call(cv);
          if (p && p.catch) p.catch(() => { cv.classList.add("fake"); setFull(true); });
        } catch (e) { cv.classList.add("fake"); setFull(true); }
        setFull(true);
      } else {
        cv.classList.add("fake");
        setFull(true);
      }
      cv.focus({ preventScroll: true });
    }
    function exitFull() {
      if (fsElement()) {
        const ex = document.exitFullscreen || document.webkitExitFullscreen;
        if (ex) { try { ex.call(document); } catch (e) { /* ignore */ } }
      }
      cv.classList.remove("fake");
      setFull(false);
    }
    const onFsChange = () => { if (!fsElement() && !cv.classList.contains("fake")) setFull(false); };
    document.addEventListener("fullscreenchange", onFsChange);
    document.addEventListener("webkitfullscreenchange", onFsChange);
    const goBtn = document.getElementById("cvgo");
    if (goBtn) goBtn.addEventListener("click", enterFull);
    document.getElementById("cvx").addEventListener("click", exitFull);

    const sel = document.getElementById("cvlist");
    if (sel) sel.addEventListener("change", () => {
      list = built.lists.find((l) => l.id === sel.value) || built.lists[0];
      items = list.items.slice();
      index = 0;
      state.open = false;
      summary();
      show();
    });
    const tools = document.getElementById("cvtools");
    if (tools) tools.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      const ma = b.getAttribute("data-ma");
      const tool = b.getAttribute("data-tool");
      if (ma) {
        state.ma[ma] = !state.ma[ma];
        saveMa(state.ma);
        if (maSeries[ma]) maSeries[ma].applyOptions({ visible: state.ma[ma] });
      } else if (tool === "vol") {
        state.vol = !state.vol;
        store("desk-cv-vol", state.vol);
        show();
      } else if (tool === "why") {
        state.why = !state.why;
        store("desk-cv-why", state.why);
        syncTools();
        fitView();
      } else if (tool === "flip") {
        state.rightIsNext = !state.rightIsNext;
        store("desk-cv-right-next", state.rightIsNext);
      }
      syncTools();
    });
    if (why) {
      const toggle = (e) => {
        if (e) e.stopPropagation();
        state.open = !state.open;
        why.classList.toggle("open", state.open);
        why.setAttribute("aria-expanded", state.open ? "true" : "false");
        why.innerHTML = reasonHtml(items[index]);
        fitView();
      };
      why.addEventListener("click", toggle);
      why.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(e); } });
    }
    const prev = document.getElementById("cvprev");
    const next = document.getElementById("cvnext");
    if (prev) prev.addEventListener("click", () => go(-1));
    if (next) next.addEventListener("click", () => go(1));

    // Swipes. With chart_touch_pan off the chart ignores one-finger drags, so a sideways swipe always changes the chart.
    // With it on, only a quick, mostly sideways flick counts, so a slow drag still pans the chart.
    if (on("swipe")) {
      let start = null;
      body.addEventListener("touchstart", (e) => {
        if (e.touches.length !== 1 || e.target.closest(".cv-why, .cv-arrow")) { start = null; return; }
        const p = e.touches[0];
        start = { x: p.clientX, y: p.clientY, t: Date.now() };
      }, { passive: true });
      body.addEventListener("touchmove", (e) => { if (e.touches.length > 1) start = null; }, { passive: true });
      body.addEventListener("touchend", (e) => {
        if (!start || !e.changedTouches.length) return;
        const p = e.changedTouches[0];
        const dir = swipeDirection(p.clientX - start.x, p.clientY - start.y, Date.now() - start.t, {
          minPx: cfgNum("swipe_min_px", 50), maxMs: cfgNum("swipe_max_ms", 700), ratio: cfgNum("swipe_ratio", 1.5),
          touchPan: touchPan, rightIsNext: state.rightIsNext,
        });
        start = null;
        if (dir === "next") go(1);
        else if (dir === "prev") go(-1);
      }, { passive: true });
      body.addEventListener("touchcancel", () => { start = null; }, { passive: true });
    }
    if (on("keyboard")) {
      document.addEventListener("keydown", (e) => {
        const tag = (e.target && e.target.tagName || "").toLowerCase();
        if (tag === "input" || tag === "textarea" || tag === "select" || e.metaKey || e.ctrlKey || e.altKey) return;
        if (e.key === "ArrowRight") { e.preventDefault(); go(1); }
        else if (e.key === "ArrowLeft") { e.preventDefault(); go(-1); }
        else if (e.key === "Escape" && cv.classList.contains("full")) exitFull();
      });
    }
    if (typeof ResizeObserver !== "undefined") {
      let raf = 0;
      new ResizeObserver(() => {
        cancelAnimationFrame(raf);
        raf = requestAnimationFrame(() => fitView());
      }).observe(host);
    }
    syncTools();
    summary();
    show();
  }

  window.DESK_EXTRA_PAGES = Object.assign(window.DESK_EXTRA_PAGES || {}, {
    chartviewer: {
      files: ["scores.csv"].concat(LISTS.map((l) => l.file)),
      render: render,
    },
  });
  window.DeskViewer = api;
})();
