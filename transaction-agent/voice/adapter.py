#!/usr/bin/env python3
"""Voice channel adapter: the actual HTTP endpoints Bolna's custom-function
tools call during a phone call. This is purely a translation layer — every
endpoint here does its work by calling api.py over HTTP (via httpx, exactly
like any other API client would) and then reshapes the response into
`spoken_text` for Bolna's TTS to read. Nothing here parses a payment
request, decides an approval, or executes a transaction; see graph.py /
api.py for all of that.

Run it with:

    uvicorn voice.adapter:app --reload --port 8100

(api.py should already be running, e.g. `uvicorn api:app --port 8000` —
see TRANSACTION_AGENT_API_BASE_URL in .env.example.)

Design notes:

- State is keyed by call_sid (voice/state.py), never by thread_id. Bolna
  fills a tool call's parameters from what its LLM remembers of the
  conversation; asking it to correctly recall and re-embed an opaque
  36-character thread_id turn after turn is a real, avoidable failure
  mode. call_sid is auto-injected by Bolna into every tool call via
  templating, so it's never something the LLM has to "remember."

- The select -> confirm two-step is enforced here, not left to the LLM's
  judgment: /voice/requests/select only ever *records* a pending selection
  and reads back its total; /voice/requests/confirm is the only endpoint
  that can call POST /requests/{id}/approve, and only once it has seen an
  explicit affirmative word. A bad PIN does not clear the pending
  selection, so a retry doesn't require re-stating which payments to
  approve — same as the graph's own passphrase-retry loop.

- Every endpoint returns HTTP 200 with a `spoken_text` field explaining
  what happened, even on failure — a phone call has no good way to
  surface a raw HTTP error, so failures are turned into something sayable
  instead of propagating as a 4xx/5xx the voice agent has no plan for.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel

from transaction_agent import negotiations
from transaction_agent.models import utcnow_iso
from voice import nlu
from voice import sheets as voice_sheets
from voice import state as voice_state

load_dotenv()

DEFAULT_DEV_SHARED_SECRET = "dev-local-voice-secret"


@dataclass
class VoiceSettings:
    api_base_url: str = field(
        default_factory=lambda: os.environ.get("TRANSACTION_AGENT_API_BASE_URL", "http://127.0.0.1:8000")
    )
    api_key: str = field(default_factory=lambda: os.environ.get("TRANSACTION_AGENT_API_KEY", "dev-local-key"))
    shared_secret: str = field(
        default_factory=lambda: os.environ.get("VOICE_ADAPTER_SHARED_SECRET", DEFAULT_DEV_SHARED_SECRET)
    )
    voice_state_path: str = field(default_factory=lambda: voice_state.DEFAULT_VOICE_STATE_PATH)
    negotiations_path: str = field(default_factory=lambda: negotiations.DEFAULT_NEGOTIATIONS_PATH)


# --- request/response models -----------------------------------------------


class VoiceCreateRequestBody(BaseModel):
    call_sid: str
    transcript: str
    caller_number: Optional[str] = None


class VoiceSelectBody(BaseModel):
    call_sid: str
    selection_text: Optional[str] = None
    dtmf_digits: Optional[str] = None


class VoiceConfirmBody(BaseModel):
    call_sid: str
    confirmation_text: Optional[str] = None
    dtmf_digit: Optional[str] = None
    approver_username: Optional[str] = None
    pin: Optional[str] = None


class VoiceDisambiguateBody(BaseModel):
    call_sid: str
    choice_text: Optional[str] = None
    dtmf_digit: Optional[str] = None


class NegotiationOutcomeBody(BaseModel):
    call_sid: str
    vendor_name: str
    outcome: str  # "accepted" | "declined"
    agreed_amount: Optional[float] = None
    currency: str = "INR"
    purpose: Optional[str] = None
    notes: Optional[str] = None


class VoiceResponse(BaseModel):
    spoken_text: str
    status: str
    call_sid: str
    transactions: Optional[list[dict[str, Any]]] = None
    results: Optional[list[dict[str, Any]]] = None


# --- helpers -----------------------------------------------------------


def _disambiguation_prompt(item: dict[str, Any]) -> str:
    candidates = item["candidates"]
    amount_words = nlu.amount_to_words(item["amount"], "INR")
    if candidates:
        options = "; ".join(f"option {i + 1}, {c['name']}" for i, c in enumerate(candidates))
        return (
            f"I'm not sure who you meant by '{item['recipient_text']}' for the payment of {amount_words}. "
            f"Did you mean {options}? Say the option number, or say 'new' to add them as a new recipient."
        )
    return (
        f"I don't have anyone called '{item['recipient_text']}' in the recipient directory, for the payment of "
        f"{amount_words}. Should I add them as a new recipient? Say 'yes' to add them, or tell me the correct name."
    )


def _format_results_for_voice(results: list[dict[str, Any]]) -> str:
    lines = []
    for tx in results:
        amount_words = nlu.amount_to_words(tx["amount"], tx["currency"])
        if tx["status"] == "Completed":
            lines.append(f"{tx['recipient']}: payment of {amount_words} completed.")
        elif tx["status"] == "Failed":
            lines.append(f"{tx['recipient']}: payment of {amount_words} failed.")
        else:
            lines.append(f"{tx['recipient']}: {tx['status']}.")
    lines.append("Remember, no real funds were moved — this was a simulated payment.")
    return " ".join(lines)


def create_app(settings: Optional[VoiceSettings] = None, api_client: Optional[httpx.Client] = None) -> FastAPI:
    """api_client lets tests point this adapter at an in-process api.py
    TestClient-style transport instead of a real network address."""
    settings = settings or VoiceSettings()

    owned_client = api_client is None
    client = api_client or httpx.Client(
        base_url=settings.api_base_url, headers={"X-API-Key": settings.api_key}, timeout=10.0
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        if owned_client:
            client.close()

    app = FastAPI(title="Transaction Agent Voice Adapter", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings

    def require_shared_secret(authorization: Optional[str] = Header(default=None)) -> None:
        expected = f"Bearer {settings.shared_secret}"
        if authorization != expected:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing voice adapter credentials")

    auth = Depends(require_shared_secret)
    path = settings.voice_state_path

    def _log(call_sid: str, speaker: str, text: str) -> None:
        voice_state.append_transcript_turn(call_sid, speaker, text, path=path)

    @app.post("/voice/requests", response_model=VoiceResponse, dependencies=[auth])
    def voice_create_request(body: VoiceCreateRequestBody):
        _log(body.call_sid, "caller", body.transcript)

        resp = client.post(
            "/requests",
            json={
                "raw_request": body.transcript,
                "requester_id": f"voice:{body.caller_number or body.call_sid}",
                "channel": "voice",
                "call_id": body.call_sid,
                "transcript_ref": voice_state.transcript_ref_for(body.call_sid),
                "auto_resolve_recipients": False,
            },
        )
        if resp.status_code != 200:
            spoken = "Sorry, I couldn't process that payment request. Could you say it again?"
            _log(body.call_sid, "agent", spoken)
            return VoiceResponse(spoken_text=spoken, status="error", call_sid=body.call_sid)

        data = resp.json()
        voice_state.link_call(body.call_sid, data["thread_id"], path=path)

        if data["status"] == "pending_recipient_disambiguation":
            first_item = voice_state.start_disambiguation(body.call_sid, data["pending_recipients"], path=path)
            spoken = _disambiguation_prompt(first_item)
            _log(body.call_sid, "agent", spoken)
            return VoiceResponse(spoken_text=spoken, status="pending_recipient_disambiguation", call_sid=body.call_sid)

        spoken = nlu.format_review_for_voice(data["transactions"])
        _log(body.call_sid, "agent", spoken)
        return VoiceResponse(
            spoken_text=spoken, status="pending_approval", call_sid=body.call_sid, transactions=data["transactions"]
        )

    @app.post("/voice/requests/disambiguate", response_model=VoiceResponse, dependencies=[auth])
    def voice_disambiguate(body: VoiceDisambiguateBody):
        text = body.dtmf_digit or body.choice_text or ""
        _log(body.call_sid, "caller", text)

        current = voice_state.get_current_disambiguation_item(body.call_sid, path=path)
        if current is None:
            spoken = "There's nothing to disambiguate right now."
            return VoiceResponse(spoken_text=spoken, status="error", call_sid=body.call_sid)

        candidates = current["candidates"]
        normalized = text.strip().lower()
        choice: Optional[dict[str, Any]] = None
        if normalized.isdigit() and candidates and 1 <= int(normalized) <= len(candidates):
            choice = {"recipient_id": candidates[int(normalized) - 1]["recipient_id"]}
        elif any(w in normalized for w in ("new", "yes", "add", "register")):
            choice = {"register_new": {"name": current["recipient_text"]}}
        elif normalized:
            # anything else spoken is treated as a corrected recipient name
            choice = {"register_new": {"name": text.strip()}}

        if choice is None:
            spoken = "Sorry, I didn't catch that. " + _disambiguation_prompt(current)
            _log(body.call_sid, "agent", spoken)
            return VoiceResponse(spoken_text=spoken, status="pending_recipient_disambiguation", call_sid=body.call_sid)

        next_item, all_choices = voice_state.record_choice_and_advance(
            body.call_sid, current["transaction_id"], choice, path=path
        )

        if next_item is not None:
            spoken = _disambiguation_prompt(next_item)
            _log(body.call_sid, "agent", spoken)
            return VoiceResponse(spoken_text=spoken, status="pending_recipient_disambiguation", call_sid=body.call_sid)

        thread_id = voice_state.get_thread_id(body.call_sid, path=path)
        resp = client.post(f"/requests/{thread_id}/disambiguate", json={"choices": all_choices})
        voice_state.clear_disambiguation(body.call_sid, path=path)
        if resp.status_code != 200:
            spoken = "Sorry, something went wrong resolving that recipient. Let's start the payment again."
            _log(body.call_sid, "agent", spoken)
            return VoiceResponse(spoken_text=spoken, status="error", call_sid=body.call_sid)

        data = resp.json()
        spoken = nlu.format_review_for_voice(data["transactions"])
        _log(body.call_sid, "agent", spoken)
        return VoiceResponse(
            spoken_text=spoken, status="pending_approval", call_sid=body.call_sid, transactions=data["transactions"]
        )

    @app.post("/voice/requests/select", response_model=VoiceResponse, dependencies=[auth])
    def voice_select(body: VoiceSelectBody):
        text = body.dtmf_digits or body.selection_text or ""
        _log(body.call_sid, "caller", text)

        thread_id = voice_state.get_thread_id(body.call_sid, path=path)
        if not thread_id:
            spoken = "I don't have a payment request started for this call yet. What would you like to pay?"
            return VoiceResponse(spoken_text=spoken, status="error", call_sid=body.call_sid)

        resp = client.get(f"/requests/{thread_id}")
        if resp.status_code != 200 or resp.json().get("status") != "pending_approval":
            spoken = "There's nothing waiting for approval on this call right now."
            return VoiceResponse(spoken_text=spoken, status="error", call_sid=body.call_sid)

        transactions = resp.json()["transactions"]
        indices = (
            nlu.parse_dtmf_selection(body.dtmf_digits, len(transactions))
            if body.dtmf_digits
            else nlu.parse_selection(text, len(transactions))
        )

        selected = [transactions[i - 1] for i in indices]
        total = sum(tx["amount"] for tx in selected)
        currency = selected[0]["currency"] if selected else (transactions[0]["currency"] if transactions else "INR")
        voice_state.set_pending_selection(body.call_sid, [tx["id"] for tx in selected], total, currency, path=path)

        spoken = nlu.format_selection_confirmation(selected, total, currency)
        _log(body.call_sid, "agent", spoken)
        return VoiceResponse(spoken_text=spoken, status="awaiting_confirmation", call_sid=body.call_sid)

    @app.post("/voice/requests/confirm", response_model=VoiceResponse, dependencies=[auth])
    def voice_confirm(body: VoiceConfirmBody):
        text = body.dtmf_digit or body.confirmation_text or ""
        _log(body.call_sid, "caller", text)

        pending = voice_state.get_pending_selection(body.call_sid, path=path)
        if pending is None:
            spoken = "I don't have a selection to confirm yet. Which payments would you like to approve?"
            return VoiceResponse(spoken_text=spoken, status="error", call_sid=body.call_sid)

        if nlu.is_negative(text):
            voice_state.clear_pending_selection(body.call_sid, path=path)
            spoken = "Okay, I've cleared that selection. Which payments would you like to approve?"
            _log(body.call_sid, "agent", spoken)
            return VoiceResponse(spoken_text=spoken, status="selection_cancelled", call_sid=body.call_sid)

        if not nlu.is_affirmative(text):
            spoken = "Sorry, I need you to say 'confirm' to proceed, or 'cancel' to pick again."
            _log(body.call_sid, "agent", spoken)
            return VoiceResponse(spoken_text=spoken, status="needs_confirmation_repeat", call_sid=body.call_sid)

        if not body.approver_username or not body.pin:
            spoken = "I need your approver username and PIN before I can process this. What's your username?"
            return VoiceResponse(spoken_text=spoken, status="needs_credentials", call_sid=body.call_sid)

        thread_id = voice_state.get_thread_id(body.call_sid, path=path)
        resp = client.post(
            f"/requests/{thread_id}/approve",
            json={"selected_ids": pending["selected_ids"], "approver_id": body.approver_username, "passphrase": body.pin},
        )
        if resp.status_code == 401:
            # do NOT clear the pending selection: a retry shouldn't need to re-select
            spoken = "That PIN wasn't recognized. Please say or key in your PIN again."
            _log(body.call_sid, "agent", spoken)
            return VoiceResponse(spoken_text=spoken, status="pin_rejected", call_sid=body.call_sid)
        if resp.status_code != 200:
            spoken = "Sorry, something went wrong processing that payment."
            _log(body.call_sid, "agent", spoken)
            return VoiceResponse(spoken_text=spoken, status="error", call_sid=body.call_sid)

        voice_state.clear_pending_selection(body.call_sid, path=path)
        results = resp.json()["results"]
        spoken = _format_results_for_voice(results)
        _log(body.call_sid, "agent", spoken)
        return VoiceResponse(spoken_text=spoken, status="completed", call_sid=body.call_sid, results=results)

    @app.get("/voice/requests/{call_sid}", dependencies=[auth])
    def voice_get_status(call_sid: str):
        thread_id = voice_state.get_thread_id(call_sid, path=path)
        if not thread_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No call recorded for call_sid {call_sid!r}")
        resp = client.get(f"/requests/{thread_id}")
        if resp.status_code != 200:
            raise HTTPException(resp.status_code, resp.text)
        body = resp.json()
        body["call_sid"] = call_sid
        return body

    @app.post("/voice/negotiation/outcome", response_model=VoiceResponse, dependencies=[auth])
    def voice_negotiation_outcome(body: NegotiationOutcomeBody):
        """Called by the *outbound vendor negotiation* agent (a separate
        Bolna agent from the approval-flow one above) once a call ends.
        Records the outcome regardless of what happens next; on 'accepted'
        it also creates a normal payment request — through the exact same
        POST /requests path any other channel uses — so the result lands
        in the owner's regular approval queue rather than a side channel."""
        if body.outcome not in ("accepted", "declined"):
            spoken = "Sorry, I can only record an outcome as accepted or declined."
            return VoiceResponse(spoken_text=spoken, status="error", call_sid=body.call_sid)

        summary = f"{body.outcome}: {body.vendor_name}" + (
            f" at {body.agreed_amount} {body.currency}" if body.agreed_amount is not None else ""
        )
        _log(body.call_sid, "negotiation_summary", summary)
        transcript_ref = voice_state.transcript_ref_for(body.call_sid)

        transaction_id = None
        if body.outcome == "accepted":
            if body.agreed_amount is None or body.agreed_amount <= 0:
                spoken = "I need a valid agreed amount to record an accepted negotiation. What was the final price?"
                return VoiceResponse(spoken_text=spoken, status="error", call_sid=body.call_sid)

            raw_request = f"Pay {body.agreed_amount} to {body.vendor_name}"
            if body.purpose:
                raw_request += f" for {body.purpose}"
            resp = client.post(
                "/requests",
                json={
                    "raw_request": raw_request,
                    "requester_id": f"voice-negotiation:{body.call_sid}",
                    "channel": "voice",
                    "call_id": body.call_sid,
                    "transcript_ref": transcript_ref,
                    # this agent has no disambiguation sub-flow of its own, unlike
                    # the approval-flow agent — auto-resolve rather than block.
                    "auto_resolve_recipients": True,
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("transactions"):
                    transaction_id = data["transactions"][0]["id"]

        negotiations.record_outcome(
            call_sid=body.call_sid,
            vendor_name=body.vendor_name,
            outcome=body.outcome,
            agreed_amount=body.agreed_amount,
            currency=body.currency,
            purpose=body.purpose,
            notes=body.notes,
            transcript_ref=transcript_ref,
            transaction_id=transaction_id,
            path=settings.negotiations_path,
        )
        voice_sheets.append_negotiation_row(
            {
                "created_at": utcnow_iso(),
                "call_sid": body.call_sid,
                "vendor_name": body.vendor_name,
                "outcome": body.outcome,
                "agreed_amount": body.agreed_amount,
                "currency": body.currency,
                "purpose": body.purpose,
                "notes": body.notes,
                "transaction_id": transaction_id,
            }
        )

        if body.outcome == "accepted":
            spoken = (
                f"Thank you, {body.vendor_name}! I've recorded {body.agreed_amount} {body.currency} as agreed. "
                "This has been sent to the owner for approval. Have a great day."
            )
        else:
            spoken = f"No problem, thank you for your time — I've noted that {body.vendor_name} isn't able to proceed at this time."
        _log(body.call_sid, "agent", spoken)
        return VoiceResponse(spoken_text=spoken, status="recorded", call_sid=body.call_sid)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8100)
