/* The saved Nick 360 desk file must give the same ranks, grades, screens, and chart numbers
   as computing the whole desk in the browser. No network. */
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const E = require("../site/nick360/engine.js");
const P = require("../site/nick360/pack.js");

const ROOT = path.resolve(__dirname, "..");
const MAS = [10, 20, 50, 150, 200];

function day(i) {
  const dt = new Date(Date.UTC(2021, 0, 4));
  dt.setUTCDate(dt.getUTCDate() + i);
  return dt.toISOString().slice(0, 10);
}
function synthetic() {
  const records = [];
  for (let n = 0; n < 40; n++) {
    const len = n === 3 ? 30 : n === 4 ? 0 : 420 + (n % 7) * 40;
    const rows = [];
    let px = 20 + n;
    for (let i = 0; i < len; i++) {
      px = px * (1 + Math.sin(i / (5 + n % 4)) * 0.012 + (n % 5 - 2) * 0.0009);
      rows.push({ date: day(i + (n % 3)), open: px * 0.995, high: px * 1.02, low: px * 0.98, close: px, volume: n === 6 && i === len - 5 ? "" : 10000 + ((i * 37 + n * 11) % 900) * 100 });
    }
    records.push({ ticker: "T" + n, company: "Co " + n, sector: "S" + (n % 3), score: n % 2 ? { entry_low: "10", entry_high: "11", stop: "9", trade_target: "14", other: "x" } : {}, bars: rows });
  }
  return { records: records, meta: { price_as_of: day(700) }, listingMap: { T1: { offerDate: day(0), adr: "1" } } };
}

function same(a, b, where) {
  assert.deepStrictEqual(JSON.parse(JSON.stringify(a == null ? null : a)), JSON.parse(JSON.stringify(b == null ? null : b)), where);
}
function at(arr, i) { return i >= 0 ? arr[i] : undefined; }

function compareLite(full, lite, where) {
  const i = full.last;
  assert.strictEqual(lite.ticker, full.ticker, where);
  assert.strictEqual(lite.last, i, where + " last");
  assert.strictEqual(lite.bars.length, full.bars.length, where + " bar count");
  ["company", "sector", "date", "close", "chg", "offHigh", "stale", "pivot20"].forEach((k) => assert.strictEqual(lite[k], full[k], where + " " + k));
  same(lite.stage, full.stage, where + " stage");
  same(lite.vcp, full.vcp, where + " vcp");
  same(lite.patterns.near, full.patterns.near, where + " near");
  same(lite.template, full.template, where + " template");
  same(lite.recent, full.recent, where + " recent");
  same(at(lite.bars, i), at(full.bars, i), where + " last bar");
  ["rank", "grade", "pressure", "risk", "relVol", "dry"].forEach((k) => same(at(lite[k], i), at(full[k], i), where + " " + k));
  MAS.forEach((p) => same(at(lite.sma[p], i), at(full.sma[p], i), where + " sma" + p));
  ["entry_low", "entry_high", "stop", "trade_target"].forEach((k) => {
    const want = full.score && full.score[k] != null && full.score[k] !== "" ? full.score[k] : undefined;
    assert.strictEqual(lite.score[k], want, where + " " + k);
  });
}

function compareHydrated(full, h, where) {
  same(h.bars, full.bars, where + " bars");
  ["rank", "grade", "pressure", "risk", "relVol", "dry", "wscore"].forEach((k) => same(h[k], full[k], where + " " + k));
  MAS.forEach((p) => same(h.sma[p], full.sma[p], where + " sma" + p));
  ["last", "date", "close", "chg", "offHigh", "stale", "pivot20"].forEach((k) => assert.strictEqual(h[k], full[k], where + " " + k));
  ["stage", "vcp", "template", "recent", "patterns", "hl"].forEach((k) => same(h[k], full[k], where + " " + k));
}

function check(desk, meta, rowsFor, label) {
  const pack = JSON.parse(JSON.stringify(P.packDesk(desk, { meta: meta, missing: 0 })));
  const lite = P.unpackDesk(pack, E);
  assert.strictEqual(lite.stocks.length, desk.stocks.length);
  desk.screens.forEach((sc, k) => {
    const got = lite.screens[k];
    assert.strictEqual(got.id, sc.id);
    same(got.matches, sc.matches, label + " screen " + sc.id);
    assert.strictEqual(got.evaluated, sc.evaluated, label + " evaluated " + sc.id);
    assert.strictEqual(got.skipped, sc.skipped, label + " skipped " + sc.id);
    assert.strictEqual(got.ourName, sc.ourName);
    assert.strictEqual(got.formula, sc.formula);
  });
  let hydrated = 0;
  desk.stocks.forEach((s, k) => {
    compareLite(s, lite.stocks[k], label + " " + s.ticker);
    const h = P.hydrate(lite.stocks[k], rowsFor(s.ticker), E, { price_as_of: pack.price_as_of }, pack.dates);
    compareHydrated(s, h, label + " hydrated " + s.ticker);
    hydrated += 1;
  });
  return { pack: pack, hydrated: hydrated };
}

const syn = synthetic();
const synDesk = E.buildDesk(syn.records, syn.meta, syn.listingMap);
const synRows = new Map(syn.records.map((r) => [r.ticker, r.bars]));
check(synDesk, syn.meta, (t) => synRows.get(t), "synthetic");
assert.throws(() => P.unpackDesk({ kind: "nick360-desk", v: 999 }, E));
console.log("ok synthetic desk round trip");

if (fs.existsSync(path.join(ROOT, "data", "ohlc")) && fs.existsSync(path.join(ROOT, "data", "scores.csv")) && !process.env.N360_SKIP_REAL) {
  const B = require("../nick360_build.js");
  const res = B.build();
  const rows = new Map(res.inputs.records.map((r) => [r.ticker, r.bars]));
  const out = check(res.desk, res.inputs.meta, (t) => rows.get(t), "stored");
  console.log("ok stored desk round trip: " + res.desk.stocks.length + " symbols, " + out.hydrated + " charts recomputed, " + res.desk.screens.length + " screens");
  const saved = path.join(ROOT, "data", "nick360", "desk.json");
  if (fs.existsSync(saved)) {
    const file = JSON.parse(fs.readFileSync(saved, "utf8"));
    if (file.price_as_of === out.pack.price_as_of && file.updated_pt === out.pack.updated_pt) {
      const strip = (p) => Object.assign({}, p, { built_utc: "" });
      same(strip(file), strip(out.pack), "saved desk.json matches the stored files");
      console.log("ok saved desk.json matches the stored files");
    } else console.log("note: saved desk.json is from " + file.updated_pt + "; stored files are from " + out.pack.updated_pt);
  }
}
console.log("nick360 pack ok");
