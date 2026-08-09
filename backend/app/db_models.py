"""SQLAlchemy models mirroring the real Neon schema exactly, as introspected
(information_schema.columns / table_constraints) against the live database —
not a redesign. Every table already exists and is populated; nothing here
should ever run `create_all`, `DROP`, or `ALTER`. IDs are the app-generated
UUID strings already in use (character varying, not a Postgres uuid column),
consistent with the rest of this codebase's "string UUIDv4 everywhere"
convention.

Relationships are defined only where a router actually needs the join, with
explicit foreign_keys where a table has more than one FK to the same target
column shape (e.g. two disruption-scoped tables both point at
disruption_events.id).
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Organisation(Base):
    __tablename__ = "organisations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    city: Mapped[str] = mapped_column(String)
    industry: Mapped[str] = mapped_column(String)
    revenue_cr: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Vendor(Base):
    __tablename__ = "vendors"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organisations.id"))
    name: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String)
    gstin: Mapped[str] = mapped_column(String)
    udyam_number: Mapped[str | None] = mapped_column(String, nullable=True)
    phone: Mapped[str] = mapped_column(String)
    email: Mapped[str] = mapped_column(String)
    city: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String)
    languages: Mapped[list] = mapped_column(JSON)
    reliability_score: Mapped[int] = mapped_column(Integer)
    on_time_rate: Mapped[float] = mapped_column(Float)
    orders_completed: Mapped[int] = mapped_column(Integer)
    disputes: Mapped[int] = mapped_column(Integer)
    avg_lead_time_days: Mapped[float] = mapped_column(Float)
    is_backup_pool: Mapped[bool] = mapped_column(Boolean)
    payment_terms_days: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DisruptionEvent(Base):
    __tablename__ = "disruption_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organisations.id"))
    type: Mapped[str] = mapped_column(String)
    stage: Mapped[str] = mapped_column(String)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id"))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    headline: Mapped[str] = mapped_column(String)
    signal_payload: Mapped[dict] = mapped_column(JSON)
    detector_name: Mapped[str] = mapped_column(String)
    detector_source: Mapped[str] = mapped_column(String)
    affected_po_ids: Mapped[list] = mapped_column(JSON)
    diagnosed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sourced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approval_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    negotiation_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    negotiated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    settlement_staged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    root_cause: Mapped[str | None] = mapped_column(String, nullable=True)
    diagnosis_narrative: Mapped[str | None] = mapped_column(String, nullable=True)
    diagnosis_evidence: Mapped[list] = mapped_column(JSON)
    diagnosis_guardian_status: Mapped[str | None] = mapped_column(String, nullable=True)
    diagnosis_guardian_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    vendor: Mapped[Vendor] = relationship(lazy="joined")
    exposure_calc: Mapped["ExposureCalc | None"] = relationship(back_populates="disruption", uselist=False)
    approval: Mapped["Approval | None"] = relationship(back_populates="disruption", uselist=False)
    negotiation: Mapped["Negotiation | None"] = relationship(back_populates="disruption", uselist=False)
    candidates: Mapped[list["VendorCandidate"]] = relationship(back_populates="disruption")


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organisations.id"))
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id"))
    po_number: Mapped[str] = mapped_column(String)
    item_sku: Mapped[str] = mapped_column(String)
    item_name: Mapped[str] = mapped_column(String)
    qty: Mapped[int] = mapped_column(Integer)
    unit_price_paise: Mapped[int] = mapped_column(BigInteger)
    ordered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    promised_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String)
    downstream_order_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    downstream_order_value_paise: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    penalty_rate_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)


class InventorySnapshot(Base):
    __tablename__ = "inventory_snapshots"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organisations.id"))
    sku: Mapped[str] = mapped_column(String)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    on_hand_qty: Mapped[float] = mapped_column(Float)
    reorder_point: Mapped[float] = mapped_column(Float)
    daily_consumption: Mapped[float] = mapped_column(Float)


class CommEvent(Base):
    __tablename__ = "comm_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organisations.id"))
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id"))
    channel: Mapped[str] = mapped_column(String)
    direction: Mapped[str] = mapped_column(String)
    body: Mapped[str] = mapped_column(String)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class VendorCandidate(Base):
    __tablename__ = "vendor_candidates"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    disruption_id: Mapped[str] = mapped_column(ForeignKey("disruption_events.id"))
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id"))
    match_score: Mapped[float] = mapped_column(Float)
    rank: Mapped[int] = mapped_column(Integer)
    rationale: Mapped[str] = mapped_column(String)
    quoted_unit_price_paise: Mapped[int] = mapped_column(BigInteger)
    quoted_lead_time_days: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    disruption: Mapped[DisruptionEvent] = relationship(back_populates="candidates")
    vendor: Mapped[Vendor] = relationship(lazy="joined")
    # No formal relationship to Verification: it's matched on a
    # (disruption_id, vendor_id) pair rather than a single FK, which makes a
    # declarative relationship() need a string-evaluated composite join with
    # a forward reference — fragile for what it buys. The router fetches
    # verifications for the relevant disruption with a plain second query
    # and matches them up in Python instead.


class Verification(Base):
    __tablename__ = "verifications"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id"))
    disruption_id: Mapped[str | None] = mapped_column(ForeignKey("disruption_events.id"), nullable=True)
    gstin_status: Mapped[str] = mapped_column(String)
    gstin_detail: Mapped[dict] = mapped_column(JSON)
    udyam_status: Mapped[str] = mapped_column(String)
    udyam_detail: Mapped[dict] = mapped_column(JSON)
    overall_status: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    latency_ms: Mapped[float] = mapped_column(Float)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    disruption_id: Mapped[str | None] = mapped_column(ForeignKey("disruption_events.id"), nullable=True)
    agent: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_id: Mapped[str | None] = mapped_column(String, nullable=True)
    input_summary: Mapped[str] = mapped_column(String)
    output_summary: Mapped[str] = mapped_column(String)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    token_usage: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class ExposureCalc(Base):
    __tablename__ = "exposure_calcs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    disruption_id: Mapped[str] = mapped_column(ForeignKey("disruption_events.id"))
    total_paise: Mapped[int] = mapped_column(BigInteger)
    confidence: Mapped[float] = mapped_column(Float)
    breakdown: Mapped[list] = mapped_column(JSON)
    inputs: Mapped[dict] = mapped_column(JSON)
    formula_version: Mapped[str] = mapped_column(String)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    disruption: Mapped[DisruptionEvent] = relationship(back_populates="exposure_calc")


class Negotiation(Base):
    __tablename__ = "negotiations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    disruption_id: Mapped[str] = mapped_column(ForeignKey("disruption_events.id"))
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id"))
    status: Mapped[str] = mapped_column(String)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    transcript_url: Mapped[str | None] = mapped_column(String, nullable=True)
    transcript_summary: Mapped[str] = mapped_column(String)
    rounds: Mapped[int] = mapped_column(Integer)
    opening_unit_price_paise: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    opening_lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    opening_payment_terms_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    agreed_unit_price_paise: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    agreed_lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    agreed_payment_terms_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    guardian_status: Mapped[str] = mapped_column(String)
    guardian_detail: Mapped[dict] = mapped_column(JSON)
    raw_outcome: Mapped[dict] = mapped_column(JSON)

    disruption: Mapped[DisruptionEvent] = relationship(back_populates="negotiation")
    vendor: Mapped[Vendor] = relationship(lazy="joined")


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    disruption_id: Mapped[str] = mapped_column(ForeignKey("disruption_events.id"))
    status: Mapped[str] = mapped_column(String)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String, nullable=True)
    channel: Mapped[str | None] = mapped_column(String, nullable=True)
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String, nullable=True)
    presented_options: Mapped[list] = mapped_column(JSON)

    disruption: Mapped[DisruptionEvent] = relationship(back_populates="approval")


class AuditLogEntry(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organisations.id"))
    disruption_id: Mapped[str | None] = mapped_column(ForeignKey("disruption_events.id"), nullable=True)
    seq: Mapped[int] = mapped_column(Integer)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor_type: Mapped[str] = mapped_column(String)
    actor: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    detail: Mapped[dict] = mapped_column(JSON)
    prev_hash: Mapped[str] = mapped_column(String)
    hash: Mapped[str] = mapped_column(String)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String, unique=True)
    endpoint: Mapped[str] = mapped_column(String)
    response_payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SettlementBatch(Base):
    __tablename__ = "settlement_batches"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organisations.id"))
    period_month: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    total_paise: Mapped[int] = mapped_column(BigInteger)
    item_count: Mapped[int] = mapped_column(Integer)
    staged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String, nullable=True)

    items: Mapped[list["SettlementItem"]] = relationship(back_populates="batch")


class SettlementItem(Base):
    __tablename__ = "settlement_items"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("settlement_batches.id"))
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id"))
    po_ids: Mapped[list] = mapped_column(JSON)
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String)
    reference: Mapped[str] = mapped_column(String)
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    batch: Mapped[SettlementBatch] = relationship(back_populates="items")
    vendor: Mapped[Vendor] = relationship(lazy="joined")
