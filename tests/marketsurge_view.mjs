/**
 * MarketSurge-style Chart Viewer in a real headless browser, light mode. Files are served from this checkout (nothing goes
 * to the network); scores.csv gets a made-up composite_rating for one stock and settings.csv is edited per case.
 * Checks the Comp chip after RS and EPS, price bars first, blue up / red down, 50-day red and 200-day black, the red
 * volume average line, the base overlay and its caption, the Patterns chip, Weekly 10 and 40-week lines, and every switch off.
 * Usage: node tests/marketsurge_view.mjs   (needs playwright; PLAYWRIGHT_ROOT can point at it)
 * Prints "marketsurge view ok" and exits 0 when every check passes.
 */
import fs from "fs";
import path from "path";
import { fileURLToPath, pathToFileURL } from "url";

const killer = setTimeout(() => { console.log("marketsurge view: timed out"); process.exit(2); }, 300000);
async function loadChromium() {
  try { return (await import("playwright")).chromium; } catch (err) {
    const root = process.env.PLAYWRIGHT_ROOT;
    if (!root) throw err;
    return (await import(pathToFileURL(path.join(root, "index.mjs")).href)).chromium;
  }
}
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const BASE = "http://desk.test/";
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".csv": "text/csv", ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml", ".webmanifest": "application/manifest+json" };
const fails = [];
const check = (ok, what) => { if (!ok) fails.push(what); };

// A stock whose newest base is live (not COMPLETED), plus a made-up Comp rating, EPS, and RS for it.
const rows = fs.readFileSync(path.join(ROOT, "data", "base_patterns.csv"), "utf8").trim().split("\n");
const head = rows[0].split(",");
const col = (r, n) => r.split(",")[head.indexOf(n)];
const pick = rows.slice(1).find((r) => col(r, "latest") === "yes" && col(r, "status") === "BUY ZONE" && col(r, "pattern") !== "ipo_base");
const T = col(pick, "ticker");

function withSettings(over) {
  const lines = fs.readFileSync(path.join(ROOT, "data", "settings.csv"), "utf8").split("\n").filter((l) => {
    const k = l.split(",")[0];
    return !(k in over);
  });
  Object.keys(over).forEach((k) => lines.push(k + "," + over[k]));
  return lines.join("\n");
}

async function open(browser, over, extra) {
  const ctx = await browser.newContext({ viewport: { width: 1300, height: 1100 }, deviceScaleFactor: 1 });
  await ctx.addInitScript(() => {
    try { localStorage.setItem("desk-theme", "light"); } catch (e) { /* ignore */ }
    window.__charts = [];
    let lc;
    Object.defineProperty(window, "LightweightCharts", { configurable: true, get: () => lc, set: (v) => {
      const make = v.createChart;
      lc = Object.assign({}, v, { createChart: function () { const ch = make.apply(this, arguments); window.__charts.push(ch); return ch; } });
    } });
  });
  const page = await ctx.newPage();
  const errors = [];
  const outside = { n: 0 };
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.route("**/*", (route) => {
    const url = route.request().url();
    if (!url.startsWith(BASE)) { outside.n++; return route.abort(); }
    const u = new URL(url);
    const rel = decodeURIComponent(u.pathname).replace(/^\/+/, "");
    if (rel === "data/settings.csv") return route.fulfill({ status: 200, contentType: "text/csv", body: withSettings(over || {}) });
    if (rel === "data/scores.csv") {
      const text = fs.readFileSync(path.join(ROOT, "data", "scores.csv"), "utf8");
      const body = extra && extra.scores ? extra.scores(text) : text;
      return route.fulfill({ status: 200, contentType: "text/csv", body });
    }
    const file = path.join(ROOT, rel);
    if (!file.startsWith(ROOT) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) return route.fulfill({ status: 404, body: "" });
    return route.fulfill({ status: 200, contentType: TYPES[path.extname(file)] || "application/octet-stream", body: fs.readFileSync(file) });
  });
  await page.goto(BASE + "site/chart-viewer.html?list=all&t=" + T, { waitUntil: "load" });
  await page.waitForFunction((t) => window.__charts.length && document.querySelector("#cvtk") && document.querySelector("#cvtk").textContent === t, T, { timeout: 30000 });
  await page.waitForTimeout(800);
  return { ctx, page, errors, outside };
}

// scores.csv with composite_rating set to 91 for the picked stock (the committed file may not have the column until the next run).
function addComp(text) {
  const lines = text.split("\n");
  const hdr = lines[0].split(",");
  if (hdr.indexOf("composite_rating") >= 0) return text;
  // Put the new column just after eps_rating by editing the header and the one stock's row with a real CSV split.
  const at = hdr.indexOf("eps_rating") + 1;
  hdr.splice(at, 0, "composite_rating");
  const out = [hdr.join(",")];
  let record = "";
  for (let i = 1; i < lines.length; i++) {
    record = record ? record + "\n" + lines[i] : lines[i];
    if ((record.match(/"/g) || []).length % 2) continue;
    const cells = splitCsv(record);
    cells.splice(at, 0, cells[1] === T ? "91" : "");
    out.push(cells.map((c) => (/[",\n]/.test(c) ? '"' + c.replace(/"/g, '""') + '"' : c)).join(","));
    record = "";
  }
  return out.join("\n");
}
function splitCsv(line) {
  const cells = [];
  let cur = "", q = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (q) { if (ch === '"' && line[i + 1] === '"') { cur += '"'; i++; } else if (ch === '"') q = false; else cur += ch; }
    else if (ch === '"') q = true;
    else if (ch === ",") { cells.push(cur); cur = ""; }
    else cur += ch;
  }
  cells.push(cur);
  return cells;
}

const info = (page) => page.evaluate(() => {
  const ch = window.__charts[window.__charts.length - 1];
  const p0 = ch.panes()[0].getSeries();
  const p1 = ch.panes()[1] ? ch.panes()[1].getSeries() : [];
  const price = p0[0];
  const lines = p0.filter((s) => s.seriesType() === "Line");
  return {
    type: price.seriesType(), priceOpts: price.options(), p1: p1.map((s) => s.seriesType()),
    lineColors: lines.map((s) => s.options().color),
    chips: [...document.querySelectorAll("#cvtools .cvchip")].map((b) => b.textContent.trim() + (b.hidden ? "(hidden)" : "")),
    comp: (document.getElementById("cvcomp") || {}).textContent, compHot: document.getElementById("cvcomp") ? document.getElementById("cvcomp").classList.contains("hot") : null,
    compHidden: document.getElementById("cvcomp") ? document.getElementById("cvcomp").hidden : null,
    bases: document.getElementById("cvchart").getAttribute("data-bases"),
    note: document.getElementById("cvpatnote") ? { hidden: document.getElementById("cvpatnote").hidden, text: document.getElementById("cvpatnote").textContent } : null,
    bg: getComputedStyle(document.documentElement).getPropertyValue("--bg"),
  };
});

const chromium = await loadChromium();
const browser = await chromium.launch();
try {
  // 1. Everything on (the shipped config).
  {
    const { ctx, page, errors, outside } = await open(browser, {}, { scores: addComp });
    const a = await info(page);
    check(a.type === "Bar", "first view is price bars (" + a.type + ")");
    check(a.priceOpts.upColor === "#1d4ed8" && a.priceOpts.downColor === "#dc2626", "blue up, red down on white (" + a.priceOpts.upColor + " " + a.priceOpts.downColor + ")");
    check(a.comp === "Comp 91" && a.compHot === true && a.compHidden === false, "Comp chip 91 is green: " + a.comp);
    const order = a.chips.filter((c) => /^(RS|EPS|Comp) \d+/.test(c)).map((c) => c.split(" ")[0]);
    check(order.indexOf("Comp") === order.length - 1 && (order.indexOf("EPS") < 0 || order.indexOf("EPS") < order.indexOf("Comp")), "Comp sits after RS and EPS: " + order);
    check(a.lineColors.includes("#dc2626") && a.lineColors.includes("#111827"), "50-day red and 200-day black: " + a.lineColors);
    check(a.p1.length === 2 && a.p1[1] === "Line", "volume pane has the bars and the red average line: " + a.p1);
    check(Number(a.bases) >= 1, "base overlay drawn: " + a.bases);
    check(a.note && a.note.hidden === false && /Pivot \d/.test(a.note.text) && /buy zone/.test(a.note.text), "caption under the chart: " + (a.note && a.note.text));
    check(a.chips.includes("Patterns"), "Patterns chip is there");
    // Patterns chip turns the overlay and caption off.
    await page.click('#cvtools [data-tool="pat"]'); await page.waitForTimeout(900);
    const b = await info(page);
    check(Number(b.bases) === 0 && b.note.hidden === true, "Patterns chip hides the overlay and caption");
    await page.click('#cvtools [data-tool="pat"]'); await page.waitForTimeout(900);
    check(Number((await info(page)).bases) >= 1, "Patterns chip brings it back");
    // Weekly: the 50, 150, 200-day lines are 10, 30, 40 weeks; the chips say so.
    await page.click('#cvtools [data-tf="weekly"]'); await page.waitForTimeout(1200);
    const w = await page.evaluate(() => [...document.querySelectorAll("#cvtools [data-ma] .cvl")].map((e) => e.textContent));
    check(w.includes("MA 10w") && w.includes("MA 40w"), "weekly chips: " + w);
    await page.click('#cvtools [data-tf="daily"]'); await page.waitForTimeout(900);
    // Candles keep the blue and red.
    await page.click('#cvtools [data-style="candles"]'); await page.waitForTimeout(900);
    const c = await info(page);
    check(c.type === "Candlestick" && c.priceOpts.upColor === "#1d4ed8" && c.priceOpts.downColor === "#dc2626", "candles are blue and red too");
    check(errors.length === 0, "no page errors: " + errors.join(" | "));
    check(outside.n === 0, "no network outside the checkout: " + outside.n);
    await ctx.close();
  }
  // 2. Each switch off on its own.
  const offs = [
    ["chart_viewer.comp_chip", (a) => a.comp === undefined, "Comp chip off"],
    ["chart_viewer.patterns", (a) => Number(a.bases || 0) === 0 && (a.note === null || a.note.hidden) && !a.chips.includes("Patterns"), "patterns off"],
    ["chart_viewer.volume_avg_line", (a) => a.p1.length === 1, "volume average line off"],
    ["chart_viewer.ms_look", (a) => a.type === "Candlestick" && a.priceOpts.upColor !== "#1d4ed8" && !a.lineColors.includes("#111827"), "MarketSurge look off"],
    ["chart_viewer.pattern_caption", (a) => a.note === null && Number(a.bases) >= 1, "caption off"],
    ["feature.base_patterns", (a) => Number(a.bases || 0) === 0, "base patterns feature off"],
  ];
  for (const [key, ok, what] of offs) {
    const { ctx, page, errors } = await open(browser, { [key]: "False" }, { scores: addComp });
    const a = await info(page);
    check(ok(a), what + " (" + JSON.stringify({ type: a.type, comp: a.comp, bases: a.bases, p1: a.p1, note: !!a.note }) + ")");
    check(errors.length === 0, what + ": no page errors " + errors.join(" | "));
    await ctx.close();
  }
  // 3. A stock with no Composite Rating has no chip.
  {
    const { ctx, page } = await open(browser, {}, { scores: (t) => t });
    const a = await info(page);
    check(a.compHidden === true || a.comp === undefined || a.comp === "", "no chip without a Composite Rating: " + a.comp);
    await ctx.close();
  }
} finally {
  await browser.close();
  clearTimeout(killer);
}
if (fails.length) { console.log("marketsurge view FAILED:\n- " + fails.join("\n- ")); process.exit(1); }
console.log("marketsurge view ok");
