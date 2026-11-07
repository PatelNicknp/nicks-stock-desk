/**
 * Market News on Today. Layout matches the design sample.
 * Data comes from data/market_brief.json (desk numbers and free headlines).
 * Sub-switches default on when the settings row is missing.
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

  function flagOn(featureOn, key) {
    try {
      if (!featureOn || typeof featureOn !== "function") return true;
      return featureOn(key) !== false;
    } catch (e) {
      return true;
    }
  }

  function addDays(iso, n) {
    var parts = String(iso || "").split("-").map(Number);
    if (parts.length < 3 || parts.some(function (x) { return !x; })) return "";
    var d = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
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

  function showWeekly(brief) {
    var recap = brief && brief.weekly_recap;
    if (!recap || !recap.text) return false;
    var session = brief.session;
    if (!session) return true;
    var today = todayPT();
    var sunday = addDays(session, 2);
    return !!sunday && today >= session && today <= sunday;
  }

  function marketOpen(now) {
    try {
      var fmt = new Intl.DateTimeFormat("en-US", {
        timeZone: "America/New_York",
        weekday: "short",
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
      });
      var parts = fmt.formatToParts(now || new Date());
      var get = function (t) {
        var hit = parts.filter(function (p) { return p.type === t; })[0];
        return hit ? hit.value : "";
      };
      var wd = get("weekday");
      if (wd === "Sat" || wd === "Sun") return false;
      var mins = Number(get("hour")) * 60 + Number(get("minute"));
      return mins >= (9 * 60 + 30) && mins < (16 * 60);
    } catch (e) {
      return false;
    }
  }

  function refLink(n, ok) {
    if (!ok || !n) return "";
    return '<a class="mn-ref" href="#mn-src-' + n + '" aria-label="Source ' + n + '">' + n + "</a>";
  }

  function indexHtml(row, href) {
    var missing = row.arrow === "missing" || row.pct == null;
    var cls = missing ? "mn-missing" : (row.arrow === "up" ? "mn-up" : row.arrow === "down" ? "mn-down" : "mn-flatv");
    var value = missing
      ? '<span class="mn-value">n/a</span>'
      : '<span class="mn-value">' +
        (row.arrow === "down" ? '<span class="mn-arrow" aria-label="down">▼</span>' : "") +
        (row.arrow === "up" ? '<span class="mn-arrow" aria-label="up">▲</span>' : "") +
        esc(row.pct_text || "") + "</span>";
    var inner = '<span class="mn-indexname">' + esc(row.name) + "</span>" + value;
    if (href && !missing) {
      return '<a class="mn-index ' + cls + '" href="' + esc(href) + '">' + inner + "</a>";
    }
    var note = missing && row.note ? ' title="' + esc(row.note) + '"' : "";
    return '<div class="mn-index ' + cls + '"' + note + ">" + inner + "</div>";
  }

  function chipHtml(c, href) {
    if (c.kind === "summary") {
      return '<span class="mn-chip mn-neutral">' + esc(c.name) + "</span>";
    }
    var cls = c.arrow === "up" ? "mn-up" : "mn-down";
    var sign = c.arrow === "down" ? "−" : "";
    var inner = "<span>" + esc(c.name) + "</span><b>" + sign + esc(c.pct_text || "") + "</b>";
    var width = ' style="--width:' + (c.bar || 0) + '%"';
    if (href) {
      return '<a class="mn-chip ' + cls + '" href="' + esc(href) + '"' + width + ">" + inner + "</a>";
    }
    return '<span class="mn-chip ' + cls + '"' + width + ">" + inner + "</span>";
  }

  function storyLink(h) {
    var n = h.n < 10 ? "0" + h.n : String(h.n);
    var title = esc(h.title || "");
    var body = '<div><div class="mn-meta"><span class="mn-num">' + esc(n) + "</span><b>" +
      esc(h.source || "Source") + (h.via ? " via " + esc(h.via) : "") + "</b>" +
      (h.region ? "<span>" + esc(h.region) + "</span>" : "") +
      (h.date_label ? "<span>" + esc(h.date_label) + "</span>" : "") +
      (h.age_label ? "<span>" + esc(h.age_label) + "</span>" : "") +
      '</div><div class="mn-storytitle">' + title + "</div>" +
      (h.why ? '<div class="mn-why">' + esc(h.why) + "</div>" : "") + "</div>" +
      '<span class="mn-out" aria-hidden="true">↗</span>';
    if (h.url) {
      return '<a class="mn-story" id="mn-src-' + h.n + '" href="' + esc(h.url) +
        '" target="_blank" rel="noopener noreferrer">' + body + "</a>";
    }
    return '<div class="mn-story" id="mn-src-' + h.n + '">' + body + "</div>";
  }

  function signedPct(pct) {
    if (pct == null || pct === "") return "";
    var n = Number(pct);
    if (!isFinite(n)) return "";
    var body = Math.abs(n).toFixed(2) + "%";
    if (n > 0) return "+" + body;
    if (n < 0) return "−" + body;
    return body;
  }

  function statusLabel(status) {
    return {
      closed: "Closed",
      prior_local_close: "Prior local close",
      intraday: "Intraday",
      delayed: "Delayed",
      stale: "Stale",
      unknown: "Unknown",
    }[status] || "Unknown";
  }

  function worldStrip(brief) {
    var world = brief.world_moves;
    if (!world || !(world.rows || []).length) return "";
    var strip = world.strip || [];
    var chips = strip.map(function (row) {
      var cls = row.pct > 0 ? "mn-up" : row.pct < 0 ? "mn-down" : "mn-flatv";
      var kind = row.kind === "etf_proxy" ? "ETF" : "Index";
      return '<div class="mn-wchip ' + cls + '"><span>' + esc(row.name) +
        " · " + esc(kind) + "</span><b>" + esc(signedPct(row.pct)) + "</b><small>" +
        esc(row.session_date || "") + " · " + esc(statusLabel(row.status)) + "</small></div>";
    }).join("");
    var missing = (world.missing || []).join(", ");
    return '<section class="mn-world" aria-label="Major markets">' +
      '<p class="mn-label">Major markets</p>' +
      '<p class="mn-worldsum">' + esc(world.summary || "") + "</p>" +
      (chips ? '<div class="mn-worldrow">' + chips + "</div>" : "") +
      (missing ? '<p class="mn-worldmiss">No verified index close for ' + esc(missing) +
        ". The chips above stay the desk's stored ETF readings.</p>" : "") +
      "</section>";
  }

  function worldTable(brief) {
    var world = brief.world_moves;
    if (!world || !(world.rows || []).length) return "";
    var body = world.rows.map(function (row) {
      var link = row.source_url
        ? '<a href="' + esc(row.source_url) + '" target="_blank" rel="noopener noreferrer">' + esc(row.source || "Source") + "</a>"
        : esc(row.source || "");
      var cause = row.cause
        ? esc(row.cause) + (row.cause_url
          ? ' <a href="' + esc(row.cause_url) + '" target="_blank" rel="noopener noreferrer">Link</a>'
          : "")
        : "No sourced cause." + (row.note ? " " + esc(row.note) : "");
      var kind = row.kind === "etf_proxy" ? "ETF proxy" : "Index";
      return "<tr><td>" + esc(row.name) + "</td><td>" + esc(kind) + "</td><td>" +
        esc(row.session_date || "—") + "</td><td>" + esc(statusLabel(row.status)) + "</td><td>" +
        esc(row.pct == null ? "Unknown" : signedPct(row.pct)) + "</td><td>" + link + "</td><td>" +
        cause + "</td></tr>";
    }).join("");
    return '<p><strong>Major markets.</strong> ' + esc(world.summary || "") + "</p>" +
      '<div class="mn-wscroll"><table class="mn-wtable"><thead><tr>' +
      "<th>Benchmark</th><th>Kind</th><th>Session</th><th>Status</th><th>Change</th><th>Source</th><th>Cause</th>" +
      "</tr></thead><tbody>" + body + "</tbody></table></div>";
  }

  function detailParagraphs(brief, opts) {
    var story = brief.story || {};
    var bits = [];
    if (story.note) bits.push("<p>" + esc(story.note) + "</p>");
    var causes = brief.causes || [];
    if (causes.length) {
      var tags = causes.map(function (c) {
        var label = c.label || c.cause || "";
        var backed = (c.headlines || []).length ? "" : " (no headline, not used as the cause)";
        return esc(label) + backed;
      }).join("; ");
      bits.push("<p><strong>Cause tags.</strong> " + tags + ".</p>");
    }
    var vs = brief.vs_yesterday || {};
    if (vs.text) bits.push("<p><strong>Versus yesterday.</strong> " + esc(vs.text) + "</p>");
    var breadth = brief.breadth_check || {};
    if (breadth.text) bits.push("<p><strong>Breadth.</strong> " + esc(breadth.text) + "</p>");
    var regime = brief.regime || {};
    if (regime.text) bits.push("<p><strong>Regime.</strong> " + esc(regime.text) + "</p>");
    var cal = brief.calendar || {};
    if (cal.text) bits.push("<p><strong>Calendar.</strong> " + esc(cal.text) + "</p>");
    if (brief.watch_next) bits.push("<p><strong>What to watch next.</strong> " + esc(brief.watch_next) + "</p>");
    if (showWeekly(brief)) bits.push("<p><strong>This week.</strong> " + esc(brief.weekly_recap.text) + "</p>");
    if (opts.tips && brief.tips && (brief.tips.lines || []).length) {
      var lines = brief.tips.lines.map(function (ln) { return esc(ln); }).join(" ");
      bits.push("<p><strong>" + esc(brief.tips.title || "What it means for me") + ".</strong> " + lines + "</p>");
      if (brief.tips.disclaimer) bits.push("<p>" + esc(brief.tips.disclaimer) + "</p>");
    }
    var learning = (brief.learning || {}).stats || {};
    if (learning.n_labeled != null) {
      bits.push("<p><strong>Learning.</strong> " + esc(String(learning.n_labeled)) +
        " saved days are kept for later study. This does not place a trade.</p>");
    }
    var dow = (story.indexes || []).filter(function (r) { return r.name === "Dow" && r.arrow === "missing"; })[0];
    if (dow && dow.note) bits.push("<p><strong>Dow.</strong> " + esc(dow.note) + "</p>");
    bits.push(worldTable(brief));
    if (brief.disclaimer) bits.push("<p>" + esc(brief.disclaimer) + "</p>");
    return bits.join("");
  }

  function render(host, brief, opts) {
    opts = opts || {};
    var featureOn = opts.featureOn || function () { return true; };
    if (!flagOn(featureOn, "feature.market_news")) {
      host.innerHTML = "";
      return;
    }
    var story = brief.story;
    if (!story) {
      host.innerHTML = '<article class="mn-card" id="market-news"><div class="mn-inner">' +
        '<p class="mn-eyebrow">Market news</p><h2 class="mn-title">Why the market moved today</h2>' +
        '<p class="mn-date">' + esc(brief.why_moved || "No brief yet.") + "</p></div></article>";
      return;
    }
    var whyOn = flagOn(featureOn, "feature.market_news_why_detail");
    var more = flagOn(featureOn, "feature.market_news_more_headlines");
    var card = flagOn(featureOn, "feature.market_news_card_layout");
    var tipsOn = flagOn(featureOn, "feature.market_news_tips");
    var indexesOn = flagOn(featureOn, "feature.market_news_indexes");
    var sectorsOn = flagOn(featureOn, "feature.market_news_sectors");
    var detailsOn = flagOn(featureOn, "feature.market_news_details");
    var news = (story.news || []).slice(0, more ? 5 : 2);
    var shown = {};
    news.forEach(function (h) { shown[h.n] = true; });
    var anchor = story.support_ref && shown[story.support_ref] ? "#mn-src-" + story.support_ref : "";

    var open = marketOpen();
    var mkt = '<span class="mn-mkt ' + (open ? "mn-open" : "mn-closed") + '">' +
      (open ? "Market open" : "Market closed") + "</span>";

    var indexes = "";
    if (indexesOn && (story.indexes || []).length) {
      indexes = '<div class="mn-indices mn-cols-' + story.indexes.length + '" aria-label="Index moves">' +
        story.indexes.map(function (row) { return indexHtml(row, anchor); }).join("") +
        "</div>";
    }

    var tone = story.direction === "up" ? "mn-up" : story.direction === "down" ? "mn-down" : "mn-flatv";
    var reason = "";
    if (whyOn) {
      var supportRef = story.support_ref && shown[story.support_ref] ? story.support_ref : null;
      var bullets = (story.bullets || []).map(function (b) {
        var ref = b.ref && shown[b.ref] ? b.ref : null;
        return "<li><strong>" + esc(b.lead || "") + "</strong> " + esc(b.rest || "") + refLink(ref, true) + "</li>";
      }).join("");
      reason = '<div class="mn-reason ' + tone + '"><h3>' + esc(story.lead || "") + "</h3><p>" +
        esc(story.support || "") + refLink(supportRef, true) + "</p></div>" +
        (bullets ? '<ul class="mn-support">' + bullets + "</ul>" : "");
    } else if (brief.why_moved_short) {
      reason = '<div class="mn-reason ' + tone + '"><p>' + esc(brief.why_moved_short) + "</p></div>";
    }

    var sectors = "";
    if (sectorsOn && (story.chips || []).length) {
      sectors = '<section class="mn-sectors" aria-label="' + esc(story.sector_label || "Sectors") + '">' +
        '<p class="mn-label">' + esc(story.sector_label || "") + "</p><div class=\"mn-chips\">" +
        story.chips.map(function (c) { return chipHtml(c, c.kind === "summary" ? "" : anchor); }).join("") +
        "</div></section>";
    }

    var sources = "";
    if (news.length) {
      sources = '<section class="mn-sources" aria-label="Source headlines"><p class="mn-label">The news behind the move</p>' +
        news.map(storyLink).join("") + "</section>";
    }

    var details = "";
    if (detailsOn) {
      details = '<details class="mn-details"><summary><span>More details<small>Numbers &amp; context</small></span>' +
        '<i class="mn-chevron" aria-hidden="true"></i></summary><div class="mn-detailbody">' +
        detailParagraphs(brief, { tips: tipsOn }) +
        (more && (story.news || []).length > news.length
          ? "<p><strong>Other headlines.</strong> " +
            (story.news || []).slice(news.length).map(function (h) {
              return esc(h.source || "Source") + ": " + esc(h.title || "");
            }).join(" ") + "</p>"
          : "") +
        "</div></details>";
    }

    var date = [story.date_label, story.summary].filter(Boolean).join(" · ");
    host.innerHTML =
      '<article class="mn-card' + (card ? "" : " mn-flat") + '" id="market-news" aria-labelledby="mn-title">' +
      '<div class="mn-inner">' +
      '<div class="mn-eyebrowrow"><p class="mn-eyebrow">Market news</p>' + mkt + "</div>" +
      '<h2 class="mn-title" id="mn-title">Why the market moved today</h2>' +
      (date ? '<p class="mn-date">' + esc(date) + "</p>" : "") +
      indexes + reason + worldStrip(brief) + sectors + sources +
      "</div>" + details + "</article>" +
      '<p class="mn-note">Sources linked above. Research only. This desk never places a trade.</p>';
  }

  async function loadAndRender(host, opts) {
    opts = opts || {};
    var featureOn = opts.featureOn || function () { return true; };
    if (!flagOn(featureOn, "feature.market_news")) {
      host.innerHTML = "";
      host.hidden = true;
      return null;
    }
    var url = opts.url || briefUrl("market_brief.json");
    try {
      var res = await fetch(url, { cache: "no-store" });
      if (!res.ok) throw new Error("HTTP " + res.status);
      var brief = await res.json();
      host.hidden = false;
      render(host, brief, opts);
      return brief;
    } catch (err) {
      host.hidden = false;
      host.innerHTML =
        '<article class="mn-card"><div class="mn-inner"><p class="mn-eyebrow">Market news</p>' +
        '<h2 class="mn-title">Why the market moved today</h2>' +
        '<p class="mn-date">Could not load the brief (' + esc(err.message || err) + ").</p></div></article>";
      return null;
    }
  }

  async function mountToday(pageEl, opts) {
    if (!pageEl) return;
    opts = opts || {};
    var featureOn = opts.featureOn || (global.Desk && global.Desk.featureOn) || function () { return true; };
    if (!flagOn(featureOn, "feature.market_news")) return;
    var host = pageEl.querySelector("[data-market-news-host]");
    if (!host) {
      host = document.createElement("div");
      host.className = "mn-host";
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
    marketOpen: marketOpen,
  };
})(typeof window !== "undefined" ? window : globalThis);
