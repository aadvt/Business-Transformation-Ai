"""Pydantic data model for the Transaction Agent.

State machine:

    Created -> PendingApproval -> Approved -> Processing -> Completed
                                                           -> Failed
               PendingApproval -> Rejected
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str = "txn") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class TransactionStatus(str, Enum):
    CREATED = "Created"
    PENDING_APPROVAL = "PendingApproval"
    APPROVED = "Approved"
    PROCESSING = "Processing"
    COMPLETED = "Completed"
    FAILED = "Failed"
    REJECTED = "Rejected"


class Transaction(BaseModel):
    id: str = Field(default_factory=new_id)
    recipient: str
    recipient_id: Optional[str] = None  # resolved recipient directory entry, later phase
    amount: float
    currency: str = "INR"
    purpose: Optional[str] = None
    status: TransactionStatus = TransactionStatus.CREATED

    # provenance: the raw text fragment this transaction was interpreted from
    interpreted_from: Optional[str] = None

    # lifecycle timestamps
    created_at: Optional[str] = None
    entered_queue_at: Optional[str] = None
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    execution_started_at: Optional[str] = None

    # result of the (simulated) execution attempt
    execution_result: Optional[dict[str, Any]] = None


class AuditEntry(BaseModel):
    """One state transition, persisted for a full audit trail."""

    entry_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    transaction_id: str
    from_status: Optional[str]
    to_status: str
    timestamp: str = Field(default_factory=utcnow_iso)
    note: Optional[str] = None


class ParsedTransactionItem(BaseModel):
    """One payment instruction extracted from free text, before it becomes a Transaction."""

    recipient: str = Field(description="Name of the payee / recipient")
    amount: float = Field(description="Numeric payment amount, no currency symbols or commas")
    currency: str = Field(default="INR", description="ISO-ish currency code, default INR")
    purpose: Optional[str] = Field(default=None, description="Stated purpose of the payment, if any")


class ParsedTransactionList(BaseModel):
    """Structured-output envelope: every payment instruction found in the user's message."""

    transactions: list[ParsedTransactionItem] = Field(default_factory=list)
