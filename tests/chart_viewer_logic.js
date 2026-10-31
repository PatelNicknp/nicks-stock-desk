/* Chart Viewer list, reason, and swipe rules on fixed rows. No clock, no network. Exit 0 when every check passes. */
const path = require("path");
const V = require(path.join(__dirname, "..", "site", "js", "viewer.js"));

const fails = [];
function eq(got, want, what) {
  const a = JSON.stringify(got);
  const b = JSON.stringify(want);
  if (a !== b) fails.push(what + ": got " + a + " want " + b);
}

const files = {
  "scores.csv": [
    { ticker: "AAA", company: "Alpha", score: "9", price: "10", day_pct: "1.5" },
    { ticker: "BBB", company: "Beta", score: "12", price: "20", day_pct: "-2" },
    { ticker: "CCC", company: "Gamma", score: "3", price: "30", day_pct: "0" },
    { ticker: "DDD", company: "Delta", score: "7", price: "40", day_pct: "0" },
    { ticker: "EEE", company: "Echo", score: "5", price: "50", day_pct: "0" },
  ],
  "scanner_vcp.csv": [
    { ticker: "AAA", status: "READY", strength: "80", reason: "Trend template 8/8. Contractions: 5.8%, 3.5%. Buy point 200.66. The pullbacks are tightening." },
    { ticker: "BBB", status: "WATCHING", strength: "40", reason: "Trend template 7/8." },
    { ticker: "", status: "", data_status: "MISSING" },
  ],
  "scanner_box.csv": [
    { ticker: "BBB", status: "BROKEN OUT today", strength: "30", reason: "Closed above the box." },
    { ticker: "CCC", status: "READY", strength: "90", reason: "Tight range." },
  ],
  "scanner_qullamaggie.csv": [
    { ticker: "DDD", status: "CLOSED", strength: "50", reason: "Closed trade." },
  ],
  "scanner_growth.csv": [
    { ticker: "AAA", passes: "yes", why: "Revenue growth is at least the screen level." },
    { ticker: "EEE", passes: "no", why: "Too slow." },
  ],
  "scanner_volume.csv": [
    { ticker: "EEE", direction: "BUYING", spike: "yes", streak: "no", quiet: "no", volume_ratio: "3", reason: "Traded 3 times its usual volume." },
  ],
  "scanner_52w.csv": [
    { ticker: "CCC", new_high_today: "no", new_low_today: "no", near_high: "yes", high_on_volume: "no", pct_from_high: "-2.5" },
    { ticker: "DDD", new_high_today: "no", new_low_today: "no", near_high: "no" },
  ],
  "buy_setups.csv": [
    { ticker: "BBB", best_status: "BROKEN OUT today", reason: "Box broke out today." },
  ],
  "watchlist.csv": [
    { ticker: "DDD", timing: "Uptrend", note_input: "" },
  ],
};
const allOn = () => true;
let built = V.buildLists(files, { featureOn: allOn, includeWatching: true, includeClosed: false });
const ids = built.lists.map((l) => l.id);
eq(ids.slice(0, 3), ["all", "buysetups", "watchlist"], "list order starts with All, Buy setups, Watchlist");
eq(ids.indexOf("vcp") > 0 && ids.indexOf("ep") > 0 && ids.indexOf("week52") > 0 && ids.indexOf("wheel") > 0, true, "every scanner has a list");
const all = built.lists[0];
// AAA: VCP + Growth = 2, strength 80. BBB: VCP + Box = 2, strength 40. CCC: Box + 52-week = 2, strength 90. EEE: volume = 1.
// DDD: only a CLOSED trade and the watchlist, so it is not in All.
eq(all.items, ["CCC", "AAA", "BBB", "EEE"], "All is deduped, most scanners first, then strength");
eq(built.info.BBB.entries.map((e) => e.label + " " + e.status), ["Buy setup BROKEN OUT today", "Box BROKEN OUT today", "VCP WATCHING"], "reasons list every list, best status first");
eq(built.info.BBB.count, 2, "Buy setups do not count as a scanner");
eq(built.lists.find((l) => l.id === "vcp").items, ["AAA", "BBB"], "single list keeps its own order");
eq(built.info.CCC.entries[1].reason, "Within 5% of its 52-week high (2.50% under it).", "52-week reason is plain words");

built = V.buildLists(files, { featureOn: allOn, includeWatching: false, includeClosed: true });
eq(built.lists[0].items, ["CCC", "AAA", "DDD", "BBB", "EEE"], "include_closed adds DDD, include_watching off drops BBB from VCP");
eq(built.lists.find((l) => l.id === "vcp").items, ["AAA"], "WATCHING left out when include_watching is off");

// vcp.show_weaker_trend on: labeled WATCHING rows follow include_watching and rank under plain WATCHING.
const weakFiles = {
  "scanner_vcp.csv": [
    { ticker: "AAA", status: "READY", strength: "80", reason: "Trend template 8/8." },
    { ticker: "HHH", status: "WATCHING (trend not 8/8)", strength: "95", reason: "Pullbacks are tightening, but the trend template is 0 of 8." },
    { ticker: "OOO", status: "WATCHING (one pullback)", strength: "85", reason: "The trend template is 8 of 8, but there is only one pullback so far." },
    { ticker: "WWW", status: "WATCHING", strength: "70", reason: "Price is through the buy point." },
  ],
};
eq(V.isWatching("WATCHING (trend not 8/8)") && V.isWatching("WATCHING (one pullback)") && V.isWatching("WATCHING"), true, "labeled WATCHING counts as WATCHING");
eq(V.isWatching("READY") || V.isWatching("BROKEN OUT today"), false, "READY and BROKEN OUT are not WATCHING");
eq(V.rankOf("WATCHING (trend not 8/8)") > V.rankOf("WATCHING"), true, "weaker label ranks under plain WATCHING");
built = V.buildLists(weakFiles, { featureOn: allOn, includeWatching: true });
eq(built.lists.find((l) => l.id === "vcp").items, ["AAA", "WWW", "HHH", "OOO"], "weaker rows sort after READY and plain WATCHING");
eq(built.info.HHH.entries.map((e) => e.label + " " + e.status), ["VCP WATCHING (trend not 8/8)"], "reason box keeps the full label");
built = V.buildLists(weakFiles, { featureOn: allOn, includeWatching: false });
eq(built.lists.find((l) => l.id === "vcp").items, ["AAA"], "include_watching off drops every WATCHING label");
eq(built.lists[0].items, ["AAA"], "All scanner stocks drops weaker rows with include_watching off");

built = V.buildLists(files, { featureOn: (k) => k !== "feature.scanner_box", includeWatching: true });
eq(built.lists.some((l) => l.id === "box"), false, "a list turned off in settings is not offered");
eq(built.lists[0].items.indexOf("CCC") >= 0, true, "CCC stays in All through the 52-week list");

built = V.buildLists(Object.assign({}, files, { "watchlist.csv": [] }), { featureOn: allOn, includeWatching: true });
eq(built.lists.some((l) => l.id === "watchlist"), false, "an empty watchlist is not offered");

eq(V.shorten("Trend template 8/8. Contractions: 5.8%, 3.5%. Buy point 200.66. The pullbacks are tightening.", 60),
  "Trend template 8/8. Contractions: 5.8%, 3.5%.", "shorten keeps whole sentences and does not split 5.8");
eq(V.shorten("word ".repeat(40), 30).endsWith("..."), true, "shorten cuts a long run-on at a word");
eq(V.shorten("Short.", 110), "Short.", "short reasons stay as they are");

const sw = (dx, dy, ms, extra) => V.swipeDirection(dx, dy, ms, Object.assign({ minPx: 50, maxMs: 700, ratio: 1.5 }, extra || {}));
eq(sw(120, 10, 200), "next", "swipe right is next by default");
eq(sw(-120, 10, 200), "prev", "swipe left is the one before");
eq(sw(120, 10, 200, { rightIsNext: false }), "prev", "the flip button swaps it");
eq(sw(30, 0, 100), "", "a short drag is not a swipe");
eq(sw(100, 90, 100), "", "a mostly up-down drag is not a swipe");
eq(sw(150, 10, 2000), "next", "a slow swipe still counts when the chart cannot pan");
eq(sw(150, 10, 2000, { touchPan: true }), "", "with chart_touch_pan a slow drag pans the chart instead");
eq(sw(150, 10, 300, { touchPan: true }), "next", "with chart_touch_pan a quick flick still changes the chart");

eq(Math.round(V.padBars(120, 600, 200) * 10) / 10, 60, "pad bars keep the last candle left of the box");
eq(V.padBars(120, 600, 0), 3, "no box, the normal small gap");
eq(V.padBars(120, 300, 290) <= (0.65 * 300 * 120) / (0.35 * 300) + 1e-9, true, "a very wide box never squeezes the candles under a third");

if (fails.length) {
  console.log(fails.join("\n"));
  process.exit(1);
}
console.log("chart viewer logic ok");
