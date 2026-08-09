"""Exposure engine — the ONLY place a rupee amount gets computed.

Governing principle (see CLAUDE.md): the LLM never produces a number that
reaches the user. Every function here is pure Python — no DB session, no I/O,
no LLM call — so it is fully unit-testable and its arithmetic can be shown to
a judge by opening this file. `app.agents.diagnosis` gathers the inputs from
the database and hands them to `compute_exposure`; the LLM only ever narrates
what this module already computed.

    blocked_value    = Σ (undelivered_qty × unit_price_paise) over affected POs
    idle_cost        = idle_days × daily_line_cost_paise, ONLY when the caller
                       confirms the line is production-critical (see
                       `production_critical` — deliberately opt-in: we do not
                       charge idle cost on a guess)
    penalty_exposure = Σ (downstream_order_value_paise × penalty_rate_bps / 10_000)
                       over POs that carry both fields
    expedite_premium = Σ max(0, best_backup_unit_price − po.unit_price_paise) × po.undelivered_qty
                       over affected POs, 0 until a backup quote exists
    total_paise      = blocked_value + idle_cost + penalty_exposure + expedite_premium

`confidence` is the fraction of four completeness signals that are true:
downstream order linked, penalty rate known, consumption rate known (i.e. is
`production_critical` a confirmed fact rather than an unknown), backup quote
available. `missing_inputs` names whichever are false, in the same order.
"""

from dataclasses import dataclass, field

from app.schemas.money import format_inr

FORMULA_VERSION = "v1"


@dataclass(frozen=True)
class AffectedPO:
    po_id: str
    po_number: str
    undelivered_qty: int
    unit_price_paise: int
    downstream_order_ref: str | None = None
    downstream_order_value_paise: int | None = None
    penalty_rate_bps: int | None = None

    def __post_init__(self) -> None:
        if self.undelivered_qty < 0:
            raise ValueError(f"undelivered_qty must be >= 0, got {self.undelivered_qty}")
        if self.unit_price_paise < 0:
            raise ValueError(f"unit_price_paise must be >= 0, got {self.unit_price_paise}")

    @property
    def has_penalty_exposure(self) -> bool:
        return self.downstream_order_value_paise is not None and self.penalty_rate_bps is not None


@dataclass(frozen=True)
class BackupQuote:
    vendor_name: str
    unit_price_paise: int


@dataclass(frozen=True)
class ExposureBreakdownItem:
    label: str
    amount_paise: int
    basis: str


@dataclass(frozen=True)
class ExposureResult:
    total_paise: int
    confidence: float
    breakdown: list[ExposureBreakdownItem]
    inputs: dict
    missing_inputs: list[str]
    formula_version: str = FORMULA_VERSION


def compute_exposure(
    affected_pos: list[AffectedPO],
    *,
    idle_days: int = 0,
    daily_line_cost_paise: int = 0,
    production_critical: bool = False,
    consumption_rate_known: bool = False,
    best_backup_quote: BackupQuote | None = None,
) -> ExposureResult:
    if idle_days < 0:
        raise ValueError(f"idle_days must be >= 0, got {idle_days}")
    if daily_line_cost_paise < 0:
        raise ValueError(f"daily_line_cost_paise must be >= 0, got {daily_line_cost_paise}")

    breakdown: list[ExposureBreakdownItem] = []

    # --- blocked_value ---------------------------------------------------
    blocked_value = 0
    for po in affected_pos:
        if po.undelivered_qty == 0:
            continue
        amount = po.undelivered_qty * po.unit_price_paise
        blocked_value += amount
        breakdown.append(
            ExposureBreakdownItem(
                label=f"Blocked inventory value ({po.po_number})",
                amount_paise=amount,
                basis=(
                    f"{po.undelivered_qty:,} units × {format_inr(po.unit_price_paise)} "
                    f"undelivered on {po.po_number}"
                ),
            )
        )

    # --- idle_cost ---------------------------------------------------------
    idle_cost = 0
    if production_critical and idle_days > 0 and daily_line_cost_paise > 0:
        idle_cost = idle_days * daily_line_cost_paise
        breakdown.append(
            ExposureBreakdownItem(
                label="Idle production line cost",
                amount_paise=idle_cost,
                basis=f"{idle_days} day(s) of line downtime at {format_inr(daily_line_cost_paise)}/day",
            )
        )

    # --- penalty_exposure ----------------------------------------------------
    penalty_exposure = 0
    for po in affected_pos:
        if not po.has_penalty_exposure:
            continue
        amount = (po.downstream_order_value_paise * po.penalty_rate_bps) // 10_000
        penalty_exposure += amount
        breakdown.append(
            ExposureBreakdownItem(
                label=f"Contractual delay penalty ({po.downstream_order_ref or po.po_number})",
                amount_paise=amount,
                basis=(
                    f"{po.penalty_rate_bps} bps of {format_inr(po.downstream_order_value_paise)} "
                    f"downstream order value ({po.downstream_order_ref or 'ref unknown'})"
                ),
            )
        )

    # --- expedite_premium -----------------------------------------------------
    expedite_premium = 0
    if best_backup_quote is not None:
        for po in affected_pos:
            if po.undelivered_qty == 0:
                continue
            delta = best_backup_quote.unit_price_paise - po.unit_price_paise
            if delta <= 0:
                continue
            amount = delta * po.undelivered_qty
            expedite_premium += amount
            breakdown.append(
                ExposureBreakdownItem(
                    label=f"Expedite premium ({po.po_number})",
                    amount_paise=amount,
                    basis=(
                        f"{po.undelivered_qty:,} units × ({format_inr(best_backup_quote.unit_price_paise)} "
                        f"{best_backup_quote.vendor_name} quote − {format_inr(po.unit_price_paise)} original price)"
                    ),
                )
            )

    total_paise = blocked_value + idle_cost + penalty_exposure + expedite_premium

    downstream_linked = any(po.downstream_order_ref is not None for po in affected_pos)
    penalty_rate_known = any(po.has_penalty_exposure for po in affected_pos)
    backup_quote_available = best_backup_quote is not None

    signals = {
        "downstream order linked": downstream_linked,
        "penalty rate known": penalty_rate_known,
        "consumption rate known": consumption_rate_known,
        "backup vendor quote available": backup_quote_available,
    }
    missing_inputs = [label for label, present in signals.items() if not present]
    confidence = round(sum(signals.values()) / len(signals), 4)

    inputs = {
        "affected_pos": [
            {
                "po_id": po.po_id,
                "po_number": po.po_number,
                "undelivered_qty": po.undelivered_qty,
                "unit_price_paise": po.unit_price_paise,
                "downstream_order_ref": po.downstream_order_ref,
                "downstream_order_value_paise": po.downstream_order_value_paise,
                "penalty_rate_bps": po.penalty_rate_bps,
            }
            for po in affected_pos
        ],
        "idle_days": idle_days,
        "daily_line_cost_paise": daily_line_cost_paise,
        "production_critical": production_critical,
        "consumption_rate_known": consumption_rate_known,
        "best_backup_quote": (
            {"vendor_name": best_backup_quote.vendor_name, "unit_price_paise": best_backup_quote.unit_price_paise}
            if best_backup_quote is not None
            else None
        ),
        "blocked_value_paise": blocked_value,
        "idle_cost_paise": idle_cost,
        "penalty_exposure_paise": penalty_exposure,
        "expedite_premium_paise": expedite_premium,
    }

    return ExposureResult(
        total_paise=total_paise,
        confidence=confidence,
        breakdown=breakdown,
        inputs=inputs,
        missing_inputs=missing_inputs,
    )
