/**
 * Chart Viewer touch check on an iPhone in portrait (390x844), with real touches sent through the browser.
 * The chip bar is wider than the screen, so a sideways swipe there scrolls the chips and keeps the chart.
 * A sideways swipe on the header row (ticker, price, counter) still changes the chart.
 * Files are served from this checkout. Nothing goes to the network; Yahoo is blocked.
 * Usage: node tests/chart_viewer_touch.mjs   (needs playwright; PLAYWRIGHT_ROOT can point at it)
 * Prints "chart viewer touch ok" and exits 0 when every check passes.
 */
import fs from "fs";
import path from "path";
import { fileURLToPath, pathToFileURL } from "url";

async function loadChromium() {
  try {
    return (await import("playwright")).chromium;
  } catch (err) {
    const root = process.env.PLAYWRIGHT_ROOT;
    if (!root) throw err;
    return (await import(pathToFileURL(path.join(root, "index.mjs")).href)).chromium;
  }
}

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const BASE = "http://desk.test/";
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".csv": "text/csv", ".json": "application/json",
  ".png": "image/png", ".svg": "image/svg+xml", ".webmanifest": "application/manifest+json" };
const IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1";

const fails = [];
function check(ok, what) { if (!ok) fails.push(what); }

const chromium = await loadChromium();
const browser = await chromium.launch();
try {
  const ctx = await browser.newContext({ userAgent: IPHONE, viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true });
  const page = await ctx.newPage();
  let outside = 0;
  await page.route("**/*", (route) => {
    const url = route.request().url();
    if (!url.startsWith(BASE)) { outside++; return route.abort(); }
    const rel = decodeURIComponent(new URL(url).pathname).replace(/^\/+/, "");
    const file = path.join(ROOT, rel);
    if (!file.startsWith(ROOT) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) return route.fulfill({ status: 404, body: "" });
    return route.fulfill({ status: 200, contentType: TYPES[path.extname(file)] || "application/octet-stream", body: fs.readFileSync(file) });
  });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(BASE + "site/chart-viewer.html?list=all", { waitUntil: "load" });
  await page.waitForSelector("#cvgo", { timeout: 20000 });
  await page.waitForFunction(() => document.querySelector("#cvtk") && document.querySelector("#cvtk").textContent, null, { timeout: 20000 });
  await page.click("#cvgo");
  await page.waitForTimeout(600);
  const cdp = await ctx.newCDPSession(page);
  const ticker = () => page.$eval("#cvtk", (e) => e.textContent);
  const rect = (sel) => page.$eval(sel, (e) => { const r = e.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; });
  async function swipe(x0, y, x1, ms) {
    const steps = 8;
    await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x: x0, y: y }] });
    for (let i = 1; i <= steps; i++) {
      await new Promise((r) => setTimeout(r, ms / steps));
      await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x: x0 + ((x1 - x0) * i) / steps, y: y }] });
    }
    await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    await page.waitForTimeout(700);
  }

  check(await page.$eval("#cv", (e) => e.classList.contains("full")), "full screen overlay is open");
  const fit = await page.$eval("#cvtools", (e) => ({ sw: e.scrollWidth, cw: e.clientWidth, left: e.scrollLeft }));
  check(fit.sw > fit.cw, "chip bar overflows at 390x844 (scrollWidth " + fit.sw + " > clientWidth " + fit.cw + ")");
  const v = await page.evaluate(() => window.DeskViewer.swipeZone(false, true, 600, 370));
  check(v === "scroll", "swipeZone says an overflowing chip bar scrolls");

  // A quick sideways swipe on the chip bar, right to left (toward the Drag and range chips).
  const bar = await rect("#cvtools");
  const before = await ticker();
  await swipe(bar.x + bar.w - 30, bar.y + bar.h / 2, bar.x + 40, 200);
  const afterBar = await ticker();
  const left = await page.$eval("#cvtools", (e) => e.scrollLeft);
  check(afterBar === before, "chip bar swipe keeps the same chart (" + before + " -> " + afterBar + ")");
  check(left > fit.left, "chip bar swipe scrolls the chips (scrollLeft " + fit.left + " -> " + left + ")");
  // The far chips are reachable and still work after the scroll.
  await page.$eval('#cvtools [data-range="all"]', (e) => e.scrollIntoView({ inline: "end" }));
  await page.tap('#cvtools [data-range="all"]');
  check(await page.$eval('#cvtools [data-range="all"]', (e) => e.classList.contains("on")), "All chip works after scrolling");
  check((await ticker()) === before, "tapping a range chip keeps the chart");

  // A sideways swipe on the header row still changes the chart, even a slow one.
  const head = await rect(".cv-top");
  await swipe(head.x + 60, head.y + head.h / 2, head.x + 330, 900);
  const afterHead = await ticker();
  check(afterHead !== before, "header swipe changes the chart (" + before + " -> " + afterHead + ")");

  check(outside === 0, "no requests leave this checkout (" + outside + ")");
  check(errors.length === 0, "no page errors: " + errors.join("; "));
} finally {
  await browser.close();
}
if (fails.length) {
  console.log(fails.join("\n"));
  process.exit(1);
}
console.log("chart viewer touch ok");
