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
eq(/^Cup w\/ Handle, 30% deep, 20 weeks, handle 8.5% deep\. Pivot 58\.00, buy point 58\.10, buy zone up to 60\.90\. Breakout 2026-08-17\. Price is 2\.10% above the pivot \(buy zone\)\.$/.test(cap), true, "caption: " + cap);
eq(V.patternCaption(null), "", "no base no caption");

// MarketSurge colors: 50-day red, 200-day black, 10-week and 40-week on Weekly.
eq(V.msMaColor(50, true), "#dc2626", "50 red");
eq(V.msMaColor(200, true), "#111827", "200 black on white");
eq(V.msMaColor(200, false), "#e5e7eb", "200 light on dark");
eq([V.msPeriod(50, true), V.msPeriod(150, true), V.msPeriod(200, true), V.msPeriod(10, true), V.msPeriod(50, false)], [10, 30, 40, 10, 50], "weekly periods");
Object.keys(V.PATTERN_NAMES).forEach((k) => { eq(typeof V.PATTERN_COLORS[k], "string", "color for " + k); });

// MarketSurge style: swing prices. A clean up-down-up zigzag gives alternating highs and lows that moved enough.
const zig = [];
[10, 20, 12, 24, 23.5, 15].forEach((p, k, arr) => {
  if (k === arr.length - 1) return;
  const q = arr[k + 1];
  for (let j = 0; j < 10; j++) { const c = p + (q - p) * j / 10; zig.push({ date: "d" + zig.length, o: c, h: c + 0.1, l: c - 0.1, c: c }); }
});
const sw = V.swingPoints(zig, 3, 8);
eq(sw.map((p) => p.kind), ["low", "high", "low", "high", "low"], "swing kinds alternate");
eq(sw.map((p) => Math.round(p.price * 10) / 10), [9.9, 20.1, 11.9, 24.1, 15.8], "swing prices; the 23.5 dip is too small for its own label");
eq(V.swingPoints([], 3, 8), [], "no bars no swings");
// EPS markers: eps_marks.csv rows as they are; earnings_history rows give the change against four quarters back.
eq(V.epsMarks([{ ticker: "A", date: "2026-05-01", eps: "1.2", yoy_pct: "36", data_status: "OK" }, { ticker: "A", date: "2026-02-01", eps: "1", yoy_pct: "", data_status: "OK" }]),
  [{ date: "2026-02-01", eps: 1, pct: null }, { date: "2026-05-01", eps: 1.2, pct: 36 }], "eps_marks rows, oldest first");
const hist = ["2025-01-30", "2025-04-30", "2025-07-30", "2025-10-30", "2026-01-30"].map((d, k) => ({ earnings_date: d, eps_actual: String([1, 1.1, 1.2, 1.3, 1.5][k]) }));
hist.push({ earnings_date: "2026-04-30", eps_actual: "" });
const em = V.epsMarks(hist);
eq(em.length, 5, "only reported quarters");
eq(em[4].pct, 50, "1.5 vs 1.0 a year before is +50%");
eq(em[0].pct, null, "no year-ago quarter, no percent");
eq(V.epsMarks([{ earnings_date: "2025-01-01", eps_actual: "-1" }, { earnings_date: "2025-04-01", eps_actual: "1" }, { earnings_date: "2025-07-01", eps_actual: "1" }, { earnings_date: "2025-10-01", eps_actual: "1" }, { earnings_date: "2026-01-01", eps_actual: "1" }])[4].pct, null, "a year-ago loss gives no percent");
eq([V.epsMarkText({ pct: 36 }), V.epsMarkText({ pct: -12 }), V.epsMarkText({ pct: null })], ["EPS +36%", "EPS -12%", "EPS"], "marker text");
// Pivot note in the header.
const pbars = ["2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14", "2026-08-17", "2026-08-18"].map((d) => ({ date: d, c: 59.74 }));
eq(V.pivotNote({ latest: true, status: "BUY ZONE", pivot: 58, breakoutDate: "2026-08-14", endDate: "2026-08-13" }, pbars), "+3.0% from Pivot in 2 days", "pivot note with a breakout");
eq(V.pivotNote({ latest: true, status: "NEAR PIVOT", pivot: 62, breakoutDate: "", endDate: "2026-08-13" }, pbars), "-3.6% from Pivot", "below the pivot, no breakout yet");
eq(V.pivotNote({ latest: true, status: "COMPLETED", pivot: 58 }, pbars), "", "no note for a finished base");
eq(V.pivotNote(null, pbars), "", "no base no note");
// MarketSurge style colors stay as written in light mode (none of them is in desk.js LIGHT_MAP).
const deskSrc = require("fs").readFileSync(path.join(__dirname, "..", "site", "js", "desk.js"), "utf8");
const lightMap = deskSrc.slice(deskSrc.indexOf("const LIGHT_MAP"), deskSrc.indexOf("const THEME_KEY")).toLowerCase();
const colors = [V.MSS.up, V.MSS.down, V.MSS.rs, V.MSS.volAvg, V.MSS.bg].concat(Object.values(V.MSS.ma));
colors.forEach((c) => { if (c !== "#FFFFFF") eq(lightMap.indexOf('"' + c.toLowerCase() + '"'), -1, "not remapped: " + c); });

// v3 pattern recognition: the cup bowl hugs the lows, labels carry the stage, failed bases are not live.
eq(V.bowlHull([[0, 10], [1, 50], [2, 30], [3, 60], [4, 20]]), [[0, 10], [1, 50], [3, 60], [4, 20]], "bowl goes under every low, skips the bounce");
eq(V.bowlHull([[0, 5]]), [[0, 5]], "one point bowl");
eq([V.isLive("BUY ZONE"), V.isLive("FORMING"), V.isLive("COMPLETED"), V.isLive("FAILED")], [true, true, false, false], "live statuses");
const sIdx = V.patternIndex([{ ticker: "SSS", pattern: "saucer", latest: "yes", status: "FAILED", start_date: "2026-01-05", end_date: "2026-07-01", left_high: "50", low: "40", low_date: "2026-03-01", depth_pct: "20", length_weeks: "25", pivot: "50", buy_point: "50.1", zone_top: "52.5", pct_from_pivot: "-9", breakout_date: "2026-07-02", handle_date: "2026-06-20", handle_depth_pct: "6", rim_date: "2026-06-20", handle_low_date: "2026-06-25", stage: "2", stage_label: "2(b)", deep_base: "yes", breakout_volume_pct: "55", breakout_volume_ok: "yes", failed_date: "2026-07-20", data_status: "OK" },
  { ticker: "TTT", pattern: "cup_handle", latest: "yes", status: "BUY ZONE", start_date: "2026-04-01", end_date: "2026-08-14", left_high: "60", low: "46", low_date: "2026-06-01", depth_pct: "23.4", length_weeks: "9.2", pivot: "58", buy_point: "58.1", zone_top: "60.9", pct_from_pivot: "2.1", breakout_date: "2026-08-17", handle_date: "2026-07-20", handle_depth_pct: "8.5", stage: "2", stage_label: "2", breakout_volume_pct: "12", breakout_volume_ok: "no", data_status: "OK" }]);
const sb = sIdx.SSS[sIdx.SSS.length - 1], tb = sIdx.TTT[sIdx.TTT.length - 1];
eq([sb.name, sb.stageLabel, sb.deep, sb.boVolOk, sb.failedDate, sb.rimDate, sb.handleLowDate], ["Saucer w/ Handle", "2(b)", true, true, "2026-07-20", "2026-06-20", "2026-06-25"], "saucer row fields");
eq(V.patternLabel(tb), "Cup w/ Handle 23% 9w  Stage 2", "label with depth, weeks, stage");
eq(V.patternLabel(sb), "Saucer w/ Handle 20% 25w  Stage 2(b)  failed", "failed label");
const sCap = V.patternCaption(sb), tCap = V.patternCaption(tb);
eq([sCap.includes("Stage 2(b)"), sCap.includes("deeper than usual"), sCap.includes("+55%"), sCap.includes("Failed 2026-07-20")], [true, true, true, true], "caption: stage, deep, volume, failed");
eq(tCap.includes("(light)"), true, "caption flags a light-volume breakout");

// v5 tighter bases: an ascending base is a rising channel through its pullbacks; no line dips to a one-bar spike.
const aBars = [];
for (let i = 0; i < 40; i++) { const d = new Date(Date.UTC(2026, 7, 3 + i)).toISOString().slice(0, 10); aBars.push({ date: d, h: 100 + i, l: 90 + i, c: 95 + i }); }
aBars[5].l = 60;  // a spike wick
const aIdx = V.patternIndex([{ ticker: "ASC", pattern: "ascending_base", latest: "yes", status: "FORMING", start_date: aBars[2].date, end_date: aBars[38].date,
  left_high: "138", low: "94", low_date: aBars[5].date, depth_pct: "14", length_weeks: "7", pivot: "138", buy_point: "138.1", zone_top: "144.9", pct_from_pivot: "-1",
  pullback_low_dates: [aBars[5].date, aBars[15].date, aBars[25].date].join(";"), pullback_high_dates: [aBars[2].date, aBars[12].date, aBars[22].date].join(";"), data_status: "OK" }]);
const aBase = aIdx.ASC[0];
eq([aBase.pullbackLowDates.length, aBase.pullbackHighDates.length], [3, 3], "pullback dates read");
const aSh = V.patternShape(aBase, aBars);
eq(aSh.kind, "asc", "ascending base is a channel");
eq(aSh.lowPts.map((p) => p[0]), [5, 15, 25], "lower line through the three pullback lows");
eq(aSh.lowPts[0][1], 94, "spike wick clipped to the base low from the file");
eq(aSh.highPts[aSh.highPts.length - 1][0], 38, "upper line ends at the base high");
eq(V.patternShape(Object.assign({}, aBase, { pullbackLowDates: [] }), aBars).kind, "box", "no pullback dates: plain lines");

if (fails.length) { console.log("marketsurge check FAILED:\n- " + fails.join("\n- ")); process.exit(1); }
console.log("marketsurge check ok");
