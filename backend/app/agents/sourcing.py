"""Sourcing — finds and ranks alternate vendors, verifies them, and (once a
best quote exists) hands the exposure engine what it needs to price expediting.

Ranking is a deterministic weighted score (weights in config, each component
computed and logged so it's explainable) — the LLM's only job here is writing
a one-line business-language rationale per already-ranked candidate. It never
sees the score and cannot change the ranking.
"""

import math
import statistics
import uuid

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.base import Agent, AgentContext, AgentResult
from app.agents.diagnosis import _is_production_critical
from app.config import settings
from app.constants import DEFAULT_ORG_ID
from app.db.models import (
    DisruptionEvent,
    ExposureCalc,
    Organisation,
    PurchaseOrder,
    Vendor as VendorRow,
    VendorCandidate,
)
from app.llm import prompts
from app.llm.client import LLMSchemaError, get_llm
from app.schemas.enums import AgentName, AgentStatus
from app.schemas.money import format_inr, utc_now
from app.services.audit import append_audit
from app.services.exposure import AffectedPO, BackupQuote, compute_exposure
from app.services.verification import verify_vendor

TOP_N_CANDIDATES = 3
_MAX_DISTANCE_KM = 2500.0  # roughly spans India end-to-end; caps the geo score at 0 beyond this
_EARTH_RADIUS_KM = 6371.0


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


class CandidateScore(BaseModel):
    vendor_id: str
    vendor_name: str
    reliability_component: float
    lead_time_component: float
    price_component: float
    geography_component: float
    relationship_component: float
    match_score: float
    quoted_unit_price_paise: int
    quoted_lead_time_days: int
    distance_km: float


def _score_candidate(
    candidate: VendorRow, *, reference_price_paise: float, plant_lat: float, plant_lng: float,
    candidate_avg_price_paise: int | None,
) -> CandidateScore:
    quoted_price = candidate_avg_price_paise if candidate_avg_price_paise else int(reference_price_paise)
    quoted_lead_time = int(round(candidate.avg_lead_time_days)) if candidate.avg_lead_time_days > 0 else settings.max_lead_time_days

    reliability_c = candidate.reliability_score / 100.0
    lead_time_c = _clamp01(1 - (quoted_lead_time / settings.max_lead_time_days))
    price_c = (
        _clamp01(1 - abs(quoted_price - reference_price_paise) / reference_price_paise)
        if reference_price_paise > 0
        else 0.5
    )
    distance_km = _haversine_km(candidate.lat, candidate.lng, plant_lat, plant_lng)
    geography_c = _clamp01(1 - distance_km / _MAX_DISTANCE_KM)
    relationship_c = 1.0 if candidate.orders_completed > 0 else 0.0

    match_score = (
        settings.sourcing_weight_reliability * reliability_c
        + settings.sourcing_weight_lead_time * lead_time_c
        + settings.sourcing_weight_price * price_c
        + settings.sourcing_weight_geography * geography_c
        + settings.sourcing_weight_relationship * relationship_c
    )

    return CandidateScore(
        vendor_id=candidate.id,
        vendor_name=candidate.name,
        reliability_component=round(reliability_c, 4),
        lead_time_component=round(lead_time_c, 4),
        price_component=round(price_c, 4),
        geography_component=round(geography_c, 4),
        relationship_component=round(relationship_c, 4),
        match_score=round(match_score, 4),
        quoted_unit_price_paise=quoted_price,
        quoted_lead_time_days=quoted_lead_time,
        distance_km=round(distance_km, 1),
    )


def _candidate_avg_price(session: Session, vendor_id: str) -> int | None:
    prices = session.execute(
        select(PurchaseOrder.unit_price_paise).where(PurchaseOrder.vendor_id == vendor_id)
    ).scalars().all()
    return int(statistics.mean(prices)) if prices else None


class CandidateRationale(BaseModel):
    vendor_name: str
    rationale: str = Field(max_length=300)


class SourcingRationales(BaseModel):
    candidates: list[CandidateRationale]


class SourcingAgent(Agent):
    name = AgentName.SOURCING

    def _execute(self, ctx: AgentContext) -> AgentResult:
        session = ctx.session
        disruption_id = ctx.disruption_id
        if not disruption_id:
            return AgentResult(status=AgentStatus.ERROR, error="SourcingAgent requires ctx.disruption_id")

        disruption = session.get(DisruptionEvent, disruption_id)
        if disruption is None:
            return AgentResult(status=AgentStatus.ERROR, error=f"No disruption {disruption_id}")

        failed_vendor = session.get(VendorRow, disruption.vendor_id)
        if failed_vendor is None:
            return AgentResult(status=AgentStatus.ERROR, error=f"No vendor {disruption.vendor_id}")

        org = session.get(Organisation, ctx.org_id) or session.get(Organisation, DEFAULT_ORG_ID)

        pool = session.execute(
            select(VendorRow).where(
                VendorRow.org_id == ctx.org_id,
                VendorRow.category == failed_vendor.category,
                VendorRow.id != failed_vendor.id,
            )
        ).scalars().all()

        if not pool:
            return AgentResult(
                status=AgentStatus.DONE,
                summary=f"No alternate vendors found in category '{failed_vendor.category}'.",
                data={"candidate_count": 0},
            )

        affected_pos = []
        if disruption.affected_po_ids:
            affected_pos = session.execute(
                select(PurchaseOrder).where(PurchaseOrder.id.in_(disruption.affected_po_ids))
            ).scalars().all()
        reference_price = (
            statistics.median(po.unit_price_paise for po in affected_pos) if affected_pos else 0.0
        )

        scores = [
            _score_candidate(
                v, reference_price_paise=reference_price, plant_lat=org.lat, plant_lng=org.lng,
                candidate_avg_price_paise=_candidate_avg_price(session, v.id),
            )
            for v in pool
        ]
        scores.sort(key=lambda s: (-s.match_score, s.vendor_name))
        top_scores = scores[:TOP_N_CANDIDATES]

        for s in top_scores:
            append_audit(
                session, org_id=ctx.org_id, disruption_id=disruption_id, actor_type="AGENT", actor="SOURCING",
                action="CANDIDATE_SCORED",
                detail={
                    "vendor_id": s.vendor_id, "vendor_name": s.vendor_name, "match_score": s.match_score,
                    "reliability_component": s.reliability_component, "lead_time_component": s.lead_time_component,
                    "price_component": s.price_component, "geography_component": s.geography_component,
                    "relationship_component": s.relationship_component, "distance_km": s.distance_km,
                    "weights": {
                        "reliability": settings.sourcing_weight_reliability,
                        "lead_time": settings.sourcing_weight_lead_time,
                        "price": settings.sourcing_weight_price,
                        "geography": settings.sourcing_weight_geography,
                        "relationship": settings.sourcing_weight_relationship,
                    },
                },
            )

        verifications = {}
        for s in top_scores:
            vendor_row = session.get(VendorRow, s.vendor_id)
            verifications[s.vendor_id] = verify_vendor(session, vendor_row, disruption_id=disruption_id)

        # --- ONE LLM call: a business-language rationale per already-ranked candidate ---
        candidate_summary = "\n".join(
            f"- {s.vendor_name}: match_score={s.match_score:.2f}, reliability={s.reliability_component:.2f}, "
            f"lead_time_fit={s.lead_time_component:.2f}, price_fit={s.price_component:.2f}, "
            f"quoted_price={format_inr(s.quoted_unit_price_paise)}, quoted_lead_time={s.quoted_lead_time_days} days, "
            f"verification={verifications[s.vendor_id].overall_status.value}"
            for s in top_scores
        )
        user_prompt = (
            f"Disrupted vendor: {failed_vendor.name} ({failed_vendor.category})\n"
            f"Disruption: {disruption.headline}\n"
            f"Ranked candidates (already scored and ordered — do not re-rank):\n{candidate_summary}"
        )

        rationale_by_name: dict[str, str] = {}
        try:
            result = get_llm().complete(
                prompts.SOURCING_RATIONALE_V1, user_prompt, schema=SourcingRationales,
                tag=prompts.TAG_SOURCING_RATIONALE, max_tokens=600, disruption_id=disruption_id,
            )
            rationale_by_name = {c.vendor_name: c.rationale for c in result.parsed.candidates}
        except LLMSchemaError:
            pass  # fall through to the deterministic default below for every candidate

        candidate_ids: list[str] = []
        now = utc_now()
        for rank, s in enumerate(top_scores, start=1):
            rationale = rationale_by_name.get(
                s.vendor_name,
                f"Ranked #{rank} with a {s.match_score:.2f} match score "
                f"(reliability {s.reliability_component:.2f}, price fit {s.price_component:.2f}).",
            )
            candidate_id = str(uuid.uuid4())
            session.add(
                VendorCandidate(
                    id=candidate_id,
                    disruption_id=disruption_id,
                    vendor_id=s.vendor_id,
                    match_score=s.match_score,
                    rank=rank,
                    rationale=rationale[:500],
                    quoted_unit_price_paise=s.quoted_unit_price_paise,
                    quoted_lead_time_days=s.quoted_lead_time_days,
                    created_at=now,
                )
            )
            candidate_ids.append(candidate_id)

        # --- recompute exposure now that a best quote exists (expedite_premium) ---
        if affected_pos and top_scores:
            best = top_scores[0]
            exposure_inputs = [
                AffectedPO(
                    po_id=po.id, po_number=po.po_number,
                    undelivered_qty=po.qty if po.delivered_at is None else 0,
                    unit_price_paise=po.unit_price_paise,
                    downstream_order_ref=po.downstream_order_ref,
                    downstream_order_value_paise=po.downstream_order_value_paise,
                    penalty_rate_bps=po.penalty_rate_bps,
                )
                for po in affected_pos
            ]
            idle_days = int(disruption.signal_payload.get("days_late", 0)) if disruption.detector_name == "overdue_delivery" else 0
            consumption_known = _is_production_critical(session, [po.item_sku for po in affected_pos])
            recomputed = compute_exposure(
                exposure_inputs,
                idle_days=idle_days,
                daily_line_cost_paise=settings.daily_line_cost_paise,
                production_critical=consumption_known,
                consumption_rate_known=consumption_known,
                best_backup_quote=BackupQuote(vendor_name=best.vendor_name, unit_price_paise=best.quoted_unit_price_paise),
            )
            session.add(
                ExposureCalc(
                    id=str(uuid.uuid4()),
                    disruption_id=disruption_id,
                    total_paise=recomputed.total_paise,
                    confidence=recomputed.confidence,
                    breakdown=[
                        {
                            "label": item.label, "amount_paise": item.amount_paise,
                            "amount_display": format_inr(item.amount_paise), "basis": item.basis,
                        }
                        for item in recomputed.breakdown
                    ],
                    inputs=recomputed.inputs,
                    formula_version=recomputed.formula_version,
                    computed_at=now,
                )
            )

        return AgentResult(
            status=AgentStatus.DONE,
            summary=f"Ranked {len(scores)} candidate(s) in '{failed_vendor.category}', persisted top {len(top_scores)}.",
            data={"candidate_ids": candidate_ids, "candidate_count": len(top_scores), "pool_size": len(scores)},
        )
