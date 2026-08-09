"""Impact graph tests: deterministic traversal (in-memory sqlite, no network,
no LLM — app/services/impact.py never calls one), every edge references a
node that exists, layers strictly increase along every edge, and the summary
exposure is read verbatim from the exposure_calcs row rather than recomputed.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models import DisruptionEvent, ExposureCalc, InventorySnapshot, Organisation, PurchaseOrder, Vendor
from app.schemas.enums import GraphNodeKind, GraphNodeState
from app.services.impact import PLANT_NODE_ID, build_impact_graph

ORG_ID = "org1"
VENDOR_ID = "v1"
DISRUPTION_ID = "d1"


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()

    from app.schemas.money import utc_now
    now = utc_now()

    s.add(Organisation(id=ORG_ID, name="Test Org", city="Pune", industry="x", revenue_cr=1.0, lat=18.5, lng=73.8, created_at=now))
    s.add(Vendor(
        id=VENDOR_ID, org_id=ORG_ID, name="Test Vendor", category="Fasteners", gstin="27AABCS1429B1ZP",
        udyam_number=None, phone="+91", email="a@b.com", city="Pune", state="Maharashtra",
        lat=18.5, lng=73.8, languages=[], reliability_score=80, on_time_rate=0.71, orders_completed=5,
        disputes=0, avg_lead_time_days=3.0, is_backup_pool=False, payment_terms_days=30,
        created_at=now, updated_at=now,
    ))
    s.flush()

    # PO1: open, affected, production-critical sku, downstream order WITH penalty -> IMPACTED item + order
    po1 = PurchaseOrder(
        id="po1", org_id=ORG_ID, vendor_id=VENDOR_ID, po_number="PO-1", item_sku="FST-M8-BOLT",
        item_name="M8 hex bolt", qty=1200, unit_price_paise=500, ordered_at=now, promised_at=now,
        delivered_at=None, status="LATE", downstream_order_ref="SO-1", downstream_order_value_paise=42_000_000,
        penalty_rate_bps=100,
    )
    # PO2: open, NOT affected, same sku as po1 -> item stays IMPACTED (po1 already impacted it), no downstream ref
    po2 = PurchaseOrder(
        id="po2", org_id=ORG_ID, vendor_id=VENDOR_ID, po_number="PO-2", item_sku="FST-M8-BOLT",
        item_name="M8 hex bolt", qty=300, unit_price_paise=500, ordered_at=now, promised_at=now,
        delivered_at=None, status="PENDING", downstream_order_ref=None, downstream_order_value_paise=None,
        penalty_rate_bps=None,
    )
    # PO3: open, different sku, not production-critical (no inventory_snapshots row), downstream ref WITHOUT penalty -> AT_RISK item + order
    po3 = PurchaseOrder(
        id="po3", org_id=ORG_ID, vendor_id=VENDOR_ID, po_number="PO-3", item_sku="FST-M6-NUT",
        item_name="M6 hex nut", qty=800, unit_price_paise=200, ordered_at=now, promised_at=now,
        delivered_at=None, status="PENDING", downstream_order_ref="SO-2", downstream_order_value_paise=5_000_000,
        penalty_rate_bps=None,
    )
    # PO4: delivered -> must NOT appear in the graph at all
    po4 = PurchaseOrder(
        id="po4", org_id=ORG_ID, vendor_id=VENDOR_ID, po_number="PO-4", item_sku="FST-M8-BOLT",
        item_name="M8 hex bolt", qty=100, unit_price_paise=500, ordered_at=now, promised_at=now,
        delivered_at=now, status="DELIVERED", downstream_order_ref=None, downstream_order_value_paise=None,
        penalty_rate_bps=None,
    )
    s.add_all([po1, po2, po3, po4])

    s.add(InventorySnapshot(
        id="inv1", org_id=ORG_ID, sku="FST-M8-BOLT", at=now, on_hand_qty=100.0, reorder_point=50.0, daily_consumption=10.0,
    ))

    d = DisruptionEvent(
        id=DISRUPTION_ID, org_id=ORG_ID, type="DELIVERY_DELAY", stage="DIAGNOSED",
        vendor_id=VENDOR_ID, detected_at=now, diagnosed_at=now, headline="Test disruption",
        signal_payload={}, detector_name="overdue_delivery", detector_source="RULE_BASED",
        affected_po_ids=["po1"],
    )
    s.add(d)

    s.add(ExposureCalc(
        id="exp1", disruption_id=DISRUPTION_ID, total_paise=920_000_00, confidence=0.8,
        breakdown=[], inputs={}, formula_version="v1", computed_at=now,
    ))
    s.flush()
    s.commit()
    yield s
    s.close()


def _disruption(session):
    return session.get(DisruptionEvent, DISRUPTION_ID)


def test_graph_is_deterministic(session):
    d = _disruption(session)
    g1 = build_impact_graph(session, d)
    g2 = build_impact_graph(session, d)
    # computed_at is a fresh timestamp each call — everything else must match exactly.
    assert g1.model_dump(exclude={"computed_at"}) == g2.model_dump(exclude={"computed_at"})


def test_every_edge_references_existing_nodes(session):
    d = _disruption(session)
    g = build_impact_graph(session, d)
    node_ids = {n.id for n in g.nodes}
    for edge in g.edges:
        assert edge.source in node_ids, f"edge {edge.id} source {edge.source} has no node"
        assert edge.target in node_ids, f"edge {edge.id} target {edge.target} has no node"


def test_layers_strictly_increase_along_every_edge(session):
    d = _disruption(session)
    g = build_impact_graph(session, d)
    layer_by_id = {n.id: n.layer for n in g.nodes}
    for edge in g.edges:
        assert layer_by_id[edge.source] < layer_by_id[edge.target], (
            f"edge {edge.id} does not strictly increase layer "
            f"({layer_by_id[edge.source]} -> {layer_by_id[edge.target]})"
        )
    # node layers only ever take the four documented values
    assert {n.layer for n in g.nodes} <= {0, 1, 2, 3}


def test_summary_exposure_matches_db_row_exactly(session):
    d = _disruption(session)
    g = build_impact_graph(session, d)
    row = session.get(ExposureCalc, "exp1")
    assert g.summary.exposure_total_paise == row.total_paise
    assert g.summary.exposure_confidence == row.confidence
    assert g.summary.exposure_calc_id == row.id


def test_vendor_node_and_badges(session):
    d = _disruption(session)
    g = build_impact_graph(session, d)
    vendor_nodes = [n for n in g.nodes if n.kind == GraphNodeKind.VENDOR]
    assert len(vendor_nodes) == 1
    assert vendor_nodes[0].layer == 0
    assert vendor_nodes[0].state == GraphNodeState.IMPACTED
    assert "3 open POs" in vendor_nodes[0].badges  # po1, po2, po3 — po4 is delivered, excluded
    assert "on-time 71%" in vendor_nodes[0].badges


def test_item_impacted_vs_at_risk(session):
    d = _disruption(session)
    g = build_impact_graph(session, d)
    items = {n.id: n for n in g.nodes if n.kind == GraphNodeKind.ITEM}
    assert items["item:FST-M8-BOLT"].state == GraphNodeState.IMPACTED  # po1 (affected) shares this sku
    assert items["item:FST-M6-NUT"].state == GraphNodeState.AT_RISK  # po3 is open but not affected
    assert "1,500 units short" in items["item:FST-M8-BOLT"].badges  # po1.qty(1200) + po2.qty(300)


def test_line_only_for_production_critical_sku(session):
    d = _disruption(session)
    g = build_impact_graph(session, d)
    lines = [n for n in g.nodes if n.kind == GraphNodeKind.LINE]
    assert len(lines) == 1
    assert lines[0].badges == ["1 SKUs affected"]  # only FST-M8-BOLT is tracked in inventory_snapshots
    # the line is only reachable from the production-critical item
    line_edges = [e for e in g.edges if e.target == lines[0].id]
    assert {e.source for e in line_edges} == {"item:FST-M8-BOLT"}


def test_plant_anchor_always_present(session):
    d = _disruption(session)
    g = build_impact_graph(session, d)
    plant_nodes = [n for n in g.nodes if n.kind == GraphNodeKind.PLANT]
    assert len(plant_nodes) == 1
    assert plant_nodes[0].id == PLANT_NODE_ID
    assert plant_nodes[0].layer == 2


def test_order_nodes_penalty_vs_no_penalty(session):
    d = _disruption(session)
    g = build_impact_graph(session, d)
    orders = {n.id: n for n in g.nodes if n.kind == GraphNodeKind.ORDER}
    assert orders["order:po1"].state == GraphNodeState.IMPACTED  # penalty_rate_bps set
    assert "SLA penalty" in orders["order:po1"].badges
    assert orders["order:po3"].state == GraphNodeState.AT_RISK  # no penalty_rate_bps
    assert "SLA penalty" not in orders["order:po3"].badges
    # po4 (delivered) and po2 (no downstream_order_ref) never became order nodes
    assert "order:po2" not in orders
    assert "order:po4" not in orders


def test_severity_tier_matches_configured_thresholds(session):
    from app.config import settings

    d = _disruption(session)
    g = build_impact_graph(session, d)
    assert g.summary.tier_thresholds_paise == {
        "tier_1_paise": settings.impact_tier1_exposure_paise,
        "tier_2_paise": settings.impact_tier2_exposure_paise,
    }
    # 920,000.00 paise (₹9.2L) is below tier 1 (₹10L) and above tier 2 (₹3L)
    assert g.summary.severity_tier == 2


def test_no_exposure_row_yields_zero_summary(session):
    session.query(ExposureCalc).delete()
    session.commit()
    d = _disruption(session)
    g = build_impact_graph(session, d)
    assert g.summary.exposure_total_paise == 0
    assert g.summary.exposure_calc_id is None
    assert g.summary.severity_tier == 3
