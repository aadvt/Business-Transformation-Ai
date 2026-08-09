# D7 Demo Runbook

## Start (two terminals + one browser profile)

```powershell
# Terminal 1 — backend
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# Terminal 2 — ngrok (static domain, so Bolna's webhook URL never changes)
ngrok http --url=affecting-gains-thinner.ngrok-free.dev 8000

# Terminal 3 — frontend
cd frontend
npm run dev        # http://localhost:3000

# Sanity before going on stage
cd backend; python scripts/warm_up.py
```

Bolna post-call webhook: `https://affecting-gains-thinner.ngrok-free.dev/api/v1/webhooks/bolna`
with header `X-Voice-Adapter-Secret: <BOLNA_WEBHOOK_SECRET from backend/.env>`.

Windows for the show: **`/command` full screen** (the whole demo lives here) +
**`/phone` in a separate narrow window** (the owner's phone). `/directory` is a
deliberate detour, opened once from the candidate rail's footer link.

## Pre-demo smoke check (~4 min, do this once before the room fills)

```powershell
cd frontend
$env:SHOT_DIR="$env:TEMP\sanjeevani-smoke"; node scripts/pipeline_watch.mjs
```

Drives a real run in headless Chromium — Simulate Crisis → dialog → impact
graph → candidates → payment split — and prints `OK`/`MISS` per beat plus any
console error. Three `OK`s and `errors: []` means the golden path is live.
Screenshots land in `$SHOT_DIR` if you want to eyeball them.

## The demo run (two operators)

| Beat | Console operator (/command) | Second operator |
|---|---|---|
| 0. Reset | Demo bar → **Reset demo** (bottom-left, hover to reveal) | — |
| 1. Trigger | **Simulate Crisis** → pick vendor → submit | — |
| 2. Impact→Plan | Narrate while graph animates → candidates slide in → plan diff with the **one-payment split** appears (~2 min pipeline; keep talking) | — |
| 3. Approval | Point at the phone window | Tap **Approve** on the approval card in `/phone` |
| 4. Call | Press **Call \<vendor\>** on the approval card. Briefing panel takes over the screen | **Click dial in Bolna's dashboard** (the screen shows a reminder chip) |
| 5. Listen | ~90s: audience listens; screen shows the briefing + guardrails | Vendor actor answers, quotes a price UNDER the guardrail shown on screen |
| 6. Reveal | Call ends → webhook lands → transcript + fields cascade (~8s), Guardian badge, exposure recomputes, stage → NEGOTIATED, payment split shows the agreed price | — |
| 7. Settle | `/settlement` → Confirm batch → Execute payout | — |

**Rehearsal without a phone call:** on the approval card choose
"rehearse with replay instead" (visible with `NEXT_PUBLIC_DEMO_CONTROLS=true`)
— it runs the identical pipeline off `fixtures/bolna_replay.json` ~8s after
you press it. The fixture's delivery date self-refreshes to "2 days from now".

**Vendor actor brief:** confirm availability of 500 units, open at a price
slightly over the target shown on the briefing panel, settle just **under the
MAX PRICE guardrail on screen**, promise 2-day delivery, give a UPI id. A
price *above* the guardrail is also a rehearsed story: the field goes red,
"above guardrail — needs review", and the stage deliberately does not advance.

## Offline fallback

Stop the server, set `DATABASE_URL=sqlite:///./fallback.db`, remove
`DATABASE_URL_DIRECT`, run `python -m app.seed --reset`, then restart Uvicorn.
This is a local rehearsal path and never alters Neon.

## Failure cues

| Failure | Action |
|---|---|
| ngrok URL changed | Update `.env` + Bolna webhook URL, rerun warm-up |
| Webhook never arrives | After 90s the call view offers **Replay last call** (also `R` in the demo bar); check `/api/v1/webhooks/bolna/health` and the ngrok inspector |
| Bolna call fails to connect | Switch to the replay path — identical on screen except the honest `source` field |
| Vendor doesn't answer | Same: replay |
| watsonx down | Set `LLM_PROVIDER=stub`; stub responses are demo-grade prose |
| Neon unreachable | SQLite fallback above |
| WebSocket drops | Refresh — `/command?call=<id>` and the ring buffer restore state |
| Sheet sync fails | `GET /api/v1/agent/vendor-sheet.csv` and paste into the sheet |
| TTM not loaded | Watchlist shows unavailable; scenario still runs |
| Wrong approval card tapped | Cards are per-disruption; tap the NEWEST card (bottom of the thread) |
| `POST /disruptions/simulate` reports an old stage | The disruption already progressed — **Reset demo** first, then trigger |
| Directory shows "GSTIN verified", not "Verified" | Correct and expected: GSTIN is an offline checksum we can always settle; Udyam needs a provider that isn't configured. Say so if asked — it's the honest badge |
| Trigger modal's vendor list is empty | `GET /simulate/targets` failed; check the backend log. It should answer in ~1.5s |
| Canvas shows a disruption you didn't trigger | `MOCK_LIVE_REPLAY` must be `false` in `backend/.env` — when on, it broadcasts a scripted fake disruption every 45s into the live feed |
| Candidate rail or plan never appears | Sourcing found nothing (check the SOURCING `agent_runs` row) — the rail is driven by a real `CANDIDATES_FOUND` from the pipeline |

## Known timings

- Simulate → AWAITING_APPROVAL: **~2 minutes** (real watsonx calls). Script the
  narration to cover it; the graph/candidates/plan animate in as they land.
- Replay button → reveal complete: ~8s delay + ~10s reveal.
- Neon cold start: first request after >5 min idle can take ~10s (keepalive
  normally prevents this while the server is up).
