"""Diagnosis — computes exposure (pure Python, see app.services.exposure) and
asks the LLM for exactly two things it's actually suited for: a root-cause
classification and a plain-English narrative explaining numbers Python already
computed. The LLM never touches the arithmetic.

Guardian checkpoint #1: the narrative is checked for groundedness against the
same evidence it was built from. Ungrounded once -> regenerate. Ungrounded
twice -> fall back to a narrative built by plain string formatting from the
exposure breakdown (`diagnosis_narrative_source="TEMPLATE"`), never silently
publish an ungrounded claim.
"""

import uuid

from pydantic import BaseModel, Field
from sqlalchemy import exists, select

from app.agents.base import Agent, AgentContext, AgentResult
from app.config import settings
from app.db.models import DisruptionEvent, ExposureCalc, InventorySnapshot, PurchaseOrder, Vendor as VendorRow
from app.llm import prompts
from app.llm.client import LLMSchemaError, get_llm
from app.llm.guardian import GuardianRisk, get_guardian
from app.schemas.enums import AgentName, AgentStatus, RootCause
from app.schemas.money import format_inr, utc_now
from app.services.exposure import AffectedPO, ExposureResult, compute_exposure


class DiagnosisClassification(BaseModel):
    root_cause: RootCause
    narrative: str = Field(max_length=280)
    evidence: list[str]


def _guardian_check_schema(verdict) -> dict:
    """Maps a GuardianVerdict onto the Phase 1 contract's {status, passed}
    shape used for disruption.diagnosis.guardian everywhere in the API."""
    if verdict.status != "OK":
        return {"status": "UNAVAILABLE", "passed": True}
    return {"status": "PASSED" if verdict.passed else "FAILED", "passed": verdict.passed}


def _is_production_critical(session, item_skus: list[str]) -> bool:
    """A SKU we actively track in inventory_snapshots is one whose consumption
    rate we actually know — that's the honest signal for "is this line
    production-critical", not a guess. See app/services/exposure.py."""
    if not item_skus:
        return False
    return session.execute(
        select(exists().where(InventorySnapshot.sku.in_(item_skus)))
    ).scalar_one()


def _template_narrative(exposure: ExposureResult, root_cause: RootCause) -> str:
    top_items = exposure.breakdown[:2]
    if top_items:
        parts = "; ".join(f"{item.label} ({format_inr(item.amount_paise)})" for item in top_items)
        return (
            f"Automated diagnosis (root cause: {root_cause.value.replace('_', ' ').lower()}). "
            f"Exposure of {format_inr(exposure.total_paise)} computed from verified order data: {parts}."
        )[:280]
    return (
        f"Automated diagnosis (root cause: {root_cause.value.replace('_', ' ').lower()}). "
        "No financial exposure could be computed from available data."
    )[:280]


class DiagnosisAgent(Agent):
    name = AgentName.DIAGNOSIS

    def _execute(self, ctx: AgentContext) -> AgentResult:
        session = ctx.session
        disruption_id = ctx.disruption_id
        if not disruption_id:
            return AgentResult(status=AgentStatus.ERROR, error="DiagnosisAgent requires ctx.disruption_id")

        disruption = session.get(DisruptionEvent, disruption_id)
        if disruption is None:
            return AgentResult(status=AgentStatus.ERROR, error=f"No disruption {disruption_id}")

        vendor = session.get(VendorRow, disruption.vendor_id)
        vendor_name = vendor.name if vendor else "Unknown vendor"

        # --- gather evidence, build exposure inputs (pure data, no arithmetic yet) ---
        po_rows = []
        if disruption.affected_po_ids:
            po_rows = session.execute(
                select(PurchaseOrder).where(PurchaseOrder.id.in_(disruption.affected_po_ids))
            ).scalars().all()

        affected_pos = [
            AffectedPO(
                po_id=po.id,
                po_number=po.po_number,
                undelivered_qty=po.qty if po.delivered_at is None else 0,
                unit_price_paise=po.unit_price_paise,
                downstream_order_ref=po.downstream_order_ref,
                downstream_order_value_paise=po.downstream_order_value_paise,
                penalty_rate_bps=po.penalty_rate_bps,
            )
            for po in po_rows
        ]

        item_skus = [po.item_sku for po in po_rows]
        consumption_known = _is_production_critical(session, item_skus)

        idle_days = 0
        if disruption.detector_name == "overdue_delivery":
            idle_days = int(disruption.signal_payload.get("days_late", 0))

        exposure_result = compute_exposure(
            affected_pos,
            idle_days=idle_days,
            daily_line_cost_paise=settings.daily_line_cost_paise,
            production_critical=consumption_known,
            consumption_rate_known=consumption_known,
            best_backup_quote=None,  # recomputed by Sourcing once candidates exist
        )

        # --- ONE LLM call: root cause + narrative, given evidence + the computed breakdown ---
        evidence_lines = "\n".join(f"- {item.label}: {item.basis}" for item in exposure_result.breakdown)
        user_prompt = (
            f"Disruption: {disruption.headline}\n"
            f"Type: {disruption.type}\n"
            f"Vendor: {vendor_name}\n"
            f"Detector: {disruption.detector_name}\n"
            f"Raw signal evidence: {disruption.signal_payload}\n"
            f"Computed financial exposure breakdown:\n{evidence_lines or '(no exposure could be computed)'}\n"
            f"Total exposure: {format_inr(exposure_result.total_paise)} "
            f"(confidence {exposure_result.confidence:.2f})"
        )

        llm = get_llm()
        guardian = get_guardian()
        context_text = user_prompt  # what Guardian checks the narrative's claims against

        try:
            classification = llm.complete(
                prompts.DIAGNOSIS_NARRATIVE_V1, user_prompt, schema=DiagnosisClassification,
                tag=prompts.TAG_DIAGNOSIS_NARRATIVE, max_tokens=500, disruption_id=disruption_id,
            ).parsed
            narrative_source = "LLM"
            narrative = classification.narrative
            verdict = guardian.check(
                narrative, risk=GuardianRisk.GROUNDEDNESS, context=context_text, disruption_id=disruption_id
            )
        except LLMSchemaError:
            # The model can fail the schema (e.g. narrative over 280 chars) on
            # both its first try AND the client's own repair round-trip — that
            # is a different failure from a grounded-but-wrong narrative, but
            # the fix is the same: never let it crash the disruption, fall
            # back to a narrative built by Python from data already computed.
            classification = DiagnosisClassification(
                root_cause=RootCause.UNKNOWN,
                narrative=_template_narrative(exposure_result, RootCause.UNKNOWN)[:280],
                evidence=["LLM output could not be parsed into the required schema; falling back to computed data only."],
            )
            narrative = classification.narrative
            narrative_source = "TEMPLATE"
            verdict = guardian.check(
                narrative, risk=GuardianRisk.GROUNDEDNESS, context=context_text, disruption_id=disruption_id
            )

        if narrative_source == "LLM" and verdict.status == "OK" and not verdict.passed:
            # Regenerate once, nudged toward staying inside the given evidence.
            retry_prompt = (
                user_prompt
                + "\n\nYour previous narrative made claims not supported by the evidence above. "
                "Rewrite it using ONLY the facts given."
            )
            try:
                classification = llm.complete(
                    prompts.DIAGNOSIS_NARRATIVE_V1, retry_prompt, schema=DiagnosisClassification,
                    tag=prompts.TAG_DIAGNOSIS_NARRATIVE, max_tokens=500, disruption_id=disruption_id,
                ).parsed
                narrative = classification.narrative
            except LLMSchemaError:
                pass  # keep the first (ungrounded) narrative text; the check below will template it

            verdict = guardian.check(
                narrative, risk=GuardianRisk.GROUNDEDNESS, context=context_text, disruption_id=disruption_id
            )
            if verdict.status == "OK" and not verdict.passed:
                narrative = _template_narrative(exposure_result, classification.root_cause)
                narrative_source = "TEMPLATE"

        # --- persist: exposure_calcs row is the arithmetic defence ---
        exposure_calc_id = str(uuid.uuid4())
        now = utc_now()
        session.add(
            ExposureCalc(
                id=exposure_calc_id,
                disruption_id=disruption_id,
                total_paise=exposure_result.total_paise,
                confidence=exposure_result.confidence,
                breakdown=[
                    {
                        "label": item.label,
                        "amount_paise": item.amount_paise,
                        "amount_display": format_inr(item.amount_paise),
                        "basis": item.basis,
                    }
                    for item in exposure_result.breakdown
                ],
                inputs=exposure_result.inputs,
                formula_version=exposure_result.formula_version,
                computed_at=now,
            )
        )

        # Diagnosis writes its own findings only — stage/timestamp transitions
        # are the orchestrator's exclusive job (app.orchestrator.engine), so
        # every transition is provably auditable in one place.
        disruption.root_cause = classification.root_cause.value
        disruption.diagnosis_narrative = narrative
        disruption.diagnosis_evidence = classification.evidence
        disruption.diagnosis_narrative_source = narrative_source
        guardian_schema = _guardian_check_schema(verdict)
        disruption.diagnosis_guardian_status = guardian_schema["status"]
        disruption.diagnosis_guardian_passed = guardian_schema["passed"]

        return AgentResult(
            status=AgentStatus.DONE,
            summary=(
                f"Root cause {classification.root_cause.value}, exposure {format_inr(exposure_result.total_paise)} "
                f"(confidence {exposure_result.confidence:.2f}), narrative_source={narrative_source}"
            ),
            data={
                "exposure_calc_id": exposure_calc_id,
                "total_paise": exposure_result.total_paise,
                "confidence": exposure_result.confidence,
                "root_cause": classification.root_cause.value,
                "narrative_source": narrative_source,
                "guardian": guardian_schema,
            },
        )
