// Drives /command the way an operator does — Simulate Crisis → dialog → run —
// then waits for the impact graph, the candidate rail and the plan panel,
// screenshotting each beat and capturing every console error along the way.
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";

const OUT = process.env.SHOT_DIR;
mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch({ channel: "msedge", headless: true });
const page = await (await browser.newContext({ viewport: { width: 1600, height: 900 } })).newPage();
const errors = [];
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
page.on("pageerror", (e) => errors.push("PAGEERROR: " + String(e)));

await page.goto("http://localhost:3000/command", { waitUntil: "domcontentloaded", timeout: 90000 });
await page.waitForTimeout(4000);

await page.click('button:has-text("Simulate Crisis")');
await page.waitForSelector("text=Run a simulation", { timeout: 20000 });
const submit = page.locator('button:has-text("Run simulation")');
await submit.waitFor({ state: "visible", timeout: 30000 });
for (let i = 0; i < 30 && (await submit.isDisabled()); i++) await page.waitForTimeout(1000);
if (await submit.isDisabled()) throw new Error("Run simulation stayed disabled — vendor list never loaded");
await submit.click();
console.log("submitted");

async function beat(label, selector, timeout, shot) {
  try {
    await page.waitForSelector(selector, { timeout });
    console.log(`OK   ${label}`);
  } catch {
    console.log(`MISS ${label}`);
  }
  if (shot) {
    await page.waitForTimeout(2500);
    await page.screenshot({ path: `${OUT}/${shot}.png` });
  }
}

await beat("impact summary", "text=Impacted nodes", 300000, "1-impact");
await beat("candidate rail", "text=/Candidates|candidates/i", 300000, "2-candidates");
await beat("plan / payment split", "text=ONE PAYMENT", 300000, "3-plan");

console.log("errors:", JSON.stringify(errors.slice(0, 8), null, 1));
await browser.close();
