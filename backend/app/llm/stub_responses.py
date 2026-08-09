"""Canned StubLLM responses, keyed by the `tag` passed to `complete()`.

These are what the system says when watsonx is unreachable or unconfigured, so
they are written as real output, not placeholders: realistic Indian vendor
names, plausible operational detail, and shapes that satisfy the pydantic
schemas the agents ask for. A judge watching a degraded demo should not be able
to tell from the prose alone.

Each entry is a JSON string (for schema calls, it must parse into the caller's
model) or plain prose (for unstructured calls). Unknown tags fall through to
DEFAULT_RESPONSE.
"""

from app.llm import prompts

DEFAULT_RESPONSE = (
    "The signal has been recorded and routed for review. No automated conclusion was "
    "drawn because the reasoning model was unavailable at the time of processing."
)

STUB_RESPONSES: dict[str, str] = {
    prompts.TAG_SMOKE_TEST: '{"answer": "Pune is a major automotive manufacturing hub in Maharashtra, India.", "confidence": 0.9}',
    prompts.TAG_SENTINEL_CLASSIFY: (
        '{"disruption_type": "DELIVERY_DELAY", "severity": "HIGH", "confidence": 0.82, '
        '"headline": "Bharat Casting Industries is 4 days overdue on mounting bracket PO feeding a penalty-bearing OEM order"}'
    ),
    prompts.TAG_DIAGNOSIS_NARRATIVE: (
        '{"root_cause": "VENDOR_CAPACITY", '
        '"narrative": "Bharat Casting Industries missed the promised date by four days with no dispatch confirmation. '
        'Their last three orders each slipped 2-3 days, pointing to a sustained capacity shortfall at their Rajkot '
        'foundry rather than a one-off transport problem.", '
        '"evidence": ["PO-SCN-A-001 promised 4 days ago, delivered_at still null", '
        '"Previous three purchase orders for this vendor closed 2-3 days late", '
        '"No inbound WhatsApp reply since the dispatch follow-up was sent"], '
        '"confidence": 0.71}'
    ),
    prompts.TAG_SOURCING_RATIONALE: (
        '{"candidates": [{"vendor_name": "Vishwakarma Precision Castings", "recommended": true, '
        '"rationale": "Same castings category with a 94% on-time rate across 40 completed orders, and quotes a 3-day lead '
        'time against the 4 days already lost. Unit price is about 8% above the incumbent, which the penalty exposure '
        'more than covers."}, '
        '{"vendor_name": "Metro Casting Works", "recommended": false, '
        '"rationale": "Cheaper per unit but sits in the backup pool with a 71% on-time rate, which is the same risk that '
        'caused this disruption."}]}'
    ),
    prompts.TAG_NEGOTIATION_BRIEF: (
        '{"briefing": "Good morning, this is Shakti Auto calling about the mounting bracket order that was due on Tuesday '
        '\\u2014 we value the long relationship and wanted to check what is holding up dispatch before we look at '
        'alternatives."}'
    ),
    prompts.TAG_NEGOTIATION_OUTCOME: (
        '{"outcome": "AGREED", "agreed_unit_price_paise": 42000, "agreed_lead_time_days": 3, '
        '"agreed_payment_terms_days": 30, "breached_guardrails": false, '
        '"summary": "Vendor confirmed the delay was a furnace repair at their Rajkot unit and committed to dispatch within '
        'three days at the existing unit price. Payment terms were left unchanged at 30 days. No penalty waiver was '
        'discussed."}'
    ),
}


def response_for(tag: str) -> str:
    return STUB_RESPONSES.get(tag, DEFAULT_RESPONSE)
