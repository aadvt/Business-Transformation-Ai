"""Exposure engine tests. Every case's expected total is computed by hand in
the test itself (not copied from the implementation) — this is the arithmetic
a judge gets shown if they ask "how did you get ₹6.2 lakh".
"""

import pytest

from app.services.exposure import AffectedPO, BackupQuote, compute_exposure


def po(**kwargs) -> AffectedPO:
    defaults = dict(po_id="po-1", po_number="PO-001", undelivered_qty=100, unit_price_paise=10_000)
    defaults.update(kwargs)
    return AffectedPO(**defaults)


def test_blocked_value_only_single_po():
    result = compute_exposure([po(undelivered_qty=1200, unit_price_paise=42_000)])
    assert result.total_paise == 1200 * 42_000 == 50_400_000
    assert len(result.breakdown) == 1
    assert result.breakdown[0].amount_paise == 50_400_000
    assert "PO-001" in result.breakdown[0].basis


def test_zero_penalty_when_no_downstream_link():
    result = compute_exposure([po(undelivered_qty=1200, unit_price_paise=42_000)])
    assert result.inputs["penalty_exposure_paise"] == 0
    assert not any("penalty" in item.label.lower() for item in result.breakdown)
    assert "downstream order linked" in result.missing_inputs
    assert "penalty rate known" in result.missing_inputs


def test_penalty_exposure_hand_calculated_golden_path():
    """This is the seeded delivery_delay_castings scenario's actual PO. By hand:
    blocked = 1200 * 42000 = 50,400,000 paise
    penalty = 1,300,000,000 * 125 // 10000 = 16,250,000 paise
    total   = 66,650,000 paise = Rs 6,66,500 -> squarely in the "Rs 6-7 lakh" range."""
    result = compute_exposure(
        [
            po(
                po_number="PO-SCN-A-001",
                undelivered_qty=1200,
                unit_price_paise=42_000,
                downstream_order_ref="SO-2026-0842",
                downstream_order_value_paise=1_300_000_000,
                penalty_rate_bps=125,
            )
        ]
    )
    assert result.total_paise == 66_650_000
    assert result.inputs["blocked_value_paise"] == 50_400_000
    assert result.inputs["penalty_exposure_paise"] == 16_250_000


def test_multi_po_aggregation():
    pos = [
        po(po_id="a", po_number="PO-A", undelivered_qty=100, unit_price_paise=5_000),
        po(po_id="b", po_number="PO-B", undelivered_qty=50, unit_price_paise=20_000),
    ]
    result = compute_exposure(pos)
    expected = (100 * 5_000) + (50 * 20_000)
    assert result.total_paise == expected == 1_500_000
    assert len(result.breakdown) == 2


def test_idle_cost_zero_without_production_critical_flag():
    result = compute_exposure([po()], idle_days=5, daily_line_cost_paise=1_000_000, production_critical=False)
    assert result.inputs["idle_cost_paise"] == 0
    assert not any("idle" in item.label.lower() for item in result.breakdown)


def test_idle_cost_applied_when_production_critical():
    result = compute_exposure([po()], idle_days=5, daily_line_cost_paise=1_000_000, production_critical=True)
    assert result.inputs["idle_cost_paise"] == 5 * 1_000_000 == 5_000_000
    assert result.total_paise == po().undelivered_qty * po().unit_price_paise + 5_000_000


def test_idle_cost_zero_when_idle_days_zero_even_if_critical():
    result = compute_exposure([po()], idle_days=0, daily_line_cost_paise=1_000_000, production_critical=True)
    assert result.inputs["idle_cost_paise"] == 0


def test_expedite_premium_zero_without_backup_quote():
    result = compute_exposure([po(undelivered_qty=100, unit_price_paise=10_000)])
    assert result.inputs["expedite_premium_paise"] == 0
    assert "backup vendor quote available" in result.missing_inputs


def test_expedite_premium_hand_calculated():
    result = compute_exposure(
        [po(undelivered_qty=100, unit_price_paise=10_000)],
        best_backup_quote=BackupQuote(vendor_name="Kohinoor Precision", unit_price_paise=14_500),
    )
    expected = (14_500 - 10_000) * 100
    assert result.inputs["expedite_premium_paise"] == expected == 450_000
    assert result.total_paise == 100 * 10_000 + 450_000


def test_expedite_premium_ignores_cheaper_or_equal_backup_quote():
    result = compute_exposure(
        [po(undelivered_qty=100, unit_price_paise=10_000)],
        best_backup_quote=BackupQuote(vendor_name="Cheaper Vendor", unit_price_paise=9_000),
    )
    assert result.inputs["expedite_premium_paise"] == 0

    result_equal = compute_exposure(
        [po(undelivered_qty=100, unit_price_paise=10_000)],
        best_backup_quote=BackupQuote(vendor_name="Same Price Vendor", unit_price_paise=10_000),
    )
    assert result_equal.inputs["expedite_premium_paise"] == 0


def test_confidence_is_zero_with_no_signals():
    result = compute_exposure([po()])
    assert result.confidence == 0.0
    assert len(result.missing_inputs) == 4


def test_confidence_is_one_with_all_signals_present():
    result = compute_exposure(
        [
            po(
                downstream_order_ref="SO-1",
                downstream_order_value_paise=1_000_000,
                penalty_rate_bps=100,
            )
        ],
        consumption_rate_known=True,
        best_backup_quote=BackupQuote(vendor_name="V", unit_price_paise=99_999_999),
    )
    assert result.confidence == 1.0
    assert result.missing_inputs == []


def test_confidence_partial_signals():
    result = compute_exposure(
        [po(downstream_order_ref="SO-1", downstream_order_value_paise=1_000_000, penalty_rate_bps=100)]
    )
    # downstream linked + penalty known = 2 of 4
    assert result.confidence == 0.5
    assert set(result.missing_inputs) == {"consumption rate known", "backup vendor quote available"}


def test_zero_qty_po_produces_no_blocked_value_breakdown_row():
    result = compute_exposure([po(undelivered_qty=0)])
    assert result.inputs["blocked_value_paise"] == 0
    assert result.breakdown == []


def test_negative_undelivered_qty_raises():
    with pytest.raises(ValueError):
        po(undelivered_qty=-1)


def test_negative_unit_price_raises():
    with pytest.raises(ValueError):
        po(unit_price_paise=-1)


def test_negative_idle_days_raises():
    with pytest.raises(ValueError):
        compute_exposure([po()], idle_days=-1, daily_line_cost_paise=100)


def test_total_always_equals_sum_of_components():
    result = compute_exposure(
        [
            po(
                po_id="a", po_number="PO-A", undelivered_qty=200, unit_price_paise=15_000,
                downstream_order_ref="SO-9", downstream_order_value_paise=5_000_000, penalty_rate_bps=200,
            ),
            po(po_id="b", po_number="PO-B", undelivered_qty=50, unit_price_paise=8_000),
        ],
        idle_days=3, daily_line_cost_paise=200_000, production_critical=True,
        best_backup_quote=BackupQuote(vendor_name="V", unit_price_paise=20_000),
    )
    component_sum = (
        result.inputs["blocked_value_paise"]
        + result.inputs["idle_cost_paise"]
        + result.inputs["penalty_exposure_paise"]
        + result.inputs["expedite_premium_paise"]
    )
    assert result.total_paise == component_sum


def test_formula_version_recorded():
    result = compute_exposure([po()])
    assert result.formula_version == "v1"


def test_breakdown_amounts_are_ints_never_floats():
    result = compute_exposure(
        [po(downstream_order_ref="SO-1", downstream_order_value_paise=1_000_003, penalty_rate_bps=333)]
    )
    for item in result.breakdown:
        assert isinstance(item.amount_paise, int)
    assert isinstance(result.total_paise, int)
