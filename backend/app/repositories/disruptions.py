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
    Organisation,
    PurchaseOrder,
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
    from app.db.models import AuditLogEntry

    rows = session.execute(
        select(VendorCandidate).where(VendorCandidate.disruption_id == disruption_id).order_by(VendorCandidate.rank)
    ).scalars().all()
    if not rows:
        return []

    # Everything the loop needs, fetched once. GET /disruptions/{id} is on the
    # critical path of the demo (it drives the candidate rail), so per-candidate
    # round-trips to Neon are latency the operator watches.
    candidate_vendor_ids = [r.vendor_id for r in rows]
    vendors_by_id = {
        v.id: v
        for v in session.execute(select(VendorRow).where(VendorRow.id.in_(candidate_vendor_ids))).scalars().all()
    }
    verification_by_vendor = {
        v.vendor_id: v
        for v in session.execute(
            select(Verification)
            .where(Verification.vendor_id.in_(candidate_vendor_ids), Verification.disruption_id == disruption_id)
            .order_by(Verification.checked_at.asc())  # ascending: last write wins
        ).scalars().all()
    }
    audit_by_vendor = {
        str(e.detail.get("vendor_id")): e
        for e in session.execute(
            select(AuditLogEntry)
            .where(AuditLogEntry.disruption_id == disruption_id, AuditLogEntry.action == "CANDIDATE_SCORED")
            .order_by(AuditLogEntry.at.asc())
        ).scalars().all()
        if isinstance(e.detail, dict)
    }

    # Shared by every candidate: the disruption, its org's plant, and the
    # incumbent PO the price delta is measured against.
    disruption = session.get(DisruptionEvent, disruption_id)
    org = session.get(Organisation, disruption.org_id) if disruption else None
    incumbent_po = None
    if disruption and disruption.affected_po_ids:
        incumbent_po = session.execute(
            select(PurchaseOrder).where(PurchaseOrder.id.in_(disruption.affected_po_ids)).limit(1)
        ).scalars().first()

    out: list[SourcingCandidate] = []
    for row in rows:
        vendor = vendors_by_id.get(row.vendor_id)
        verification = verification_by_vendor.get(row.vendor_id)

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

        # Score components, as logged per candidate by the sourcing agent.
        score_components = None
        audit_entry = audit_by_vendor.get(row.vendor_id)
        if audit_entry is not None:
            score_components = {
                "reliability": audit_entry.detail.get("reliability_component"),
                "lead_time": audit_entry.detail.get("lead_time_component"),
                "price": audit_entry.detail.get("price_component"),
                "geography": audit_entry.detail.get("geography_component"),
                "relationship": audit_entry.detail.get("relationship_component"),
            }

        # Display enrichment for the candidate rail: distance from the org's
        # plant, reliability, languages, and price delta vs the incumbent PO.
        distance_km = None
        price_delta_pct = None
        if vendor is not None:
            if org and org.lat is not None and vendor.lat is not None:
                distance_km = _haversine_km(org.lat, org.lng, vendor.lat, vendor.lng)
            if incumbent_po and incumbent_po.unit_price_paise:
                price_delta_pct = round(
                    (row.quoted_unit_price_paise - incumbent_po.unit_price_paise)
                    / incumbent_po.unit_price_paise
                    * 100,
                    1,
                )

        out.append(
            SourcingCandidate(
                vendor_id=row.vendor_id,
                name=vendor.name if vendor else "Unknown vendor",
                match_score=row.match_score,
                verification=v,
                quoted_lead_time_days=row.quoted_lead_time_days,
                quoted_unit_price_paise=row.quoted_unit_price_paise,
                score_components=score_components,
                distance_km=round(distance_km, 1) if distance_km is not None else None,
                reliability_score_0_100=vendor.reliability_score if vendor else None,
                languages=vendor.languages if vendor else None,
                price_delta_pct=price_delta_pct,
            )
        )
    return out


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    import math

    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(a)))


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

    # Two batched lookups instead of two queries per row — this list backs the
    # rail on every dashboard page, so a per-row round-trip to Neon showed up
    # as multiple seconds of blank screen on load.
    vendor_ids = {r.vendor_id for r in rows}
    vendors_by_id = {
        v.id: v
        for v in session.execute(select(VendorRow).where(VendorRow.id.in_(vendor_ids))).scalars().all()
    } if vendor_ids else {}

    latest_exposure_by_disruption: dict[str, int] = {}
    if rows:
        calcs = session.execute(
            select(ExposureCalc)
            .where(ExposureCalc.disruption_id.in_([r.id for r in rows]))
            .order_by(ExposureCalc.computed_at.asc())
        ).scalars().all()
        # Ascending order means the last write per disruption wins — the same
        # "most recent computed_at" rule the per-row query used.
        for calc in calcs:
            latest_exposure_by_disruption[calc.disruption_id] = calc.total_paise

    summaries: list[DisruptionSummary] = []
    for row in rows:
        vendor = vendors_by_id.get(row.vendor_id)
        total_paise = latest_exposure_by_disruption.get(row.id, 0)
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
