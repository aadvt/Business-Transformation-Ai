"""ORM models — Phase 2 persistence layer.

Only portable column types are used (String, JSON, BigInteger, Boolean, Integer,
Float, DateTime(timezone=True)) so `Base.metadata.create_all` produces an
identical schema on Postgres (Neon) or sqlite. Enum-like fields are stored as
String and validated against app.schemas.enums at the repository layer, rather
than native Postgres ENUM types, for the same portability reason.

One addition beyond the literal table list in the Phase 2 brief:
`idempotency_records` — a generic (key -> cached JSON response) table. The
`approvals` table has its own `idempotency_key` column as specified, which is
enough there because at most one decision is ever recorded per approval. But
settlement execute/confirm and negotiation-outcome have no natural "already
happened" row to check against, so they need a keyed cache to honor the
Phase 1 contract's "replay idempotency_key -> identical response" guarantee.
See CLAUDE.md.
"""

from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin


class Organisation(Base, IdMixin):
    __tablename__ = "organisations"

    name: Mapped[str] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(100))
    industry: Mapped[str] = mapped_column(String(100))
    revenue_cr: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Vendor(Base, IdMixin):
    __tablename__ = "vendors"

    org_id: Mapped[str] = mapped_column(String(36), ForeignKey("organisations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(100))
    gstin: Mapped[str] = mapped_column(String(15))
    udyam_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    phone: Mapped[str] = mapped_column(String(30))
    email: Mapped[str] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(100))
    languages: Mapped[list] = mapped_column(JSON, default=list)
    reliability_score: Mapped[int] = mapped_column(Integer)
    on_time_rate: Mapped[float] = mapped_column(Float)
    orders_completed: Mapped[int] = mapped_column(Integer)
    disputes: Mapped[int] = mapped_column(Integer)
    avg_lead_time_days: Mapped[float] = mapped_column(Float)
    is_backup_pool: Mapped[bool] = mapped_column(Boolean, default=False)
    payment_terms_days: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PurchaseOrder(Base, IdMixin):
    __tablename__ = "purchase_orders"

    org_id: Mapped[str] = mapped_column(String(36), ForeignKey("organisations.id"), index=True)
    vendor_id: Mapped[str] = mapped_column(String(36), ForeignKey("vendors.id"), index=True)
    po_number: Mapped[str] = mapped_column(String(50))
    item_sku: Mapped[str] = mapped_column(String(50))
    item_name: Mapped[str] = mapped_column(String(200))
    qty: Mapped[int] = mapped_column(Integer)
    unit_price_paise: Mapped[int] = mapped_column(BigInteger)
    ordered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    promised_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(30))
    downstream_order_ref: Mapped[str | None] = mapped_column(String(50), nullable=True)
    downstream_order_value_paise: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    penalty_rate_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)


class InventorySnapshot(Base, IdMixin):
    __tablename__ = "inventory_snapshots"

    org_id: Mapped[str] = mapped_column(String(36), ForeignKey("organisations.id"), index=True)
    sku: Mapped[str] = mapped_column(String(50), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    on_hand_qty: Mapped[float] = mapped_column(Float)
    reorder_point: Mapped[float] = mapped_column(Float)
    daily_consumption: Mapped[float] = mapped_column(Float)


class CommEvent(Base, IdMixin):
    __tablename__ = "comm_events"

    org_id: Mapped[str] = mapped_column(String(36), ForeignKey("organisations.id"), index=True)
    vendor_id: Mapped[str] = mapped_column(String(36), ForeignKey("vendors.id"), index=True)
    channel: Mapped[str] = mapped_column(String(20))
    direction: Mapped[str] = mapped_column(String(10))  # INBOUND | OUTBOUND
    body: Mapped[str] = mapped_column(String(2000))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class DisruptionEvent(Base, IdMixin):
    __tablename__ = "disruption_events"

    org_id: Mapped[str] = mapped_column(String(36), ForeignKey("organisations.id"), index=True)
    type: Mapped[str] = mapped_column(String(30))
    stage: Mapped[str] = mapped_column(String(30))
    vendor_id: Mapped[str] = mapped_column(String(36), ForeignKey("vendors.id"), index=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    headline: Mapped[str] = mapped_column(String(300))
    signal_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    detector_name: Mapped[str] = mapped_column(String(50))
    detector_source: Mapped[str] = mapped_column(String(20))
    affected_po_ids: Mapped[list] = mapped_column(JSON, default=list)

    diagnosed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sourced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approval_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    negotiation_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    negotiated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    settlement_staged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Diagnosis narrative fields — kept here rather than a separate table since
    # there is exactly one diagnosis per disruption and it's small.
    root_cause: Mapped[str | None] = mapped_column(String(40), nullable=True)
    diagnosis_narrative: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    diagnosis_evidence: Mapped[list] = mapped_column(JSON, default=list)
    diagnosis_guardian_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    diagnosis_guardian_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class ExposureCalc(Base, IdMixin):
    __tablename__ = "exposure_calcs"

    disruption_id: Mapped[str] = mapped_column(String(36), ForeignKey("disruption_events.id"), index=True)
    total_paise: Mapped[int] = mapped_column(BigInteger)
    confidence: Mapped[float] = mapped_column(Float)
    breakdown: Mapped[list] = mapped_column(JSON, default=list)
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    formula_version: Mapped[str] = mapped_column(String(20))
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class VendorCandidate(Base, IdMixin):
    __tablename__ = "vendor_candidates"

    disruption_id: Mapped[str] = mapped_column(String(36), ForeignKey("disruption_events.id"), index=True)
    vendor_id: Mapped[str] = mapped_column(String(36), ForeignKey("vendors.id"), index=True)
    match_score: Mapped[float] = mapped_column(Float)
    rank: Mapped[int] = mapped_column(Integer)
    rationale: Mapped[str] = mapped_column(String(500))
    quoted_unit_price_paise: Mapped[int] = mapped_column(BigInteger)
    quoted_lead_time_days: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Verification(Base, IdMixin):
    __tablename__ = "verifications"

    vendor_id: Mapped[str] = mapped_column(String(36), ForeignKey("vendors.id"), index=True)
    disruption_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("disruption_events.id"), nullable=True, index=True
    )
    gstin_status: Mapped[str] = mapped_column(String(20))
    gstin_detail: Mapped[dict] = mapped_column(JSON, default=dict)
    udyam_status: Mapped[str] = mapped_column(String(20))
    udyam_detail: Mapped[dict] = mapped_column(JSON, default=dict)
    overall_status: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(50))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    latency_ms: Mapped[float] = mapped_column(Float)


class Approval(Base, IdMixin):
    __tablename__ = "approvals"

    disruption_id: Mapped[str] = mapped_column(String(36), ForeignKey("disruption_events.id"), index=True)
    status: Mapped[str] = mapped_column(String(20))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    channel: Mapped[str | None] = mapped_column(String(20), nullable=True)
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True, unique=True)
    presented_options: Mapped[list] = mapped_column(JSON, default=list)


class Negotiation(Base, IdMixin):
    __tablename__ = "negotiations"

    disruption_id: Mapped[str] = mapped_column(String(36), ForeignKey("disruption_events.id"), index=True)
    vendor_id: Mapped[str] = mapped_column(String(36), ForeignKey("vendors.id"), index=True)
    status: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    transcript_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    transcript_summary: Mapped[str] = mapped_column(String(1000), default="")
    rounds: Mapped[int] = mapped_column(Integer, default=0)
    opening_unit_price_paise: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    opening_lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    opening_payment_terms_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    agreed_unit_price_paise: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    agreed_lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    agreed_payment_terms_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    guardian_status: Mapped[str] = mapped_column(String(20), default="PENDING")
    guardian_detail: Mapped[dict] = mapped_column(JSON, default=dict)
    raw_outcome: Mapped[dict] = mapped_column(JSON, default=dict)


class SettlementBatchRow(Base, IdMixin):
    __tablename__ = "settlement_batches"

    org_id: Mapped[str] = mapped_column(String(36), ForeignKey("organisations.id"), index=True)
    period_month: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    status: Mapped[str] = mapped_column(String(20))
    total_paise: Mapped[int] = mapped_column(BigInteger)
    item_count: Mapped[int] = mapped_column(Integer)
    staged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(200), nullable=True)


class SettlementItem(Base, IdMixin):
    __tablename__ = "settlement_items"

    batch_id: Mapped[str] = mapped_column(String(36), ForeignKey("settlement_batches.id"), index=True)
    vendor_id: Mapped[str] = mapped_column(String(36), ForeignKey("vendors.id"), index=True)
    po_ids: Mapped[list] = mapped_column(JSON, default=list)
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20))
    reference: Mapped[str] = mapped_column(String(100))
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)


class AgentRun(Base, IdMixin):
    __tablename__ = "agent_runs"

    disruption_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("disruption_events.id"), nullable=True, index=True
    )
    agent: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    input_summary: Mapped[str] = mapped_column(String(500), default="")
    output_summary: Mapped[str] = mapped_column(String(500), default="")
    error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    token_usage: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class AuditLogEntry(Base, IdMixin):
    """Append-only. Never UPDATE or DELETE a row here — use app.services.audit.append_audit."""

    __tablename__ = "audit_log"

    org_id: Mapped[str] = mapped_column(String(36), ForeignKey("organisations.id"), index=True)
    disruption_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("disruption_events.id"), nullable=True, index=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor_type: Mapped[str] = mapped_column(String(10))  # AGENT | HUMAN | SYSTEM
    actor: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(100))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))

    __table_args__ = (UniqueConstraint("disruption_id", "seq", name="uq_audit_log_disruption_seq"),)


class IdempotencyRecord(Base, IdMixin):
    """Generic idempotency cache for endpoints whose target row can't itself carry
    the idempotency_key (settlement execute/confirm, negotiation outcome). See
    module docstring."""

    __tablename__ = "idempotency_records"

    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    endpoint: Mapped[str] = mapped_column(String(100))
    response_payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
