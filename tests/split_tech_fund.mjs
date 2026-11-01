/**
 * Technical | Fundamental split in a real browser on the saved data: the menu headings, the Chart Viewer switch,
 * list filtering, the Why box, the remembered pick, and features.split_tech_fund off giving the old menu and viewer.
 * No clock, no network (pages and CSVs come from a local server). Prints "split tech fund ok".
 */
import fs from "fs";
import http from "http";
import path from "path";
import { fileURLToPath, pathToFileURL } from "url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
async function loadChromium() {
  try {
    return (await import("playwright")).chromium;
  } catch (err) {
    const pr = process.env.PLAYWRIGHT_ROOT;
    if (!pr) throw err;
    return (await import(pathToFileURL(path.join(pr, "index.mjs")).href)).chromium;
  }
}
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".csv": "text/csv", ".png": "image/png", ".webmanifest": "application/manifest+json" };
function serve() {
  const server = http.createServer((req, res) => {
    const url = decodeURIComponent((req.url || "/").split("?")[0]);
    const file = path.normalize(path.join(root, url));
    if (!file.startsWith(root) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404); res.end("missing"); return; }
    res.writeHead(200, { "Content-Type": TYPES[path.extname(file)] || "application/octet-stream" });
    fs.createReadStream(file).pipe(res);
  });
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve(server)));
}

const fails = [];
function eq(got, want, what) {
  const a = JSON.stringify(got), b = JSON.stringify(want);
  if (a !== b) fails.push(what + ": got " + a + " want " + b);
}
const OLD_NAV = ["Overview", "Chart Viewer", "Scanners", "Options", "Earnings", "Sentiment", "Financials", "Macro", "Technicals", "System"];
const NEW_NAV = ["Overview", "Chart Viewer", "Technical", "Fundamental", "Options", "Earnings", "Sentiment", "Financials", "Macro", "Market", "System"];
const TECH = ["VCP", "Box breakout", "Flag breakout", "Qullamaggie breakout", "Marios breakout", "Episodic pivot", "Gap Up", "52-week",
  "52-week breakouts", "High volume", "Pullbacks", "Breakdowns", "Trends", "Wheel (stocks only)"];
const FUND = ["CANSLIM", "Leaders", "Growth", "Quality", "Dividend", "Stock scorecard", "Top stocks"];
const TECH_LISTS = ["vcp", "box", "flag", "qullamaggie", "marios", "ep", "gapup", "breakdowns", "volume", "week52", "wheel"];
const FUND_LISTS = ["canslim", "leaders", "growth", "quality", "dividend"];
const TECH_SHORT = ["VCP", "Box", "Flag", "Qullamaggie", "Marios", "EP", "Gap Up", "Breakdown", "High volume", "52-week", "Wheel"];
const FUND_SHORT = ["CANSLIM", "Leaders", "Growth", "Quality", "Dividend"];
const BOTH_SHORT = ["Buy setup", "Watchlist"];

async function open(ctx, url) {
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e.message || e)));
  await page.goto(url, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("body[data-ready='1'], body[data-ready='error']", { timeout: 30000 });
  await page.waitForTimeout(200);
  page._errors = errors;
  return page;
}
const navNames = (page) => page.$$eval("#nav .grp", (bs) => bs.map((b) => b.textContent.replace(/[▾▸]/g, "").replace(/\d+$/, "").trim()));
const options = (page) => page.$$eval("#cvlist option", (os) => os.map((o) => ({ v: o.value, t: o.textContent })));
const groupOn = (page) => page.$eval("#cvgroup button.on", (b) => b.textContent);
async function whyLabels(page, steps) {
  const seen = new Set();
  for (let i = 0; i < steps; i++) {
    const open = await page.$eval("#cvwhy", (w) => w.classList.contains("open"));
    if (!open) await page.click("#cvwhy");
    (await page.$$eval("#cvwhy .cv-why-l", (ls) => ls.map((l) => l.textContent))).forEach((l) => seen.add(l));
    await page.click("#cvnext");
    await page.waitForTimeout(60);
  }
  return Array.from(seen);
}

async function main() {
  let chromium;
  try { chromium = await loadChromium(); } catch (err) { console.log("skip: playwright is not installed"); process.exit(2); }
  const server = await serve();
  const base = "http://127.0.0.1:" + server.address().port + "/site/";
  const browser = await chromium.launch({ args: ["--no-sandbox"] });
  const counts = {};
  try {
    // ---- Split on (the published settings) ----
    let ctx = await browser.newContext({ viewport: { width: 1180, height: 820 } });
    let page = await open(ctx, base + "vcp.html");
    eq(await navNames(page), NEW_NAV, "menu headings with the split on");
    const groups = await page.evaluate(() => window.Desk.navGroups().map((g) => [g[0], g[1].map((it) => it[0])]));
    const g = Object.fromEntries(groups);
    eq(g.Technical, TECH, "Technical heading pages");
    eq(g.Fundamental, FUND, "Fundamental heading pages");
    eq(g.Overview, ["Today", "Buy setups", "Watchlist and portfolio", "Alerts", "Backtest"], "non-screener pages stay in Overview");
    eq(g.Market, ["Gainers and losers", "Breadth", "Sector performance", "Heatmaps"], "market pages stay outside both");
    eq(g.Options, ["Debit spreads"], "Options stays outside both");
    eq(await page.$$eval("#nav .group[data-open='1'] .grp", (b) => b.map((x) => x.textContent.replace(/[▾▸]/g, "").replace(/\d+$/, "").trim())), ["Technical"], "VCP page opens the Technical heading");
    eq(await page.$("#about .about-title") !== null, true, "VCP keeps its description box");
    await page.close();
    for (const name of ["canslim.html", "leaders.html", "growth.html", "gap-up.html", "breakdowns.html", "wheel.html", "pullbacks.html", "breakouts.html", "trends.html"]) {
      page = await open(ctx, base + name);
      eq([name, await page.$("#about .about-title") !== null, page._errors.length], [name, true, 0], "description box and no errors");
      await page.close();
    }

    // Chart Viewer: a new device starts on Technical.
    page = await open(ctx, base + "chart-viewer.html");
    eq(await page.$$eval("#cvgroup button", (bs) => bs.map((b) => b.textContent)), ["Technical", "Fundamental"], "switch buttons");
    eq(await groupOn(page), "Technical", "a new device starts on Technical");
    let opts = await options(page);
    eq(/^All technical stocks \(\d+\)$/.test(opts[0].t), true, "All technical stocks is first: " + opts[0].t);
    counts.technical = Number(/\((\d+)\)/.exec(opts[0].t)[1]);
    eq(opts.slice(1).every((o) => TECH_LISTS.concat(["buysetups", "watchlist"]).includes(o.v)), true, "technical picker shows only technical lists");
    eq(opts.some((o) => FUND_LISTS.includes(o.v)), false, "no fundamental list on the technical side");
    eq(new URL(page.url()).searchParams.get("group"), "technical", "address carries the side");
    let labels = await whyLabels(page, 12);
    eq(labels.filter((l) => !TECH_SHORT.concat(BOTH_SHORT).includes(l)), [], "technical Why box shows only technical reasons");
    eq(await page.evaluate(() => document.querySelector("#cvsum").textContent.startsWith("All technical stocks:")), true, "summary names the side");
    // Other viewer tools still work: MA chip, range chip, arrows.
    const ma = await page.$eval('#cvtools [data-ma="20"]', (b) => b.getAttribute("aria-pressed"));
    await page.click('#cvtools [data-ma="20"]');
    eq(await page.$eval('#cvtools [data-ma="20"]', (b) => b.getAttribute("aria-pressed")), ma === "true" ? "false" : "true", "MA chip still toggles");
    await page.click('#cvtools [data-range="1y"]');
    eq(await page.$eval('#cvtools [data-range="1y"]', (b) => b.getAttribute("aria-pressed")), "true", "range chip still works");

    // Switch to Fundamental: picker, All, Why box, saved pick.
    await page.click('#cvgroup [data-group="fundamental"]');
    await page.waitForTimeout(100);
    eq(await groupOn(page), "Fundamental", "switch moves to Fundamental");
    eq(await page.evaluate(() => localStorage.getItem("desk-cv-group")), "fundamental", "the pick is saved on the device");
    opts = await options(page);
    eq(/^All fundamental stocks \(\d+\)$/.test(opts[0].t), true, "All fundamental stocks is first: " + opts[0].t);
    counts.fundamental = Number(/\((\d+)\)/.exec(opts[0].t)[1]);
    eq(opts.slice(1).every((o) => FUND_LISTS.concat(["buysetups", "watchlist"]).includes(o.v)), true, "fundamental picker shows only fundamental lists");
    eq(opts.some((o) => TECH_LISTS.includes(o.v)), false, "no technical list on the fundamental side");
    eq(await page.$eval("#cvcount", (c) => / of (\d+)$/.exec(c.textContent)[1]), String(counts.fundamental), "counter follows the new list");
    labels = await whyLabels(page, 12);
    eq(labels.filter((l) => !FUND_SHORT.concat(BOTH_SHORT).includes(l)), [], "fundamental Why box shows only fundamental reasons");
    eq(labels.some((l) => FUND_SHORT.includes(l)), true, "fundamental reasons are there");
    await page.close();

    // Remembered: a plain visit opens Fundamental; a VCP link opens Technical; Buy setups keeps the saved side.
    page = await open(ctx, base + "chart-viewer.html");
    eq(await groupOn(page), "Fundamental", "the last pick is remembered");
    await page.close();
    page = await open(ctx, base + "chart-viewer.html?list=vcp");
    eq([await groupOn(page), await page.$eval("#cvlist", (s) => s.value)], ["Technical", "vcp"], "a VCP link opens the Technical side on VCP");
    await page.close();
    page = await open(ctx, base + "chart-viewer.html?list=canslim");
    eq([await groupOn(page), await page.$eval("#cvlist", (s) => s.value)], ["Fundamental", "canslim"], "a CANSLIM link opens the Fundamental side");
    await page.click('#cvgroup [data-group="technical"]');
    eq(await page.$eval("#cvlist", (s) => s.value), "all", "switching away from CANSLIM goes to All technical stocks");
    await page.selectOption("#cvlist", "buysetups");
    await page.click('#cvgroup [data-group="fundamental"]');
    eq(await page.$eval("#cvlist", (s) => s.value), "buysetups", "Buy setups stays picked on both sides");
    eq(page._errors, [], "no page errors on the viewer");
    await page.close();
    await ctx.close();

    // Light mode and an iPhone still show the switch, full width, without sideways scroll.
    ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
    await ctx.addInitScript(() => { try { localStorage.setItem("desk-theme", "light"); } catch (e) { /* ignore */ } });
    page = await open(ctx, base + "chart-viewer.html");
    const phone = await page.evaluate(() => ({
      theme: document.documentElement.getAttribute("data-theme"),
      overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      seg: Math.round(document.querySelector("#cvgroup").getBoundingClientRect().width),
      pick: Math.round(document.querySelector(".cvpick").getBoundingClientRect().width),
    }));
    eq([phone.theme, phone.overflow <= 1, Math.abs(phone.seg - phone.pick) <= 2], ["light", true, true], "iPhone light mode switch " + JSON.stringify(phone));
    await page.close();
    await ctx.close();

    // ---- Split off: exactly the old menu and viewer ----
    const settings = fs.readFileSync(path.join(root, "data", "settings.csv"), "utf8").replace("feature.split_tech_fund,True", "feature.split_tech_fund,False");
    ctx = await browser.newContext({ viewport: { width: 1180, height: 820 } });
    await ctx.route("**/data/settings.csv", (route) => route.fulfill({ status: 200, contentType: "text/csv", body: settings }));
    await ctx.addInitScript(() => { try { localStorage.setItem("desk-cv-group", "fundamental"); } catch (e) { /* ignore */ } });
    page = await open(ctx, base + "chart-viewer.html?list=canslim");
    eq(await navNames(page), OLD_NAV, "split off: the old menu headings");
    const oldGroups = await page.evaluate(() => JSON.stringify(window.Desk.navGroups()));
    eq(oldGroups.includes('"Technical"') || oldGroups.includes('"Fundamental"') || oldGroups.includes('"Market"'), false, "split off: no new headings");
    eq(await page.$("#cvgroup"), null, "split off: no switch");
    opts = await options(page);
    eq(/^All scanner stocks \(\d+\)$/.test(opts[0].t), true, "split off: All scanner stocks " + opts[0].t);
    counts.off = Number(/\((\d+)\)/.exec(opts[0].t)[1]);
    eq(opts.some((o) => o.v === "vcp") && opts.some((o) => o.v === "canslim"), true, "split off: both kinds of list in one picker");
    eq(await page.$eval("#cvlist", (s) => s.value), "canslim", "split off: list from the address");
    eq(new URL(page.url()).searchParams.has("group"), false, "split off: no side in the address");
    eq(await page.$eval("#about p", (p) => p.textContent.includes("All scanner stocks puts every stock")), true, "split off: old description");
    eq(page._errors, [], "split off: no page errors");
    await page.close();
    // group_toggle off with the split on: the menu is split, the viewer is the old single one.
    await ctx.unroute("**/data/settings.csv");
    const noToggle = fs.readFileSync(path.join(root, "data", "settings.csv"), "utf8").replace("chart_viewer.group_toggle,True", "chart_viewer.group_toggle,False");
    await ctx.route("**/data/settings.csv", (route) => route.fulfill({ status: 200, contentType: "text/csv", body: noToggle }));
    page = await open(ctx, base + "chart-viewer.html");
    eq([await page.$("#cvgroup"), (await options(page))[0].t.startsWith("All scanner stocks"), (await navNames(page)).includes("Technical")], [null, true, true], "group_toggle off: old viewer, split menu");
    await page.close();
    await ctx.close();
  } finally {
    await browser.close();
    server.close();
  }
  if (fails.length) {
    console.log(fails.join("\n"));
    process.exit(1);
  }
  console.log("counts " + JSON.stringify(counts));
  console.log("split tech fund ok");
}
main().catch((err) => { console.error(err); process.exit(1); });
