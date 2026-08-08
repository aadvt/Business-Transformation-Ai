"""Outbound bridge to the transaction-agent service (../transaction-agent),
used by the settlement execute flow to hand a confirmed batch off as a
real payment request instead of just settlement-page copy text.

Best-effort by design: transaction-agent is a separate, independently
runnable service. If it's unreachable or rejects the request, settlement
execute must still succeed on the Sanjeevani side — this augments the
flow, it doesn't gate it. Never raises; returns None on any failure.
"""

import logging

import httpx

from app.config import settings
from app.schemas.settlement import SettlementBatch, TransactionAgentHandoff

logger = logging.getLogger(__name__)


def _build_raw_request(batch: SettlementBatch) -> str:
    # Plain digit amounts (no thousands separators) parse correctly under
    # both transaction-agent's offline regex parser and its LLM parser —
    # Indian-style grouping ("18,45,000") doesn't match the offline
    # parser's 3-digit-group regex.
    parts = [f"{line.amount_paise // 100} to {line.vendor.name}" for line in batch.lines]
    return "Pay " + ", ".join(parts)


async def stage_settlement_batch(batch: SettlementBatch, requested_by: str) -> TransactionAgentHandoff | None:
    if not batch.lines:
        return None

    payload = {
        "raw_request": _build_raw_request(batch),
        "requester_id": requested_by,
        "channel": "api",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{settings.transaction_agent_base_url}/requests",
                json=payload,
                headers={"X-API-Key": settings.transaction_agent_api_key},
            )
            response.raise_for_status()
            body = response.json()
    except httpx.HTTPError as exc:
        logger.warning("transaction-agent handoff failed for batch %s: %s", batch.id, exc)
        return None

    return TransactionAgentHandoff(
        thread_id=body["thread_id"],
        status=body["status"],
        review_text=body.get("review_text"),
    )
