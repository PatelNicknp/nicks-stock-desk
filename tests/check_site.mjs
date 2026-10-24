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
const outDir = process.argv[3] || "/opt/cursor/artifacts/site-screenshots";
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
