"""Automated coverage of everything the voice channel does that doesn't
require an actual phone call: the adapter's own request handling, the
select-then-confirm gate, PIN retry, disambiguation, audit tagging, and a
caller hanging up leaving the transaction correctly parked. What can't be
exercised here — real STT/TTS, Bolna's own LLM behavior on a live call — is
covered by VOICE_TEST_PLAN.md instead.
"""

import pathlib
import shutil

import pytest
from fastapi.testclient import TestClient

from api import Settings as ApiSettings
from api import create_app as create_api_app
from transaction_agent import audit, negotiations, recipient_directory, users
from voice import state as voice_state
from voice.adapter import VoiceSettings
from voice.adapter import create_app as create_voice_app

AUTH = {"Authorization": "Bearer voice-test-secret"}


def _build(tmp_path: pathlib.Path):
    api_settings = ApiSettings(
        checkpoint_db=str(tmp_path / "checkpoints.sqlite"),
        checkpoint_dsn=None,  # force SQLite even if DATABASE_URL_DIRECT is set in the environment
        audit_path=str(tmp_path / "audit.json"),
        recipient_directory_path=str(tmp_path / "recipients.sqlite"),
        users_path=str(tmp_path / "users.sqlite"),
        api_key="api-test-key",
        offline=True,
    )
    api_app = create_api_app(api_settings)
    api_client = TestClient(api_app, base_url="http://api-test", headers={"X-API-Key": "api-test-key"})

    voice_settings = VoiceSettings(
        voice_state_path=str(tmp_path / "voice_state.sqlite"),
        shared_secret="voice-test-secret",
        negotiations_path=str(tmp_path / "negotiations.sqlite"),
    )
    voice_app = create_voice_app(voice_settings, api_client=api_client)
    voice_client = TestClient(voice_app)

    return voice_client, api_client, api_settings, voice_settings


def _seed(api_settings, recipients=(), username="krish", pin="1234"):
    users.create_user(username, pin, path=api_settings.users_path)
    for name in recipients:
        recipient_directory.register(name, path=api_settings.recipient_directory_path)


def test_missing_shared_secret_is_rejected(tmp_path):
    voice_client, *_ = _build(tmp_path)
    r = voice_client.post("/voice/requests", json={"call_sid": "c1", "transcript": "pay 100 to A"})
    assert r.status_code == 401


def test_clean_single_recipient_approval(tmp_path):
    voice_client, api_client, api_settings, _ = _build(tmp_path)
    _seed(api_settings, recipients=["ABC Logistics"])

    r1 = voice_client.post(
        "/voice/requests", json={"call_sid": "call_1", "transcript": "pay 12000 to ABC Logistics"}, headers=AUTH
    )
    assert r1.status_code == 200
    assert r1.json()["status"] == "pending_approval"
    assert "twelve thousand rupees" in r1.json()["spoken_text"]

    r2 = voice_client.post(
        "/voice/requests/select", json={"call_sid": "call_1", "selection_text": "all"}, headers=AUTH
    )
    assert r2.json()["status"] == "awaiting_confirmation"
    assert "confirm" in r2.json()["spoken_text"].lower()

    r3 = voice_client.post(
        "/voice/requests/confirm",
        json={"call_sid": "call_1", "confirmation_text": "confirm", "approver_username": "krish", "pin": "1234"},
        headers=AUTH,
    )
    assert r3.status_code == 200
    assert r3.json()["status"] == "completed"
    assert r3.json()["results"][0]["status"] == "Completed"
    assert "no real funds" in r3.json()["spoken_text"].lower()


def test_multi_recipient_partial_selection(tmp_path):
    voice_client, api_client, api_settings, _ = _build(tmp_path)
    _seed(api_settings, recipients=["A", "B", "C"])

    voice_client.post(
        "/voice/requests", json={"call_sid": "call_2", "transcript": "pay 100 to A, 200 to B, 300 to C"}, headers=AUTH
    )
    r = voice_client.post(
        "/voice/requests/select", json={"call_sid": "call_2", "selection_text": "one and three"}, headers=AUTH
    )
    assert "A" in r.json()["spoken_text"] and "C" in r.json()["spoken_text"]
    assert "B" not in r.json()["spoken_text"]

    r2 = voice_client.post(
        "/voice/requests/confirm",
        json={"call_sid": "call_2", "confirmation_text": "confirm", "approver_username": "krish", "pin": "1234"},
        headers=AUTH,
    )
    statuses = {tx["recipient"]: tx["status"] for tx in r2.json()["results"]}
    assert statuses == {"A": "Completed", "B": "Rejected", "C": "Completed"}


def test_ambiguous_recipient_disambiguated_by_voice(tmp_path):
    voice_client, api_client, api_settings, _ = _build(tmp_path)
    _seed(api_settings)
    recipient_directory.register("Ravi Transport Services", path=api_settings.recipient_directory_path)
    recipient_directory.register("Ravi Traders", path=api_settings.recipient_directory_path)

    r1 = voice_client.post(
        "/voice/requests", json={"call_sid": "call_3", "transcript": "pay 500 to Ravi Trans"}, headers=AUTH
    )
    assert r1.json()["status"] == "pending_recipient_disambiguation"
    assert "option 1" in r1.json()["spoken_text"] and "option 2" in r1.json()["spoken_text"]

    r2 = voice_client.post(
        "/voice/requests/disambiguate", json={"call_sid": "call_3", "choice_text": "2"}, headers=AUTH
    )
    assert r2.json()["status"] == "pending_approval"
    assert r2.json()["transactions"][0]["recipient_id"] is not None

    r3 = voice_client.post(
        "/voice/requests/select", json={"call_sid": "call_3", "selection_text": "all"}, headers=AUTH
    )
    r4 = voice_client.post(
        "/voice/requests/confirm",
        json={"call_sid": "call_3", "confirmation_text": "confirm", "approver_username": "krish", "pin": "1234"},
        headers=AUTH,
    )
    assert r4.json()["results"][0]["status"] == "Completed"


def test_unknown_recipient_registered_by_voice(tmp_path):
    voice_client, api_client, api_settings, _ = _build(tmp_path)
    _seed(api_settings)

    r1 = voice_client.post(
        "/voice/requests", json={"call_sid": "call_4", "transcript": "pay 500 to Brand New Vendor"}, headers=AUTH
    )
    assert r1.json()["status"] == "pending_recipient_disambiguation"

    r2 = voice_client.post(
        "/voice/requests/disambiguate", json={"call_sid": "call_4", "choice_text": "yes please add them"}, headers=AUTH
    )
    assert r2.json()["status"] == "pending_approval"
    assert r2.json()["transactions"][0]["recipient_id"].startswith("rcpt_")


def test_multiple_ambiguous_recipients_walked_one_at_a_time(tmp_path):
    voice_client, api_client, api_settings, _ = _build(tmp_path)
    _seed(api_settings)
    recipient_directory.register("Ravi Transport Services", path=api_settings.recipient_directory_path)
    recipient_directory.register("Ravi Traders", path=api_settings.recipient_directory_path)

    r1 = voice_client.post(
        "/voice/requests",
        json={"call_sid": "call_5", "transcript": "pay 100 to Ravi Trans, 200 to Totally Unknown Vendor"},
        headers=AUTH,
    )
    assert r1.json()["status"] == "pending_recipient_disambiguation"
    first_prompt = r1.json()["spoken_text"]

    r2 = voice_client.post(
        "/voice/requests/disambiguate", json={"call_sid": "call_5", "choice_text": "1"}, headers=AUTH
    )
    # still disambiguating — second item now
    assert r2.json()["status"] == "pending_recipient_disambiguation"
    assert r2.json()["spoken_text"] != first_prompt

    r3 = voice_client.post(
        "/voice/requests/disambiguate", json={"call_sid": "call_5", "choice_text": "new"}, headers=AUTH
    )
    assert r3.json()["status"] == "pending_approval"
    assert len(r3.json()["transactions"]) == 2
    assert all(tx["recipient_id"] for tx in r3.json()["transactions"])


def test_wrong_pin_rejected_and_repromts_without_losing_selection(tmp_path):
    voice_client, api_client, api_settings, _ = _build(tmp_path)
    _seed(api_settings, recipients=["A"])

    voice_client.post("/voice/requests", json={"call_sid": "call_6", "transcript": "pay 100 to A"}, headers=AUTH)
    voice_client.post("/voice/requests/select", json={"call_sid": "call_6", "selection_text": "all"}, headers=AUTH)

    bad = voice_client.post(
        "/voice/requests/confirm",
        json={"call_sid": "call_6", "confirmation_text": "confirm", "approver_username": "krish", "pin": "0000"},
        headers=AUTH,
    )
    assert bad.json()["status"] == "pin_rejected"
    assert "PIN wasn't recognized" in bad.json()["spoken_text"]

    # the thread itself must still show nothing approved
    status_check = voice_client.get("/voice/requests/call_6", headers=AUTH)
    assert status_check.json()["status"] == "pending_approval"

    # retry with the SAME (unresent) selection, correct pin — no need to reselect
    good = voice_client.post(
        "/voice/requests/confirm",
        json={"call_sid": "call_6", "confirmation_text": "confirm", "approver_username": "krish", "pin": "1234"},
        headers=AUTH,
    )
    assert good.json()["status"] == "completed"
    assert good.json()["results"][0]["status"] == "Completed"


def test_selection_utterance_alone_never_approves_anything(tmp_path):
    """The two-step design: saying which payments to approve must never by
    itself trigger an approval call — a separate explicit confirm is required."""
    voice_client, api_client, api_settings, _ = _build(tmp_path)
    _seed(api_settings, recipients=["A"])

    voice_client.post("/voice/requests", json={"call_sid": "call_7", "transcript": "pay 100 to A"}, headers=AUTH)
    voice_client.post("/voice/requests/select", json={"call_sid": "call_7", "selection_text": "all"}, headers=AUTH)

    status_check = voice_client.get("/voice/requests/call_7", headers=AUTH)
    assert status_check.json()["status"] == "pending_approval"
    assert status_check.json()["transactions"][0]["status"] == "PendingApproval"


def test_ambiguous_confirmation_word_is_not_treated_as_yes_or_no(tmp_path):
    voice_client, api_client, api_settings, _ = _build(tmp_path)
    _seed(api_settings, recipients=["A"])

    voice_client.post("/voice/requests", json={"call_sid": "call_8", "transcript": "pay 100 to A"}, headers=AUTH)
    voice_client.post("/voice/requests/select", json={"call_sid": "call_8", "selection_text": "all"}, headers=AUTH)

    r = voice_client.post(
        "/voice/requests/confirm", json={"call_sid": "call_8", "confirmation_text": "umm what"}, headers=AUTH
    )
    assert r.json()["status"] == "needs_confirmation_repeat"

    status_check = voice_client.get("/voice/requests/call_8", headers=AUTH)
    assert status_check.json()["status"] == "pending_approval"


def test_cancel_during_confirm_clears_selection_and_allows_reselect(tmp_path):
    voice_client, api_client, api_settings, _ = _build(tmp_path)
    _seed(api_settings, recipients=["A", "B"])

    voice_client.post("/voice/requests", json={"call_sid": "call_9", "transcript": "pay 100 to A, 200 to B"}, headers=AUTH)
    voice_client.post("/voice/requests/select", json={"call_sid": "call_9", "selection_text": "all"}, headers=AUTH)

    cancel = voice_client.post(
        "/voice/requests/confirm", json={"call_sid": "call_9", "confirmation_text": "cancel"}, headers=AUTH
    )
    assert cancel.json()["status"] == "selection_cancelled"

    reselect = voice_client.post(
        "/voice/requests/select", json={"call_sid": "call_9", "selection_text": "one"}, headers=AUTH
    )
    assert "A" in reselect.json()["spoken_text"] and "B" not in reselect.json()["spoken_text"]


def test_dtmf_selection_and_confirmation(tmp_path):
    voice_client, api_client, api_settings, _ = _build(tmp_path)
    _seed(api_settings, recipients=["A", "B", "C"])

    voice_client.post(
        "/voice/requests", json={"call_sid": "call_10", "transcript": "pay 100 to A, 200 to B, 300 to C"}, headers=AUTH
    )
    r = voice_client.post("/voice/requests/select", json={"call_sid": "call_10", "dtmf_digits": "1*3#"}, headers=AUTH)
    assert "A" in r.json()["spoken_text"] and "C" in r.json()["spoken_text"] and "B" not in r.json()["spoken_text"]

    r2 = voice_client.post(
        "/voice/requests/confirm",
        json={"call_sid": "call_10", "dtmf_digit": "1", "approver_username": "krish", "pin": "1234"},
        headers=AUTH,
    )
    statuses = {tx["recipient"]: tx["status"] for tx in r2.json()["results"]}
    assert statuses == {"A": "Completed", "B": "Rejected", "C": "Completed"}


def test_hangup_after_select_leaves_thread_parked(tmp_path):
    voice_client, api_client, api_settings, _ = _build(tmp_path)
    _seed(api_settings, recipients=["A"])

    voice_client.post("/voice/requests", json={"call_sid": "call_11", "transcript": "pay 100 to A"}, headers=AUTH)
    voice_client.post("/voice/requests/select", json={"call_sid": "call_11", "selection_text": "all"}, headers=AUTH)
    # caller hangs up here — nothing more happens on this call

    status_check = voice_client.get("/voice/requests/call_11", headers=AUTH)
    assert status_check.status_code == 200
    assert status_check.json()["status"] == "pending_approval"
    assert status_check.json()["transactions"][0]["status"] == "PendingApproval"
    assert status_check.json()["transactions"][0]["approved_by"] is None


def test_hangup_before_selection_leaves_thread_parked(tmp_path):
    voice_client, api_client, api_settings, _ = _build(tmp_path)
    _seed(api_settings, recipients=["A"])

    voice_client.post("/voice/requests", json={"call_sid": "call_12", "transcript": "pay 100 to A"}, headers=AUTH)
    # caller hangs up immediately after hearing the review, before selecting anything

    status_check = voice_client.get("/voice/requests/call_12", headers=AUTH)
    assert status_check.json()["status"] == "pending_approval"


def test_unknown_call_sid_status_check_returns_404(tmp_path):
    voice_client, *_ = _build(tmp_path)
    r = voice_client.get("/voice/requests/never-called", headers=AUTH)
    assert r.status_code == 404


def test_audit_log_tags_voice_channel_call_id_and_transcript_ref(tmp_path):
    voice_client, api_client, api_settings, _ = _build(tmp_path)
    _seed(api_settings, recipients=["A"])

    voice_client.post("/voice/requests", json={"call_sid": "call_13", "transcript": "pay 100 to A"}, headers=AUTH)
    thread_id = voice_state.get_thread_id("call_13", path=str(tmp_path / "voice_state.sqlite"))
    r = api_client.get(f"/requests/{thread_id}")
    tx_id = r.json()["transactions"][0]["id"]

    voice_client.post("/voice/requests/select", json={"call_sid": "call_13", "selection_text": "all"}, headers=AUTH)
    voice_client.post(
        "/voice/requests/confirm",
        json={"call_sid": "call_13", "confirmation_text": "confirm", "approver_username": "krish", "pin": "1234"},
        headers=AUTH,
    )

    entries = audit.read_all(api_settings.audit_path)
    tx_entries = [e for e in entries if e["transaction_id"] == tx_id]
    assert tx_entries, "expected audit entries for this transaction"
    for e in tx_entries:
        assert e["channel"] == "voice"
        assert e["call_id"] == "call_13"
        assert e["transcript_ref"] == "voice_transcript:call_13"


def test_select_before_request_created_is_handled_gracefully(tmp_path):
    voice_client, *_ = _build(tmp_path)
    r = voice_client.post(
        "/voice/requests/select", json={"call_sid": "never-started", "selection_text": "all"}, headers=AUTH
    )
    assert r.status_code == 200  # never a raw error to a caller mid-call
    assert r.json()["status"] == "error"


def test_confirm_before_selection_is_handled_gracefully(tmp_path):
    voice_client, api_client, api_settings, _ = _build(tmp_path)
    _seed(api_settings, recipients=["A"])
    voice_client.post("/voice/requests", json={"call_sid": "call_14", "transcript": "pay 100 to A"}, headers=AUTH)

    r = voice_client.post(
        "/voice/requests/confirm", json={"call_sid": "call_14", "confirmation_text": "confirm"}, headers=AUTH
    )
    assert r.status_code == 200
    assert r.json()["status"] == "error"


def test_transcript_log_accumulates_every_turn(tmp_path):
    voice_client, api_client, api_settings, voice_settings = _build(tmp_path)
    _seed(api_settings, recipients=["A"])

    voice_client.post("/voice/requests", json={"call_sid": "call_15", "transcript": "pay 100 to A"}, headers=AUTH)
    voice_client.post("/voice/requests/select", json={"call_sid": "call_15", "selection_text": "all"}, headers=AUTH)

    turns = voice_state.get_transcript("call_15", path=voice_settings.voice_state_path)
    speakers = [t["speaker"] for t in turns]
    assert speakers.count("caller") >= 2
    assert speakers.count("agent") >= 2


# --- outbound vendor negotiation ------------------------------------------


def test_negotiation_accepted_records_outcome_and_creates_pending_transaction(tmp_path):
    voice_client, api_client, api_settings, voice_settings = _build(tmp_path)

    r = voice_client.post(
        "/voice/negotiation/outcome",
        json={
            "call_sid": "neg_call_1",
            "vendor_name": "ABC Traders",
            "outcome": "accepted",
            "agreed_amount": 4500,
            "purpose": "raw materials",
        },
        headers=AUTH,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "recorded"
    assert "4500" in r.json()["spoken_text"]

    rows = negotiations.list_outcomes(path=voice_settings.negotiations_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["outcome"] == "accepted"
    assert row["vendor_name"] == "ABC Traders"
    assert row["agreed_amount"] == 4500.0
    assert row["transaction_id"] is not None  # a payment request was created for owner approval

    # the created transaction is genuinely sitting in the owner's approval queue
    thread_check = api_client.get(f"/requests/{row['transaction_id']}")
    assert thread_check.status_code == 404  # transaction_id isn't a thread_id — confirms it's a real tx id, not echoed input


def test_negotiation_declined_records_outcome_without_creating_transaction(tmp_path):
    voice_client, api_client, api_settings, voice_settings = _build(tmp_path)

    r = voice_client.post(
        "/voice/negotiation/outcome",
        json={"call_sid": "neg_call_2", "vendor_name": "XYZ Corp", "outcome": "declined", "notes": "price too high"},
        headers=AUTH,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "recorded"

    rows = negotiations.list_outcomes(path=voice_settings.negotiations_path)
    assert rows[0]["outcome"] == "declined"
    assert rows[0]["transaction_id"] is None
    assert rows[0]["notes"] == "price too high"


def test_negotiation_accepted_without_amount_is_rejected(tmp_path):
    voice_client, api_client, api_settings, voice_settings = _build(tmp_path)

    r = voice_client.post(
        "/voice/negotiation/outcome",
        json={"call_sid": "neg_call_3", "vendor_name": "ABC Traders", "outcome": "accepted"},
        headers=AUTH,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "error"
    assert negotiations.list_outcomes(path=voice_settings.negotiations_path) == []


def test_negotiation_invalid_outcome_word_is_rejected(tmp_path):
    voice_client, api_client, api_settings, voice_settings = _build(tmp_path)

    r = voice_client.post(
        "/voice/negotiation/outcome",
        json={"call_sid": "neg_call_4", "vendor_name": "ABC Traders", "outcome": "maybe"},
        headers=AUTH,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "error"


def test_negotiation_outcome_requires_auth(tmp_path):
    voice_client, *_ = _build(tmp_path)
    r = voice_client.post(
        "/voice/negotiation/outcome",
        json={"call_sid": "neg_call_5", "vendor_name": "ABC Traders", "outcome": "declined"},
    )
    assert r.status_code == 401


def test_negotiation_creates_the_vendor_as_a_new_recipient(tmp_path):
    voice_client, api_client, api_settings, voice_settings = _build(tmp_path)

    voice_client.post(
        "/voice/negotiation/outcome",
        json={"call_sid": "neg_call_6", "vendor_name": "Brand New Vendor", "outcome": "accepted", "agreed_amount": 999},
        headers=AUTH,
    )
    names = {r["name"] for r in recipient_directory.list_all(path=api_settings.recipient_directory_path)}
    assert "Brand New Vendor" in names
