"""Disruption queries — assembles the richest object in the contract
(GET /disruptions/{id}) from disruption_events + exposure_calcs +
vendor_candidates + verifications + approvals + negotiations. `timeline` is
derived from disruption_events' explicit per-stage timestamp columns rather
than stored as its own table (see CLAUDE.md).
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Approval as ApprovalRow,
    DisruptionEvent,
    ExposureCalc,
    Negotiation as NegotiationRow,
    Vendor as VendorRow,
    VendorCandidate,
    Verification,
)
from app.schemas.disruptions import (
    Approval,
    CandidateVerification,
    Diagnosis,
    Disruption,
    DisruptionList,
    DisruptionSummary,
    Exposure,
    ExposureBreakdownItem,
    GuardianCheck,
    Negotiation,
    NegotiationTerm,
    SourcingCandidate,
    TimelineEvent,
)
from app.schemas.enums import ApprovalStatus, VerificationStatus
from app.schemas.money import format_inr, to_iso
from app.schemas.vendors import VendorRef

_STAGE_TIMESTAMP_FIELDS = [
    ("DETECTED", "detected_at", "SENTINEL", "Disruption detected"),
    ("DIAGNOSED", "diagnosed_at", "DIAGNOSIS", "Root cause diagnosed"),
    ("SOURCING", "sourced_at", "SOURCING", "Alternate vendor candidates matched"),
    ("AWAITING_APPROVAL", "approval_requested_at", "GOVERNANCE", "Escalated for human approval"),
    ("APPROVED", "approved_at", "GOVERNANCE", "Approval decided"),
    ("NEGOTIATING", "negotiation_started_at", "NEGOTIATION", "Vendor negotiation started"),
    ("NEGOTIATED", "negotiated_at", "NEGOTIATION", "Negotiation terms agreed"),
    ("SETTLEMENT_PENDING", "settlement_staged_at", "SETTLEMENT", "Queued into settlement batch"),
    ("SETTLED", "settled_at", "SETTLEMENT", "Settlement confirmed"),
]


def _exposure_schema(calc: ExposureCalc | None) -> Exposure:
    if calc is None:
        return Exposure(total_paise=0, total_display=format_inr(0), confidence=0.0, breakdown=[])
    return Exposure(
        total_paise=calc.total_paise,
        total_display=format_inr(calc.total_paise),
        confidence=calc.confidence,
        breakdown=[ExposureBreakdownItem.model_validate(item) for item in calc.breakdown],
    )


def _diagnosis_schema(row: DisruptionEvent) -> Diagnosis:
    return Diagnosis(
        root_cause=row.root_cause or "UNKNOWN",
        narrative=row.diagnosis_narrative or "Diagnosis pending.",
        evidence=row.diagnosis_evidence or [],
        guardian=GuardianCheck(
            status=row.diagnosis_guardian_status or "PENDING",
            passed=bool(row.diagnosis_guardian_passed),
        ),
    )


def _candidates_schema(session: Session, disruption_id: str) -> list[SourcingCandidate]:
    rows = session.execute(
        select(VendorCandidate).where(VendorCandidate.disruption_id == disruption_id).order_by(VendorCandidate.rank)
    ).scalars().all()

    out: list[SourcingCandidate] = []
    for row in rows:
        vendor = session.get(VendorRow, row.vendor_id)
        verification = session.execute(
            select(Verification)
            .where(Verification.vendor_id == row.vendor_id, Verification.disruption_id == disruption_id)
            .order_by(Verification.checked_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        if verification is not None:
            v = CandidateVerification(
                status=verification.overall_status,
                gstin_status=verification.gstin_status,
                udyam_status=verification.udyam_status,
                checked_at=to_iso(verification.checked_at),
                source=verification.source,
            )
        else:
            v = CandidateVerification(
                status=VerificationStatus.UNAVAILABLE, gstin_status=VerificationStatus.UNAVAILABLE,
                udyam_status=VerificationStatus.UNAVAILABLE, checked_at=to_iso(row.created_at), source="NONE",
            )

        out.append(
            SourcingCandidate(
                vendor_id=row.vendor_id,
                name=vendor.name if vendor else "Unknown vendor",
                match_score=row.match_score,
                verification=v,
                quoted_lead_time_days=row.quoted_lead_time_days,
                quoted_unit_price_paise=row.quoted_unit_price_paise,
            )
        )
    return out


def _approval_schema(session: Session, disruption_id: str) -> Approval | None:
    row = session.execute(
        select(ApprovalRow).where(ApprovalRow.disruption_id == disruption_id).order_by(ApprovalRow.requested_at.desc()).limit(1)
    ).scalar_one_or_none()
    if row is None:
        return None
    return Approval(
        id=row.id,
        status=row.status,
        requested_at=to_iso(row.requested_at),
        decided_at=to_iso(row.decided_at) if row.decided_at else None,
        decided_by=row.decided_by,
        channel=row.channel,
    )


def _negotiation_schema(session: Session, disruption_id: str) -> Negotiation | None:
    row = session.execute(
        select(NegotiationRow).where(NegotiationRow.disruption_id == disruption_id).order_by(NegotiationRow.id).limit(1)
    ).scalar_one_or_none()
    if row is None:
        return None

    opening = None
    if row.opening_unit_price_paise is not None:
        opening = NegotiationTerm(
            unit_price_paise=row.opening_unit_price_paise,
            lead_time_days=row.opening_lead_time_days or 0,
            payment_terms_days=row.opening_payment_terms_days or 0,
        )
    final = None
    if row.agreed_unit_price_paise is not None:
        final = NegotiationTerm(
            unit_price_paise=row.agreed_unit_price_paise,
            lead_time_days=row.agreed_lead_time_days or 0,
            payment_terms_days=row.agreed_payment_terms_days or 0,
        )

    return Negotiation(
        id=row.id,
        vendor_id=row.vendor_id,
        status=row.status,
        opening_terms=opening,
        final_terms=final,
        rounds=row.rounds,
        transcript_summary=row.transcript_summary,
        guardian=GuardianCheck(status=row.guardian_status, passed=row.guardian_status == "PASSED"),
    )


def _timeline_schema(row: DisruptionEvent, approval: Approval | None) -> list[TimelineEvent]:
    events: list[TimelineEvent] = []
    for stage, field, agent, note in _STAGE_TIMESTAMP_FIELDS:
        at = getattr(row, field, None)
        if at is None:
            continue
        stage_label = stage
        if stage == "APPROVED" and approval is not None:
            stage_label = approval.status if approval.status in ("APPROVED", "REJECTED") else "APPROVED"
        events.append(TimelineEvent(stage=stage_label, at=to_iso(at), agent=agent, note=note))
    return events


def _full_schema(session: Session, row: DisruptionEvent) -> Disruption:
    vendor = session.get(VendorRow, row.vendor_id)
    calc = session.execute(
        select(ExposureCalc).where(ExposureCalc.disruption_id == row.id).order_by(ExposureCalc.computed_at.desc()).limit(1)
    ).scalar_one_or_none()
    approval = _approval_schema(session, row.id)

    return Disruption(
        id=row.id,
        type=row.type,
        stage=row.stage,
        detected_at=to_iso(row.detected_at),
        vendor=VendorRef(id=vendor.id, name=vendor.name, gstin=vendor.gstin) if vendor else VendorRef(id=row.vendor_id, name="Unknown", gstin=""),
        affected_po_ids=row.affected_po_ids or [],
        headline=row.headline,
        exposure=_exposure_schema(calc),
        diagnosis=_diagnosis_schema(row),
        candidates=_candidates_schema(session, row.id),
        approval=approval,
        negotiation=_negotiation_schema(session, row.id),
        timeline=_timeline_schema(row, approval),
        detector_source=row.detector_source,
    )


def list_disruptions(session: Session, stage: str | None, limit: int) -> DisruptionList:
    query = select(DisruptionEvent).order_by(DisruptionEvent.detected_at.desc())
    if stage:
        query = query.where(DisruptionEvent.stage == stage)
    rows = session.execute(query.limit(limit)).scalars().all()

    summaries: list[DisruptionSummary] = []
    for row in rows:
        vendor = session.get(VendorRow, row.vendor_id)
        calc = session.execute(
            select(ExposureCalc).where(ExposureCalc.disruption_id == row.id).order_by(ExposureCalc.computed_at.desc()).limit(1)
        ).scalar_one_or_none()
        total_paise = calc.total_paise if calc else 0
        summaries.append(
            DisruptionSummary(
                id=row.id, type=row.type, stage=row.stage, detected_at=to_iso(row.detected_at),
                vendor=VendorRef(id=vendor.id, name=vendor.name, gstin=vendor.gstin) if vendor else VendorRef(id=row.vendor_id, name="Unknown", gstin=""),
                headline=row.headline, exposure_total_paise=total_paise, exposure_total_display=format_inr(total_paise),
                detector_source=row.detector_source,
            )
        )
    return DisruptionList(items=summaries, total=len(summaries))


def get_disruption(session: Session, disruption_id: str) -> Disruption | None:
    row = session.get(DisruptionEvent, disruption_id)
    if row is None:
        return None
    return _full_schema(session, row)


def get_disruption_row(session: Session, disruption_id: str) -> DisruptionEvent | None:
    return session.get(DisruptionEvent, disruption_id)
