#!/usr/bin/env node
/* Build data/nick360/desk.json for the Nick 360 page.
   Reads only files the desk job already wrote (data/scores.csv, data/ohlc/*.csv,
   data/nick360/listings.csv, data/meta.json) and runs site/nick360/engine.js on them,
   the same code the page runs. No network, no new data source, no raw price cache.
   Usage: node nick360_build.js [repo root]. Exit code 0 when the file was written. */
"use strict";
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(process.argv[2] || process.env.ROOT || __dirname);
const DATA = path.join(ROOT, "data");
const E = require(path.join(ROOT, "site", "nick360", "engine.js"));
const P = require(path.join(ROOT, "site", "nick360", "pack.js"));
const Papa = require(path.join(ROOT, "site", "vendor", "papaparse.min.js"));

function readCsv(rel, optional) {
  const file = path.join(DATA, rel);
  if (!fs.existsSync(file)) {
    if (optional) return [];
    throw new Error("missing " + rel);
  }
  return Papa.parse(fs.readFileSync(file, "utf8"), { header: true, skipEmptyLines: "greedy" }).data || [];
}

// Same reader as app.js parseOhlc.
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

function loadInputs() {
  const scores = readCsv("scores.csv");
  const listings = readCsv(path.join("nick360", "listings.csv"), true);
  const meta = JSON.parse(fs.readFileSync(path.join(DATA, "meta.json"), "utf8"));
  const scoreBy = new Map();
  scores.forEach((row) => {
    const t = String(row.ticker || "").toUpperCase();
    if (t) scoreBy.set(t, row);
  });
  const records = [];
  let missing = 0;
  scoreBy.forEach((row, t) => {
    const file = path.join(DATA, "ohlc", t + ".csv");
    let text = null;
    try { text = fs.readFileSync(file, "utf8"); } catch (err) { text = null; }
    if (text == null) { missing += 1; return; }
    records.push({ ticker: t, company: row.company || "", sector: row.sector || "", score: row, bars: parseOhlc(text) });
  });
  const listingMap = {};
  listings.forEach((row) => {
    const t = String(row.ticker || "").toUpperCase();
    if (!t) return;
    listingMap[t] = { offerDate: row.offer_date, name: row.ipo_name, adr: row.adr, source: row.source, dateKind: row.date_kind, note: row.note };
  });
  return { records: records, meta: meta, listingMap: listingMap, missing: missing, tickers: scoreBy.size };
}

function build(opt) {
  const o = opt || {};
  const inp = loadInputs();
  if (!inp.records.length) throw new Error("no stored OHLC files were readable");
  const desk = E.buildDesk(inp.records, inp.meta, inp.listingMap);
  const pack = P.packDesk(desk, { meta: inp.meta, missing: inp.missing, built: new Date().toISOString().slice(0, 19) + "Z" });
  return { desk: desk, pack: pack, inputs: inp, out: o.out };
}

function main() {
  const t0 = Date.now();
  const res = build();
  const outDir = path.join(DATA, "nick360");
  fs.mkdirSync(outDir, { recursive: true });
  const out = path.join(outDir, "desk.json");
  const tmp = out + ".tmp";
  fs.writeFileSync(tmp, JSON.stringify(res.pack));
  fs.renameSync(tmp, out);
  const size = fs.statSync(out).size;
  console.log("nick360 desk file: " + res.pack.stocks_n + " symbols, " + res.inputs.missing + " missing, " +
    (size / 1048576).toFixed(2) + " MB, price date " + res.pack.price_as_of + ", " + ((Date.now() - t0) / 1000).toFixed(1) + "s");
}

module.exports = { build: build, loadInputs: loadInputs, parseOhlc: parseOhlc };
if (require.main === module) {
  try { main(); } catch (err) {
    console.error("nick360 desk file not written: " + (err && err.stack || err));
    process.exit(1);
  }
}
