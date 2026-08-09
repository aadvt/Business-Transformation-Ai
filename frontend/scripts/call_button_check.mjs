// Reproduces the operator's path past approval: run the pipeline, approve it
// the way the owner would (the /phone tap hits this same endpoint), then
// assert the "Call vendor" button is actually on screen and clickable.
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";

const OUT = process.env.SHOT_DIR;
const API = "http://localhost:8000";
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
for (let i = 0; i < 30 && (await submit.isDisabled()); i++) await page.waitForTimeout(1000);
await submit.click();

await page.waitForSelector("text=ONE PAYMENT", { timeout: 300000 });
console.log("plan on screen");
await page.waitForTimeout(2000);
await page.screenshot({ path: `${OUT}/a-plan.png` });

// Approve exactly as the owner's WhatsApp tap does.
const list = await (await fetch(`${API}/api/v1/disruptions`)).json();
const pending = [];
for (const d of list.items) {
  const detail = await (await fetch(`${API}/api/v1/disruptions/${d.id}`)).json();
  if (detail.approval && detail.approval.status === "PENDING") pending.push(detail);
}
// /disruptions is newest-first, so pending[0] is the run we just triggered —
// the page ignores APPROVAL_DECIDED for any other disruption, by design.
const target = pending[0];
if (!target) throw new Error("no pending approval to act on");
console.log("approving:", target.headline.slice(0, 60));
const res = await fetch(`${API}/api/v1/approvals/${target.approval.id}/decision`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    decision: "APPROVE",
    channel: "WHATSAPP",
    decided_by: "owner@demo",
    idempotency_key: `layout-check-${Date.now()}`,
  }),
});
console.log("approved:", res.status);

const call = page.locator('button:has-text("Call ")').first();
try {
  await call.waitFor({ state: "visible", timeout: 30000 });
  const box = await call.boundingBox();
  const onScreen = box && box.x >= 0 && box.y >= 0 && box.x + box.width <= 1600 && box.y + box.height <= 900;
  console.log(`CALL BUTTON: visible=true onScreen=${onScreen} at x=${Math.round(box.x)} y=${Math.round(box.y)} w=${Math.round(box.width)}`);
  // Is anything covering it? elementFromPoint at its centre should be the button.
  const covered = await page.evaluate(({ x, y, width, height }) => {
    const el = document.elementFromPoint(x + width / 2, y + height / 2);
    return el ? `${el.tagName} "${(el.textContent || "").trim().slice(0, 30)}"` : "none";
  }, box);
  console.log("topmost element at button centre:", covered);
} catch {
  console.log("CALL BUTTON: NOT FOUND");
}
await page.waitForTimeout(1500);
await page.screenshot({ path: `${OUT}/b-after-approval.png` });
console.log("errors:", JSON.stringify(errors.slice(0, 5)));
await browser.close();
