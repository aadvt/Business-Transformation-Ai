"""Remediation planner — deterministic optimization, zero LLM in solve path.

Given a disruption and ranked candidate vendors, produces a concrete plan
using OR-Tools CP-SAT, optimizing for cost + lateness penalty. Falls back to
greedy if solver unavailable or times out. Reuses compute_exposure for
after-exposure so there's one number formula everywhere.
"""

import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.db.models import DisruptionEvent, PurchaseOrder, VendorCandidate, RemediationPlanRow
from app.schemas.enums import PlanChangeKind
from app.schemas.money import format_inr, utc_now
from app.services.exposure import AffectedPO, BackupQuote, compute_exposure

MAX_PRICE_UPLIFT_PCT = 0.15  # 15% above incumbent


@dataclass(frozen=True)
class SolverResult:
    solver: str
    qty_by_vendor_id: dict[str, int]  # vendor_id -> qty
    pull_forward_qty: int
    solve_ms: float
    requires_escalation: bool
    escalation_reason: str | None


def _solve_greedy(
    required_qty: int,
    affected_pos: list[PurchaseOrder],
    candidates: list[VendorCandidate],
    reference_price_paise: int,
) -> SolverResult:
    """Greedy: fill from best-ranked candidate, overflow to next."""
    start = time.monotonic()
    qty_by_vendor = {}
    remaining_qty = required_qty

    for candidate in candidates:
        if remaining_qty <= 0:
            break
        # Assume candidate can provide up to required_qty
        qty = remaining_qty  # Take all remaining from this candidate
        qty_by_vendor[candidate.vendor_id] = qty
        remaining_qty = 0

    solve_ms = (time.monotonic() - start) * 1000
    return SolverResult(
        solver="GREEDY_FALLBACK",
        qty_by_vendor_id=qty_by_vendor,
        pull_forward_qty=0,
        solve_ms=solve_ms,
        requires_escalation=False,
        escalation_reason=None,
    )


def _solve_ortools(
    required_qty: int,
    affected_pos: list[PurchaseOrder],
    candidates: list[VendorCandidate],
    reference_price_paise: int,
    pull_forward_capacity: int = 0,
    max_lead_time_days: int = 30,
    per_unit_per_day_penalty: int = 1000,
) -> SolverResult:
    """OR-Tools CP-SAT solver. Falls back to greedy on error/timeout."""
    try:
        from ortools.sat.python import cp_model
    except ImportError:
        # OR-Tools not installed, fall back to greedy
        return _solve_greedy(required_qty, affected_pos, candidates, reference_price_paise)

    start = time.monotonic()
    model = cp_model.CpModel()

    # Decision variables
    vendor_qty = {c.vendor_id: model.NewIntVar(0, required_qty, f"qty_{c.vendor_id}") for c in candidates}
    pull_forward = model.NewIntVar(0, pull_forward_capacity, "pull_forward")

    # Constraint: total qty equals required
    model.Add(sum(vendor_qty.values()) + pull_forward == required_qty)

    # Constraint: each vendor's qty <= capacity (use quoted qty as proxy)
    for candidate in candidates:
        # Assume quoted qty is available; in reality would be candidate.capacity or similar
        max_qty = min(required_qty, 1000)  # Placeholder; real impl reads candidate.capacity
        model.Add(vendor_qty[candidate.vendor_id] <= max_qty)

    # Objective: minimize cost + lateness penalty
    cost_terms = []
    for candidate in candidates:
        qty_var = vendor_qty[candidate.vendor_id]
        cost_terms.append(qty_var * candidate.quoted_unit_price_paise)

    # Lateness penalty: qty × max(0, lead_time - safe_days)
    safe_days = 3  # Assume 3 days of cover needed
    lateness_terms = []
    for candidate in candidates:
        qty_var = vendor_qty[candidate.vendor_id]
        days_late = max(0, candidate.quoted_lead_time_days - safe_days)
        lateness_terms.append(qty_var * days_late * per_unit_per_day_penalty)

    objective = sum(cost_terms) + sum(lateness_terms)
    model.Minimize(objective)

    # Solve with 2-second timeout
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 2.0

    status = solver.Solve(model)
    solve_ms = (time.monotonic() - start) * 1000

    if status not in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        # Solve failed, fall back to greedy
        return _solve_greedy(required_qty, affected_pos, candidates, reference_price_paise)

    # Extract solution
    qty_by_vendor = {vid: int(solver.Value(qty_var)) for vid, qty_var in vendor_qty.items() if solver.Value(qty_var) > 0}
    pull_forward_qty = int(solver.Value(pull_forward))

    # Check for escalation (price uplift > MAX_PRICE_UPLIFT_PCT)
    requires_escalation = False
    escalation_reason = None
    for candidate in candidates:
        if qty_by_vendor.get(candidate.vendor_id, 0) > 0:
            uplift = (candidate.quoted_unit_price_paise - reference_price_paise) / reference_price_paise if reference_price_paise > 0 else 0
            if uplift > MAX_PRICE_UPLIFT_PCT:
                requires_escalation = True
                escalation_reason = f"Vendor {candidate.vendor_id} unit price uplift {uplift*100:.1f}% exceeds {MAX_PRICE_UPLIFT_PCT*100:.0f}% cap"
                break

    return SolverResult(
        solver="ORTOOLS_CPSAT",
        qty_by_vendor_id=qty_by_vendor,
        pull_forward_qty=pull_forward_qty,
        solve_ms=solve_ms,
        requires_escalation=requires_escalation,
        escalation_reason=escalation_reason,
    )


def build_plan(session: Session, disruption: DisruptionEvent, candidates: list[VendorCandidate]):
    """Build a remediation plan by solving the vendor allocation problem.

    Returns a RemediationPlanRow ready to persist.
    """
    # Gather affected POs
    if not disruption.affected_po_ids:
        return None

    affected_pos = session.query(PurchaseOrder).filter(PurchaseOrder.id.in_(disruption.affected_po_ids)).all()
    if not affected_pos:
        return None

    required_qty = sum(po.qty for po in affected_pos if po.delivered_at is None)
    reference_price = int(sum(po.unit_price_paise for po in affected_pos) / len(affected_pos)) if affected_pos else 0

    # Compute before-exposure
    affected_po_objs = [
        AffectedPO(
            po_id=po.id,
            po_number=po.po_number,
            undelivered_qty=po.qty if po.delivered_at is None else 0,
            unit_price_paise=po.unit_price_paise,
            downstream_order_ref=po.downstream_order_ref,
            downstream_order_value_paise=po.downstream_order_value_paise,
            penalty_rate_bps=po.penalty_rate_bps,
        )
        for po in affected_pos
    ]
    before_exposure = compute_exposure(affected_po_objs, production_critical=True)

    # Solve
    solver_result = _solve_ortools(
        required_qty=required_qty,
        affected_pos=affected_pos,
        candidates=candidates,
        reference_price_paise=reference_price,
    )

    # Build plan changes
    changes = []
    eta_base = disruption.detected_at + timedelta(days=7)  # Placeholder

    for vendor_id, qty in solver_result.qty_by_vendor_id.items():
        candidate = next((c for c in candidates if c.vendor_id == vendor_id), None)
        if not candidate:
            continue
        eta = eta_base + timedelta(days=candidate.quoted_lead_time_days)
        changes.append({
            "kind": PlanChangeKind.SWITCH_VENDOR.value,
            "vendor_id": vendor_id,
            "item_sku": affected_pos[0].item_sku if affected_pos else "",
            "qty": qty,
            "unit_price_paise": candidate.quoted_unit_price_paise,
            "unit_price_display": format_inr(candidate.quoted_unit_price_paise),
            "lead_time_days": candidate.quoted_lead_time_days,
            "eta_date": eta.isoformat()[:10],
            "rationale": "",  # Filled in by LLM layer
        })

    if solver_result.pull_forward_qty > 0:
        changes.append({
            "kind": PlanChangeKind.PULL_FORWARD_STOCK.value,
            "vendor_id": None,
            "item_sku": affected_pos[0].item_sku if affected_pos else "",
            "qty": solver_result.pull_forward_qty,
            "unit_price_paise": 0,
            "unit_price_display": "₹0",
            "lead_time_days": 0,
            "eta_date": disruption.detected_at.isoformat()[:10],
            "rationale": "Use existing inventory above safety stock",
        })

    # Compute after-exposure with substituted terms
    after_affected_pos = []
    for po in affected_po_objs:
        # Find how much of this PO is covered by plan
        # Simplified: assume all qty from candidates
        after_affected_pos.append(po)  # Would be modified by plan in real impl
    after_exposure = compute_exposure(after_affected_pos, production_critical=True)

    cost_to_resolve = sum(
        c["qty"] * c["unit_price_paise"]
        for c in changes
        if c["kind"] != PlanChangeKind.PULL_FORWARD_STOCK.value
    )
    net_saving = before_exposure.total_paise - after_exposure.total_paise - cost_to_resolve

    now = utc_now()
    plan_row = RemediationPlanRow(
        id=str(uuid.uuid4()),
        disruption_id=disruption.id,
        changes=changes,
        before_exposure_paise=before_exposure.total_paise,
        after_exposure_paise=after_exposure.total_paise,
        cost_to_resolve_paise=cost_to_resolve,
        net_saving_paise=max(0, net_saving),
        requires_escalation=solver_result.requires_escalation,
        escalation_reason=solver_result.escalation_reason,
        solve_ms=solver_result.solve_ms,
        solver=solver_result.solver,
        created_at=now,
    )

    return plan_row
