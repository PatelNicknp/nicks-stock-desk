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

function putBar(bars, i, price, vol) {
  bars[i].o = price;
  bars[i].h = price;
  bars[i].l = price;
  bars[i].c = price;
  if (vol != null) bars[i].v = vol;
}

function span(bars, a, b, p0, p1, vol) {
  const steps = b - a;
  for (let i = a; i <= b; i++) {
    const t = steps === 0 ? 0 : (i - a) / steps;
    putBar(bars, i, p0 + (p1 - p0) * t, vol);
  }
}

function risingTape(n) {
  const bars = [];
  for (let i = 0; i < n; i++) {
    const c = 40 + i * 0.22;
    bars.push({ d: day(i), o: c, h: c, l: c, c: c, v: 1000 });
  }
  return bars;
}

function decliningTape(n) {
  const bars = [];
  for (let i = 0; i < n; i++) {
    const c = 250 - i * 0.15;
    bars.push({ d: day(i), o: c, h: c, l: c, c: c, v: 1000 });
  }
  return bars;
}

function paintVcp(bars, depths, opt) {
  const o = opt || {};
  const end = bars.length - 1;
  const gap = 8;
  const lastHigh = end - 17;
  const firstHigh = lastHigh - (depths.length - 1) * gap;
  const P = bars[firstHigh].c;
  const vols = o.vols || depths.map(function () { return 1000; });
  const closePrice = o.closePrice == null ? P : o.closePrice;
  for (let c = 0; c < depths.length; c++) {
    const H = firstHigh + c * gap;
    const L = H + 4;
    const low = P * (1 - depths[c]);
    span(bars, H, L, P, low, vols[c]);
    const rightEnd = c < depths.length - 1 ? H + gap - 1 : L + 3;
    span(bars, L + 1, rightEnd, low * 1.01, c < depths.length - 1 ? P * 0.99 : closePrice, 1000);
  }
  const tailVol = o.tailVol == null ? 700 : o.tailVol;
  for (let i = end - 9; i <= end; i++) putBar(bars, i, closePrice, tailVol);
  return { P: P, firstHigh: firstHigh, lastHigh: lastHigh };
}

function vcpDesk(leadBars, peerBars) {
  const records = [{ ticker: "LEAD", bars: leadBars }];
  if (peerBars) records.push({ ticker: "LAG", bars: peerBars });
  return E.buildDesk(records, {});
}

function leadOf(desk) {
  return desk.stocks.find((s) => s.ticker === "LEAD");
}

check("a textbook tight base passes every VCP gate and keeps the contraction count", () => {
  const rules = E.VCP_RULES;
  assert.strictEqual(rules.depthRatio, 0.8);
  assert.strictEqual(rules.maxFirstDepth, 0.35);
  assert.strictEqual(rules.maxFinalDepth, 0.1);
  assert.strictEqual(rules.lookback, 325);
  assert.strictEqual(rules.minBase, 15);
  assert.strictEqual(rules.dryMax, 0.75);
  assert.strictEqual(rules.rightBars, 10);
  assert.strictEqual(rules.maxRightRange, 0.08);
  assert.strictEqual(rules.maxBelowPivot, 0.08);
  assert.strictEqual(rules.maxAbovePivot, 0.05);
  const bars = risingTape(420);
  const painted = paintVcp(bars, [0.16, 0.08], { vols: [1500, 500], tailVol: 700 });
  const desk = vcpDesk(bars, decliningTape(420));
  const lead = leadOf(desk);
  assert.strictEqual(lead.template.complete, true, JSON.stringify(lead.template.items.filter((x) => x.state !== "pass")));
  assert.strictEqual(lead.vcp.candidate, true, lead.vcp.reason);
  assert.strictEqual(lead.vcp.count, 2);
  assert.ok(Math.abs(lead.vcp.depths[0] - 0.16) < 1e-9);
  assert.ok(Math.abs(lead.vcp.depths[1] - 0.08) < 1e-9);
  assert.ok(Math.abs(lead.vcp.pivot - painted.P) < 1e-6);
  assert.strictEqual(lead.vcp.brokenOut, false);
  assert.ok(lead.vcp.baseSessions >= 15);
  assert.ok(Math.abs(lead.vcp.dry - 0.7) < 1e-9);
  assert.ok(/2 contractions/.test(lead.vcp.reason));
  assert.ok(/still under the pivot/.test(lead.vcp.reason));
  const vcp = desk.screens.find((s) => s.id === "vcp");
  assert.deepStrictEqual(vcp.matches, ["LEAD"]);
  const dry = desk.screens.find((s) => s.id === "dry");
  assert.ok(dry.matches.indexOf("LEAD") < 0, "70% dry-up is inside the VCP gate and outside the 60% volume dry-up screen");
});

check("four and five contractions stay fully counted", () => {
  const four = risingTape(420);
  paintVcp(four, [0.24, 0.16, 0.08, 0.04], { vols: [1000, 1000, 1800, 600], tailVol: 400 });
  const fourLead = leadOf(vcpDesk(four, decliningTape(420)));
  assert.strictEqual(fourLead.vcp.candidate, true, fourLead.vcp.reason);
  assert.strictEqual(fourLead.vcp.count, 4);
  assert.ok(/^4 contractions/.test(fourLead.vcp.reason));
  const five = risingTape(460);
  paintVcp(five, [0.3, 0.22, 0.15, 0.1, 0.05], { vols: [1000, 1000, 1000, 1800, 600], tailVol: 400 });
  const fiveLead = leadOf(vcpDesk(five, decliningTape(460)));
  assert.strictEqual(fiveLead.vcp.candidate, true, fiveLead.vcp.reason);
  assert.strictEqual(fiveLead.vcp.count, 5);
  assert.ok(/^5 contractions/.test(fiveLead.vcp.reason));
});

check("trend template 8 of 8 is still required", () => {
  const bars = risingTape(420);
  paintVcp(bars, [0.16, 0.08], { vols: [1500, 500], tailVol: 700 });
  const alone = leadOf(vcpDesk(bars, null));
  assert.strictEqual(alone.vcp.candidate, false);
  assert.strictEqual(alone.vcp.skipped, true);
  assert.ok(/missing an input/.test(alone.vcp.reason));
  const fast = risingTape(420);
  fast.forEach((b, i) => { const c = 20 + i * 1.4; b.o = b.h = b.l = b.c = c; });
  const ranked = leadOf(vcpDesk(bars, fast));
  assert.strictEqual(ranked.template.complete, false);
  assert.strictEqual(ranked.vcp.candidate, false);
  assert.ok(/not 8 of 8/.test(ranked.vcp.reason));
});

check("each contraction must be at most 80% as deep as the one before", () => {
  const weak = risingTape(420);
  paintVcp(weak, [0.12, 0.1], { vols: [1500, 500], tailVol: 700 });
  const weakLead = leadOf(vcpDesk(weak, decliningTape(420)));
  assert.strictEqual(weakLead.vcp.candidate, false, weakLead.vcp.reason);
  assert.ok(weakLead.vcp.count < 2);
  assert.ok(/at most 80%/.test(weakLead.vcp.reason));
  const edge = risingTape(420);
  paintVcp(edge, [0.1, 0.08], { vols: [1500, 500], tailVol: 700 });
  const edgeLead = leadOf(vcpDesk(edge, decliningTape(420)));
  assert.strictEqual(edgeLead.vcp.candidate, true, edgeLead.vcp.reason);
  assert.strictEqual(edgeLead.vcp.count, 2);
  const over = risingTape(420);
  paintVcp(over, [0.1, 0.081], { vols: [1500, 500], tailVol: 700 });
  const overLead = leadOf(vcpDesk(over, decliningTape(420)));
  assert.strictEqual(overLead.vcp.candidate, false);
  assert.ok(overLead.vcp.count < 2);
});

check("the first contraction cannot be deeper than 35% and the last must be under 10%", () => {
  const deep = risingTape(420);
  paintVcp(deep, [0.4, 0.08], { vols: [1500, 500], tailVol: 400 });
  const deepLead = leadOf(vcpDesk(deep, decliningTape(420)));
  assert.strictEqual(deepLead.template.complete, true, JSON.stringify(deepLead.template.items));
  assert.strictEqual(deepLead.vcp.candidate, false, deepLead.vcp.reason);
  assert.ok(/deeper than 35%/.test(deepLead.vcp.reason));
  const cap = risingTape(420);
  paintVcp(cap, [0.35, 0.08], { vols: [1500, 500], tailVol: 400 });
  const capLead = leadOf(vcpDesk(cap, decliningTape(420)));
  assert.strictEqual(capLead.vcp.candidate, true, capLead.vcp.reason);
  const justOver = risingTape(420);
  paintVcp(justOver, [0.351, 0.08], { vols: [1500, 500], tailVol: 400 });
  const justLead = leadOf(vcpDesk(justOver, decliningTape(420)));
  assert.ok(/deeper than 35%/.test(justLead.vcp.reason));
  const wideLast = risingTape(420);
  paintVcp(wideLast, [0.2, 0.1], { vols: [1500, 500], tailVol: 400 });
  const wideLead = leadOf(vcpDesk(wideLast, decliningTape(420)));
  assert.strictEqual(wideLead.vcp.candidate, false, wideLead.vcp.reason);
  assert.ok(/not under 10%/.test(wideLead.vcp.reason));
  const tightLast = risingTape(420);
  paintVcp(tightLast, [0.2, 0.099], { vols: [1500, 500], tailVol: 400 });
  const tightLead = leadOf(vcpDesk(tightLast, decliningTape(420)));
  assert.strictEqual(tightLead.vcp.candidate, true, tightLead.vcp.reason);
});

check("a dip under 3% is not a contraction", () => {
  const bars = risingTape(420);
  paintVcp(bars, [0.16, 0.02, 0.06], { vols: [1500, 1000, 500], tailVol: 400 });
  const lead = leadOf(vcpDesk(bars, decliningTape(420)));
  assert.strictEqual(lead.vcp.candidate, true, lead.vcp.reason);
  assert.strictEqual(lead.vcp.count, 2);
  assert.ok(Math.abs(lead.vcp.depths[0] - 0.16) < 1e-9);
  assert.ok(Math.abs(lead.vcp.depths[1] - 0.06) < 1e-9);
});

check("base length is at least 15 sessions and the lookback is 325", () => {
  function shortBase(sessions) {
    const bars = risingTape(420);
    const end = bars.length - 1;
    const H = end - (sessions - 1);
    const P = bars[H].c;
    const rel = [P, P * 0.96, P * 0.9, P * 0.86, P * 0.96, P * 0.98, P, P * 0.985, P * 0.97, P * 0.96, P * 0.95, P * 0.97, P * 0.98, P];
    rel.forEach((price, k) => putBar(bars, H + k, price, k <= 3 ? 1800 : k >= 6 && k <= 10 ? 600 : 1000));
    for (let i = end - 9; i <= end; i++) bars[i].v = 400;
    return bars;
  }
  const tooShort = leadOf(vcpDesk(shortBase(14), decliningTape(420)));
  assert.strictEqual(tooShort.template.complete, true, JSON.stringify(tooShort.template.items.filter((x) => x.state !== "pass")));
  assert.strictEqual(tooShort.vcp.baseSessions, 14);
  assert.strictEqual(tooShort.vcp.candidate, false, tooShort.vcp.reason);
  assert.ok(/shorter than 15/.test(tooShort.vcp.reason));
  const enough = leadOf(vcpDesk(shortBase(15), decliningTape(420)));
  assert.strictEqual(enough.vcp.baseSessions, 15, enough.vcp.reason);
  assert.strictEqual(enough.vcp.candidate, true, enough.vcp.reason);

  function distant(back) {
    const bars = risingTape(520);
    const end = bars.length - 1;
    const saved = bars.map((b) => b.c);
    const c1 = end - back;
    const P1 = saved[c1];
    span(bars, c1, c1 + 4, P1, P1 * 0.84, 2000);
    const c2 = end - 17;
    const P2 = saved[c2];
    for (let i = c1 + 5; i < c2; i++) {
      const t = (i - (c1 + 5)) / (c2 - (c1 + 5));
      putBar(bars, i, P1 * 0.9 + (P2 * 0.99 - P1 * 0.9) * t, 1000);
    }
    span(bars, c2, c2 + 4, P2, P2 * 0.94, 800);
    span(bars, c2 + 5, c2 + 7, P2 * 0.95, P2, 1000);
    for (let i = end - 9; i <= end; i++) putBar(bars, i, P2, 400);
    return bars;
  }
  const inside = leadOf(vcpDesk(distant(300), decliningTape(520)));
  assert.strictEqual(inside.template.complete, true, JSON.stringify(inside.template.items.filter((x) => x.state !== "pass")));
  assert.strictEqual(inside.vcp.candidate, true, inside.vcp.reason);
  assert.ok(inside.vcp.baseSessions > 120);
  assert.ok(inside.vcp.baseSessions <= 325);
  const outside = leadOf(vcpDesk(distant(340), decliningTape(520)));
  assert.strictEqual(outside.template.complete, true, outside.vcp.reason);
  assert.strictEqual(outside.vcp.candidate, false, outside.vcp.reason);
  assert.ok(/at most 80%/.test(outside.vcp.reason));
  assert.ok(outside.vcp.count < 2);
});

check("volume must dry up on the last contraction and into the last 10 sessions", () => {
  const louder = risingTape(420);
  paintVcp(louder, [0.16, 0.08], { vols: [500, 1500], tailVol: 700 });
  const louderLead = leadOf(vcpDesk(louder, decliningTape(420)));
  assert.strictEqual(louderLead.vcp.candidate, false, louderLead.vcp.reason);
  assert.ok(/lower average volume/.test(louderLead.vcp.reason));
  const dryEdge = risingTape(420);
  paintVcp(dryEdge, [0.16, 0.08], { vols: [1500, 500], tailVol: 750 });
  const dryEdgeLead = leadOf(vcpDesk(dryEdge, decliningTape(420)));
  assert.ok(Math.abs(dryEdgeLead.vcp.dry - 0.75) < 1e-9, String(dryEdgeLead.vcp.dry));
  assert.strictEqual(dryEdgeLead.vcp.candidate, true, dryEdgeLead.vcp.reason);
  const wet = risingTape(420);
  paintVcp(wet, [0.16, 0.08], { vols: [1500, 500], tailVol: 751 });
  const wetLead = leadOf(vcpDesk(wet, decliningTape(420)));
  assert.strictEqual(wetLead.vcp.candidate, false, wetLead.vcp.reason);
  assert.ok(/75%/.test(wetLead.vcp.reason));
  const missing = risingTape(420);
  paintVcp(missing, [0.16, 0.08], { vols: [1500, 500], tailVol: 700 });
  missing[missing.length - 30].v = null;
  const missingLead = leadOf(vcpDesk(missing, decliningTape(420)));
  assert.strictEqual(missingLead.vcp.skipped, true, missingLead.vcp.reason);
  assert.strictEqual(missingLead.vcp.candidate, false);
});

check("the right side must be tight and the close must sit near the pivot", () => {
  function withTail(mutate) {
    const bars = risingTape(420);
    const painted = paintVcp(bars, [0.16, 0.08], { vols: [1500, 500], tailVol: 400 });
    mutate(bars, painted.P);
    return leadOf(vcpDesk(bars, decliningTape(420)));
  }
  const wide = withTail((bars, P) => {
    for (let i = bars.length - 10; i < bars.length; i++) {
      bars[i].h = P;
      bars[i].l = P * 0.919;
      bars[i].c = P;
      bars[i].o = P;
    }
  });
  assert.strictEqual(wide.template.complete, true, JSON.stringify(wide.template.items.filter((x) => x.state !== "pass")));
  assert.strictEqual(wide.vcp.candidate, false, wide.vcp.reason);
  assert.ok(/wider than 8%/.test(wide.vcp.reason));
  const rangeEdge = withTail((bars, P) => {
    for (let i = bars.length - 10; i < bars.length; i++) {
      bars[i].h = P;
      bars[i].l = P * 0.92;
      bars[i].c = P;
      bars[i].o = P;
    }
  });
  assert.ok(Math.abs(rangeEdge.vcp.range - 0.08) < 1e-9);
  assert.strictEqual(rangeEdge.vcp.candidate, true, rangeEdge.vcp.reason);
  function pullClose(factor) {
    const bars = risingTape(420);
    const painted = paintVcp(bars, [0.2, 0.095], { vols: [1500, 500], tailVol: 400 });
    const end = bars.length - 1;
    for (let i = end - 49; i <= end - 30; i++) putBar(bars, i, painted.P * 0.86, 1000);
    for (let i = end - 29; i <= end - 26; i++) {
      const t = (i - (end - 29)) / 3;
      putBar(bars, i, painted.P * (0.9 + 0.06 * t), 1000);
    }
    for (let i = end - 9; i <= end; i++) putBar(bars, i, painted.P * factor, 400);
    return leadOf(vcpDesk(bars, decliningTape(420)));
  }
  const lowLead = pullClose(0.919);
  assert.strictEqual(lowLead.template.complete, true, JSON.stringify(lowLead.template.items.filter((x) => x.state !== "pass")));
  assert.strictEqual(lowLead.vcp.candidate, false, lowLead.vcp.reason);
  assert.ok(/more than 8% below/.test(lowLead.vcp.reason));
  const underLead = pullClose(0.92);
  assert.strictEqual(underLead.vcp.candidate, true, underLead.vcp.reason);
  assert.strictEqual(underLead.vcp.brokenOut, false);
  const extended = risingTape(420);
  const ext = paintVcp(extended, [0.16, 0.08], { vols: [1500, 500], tailVol: 400, closePrice: null });
  for (let i = extended.length - 10; i < extended.length; i++) putBar(extended, i, ext.P * 1.051, 400);
  const extLead = leadOf(vcpDesk(extended, decliningTape(420)));
  assert.strictEqual(extLead.vcp.candidate, false, extLead.vcp.reason);
  assert.strictEqual(extLead.vcp.brokenOut, true);
  assert.ok(/more than 5% above/.test(extLead.vcp.reason));
  const atCap = risingTape(420);
  const cap = paintVcp(atCap, [0.16, 0.08], { vols: [1500, 500], tailVol: 400 });
  for (let i = atCap.length - 10; i < atCap.length; i++) putBar(atCap, i, cap.P * 1.05, 400);
  const capLead = leadOf(vcpDesk(atCap, decliningTape(420)));
  assert.strictEqual(capLead.vcp.candidate, true, capLead.vcp.reason);
  assert.strictEqual(capLead.vcp.brokenOut, true);
  assert.ok(/above the pivot/.test(capLead.vcp.reason));
  assert.ok(/separate screen/.test(capLead.vcp.reason));
});

check("a close above the VCP pivot is flagged and breakout volume stays separate", () => {
  const bars = risingTape(420);
  const painted = paintVcp(bars, [0.16, 0.08], { vols: [1500, 500], tailVol: 700 });
  putBar(bars, bars.length - 1, painted.P * 1.02, 700);
  const desk = vcpDesk(bars, decliningTape(420));
  const lead = leadOf(desk);
  assert.strictEqual(lead.vcp.candidate, true, lead.vcp.reason);
  assert.strictEqual(lead.vcp.brokenOut, true);
  assert.ok(lead.vcp.pivot === painted.P);
  const breakout = desk.screens.find((s) => s.id === "breakout");
  assert.ok(breakout.matches.indexOf("LEAD") < 0);
  assert.notStrictEqual(lead.patterns.breakout.state, "match");
  const riser = risingTape(420);
  putBar(riser, riser.length - 1, riser[riser.length - 1].c, 5000);
  const popped = leadOf(vcpDesk(riser, decliningTape(420)));
  assert.strictEqual(popped.patterns.breakout.state, "match");
  assert.strictEqual(popped.vcp.candidate, false);
  const formulas = {};
  E.SCREEN_DEFS.forEach((d) => { formulas[d.id] = d.formula; });
  assert.strictEqual(formulas.tight, "Last 15 sessions' high-to-low range is at most 8% of the midpoint, the 10-session volume is at most 70% of the prior 50, and the close is above the 50-day.");
  assert.strictEqual(formulas.dry, "10-session average volume is at most 60% of the 50 sessions before that window, the close is above the 50-day, and the close is within 15% of the 63-session high.");
  assert.strictEqual(formulas.near, "Close is under that high by at most 3% and still above the 50-day.");
  assert.strictEqual(formulas.breakout, "Close above the highest high of the prior 20 sessions, and volume at least 1.5 times the prior 50-session average. Today's volume is not inside that average.");
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
