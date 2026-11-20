/* MarketSurge-style Chart Viewer rules on fixed rows: Comp chip, base rows, shapes, caption, colors. No clock, no network. */
const path = require("path");
const V = require(path.join(__dirname, "..", "site", "js", "viewer.js"));
const fails = [];
function eq(got, want, what) {
  const a = JSON.stringify(got), b = JSON.stringify(want);
  if (a !== b) fails.push(what + ": got " + a + " want " + b);
}

// Comp chip: same rules as the RS and EPS chips.
eq(V.compChip(91, 80).text, "Comp 91", "91 text");
eq(V.compChip(91, 80).hot, true, "91 green");
eq(V.compChip(80, 80).hot, true, "80 green");
eq(V.compChip(79, 80).hot, false, "79 plain");
eq(V.compChip(79, 80).show, true, "79 shows");
eq(V.compChip("85", 80).text, "Comp 85", "csv string");
eq(V.compChip(90, 95).hot, false, "green line follows the setting");
eq(V.compChip(90, 0).hot, true, "bad setting falls back to 80");
["", null, undefined, "nan", "None", 0, -3, 100, "abc"].forEach((v) => {
  eq(V.compChip(v, 80).show, false, "no chip for " + JSON.stringify(v));
  eq(V.compChip(v, 80).text, "", "no text for " + JSON.stringify(v));
});

// buildLists carries composite_rating from scores.csv, and scanner pivots ride on each entry.
const built = V.buildLists({
  "scores.csv": [{ ticker: "AAA", company: "Alpha", score: "80", rs: "95", eps_rating: "85", composite_rating: "93" },
    { ticker: "BBB", company: "Beta", score: "70", rs: "60", eps_rating: "", composite_rating: "" }],
  "scanner_vcp.csv": [{ ticker: "AAA", status: "READY", pivot: "26.11", reason: "r", strength: "90" }, { ticker: "BBB", status: "READY", pivot: "", reason: "r", strength: "80" }],
}, { featureOn: () => true, includeWatching: true });
eq(built.info.AAA.comp, 93, "comp from scores");
eq(built.info.BBB.comp, null, "blank comp is null");
eq(built.info.AAA.entries[0].pivot, 26.11, "scanner pivot on the entry");
eq(built.info.BBB.entries[0].pivot, null, "blank pivot is null");

// Base rows by ticker.
const idx = V.patternIndex([
  { ticker: "aaa", pattern: "flat_base", latest: "no", status: "COMPLETED", start_date: "2026-01-05", end_date: "2026-02-20", left_high: "50", low: "45", low_date: "2026-01-30", depth_pct: "10", length_weeks: "6.6", pivot: "50", buy_point: "50.1", zone_top: "52.5", pct_from_pivot: "20", breakout_date: "2026-02-23", data_status: "OK" },
  { ticker: "AAA", pattern: "cup_handle", latest: "yes", status: "BUY ZONE", start_date: "2026-04-01", end_date: "2026-08-14", left_high: "60", low: "42", low_date: "2026-06-01", depth_pct: "30", length_weeks: "20", pivot: "58", buy_point: "58.1", zone_top: "60.9", pct_from_pivot: "2.1", breakout_date: "2026-08-17", handle_date: "2026-07-20", handle_depth_pct: "8.5", data_status: "OK" },
  { ticker: "BBB", pattern: "nonsense", latest: "yes", start_date: "2026-01-01", end_date: "2026-02-01", pivot: "5", data_status: "OK" },
  { ticker: "CCC", pattern: "cup", latest: "yes", start_date: "", end_date: "", pivot: "5", data_status: "OK" },
  { ticker: "", pattern: "cup", data_status: "MISSING" },
]);
eq(Object.keys(idx), ["AAA"], "only real rows kept");
eq(idx.AAA.map((b) => b.pattern), ["flat_base", "cup_handle"], "oldest first");
eq(idx.AAA[1].latest, true, "latest flag");
eq(idx.AAA[1].name, "Cup w/ Handle", "plain name");
eq(V.patternIndex(null), {}, "no rows");

// Dates to bar indexes: daily is that day, weekly is the week holding it, clamped at the ends.
const dates = ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-09"];
eq(V.barIndexOn(dates, "2026-01-06"), 2, "exact day");
eq(V.barIndexOn(dates, "2026-01-07"), 3, "next bar on or after");
eq(V.barIndexOn(dates, "2025-12-01"), 0, "before the first bar");
eq(V.barIndexOn(dates, "2027-01-01"), 3, "after the last bar");
eq(V.barIndexOn([], "2026-01-01"), -1, "no bars");

// Shapes on fixed bars (a bowl, then a handle).
const bars = [];
const closes = [60, 55, 50, 46, 44, 43, 44, 47, 52, 57, 59, 56, 54, 55, 58];
closes.forEach((c, i) => bars.push({ date: "2026-03-" + String(i + 1).padStart(2, "0"), o: c, h: c + 1, l: c - 1, c: c }));
const cup = V.patternShape({ pattern: "cup_handle", startDate: "2026-03-01", endDate: "2026-03-15", lowDate: "2026-03-06", handleDate: "2026-03-11", breakoutDate: "", leftHigh: 61, low: 42, pivot: 60, zoneTop: 63 }, bars);
eq(cup.kind, "cup", "cup kind");
eq([cup.s, cup.e, cup.low, cup.rim], [0, 14, 5, 10], "cup indexes");
eq(cup.pivotFrom, 10, "pivot line starts at the handle");
eq(cup.handleLow, 12, "handle low index");
eq(cup.path[0], [0, 61], "outline starts at the left side high");
eq(cup.path[cup.path.length - 1], [10, 60], "outline ends at the rim");
eq(cup.path.every((p) => Number.isFinite(p[0]) && Number.isFinite(p[1])), true, "outline is all numbers");
eq(Math.min.apply(null, cup.path.map((p) => p[1])), 42, "outline reaches the bottom of the bowl");
const box = V.patternShape({ pattern: "flat_base", startDate: "2026-03-01", endDate: "2026-03-10", lowDate: "2026-03-06", leftHigh: 61, low: 42, pivot: 61, zoneTop: 64 }, bars);
eq(box.kind, "box", "flat is a box");
eq([box.top, box.bottom, box.pivotFrom], [61, 42, 0], "box edges");
const dbl = V.patternShape({ pattern: "double_bottom", startDate: "2026-03-01", endDate: "2026-03-15", lowDate: "2026-03-06", firstLowDate: "2026-03-04", midPeakDate: "2026-03-05", leftHigh: 61, low: 42, pivot: 58 }, bars);
eq(dbl.kind, "double", "double bottom kind");
eq(dbl.pts.length, 5, "W has five points");
eq(dbl.pts[2], [4, 58], "middle peak at the pivot");

// Caption.
const cap = V.patternCaption(idx.AAA[1]);
eq(/^Cup w\/ Handle, 30% deep, 20 weeks, handle 8.5% deep\. Pivot 58\.00, buy point 58\.10, buy zone up to 60\.90\. Price is 2\.10% above the pivot \(buy zone\)\.$/.test(cap), true, "caption: " + cap);
eq(V.patternCaption(null), "", "no base no caption");

// MarketSurge colors: 50-day red, 200-day black, 10-week and 40-week on Weekly.
eq(V.msMaColor(50, true), "#dc2626", "50 red");
eq(V.msMaColor(200, true), "#111827", "200 black on white");
eq(V.msMaColor(200, false), "#e5e7eb", "200 light on dark");
eq([V.msPeriod(50, true), V.msPeriod(150, true), V.msPeriod(200, true), V.msPeriod(10, true), V.msPeriod(50, false)], [10, 30, 40, 10, 50], "weekly periods");
Object.keys(V.PATTERN_NAMES).forEach((k) => { eq(typeof V.PATTERN_COLORS[k], "string", "color for " + k); });

if (fails.length) { console.log("marketsurge check FAILED:\n- " + fails.join("\n- ")); process.exit(1); }
console.log("marketsurge check ok");
