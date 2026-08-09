"""Public vendor directory — no API key required, rate-limited.

These endpoints are deliberately NOT behind require_api_key, allowing anonymous
access. Rate limiting is enforced by the API gateway, not this code (see
app/main.py for deployment-level rate-limit headers, or manage via CloudFlare/WAF).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.constants import DEFAULT_ORG_ID
from app.db.session import get_session
from app.db.models import Vendor as VendorRow
from app.repositories import vendors as vendor_repo
from app.schemas.public_vendors import (
    PublicVendor,
    PublicVendorList,
    RegistrationResponse,
    VendorRegistration,
    VendorVerification,
    VerificationDetail,
)
from app.services.audit import append_audit
from app.services.gstin import validate_gstin
from app.services.verification import verify_vendor
from app.schemas.money import utc_now

router = APIRouter(prefix="/api/v1/public", tags=["public"])


def _mask_gstin(gstin: str) -> str:
    """Show first 2 (state) and last 3 chars only."""
    if len(gstin) < 5:
        return "***"
    return f"{gstin[:2]}*{'*'*(len(gstin)-5)}{gstin[-3:]}"


def _vendor_to_public(
    session: Session, vendor: VendorRow, distance_km: float | None = None
) -> PublicVendor:
    """Convert ORM Vendor to PublicVendor response with verification details."""
    verification_result = verify_vendor(session, vendor)

    # Build verification detail list showing what was checked
    details = [
        VerificationDetail(
            field="GSTIN Structure",
            status="VALID" if verification_result.gstin.detail.get("structure_valid") else "INVALID",
            description="GSTIN follows the correct 15-character format",
        ),
        VerificationDetail(
            field="GSTIN Checksum",
            status="VALID" if verification_result.gstin.detail.get("checksum_valid") else "INVALID",
            description="GSTIN checksum passes mod-36 validation",
        ),
    ]
    if verification_result.udyam.detail.get("udyam_number"):
        details.append(
            VerificationDetail(
                field="Udyam Registration",
                status=verification_result.udyam.status.value,
                description=verification_result.udyam.detail.get("reason", "Verified against Udyam database"),
            )
        )

    verification = VendorVerification(
        overall_status=verification_result.overall_status.value,
        gstin_status=verification_result.gstin.status.value,
        gstin_masked=_mask_gstin(vendor.gstin),
        udyam_status=verification_result.udyam.status.value if verification_result.udyam else None,
        details=details,
        source=verification_result.gstin.source,
        checked_at=verification_result.checked_at,
    )

    return PublicVendor(
        id=vendor.id,
        name=vendor.name,
        category=vendor.category,
        city=vendor.city,
        state=vendor.state,
        distance_km=distance_km,
        lead_time_days=int(round(vendor.avg_lead_time_days)) if vendor.avg_lead_time_days > 0 else 30,
        capacity_hint=vendor.capacity_hint,
        price_band=vendor.price_band,
        languages=vendor.languages or [],
        reliability={
            "score_0_100": vendor.reliability_score,
            "on_time_rate": vendor.on_time_rate,
            "orders_completed": vendor.orders_completed,
        },
        verification=verification,
    )


@router.get("/vendors", response_model=PublicVendorList)
def get_public_vendors(
    category: str | None = Query(None),
    verified: bool = Query(False),
    limit: int = Query(50, ge=1, le=100),
    session: Session = Depends(get_session),
) -> PublicVendorList:
    """List vendors from the public directory."""
    vendors = vendor_repo.search_vendors(
        session,
        category=category,
        verified_only=verified,
        limit=limit,
    )
    items = [_vendor_to_public(session, v) for v in vendors]
    return PublicVendorList(items=items, total=len(items))


@router.get("/vendors/{vendor_id}", response_model=PublicVendor)
def get_public_vendor(vendor_id: str, session: Session = Depends(get_session)) -> PublicVendor:
    """Get a specific vendor with full verification details."""
    vendor = session.get(VendorRow, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return _vendor_to_public(session, vendor)


@router.post("/vendors/register", response_model=RegistrationResponse)
def register_vendor(
    payload: VendorRegistration,
    session: Session = Depends(get_session),
) -> RegistrationResponse:
    """Register a new vendor. Validates GSTIN offline, checks for duplicates."""

    # Validate GSTIN
    gstin_check = validate_gstin(payload.gstin)
    if not gstin_check.valid:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid GSTIN: {gstin_check.reason}",
        )

    # Check for GSTIN duplicate
    existing_by_gstin = session.query(VendorRow).filter_by(gstin=payload.gstin).first()
    if existing_by_gstin:
        raise HTTPException(
            status_code=409,
            detail="A vendor with this GSTIN already exists",
        )

    # Check for phone duplicate (within same org)
    existing_by_phone = session.query(VendorRow).filter_by(
        phone=payload.phone, org_id=DEFAULT_ORG_ID
    ).first()
    if existing_by_phone:
        raise HTTPException(
            status_code=409,
            detail="A vendor with this phone number already exists",
        )

    # Check for (name + city) duplicate
    existing_by_name_city = session.query(VendorRow).filter_by(
        name=payload.name, city=payload.city, org_id=DEFAULT_ORG_ID
    ).first()
    if existing_by_name_city:
        raise HTTPException(
            status_code=409,
            detail="A vendor with this name and city already exists",
        )

    # Create vendor
    now = utc_now()
    vendor = VendorRow(
        id=str(uuid.uuid4()),
        org_id=DEFAULT_ORG_ID,
        name=payload.name,
        category=payload.category,
        gstin=payload.gstin,
        udyam_number=payload.udyam_number,
        phone=payload.phone,
        email=payload.email,
        city=payload.city,
        state=payload.state,
        lat=0.0,  # Not provided in registration form; demo only
        lng=0.0,
        languages=payload.languages,
        reliability_score=50,  # Neutral default
        on_time_rate=0.5,
        orders_completed=0,
        disputes=0,
        avg_lead_time_days=payload.lead_time_days,
        is_backup_pool=True,  # New vendors start in backup pool
        payment_terms_days=30,
        capacity_hint=payload.capacity_hint,
        price_band=payload.price_band,
        created_at=now,
        updated_at=now,
    )
    session.add(vendor)
    session.flush()

    # Record audit entry
    append_audit(
        session,
        org_id=DEFAULT_ORG_ID,
        disruption_id=None,
        actor_type="EXTERNAL",
        actor="PUBLIC_REGISTRATION",
        action="VENDOR_REGISTERED",
        detail={
            "vendor_id": vendor.id,
            "name": payload.name,
            "gstin": payload.gstin[:2] + "***" + payload.gstin[-3:],  # Masked
            "source": "public_registration",
        },
    )
    session.commit()

    # Verify the newly registered vendor
    verification = verify_vendor(session, vendor)

    return RegistrationResponse(
        vendor_id=vendor.id,
        created=True,
        reason_if_duplicate=None,
        verification=VendorVerification(
            overall_status=verification.overall_status.value,
            gstin_status=verification.gstin.status.value,
            gstin_masked=_mask_gstin(vendor.gstin),
            udyam_status=verification.udyam.status.value if verification.udyam else None,
            details=[
                VerificationDetail(
                    field="GSTIN Structure",
                    status="VALID",
                    description="GSTIN follows the correct 15-character format",
                ),
                VerificationDetail(
                    field="GSTIN Checksum",
                    status="VALID",
                    description="GSTIN checksum passes mod-36 validation",
                ),
            ],
            source=verification.gstin.source,
            checked_at=verification.checked_at,
        ),
    )
