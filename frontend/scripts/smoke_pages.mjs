// Loads every demo page and reports console errors. Fast sanity check that
// no page is broken; pipeline_watch.mjs is the deeper golden-path check.
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";

const OUT = process.env.SHOT_DIR;
mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch({ channel: "msedge", headless: true });
const page = await (await browser.newContext({ viewport: { width: 1600, height: 900 } })).newPage();

for (const path of ["/command", "/phone", "/settlement", "/directory", "/network", "/waterfall", "/"]) {
  const errors = [];
  const onErr = (m) => m.type() === "error" && errors.push(m.text());
  const onPageErr = (e) => errors.push("PAGEERROR: " + String(e));
  page.on("console", onErr);
  page.on("pageerror", onPageErr);
  await page.goto(`http://localhost:3000${path}`, { waitUntil: "domcontentloaded", timeout: 90000 });
  await page.waitForTimeout(7000);
  await page.screenshot({ path: `${OUT}/page${path.replace(/\//g, "_") || "_root"}.png` });
  console.log(`${errors.length === 0 ? "OK  " : "ERR "} ${path} ${errors.slice(0, 3).join(" | ")}`);
  page.off("console", onErr);
  page.off("pageerror", onPageErr);
}
await browser.close();
