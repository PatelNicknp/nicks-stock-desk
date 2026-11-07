/* Browser checks: Overview opens Nick 360 in a new tab, screens and the paper log work, styles stay isolated. */
import http from "http";
import fs from "fs";
import path from "path";
import { createRequire } from "module";
import { fileURLToPath } from "url";

const require = createRequire(import.meta.url);

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function loadPlaywright() {
  const tries = ["playwright", process.env.PLAYWRIGHT_NODE_PATH, "/tmp/pw/node_modules/playwright"].filter(Boolean);
  for (const name of tries) {
    try { return require(name); } catch (err) { /* next */ }
  }
  return null;
}

function contentType(file) {
  if (file.endsWith(".html")) return "text/html; charset=utf-8";
  if (file.endsWith(".js")) return "text/javascript; charset=utf-8";
  if (file.endsWith(".css")) return "text/css; charset=utf-8";
  if (file.endsWith(".json")) return "application/json; charset=utf-8";
  if (file.endsWith(".csv")) return "text/csv; charset=utf-8";
  return "application/octet-stream";
}

function serve() {
  const server = http.createServer((req, res) => {
    const url = decodeURIComponent((req.url || "/").split("?")[0]);
    const file = path.normalize(path.join(root, url));
    if (!file.startsWith(root) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
      res.writeHead(404);
      res.end("missing");
      return;
    }
    res.writeHead(200, { "Content-Type": contentType(file) });
    fs.createReadStream(file).pipe(res);
  });
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve(server)));
}

function fail(msg) {
  console.error(msg);
  process.exit(1);
}

const pw = loadPlaywright();
if (!pw) {
  console.log("skip: playwright is not installed");
  process.exit(2);
}

const server = await serve();
const port = server.address().port;
const browser = await pw.chromium.launch({ args: ["--no-sandbox"] });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const deskErrors = [];
page.on("pageerror", (err) => deskErrors.push(String(err)));
await page.goto("http://127.0.0.1:" + port + "/site/index.html", { waitUntil: "domcontentloaded" });
await page.waitForSelector("#nick360-open", { timeout: 30000 });
const link = await page.$eval("#nick360-open", (el) => ({
  target: el.getAttribute("target"),
  rel: el.getAttribute("rel"),
  text: el.textContent.trim(),
  href: el.getAttribute("href"),
}));
if (link.target !== "_blank" || !String(link.rel).includes("noopener") || !String(link.rel).includes("noreferrer")) fail("new tab link is not safe: " + JSON.stringify(link));
if (link.text !== "Nick 360" || link.href !== "nick360/index.html") fail("overview button mismatch " + JSON.stringify(link));
const deskSheets = await page.evaluate(() => Array.from(document.styleSheets).map((s) => s.href || ""));
if (deskSheets.some((href) => href.includes("nick360.css"))) fail("Nick 360 CSS loaded on the stock box");
const h1 = await page.$eval("h1", (el) => getComputedStyle(el).fontFamily);
if (!h1) fail("desk heading missing");

const [popup] = await Promise.all([
  page.waitForEvent("popup"),
  page.click("#nick360-open"),
]);
const boxErrors = [];
popup.on("pageerror", (err) => boxErrors.push(String(err)));
await popup.waitForSelector("#n360[data-ready='1']", { timeout: 180000 });
await popup.setViewportSize({ width: 1440, height: 900 });
const brand = await popup.locator(".brand b").innerText();
if (brand !== "Nick 360") fail("brand " + brand);
const sheets = await popup.evaluate(() => Array.from(document.styleSheets).map((s) => s.href || ""));
if (sheets.some((href) => href.includes("desk.css"))) fail("desk.css loaded inside Nick 360");
if (!sheets.some((href) => href.includes("nick360.css"))) fail("nick360.css missing");
const pill = await popup.locator(".pill").innerText();
if (!pill.includes("NOT A LIVE FEED")) fail("pill " + pill);
if (await popup.locator("text=SPY Model 25").count()) fail("proprietary timing model was rendered");

const first = await popup.locator("#jump").inputValue();
const other = popup.locator(".srow").filter({ hasNotText: first }).first();
await other.click();
await popup.waitForFunction((prev) => document.querySelector("#jump") && document.querySelector("#jump").value !== prev, first);
const second = await popup.locator("#jump").inputValue();
if (!second || second === first) fail("symbol did not change");
const quote = await popup.locator(".quote").innerText();
if (!quote.includes(second) && !quote.includes("V/50d")) fail("quote missing volume reading");
if (!quote.includes("V/50d")) fail("relative volume label missing");

await popup.getByRole("button", { name: "Actions", exact: true }).click();
await popup.locator("#menu").waitFor({ state: "visible" });
if (!await popup.locator("#menu").innerText().then((t) => t.includes("Copy last price"))) fail("actions menu incomplete");
await popup.keyboard.press("Escape");
await popup.locator("#menu").waitFor({ state: "hidden" });

await popup.locator("canvas#cv").click({ button: "right", position: { x: 200, y: 240 } });
await popup.locator("#menu").waitFor({ state: "visible" });
await popup.keyboard.press("Escape");

await popup.locator(".tool").getByRole("button", { name: "Summary" }).click();
const summary = await popup.locator(".right").innerText();
if (!summary.includes("Not a language model")) fail("summary is not labeled as computed");
if (summary.includes("DESK AI") || summary.includes("Ask AI")) fail("fake AI label rendered");

await popup.getByRole("button", { name: "Alert Report", exact: true }).click();
if (!await popup.locator(".left").innerText().then((t) => t.includes("Alert report"))) fail("alert report did not open");

await popup.getByRole("button", { name: "Dashboard", exact: true }).click();
const dash = await popup.locator("#view").innerText();
if (!dash.includes("Market status") || !dash.includes("Our regime")) fail("dashboard missing regime");
if (dash.includes("SPY Model") || dash.includes("QQQ Model")) fail("dashboard copied a proprietary model name");

await popup.getByRole("button", { name: "Grader", exact: true }).click();
if (!await popup.locator("#view").innerText().then((t) => t.includes("Trade library"))) fail("grader missing trade library");

await popup.getByRole("button", { name: "Analytics", exact: true }).click();
const before = await popup.locator("#view").innerText();
if (!before.includes("YTD realized") || !before.includes("—")) fail("analytics invented a result before any fills");
await popup.getByRole("button", { name: "Add fill", exact: true }).click();
await popup.locator("#pt").fill("AAPL");
await popup.locator("#pd").fill("2026-01-05");
await popup.locator("#psh").fill("10");
await popup.locator("#pp").fill("100");
await popup.locator("#pst").fill("90");
await popup.locator("#psz").selectOption("full");
await popup.getByRole("button", { name: "Save fill", exact: true }).click();
await popup.getByRole("button", { name: "Dashboard", exact: true }).click();
const after = await popup.locator("#view").innerText();
if (!after.includes("AAPL") || !after.includes("Full positions")) fail("paper position did not group");

await popup.setViewportSize({ width: 390, height: 844 });
await popup.getByRole("button", { name: "Charting", exact: true }).click();
const overflow = await popup.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
if (overflow > 8) fail("phone overflow " + overflow);

if (deskErrors.length) fail("desk page error " + deskErrors[0]);
if (boxErrors.length) fail("nick360 page error " + boxErrors[0]);
await browser.close();
server.close();
console.log("nick360 ui ok");
