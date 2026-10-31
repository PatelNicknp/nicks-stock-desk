/**
 * Chart Viewer first view on iPhone and iPad, portrait and landscape, with the real chart in a headless browser.
 * The first view must show the last range_months_phone (3) or range_months (6) months with the newest candle
 * on screen and the candles spread across the width (only the reason-box padding on the right). It must be put
 * back after a resize, a turn of the device, and opening or closing full screen, and also when the chart was
 * first drawn only a few px wide and widened later. A range the user dragged to is kept through all of those
 * until a range chip is tapped.
 * Files are served from this checkout. Nothing goes to the network; Yahoo is blocked.
 * Usage: node tests/chart_viewer_fit.mjs   (needs playwright; PLAYWRIGHT_ROOT can point at it)
 * Prints "chart viewer fit ok" and exits 0 when every check passes.
 */
import fs from "fs";
import path from "path";
import { createRequire } from "module";
import { fileURLToPath, pathToFileURL } from "url";

const killer = setTimeout(() => { console.log("chart viewer fit: timed out"); process.exit(2); }, 240000);

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
const V = createRequire(import.meta.url)(path.join(ROOT, "site", "js", "viewer.js"));
const BASE = "http://desk.test/";
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".csv": "text/csv", ".json": "application/json",
  ".png": "image/png", ".svg": "image/svg+xml", ".webmanifest": "application/manifest+json" };
const IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1";
const IPAD = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15";
const CASES = [
  { name: "iPhone portrait", w: 390, h: 844, ua: IPHONE, mobile: true },
  { name: "iPhone landscape", w: 844, h: 390, ua: IPHONE, mobile: true },
  { name: "iPad portrait", w: 820, h: 1180, ua: IPAD, mobile: false },
  { name: "iPad landscape", w: 1180, h: 820, ua: IPAD, mobile: false },
];

const fails = [];
function check(ok, what) { if (!ok) fails.push(what); }
function datesOf(ticker) {
  const lines = fs.readFileSync(path.join(ROOT, "data", "ohlc", ticker + ".csv"), "utf8").trim().split("\n").slice(1);
  return lines.map((l) => l.slice(0, 10)).filter(Boolean).sort();
}

async function openPage(browser, c, narrowPx) {
  const ctx = await browser.newContext({ userAgent: c.ua, viewport: { width: c.w, height: c.h }, isMobile: c.mobile, hasTouch: true, deviceScaleFactor: 2 });
  await ctx.addInitScript((narrow) => {
    Object.defineProperty(navigator, "maxTouchPoints", { get: () => 5 });
    if (/Macintosh/.test(navigator.userAgent)) Object.defineProperty(navigator, "platform", { get: () => "MacIntel" });
    // Keep a handle on each chart the viewer makes, to read its visible range.
    window.__charts = [];
    let lc;
    Object.defineProperty(window, "LightweightCharts", { configurable: true, get: () => lc, set: (v) => {
      const make = v.createChart;
      lc = Object.assign({}, v, { createChart: function () { const ch = make.apply(this, arguments); window.__charts.push(ch); return ch; } });
    } });
    // Draw the chart only a few px wide (layout not done yet), to widen it later.
    if (narrow) document.addEventListener("DOMContentLoaded", () => {
      const st = document.createElement("style");
      st.id = "narrow";
      st.textContent = "#cvchart{right:auto!important;width:" + narrow + "px!important}";
      document.head.appendChild(st);
    });
  }, narrowPx || 0);
  const page = await ctx.newPage();
  const net = { outside: 0 };
  await page.route("**/*", (route) => {
    const url = route.request().url();
    if (!url.startsWith(BASE)) { net.outside++; return route.abort(); }
    const rel = decodeURIComponent(new URL(url).pathname).replace(/^\/+/, "");
    const file = path.join(ROOT, rel);
    if (!file.startsWith(ROOT) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) return route.fulfill({ status: 404, body: "" });
    return route.fulfill({ status: 200, contentType: TYPES[path.extname(file)] || "application/octet-stream", body: fs.readFileSync(file) });
  });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(BASE + "site/chart-viewer.html?list=all", { waitUntil: "load" });
  await page.waitForFunction(() => window.__charts.length && document.querySelector("#cvtk").textContent, null, { timeout: 20000 });
  await page.waitForTimeout(700);
  const ticker = await page.$eval("#cvtk", (e) => e.textContent);
  return { ctx, page, net, errors, ticker, dates: datesOf(ticker) };
}

const view = (page) => page.evaluate(() => {
  const ts = window.__charts[window.__charts.length - 1].timeScale();
  const lr = ts.getVisibleLogicalRange();
  return { from: lr.from, to: lr.to, plot: ts.width() };
});
const settle = (page) => page.waitForTimeout(500);

function firstView(v, dates, what, monthsWanted) {
  const n = dates.length;
  const months = monthsWanted || (v.plot < 520 ? 3 : 6);
  const want = V.rangeFrom(dates, months);
  check(Math.abs(v.from - (want - 0.5)) <= 1, what + ": starts " + months + " months back (from " + v.from.toFixed(1) + ", want " + (want - 0.5) + ")");
  check(v.to >= n - 1, what + ": newest candle on screen");
  const share = (n - 1 - Math.max(v.from, 0)) / (v.to - v.from);
  check(share >= 0.34, what + ": candles use " + Math.round(share * 100) + "% of the width, not a narrow strip");
  check(share <= 0.999, what + ": a little room on the right for the reason box");
  const pxPerBar = v.plot / (v.to - v.from);
  check(pxPerBar > 1.2, what + ": candles are not squeezed (" + pxPerBar.toFixed(2) + " px per bar)");
}

const chromium = await loadChromium();
const browser = await chromium.launch();
try {
  for (const c of CASES) {
    const { ctx, page, net, errors, ticker, dates } = await openPage(browser, c);
    const n = dates.length;
    const L = (step) => c.name + " " + step;
    firstView(await view(page), dates, L("inline"));
    await page.click("#cvgo"); await settle(page);
    firstView(await view(page), dates, L("full screen"));
    await page.setViewportSize({ width: c.h, height: c.w }); await settle(page);
    firstView(await view(page), dates, L("turned"));
    await page.setViewportSize({ width: c.w, height: c.h }); await settle(page);
    firstView(await view(page), dates, L("turned back"));

    const before = await view(page);
    // Drag the chart slowly to the right (back in time). The same stock stays, and the dragged range is kept.
    const box = await page.$eval("#cvchart", (e) => { const r = e.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; });
    const cdp = await ctx.newCDPSession(page);
    const y = box.y + box.h * 0.4;
    await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x: box.x + box.w * 0.2, y }] });
    for (let i = 1; i <= 12; i++) {
      await new Promise((r) => setTimeout(r, 70));
      await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x: box.x + box.w * (0.2 + (0.5 * i) / 12), y }] });
    }
    await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    await page.waitForTimeout(600);
    check((await page.$eval("#cvtk", (e) => e.textContent)) === ticker, L("drag") + ": a slow drag keeps the same stock");
    const panned = await view(page);
    check(panned.from < before.from - 5, L("drag") + ": the drag moved back in time (from " + before.from.toFixed(1) + " to " + panned.from.toFixed(1) + ")");
    const kept = async (step) => {
      const v = await view(page);
      check(Math.abs(v.from - panned.from) <= 1 && Math.abs(v.to - panned.to) <= 1,
        L(step) + ": keeps the dragged range (" + v.from.toFixed(1) + " to " + v.to.toFixed(1) + ", dragged " + panned.from.toFixed(1) + " to " + panned.to.toFixed(1) + ")");
    };
    await page.setViewportSize({ width: c.h, height: c.w }); await settle(page);
    await kept("turned after drag");
    await page.setViewportSize({ width: c.w, height: c.h }); await settle(page);
    await kept("turned back after drag");
    await page.click("#cvx"); await settle(page);
    await kept("closed full screen after drag");
    await page.click("#cvgo"); await settle(page);
    await kept("full screen again after drag");
    await page.$eval('#cvtools [data-range="3m"]', (e) => e.scrollIntoView({ inline: "end" }));
    await page.$eval('#cvtools [data-range="3m"]', (e) => e.click());
    await settle(page);
    firstView(await view(page), dates, L("3M chip"), 3);
    await page.setViewportSize({ width: c.h, height: c.w }); await settle(page);
    firstView(await view(page), dates, L("3M chip turned"), 3);
    check(net.outside === 0, L("network") + ": no requests leave this checkout (" + net.outside + ")");
    check(errors.length === 0, L("errors") + ": " + errors.join("; "));
    await ctx.close();

    // Drawn while the chart is only 8 px wide, then widened: the first view is set once it is wide enough.
    const nw = await openPage(browser, c, 8);
    await nw.page.evaluate(() => document.getElementById("narrow").remove());
    await settle(nw.page);
    firstView(await view(nw.page), nw.dates, L("drawn narrow, then widened"));
    await nw.page.click("#cvgo"); await settle(nw.page);
    firstView(await view(nw.page), nw.dates, L("drawn narrow, then full screen"));
    check(nw.errors.length === 0, L("narrow errors") + ": " + nw.errors.join("; "));
    await nw.ctx.close();
  }
} finally {
  await browser.close();
}
clearTimeout(killer);
if (fails.length) {
  console.log(fails.join("\n"));
  process.exit(1);
}
console.log("chart viewer fit ok");
