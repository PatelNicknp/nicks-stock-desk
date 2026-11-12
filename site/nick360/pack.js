/* Nick 360 desk file. The update job runs engine.js once over every stored chart and saves
   only what the workspace shows, so a phone does not have to read 2,500 five-year files.
   packDesk writes that file. unpackDesk turns it back into light stock rows. hydrate reads
   one symbol's full stored bars when its chart opens and recomputes it with the same engine,
   using the saved cross-desk ranks. No network here and no new data source. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.N360Pack = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const VERSION = 1;
  const MAS = [10, 20, 50, 150, 200];

  function at(i, v) {
    // One stored value at the last index. The array keeps the full length, so code that
    // reads s.bars.length or s.rank[s.last] still sees the same numbers.
    const a = [];
    if (i >= 0) a[i] = v;
    return a;
  }
  function stateCode(st) { return st === "pass" ? "p" : st === "fail" ? "f" : "m"; }
  function codeState(c) { return c === "p" ? "pass" : c === "f" ? "fail" : "missing"; }
  function labelsKey(items) { return items.map((x) => x.id + "\u0001" + x.label).join("\u0002"); }

  function packRanks(s, dates) {
    const idx = new Map();
    s.bars.forEach((b, i) => idx.set(b.d, i));
    let out = "";
    dates.forEach((d) => {
      const i = idx.get(d);
      const r = i == null ? null : s.rank[i];
      out += typeof r === "number" && r >= 1 && r <= 99 ? (r < 10 ? "0" + r : String(r)) : "..";
    });
    return out;
  }
  function unpackRanks(text, dates) {
    const out = new Map();
    for (let k = 0; k < dates.length; k++) {
      const bit = String(text || "").slice(k * 2, k * 2 + 2);
      if (bit && bit !== "..") out.set(dates[k], Number(bit));
    }
    return out;
  }

  function packDesk(desk, opt) {
    const o = opt || {};
    const meta = o.meta || {};
    const evIndex = new Map();
    const ev = [];
    const dIndex = new Map();
    const rdates = [];
    let gradeLabels = null;
    let templateLabels = null;
    function evId(e) {
      const key = e.side + "\u0001" + (e.net ? 1 : 0) + "\u0001" + e.text;
      if (!evIndex.has(key)) { evIndex.set(key, ev.length); ev.push([e.side, e.net ? 1 : 0, e.text]); }
      return evIndex.get(key);
    }
    function dateId(d) {
      if (!dIndex.has(d)) { dIndex.set(d, rdates.length); rdates.push(d); }
      return dIndex.get(d);
    }
    const tickerIndex = new Map();
    const stocks = desk.stocks.map((s, si) => {
      tickerIndex.set(s.ticker, si);
      const i = s.last;
      const row = {
        t: s.ticker, co: s.company || "", se: s.sector || "", n: s.bars.length,
        date: s.date, close: s.close, chg: s.chg, offHigh: s.offHigh, stale: s.stale ? 1 : 0, pivot20: s.pivot20,
      };
      const sc = s.score || {};
      const keep = {};
      ["entry_low", "entry_high", "stop", "trade_target"].forEach((k) => { if (sc[k] != null && sc[k] !== "") keep[k] = sc[k]; });
      if (Object.keys(keep).length) row.sc = keep;
      if (i >= 0) {
        const b = s.bars[i];
        row.bar = [b.d, b.o, b.h, b.l, b.c, b.v];
        row.rank = s.rank[i];
        row.pressure = s.pressure[i];
        row.risk = s.risk[i];
        row.relVol = s.relVol[i];
        row.dry = s.dry[i];
        row.sma = MAS.map((p) => s.sma[p][i]);
        const g = s.grade[i];
        if (g) {
          if (gradeLabels == null) gradeLabels = g.checks.map((c) => ({ id: c.id, label: c.label }));
          if (labelsKey(g.checks) !== labelsKey(gradeLabels)) throw new Error("grade checks changed shape for " + s.ticker);
          row.grade = [g.letter, g.pass, g.known, g.checks.map((c) => stateCode(c.state)).join("")];
        } else row.grade = null;
      }
      const tpl = s.template;
      if (tpl && tpl.items && tpl.items.length) {
        if (templateLabels == null) templateLabels = tpl.items.map((c) => ({ id: c.id, label: c.label }));
        if (labelsKey(tpl.items) !== labelsKey(templateLabels)) throw new Error("template items changed shape for " + s.ticker);
        row.tpl = tpl.items.map((c) => stateCode(c.state)).join("");
      } else row.tplRaw = tpl;
      row.stage = s.stage;
      row.vcp = s.vcp;
      // Screens are saved below. The page itself only reads the near-buy-point distance.
      row.patterns = s.patterns ? { near: s.patterns.near } : null;
      row.ranks = packRanks(s, desk.dates);
      row.recent = (s.recent || []).map((blk) => [dateId(blk.date)].concat(blk.events.map(evId)));
      return row;
    });
    const screens = desk.screens.map((sc) => ({
      id: sc.id,
      status: sc.status,
      m: sc.matches ? sc.matches.map((t) => tickerIndex.get(t)) : null,
      ev: sc.evaluated,
      sk: sc.skipped,
    }));
    return {
      v: VERSION,
      kind: "nick360-desk",
      price_as_of: meta.price_as_of || "",
      updated_pt: meta.updated_pt || "",
      built_utc: o.built || "",
      missing: o.missing || 0,
      stocks_n: stocks.length,
      dates: desk.dates,
      rdates: rdates,
      ev: ev,
      gradeLabels: gradeLabels || [],
      templateLabels: templateLabels || [],
      screens: screens,
      stocks: stocks,
    };
  }

  function liteStock(row, pack) {
    const n = row.n || 0;
    const i = n - 1;
    const s = {
      lite: true,
      ticker: row.t, company: row.co || "", sector: row.se || "", score: row.sc || {},
      last: i, date: row.date || "", close: row.close, chg: row.chg, offHigh: row.offHigh,
      stale: !!row.stale, pivot20: row.pivot20, stage: row.stage, vcp: row.vcp, patterns: row.patterns,
      rankText: row.ranks || "",
    };
    const bars = new Array(n);
    if (i >= 0 && row.bar) bars[i] = { d: row.bar[0], o: row.bar[1], h: row.bar[2], l: row.bar[3], c: row.bar[4], v: row.bar[5] };
    s.bars = bars;
    s.rank = at(i, row.rank);
    s.pressure = at(i, row.pressure);
    s.risk = at(i, row.risk);
    s.relVol = at(i, row.relVol);
    s.dry = at(i, row.dry);
    s.sma = {};
    MAS.forEach((p, k) => { s.sma[p] = at(i, row.sma ? row.sma[k] : null); });
    let grade = null;
    if (row.grade) {
      grade = {
        letter: row.grade[0],
        checks: pack.gradeLabels.map((c, k) => ({ id: c.id, label: c.label, state: codeState(row.grade[3][k]) })),
        pass: row.grade[1],
        known: row.grade[2],
      };
    }
    s.grade = at(i, grade);
    if (row.tpl != null) {
      const items = pack.templateLabels.map((c, k) => ({ id: c.id, label: c.label, state: codeState(row.tpl[k]) }));
      s.template = {
        items: items,
        pass: items.filter((x) => x.state === "pass").length,
        fail: items.filter((x) => x.state === "fail").length,
        missing: items.filter((x) => x.state === "missing").length,
        complete: items.every((x) => x.state === "pass"),
      };
    } else s.template = row.tplRaw;
    const blocks = row.recent || [];
    s.recent = blocks.map((blk, j) => {
      const events = blk.slice(1).map((id) => {
        const e = pack.ev[id];
        return { side: e[0], net: !!e[1], text: e[2] };
      });
      let net = 0;
      events.forEach((e) => { if (e.net) net += e.side === "pos" ? 1 : e.side === "neg" ? -1 : 0; });
      return { date: pack.rdates[blk[0]], index: i - (blocks.length - 1 - j), events: events, net: net };
    });
    return s;
  }

  function unpackDesk(pack, E) {
    if (!pack || pack.kind !== "nick360-desk" || pack.v !== VERSION) throw new Error("desk file version");
    const defs = E.SCREEN_DEFS;
    const ids = pack.screens.map((s) => s.id).join(",");
    if (ids !== defs.map((d) => d.id).join(",")) throw new Error("desk file screens differ from this page");
    const stocks = pack.stocks.map((row) => liteStock(row, pack));
    const screens = pack.screens.map((sc, k) => {
      const def = defs[k];
      return {
        id: def.id, ref: def.ref, ourName: def.ourName, status: sc.status, evidence: def.evidence, formula: def.formula, data: def.data,
        matches: sc.m ? sc.m.map((j) => stocks[j].ticker) : null, evaluated: sc.ev, skipped: sc.sk,
      };
    });
    return { stocks: stocks, dates: pack.dates, screens: screens, coverage: E.COVERAGE, packed: true, missing: pack.missing || 0 };
  }

  // Full bars for one symbol: same parse, same averages, the saved cross-desk rank, then the
  // same finalize step the full desk runs. The light row keeps its screen results.
  function hydrate(lite, rows, E, meta, dates) {
    const parsed = E.parseBars(rows);
    const s = E.analyzeBars(parsed.bars);
    const ranks = unpackRanks(lite.rankText, dates || []);
    s.bars.forEach((b, i) => { if (ranks.has(b.d)) s.rank[i] = ranks.get(b.d); });
    s.ticker = lite.ticker;
    s.company = lite.company;
    s.sector = lite.sector;
    s.score = lite.score;
    s.dropped = parsed.dropped;
    E.finalizeStock(s, meta || {});
    s.lite = false;
    return s;
  }

  return { VERSION: VERSION, packDesk: packDesk, unpackDesk: unpackDesk, hydrate: hydrate, liteStock: liteStock, packRanks: packRanks, unpackRanks: unpackRanks };
});
