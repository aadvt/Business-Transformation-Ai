"""GSTIN/Udyam verification — offline-first, provider-optional, always cached.

GSTIN has a real public checksum algorithm (app.services.gstin), so it always
gets a definitive VERIFIED/FAILED from that offline check alone — a live
provider, if configured, can corroborate it, but an unreachable provider never
downgrades GSTIN to UNAVAILABLE. Udyam registration numbers have no published
checksum, so Udyam verification is provider-dependent: no provider configured,
or the provider times out, means UNAVAILABLE for Udyam specifically.

Results are cached in the `verifications` table for `verification_cache_ttl_hours`
so repeat demo runs against the same vendor are instant and don't depend on a
live provider being reachable. Never returns a bare boolean — always status +
the fields actually checked + source + checked_at, because the frontend needs
evidence to show, not a green tick.
"""

import time
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Verification as VerificationRow, Vendor as VendorRow
from app.schemas.enums import VerificationStatus
from app.schemas.money import as_utc, to_iso, utc_now
from app.services.gstin import validate_gstin

OFFLINE_SOURCE = "OFFLINE_CHECKSUM"
NO_PROVIDER_SOURCE = "NO_PROVIDER_CONFIGURED"

# Worst-first, used to combine two check statuses into one overall status.
_STATUS_PRIORITY = [
    VerificationStatus.FAILED,
    VerificationStatus.UNAVAILABLE,
    VerificationStatus.UNVERIFIED,
    VerificationStatus.VERIFIED,
]


@dataclass(frozen=True)
class CheckResult:
    status: VerificationStatus
    detail: dict[str, Any]
    source: str


@dataclass(frozen=True)
class VerificationResult:
    overall_status: VerificationStatus
    gstin: CheckResult
    udyam: CheckResult
    checked_at: str
    latency_ms: float
    from_cache: bool = False


def _worse(a: VerificationStatus, b: VerificationStatus) -> VerificationStatus:
    return a if _STATUS_PRIORITY.index(a) <= _STATUS_PRIORITY.index(b) else b


def _check_gstin_offline(gstin: str) -> CheckResult:
    check = validate_gstin(gstin)
    status = VerificationStatus.VERIFIED if check.valid else VerificationStatus.FAILED
    return CheckResult(
        status=status,
        detail={
            "gstin": gstin,
            "structure_valid": check.structure_valid,
            "checksum_valid": check.checksum_valid,
            "reason": check.reason,
        },
        source=OFFLINE_SOURCE,
    )


def _call_provider(path: str, payload: dict) -> dict | None:
    """Returns the provider's JSON body, or None on any failure (timeout,
    connection error, non-2xx). Never raises — an unreachable provider is an
    expected, handled case, not an error path."""
    if not settings.verification_provider_url:
        return None
    try:
        response = httpx.post(
            f"{settings.verification_provider_url.rstrip('/')}{path}",
            json=payload,
            headers={"Authorization": f"Bearer {settings.verification_provider_api_key}"},
            timeout=settings.verification_timeout_seconds,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError:
        return None


def _check_gstin_with_provider(gstin: str) -> CheckResult:
    """Offline result is always computed first and is the fallback; the
    provider, if it answers, can only corroborate — never downgrade GSTIN to
    UNAVAILABLE, since we always have a definitive offline answer."""
    offline = _check_gstin_offline(gstin)
    body = _call_provider("/gstin/verify", {"gstin": gstin})
    if body is None:
        return CheckResult(
            status=offline.status,
            detail={**offline.detail, "provider": "unreachable, offline result stands"},
            source=offline.source,
        )
    provider_verified = bool(body.get("verified"))
    status = VerificationStatus.VERIFIED if provider_verified else offline.status
    return CheckResult(
        status=status,
        detail={**offline.detail, "provider_response": body},
        source=settings.verification_provider,
    )


def _check_udyam(udyam_number: str | None) -> CheckResult:
    if not udyam_number:
        return CheckResult(
            status=VerificationStatus.UNVERIFIED,
            detail={"udyam_number": None, "reason": "vendor has no Udyam registration on file"},
            source=NO_PROVIDER_SOURCE,
        )
    if not settings.verification_provider_url:
        return CheckResult(
            status=VerificationStatus.UNAVAILABLE,
            detail={"udyam_number": udyam_number, "reason": "no verification provider configured"},
            source=NO_PROVIDER_SOURCE,
        )
    body = _call_provider("/udyam/verify", {"udyam_number": udyam_number})
    if body is None:
        return CheckResult(
            status=VerificationStatus.UNAVAILABLE,
            detail={"udyam_number": udyam_number, "reason": "provider unreachable or timed out"},
            source=settings.verification_provider,
        )
    status = VerificationStatus.VERIFIED if body.get("verified") else VerificationStatus.FAILED
    return CheckResult(
        status=status,
        detail={"udyam_number": udyam_number, "provider_response": body},
        source=settings.verification_provider,
    )


def _fresh_enough(row: VerificationRow) -> bool:
    return utc_now() - as_utc(row.checked_at) <= timedelta(hours=settings.verification_cache_ttl_hours)


def _get_cached(session: Session, vendor_id: str) -> VerificationRow | None:
    row = session.execute(
        select(VerificationRow)
        .where(VerificationRow.vendor_id == vendor_id)
        .order_by(VerificationRow.checked_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        return None
    return row if _fresh_enough(row) else None


def load_verification_cache(session: Session, vendor_ids: list[str]) -> dict[str, VerificationRow]:
    """One query's worth of cached verifications for many vendors, to be passed
    into `verify_vendor(..., cache=...)`. Verifying a directory page one vendor
    at a time meant one cache-lookup round-trip per row — seconds of latency on
    a 24-vendor list, for checks that are themselves offline and instant."""
    if not vendor_ids:
        return {}
    rows = session.execute(
        select(VerificationRow)
        .where(VerificationRow.vendor_id.in_(vendor_ids))
        .order_by(VerificationRow.checked_at.asc())
    ).scalars().all()
    # Ascending, so the last write per vendor wins — same "most recent
    # checked_at" rule the single-vendor lookup applies.
    latest: dict[str, VerificationRow] = {r.vendor_id: r for r in rows}
    return {vid: row for vid, row in latest.items() if _fresh_enough(row)}


def verify_vendor(
    session: Session,
    vendor: VendorRow,
    *,
    disruption_id: str | None = None,
    cache: dict[str, VerificationRow] | None = None,
) -> VerificationResult:
    cached = cache.get(vendor.id) if cache is not None else _get_cached(session, vendor.id)
    if cached is not None:
        return VerificationResult(
            overall_status=VerificationStatus(cached.overall_status),
            gstin=CheckResult(status=VerificationStatus(cached.gstin_status), detail=cached.gstin_detail, source=cached.source),
            udyam=CheckResult(status=VerificationStatus(cached.udyam_status), detail=cached.udyam_detail, source=cached.source),
            checked_at=to_iso(cached.checked_at),
            latency_ms=cached.latency_ms,
            from_cache=True,
        )

    start = time.monotonic()
    if settings.verification_provider:
        gstin_result = _check_gstin_with_provider(vendor.gstin)
    else:
        gstin_result = _check_gstin_offline(vendor.gstin)
    udyam_result = _check_udyam(vendor.udyam_number)
    latency_ms = (time.monotonic() - start) * 1000

    overall = _worse(gstin_result.status, udyam_result.status)
    now = utc_now()
    source = gstin_result.source if gstin_result.source != OFFLINE_SOURCE else (udyam_result.source or OFFLINE_SOURCE)

    session.add(
        VerificationRow(
            id=str(uuid.uuid4()),
            vendor_id=vendor.id,
            disruption_id=disruption_id,
            gstin_status=gstin_result.status.value,
            gstin_detail=gstin_result.detail,
            udyam_status=udyam_result.status.value,
            udyam_detail=udyam_result.detail,
            overall_status=overall.value,
            source=source,
            checked_at=now,
            latency_ms=latency_ms,
        )
    )

    return VerificationResult(
        overall_status=overall,
        gstin=gstin_result,
        udyam=udyam_result,
        checked_at=to_iso(now),
        latency_ms=latency_ms,
        from_cache=False,
    )
