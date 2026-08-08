# Voice Channel Test Plan

`tests/test_voice_adapter.py` and `tests/test_voice_nlu.py` cover everything
the adapter does mechanically — selection parsing, the select→confirm gate,
PIN retry, disambiguation, audit tagging, hangup-leaves-things-parked — with
`TestClient` driving `voice/adapter.py` exactly the way Bolna's tool
webhooks would (same request shapes, same headers), against a real `api.py`
instance underneath. What that setup **cannot** exercise is a real phone
call: whether Bolna's STT hears the caller correctly, whether its LLM
actually calls the right tool at the right time given the system prompt in
`voice/bolna_agent_config.json`, whether the TTS voice is intelligible, and
what a real DTMF webhook payload looks like (Bolna's docs confirm DTMF
capture exists but don't publish its exact shape — see the note in
`voice/nlu.py`).

This document is the plan for verifying those on a real call, once
`voice/adapter.py` and `api.py` are both deployed somewhere Bolna can reach
(see `voice/register_agent.py` and the README's "Voice channel" section).
Each scenario lists the seed data to set up first, the expected turn-by-turn
dialogue, and exactly what to check afterward via the adapter's and API's
own read endpoints — the same source of truth the automated tests check,
just verified by listening to a real call instead of asserting on a
response body.

## Setup common to every scenario

1. Deploy `api.py` and `voice/adapter.py` somewhere reachable (or tunnel
   local instances with ngrok). Point `voice/adapter.py` at `api.py` via
   `TRANSACTION_AGENT_API_BASE_URL` / `TRANSACTION_AGENT_API_KEY`.
2. `python -m voice.register_agent --submit` once `VOICE_ADAPTER_BASE_URL`
   and `VOICE_ADAPTER_SHARED_SECRET` are set, or update the URLs by hand in
   the Bolna dashboard.
3. Seed a recipient and a user before each call:
   ```bash
   python -c "from transaction_agent import recipient_directory as rd; rd.register('ABC Logistics')"
   python -m transaction_agent.users create krish --passphrase 1234
   ```
4. Place the call via Bolna's dashboard "Test Call" feature, or
   `POST https://api.bolna.ai/call` with the registered `agent_id`.
5. After the call, pull the transcript and tool-call log from Bolna's call
   execution record (`GET /executions/{execution_id}`,
   `GET /executions/{execution_id}/logs`) to see exactly which tools were
   called with which arguments — this is how you confirm the LLM followed
   the prompt's ordering rather than skipping a step.

---

## Scenario 1 — Clean single-recipient approval

**Seed:** recipient "ABC Logistics" registered; user "krish" / PIN "1234".

**Say:** *"Pay twelve thousand rupees to ABC Logistics."*

**Expect:**
- One `start_payment_request` tool call, `transcript` containing the
  caller's sentence essentially verbatim (not restructured into e.g. a
  JSON-ish summary — this is the thing to listen for specifically, since
  it's the one behavior a system prompt can't force, only strongly
  encourage).
- Agent reads back exactly one payment, twelve thousand rupees to ABC
  Logistics, and a matching total.
- **Say:** *"All."* → agent reads back the total and asks for explicit
  confirmation — this must be its own turn, not folded into the previous
  response.
- **Say:** *"Confirm."* → agent asks for approver username and PIN (if not
  already given).
- **Say:** *"Krish, one two three four."* → `confirm_payment` called with
  `approver_username="krish"`, `pin="1234"`.
- Agent reads back "ABC Logistics: payment ... completed" and explicitly
  states no real funds moved.

**Verify after the call:**
- `GET /requests/{thread_id}` (via `GET /voice/requests/{call_sid}` using
  the call's `call_sid`) shows `status: "completed"`, one result with
  `status: "Completed"` and `approved_by: "krish"`.
- `GET /audit/{transaction_id}` shows the full transition chain (Created →
  PendingApproval → Approved → Processing → Completed) each tagged
  `channel: "voice"`, with `call_id` matching the call's `call_sid`.

**Automated equivalent:** `test_clean_single_recipient_approval`.

---

## Scenario 2 — Multi-recipient partial selection

**Seed:** recipients "ABC Logistics", "Ravi Transport", "Zed Co" registered.

**Say:** *"Pay twelve thousand to ABC Logistics, eighty five hundred to Ravi
Transport, and three thousand to Zed Co."*

**Expect:**
- Agent reads back all three, correctly ordered, with the combined total.
- **Say:** *"Approve the first and the third."* → agent reads back a
  selection total covering only ABC Logistics and Zed Co, explicitly
  naming both, and asks for confirmation.
- Confirm with valid credentials.
- Final readback: ABC Logistics and Zed Co completed; Ravi Transport is
  **not** mentioned as paid (it was rejected, not silently dropped).

**Verify after the call:**
- `GET /requests/{thread_id}` results include all three transactions:
  ABC Logistics and Zed Co `Completed`, Ravi Transport `Rejected`.
- Confirm the count is 3, not 2 — the whole point of this scenario is that
  an unselected transaction still shows up with an explicit terminal
  status rather than disappearing from the record.

**Automated equivalent:** `test_multi_recipient_partial_selection`.

---

## Scenario 3 — Ambiguous recipient disambiguated by voice

**Seed:** two similarly-named recipients, e.g. "Ravi Transport Services"
and "Ravi Traders", both registered.

**Say:** *"Pay five hundred rupees to Ravi Trans."*

**Expect:**
- Instead of a payment review, the agent asks a disambiguation question
  naming both candidates by option number (`disambiguate_recipient`'s
  prompt, driven by `start_payment_request`'s `pending_recipient_disambiguation`
  response).
- **Say:** *"Option two."* (or the recipient's full name) →
  `disambiguate_recipient` called with that answer.
- Agent proceeds to the normal payment review, now naming the resolved
  recipient.
- Continue through selection and confirmation as in Scenario 1.

**Also worth trying on a second call:** a completely unknown recipient
("Pay two hundred to Zylo Traders", nothing registered under that name) —
the agent should offer to register them as new, and a "yes" should result
in a review that shows a freshly-minted `recipient_id`.

**Verify after the call:**
- The transaction's `recipient_id` in the final result matches the
  recipient the caller picked (check `recipient_directory.sqlite`
  directly, or `GET /requests/{thread_id}` before confirming).
- If a new recipient was registered, confirm it now appears in future
  disambiguation candidate lists for similar names.

**Automated equivalent:** `test_ambiguous_recipient_disambiguated_by_voice`,
`test_unknown_recipient_registered_by_voice`,
`test_multiple_ambiguous_recipients_walked_one_at_a_time` (for a request
with more than one ambiguous name in the same sentence).

---

## Scenario 4 — Wrong PIN rejected and re-prompted

**Seed:** recipient registered; user "krish" / PIN "1234".

**Say:** *"Pay one hundred rupees to ABC Logistics."* → *"All."* →
*"Confirm."* → *"Krish, PIN nine nine nine nine."*

**Expect:**
- Agent says the PIN wasn't recognized and asks for it again — it must
  **not** say the payment failed, was rejected outright, or ask the caller
  to restate which payments to approve.
- **Say:** *"One two three four."* (the correct PIN) → payment completes
  normally, without re-selecting anything.

**Verify after the call:**
- Bolna's tool-call log shows two `confirm_payment` calls for this one
  payment attempt (one with the wrong PIN, one with the right one) —
  confirming the agent actually retried rather than giving up or the
  system silently succeeding on a bad PIN.
- `GET /audit/{transaction_id}` shows only ONE `PendingApproval -> Approved`
  transition (from the successful attempt) — the failed PIN attempt must
  not have written anything, since the graph's retry loop never runs its
  post-verification code on a failed attempt.

**Automated equivalent:**
`test_wrong_pin_rejected_and_repromts_without_losing_selection`.

---

## Scenario 5 — Caller hangs up mid-flow

Run this as two separate calls (a real hangup can't be scripted from the
caller side, so this uses "stop responding / disconnect").

**Seed:** recipient registered.

**Call A — hang up after hearing the review, before selecting:**
1. *"Pay one hundred rupees to ABC Logistics."*
2. Hang up as soon as the agent starts reading the review back.

**Call B — hang up after selecting, before confirming:**
1. *"Pay one hundred rupees to ABC Logistics."* → *"All."*
2. Hang up right after the agent asks for confirmation.

**Expect (both calls):** the call simply ends. No error, no fallback
approval, no message claiming the payment went through.

**Verify after each call:**
- `GET /voice/requests/{call_sid}` (using that call's `call_sid`, findable
  in Bolna's execution record even after the call ends) returns
  `status: "pending_approval"`, with the transaction's `status` still
  `PendingApproval` and `approved_by: null`.
- The thread is genuinely resumable: place a **new** call, or use
  `curl` directly against the adapter with the same `call_sid`, and
  confirm `select`/`confirm` still work and pick up exactly where the
  first call left off (this also exercises the same SQLite-backed
  checkpoint persistence proven in `tests/test_persistence.py` for the
  CLI/API front ends — the voice channel gets it for free from the same
  graph).
- Nothing in `processed_transactions` or the audit log claims a terminal
  status (`Completed`/`Failed`/`Rejected`) for this transaction.

**Automated equivalent:** `test_hangup_after_select_leaves_thread_parked`,
`test_hangup_before_selection_leaves_thread_parked` — these assert the
exact same parked-state property using a direct HTTP call, standing in for
the hangup (there's no way to simulate an actual phone disconnect signal
outside a real Bolna call).

---

## Known gaps only a real call can close

- **DTMF payload shape.** `voice/nlu.parse_dtmf_selection` defines our own
  convention (`*`-separated digits, `#` to terminate, `0`/`9` shortcuts)
  because Bolna's docs don't publish the exact webhook shape for keypad
  input. The first real call using DTMF should confirm what Bolna actually
  sends and adjust `voice/adapter.py`'s DTMF parameter handling if it
  differs from a bare digit string.
- **Verbatim readback compliance.** The system prompt in
  `bolna_agent_config.json` instructs the LLM to read `spoken_text` back
  word-for-word rather than re-deriving numbers, since Bolna's docs
  confirm tool responses are handed to the LLM which "continues the
  conversation naturally" — i.e. it *can* paraphrase. Only a real call
  (or several) shows how reliably the model actually complies; if it
  drifts, tightening the prompt or lowering `temperature` further are the
  first things to try.
- **Turn-taking latency and barge-in.** Whether a caller talking over the
  agent (e.g. saying "confirm" before the readback finishes) is handled
  gracefully is a platform-level behavior, not something this adapter
  controls.
