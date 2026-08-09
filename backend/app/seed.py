"""Deterministic, idempotent seed script for the Sanjeevani database.

Run with:  python -m app.seed --reset
(from the backend/ directory, against DATABASE_URL_DIRECT — never the pooled URL)

- Deterministic: every ID and randomized value is drawn from `random.Random(SEED)`
  in a fixed generation order, so re-running with --reset produces an identical
  dataset every time.
- Idempotent: without --reset, if the organisation already exists, the script is
  a no-op. With --reset, all app tables are wiped (in FK-safe order) and reseeded.

Five vendors and three disruptions keep the EXACT UUIDs used in Phase 1's mock
fixtures (and referenced by tests/test_contract.py) so the contract test suite
keeps passing unmodified against the real database — this is what "the API
shapes must not change" means at the data layer. Everything else (19 more
vendors, ~140 purchase orders, ~7,200 inventory points, comms, two golden-path
disruption scenarios) is freshly generated to make the demo dataset rich.
"""

import argparse
import sys
import uuid
from datetime import timedelta
from random import Random

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import (
    AgentRun,
    Approval,
    AuditLogEntry,
    CommEvent,
    DisruptionEvent,
    ExposureCalc,
    IdempotencyRecord,
    InventorySnapshot,
    Negotiation,
    Organisation,
    PurchaseOrder,
    SettlementBatchRow,
    SettlementItem,
    Vendor,
    VendorCandidate,
    Verification,
)
from app.constants import DEFAULT_ORG_ID
from app.db.session import SessionLocal, get_direct_engine
from app.schemas.money import format_inr, utc_now
from app.services.audit import append_audit
from app.services.gstin import generate_valid_gstin
from app.services.ids import det_uuid4

SEED = 42

ORG_ID = DEFAULT_ORG_ID
ORG_NAME = "Shakti Auto Components Pvt Ltd"
ORG_CITY = "Pune"
ORG_INDUSTRY = "Automotive Ancillary"
ORG_REVENUE_CR = 180.0
ORG_LAT = 18.5204  # Pune plant — sourcing's geographic-proximity score is measured from here
ORG_LNG = 73.8567

# City centroid coordinates, reused for every vendor and the plant above so the
# frontend's network map and the sourcing agent's proximity score agree.
CITY_COORDS = {
    "Pune": (18.5204, 73.8567),
    "Chennai": (13.0827, 80.2707),
    "Coimbatore": (11.0168, 76.9558),
    "Ludhiana": (30.9010, 75.8573),
    "Rajkot": (22.3039, 70.8022),
    "Jaipur": (26.9124, 75.7873),
}

# --- Fixed, Phase-1-compatible IDs (see tests/test_contract.py) ---
V1_ID = "4c34118b-bbe1-4016-885d-e6bc7917b3b0"  # Shree Balaji Auto Components
V2_ID = "1799a38c-a9ed-4d03-b666-4784d6346a7b"  # Kohinoor Precision Pvt Ltd
V3_ID = "d0461e77-fbca-487c-9349-e0eb64d1dedf"  # Coromandel Tooling Works
V4_ID = "1f085369-1380-4c55-9cbc-f447ccd95df9"  # Marudhar Steel Traders
V5_ID = "b987144e-5e0d-4bb4-b8f8-ec9cf6b54d9f"  # Sundaram Logistics & Freight

D1_ID = "981f074f-9332-4b66-a24d-ffcaff0144cf"  # DELIVERY_DELAY, SETTLEMENT_PENDING
D2_ID = "6947d32f-c8f4-4cba-ac9b-398529becdb8"  # PRICE_SHOCK, AWAITING_APPROVAL
D3_ID = "228bdcbe-3b9e-42a4-a84f-2f42c48ec664"  # QUALITY_REJECTION, DETECTED

APPROVAL_D1_ID = "a52a6e18-ccbc-4fba-9237-7c0a845a8c02"
APPROVAL_D2_ID = "9fa01c6e-d636-4009-ab03-c2d49ba11bc3"
NEGOTIATION_D1_ID = "192864e3-7595-45fe-8a2b-16c4ce44aa27"
BATCH_AUG_ID = "a7a105e1-2dc7-4ee8-b3b0-0eed03317722"
BATCH_JUL_ID = "b19a4d97-0eca-4944-9c36-2161b9fa02a0"

FORECAST_SKU = "CRS-2MM"  # steel — doubles as the STOCKOUT_RISK golden-path scenario

# --- Reference data ---
CATEGORIES = ["Castings", "Fasteners", "Rubber Seals", "Wiring Harness", "Machining", "Packaging", "Powder Coating"]
CITIES = [
    ("Pune", "Maharashtra", "27"),
    ("Chennai", "Tamil Nadu", "33"),
    ("Coimbatore", "Tamil Nadu", "33"),
    ("Ludhiana", "Punjab", "03"),
    ("Rajkot", "Gujarat", "24"),
]

# (name, city, state, state_code, category, is_primary)
NEW_VENDORS = [
    ("Bharat Casting Industries", "Rajkot", "Gujarat", "24", "Castings", True),
    ("Vishwakarma Precision Castings", "Coimbatore", "Tamil Nadu", "33", "Castings", True),
    ("Om Fasteners Pvt Ltd", "Ludhiana", "Punjab", "03", "Fasteners", True),
    ("National Bolt & Fastener Works", "Rajkot", "Gujarat", "24", "Fasteners", True),
    ("Anand Rubber Seals Pvt Ltd", "Pune", "Maharashtra", "27", "Rubber Seals", True),
    ("Deccan Elastomers", "Chennai", "Tamil Nadu", "33", "Rubber Seals", True),
    ("Suryodaya Wiring Systems", "Pune", "Maharashtra", "27", "Wiring Harness", True),
    ("Precision Engineering Works", "Coimbatore", "Tamil Nadu", "33", "Machining", True),
    ("Unity CNC Solutions", "Pune", "Maharashtra", "27", "Machining", True),
    ("Sai Packaging Industries", "Rajkot", "Gujarat", "24", "Packaging", False),
    ("Maharaja Pack & Print", "Ludhiana", "Punjab", "03", "Packaging", False),
    ("Bhavani Powder Coatings", "Coimbatore", "Tamil Nadu", "33", "Powder Coating", False),
    ("Sundar Surface Finishing", "Pune", "Maharashtra", "27", "Powder Coating", False),
    ("Metro Casting Works", "Chennai", "Tamil Nadu", "33", "Castings", False),
    ("Apex Fastener Industries", "Pune", "Maharashtra", "27", "Fasteners", False),
    ("Global Rubber Components", "Ludhiana", "Punjab", "03", "Rubber Seals", False),
    ("Vinayak Wiring & Cables", "Rajkot", "Gujarat", "24", "Wiring Harness", False),
    ("Krishna Harness Technologies", "Chennai", "Tamil Nadu", "33", "Wiring Harness", False),
    ("Rajlaxmi Machining Pvt Ltd", "Ludhiana", "Punjab", "03", "Machining", False),
]

CATEGORY_SKU_PREFIX = {
    "Castings": "CST",
    "Fasteners": "FST",
    "Rubber Seals": "RBR",
    "Wiring Harness": "WHS",
    "Machining": "MCH",
    "Packaging": "PKG",
    "Powder Coating": "PWD",
}

CATEGORY_UNIT_PRICE_PAISE_RANGE = {
    "Castings": (15000, 90000),
    "Fasteners": (500, 5000),
    "Rubber Seals": (2000, 15000),
    "Wiring Harness": (8000, 40000),
    "Machining": (20000, 120000),
    "Packaging": (1000, 8000),
    "Powder Coating": (3000, 20000),
}

LANGUAGE_BY_STATE = {
    "Maharashtra": ["mr", "hi", "en"],
    "Tamil Nadu": ["ta", "en"],
    "Punjab": ["pa", "hi", "en"],
    "Gujarat": ["gu", "hi", "en"],
    "Rajasthan": ["hi", "en"],
}

# 10 SKUs for inventory_snapshots. `ramp=True` marks a slow demand-ramp series
# (declining toward/through reorder_point) — 3 of these become forecast-flagged
# stockout-risk candidates. CRS-2MM is the one wired to the golden-path scenario.
INVENTORY_SKUS = [
    {"sku": "CRS-2MM", "name": "Cold-rolled steel 2mm", "start_qty": 4200, "reorder_point": 2500, "base_daily": 90, "ramp": True},
    {"sku": "FST-M8-BOLT", "name": "M8 hex bolt", "start_qty": 60000, "reorder_point": 15000, "base_daily": 1400, "ramp": True},
    {"sku": "RBR-SEAL-A", "name": "Rubber O-ring seal A", "start_qty": 22000, "reorder_point": 6000, "base_daily": 480, "ramp": True},
    {"sku": "WHS-HARN-12V", "name": "12V wiring harness assembly", "start_qty": 5200, "reorder_point": 1200, "base_daily": 95, "ramp": False},
    {"sku": "MCH-SHAFT-22", "name": "Machined shaft 22mm", "start_qty": 3100, "reorder_point": 900, "base_daily": 55, "ramp": False},
    {"sku": "PKG-BOX-L", "name": "Corrugated box, large", "start_qty": 18000, "reorder_point": 4000, "base_daily": 620, "ramp": False},
    {"sku": "PWD-COAT-BLK", "name": "Powder coat, matte black", "start_qty": 2600, "reorder_point": 700, "base_daily": 48, "ramp": False},
    {"sku": "CST-BRKT-07", "name": "Casted mounting bracket 07", "start_qty": 7400, "reorder_point": 1800, "base_daily": 160, "ramp": False},
    {"sku": "RBR-GASKET-C", "name": "Rubber gasket C-series", "start_qty": 9600, "reorder_point": 2400, "base_daily": 210, "ramp": False},
    {"sku": "FST-M6-NUT", "name": "M6 hex nut", "start_qty": 84000, "reorder_point": 20000, "base_daily": 1600, "ramp": False},
]

SILENT_VENDOR_NAME = "Om Fasteners Pvt Ltd"

ALL_MODELS_IN_FK_ORDER = [
    IdempotencyRecord,
    AuditLogEntry,
    AgentRun,
    SettlementItem,
    SettlementBatchRow,
    Negotiation,
    Approval,
    Verification,
    VendorCandidate,
    ExposureCalc,
    DisruptionEvent,
    CommEvent,
    InventorySnapshot,
    PurchaseOrder,
    Vendor,
    Organisation,
]


def _print_summary(session: Session, scenario_a_po_id: str, scenario_a_vendor: str) -> None:
    print("\n=== Seed summary ===")
    for model in reversed(ALL_MODELS_IN_FK_ORDER):
        count = session.execute(select(func.count()).select_from(model)).scalar_one()
        print(f"  {model.__tablename__:<22} {count}")
    print("\n=== Golden-path scenarios (data seeded, disruption NOT yet triggered) ===")
    print(f"  (a) DELIVERY_DELAY   PO id={scenario_a_po_id}  vendor={scenario_a_vendor}  ~4 days overdue, downstream penalty exposure ~Rs 6-7L")
    print(f"  (b) STOCKOUT_RISK    SKU={FORECAST_SKU}  trending toward/through reorder_point over the forecast horizon")
    print(f"\n=== Phase-1-compatible contract fixtures (for tests/test_contract.py) ===")
    print(f"  disruptions: {D1_ID}, {D2_ID}, {D3_ID}")
    print(f"  approval={APPROVAL_D2_ID}  negotiation={NEGOTIATION_D1_ID}  settlement_batch={BATCH_AUG_ID}")
    print()


def seed(reset: bool) -> None:
    engine = get_direct_engine()

    if reset:
        # No Alembic — a --reset always rebuilds the schema from the current
        # models.py rather than just wiping rows, so an added/changed column
        # (e.g. Vendor.lat/lng) can never leave a stale table shape behind.
        print("Dropping and recreating schema...")
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    session = SessionLocal()
    session.bind = engine  # seed against the direct connection, not the pooled one

    try:
        already_seeded = session.execute(select(func.count()).select_from(Organisation)).scalar_one() > 0
        if already_seeded and not reset:
            print("Already seeded (organisation exists). Pass --reset to wipe and reseed.")
            return

        rng = Random(SEED)
        now = utc_now()

        # --- Organisation ---
        org = Organisation(
            id=ORG_ID, name=ORG_NAME, city=ORG_CITY, industry=ORG_INDUSTRY,
            revenue_cr=ORG_REVENUE_CR, lat=ORG_LAT, lng=ORG_LNG,
            created_at=now - timedelta(days=900),
        )
        session.add(org)
        session.flush()

        # --- Vendors ---
        vendors: list[Vendor] = []

        legacy = [
            (V1_ID, "Shree Balaji Auto Components", "Pune", "Maharashtra", "27", "Fasteners", True),
            (V2_ID, "Kohinoor Precision Pvt Ltd", "Pune", "Maharashtra", "27", "Machining", True),
            (V3_ID, "Coromandel Tooling Works", "Coimbatore", "Tamil Nadu", "33", "Machining", True),
            (V4_ID, "Marudhar Steel Traders", "Jaipur", "Rajasthan", "08", "Castings", True),
            (V5_ID, "Sundaram Logistics & Freight", "Chennai", "Tamil Nadu", "33", "Packaging", True),
        ]

        vendor_seed_counter = 0
        for vid, name, city, state, state_code, category, is_primary in legacy:
            gstin = generate_valid_gstin(state_code, seed=SEED * 1000 + vendor_seed_counter)
            vendor_seed_counter += 1
            vendors.append(_build_vendor(rng, vid, name, city, state, category, gstin, is_primary))

        for name, city, state, state_code, category, is_primary in NEW_VENDORS:
            vid = det_uuid4(rng)
            gstin = generate_valid_gstin(state_code, seed=SEED * 1000 + vendor_seed_counter)
            vendor_seed_counter += 1
            vendors.append(_build_vendor(rng, vid, name, city, state, category, gstin, is_primary))

        session.add_all(vendors)
        session.flush()

        vendor_by_id = {v.id: v for v in vendors}
        primary_vendors = [v for v in vendors if not v.is_backup_pool]
        silent_vendor = next(v for v in vendors if v.name == SILENT_VENDOR_NAME)

        # --- Purchase orders (drives derived reliability stats) ---
        pos = _generate_purchase_orders(rng, now, primary_vendors)
        # "Bharat Casting Industries" specifically — keeps this scenario's vendor
        # distinct from V4 (Marudhar Steel), which is already the PRICE_SHOCK vendor.
        scenario_a_vendor = next(v for v in vendors if v.name == "Bharat Casting Industries")
        scenario_a_po = _build_scenario_a_po(rng, now, scenario_a_vendor)
        pos.append(scenario_a_po)
        session.add_all(pos)
        session.flush()

        _derive_vendor_reliability(vendor_by_id, pos)

        # --- Inventory snapshots ---
        inventory_rows = _generate_inventory_snapshots(rng, now)
        session.bulk_insert_mappings(InventorySnapshot, inventory_rows)

        # --- Comm events ---
        comm_rows = _generate_comm_events(rng, now, vendors, silent_vendor)
        session.bulk_insert_mappings(CommEvent, comm_rows)

        # --- Legacy disruptions (Phase-1-compatible) ---
        _seed_legacy_disruptions(session, rng, now, vendor_by_id)

        # --- Settlement batches ---
        _seed_settlement_batches(session, now, vendor_by_id)

        session.commit()
        _print_summary(session, scenario_a_po.id, vendor_by_id[scenario_a_po.vendor_id].name)

    finally:
        session.close()


def _build_vendor(rng: Random, vid: str, name: str, city: str, state: str, category: str, gstin: str, is_primary: bool) -> Vendor:
    now = utc_now()
    base_lat, base_lng = CITY_COORDS[city]
    # Small deterministic jitter (~a few km) so vendors in the same city don't
    # all stack on one point on the frontend's network map.
    lat = round(base_lat + rng.uniform(-0.05, 0.05), 4)
    lng = round(base_lng + rng.uniform(-0.05, 0.05), 4)
    return Vendor(
        id=vid,
        org_id=ORG_ID,
        name=name,
        category=category,
        gstin=gstin,
        udyam_number=f"UDYAM-{('MH' if state == 'Maharashtra' else 'TN' if state == 'Tamil Nadu' else 'PB' if state == 'Punjab' else 'GJ' if state == 'Gujarat' else 'RJ')}-{rng.randint(18, 26):02d}-{rng.randint(1000000, 9999999)}",
        phone=f"+91-9{rng.randint(1000,9999)}0-{rng.randint(10000,99999)}",
        email=f"contact@{name.lower().split()[0]}{rng.randint(10,99)}.in",
        city=city,
        state=state,
        lat=lat,
        lng=lng,
        languages=LANGUAGE_BY_STATE.get(state, ["hi", "en"]),
        # placeholders — overwritten by _derive_vendor_reliability for those with PO history
        reliability_score=rng.randint(50, 70),
        on_time_rate=round(rng.uniform(0.6, 0.85), 2),
        orders_completed=rng.randint(5, 20),
        disputes=rng.randint(0, 3),
        avg_lead_time_days=float(rng.randint(3, 12)),
        is_backup_pool=not is_primary,
        payment_terms_days=rng.choice([15, 30, 45]),
        capacity_hint=rng.choice(["Low", "Medium", "High", "Very High"]),
        price_band=rng.choice(["Budget", "Standard", "Premium"]),
        created_at=now - timedelta(days=rng.randint(200, 1200)),
        updated_at=now - timedelta(days=rng.randint(0, 30)),
    )


def _generate_purchase_orders(rng: Random, now, primary_vendors: list[Vendor]) -> list[PurchaseOrder]:
    pos: list[PurchaseOrder] = []
    for vendor in primary_vendors:
        prefix = CATEGORY_SKU_PREFIX[vendor.category]
        lo, hi = CATEGORY_UNIT_PRICE_PAISE_RANGE[vendor.category]
        base_lead_time = rng.randint(2, 10)
        for i in range(10):
            days_ago = rng.randint(5, 120)
            ordered_at = now - timedelta(days=days_ago)
            lead_time = max(1, base_lead_time + rng.randint(-1, 1))
            promised_at = ordered_at + timedelta(days=lead_time)

            roll = rng.random()
            if roll < 0.03:
                status = "QUALITY_REJECTED"
                delivered_at = promised_at + timedelta(days=rng.randint(0, 2))
            elif roll < 0.15:
                status = "LATE"
                delivered_at = promised_at + timedelta(days=rng.randint(1, 6))
            else:
                status = "DELIVERED"
                delivered_at = promised_at - timedelta(days=rng.randint(0, 1))
            if delivered_at > now:
                delivered_at = None
                status = "PENDING"

            downstream_ref = None
            downstream_value_paise = None
            penalty_bps = None
            if rng.random() < 0.15:
                downstream_ref = f"SO-2026-{rng.randint(1000,9999)}"
                downstream_value_paise = rng.randint(2_000_000, 15_000_000) * 10
                penalty_bps = rng.choice([25, 50, 75, 100])

            pos.append(
                PurchaseOrder(
                    id=det_uuid4(rng),
                    org_id=ORG_ID,
                    vendor_id=vendor.id,
                    po_number=f"PO-{vendor.id[:4].upper()}-{i:03d}",
                    item_sku=f"{prefix}-{rng.randint(100,999)}",
                    item_name=f"{vendor.category} item #{rng.randint(1,50)}",
                    qty=rng.randint(50, 2000),
                    unit_price_paise=rng.randint(lo, hi),
                    ordered_at=ordered_at,
                    promised_at=promised_at,
                    delivered_at=delivered_at,
                    status=status,
                    downstream_order_ref=downstream_ref,
                    downstream_order_value_paise=downstream_value_paise,
                    penalty_rate_bps=penalty_bps,
                )
            )
    return pos


def _build_scenario_a_po(rng: Random, now, vendor: Vendor) -> PurchaseOrder:
    """Golden-path (a): a castings vendor 4 days overdue on a PO feeding a
    downstream order with a penalty clause. Tuned so exposure = downstream_value
    * penalty_rate_bps/10000 * days_late lands at ~₹6.5L (see CLAUDE.md)."""
    ordered_at = now - timedelta(days=10)
    promised_at = now - timedelta(days=4)
    return PurchaseOrder(
        id=det_uuid4(rng),
        org_id=ORG_ID,
        vendor_id=vendor.id,
        po_number="PO-SCN-A-001",
        item_sku=f"{CATEGORY_SKU_PREFIX[vendor.category]}-901",
        item_name=f"{vendor.category} item — golden path A",
        qty=1200,
        unit_price_paise=42000,
        ordered_at=ordered_at,
        promised_at=promised_at,
        delivered_at=None,
        status="LATE",
        downstream_order_ref="SO-2026-0842",
        downstream_order_value_paise=1_300_000_000,  # ₹1.3Cr
        penalty_rate_bps=125,  # 1.25%/day -> 4 days = ~₹6.5L
    )


def _derive_vendor_reliability(vendor_by_id: dict[str, Vendor], pos: list[PurchaseOrder]) -> None:
    by_vendor: dict[str, list[PurchaseOrder]] = {}
    for po in pos:
        by_vendor.setdefault(po.vendor_id, []).append(po)

    for vid, vendor_pos in by_vendor.items():
        vendor = vendor_by_id[vid]
        terminal = [p for p in vendor_pos if p.status in ("DELIVERED", "LATE", "QUALITY_REJECTED")]
        if not terminal:
            continue
        delivered_on_time = sum(1 for p in terminal if p.status == "DELIVERED")
        late = sum(1 for p in terminal if p.status == "LATE")
        rejected = sum(1 for p in terminal if p.status == "QUALITY_REJECTED")
        completed = len(terminal)
        on_time_rate = delivered_on_time / completed if completed else 0.0
        dispute_rate = rejected / completed if completed else 0.0
        lead_times = [(p.promised_at - p.ordered_at).total_seconds() / 86400 for p in vendor_pos]

        vendor.orders_completed = completed
        vendor.on_time_rate = round(on_time_rate, 2)
        vendor.disputes = rejected
        vendor.avg_lead_time_days = round(sum(lead_times) / len(lead_times), 1)
        vendor.reliability_score = max(0, min(100, round(100 * (0.7 * on_time_rate + 0.3 * (1 - dispute_rate)))))


def _weekday_factor(dt) -> float:
    return 1.15 if dt.weekday() < 5 else 0.7


def _generate_inventory_snapshots(rng: Random, now) -> list[dict]:
    rows: list[dict] = []
    total_hours = 720  # 30 days hourly, clears the 512-point TTM context window
    for sku_def in INVENTORY_SKUS:
        qty = float(sku_def["start_qty"])
        reorder_point = float(sku_def["reorder_point"])
        base_daily = float(sku_def["base_daily"])
        ramp = sku_def["ramp"]
        restock_every = 200 if ramp else 168
        restock_qty = base_daily * (5.5 if ramp else 7.2)

        for h in range(total_hours):
            at = now - timedelta(hours=(total_hours - 1 - h))
            ramp_factor = 1.0 + (0.85 * h / total_hours) if ramp else 1.0
            noise = rng.uniform(0.85, 1.15)
            daily_consumption = base_daily * ramp_factor * noise
            hourly_consumption = (daily_consumption / 24) * _weekday_factor(at)
            qty = max(0.0, qty - hourly_consumption)
            if h > 0 and h % restock_every == 0:
                qty += restock_qty

            rows.append(
                {
                    "id": det_uuid4(rng),
                    "org_id": ORG_ID,
                    "sku": sku_def["sku"],
                    "at": at,
                    "on_hand_qty": round(qty, 1),
                    "reorder_point": reorder_point,
                    "daily_consumption": round(daily_consumption, 1),
                }
            )
    return rows


COMM_TEMPLATES_OUTBOUND = [
    "Hi, please confirm dispatch status for our latest PO.",
    "Following up — can you share the updated ETA?",
    "Please send the QC report for the last batch.",
    "Can we lock in pricing for next quarter's volume?",
]
COMM_TEMPLATES_INBOUND = [
    "Dispatch confirmed, should reach you by Thursday.",
    "Apologies for the delay, truck left this morning.",
    "QC report attached, all units within tolerance.",
    "Yes, we can hold current pricing for Q3.",
]


def _generate_comm_events(rng: Random, now, vendors: list[Vendor], silent_vendor: Vendor) -> list[dict]:
    rows: list[dict] = []
    chatty_vendors = [v for v in vendors if not v.is_backup_pool][:10]

    for vendor in chatty_vendors:
        n_exchanges = rng.randint(2, 5)
        for i in range(n_exchanges):
            days_ago = rng.randint(1, 45)
            at_out = now - timedelta(days=days_ago, hours=rng.randint(0, 5))
            rows.append(
                {
                    "id": det_uuid4(rng), "org_id": ORG_ID, "vendor_id": vendor.id,
                    "channel": "WHATSAPP", "direction": "OUTBOUND",
                    "body": rng.choice(COMM_TEMPLATES_OUTBOUND), "at": at_out,
                }
            )
            at_in = at_out + timedelta(hours=rng.randint(1, 20))
            if at_in < now:
                rows.append(
                    {
                        "id": det_uuid4(rng), "org_id": ORG_ID, "vendor_id": vendor.id,
                        "channel": "WHATSAPP", "direction": "INBOUND",
                        "body": rng.choice(COMM_TEMPLATES_INBOUND), "at": at_in,
                    }
                )

    # The silent vendor: normal history, then one unanswered outbound 14 days ago.
    for i in range(3):
        days_ago = rng.randint(20, 60)
        at_out = now - timedelta(days=days_ago)
        rows.append(
            {
                "id": det_uuid4(rng), "org_id": ORG_ID, "vendor_id": silent_vendor.id,
                "channel": "WHATSAPP", "direction": "OUTBOUND",
                "body": rng.choice(COMM_TEMPLATES_OUTBOUND), "at": at_out,
            }
        )
        rows.append(
            {
                "id": det_uuid4(rng), "org_id": ORG_ID, "vendor_id": silent_vendor.id,
                "channel": "WHATSAPP", "direction": "INBOUND",
                "body": rng.choice(COMM_TEMPLATES_INBOUND), "at": at_out + timedelta(hours=6),
            }
        )
    rows.append(
        {
            "id": det_uuid4(rng), "org_id": ORG_ID, "vendor_id": silent_vendor.id,
            "channel": "WHATSAPP", "direction": "OUTBOUND",
            "body": "Following up on the delayed shipment — please respond.",
            "at": now - timedelta(days=14),
        }
    )
    return rows


def _seed_legacy_disruptions(session: Session, rng: Random, now, vendor_by_id: dict[str, Vendor]) -> None:
    # --- D1: DELIVERY_DELAY, SETTLEMENT_PENDING, fully resolved historically ---
    d1 = DisruptionEvent(
        id=D1_ID, org_id=ORG_ID, type="DELIVERY_DELAY", stage="SETTLEMENT_PENDING",
        vendor_id=V1_ID, detected_at=now - timedelta(days=2, hours=3),
        headline="M8 hex bolt shipment 6 days behind schedule, line stoppage risk at Chakan plant",
        signal_payload={"gps_gap_hours": 14}, detector_name="carrier_tracking_gap", detector_source="RULE_BASED",
        affected_po_ids=[],
        diagnosed_at=now - timedelta(days=2, hours=2, minutes=52),
        sourced_at=now - timedelta(days=2, hours=2, minutes=37),
        approval_requested_at=now - timedelta(days=2, hours=2, minutes=12),
        approved_at=now - timedelta(days=2, hours=1, minutes=50),
        negotiation_started_at=now - timedelta(days=2, hours=1, minutes=47),
        negotiated_at=now - timedelta(days=2, hours=1, minutes=31),
        settlement_staged_at=now - timedelta(days=2, hours=1, minutes=27),
        root_cause="TRANSPORT_BREAKDOWN",
        diagnosis_narrative="Carrier's truck suffered an axle failure on NH48 near Lonavala; replacement vehicle dispatch was delayed by monsoon traffic restrictions.",
        diagnosis_evidence=["GPS ping gap of 14 hours on carrier tracking API", "Carrier support ticket #CT-88213 confirms axle failure"],
        diagnosis_guardian_status="PASSED", diagnosis_guardian_passed=True,
    )
    session.add(d1)
    session.flush()  # models don't declare ORM relationships, so cross-table FK
    # ordering isn't auto-sorted at flush time — parent rows must be flushed
    # before children that reference them by plain id column, or Postgres (which
    # enforces FK constraints, unlike sqlite in default mode) rejects the insert.

    session.add(ExposureCalc(
        id=det_uuid4(rng), disruption_id=D1_ID, total_paise=1_850_000_00,
        confidence=0.87,
        breakdown=[
            {"label": "Idle assembly line cost", "amount_paise": 1_200_000_00, "amount_display": format_inr(1_200_000_00), "basis": "6 days of Chakan line-3 downtime at historical ₹20L/day idle cost"},
            {"label": "Expedited air freight surcharge", "amount_paise": 450_000_00, "amount_display": format_inr(450_000_00), "basis": "Quoted air-freight premium over the original sea-freight booking"},
            {"label": "Contractual delay penalty (downstream OEM)", "amount_paise": 200_000_00, "amount_display": format_inr(200_000_00), "basis": "0.5% per day penalty clause in OEM supply contract, capped at 5 days"},
        ],
        inputs={}, formula_version="v1", computed_at=now - timedelta(days=2, hours=2, minutes=55),
    ))
    session.add(VendorCandidate(
        id=det_uuid4(rng), disruption_id=D1_ID, vendor_id=V2_ID, match_score=0.88, rank=1,
        rationale="High reliability, same category, verified GSTIN/Udyam", quoted_unit_price_paise=1450,
        quoted_lead_time_days=2, created_at=now - timedelta(days=2, hours=2, minutes=25),
    ))
    session.add(Verification(
        id=det_uuid4(rng), vendor_id=V2_ID, disruption_id=D1_ID,
        gstin_status="VERIFIED", gstin_detail={}, udyam_status="VERIFIED", udyam_detail={},
        overall_status="VERIFIED", source="GST_PORTAL_STUB",
        checked_at=now - timedelta(days=2, hours=2, minutes=20), latency_ms=340.0,
    ))
    session.add(Approval(
        id=APPROVAL_D1_ID, disruption_id=D1_ID, status="APPROVED",
        requested_at=now - timedelta(days=2, hours=2, minutes=12),
        decided_at=now - timedelta(days=2, hours=1, minutes=50),
        decided_by="priya.sharma@shakti-auto.in", channel="WEB", note=None,
        idempotency_key=None, presented_options=[],
    ))
    session.add(Negotiation(
        id=NEGOTIATION_D1_ID, disruption_id=D1_ID, vendor_id=V2_ID, status="AGREED",
        started_at=now - timedelta(days=2, hours=1, minutes=47),
        ended_at=now - timedelta(days=2, hours=1, minutes=31),
        transcript_url=None,
        transcript_summary="Vendor agreed to expedite to 2-day lead time and hold pricing within guardrail after volume commitment for next quarter.",
        rounds=3,
        opening_unit_price_paise=1600, opening_lead_time_days=3, opening_payment_terms_days=30,
        agreed_unit_price_paise=1450, agreed_lead_time_days=2, agreed_payment_terms_days=30,
        guardian_status="PASSED", guardian_detail={}, raw_outcome={},
    ))

    for actor_type, actor, action, detail, at in [
        ("AGENT", "SENTINEL", "SIGNAL_RAISED", {"note": "Carrier tracking gap exceeded 12h threshold"}, d1.detected_at),
        ("AGENT", "DIAGNOSIS", "ROOT_CAUSE_ASSIGNED", {"root_cause": "TRANSPORT_BREAKDOWN"}, d1.diagnosed_at),
        ("AGENT", "SOURCING", "CANDIDATES_MATCHED", {"count": 1}, d1.sourced_at),
        ("HUMAN", "priya.sharma@shakti-auto.in", "APPROVAL_DECIDED", {"decision": "APPROVE"}, d1.approved_at),
        ("AGENT", "NEGOTIATION", "TERMS_AGREED", {"unit_price_paise": 1450}, d1.negotiated_at),
        ("AGENT", "SETTLEMENT", "BATCH_QUEUED", {"batch_id": BATCH_AUG_ID}, d1.settlement_staged_at),
    ]:
        append_audit(session, org_id=ORG_ID, disruption_id=D1_ID, actor_type=actor_type, actor=actor, action=action, detail=detail, at=at)

    # --- D2: PRICE_SHOCK, AWAITING_APPROVAL, decision still pending ---
    d2 = DisruptionEvent(
        id=D2_ID, org_id=ORG_ID, type="PRICE_SHOCK", stage="AWAITING_APPROVAL",
        vendor_id=V4_ID, detected_at=now - timedelta(hours=8),
        headline="TTM forecast flags 18% cold-rolled steel price spike ahead of next PO cycle",
        signal_payload={"breach_probability": 0.81, "sku": FORECAST_SKU}, detector_name="ttm_forecast", detector_source="TTM_FORECAST",
        affected_po_ids=[],
        diagnosed_at=now - timedelta(hours=7, minutes=45),
        approval_requested_at=now - timedelta(hours=7, minutes=30),
        root_cause="FINANCIAL_DISTRESS",
        diagnosis_narrative="Vendor's regional supplier base is passing through a raw-ore cost increase; TTM model detected the leading indicator two weeks before spot price movement.",
        diagnosis_evidence=["Granite TTM forecast breach probability 0.81 for SKU " + FORECAST_SKU, "Vendor's last two invoices show sequential price creep"],
        diagnosis_guardian_status="PASSED", diagnosis_guardian_passed=True,
    )
    session.add(d2)
    session.flush()
    session.add(ExposureCalc(
        id=det_uuid4(rng), disruption_id=D2_ID, total_paise=920_000_00, confidence=0.74,
        breakdown=[
            {"label": "Projected cost increase on Q3 steel order", "amount_paise": 780_000_00, "amount_display": format_inr(780_000_00), "basis": "18% forecast price delta applied to committed Q3 order volume"},
            {"label": "Hedging / early-lock premium", "amount_paise": 140_000_00, "amount_display": format_inr(140_000_00), "basis": "Estimated premium to lock current pricing before the forecast breach date"},
        ],
        inputs={}, formula_version="v1", computed_at=now - timedelta(hours=7, minutes=50),
    ))
    session.add(Approval(
        id=APPROVAL_D2_ID, disruption_id=D2_ID, status="PENDING",
        requested_at=now - timedelta(hours=7, minutes=30),
        decided_at=None, decided_by=None, channel=None, note=None,
        idempotency_key=None, presented_options=[],
    ))
    for actor_type, actor, action, detail, at in [
        ("AGENT", "SENTINEL", "SIGNAL_RAISED", {"sku": FORECAST_SKU}, d2.detected_at),
        ("AGENT", "DIAGNOSIS", "ROOT_CAUSE_ASSIGNED", {"root_cause": "FINANCIAL_DISTRESS"}, d2.diagnosed_at),
        ("AGENT", "GOVERNANCE", "APPROVAL_REQUESTED", {"approval_id": APPROVAL_D2_ID}, d2.approval_requested_at),
    ]:
        append_audit(session, org_id=ORG_ID, disruption_id=D2_ID, actor_type=actor_type, actor=actor, action=action, detail=detail, at=at)

    # --- D3: QUALITY_REJECTION, DETECTED, freshly opened ---
    d3 = DisruptionEvent(
        id=D3_ID, org_id=ORG_ID, type="QUALITY_REJECTION", stage="DETECTED",
        vendor_id=V3_ID, detected_at=now - timedelta(minutes=40),
        headline="Incoming QC rejected 12% of jig fixture batch for dimensional tolerance failure",
        signal_payload={"qc_report": "QC-55210", "rejected": 34, "total": 280}, detector_name="qc_scan", detector_source="RULE_BASED",
        affected_po_ids=[],
        diagnosis_guardian_status="PENDING", diagnosis_guardian_passed=False,
    )
    session.add(d3)
    session.flush()
    session.add(ExposureCalc(
        id=det_uuid4(rng), disruption_id=D3_ID, total_paise=260_000_00, confidence=0.55,
        breakdown=[
            {"label": "Rejected batch replacement cost", "amount_paise": 180_000_00, "amount_display": format_inr(180_000_00), "basis": "12% of ₹1.5Cr batch value flagged non-conforming by QC"},
            {"label": "Rework and re-inspection labor", "amount_paise": 80_000_00, "amount_display": format_inr(80_000_00), "basis": "Estimated QC + rework hours at standard shop rate"},
        ],
        inputs={}, formula_version="v1", computed_at=d3.detected_at,
    ))
    append_audit(session, org_id=ORG_ID, disruption_id=D3_ID, actor_type="AGENT", actor="SENTINEL", action="SIGNAL_RAISED", detail={"qc_report": "QC-55210"}, at=d3.detected_at)


def _seed_settlement_batches(session: Session, now, vendor_by_id: dict[str, Vendor]) -> None:
    session.add(SettlementBatchRow(
        id=BATCH_AUG_ID, org_id=ORG_ID, period_month=now.strftime("%Y-%m"), status="PENDING",
        total_paise=212_500_00, item_count=2, staged_at=now - timedelta(days=2, hours=1, minutes=27),
        approved_at=None, confirmed_at=None, approved_by=None,
    ))
    session.flush()
    session.add(SettlementItem(
        id=str(uuid.uuid4()), batch_id=BATCH_AUG_ID, vendor_id=V1_ID,
        po_ids=[], amount_paise=184_500_00, status="PENDING", reference="INV-SB-20260731-04",
        note=None, due_date=(now + timedelta(days=6)).date(),
    ))
    session.add(SettlementItem(
        id=str(uuid.uuid4()), batch_id=BATCH_AUG_ID, vendor_id=V5_ID,
        po_ids=[], amount_paise=28_000_00, status="PENDING", reference="INV-SL-20260805-11",
        note=None, due_date=(now + timedelta(days=9)).date(),
    ))

    last_month = (now.replace(day=1) - timedelta(days=1))
    session.add(SettlementBatchRow(
        id=BATCH_JUL_ID, org_id=ORG_ID, period_month=last_month.strftime("%Y-%m"), status="CONFIRMED",
        total_paise=415_000_00, item_count=1, staged_at=last_month - timedelta(days=1),
        approved_at=last_month, confirmed_at=last_month, approved_by="finance.ops@shakti-auto.in",
    ))
    session.flush()
    session.add(SettlementItem(
        id=str(uuid.uuid4()), batch_id=BATCH_JUL_ID, vendor_id=V2_ID,
        po_ids=[], amount_paise=415_000_00, status="CONFIRMED", reference="INV-KP-20260728-02",
        note=None, due_date=last_month.date(),
    ))


def main() -> None:
    # Windows terminals often default to a cp1252 stdout, which chokes on ₹ etc.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Seed the Sanjeevani database.")
    parser.add_argument("--reset", action="store_true", help="Wipe all app tables before reseeding.")
    args = parser.parse_args()
    seed(reset=args.reset)


if __name__ == "__main__":
    sys.exit(main() or 0)
