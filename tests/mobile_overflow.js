/* Every site page at a 390px phone width must not scroll sideways. */
const http = require("http");
const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");

function loadPlaywright() {
  const tries = ["playwright", process.env.PLAYWRIGHT_NODE_PATH, "/tmp/pw/node_modules/playwright"].filter(Boolean);
  for (const name of tries) {
    try { return require(name); } catch (e) { /* next */ }
  }
  return null;
}

function contentType(file) {
  if (file.endsWith(".html")) return "text/html; charset=utf-8";
  if (file.endsWith(".js")) return "text/javascript; charset=utf-8";
  if (file.endsWith(".css")) return "text/css; charset=utf-8";
  if (file.endsWith(".csv")) return "text/csv; charset=utf-8";
  if (file.endsWith(".png")) return "image/png";
  if (file.endsWith(".webmanifest")) return "application/manifest+json";
  if (file.endsWith(".svg")) return "image/svg+xml";
  if (file.endsWith(".gz")) return "application/gzip";
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
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => resolve(server));
  });
}

async function main() {
  const pw = loadPlaywright();
  if (!pw) {
    console.log("skip: playwright is not installed");
    process.exit(2);
  }
  const pages = fs.readdirSync(path.join(root, "site")).filter((n) => n.endsWith(".html")).sort();
  const server = await serve();
  const port = server.address().port;
  const browser = await pw.chromium.launch({ args: ["--no-sandbox"] });
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const bad = [];
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e.message || e)));
  for (const name of pages) {
    errors.length = 0;
    await page.goto("http://127.0.0.1:" + port + "/site/" + name, { waitUntil: "domcontentloaded" });
    await page.waitForSelector("body[data-ready='1'], body[data-ready='error']", { timeout: 20000 });
    await page.waitForTimeout(250);
    const info = await page.evaluate(() => {
      const doc = document.documentElement;
      const menu = document.querySelector(".menu-btn");
      const menuStyle = menu ? getComputedStyle(menu).display : "missing";
      return {
        overflow: doc.scrollWidth - doc.clientWidth,
        scrollWidth: doc.scrollWidth,
        clientWidth: doc.clientWidth,
        ready: document.body.dataset.ready,
        menu: menuStyle,
      };
    });
    if (info.overflow > 1 || info.ready !== "1" || info.menu === "none" || info.menu === "missing") {
      bad.push(name + " overflow=" + info.overflow + " ready=" + info.ready + " menu=" + info.menu + (errors.length ? " err=" + errors[0] : ""));
    }
  }
  const wide = await browser.newPage({ viewport: { width: 1180, height: 820 } });
  await wide.goto("http://127.0.0.1:" + port + "/site/index.html", { waitUntil: "domcontentloaded" });
  await wide.waitForSelector("body[data-ready='1']", { timeout: 20000 });
  const rail = await wide.evaluate(() => {
    const menu = getComputedStyle(document.querySelector(".menu-btn")).display;
    const nav = getComputedStyle(document.querySelector(".nav")).position;
    return { menu: menu, nav: nav };
  });
  if (rail.menu !== "none" || rail.nav === "fixed") {
    bad.push("iPad landscape should keep the side rail, menu=" + rail.menu + " nav=" + rail.nav);
  }
  await browser.close();
  server.close();
  if (bad.length) {
    console.log(bad.join("\n"));
    process.exit(1);
  }
  console.log(pages.length + " pages fit at 390px, and iPad landscape keeps the rail");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
