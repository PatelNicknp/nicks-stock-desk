/**
 * Chart Viewer first view on iPhone and iPad, portrait and landscape, with the real chart in a headless browser.
 * With dense_default on, the first view uses one candle width (target_bar_spacing) on every screen,
 * daily or weekly, with the newest candle about 12 px left of the price axis. It must be put
 * back after a resize, a turn of the device, and opening or closing full screen, and also when the chart was
 * first drawn only a few px wide and widened later. A range the user dragged to is kept through all of those
 * until a range chip is tapped. With the Why box at the top left, the newest candle stays about 12 px
 * left of the price axis. 3M, 6M, 1Y, and All are hidden; Daily | Weekly is in their place.
 * Files are served from this checkout. Nothing goes to the network; Yahoo is blocked.
 * Usage: node tests/chart_viewer_fit.mjs   (needs playwright; PLAYWRIGHT_ROOT can point at it)
 * Prints "chart viewer fit ok" and exits 0 when every check passes.
 */
import fs from "fs";
import path from "path";
import { createRequire } from "module";
import { fileURLToPath, pathToFileURL } from "url";

const killer = setTimeout(() => { console.log("chart viewer fit: timed out"); process.exit(2); }, 420000);

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
const CV = JSON.parse(fs.readFileSync(path.join(ROOT, "config.json"), "utf8")).chart_viewer;
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

async function openPage(browser, c, narrowPx, theme) {
  const ctx = await browser.newContext({ userAgent: c.ua, viewport: { width: c.w, height: c.h }, isMobile: c.mobile, hasTouch: true, deviceScaleFactor: 2, colorScheme: theme === "light" ? "light" : "dark" });
  await ctx.addInitScript((opts) => {
    Object.defineProperty(navigator, "maxTouchPoints", { get: () => 5 });
    if (/Macintosh/.test(navigator.userAgent)) Object.defineProperty(navigator, "platform", { get: () => "MacIntel" });
    if (opts.theme) { try { localStorage.setItem("desk-theme", opts.theme); } catch (e) { /* ignore */ } }
    // Keep a handle on each chart the viewer makes, to read its visible range.
    window.__charts = [];
    let lc;
    Object.defineProperty(window, "LightweightCharts", { configurable: true, get: () => lc, set: (v) => {
      const make = v.createChart;
      lc = Object.assign({}, v, { createChart: function () { const ch = make.apply(this, arguments); window.__charts.push(ch); return ch; } });
    } });
    // Draw the chart only a few px wide (layout not done yet), to widen it later.
    if (opts.narrow) document.addEventListener("DOMContentLoaded", () => {
      const st = document.createElement("style");
      st.id = "narrow";
      st.textContent = "#cvchart{right:auto!important;width:" + opts.narrow + "px!important}";
      document.head.appendChild(st);
    });
  }, { narrow: narrowPx || 0, theme: theme || "" });
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
  const pxPerBar = v.plot / (v.to - v.from);
  const gap = v.plot * (v.to - (n - 1)) / (v.to - v.from);
  check(v.to >= n - 1, what + ": newest candle on screen");
  if (monthsWanted) {
    const want = V.rangeFrom(dates, monthsWanted);
    check(Math.abs(v.from - (want - 0.5)) <= 1, what + ": starts " + monthsWanted + " months back (from " + v.from.toFixed(1) + ")");
  } else if (CV.dense_default) {
    const r = V.denseRange(n - 1, v.plot, V.RIGHT_MARGIN_PX, CV.target_bar_spacing, CV.min_bar_spacing_px, CV.max_bar_spacing_px);
    check(Math.abs(v.from - r.from) <= 1.2 && Math.abs(v.to - r.to) <= 1.2, what + ": opens at the dense range (from " + v.from.toFixed(1) + ", want " + r.from.toFixed(1) + ")");
    check(Math.abs(pxPerBar - CV.target_bar_spacing) < 0.35, what + ": bar spacing " + pxPerBar.toFixed(2) + " px");
  }
  const share = (n - 1 - Math.max(v.from, 0)) / (v.to - v.from);
  check(share >= 0.34, what + ": candles use " + Math.round(share * 100) + "% of the width, not a narrow strip");
  check(share <= 0.999, what + ": a small gap left of the price axis");
  check(pxPerBar > CV.min_bar_spacing_px - 0.05, what + ": candles stay readable (" + pxPerBar.toFixed(2) + " px per bar)");
  check(gap > 6 && gap < 22, what + ": newest candle is " + gap.toFixed(1) + " px left of the price axis");
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
    // Right of the top-left Why box and in the price pane, so the drag lands on the chart.
    const y = box.y + box.h * 0.42;
    await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x: box.x + box.w * 0.62, y }] });
    for (let i = 1; i <= 12; i++) {
      await new Promise((r) => setTimeout(r, 70));
      await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x: box.x + box.w * (0.62 + (0.28 * i) / 12), y }] });
    }
    await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    await page.waitForTimeout(600);
    check((await page.$eval("#cvtk", (e) => e.textContent)) === ticker, L("drag") + ": a slow drag keeps the same stock");
    const panned = await view(page);
    check(panned.from < before.from - 5, L("drag") + ": the drag moved back in time (from " + before.from.toFixed(1) + " to " + panned.from.toFixed(1) + ")");
    const kept = async (step) => {
      const v = await view(page);
      // The chart library can nudge the left edge by a little more than one bar when it
      // fits a saved range to a new width. Two bars still catches a jump back to the first view.
      check(Math.abs(v.from - panned.from) <= 2 && Math.abs(v.to - panned.to) <= 2,
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
    // Daily | Weekly replaces the range chips. Weekly refits to its own span and drops the dragged range.
    await page.click('#cvtools [data-tf="weekly"]');
    await settle(page);
    const weekly = await page.evaluate(() => {
      const chart = window.__charts[window.__charts.length - 1];
      const ts = chart.timeScale();
      const lr = ts.getVisibleLogicalRange();
      const data = chart.panes()[0].getSeries()[0].data();
      return { from: lr.from, to: lr.to, plot: ts.width(), dates: data.map((d) => d.time) };
    });
    const wPx = weekly.plot / (weekly.to - weekly.from);
    check(weekly.dates.length < n / 3, L("Weekly") + ": " + weekly.dates.length + " weekly bars from " + n + " daily bars");
    check(Math.abs(wPx - CV.target_bar_spacing) < 0.35, L("Weekly") + ": same thickness as daily (" + wPx.toFixed(2) + " px)");
    check(weekly.to >= weekly.dates.length - 1, L("Weekly") + ": newest week on screen");
    const wGap = weekly.plot * (weekly.to - (weekly.dates.length - 1)) / (weekly.to - weekly.from);
    check(wGap > 6 && wGap < 22, L("Weekly") + ": newest bar is " + wGap.toFixed(1) + " px left of the price axis");
    await page.click('#cvtools [data-tf="daily"]');
    await settle(page);
    firstView(await view(page), dates, L("back to Daily"));
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

  // Why box, candle spot, chip bar, and both themes at the sizes Nick uses.
  const LAYOUTS = [
    { name: "iPhone 390", w: 390, h: 844, ua: IPHONE, mobile: true },
    { name: "iPad 820", w: 820, h: 1180, ua: IPAD, mobile: false },
    { name: "iPad 1180", w: 1180, h: 820, ua: IPAD, mobile: false },
  ];
  for (const theme of ["dark", "light"]) {
    for (const c of LAYOUTS) {
      const opened = await openPage(browser, c, 0, theme);
      const { page, errors } = opened;
      const L = (step) => c.name + " " + theme + " " + step;
      const spot = await page.evaluate(() => {
        const chart = window.__charts[window.__charts.length - 1];
        const ts = chart.timeScale();
        const lr = ts.getVisibleLogicalRange();
        const data = chart.panes()[0].getSeries()[0].data();
        const why = document.getElementById("cvwhy").getBoundingClientRect();
        const host = document.getElementById("cvchart").getBoundingClientRect();
        const tools = document.getElementById("cvtools").getBoundingClientRect();
        const doc = document.documentElement;
        const bar = document.getElementById("cvtools");
        return {
          from: lr.from, to: lr.to, plot: ts.width(), n: data.length,
          up: chart.panes()[0].getSeries()[0].options().upColor,
          why: { t: why.top, l: why.left, r: why.right, b: why.bottom },
          host: { t: host.top, l: host.left, r: host.right, b: host.bottom },
          toolsBottom: tools.bottom,
          psw: chart.priceScale("right").width(),
          pageOver: doc.scrollWidth - doc.clientWidth,
          toolsOver: bar.scrollWidth - bar.clientWidth,
          ranges: bar.querySelectorAll("[data-range]").length,
          theme: document.documentElement.getAttribute("data-theme"),
          cls: document.getElementById("cvwhy").className,
        };
      });
      const gap = spot.plot * (spot.to - (spot.n - 1)) / (spot.to - spot.from);
      const px = spot.plot / (spot.to - spot.from);
      check(spot.theme === theme, L("theme") + " is " + spot.theme);
      check(Math.abs(px - CV.target_bar_spacing) < 0.45, L("spacing") + " is " + px.toFixed(2) + " px");
      check(spot.cls.indexOf("tl") >= 0, L("why") + " is at the top left");
      check(spot.why.t >= spot.toolsBottom - 2, L("why") + " stays below the chips");
      check(spot.why.t <= spot.host.t + 16, L("why") + " starts at the top of the chart");
      check(spot.why.l <= spot.host.l + 16, L("why") + " starts at the left of the chart");
      check(spot.why.r < spot.host.r - spot.psw, L("why") + " does not cover the price axis");
      check(spot.why.b - spot.why.t < (spot.host.b - spot.host.t) * 0.5, L("why") + " stays compact");
      check(gap > 6 && gap < 22, L("candle") + " is " + gap.toFixed(1) + " px left of the price axis");
      check(spot.ranges === 0, L("ranges") + " are hidden");
      check(spot.toolsOver <= 1, L("chips") + " fit (" + spot.toolsOver + " px)");
      check(spot.pageOver <= 1, L("page") + " does not scroll sideways (" + spot.pageOver + " px)");
      const candleUp = theme === "light" ? "#137336" : "#22c55e";
      check(String(spot.up).toLowerCase() === candleUp, L("candles") + " stay green (" + spot.up + ")");
      await page.click('#cvtools [data-style="bars"]');
      await settle(page);
      const barsLook = await page.evaluate(() => {
        const chart = window.__charts[window.__charts.length - 1];
        const series = chart.panes()[0].getSeries()[0];
        const lr = chart.timeScale().getVisibleLogicalRange();
        return { up: String(series.options().upColor).toLowerCase(), down: String(series.options().downColor).toLowerCase(), n: series.data().length, to: lr.to };
      });
      const wantUp = theme === "light" ? "#1d4ed8" : "#60a5fa";
      const wantDn = theme === "light" ? "#a21caf" : "#d946ef";
      check(barsLook.up === wantUp && barsLook.down === wantDn, L("bars") + " colors " + barsLook.up + " " + barsLook.down);
      check(barsLook.n === spot.n && barsLook.to >= barsLook.n - 1, L("bars") + " keeps the daily bars");
      await page.click("#cvwhy");
      await settle(page);
      const open = await page.evaluate(() => {
        const why = document.getElementById("cvwhy");
        const host = document.getElementById("cvchart").getBoundingClientRect();
        const wr = why.getBoundingClientRect();
        const tools = document.getElementById("cvtools").getBoundingClientRect();
        const psw = window.__charts[window.__charts.length - 1].priceScale("right").width();
        return { open: why.classList.contains("open"), top: wr.top, right: wr.right, tools: tools.bottom, axis: host.right - psw };
      });
      check(open.open, L("why tap") + " reads the full reason");
      check(open.top >= open.tools - 2, L("why tap") + " still clears the chips");
      check(open.right < open.axis, L("why tap") + " still clears the price axis");
      await page.click('#cvtools [data-tf="weekly"]');
      await settle(page);
      const both = await page.evaluate(() => {
        const chart = window.__charts[window.__charts.length - 1];
        const series = chart.panes()[0].getSeries()[0];
        const lr = chart.timeScale().getVisibleLogicalRange();
        return { n: series.data().length, up: String(series.options().upColor).toLowerCase(), px: chart.timeScale().width() / (lr.to - lr.from) };
      });
      check(both.n < spot.n / 3, L("weekly bars") + " " + both.n + " from " + spot.n + " daily");
      check(both.up === wantUp, L("weekly bars") + " keep the bar colors");
      check(Math.abs(both.px - CV.target_bar_spacing) < 0.45, L("weekly spacing") + " is " + both.px.toFixed(2) + " px");
      check(errors.length === 0, L("errors") + ": " + errors.join("; "));
      await opened.ctx.close();
    }
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
