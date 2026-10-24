/**
 * Open every desk page, fail on a JavaScript error, and save screenshots.
 * Usage: node tests/check_site.mjs [baseUrl]
 * Default base is http://127.0.0.1:8765/site/
 */
import fs from "fs";
import path from "path";
import { pathToFileURL } from "url";

async function loadChromium() {
  try {
    return (await import("playwright")).chromium;
  } catch (err) {
    const root = process.env.PLAYWRIGHT_ROOT;
    if (!root) throw err;
    return (await import(pathToFileURL(path.join(root, "index.mjs")).href)).chromium;
  }
}

const base = process.argv[2] || "http://127.0.0.1:8765/site/";
const outDir = process.argv[3] || "/opt/cursor/artifacts/site-screenshots-v3";
const pages = [
  "index.html", "top-stocks.html", "scorecard.html", "watchlist.html", "alerts.html", "backtest.html",
  "growth.html", "quality.html", "dividend.html", "wheel.html", "vcp.html", "canslim.html",
  "box.html", "flag.html", "leaders.html", "earnings-calendar.html", "earnings-heatmap.html",
  "earnings-cards.html", "put-call.html", "walls.html", "analysts.html", "thirteen-f.html", "aaii.html",
  "insiders.html", "headlines.html", "xly-xlp.html", "financials.html", "earnings-tracker.html",
  "company-financials.html", "dividend-fundamentals.html", "macro.html", "sector-macro.html",
  "historical-pe.html", "breakouts.html", "trends.html", "pullbacks.html", "gainers.html",
  "breadth.html", "sector-performance.html", "heatmaps.html", "updates.html", "help.html",
];
const ipad = new Set(["index.html", "top-stocks.html", "scorecard.html", "watchlist.html", "backtest.html", "vcp.html"]);

function ignore(text) {
  const t = String(text || "");
  return /favicon|net::ERR_BLOCKED|Download the React DevTools/i.test(t);
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"') {
        if (text[i + 1] === '"') { cell += '"'; i++; }
        else quoted = false;
      } else cell += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ",") { row.push(cell); cell = ""; }
    else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      row.push(cell);
      cell = "";
      if (row.length > 1 || row[0] !== "") rows.push(row);
      row = [];
    } else cell += ch;
  }
  if (cell.length || row.length) {
    row.push(cell);
    rows.push(row);
  }
  if (!rows.length) return [];
  const header = rows[0];
  return rows.slice(1).filter((r) => r.some((c) => c !== "")).map((r) => {
    const obj = {};
    header.forEach((key, i) => { obj[key] = r[i] == null ? "" : r[i]; });
    return obj;
  });
}

function sameNum(a, b) {
  if (String(a).trim() === "" && String(b).trim() === "") return true;
  const na = Number(a);
  const nb = Number(b);
  if (Number.isFinite(na) && Number.isFinite(nb)) return Math.abs(na - nb) < 1e-6;
  return String(a).trim() === String(b).trim();
}

function checkScores(dataDir) {
  const scoresPath = path.join(dataDir, "scores.csv");
  if (!fs.existsSync(scoresPath)) {
    console.error("missing " + scoresPath);
    return 1;
  }
  const scores = parseCsv(fs.readFileSync(scoresPath, "utf8"));
  const byTicker = new Map();
  let buys = 0;
  for (const row of scores) {
    const ticker = String(row.ticker || "").trim();
    if (!ticker) continue;
    byTicker.set(ticker, row);
    if (String(row.verdict || "").trim() === "BUY") buys += 1;
  }
  const problems = [];
  for (const name of fs.readdirSync(dataDir).filter((n) => n.endsWith(".csv")).sort()) {
    const rows = parseCsv(fs.readFileSync(path.join(dataDir, name), "utf8"));
    if (!rows.length) continue;
    if (name === "market_today.csv" && Object.prototype.hasOwnProperty.call(rows[0], "buy_count")) {
      const got = Number(rows[0].buy_count);
      if (got !== buys) problems.push("market_today.csv buy_count " + rows[0].buy_count + " != " + buys + " BUY rows in scores.csv");
      continue;
    }
    const hasScore = Object.prototype.hasOwnProperty.call(rows[0], "score");
    const hasVerdict = Object.prototype.hasOwnProperty.call(rows[0], "verdict");
    if (!Object.prototype.hasOwnProperty.call(rows[0], "ticker") || (!hasScore && !hasVerdict)) continue;
    if (name === "scores.csv") continue;
    let use = rows;
    if (name === "score_history.csv") {
      const latest = new Map();
      for (const row of rows) {
        const ticker = String(row.ticker || "").trim();
        if (!ticker) continue;
        const prev = latest.get(ticker);
        if (!prev || String(row.date || "") >= String(prev.date || "")) latest.set(ticker, row);
      }
      use = [...latest.values()];
    }
    let scoreMiss = 0;
    let verdictMiss = 0;
    for (const row of use) {
      const ticker = String(row.ticker || "").trim();
      if (!ticker || !byTicker.has(ticker)) continue;
      const truth = byTicker.get(ticker);
      if (hasScore && !sameNum(row.score, truth.score)) scoreMiss += 1;
      if (hasVerdict && String(row.verdict || "").trim() !== String(truth.verdict || "").trim()) verdictMiss += 1;
    }
    if (scoreMiss || verdictMiss) problems.push(name + " score " + scoreMiss + " verdict " + verdictMiss);
  }
  if (problems.length) {
    console.error("score consistency:\n" + problems.join("\n"));
    return problems.length;
  }
  console.log("scores agree across data/*.csv (" + buys + " BUY)");
  return 0;
}

const dataDir = path.resolve(path.dirname(new URL(import.meta.url).pathname), "../data");
const scoreFails = checkScores(dataDir);
if (scoreFails) process.exit(1);

fs.mkdirSync(outDir, { recursive: true });
const chromium = await loadChromium();
const browser = await chromium.launch({ headless: true });
const failures = [];

for (const file of pages) {
  const url = new URL(file, base).href;
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
  const errors = [];
  page.on("pageerror", (err) => errors.push(String(err)));
  page.on("console", (msg) => {
    if (msg.type() === "error" && !ignore(msg.text())) errors.push(msg.text());
  });
  try {
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
    await page.waitForSelector("body[data-ready='1']", { timeout: 90000 });
    const title = await page.locator("h1").innerText();
    const research = await page.locator(".rl").innerText();
    if (!/Research only/.test(research)) errors.push("missing research line");
    if (!title) errors.push("missing title");
    if (file === "index.html" || file === "breadth.html") {
      const check = await page.evaluate(() => {
        const chart = Chart.getChart(document.getElementById("br"));
        const y = chart.scales.y;
        const rows = chart.data.datasets.map((d, i) => {
          const value = d.data[d.data.length - 1];
          const drawn = chart.getDatasetMeta(i).data[d.data.length - 1].y;
          return { label: d.label, value, drawn, pixel: y.getPixelForValue(value) };
        });
        return { yMin: y.min, yMax: y.max, rows, chips: document.querySelector(".chips") ? document.querySelector(".chips").innerText : "" };
      });
      if (check.yMin !== 0 || check.yMax !== 100) errors.push("breadth scale is " + check.yMin + " to " + check.yMax);
      for (const row of check.rows) {
        if (Math.abs(row.drawn - row.pixel) > 1) errors.push(row.label + " last point is drawn off its value");
        if (file === "index.html") {
          const chip = check.chips.match(new RegExp(row.label + "\\s+([0-9.]+)%"));
          if (!chip) errors.push("missing chip for " + row.label);
          else if (Math.abs(Number(chip[1]) - row.value) > 0.05) errors.push(row.label + " chip " + chip[1] + " != chart " + row.value);
        }
      }
    }
    const shot = path.join(outDir, file.replace(".html", "") + "-1600.png");
    await page.screenshot({ path: shot });
    if (ipad.has(file)) {
      await page.setViewportSize({ width: 1180, height: 820 });
      await page.waitForTimeout(300);
      await page.screenshot({ path: path.join(outDir, file.replace(".html", "") + "-ipad.png") });
    }
  } catch (err) {
    errors.push(String(err));
  }
  if (errors.length) failures.push({ file, errors });
  await page.close();
  process.stdout.write((errors.length ? "FAIL " : "ok   ") + file + "\n");
}

await browser.close();
fs.writeFileSync(path.join(outDir, "report.json"), JSON.stringify({ failures }, null, 2));
if (failures.length) {
  console.error(JSON.stringify(failures, null, 2));
  process.exit(1);
}
console.log("all pages rendered");
