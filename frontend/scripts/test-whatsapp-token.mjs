import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const dir = path.dirname(fileURLToPath(import.meta.url));
const envPath = path.join(dir, "..", ".env.local");

function loadEnvLocal() {
  if (!existsSync(envPath)) return;
  const lines = readFileSync(envPath, "utf8").split("\n");
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq === -1) continue;
    const key = trimmed.slice(0, eq).trim();
    const value = trimmed.slice(eq + 1).trim();
    if (!(key in process.env)) process.env[key] = value;
  }
}

loadEnvLocal();

const token = process.env.WHATSAPP_ACCESS_TOKEN;
const GRAPH_VERSION = "v21.0";

if (!token) {
  console.error("WHATSAPP_ACCESS_TOKEN is not set (checked .env.local and process env).");
  process.exit(1);
}

function mask(t) {
  return `${t.slice(0, 6)}...${t.slice(-4)} (${t.length} chars)`;
}

async function main() {
  console.log(`Testing token: ${mask(token)}`);

  // 1. Basic identity check — works for any valid Graph API token
  const meRes = await fetch(`https://graph.facebook.com/${GRAPH_VERSION}/me?access_token=${encodeURIComponent(token)}`);
  const meBody = await meRes.json();

  if (!meRes.ok || meBody.error) {
    console.error("FAILED — token rejected by /me");
    console.error(JSON.stringify(meBody.error ?? meBody, null, 2));
    process.exit(1);
  }

  console.log("PASSED /me check:");
  console.log(JSON.stringify(meBody, null, 2));

  // 2. WhatsApp Business phone numbers this token can manage, if the
  //    identity above is a WhatsApp Business Account (WABA) or has one linked.
  //    Requires whatsapp_business_management permission; safe to fail quietly.
  if (meBody.id) {
    const waRes = await fetch(
      `https://graph.facebook.com/${GRAPH_VERSION}/${meBody.id}/phone_numbers?access_token=${encodeURIComponent(token)}`
    );
    const waBody = await waRes.json();
    if (waRes.ok && !waBody.error) {
      console.log("\nLinked WhatsApp phone numbers:");
      console.log(JSON.stringify(waBody, null, 2));
    } else {
      console.log("\n(No WhatsApp phone numbers endpoint access from this ID — expected if this token's id isn't a WABA.)");
    }
  }

  // 3. Direct lookup of a specific WhatsApp phone number ID, if provided.
  //    Read-only — confirms the token can see and manage this number.
  const phoneNumberId = process.env.WHATSAPP_PHONE_NUMBER_ID;
  if (phoneNumberId) {
    console.log(`\nLooking up phone number ID ${phoneNumberId}...`);
    const pnRes = await fetch(
      `https://graph.facebook.com/${GRAPH_VERSION}/${phoneNumberId}?fields=id,display_phone_number,verified_name,quality_rating,platform_type,throughput&access_token=${encodeURIComponent(
        token
      )}`
    );
    const pnBody = await pnRes.json();
    if (pnRes.ok && !pnBody.error) {
      console.log("PASSED phone number lookup:");
      console.log(JSON.stringify(pnBody, null, 2));
    } else {
      console.error("FAILED phone number lookup:");
      console.error(JSON.stringify(pnBody.error ?? pnBody, null, 2));
    }
  }
}

main().catch((err) => {
  console.error("FAILED — request error");
  console.error(err);
  process.exit(1);
});
