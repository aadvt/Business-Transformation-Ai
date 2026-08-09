"""Integration tests against an already-seeded database.

Run `python -m app.seed --reset` before this file (or against a fresh sqlite
DB pointed to by DATABASE_URL) — these tests read, they don't seed.
"""

import pytest
from sqlalchemy import func, select

from app.db.models import InventorySnapshot, Organisation, PurchaseOrder, Vendor
from app.db.session import SessionLocal
from app.services.audit import verify_audit_chain
from app.services.gstin import validate_gstin


@pytest.fixture(scope="module")
def session():
    s = SessionLocal()
    yield s
    s.close()


def test_organisation_seeded(session):
    count = session.execute(select(func.count()).select_from(Organisation)).scalar_one()
    assert count == 1


def test_vendor_count(session):
    count = session.execute(select(func.count()).select_from(Vendor)).scalar_one()
    assert count == 24


def test_vendor_primary_backup_split(session):
    primary = session.execute(select(func.count()).select_from(Vendor).where(Vendor.is_backup_pool.is_(False))).scalar_one()
    backup = session.execute(select(func.count()).select_from(Vendor).where(Vendor.is_backup_pool.is_(True))).scalar_one()
    assert primary == 14
    assert backup == 10


def test_all_vendor_gstins_are_valid(session):
    vendors = session.execute(select(Vendor)).scalars().all()
    assert len(vendors) > 0
    invalid = [(v.name, v.gstin, validate_gstin(v.gstin).reason) for v in vendors if not validate_gstin(v.gstin).valid]
    assert invalid == [], f"Invalid GSTINs found: {invalid}"


def test_purchase_order_count_approx_140(session):
    count = session.execute(select(func.count()).select_from(PurchaseOrder)).scalar_one()
    assert 130 <= count <= 160


def test_purchase_order_late_and_rejected_rates_are_plausible(session):
    total = session.execute(select(func.count()).select_from(PurchaseOrder)).scalar_one()
    late = session.execute(select(func.count()).select_from(PurchaseOrder).where(PurchaseOrder.status == "LATE")).scalar_one()
    rejected = session.execute(
        select(func.count()).select_from(PurchaseOrder).where(PurchaseOrder.status == "QUALITY_REJECTED")
    ).scalar_one()
    assert 0.05 <= late / total <= 0.25
    assert 0.0 <= rejected / total <= 0.08


def test_every_sku_clears_512_inventory_points(session):
    skus = session.execute(select(InventorySnapshot.sku.distinct())).scalars().all()
    assert len(skus) == 10
    for sku in skus:
        count = session.execute(
            select(func.count()).select_from(InventorySnapshot).where(InventorySnapshot.sku == sku)
        ).scalar_one()
        assert count >= 512, f"{sku} only has {count} points, need >= 512 for TTM's context window"


def test_audit_chain_verifies_for_seeded_disruption(session):
    result = verify_audit_chain(session, "981f074f-9332-4b66-a24d-ffcaff0144cf")
    assert result.ok
    assert result.broken_at is None
