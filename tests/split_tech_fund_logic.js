/* Technical | Fundamental split: group mapping, list filtering, the off switch, and the remembered pick. Fixed rows, no clock, no network. */
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
    { ticker: "AAA", company: "Alpha", score: "9" }, { ticker: "BBB", company: "Beta", score: "12" },
    { ticker: "CCC", company: "Gamma", score: "3" }, { ticker: "DDD", company: "Delta", score: "7" },
  ],
  "scanner_vcp.csv": [{ ticker: "AAA", status: "READY", strength: "80", reason: "Tight." }],
  "scanner_box.csv": [{ ticker: "BBB", status: "BROKEN OUT today", strength: "30", reason: "Out of the box." }],
  "scanner_canslim.csv": [
    { ticker: "AAA", status: "READY", strength: "60", reason: "Strict qualify." },
    { ticker: "CCC", status: "READY", strength: "70", reason: "Strict qualify." },
  ],
  "scanner_leaders.csv": [{ ticker: "AAA", status: "READY", strength: "90", reason: "VCP and CANSLIM agree." }],
  "scanner_growth.csv": [{ ticker: "DDD", passes: "yes", why: "Sales up 40%." }, { ticker: "BBB", passes: "no", why: "" }],
  "scanner_volume.csv": [{ ticker: "CCC", direction: "BUYING", spike: "yes", streak: "no", quiet: "no", volume_ratio: "3", reason: "3x volume." }],
  "buy_setups.csv": [{ ticker: "BBB", best_status: "BROKEN OUT today", reason: "Box broke out today." }],
  "watchlist.csv": [{ ticker: "DDD", timing: "Uptrend", note_input: "" }],
};
const allOn = () => true;
const base = { featureOn: allOn, includeWatching: true, includeClosed: false };

// Group mapping: every viewer scanner list has a side; Buy setups and Watchlist have none (they show in both).
V.LISTS.forEach((l) => {
  if (l.scanner) eq(["technical", "fundamental"].indexOf(V.groupOf(l.id)) >= 0, true, l.id + " has a side");
  else eq(V.groupOf(l.id), "", l.id + " is in both sides");
});
eq(["canslim", "leaders", "growth", "quality", "dividend"].map((id) => V.groupOf(id)), Array(5).fill("fundamental"), "CANSLIM, Leaders, Growth, Quality, Dividend are fundamental");
eq(["vcp", "box", "flag", "qullamaggie", "marios", "ep", "gapup", "week52", "volume", "breakdowns", "wheel"].map((id) => V.groupOf(id)),
  Array(11).fill("technical"), "pattern, gap, 52-week, volume, breakdown, and wheel lists are technical");
// A settings row wins over the default; any other word leaves it out of both; a blank row uses the default.
const read = (rows) => (key) => (key in rows ? rows[key] : null);
eq(V.groupOf("wheel", read({ "scanner_groups.wheel": "Fundamental" })), "fundamental", "settings row wins, any case");
eq(V.groupOf("wheel", read({ "scanner_groups.wheel": "none" })), "", "another word is neither side");
eq(V.groupOf("wheel", read({ "scanner_groups.wheel": "" })), "technical", "a blank row uses the default");

// Switch off (no group): exactly the old lists, the old All label, and the old reasons.
const off = V.buildLists(files, base);
eq(JSON.stringify(V.buildLists(files, Object.assign({}, base, { group: "" }))), JSON.stringify(off), "no group is the old behavior");
eq(JSON.stringify(V.buildLists(files, Object.assign({}, base, { group: "sideways" }))), JSON.stringify(off), "an unknown group is the old behavior");
eq(off.lists[0].label, "All scanner stocks", "old All label");
eq(off.lists.map((l) => l.id), ["all", "buysetups", "watchlist", "vcp", "canslim", "box", "flag", "qullamaggie", "marios", "ep", "gapup", "leaders",
  "breakdowns", "volume", "week52", "growth", "quality", "dividend", "wheel"], "old list set: every list, both sides");
eq(off.lists[0].items, ["AAA", "CCC", "BBB", "DDD"], "old All mixes both sides");
eq(off.info.AAA.count, 3, "old count is every scanner");

// Technical: only technical lists plus Buy setups and Watchlist; All technical stocks; reasons from that side only.
const tech = V.buildLists(files, Object.assign({}, base, { group: "technical" }));
eq(tech.lists[0].label, "All technical stocks", "All technical stocks label");
eq(tech.lists.filter((l) => l.id !== "all").every((l) => l.id === "buysetups" || l.id === "watchlist" || V.groupOf(l.id) === "technical"), true, "technical picker has only technical lists");
eq(["buysetups", "watchlist"].every((id) => tech.lists.some((l) => l.id === id)), true, "Buy setups and Watchlist show on the technical side");
eq(tech.lists.some((l) => l.id === "canslim" || l.id === "leaders" || l.id === "growth"), false, "no fundamental list on the technical side");
eq(tech.lists[0].items, ["AAA", "BBB", "CCC"], "All technical stocks: VCP, Box, High volume");
eq(tech.info.AAA.entries.map((e) => e.label), ["VCP"], "technical Why box drops CANSLIM and Leaders");
eq(tech.info.BBB.entries.map((e) => e.label), ["Buy setup", "Box"], "Buy setup lines show on the technical side");
eq(tech.info.AAA.count, 1, "technical count is technical scanners only");

// Fundamental.
const fund = V.buildLists(files, Object.assign({}, base, { group: "fundamental" }));
eq(fund.lists[0].label, "All fundamental stocks", "All fundamental stocks label");
eq(fund.lists.filter((l) => l.id !== "all").every((l) => l.id === "buysetups" || l.id === "watchlist" || V.groupOf(l.id) === "fundamental"), true, "fundamental picker has only fundamental lists");
eq(fund.lists.some((l) => l.id === "vcp" || l.id === "box" || l.id === "volume"), false, "no technical list on the fundamental side");
eq(fund.lists[0].items, ["AAA", "CCC", "DDD"], "All fundamental stocks: CANSLIM + Leaders first, then by strength");
eq(fund.info.AAA.entries.map((e) => e.label), ["CANSLIM", "Leaders"], "fundamental Why box drops VCP");
eq(fund.info.DDD.entries.map((e) => e.label), ["Growth", "Watchlist"], "Watchlist lines show on the fundamental side");
eq(fund.info.BBB.entries.map((e) => e.label), ["Buy setup"], "a technical-only stock keeps only its Buy setup line");
eq(fund.info.BBB.count, 0, "and counts no fundamental scanner");
// A settings mapping moves a list across.
const moved = V.buildLists(files, Object.assign({}, base, { group: "fundamental", groupOf: (id) => (id === "volume" ? "fundamental" : V.groupOf(id)) }));
eq(moved.lists.some((l) => l.id === "volume"), true, "a list mapped to fundamental shows there");

// Remembered pick: address group, then the address list's side, then the saved pick, then default_group, then technical.
eq(V.pickGroup("", "", "", "", V.groupOf), "technical", "a new device starts on technical");
eq(V.pickGroup("", "", "", "fundamental", V.groupOf), "fundamental", "default_group sets a new device");
eq(V.pickGroup("", "", "fundamental", "technical", V.groupOf), "fundamental", "the saved pick wins over default_group");
eq(V.pickGroup("", "all", "fundamental", "technical", V.groupOf), "fundamental", "list=all keeps the saved pick");
eq(V.pickGroup("", "buysetups", "fundamental", "technical", V.groupOf), "fundamental", "Buy setups keeps the saved pick");
eq(V.pickGroup("", "canslim", "technical", "technical", V.groupOf), "fundamental", "a CANSLIM link opens the fundamental side");
eq(V.pickGroup("", "vcp", "fundamental", "technical", V.groupOf), "technical", "a VCP link opens the technical side");
eq(V.pickGroup("technical", "canslim", "fundamental", "fundamental", V.groupOf), "technical", "group= in the address wins");
eq(V.pickGroup("junk", "", "junk", "junk", V.groupOf), "technical", "bad values fall back to technical");

if (fails.length) {
  console.log(fails.join("\n"));
  process.exit(1);
}
console.log("split tech fund logic ok");
