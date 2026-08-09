"""Impact graph — the disruption's blast radius as a layered node/edge graph
the frontend renders and animates.

Deterministic graph traversal only, same principle as app/services/exposure.py:
no LLM call anywhere in this module, so every node/edge on screen is
explainable by reading this file. The summary block does NOT recompute
exposure — it reads the disruption's existing, already-persisted
exposure_calcs row (the same one repositories/disruptions.py reads for
GET /disruptions/{id}) so the graph and the rest of the UI never disagree
about the number.

Layers (left to right):
  0  VENDOR  the disrupted vendor
  1  ITEM    distinct item_sku/item_name from the vendor's open POs
  2  LINE    production line(s) consuming those SKUs (if any are tracked in
             inventory_snapshots — see _is_production_critical), plus a fixed
             PLANT anchor node
  3  ORDER   downstream orders (POs carrying a downstream_order_ref) reached
             from the affected items
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.diagnosis import _is_production_critical
from app.config import settings
from app.constants import DEFAULT_ORG_ID
from app.db.models import DisruptionEvent, ExposureCalc, Organisation, PurchaseOrder, Vendor as VendorRow
from app.schemas.enums import GraphNodeKind, GraphNodeState
from app.schemas.impact import ImpactEdge, ImpactGraph, ImpactNode, ImpactSummary
from app.schemas.money import format_inr, format_inr_short, to_iso, utc_now_iso

LINE_NODE_ID = "line:aggregate"
PLANT_NODE_ID = f"plant:{DEFAULT_ORG_ID}"


@dataclass(frozen=True)
class _ExposureRow:
    id: str
    total_paise: int
    confidence: float


def _latest_exposure(session: Session, disruption_id: str) -> _ExposureRow | None:
    """Same query repositories/disruptions.py's `_exposure_schema` uses — most
    recent exposure_calcs row by computed_at. Deliberately not recomputed
    here; see module docstring."""
    row = session.execute(
        select(ExposureCalc)
        .where(ExposureCalc.disruption_id == disruption_id)
        .order_by(ExposureCalc.computed_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        return None
    return _ExposureRow(id=row.id, total_paise=row.total_paise, confidence=row.confidence)


def _severity_tier(total_paise: int) -> str:
    if total_paise >= settings.impact_tier1_exposure_paise:
        return "CRITICAL"
    if total_paise >= settings.impact_tier2_exposure_paise:
        return "ELEVATED"
    return "MODERATE"


def disruption_version_key(session: Session, disruption: DisruptionEvent) -> str:
    """Stand-in for an `updated_at` column DisruptionEvent doesn't have — the
    latest of its own per-stage timestamps, plus the latest exposure_calcs
    row's computed_at (the thing most likely to actually change the graph's
    content between two calls, since Sourcing inserts a second exposure_calcs
    row once a backup quote exists). Used as the cache-invalidation key."""
    stage_timestamps = [
        disruption.detected_at, disruption.diagnosed_at, disruption.sourced_at,
        disruption.approval_requested_at, disruption.approved_at,
        disruption.negotiation_started_at, disruption.negotiated_at,
        disruption.settlement_staged_at, disruption.settled_at,
    ]
    last_stage_at: datetime = max((t for t in stage_timestamps if t is not None), default=disruption.detected_at)
    version = to_iso(last_stage_at)
    exposure = _latest_exposure(session, disruption.id)
    if exposure is not None:
        row = session.get(ExposureCalc, exposure.id)
        version += f"|{to_iso(row.computed_at)}"
    return version


def build_impact_graph(session: Session, disruption: DisruptionEvent) -> ImpactGraph:
    vendor = session.get(VendorRow, disruption.vendor_id)
    org = session.get(Organisation, disruption.org_id)
    affected_po_ids = set(disruption.affected_po_ids or [])

    open_pos = session.execute(
        select(PurchaseOrder).where(
            PurchaseOrder.vendor_id == disruption.vendor_id, PurchaseOrder.delivered_at.is_(None)
        )
    ).scalars().all()

    nodes: list[ImpactNode] = []
    edges: list[ImpactEdge] = []

    # --- layer 0: VENDOR ---------------------------------------------------
    vendor_node_id = f"vendor:{disruption.vendor_id}"
    vendor_name = vendor.name if vendor else "Unknown vendor"
    on_time_pct = round((vendor.on_time_rate if vendor else 0.0) * 100)
    nodes.append(
        ImpactNode(
            id=vendor_node_id, kind=GraphNodeKind.VENDOR, layer=0, label=vendor_name,
            state=GraphNodeState.IMPACTED,
            badges=[f"{len(open_pos)} open POs", f"on-time {on_time_pct}%"],
        )
    )

    # --- layer 1: ITEM (grouped by item_sku across the vendor's open POs) --
    items_by_sku: dict[str, list[PurchaseOrder]] = {}
    for po in open_pos:
        items_by_sku.setdefault(po.item_sku, []).append(po)

    critical_skus: list[str] = []
    order_pos: list[PurchaseOrder] = []

    for sku, pos in items_by_sku.items():
        item_node_id = f"item:{sku}"
        item_name = pos[0].item_name
        is_impacted = any(po.id in affected_po_ids for po in pos)
        item_state = GraphNodeState.IMPACTED if is_impacted else GraphNodeState.AT_RISK
        total_units = sum(po.qty for po in pos)

        nodes.append(
            ImpactNode(
                id=item_node_id, kind=GraphNodeKind.ITEM, layer=1, label=f"{item_name} ({sku})",
                state=item_state, badges=[f"{total_units:,} units short"],
            )
        )
        edges.append(
            ImpactEdge(id=f"edge:{vendor_node_id}->{item_node_id}", source=vendor_node_id, target=item_node_id, state=item_state)
        )

        # Same helper diagnosis.py uses, reused per-sku so the "N SKUs
        # affected" line-node badge below can name exactly which SKUs.
        if _is_production_critical(session, [sku]):
            critical_skus.append(sku)

        for po in pos:
            if po.downstream_order_ref is not None:
                order_pos.append(po)

    # --- layer 2: LINE (only if at least one item is production-critical) --
    if critical_skus:
        line_impacted = any(
            po.id in affected_po_ids for sku in critical_skus for po in items_by_sku[sku]
        )
        line_state = GraphNodeState.IMPACTED if line_impacted else GraphNodeState.AT_RISK
        line_label = f"{vendor.category} production line" if vendor else "Production line"
        nodes.append(
            ImpactNode(
                id=LINE_NODE_ID, kind=GraphNodeKind.LINE, layer=2, label=line_label,
                state=line_state, badges=[f"{len(critical_skus)} SKUs affected"],
            )
        )
        for sku in critical_skus:
            item_node_id = f"item:{sku}"
            edges.append(
                ImpactEdge(id=f"edge:{item_node_id}->{LINE_NODE_ID}", source=item_node_id, target=LINE_NODE_ID, state=line_state)
            )

    # --- layer 2: PLANT (fixed anchor — always present, no edges of its own;
    # it's a layout landmark for the frontend, not a propagation step, so it
    # never breaks the layer-increases-along-every-edge invariant the other
    # three layers hold) ------------------------------------------------------
    plant_state = GraphNodeState.AT_RISK if critical_skus else GraphNodeState.HEALTHY
    nodes.append(
        ImpactNode(
            id=PLANT_NODE_ID, kind=GraphNodeKind.PLANT, layer=2,
            label=org.name if org else "Plant", state=plant_state, badges=[],
        )
    )

    # --- layer 3: ORDER (downstream orders reached from affected items) ----
    for po in order_pos:
        order_node_id = f"order:{po.id}"
        item_node_id = f"item:{po.item_sku}"
        order_state = GraphNodeState.IMPACTED if po.penalty_rate_bps is not None else GraphNodeState.AT_RISK
        badges = []
        if po.downstream_order_value_paise is not None:
            badges.append(f"{format_inr_short(po.downstream_order_value_paise)} at risk")
        if po.penalty_rate_bps is not None:
            badges.append("SLA penalty")

        nodes.append(
            ImpactNode(
                id=order_node_id, kind=GraphNodeKind.ORDER, layer=3,
                label=po.downstream_order_ref or po.po_number, state=order_state, badges=badges,
            )
        )
        edges.append(
            ImpactEdge(id=f"edge:{item_node_id}->{order_node_id}", source=item_node_id, target=order_node_id, state=order_state)
        )

    # --- summary: read, never recompute, the disruption's own exposure -----
    exposure = _latest_exposure(session, disruption.id)
    total_paise = exposure.total_paise if exposure else 0
    confidence = exposure.confidence if exposure else 0.0
    summary = ImpactSummary(
        impacted_node_count=sum(1 for n in nodes if n.state == GraphNodeState.IMPACTED),
        at_risk_order_count=sum(1 for n in nodes if n.kind == GraphNodeKind.ORDER),
        exposure_paise=total_paise,
        exposure_display=format_inr(total_paise),
        exposure_confidence=confidence,
        exposure_calc_id=exposure.id if exposure else None,
        tier=_severity_tier(total_paise),
        tier_thresholds_paise={
            "tier_1_paise": settings.impact_tier1_exposure_paise,
            "tier_2_paise": settings.impact_tier2_exposure_paise,
        },
    )

    return ImpactGraph(
        disruption_id=disruption.id, nodes=nodes, edges=edges, summary=summary, computed_at=utc_now_iso(),
    )


# Process-lifetime cache — traversal touches several tables and the graph is
# read repeatedly during a demo (polled, replayed, re-rendered), but only
# actually changes when the disruption's version key (see
# disruption_version_key) changes. Not a persisted table: an app restart
# starts with an empty cache, which is fine — it's rebuilt on first read.
_CACHE: dict[str, tuple[str, ImpactGraph]] = {}


def get_or_build_impact_graph(session: Session, disruption: DisruptionEvent) -> ImpactGraph:
    version = disruption_version_key(session, disruption)
    cached = _CACHE.get(disruption.id)
    if cached is not None and cached[0] == version:
        return cached[1]

    graph = build_impact_graph(session, disruption)
    _CACHE[disruption.id] = (version, graph)
    return graph
