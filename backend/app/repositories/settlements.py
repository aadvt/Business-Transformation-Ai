from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    SettlementBatchRow,
    SettlementItem,
    Vendor as VendorRow,
)
from app.repositories._idempotency import idempotent
from app.schemas.money import format_inr, to_iso, utc_now
from app.schemas.settlement import (
    SettlementBatch,
    SettlementBatchList,
    SettlementConfirmResponse,
    SettlementExecuteResponse,
    SettlementLine,
)
from app.schemas.vendors import VendorRef
from app.services.audit import append_audit


def _to_schema(session: Session, row: SettlementBatchRow) -> SettlementBatch:
    items = session.execute(select(SettlementItem).where(SettlementItem.batch_id == row.id)).scalars().all()
    # One vendor lookup for the whole batch rather than one per invoice line.
    vendor_ids = {i.vendor_id for i in items}
    vendors_by_id = {
        v.id: v for v in session.execute(select(VendorRow).where(VendorRow.id.in_(vendor_ids))).scalars().all()
    } if vendor_ids else {}
    lines: list[SettlementLine] = []
    for item in items:
        vendor = vendors_by_id.get(item.vendor_id)
        lines.append(
            SettlementLine(
                vendor=VendorRef(id=vendor.id, name=vendor.name, gstin=vendor.gstin) if vendor else VendorRef(id=item.vendor_id, name="Unknown", gstin=""),
                invoice_id=item.reference,
                amount_paise=item.amount_paise,
                amount_display=format_inr(item.amount_paise),
                due_date=item.due_date.isoformat() if item.due_date else "",
            )
        )
    return SettlementBatch(
        id=row.id, created_at=to_iso(row.staged_at), updated_at=to_iso(row.confirmed_at or row.approved_at or row.staged_at),
        month=row.period_month, status=row.status, total_paise=row.total_paise, total_display=format_inr(row.total_paise),
        lines=lines, confirmed_at=to_iso(row.confirmed_at) if row.confirmed_at else None, confirmed_by=row.approved_by,
    )


def list_batches(session: Session, month: str | None) -> SettlementBatchList:
    query = select(SettlementBatchRow).order_by(SettlementBatchRow.period_month.desc())
    if month:
        query = query.where(SettlementBatchRow.period_month == month)
    rows = session.execute(query).scalars().all()
    items = [_to_schema(session, r) for r in rows]
    return SettlementBatchList(items=items, total=len(items))


def execute_batch(
    session: Session, batch_id: str, idempotency_key: str, executed_by: str, org_id: str
) -> tuple[SettlementExecuteResponse | None, bool]:
    row = session.get(SettlementBatchRow, batch_id)
    if row is None:
        return None, False

    def _do() -> dict:
        row.status = "EXECUTING"
        append_audit(
            session, org_id=org_id, actor_type="HUMAN", actor=executed_by, action="SETTLEMENT_EXECUTED",
            detail={"batch_id": batch_id},
        )
        session.flush()
        return SettlementExecuteResponse(batch=_to_schema(session, row)).model_dump()

    payload, is_replay = idempotent(session, idempotency_key, "settlements.execute", _do)
    return SettlementExecuteResponse.model_validate(payload), is_replay


def confirm_batch(
    session: Session, batch_id: str, idempotency_key: str, confirmed_by: str, org_id: str
) -> tuple[SettlementConfirmResponse | None, bool]:
    row = session.get(SettlementBatchRow, batch_id)
    if row is None:
        return None, False

    def _do() -> dict:
        now = utc_now()
        row.status = "CONFIRMED"
        row.confirmed_at = now
        row.approved_by = confirmed_by
        for item in session.execute(select(SettlementItem).where(SettlementItem.batch_id == batch_id)).scalars().all():
            item.status = "CONFIRMED"
        append_audit(
            session, org_id=org_id, actor_type="HUMAN", actor=confirmed_by, action="SETTLEMENT_CONFIRMED",
            detail={"batch_id": batch_id}, at=now,
        )
        session.flush()
        return SettlementConfirmResponse(batch=_to_schema(session, row)).model_dump()

    payload, is_replay = idempotent(session, idempotency_key, "settlements.confirm", _do)
    return SettlementConfirmResponse.model_validate(payload), is_replay
