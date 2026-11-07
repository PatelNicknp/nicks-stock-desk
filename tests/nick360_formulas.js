/* Numeric checks for Nick 360. No network. */
const assert = require("assert");
const E = require("../site/nick360/engine.js");

let failed = 0;
function check(name, fn) {
  try {
    fn();
    console.log("ok", name);
  } catch (err) {
    failed += 1;
    console.error("FAIL", name);
    console.error(err && err.stack || err);
  }
}

function barsFrom(closes, opt) {
  const o = opt || {};
  return closes.map((c, i) => ({
    d: o.dates ? o.dates[i] : day(i),
    o: c, h: c * (o.high || 1.01), l: c * (o.low || 0.99), c: c,
    v: o.volume ? o.volume[i] : 1000 + i,
  }));
}
function day(i) {
  const dt = new Date(Date.UTC(2020, 0, 1));
  dt.setUTCDate(dt.getUTCDate() + i);
  return dt.toISOString().slice(0, 10);
}
function ramp(n, start, step) {
  const out = [];
  for (let i = 0; i < n; i++) out.push(start + i * step);
  return out;
}

check("sma is flat when prices are flat and ignores a NaN window", () => {
  const values = [5, 5, 5, 5, 5, NaN, 5, 5, 5, 5, 5];
  const sma = E.smaSeries(values, 5);
  assert.strictEqual(sma[4], 5);
  assert.strictEqual(sma[5], null);
  assert.strictEqual(sma[9], null);
  assert.strictEqual(sma[10], 5);
});

check("parse drops nonpositive closes, repairs a flat bar, and keeps the last duplicate date", () => {
  const parsed = E.parseBars([
    { date: "2024-01-02", open: "", high: "", low: "", close: 10, volume: 5 },
    { date: "2024-01-02", open: 10, high: 10, low: 10, close: 11, volume: "" },
    { date: "2024-01-03", close: 0, volume: 5 },
    { date: "2024-01-04", close: "nope" },
  ]);
  assert.strictEqual(parsed.bars.length, 1);
  assert.strictEqual(parsed.bars[0].c, 11);
  assert.strictEqual(parsed.bars[0].v, null);
  assert.strictEqual(parsed.dropped, 2);
});

check("relative volume uses the prior 50 sessions and not the future", () => {
  const volume = [];
  for (let i = 0; i < 80; i++) volume.push(100);
  volume[60] = 250;
  volume[79] = 9999;
  const closes = ramp(80, 20, 0.1);
  const bars = barsFrom(closes, { volume: volume });
  const s = E.analyzeBars(bars);
  assert.strictEqual(s.relVol[60], 2.5);
  const before = s.relVol[60];
  bars[79].v = 1;
  bars[61].v = 1;
  const s2 = E.analyzeBars(bars);
  assert.strictEqual(s2.relVol[60], before);
  assert.strictEqual(s2.relVol[49], null);
  assert.ok(Math.abs(s2.relVol[50] - 1) < 1e-9);
});

check("dry-up baseline excludes the recent 10 sessions", () => {
  const volume = [];
  for (let i = 0; i < 70; i++) volume.push(i < 60 ? 200 : 50);
  const s = E.analyzeBars(barsFrom(ramp(70, 30, 0), { volume: volume }));
  assert.ok(Math.abs(s.dry[69] - 0.25) < 1e-9);
});

check("a flat close splits volume and a missing volume blanks pressure", () => {
  const closes = [];
  const volume = [];
  for (let i = 0; i < 25; i++) {
    closes.push(10);
    volume.push(100);
  }
  const s = E.analyzeBars(barsFrom(closes, { volume: volume }));
  assert.ok(Math.abs(s.pressure[24].buy - 0.5) < 1e-9);
  assert.strictEqual(s.pressure[24].color, "yellow");
  const bars = barsFrom(closes, { volume: volume });
  bars[24].v = null;
  const s2 = E.analyzeBars(bars);
  assert.strictEqual(s2.pressure[24], null);
});

check("weighted score does not look ahead and a short history stays blank", () => {
  const closes = ramp(300, 50, 0.2);
  const bars = barsFrom(closes);
  const s = E.analyzeBars(bars);
  const past = s.wscore[260];
  assert.ok(past != null);
  bars[299].c = 500;
  const s2 = E.analyzeBars(bars);
  assert.strictEqual(s2.wscore[260], past);
  const short = E.analyzeBars(barsFrom(ramp(100, 10, 0.1)));
  assert.ok(short.wscore.every((v) => v == null));
});

check("ranks use tie midpoints and leave a one-name universe unranked", () => {
  assert.deepStrictEqual(E.percentileRanks([5]), [null]);
  const tied = E.percentileRanks([1, 5, 5]);
  assert.strictEqual(tied[0], 1);
  assert.strictEqual(tied[1], tied[2]);
  assert.strictEqual(tied[1], Math.round(1 + (1.5 / 2) * 98));
  const same = E.percentileRanks([3, 3, 3, 3]);
  assert.ok(same.every((r) => r === 50));
});

check("entry risk bands and a missing 50-day stay blank", () => {
  const flat = [];
  for (let i = 0; i < 60; i++) flat.push(100);
  flat[59] = 104;
  const s = E.analyzeBars(barsFrom(flat));
  assert.strictEqual(s.risk[59].color, "green");
  flat[59] = 112;
  assert.strictEqual(E.analyzeBars(barsFrom(flat)).risk[59].color, "yellow");
  flat[59] = 120;
  assert.strictEqual(E.analyzeBars(barsFrom(flat)).risk[59].color, "red");
  flat[59] = 90;
  assert.strictEqual(E.analyzeBars(barsFrom(flat)).risk[59].color, "red");
  assert.strictEqual(E.analyzeBars(barsFrom(ramp(20, 10, 0.1))).risk[19], null);
});

check("missing inputs do not become screen matches", () => {
  const records = [];
  for (let n = 0; n < 5; n++) {
    records.push({ ticker: "S" + n, company: "Short", bars: barsFrom(ramp(30, 10 + n, 0.01)) });
  }
  const desk = E.buildDesk(records, { price_as_of: "2020-02-15" });
  desk.screens.forEach((screen) => {
    if (screen.status === "unavailable") {
      assert.strictEqual(screen.matches, null);
      return;
    }
    assert.strictEqual(screen.matches.length, 0, screen.id);
    assert.ok(screen.skipped >= 5, screen.id);
  });
  const ipo = desk.screens.find((s) => s.id === "ipo");
  const power = desk.screens.find((s) => s.id === "powerIpo");
  assert.strictEqual(ipo.status, "enabled");
  assert.strictEqual(ipo.matches.length, 0);
  assert.strictEqual(power.matches.length, 0);
});

check("a real trend can pass the template only when every input exists", () => {
  const strong = barsFrom(ramp(280, 20, 0.2));
  const flat = barsFrom(ramp(280, 40, 0));
  const weak = barsFrom(ramp(280, 90, -0.1).map((c) => Math.max(8, c)));
  const past = E.analyzeBars(strong).wscore[260];
  const desk = E.buildDesk([
    { ticker: "UP", bars: strong },
    { ticker: "FLAT", bars: flat },
    { ticker: "DN", bars: weak },
  ], { price_as_of: strong[strong.length - 1].d });
  const template = desk.screens.find((s) => s.id === "template");
  assert.deepStrictEqual(template.matches, ["UP"]);
  const up = desk.stocks.find((s) => s.ticker === "UP");
  assert.strictEqual(up.template.missing, 0);
  assert.ok(up.template.complete);
  strong[279].c = strong[279].c * 3;
  assert.strictEqual(E.analyzeBars(strong).wscore[260], past);
});

check("stage 2 needs a rising 200-day and does not invent a stage", () => {
  const up = E.analyzeBars(barsFrom(ramp(260, 30, 0.2)));
  E.rankDates([up], E.calendar([up], 10));
  const stage = E.stageAt(up, up.bars.length - 1);
  assert.strictEqual(stage.stage, 2);
  const down = E.analyzeBars(barsFrom(ramp(260, 80, -0.15).map((c) => Math.max(1, c))));
  assert.strictEqual(E.stageAt(down, down.bars.length - 1).stage, 4);
  const tiny = E.analyzeBars(barsFrom(ramp(40, 10, 0.1)));
  assert.strictEqual(E.stageAt(tiny, tiny.bars.length - 1).stage, null);
});

check("SBE, position size, and the book scenario", () => {
  const sbe = E.sbeFraction({ entry: 100, stop: 92, sale: 110, shares: 90, feePerShare: 0 });
  assert.ok(Math.abs(sbe.fraction - (8 / 18)) < 1e-12);
  const sbeFee = E.sbeFraction({ entry: 100, stop: 92, sale: 110, shares: 90, feePerShare: 1 });
  assert.ok(Math.abs(sbeFee.fraction - (8 / 17)) < 1e-12);
  assert.strictEqual(E.sbeFraction({ entry: 100, stop: 100, sale: 110, shares: 10 }).ok, false);
  assert.strictEqual(E.sbeFraction({ entry: 100, stop: 90, sale: 100, shares: 10 }).ok, false);
  const size = E.positionSize({ equity: 100000, entry: 50, stop: 47, riskPct: 1, feePerShare: 0 });
  assert.strictEqual(size.shares, 333);
  const sized = E.positionSize({ equity: 100000, entry: 50, stop: 47, riskPct: 1, payoff: 2 });
  assert.strictEqual(sized.shares, 333);
  assert.strictEqual(E.positionSize({ equity: 0, entry: 50, stop: 47, riskPct: 1 }).ok, false);
  assert.strictEqual(E.positionSize({ equity: 1000, entry: 50, stop: 50, riskPct: 1 }).ok, false);
  const rbaf = E.rbafScenario({ sizePct: 25, targetPct: 40, avgGainPct: 14, avgLossPct: 7, winPct: 46, feePct: 0 });
  assert.ok(Math.abs(rbaf.linearTrades - 60.15037593984962) < 1e-6);
  assert.ok(rbaf.compoundTrades < 55);
  const dead = E.rbafScenario({ sizePct: 25, targetPct: 40, avgGainPct: 5, avgLossPct: 10, winPct: 40, feePct: 0 });
  assert.strictEqual(dead.ok, false);
  assert.ok(/not positive/.test(dead.reason));
});

check("paper stats use only the fills and do not invent a year", () => {
  const fills = [
    { id: "a", ticker: "AAA", date: "2026-01-02", side: "buy", shares: 10, price: 100, fee: 1, stop: 90, size: "full" },
    { id: "b", ticker: "AAA", date: "2026-01-12", side: "sell", shares: 4, price: 110, fee: 1 },
    { id: "c", ticker: "AAA", date: "2026-02-02", side: "sell", shares: 6, price: 95, fee: 0 },
  ];
  const stats = E.paperStats(fills, { startingCash: 5000, year: 2026, prices: { AAA: 95 } });
  assert.strictEqual(stats.closedN, 2);
  assert.strictEqual(stats.errors.length, 0);
  assert.ok(stats.batting === 0.5);
  assert.strictEqual(stats.open.length, 0);
  assert.ok(stats.ytdN === 2);
  assert.ok(stats.exposure === 0);
  const empty = E.paperStats([], { year: 2026 });
  assert.strictEqual(empty.closedN, 0);
  assert.strictEqual(empty.batting, null);
  assert.strictEqual(empty.ytdPnl, null);
  assert.strictEqual(empty.equity, null);
  assert.strictEqual(empty.stopHint.available, false);
  const tooMany = E.paperStats([{ ticker: "AAA", date: "2026-03-01", side: "sell", shares: 5, price: 10, fee: 0 }], {});
  assert.strictEqual(tooMany.errors.length, 1);
  assert.strictEqual(tooMany.closedN, 0);
});

check("bin contribution is midpoint times net count over closed trades", () => {
  const closed = [
    { pnl: 1, pnlPct: 0.03 },
    { pnl: -1, pnlPct: -0.03 },
    { pnl: -1, pnlPct: -0.05 },
  ];
  const bins = E.binRows(closed);
  const row = bins.rows.find((r) => r.label === "2–4%");
  assert.strictEqual(row.gains, 1);
  assert.strictEqual(row.losses, 0);
  assert.ok(Math.abs(row.contribution - (3 * (1 - 0) / 3)) < 1e-12);
});

check("trade review does not grade a missing stop, and a missed row is labeled after the fact", () => {
  const notes = E.gradeTrade({ entry: 100, exit: 110, pivot: 100, entryDate: "2024-01-10", exitDate: "2024-01-20" }, []);
  assert.ok(notes.notes.some((n) => /No stop/.test(n.text)));
  const bars = barsFrom([100, 130, 100], { dates: ["2024-01-10", "2024-01-11", "2024-01-20"] });
  const hit = E.gradeTrade({ entry: 100, exit: 100, stop: 90, entryDate: "2024-01-10", exitDate: "2024-01-20" }, bars);
  assert.ok(hit.notes.some((n) => /2R/.test(n.text) && /not a live signal/.test(n.text)));
  const missed = E.missedResult({ date: "2024-01-10" }, bars);
  assert.ok(missed.available);
  assert.ok(/not a signal/.test(missed.reason));
  assert.strictEqual(E.missedResult({ date: "2024-01-20" }, bars).available, false);
});

check("regime stays unavailable without breadth and never emits a fake timing model", () => {
  const none = E.regimeFromMarket({});
  assert.strictEqual(none.status, "unavailable");
  const up = E.regimeFromMarket({ breadth_sma50: 62, breadth_sma200: 58, advancers: 300, decliners: 200, spy_day_pct: 0.4, qqq_day_pct: -0.2 });
  assert.strictEqual(up.label, "UPTREND");
  assert.ok(/not a SPY 25/.test(up.note));
  const down = E.regimeFromMarket({ breadth_sma50: 30, breadth_sma200: 55, advancers: 100, decliners: 400 });
  assert.strictEqual(down.label, "DEFENSIVE");
});

check("summary quotes only computed fields", () => {
  const desk = E.buildDesk([{ ticker: "ZZ", bars: barsFrom(ramp(40, 10, 0.1)) }], {});
  const text = E.summarize(desk.stocks[0]).text;
  assert.ok(/unavailable/.test(text));
  assert.ok(/not a language-model/.test(text));
  assert.ok(!/Minervini|RPR|TPR|Fab 5/.test(text));
});

check("coverage lists every reference screen and keeps sales unavailable", () => {
  const ids = E.COVERAGE.map((c) => c.id);
  ["bread", "gradeA", "gradeAB", "gradeUp", "tight", "rank89", "lead5", "riskGreen", "ipo", "powerIpo", "top5", "newTop5", "momentum", "trendQual", "gradeJump", "gradeDtoB", "gradeD200", "stage2", "template", "vcp", "dry", "breakout", "near", "powerPlay", "cheat3c", "indexes", "sales"].forEach((id) => {
    assert.ok(ids.indexOf(id) >= 0, id);
  });
  assert.strictEqual(E.COVERAGE.find((c) => c.id === "ipo").status, "enabled");
  assert.strictEqual(E.COVERAGE.find((c) => c.id === "sales").status, "unavailable");
  assert.strictEqual(E.COVERAGE.find((c) => c.id === "indexes").status, "partial");
});

check("offer-date coverage never treats the cache start as an IPO", () => {
  assert.strictEqual(E.listingCoverage("2021-11-04", "2018-05-01", "2021-11-04"), "truncated");
  assert.strictEqual(E.listingCoverage("2024-03-21", "2024-03-21", "2021-11-04"), "covers");
  assert.strictEqual(E.listingCoverage("2024-03-26", "2024-03-21", "2021-11-04"), "covers");
  assert.strictEqual(E.listingCoverage("2024-04-20", "2024-03-21", "2021-11-04"), "truncated");
  const bars = barsFrom(ramp(40, 20, 0.1));
  const desk = E.buildDesk([{ ticker: "NEW", bars: bars }], {}, {
    NEW: { offerDate: "2019-01-02", adr: 1 },
  });
  const ipo = desk.screens.find((s) => s.id === "ipo");
  assert.strictEqual(ipo.matches.length, 0);
  assert.strictEqual(desk.stocks[0].listing.coverage, "truncated");
});

check("power play boundaries and no lookahead", () => {
  const closes = [];
  const volume = [];
  for (let i = 0; i < 50; i++) { closes.push(10); volume.push(100); }
  for (let i = 0; i < 40; i++) { closes.push(10 + i * 0.3); volume.push(200); }
  for (let i = 0; i < 12; i++) { closes.push(21.5); volume.push(40); }
  const bars = barsFrom(closes, { volume: volume, high: 1.01, low: 0.995 });
  const hit = E.powerPlayAt(bars, bars.length - 1);
  assert.strictEqual(hit.state, "match", hit.reason);
  const early = E.powerPlayAt(bars, bars.length - 5);
  closes[closes.length - 1] = 40;
  const again = E.powerPlayAt(barsFrom(closes, { volume: volume, high: 1.01, low: 0.995 }), bars.length - 5);
  assert.strictEqual(again.state, early.state);
  const shy = closes.slice();
  for (let i = 50; i < 90; i++) shy[i] = 10 + (i - 50) * 0.15;
  const miss = E.powerPlayAt(barsFrom(shy, { volume: volume, high: 1.01, low: 0.995 }), shy.length - 1);
  assert.notStrictEqual(miss.state, "match");
});

check("blank index volume is not a higher-volume day", () => {
  const bars = barsFrom([10, 11, 12], { volume: [0, 0, 0] });
  bars.forEach((b) => { b.v = null; });
  const s = E.analyzeBars(bars);
  s.last = bars.length - 1;
  const trend = E.indexTrend(s);
  assert.strictEqual(trend.volume, null);
  assert.strictEqual(trend.higherVolume, null);
});

if (failed) {
  console.error(failed + " failed");
  process.exit(1);
}
console.log("nick360 formulas ok");
