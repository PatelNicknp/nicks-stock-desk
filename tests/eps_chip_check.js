/* Chart Viewer EPS chip rules on fixed rows. No clock, no network. Exit 0 when every check passes. */
const path = require("path");
const V = require(path.join(__dirname, "..", "site", "js", "viewer.js"));

const fails = [];
function eq(got, want, what) {
  const a = JSON.stringify(got);
  const b = JSON.stringify(want);
  if (a !== b) fails.push(what + ": got " + a + " want " + b);
}

// Chip text, color line, and the blank cases.
eq(V.epsChip(85, 80).text, "EPS 85", "85 text");
eq(V.epsChip(85, 80).hot, true, "85 is green");
eq(V.epsChip(80, 80).hot, true, "80 is green");
eq(V.epsChip(79, 80).hot, false, "79 is plain");
eq(V.epsChip(79, 80).show, true, "79 still shows");
eq(V.epsChip("99", 80).text, "EPS 99", "text from a csv string");
eq(V.epsChip(1, 80).text, "EPS 1", "1 shows");
eq(V.epsChip(90, 95).hot, false, "green line follows the setting");
eq(V.epsChip(90, 0).hot, true, "a bad setting falls back to 80");
["", null, undefined, "nan", "None", 0, -5, 100, "abc"].forEach((v) => {
  eq(V.epsChip(v, 80).show, false, "no chip for " + JSON.stringify(v));
  eq(V.epsChip(v, 80).text, "", "no text for " + JSON.stringify(v));
});

// buildLists reads eps_rating from scores.csv, and a scanner row fills a stock scores.csv has no rating for.
const files = {
  "scores.csv": [
    { ticker: "AAA", company: "Alpha", score: "80", rs: "95", eps_rating: "85" },
    { ticker: "BBB", company: "Beta", score: "70", rs: "60", eps_rating: "42" },
    { ticker: "CCC", company: "Gamma", score: "60", rs: "50", eps_rating: "" },
    { ticker: "DDD", company: "Delta", score: "50", rs: "88" },
  ],
  "scanner_vcp.csv": [
    { ticker: "AAA", status: "READY", reason: "r" },
    { ticker: "BBB", status: "READY", reason: "r" },
    { ticker: "CCC", status: "READY", reason: "r" },
  ],
  "scanner_eps_rs.csv": [{ ticker: "DDD", status: "PASSES", eps_rating: "91", reason: "r" }],
};
const built = V.buildLists(files, {});
eq(built.info.AAA.eps, 85, "AAA eps from scores");
eq(built.info.BBB.eps, 42, "BBB eps from scores");
eq(built.info.CCC.eps, null, "CCC has no rating");
eq(built.info.DDD.eps, 91, "DDD eps from the Highest EPS and RS row");
eq(V.epsChip(built.info.CCC.eps, 80).show, false, "CCC has no chip");
eq(V.epsChip(built.info.BBB.eps, 80).hot, false, "BBB chip is plain");

if (fails.length) {
  console.log(fails.join("\n"));
  process.exit(1);
}
console.log("eps chip ok");
