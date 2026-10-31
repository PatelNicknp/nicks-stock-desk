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
    { ticker: "OOO", status: "WATCHING", strength: "85", reason: "The trend template is 8 of 8, with one pullback so far." },
    { ticker: "WWW", status: "WATCHING", strength: "70", reason: "Price is through the buy point." },
  ],
};
eq(V.isWatching("WATCHING (trend not 8/8)") && V.isWatching("WATCHING"), true, "labeled WATCHING counts as WATCHING");
eq(V.isWatching("READY") || V.isWatching("BROKEN OUT today"), false, "READY and BROKEN OUT are not WATCHING");
eq(V.rankOf("WATCHING (trend not 8/8)") > V.rankOf("WATCHING"), true, "weaker label ranks under plain WATCHING");
built = V.buildLists(weakFiles, { featureOn: allOn, includeWatching: true });
eq(built.lists.find((l) => l.id === "vcp").items, ["AAA", "OOO", "WWW", "HHH"], "trend-not-8/8 rows sort after READY and every plain WATCHING");
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
// New defaults: a flick is at least 80 px and at most 300 ms; ratio stays 1.5.
const sw2 = (dx, dy, ms, extra) => V.swipeDirection(dx, dy, ms, Object.assign({ minPx: 80, maxMs: 300, ratio: 1.5, touchPan: true }, extra || {}));
eq(sw2(120, 10, 200), "next", "drag mode move chart: a quick flick on the chart changes it");
eq(sw2(-120, 10, 250), "prev", "a quick flick left is the one before");
eq(sw2(120, 10, 300), "next", "exactly swipe_max_ms still counts");
eq(sw2(120, 10, 301), "", "a slow drag on the chart never changes the chart");
eq(sw2(400, 5, 1500), "", "a long slow drag back through history never changes the chart");
eq(sw2(70, 0, 100), "", "a flick under 80 px is not a swipe");
eq(sw2(120, 90, 100), "", "ratio 1.5 still rules out a mostly up-down flick");
eq(sw2(120, 10, 2000, { onBar: true }), "next", "a slow swipe on the header or chip bar always changes the chart");
// Where a touch starts: the header row always swipes; the chip bar only when it fits; else it scrolls.
eq(V.swipeZone(true, false, 0, 0), "bar", "header row is a swipe bar");
eq(V.swipeZone(false, true, 370, 370), "bar", "a chip bar that fits is a swipe bar");
eq(V.swipeZone(false, true, 371, 370), "bar", "one pixel of rounding still fits");
eq(V.swipeZone(false, true, 640, 370), "scroll", "an overflowing chip bar scrolls and never changes the chart");
eq(V.swipeZone(false, false, 0, 0), "chart", "the chart area needs a quick flick");
// After a resize, a turn, or full screen: keep a dragged range, else refit once the chart is 120 px wide.
eq(V.viewAfterResize(null, 300, 120), "fit", "no drag: put the first view back");
eq(V.viewAfterResize(null, 119, 120), "wait", "a chart under 120 px wide waits, so bars are not packed at the right edge");
eq(V.viewAfterResize(null, 0, 120), "wait", "a chart not laid out yet waits");
eq(V.viewAfterResize({ from: 900, to: 1000 }, 300, 120), "keep", "a dragged range is kept");
eq(V.viewAfterResize({ from: 900, to: 1000 }, 50, 120), "keep", "a dragged range is kept at any width");
eq(V.viewAfterResize({ from: 5, to: 5 }, 300, 120), "fit", "an empty range is not a drag");
eq(V.viewAfterResize({ from: NaN, to: 9 }, 300, 120), "fit", "a broken range is not a drag");
eq(V.viewAfterResize(null, 130), "fit", "120 px is the default minimum");
eq(sw2(-120, 10, 2000, { onBar: true }), "prev", "header swipe left is the one before");
eq(sw2(60, 0, 100, { onBar: true }), "", "header swipes still need swipe_min_px");
eq(sw2(120, 10, 2000, { touchPan: false }), "next", "drag mode next chart: any sideways swipe changes it");
eq(sw2(120, 10, 2000, { onBar: true, rightIsNext: false }), "prev", "the flip button works for header swipes");
eq(V.swipeDirection(70, 0, 100, { touchPan: true }), "", "built-in default minPx is 80");
eq(V.swipeDirection(120, 0, 350, { touchPan: true }), "", "built-in default maxMs is 300");

// Range: the chart holds every saved bar; range_months and the range chips only pick the first view.
const days = [];
for (let d = new Date(Date.UTC(2021, 10, 1)); d <= new Date(Date.UTC(2026, 9, 29)); d.setUTCDate(d.getUTCDate() + 1)) {
  if (d.getUTCDay() % 6) days.push(d.toISOString().slice(0, 10));
}
eq(days[V.rangeFrom(days, 3)] >= "2026-07-29" && days[V.rangeFrom(days, 3) - 1] < "2026-07-29", true, "3M starts three months back");
eq(days[V.rangeFrom(days, 6)] >= "2026-04-29", true, "6M starts six months back");
eq(days[V.rangeFrom(days, 12)] >= "2025-10-29" && days[V.rangeFrom(days, 12) - 1] < "2025-10-29", true, "1Y starts a year back");
eq(V.rangeFrom(days, 0), 0, "All shows every saved bar");
eq(V.rangeFrom(days, "all"), 0, "all shows every saved bar");
eq(V.rangeFrom(days.slice(-40), 6), 0, "a short history shows from its first bar");
eq(V.rangeFrom([], 6), 0, "no bars is 0");
eq(V.RANGES.map((r) => r.label), ["3M", "6M", "1Y", "All"], "range chips are 3M, 6M, 1Y, All");
eq(V.RANGES.map((r) => r.months), [3, 6, 12, 0], "range chip months");

// Memory: only the last few bar files stay parsed, so swiping a long list stays light on an iPad.
let kr = [[], []];
["A", "B", "C"].forEach((n) => { kr = V.keepRecent(kr[0], n, 2); });
eq(kr, [["B", "C"], ["A"]], "keepRecent drops the oldest");
eq(V.keepRecent(["B", "C"], "B", 2), [["C", "B"], []], "seeing a chart again moves it to the end");

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

// iPhone and iPad skip Safari's own full screen (its grey X covers the stock name) unless native_fullscreen_ios is on.
const IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1";
const IPAD_OLD = "Mozilla/5.0 (iPad; CPU OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1";
const MAC_SAFARI = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15";
const WIN_CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36";
eq(V.isAppleTouch(IPHONE, "iPhone", 5), true, "iPhone user agent is iOS");
eq(V.isAppleTouch(IPAD_OLD, "iPad", 5), true, "iPad user agent is iPadOS");
eq(V.isAppleTouch(MAC_SAFARI, "MacIntel", 5), true, "iPad reporting as a Mac with touch is iPadOS");
eq(V.isAppleTouch("", "MacIntel", 5), true, "MacIntel platform with touch is iPadOS");
eq(V.isAppleTouch(MAC_SAFARI, "", 2), true, "Mac user agent with touch is iPadOS");
eq(V.isAppleTouch(MAC_SAFARI, "MacIntel", 0), false, "a real Mac has no touch points");
eq(V.isAppleTouch(MAC_SAFARI, "MacIntel", 1), false, "one touch point is not an iPad");
eq(V.isAppleTouch(WIN_CHROME, "Win32", 10), false, "a Windows touch screen is not iOS");
eq(V.isAppleTouch(undefined, undefined, undefined), false, "no navigator details is not iOS");
eq(V.useNativeFullscreen(false, false), true, "computers keep native full screen");
eq(V.useNativeFullscreen(false, true), true, "computers keep native full screen with the switch on");
eq(V.useNativeFullscreen(true, false), false, "iPhone and iPad use the overlay by default");
eq(V.useNativeFullscreen(true, true), true, "native_fullscreen_ios true brings back Safari's full screen");

// Gap Up list: in the picker and in All scanner stocks, file order kept, chart_viewer.include_gap_up switch.
const gapFiles = {
  "scanner_vcp.csv": [{ ticker: "AAA", status: "READY", strength: "80", reason: "Tight." }],
  "scanner_gap_up.csv": [
    { ticker: "ZZZ", status: "GAP UP today", gap_date: "2026-10-29", gap_pct: "1.2", reason: "Gapped up 1.20% over the prior day's high on 2026-10-29, today." },
    { ticker: "AAA", status: "GAP HOLDING", gap_date: "2026-10-20", gap_pct: "6.5", reason: "" },
  ],
};
eq(V.LISTS.some((l) => l.id === "gapup" && l.label === "Gap Up" && l.file === "scanner_gap_up.csv" && l.scanner), true, "Gap Up is a scanner list");
built = V.buildLists(gapFiles, { featureOn: allOn, includeWatching: true });
eq(built.lists.find((l) => l.id === "gapup").items, ["ZZZ", "AAA"], "Gap Up keeps its newest-first file order");
eq(built.lists[0].items, ["AAA", "ZZZ"], "All scanner stocks counts Gap Up as a scanner");
eq(built.info.AAA.count, 2, "AAA is on VCP and Gap Up");
eq(built.info.ZZZ.entries[0].label + " " + built.info.ZZZ.entries[0].status, "Gap Up GAP UP today", "Gap Up reason box label and status");
eq(built.info.AAA.entries.find((e) => e.list === "gapup").reason, "Gapped up 6.50% over the prior day's high on 2026-10-20 and has not closed under the gap-day low.", "Gap Up reason falls back to plain words");
built = V.buildLists(gapFiles, { featureOn: allOn, includeWatching: true, includeGapUp: false });
eq(built.lists.some((l) => l.id === "gapup"), false, "include_gap_up false drops the list");
eq(built.lists[0].items, ["AAA"], "include_gap_up false drops Gap Up stocks from All");
built = V.buildLists(gapFiles, { featureOn: (k) => k !== "feature.scanner_gap_up", includeWatching: true });
eq(built.lists.some((l) => l.id === "gapup"), false, "features.scanner_gap_up off drops the list");

if (fails.length) {
  console.log(fails.join("\n"));
  process.exit(1);
}
console.log("chart viewer logic ok");
