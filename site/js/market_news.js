/**
 * Market News fragment for the Today page (overall market only).
 *
 * The desk's boot loader only Papa-parses CSV. This module fetches
 * data/market_brief.json itself (same raw.githubusercontent.com path
 * pattern as Desk.csvUrl).
 *
 * Wire-up: see INSTALL.md and web/pages_snippet.js.
 */
(function (global) {
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function briefUrl(name) {
    name = name || "market_brief.json";
    if (typeof location !== "undefined" && location.hostname && location.hostname.endsWith("github.io")) {
      return "https://raw.githubusercontent.com/PatelNicknp/nicks-stock-desk/main/data/" + name;
    }
    if (typeof location !== "undefined") {
      return new URL("../data/" + name, location.href).href;
    }
    return "../data/" + name;
  }

  function addDays(iso, n) {
    const parts = String(iso || "").split("-").map(Number);
    if (parts.length < 3 || parts.some(function (x) { return !x; })) return "";
    const d = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
    d.setUTCDate(d.getUTCDate() + n);
    return d.toISOString().slice(0, 10);
  }

  function todayPT() {
    try {
      return new Date().toLocaleDateString("en-CA", { timeZone: "America/Los_Angeles" });
    } catch (e) {
      return new Date().toISOString().slice(0, 10);
    }
  }

  // Friday close note stays up through Sunday PT. Monday's brief replaces the file;
  // this also hides a leftover Friday file once the weekend is over.
  function showWeekly(brief) {
    const recap = brief && brief.weekly_recap;
    if (!recap || !recap.text) return false;
    const session = brief.session;
    if (!session) return true;
    const today = todayPT();
    const sunday = addDays(session, 2);
    return !!sunday && today >= session && today <= sunday;
  }

  function extraLines(brief) {
    const bits = [];
    if (brief.watch_next) {
      bits.push('<div class="mn-extra"><b>What to watch next.</b> ' + esc(brief.watch_next) + "</div>");
    }
    if (showWeekly(brief)) {
      bits.push('<div class="mn-extra"><b>This week.</b> ' + esc(brief.weekly_recap.text) + "</div>");
    }
    return bits.join("");
  }

  function render(host, brief, opts) {
    opts = opts || {};
    const featureOn = opts.featureOn || function () { return true; };
    if (!featureOn("feature.market_news")) {
      host.innerHTML = "";
      host.hidden = true;
      return;
    }
    host.hidden = false;
    if (!brief || !brief.why_moved) {
      host.innerHTML =
        '<div class="panel pad mn-wrap"><div class="ptitle">Market news</div>' +
        '<div class="psub">No brief yet — it appears after the next open/close update.</div></div>';
      return;
    }

    const mood = (brief.mood && brief.mood.label) || "Mixed";
    const regime = brief.regime || {};
    const breadth = brief.breadth_check || {};
    const vs = brief.vs_yesterday || {};
    const cal = brief.calendar || {};
    const causes = brief.causes || [];
    const headlines = brief.headlines || [];
    const prior = brief.prior_brief || null;
    const slotLabel = brief.slot === "morning_open" ? "Morning open brief" :
      brief.slot === "evening_close" ? "Evening close brief" : "Market brief";

    const causeHtml = causes.map(function (c) {
      const hs = (c.headlines || []).slice(0, 3).map(function (h) {
        const link = h.url
          ? '<a href="' + esc(h.url) + '" target="_blank" rel="noopener">' + esc(h.title) + "</a>"
          : esc(h.title);
        return "<li>" + link +
          '<div class="mn-meta">' + esc(h.source || "") +
          (h.trusted ? " · trusted" : "") + "</div></li>";
      }).join("");
      return '<div class="mn-cause"><span class="lab">' + esc(c.label || c.cause) + "</span>" +
        (hs ? '<ul class="mn-list">' + hs + "</ul>" : '<div class="mn-note muted">No headlines under this label.</div>') +
        "</div>";
    }).join("");

    const headlineFallback = headlines.map(function (h) {
      const link = h.url
        ? '<a href="' + esc(h.url) + '" target="_blank" rel="noopener">' + esc(h.title) + "</a>"
        : esc(h.title);
      return "<li>" + link +
        '<div class="mn-meta">' + esc(h.source || "") +
        ((h.causes || []).length ? " · " + esc((h.causes || []).join(", ")) : "") +
        "</div></li>";
    }).join("");

    const compare = prior
      ? '<div class="mn-compare">' +
        '<div class="box"><div class="k">This brief</div><div class="v">' + esc(brief.why_moved) + "</div></div>" +
        '<div class="box"><div class="k">Prior brief (' + esc(prior.session || "") + ')</div><div class="v">' +
        esc(prior.why_moved || "—") + "</div></div></div>"
      : "";

    host.innerHTML =
      '<div class="panel pad mn-wrap" id="market-news">' +
      '<div class="rowhead stack"><div>' +
      '<div class="ptitle">Market news</div>' +
      '<div class="psub">' + esc(slotLabel) + " · overall market only · research, not a trade</div>" +
      "</div></div>" +
      '<div class="mn-why">' + esc(brief.why_moved) + "</div>" +
      '<div class="mn-row">' +
      '<span class="mn-mood ' + esc(mood) + '">Mood: ' + esc(mood) + "</span>" +
      '<span class="mn-pill">Regime <b>' + esc(regime.label || "—") + "</b></span>" +
      (vs.text ? '<span class="mn-pill">' + esc(vs.text) + "</span>" : "") +
      "</div>" +
      extraLines(brief) +
      '<div class="mn-grid">' +
      "<div>" +
      '<div class="ptitle" style="font-size:13px;margin-bottom:8px">Why — ranked causes</div>' +
      (causeHtml || ('<ul class="mn-list">' + headlineFallback + "</ul>")) +
      "</div>" +
      "<div>" +
      '<div class="ptitle" style="font-size:13px;margin-bottom:8px">Desk checks</div>' +
      '<div class="mn-note">' + esc(breadth.text || "") + "</div>" +
      '<div class="mn-note">' + esc(regime.text || "") + "</div>" +
      '<div class="mn-note">' + esc(cal.text || "") + "</div>" +
      compare +
      "</div></div>" +
      '<div class="mn-foot">' + esc(brief.disclaimer || "") + "</div>" +
      "</div>";
  }

  async function loadAndRender(host, opts) {
    opts = opts || {};
    const featureOn = opts.featureOn || function () { return true; };
    if (!featureOn("feature.market_news")) {
      host.innerHTML = "";
      host.hidden = true;
      return null;
    }
    const url = opts.url || briefUrl("market_brief.json");
    try {
      const res = await fetch(url, { cache: "no-store" });
      if (!res.ok) throw new Error("HTTP " + res.status);
      const brief = await res.json();
      render(host, brief, opts);
      return brief;
    } catch (err) {
      host.hidden = false;
      host.innerHTML =
        '<div class="panel pad mn-wrap"><div class="ptitle">Market news</div>' +
        '<div class="psub">Could not load the brief (' + esc(err.message || err) + ").</div></div>";
      return null;
    }
  }

  /**
   * Call from renderToday AFTER ctx.page.innerHTML is set.
   * Inserts the Market News panel at the top of #page.
   */
  async function mountToday(pageEl, opts) {
    if (!pageEl) return;
    opts = opts || {};
    const featureOn = opts.featureOn || (global.Desk && global.Desk.featureOn) || function () { return true; };
    if (!featureOn("feature.market_news")) return;
    let host = pageEl.querySelector("[data-market-news-host]");
    if (!host) {
      host = document.createElement("div");
      host.setAttribute("data-market-news-host", "1");
      pageEl.insertBefore(host, pageEl.firstChild);
    }
    await loadAndRender(host, { featureOn: featureOn, url: opts.url });
  }

  global.MarketNews = {
    render: render,
    loadAndRender: loadAndRender,
    mountToday: mountToday,
    briefUrl: briefUrl,
  };
})(typeof window !== "undefined" ? window : globalThis);
