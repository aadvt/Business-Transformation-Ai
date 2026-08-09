"""Phone mock — message thread derived from existing data.

Honest deliverable: WhatsApp Business API integration is NOT implemented.
The mock UI thread is what reaches users. This endpoint derives the conversation
from DB state — disruptions, approvals, negotiations, settlements — deterministically.
"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.constants import DEFAULT_ORG_ID
from app.db.session import get_session
from app.db.models import Approval as ApprovalRow, DisruptionEvent, Negotiation, SettlementBatchRow
from app.deps import require_api_key
from app.schemas.money import format_inr, to_iso, utc_now_iso

router = APIRouter(prefix="/api/v1/phone", tags=["phone"], dependencies=[Depends(require_api_key)])


class PhoneMessage:
    def __init__(self, at, direction, kind, text, card=None):
        self.id = str(uuid.uuid4())
        self.at = at
        self.direction = direction
        self.kind = kind
        self.text = text
        self.card = card

    def model_dump(self):
        result = {"id": self.id, "at": self.at, "direction": self.direction, "kind": self.kind, "text": self.text}
        if self.card:
            result["card"] = self.card
        return result


@router.get("/messages")
def get_phone_messages(
    disruption_id: str = Query(None),
    session: Session = Depends(get_session),
):
    """Message thread for the WhatsApp mock UI, derived from DB state.

    Includes: disruption alerts, approval cards, outcomes, settlement updates.
    No actual WhatsApp/Twilio integration — this is the honest deliverable.
    """
    messages = []

    if disruption_id:
        disruption = session.get(DisruptionEvent, disruption_id)
        if disruption is None:
            return {"messages": []}

        # Alert message: disruption detected
        messages.append(
            PhoneMessage(
                at=to_iso(disruption.detected_at),
                direction="IN",
                kind="ALERT",
                text=f"⚠️ Supply disruption detected: {disruption.headline}",
            )
        )

        # Approval card message
        approval = session.execute(
            select(ApprovalRow)
            .where(ApprovalRow.disruption_id == disruption_id)
            .order_by(ApprovalRow.requested_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        if approval:
            exposure_display = format_inr(0)  # Would read from latest exposure_calcs in real impl
            plan_summary = ["Switch to alternate vendor", "Expedite shipping"]  # Placeholder

            messages.append(
                PhoneMessage(
                    at=to_iso(approval.requested_at),
                    direction="OUT",
                    kind="APPROVAL_CARD",
                    text="Remediation plan ready for your approval",
                    card={
                        "disruption_id": disruption_id,
                        "approval_id": approval.id,
                        "headline": disruption.headline,
                        "exposure_display": exposure_display,
                        "plan_summary": plan_summary,
                        "actions": ["APPROVE", "MODIFY"],
                    },
                )
            )

            # Approval decision message
            if approval.decided_at:
                decision_text = f"✅ Approved on {approval.channel}" if approval.status == "APPROVED" else "❌ Rejected"
                messages.append(
                    PhoneMessage(
                        at=to_iso(approval.decided_at),
                        direction="IN",
                        kind="TEXT",
                        text=f"{decision_text} by {approval.decided_by}",
                    )
                )

        # Negotiation outcome message
        negotiation = session.execute(
            select(Negotiation)
            .where(Negotiation.disruption_id == disruption_id)
            .order_by(Negotiation.ended_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        if negotiation and negotiation.status == "AGREED":
            messages.append(
                PhoneMessage(
                    at=to_iso(negotiation.ended_at),
                    direction="IN",
                    kind="RESULT",
                    text=f"Negotiation complete: {negotiation.transcript_summary[:100]}...",
                )
            )

    # Settlement batch messages
    batches = session.execute(
        select(SettlementBatchRow)
        .where(SettlementBatchRow.org_id == DEFAULT_ORG_ID)
        .order_by(SettlementBatchRow.staged_at.desc())
        .limit(3)
    ).scalars().all()

    for batch in batches:
        messages.append(
            PhoneMessage(
                at=to_iso(batch.staged_at),
                direction="IN",
                kind="TEXT",
                text=f"Settlement batch staged: {batch.item_count} items, {format_inr(batch.total_paise)} total",
            )
        )

    # Sort by timestamp (oldest first)
    messages.sort(key=lambda m: m.at)

    return {"messages": [m.model_dump() for m in messages]}
