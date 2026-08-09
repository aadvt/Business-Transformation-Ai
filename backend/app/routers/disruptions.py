from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db import get_db
from app.db_models import DisruptionEvent, Verification
from app.deps import require_api_key
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
from app.schemas.enums import (
    AgentName,
    ApprovalStatus,
    Channel,
    DetectorSource,
    DisruptionStage,
    DisruptionType,
    RootCause,
    VerificationStatus,
)
from app.schemas.money import format_inr
from app.schemas.vendors import VendorRef

router = APIRouter(prefix="/api/v1/disruptions", tags=["disruptions"], dependencies=[Depends(require_api_key)])

# One TimelineEvent per non-null stage-transition timestamp on
# disruption_events, in chronological column order — this is a better
# source of truth than the old hand-written fixture timeline list.
_TIMELINE_STEPS: list[tuple[str, DisruptionStage, AgentName]] = [
    ("detected_at", DisruptionStage.DETECTED, AgentName.SENTINEL),
    ("diagnosed_at", DisruptionStage.DIAGNOSED, AgentName.DIAGNOSIS),
    ("sourced_at", DisruptionStage.SOURCING, AgentName.SOURCING),
    ("approval_requested_at", DisruptionStage.AWAITING_APPROVAL, AgentName.GOVERNANCE),
    ("approved_at", DisruptionStage.APPROVED, AgentName.GOVERNANCE),
    ("negotiation_started_at", DisruptionStage.NEGOTIATING, AgentName.NEGOTIATION),
    ("negotiated_at", DisruptionStage.NEGOTIATED, AgentName.NEGOTIATION),
    ("settlement_staged_at", DisruptionStage.SETTLEMENT_PENDING, AgentName.SETTLEMENT),
    ("settled_at", DisruptionStage.SETTLED, AgentName.SETTLEMENT),
    ("closed_at", DisruptionStage.CLOSED, AgentName.GOVERNANCE),
]

_TIMELINE_NOTES: dict[DisruptionStage, str] = {
    DisruptionStage.DETECTED: "Signal raised ({detector})",
    DisruptionStage.DIAGNOSED: "Root cause identified",
    DisruptionStage.SOURCING: "Alternate vendor candidates matched and verified",
    DisruptionStage.AWAITING_APPROVAL: "Escalated for human approval",
    DisruptionStage.APPROVED: "Approved",
    DisruptionStage.NEGOTIATING: "Voice negotiation started",
    DisruptionStage.NEGOTIATED: "Terms agreed",
    DisruptionStage.SETTLEMENT_PENDING: "Queued into settlement batch",
    DisruptionStage.SETTLED: "Settlement executed",
    DisruptionStage.CLOSED: "Disruption closed",
}


def _build_timeline(d: DisruptionEvent) -> list[TimelineEvent]:
    events = []
    for attr, stage, agent in _TIMELINE_STEPS:
        at = getattr(d, attr)
        if at is None:
            continue
        note = _TIMELINE_NOTES[stage].format(detector=d.detector_name)
        events.append(TimelineEvent(stage=stage, at=at.isoformat(), agent=agent, note=note))
    return events


def _build_diagnosis(d: DisruptionEvent) -> Diagnosis:
    # root_cause/narrative are null until the DIAGNOSED stage — RootCause
    # already has an UNKNOWN member, which fits "not diagnosed yet" without
    # having to make the whole Diagnosis object optional.
    return Diagnosis(
        root_cause=RootCause(d.root_cause) if d.root_cause else RootCause.UNKNOWN,
        narrative=d.diagnosis_narrative or "",
        evidence=d.diagnosis_evidence or [],
        guardian=GuardianCheck(
            status=d.diagnosis_guardian_status or "PENDING",
            passed=bool(d.diagnosis_guardian_passed),
        ),
    )


def _build_exposure(d: DisruptionEvent) -> Exposure:
    calc = d.exposure_calc
    if calc is None:
        return Exposure(total_paise=0, total_display=format_inr(0), confidence=0.0, breakdown=[])
    # breakdown JSON already carries an amount_display, but the locked
    # money convention (backend/CLAUDE.md) is display strings are always
    # derived from paise at read time, never trusted as stored — recompute.
    return Exposure(
        total_paise=calc.total_paise,
        total_display=format_inr(calc.total_paise),
        confidence=calc.confidence,
        breakdown=[
            ExposureBreakdownItem(
                label=item["label"],
                amount_paise=item["amount_paise"],
                amount_display=format_inr(item["amount_paise"]),
                basis=item["basis"],
            )
            for item in (calc.breakdown or [])
        ],
    )


def _build_candidates(d: DisruptionEvent, verifications_by_vendor: dict[str, Verification]) -> list[SourcingCandidate]:
    candidates = []
    for c in d.candidates:
        v = verifications_by_vendor.get(c.vendor_id)
        if v is not None:
            verification = CandidateVerification(
                status=VerificationStatus(v.overall_status),
                gstin_status=VerificationStatus(v.gstin_status),
                udyam_status=VerificationStatus(v.udyam_status),
                checked_at=v.checked_at.isoformat(),
                source=v.source,
            )
        else:
            verification = CandidateVerification(
                status=VerificationStatus.UNAVAILABLE,
                gstin_status=VerificationStatus.UNAVAILABLE,
                udyam_status=VerificationStatus.UNAVAILABLE,
                checked_at=c.created_at.isoformat(),
                source="NOT_VERIFIED",
            )
        candidates.append(
            SourcingCandidate(
                vendor_id=c.vendor_id,
                name=c.vendor.name,
                match_score=c.match_score,
                verification=verification,
                quoted_lead_time_days=c.quoted_lead_time_days,
                quoted_unit_price_paise=c.quoted_unit_price_paise,
            )
        )
    return candidates


def _build_approval(d: DisruptionEvent) -> Approval | None:
    a = d.approval
    if a is None:
        return None
    return Approval(
        id=a.id,
        status=ApprovalStatus(a.status),
        requested_at=a.requested_at.isoformat(),
        decided_at=a.decided_at.isoformat() if a.decided_at else None,
        decided_by=a.decided_by,
        channel=Channel(a.channel) if a.channel else None,
    )


def _build_negotiation(d: DisruptionEvent) -> Negotiation | None:
    n = d.negotiation
    if n is None:
        return None
    opening_terms = None
    if n.opening_unit_price_paise is not None:
        opening_terms = NegotiationTerm(
            unit_price_paise=n.opening_unit_price_paise,
            lead_time_days=n.opening_lead_time_days or 0,
            payment_terms_days=n.opening_payment_terms_days or 0,
        )
    final_terms = None
    if n.agreed_unit_price_paise is not None:
        final_terms = NegotiationTerm(
            unit_price_paise=n.agreed_unit_price_paise,
            lead_time_days=n.agreed_lead_time_days or 0,
            payment_terms_days=n.agreed_payment_terms_days or 0,
        )
    return Negotiation(
        id=n.id,
        vendor_id=n.vendor_id,
        status=n.status,
        opening_terms=opening_terms,
        final_terms=final_terms,
        rounds=n.rounds,
        transcript_summary=n.transcript_summary,
        guardian=GuardianCheck(status=n.guardian_status, passed=n.guardian_status == "PASSED"),
    )


async def _to_disruption(d: DisruptionEvent, db: AsyncSession) -> Disruption:
    verifications = (
        (await db.execute(select(Verification).where(Verification.disruption_id == d.id))).scalars().all()
    )
    verifications_by_vendor = {v.vendor_id: v for v in verifications}

    return Disruption(
        id=d.id,
        type=DisruptionType(d.type),
        stage=DisruptionStage(d.stage),
        detected_at=d.detected_at.isoformat(),
        vendor=VendorRef(id=d.vendor.id, name=d.vendor.name, gstin=d.vendor.gstin),
        affected_po_ids=d.affected_po_ids or [],
        headline=d.headline,
        exposure=_build_exposure(d),
        diagnosis=_build_diagnosis(d),
        candidates=_build_candidates(d, verifications_by_vendor),
        approval=_build_approval(d),
        negotiation=_build_negotiation(d),
        timeline=_build_timeline(d),
        detector_source=DetectorSource(d.detector_source),
    )


@router.get("", response_model=DisruptionList)
async def list_disruptions(
    stage: DisruptionStage | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> DisruptionList:
    stmt = (
        select(DisruptionEvent)
        .where(DisruptionEvent.org_id == settings.org_id)
        .options(selectinload(DisruptionEvent.exposure_calc))  # .vendor is lazy="joined", already eager
        .order_by(DisruptionEvent.detected_at.desc())
    )
    if stage is not None:
        stmt = stmt.where(DisruptionEvent.stage == stage.value)
    stmt = stmt.limit(limit)

    rows = (await db.execute(stmt)).scalars().all()
    summaries = [
        DisruptionSummary(
            id=d.id,
            type=DisruptionType(d.type),
            stage=DisruptionStage(d.stage),
            detected_at=d.detected_at.isoformat(),
            vendor=VendorRef(id=d.vendor.id, name=d.vendor.name, gstin=d.vendor.gstin),
            headline=d.headline,
            exposure_total_paise=d.exposure_calc.total_paise if d.exposure_calc else 0,
            exposure_total_display=format_inr(d.exposure_calc.total_paise if d.exposure_calc else 0),
            detector_source=DetectorSource(d.detector_source),
        )
        for d in rows
    ]
    return DisruptionList(items=summaries, total=len(summaries))


@router.get("/{disruption_id}", response_model=Disruption)
async def get_disruption(disruption_id: str, db: AsyncSession = Depends(get_db)) -> Disruption:
    stmt = (
        select(DisruptionEvent)
        .where(DisruptionEvent.id == disruption_id)
        .options(
            selectinload(DisruptionEvent.exposure_calc),
            selectinload(DisruptionEvent.approval),
            selectinload(DisruptionEvent.negotiation),
            selectinload(DisruptionEvent.candidates),
        )
    )
    d = (await db.execute(stmt)).scalar_one_or_none()
    if d is None:
        raise HTTPException(status_code=404, detail="Disruption not found")
    return await _to_disruption(d, db)
