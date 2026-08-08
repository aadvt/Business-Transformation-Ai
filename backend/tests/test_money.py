from app.mocks.loader import store
from app.schemas.money import format_inr, format_inr_short


def test_format_inr_thousands():
    assert format_inr(150000) == "₹1,500"


def test_format_inr_lakh():
    assert format_inr(620000000) == "₹62,00,000"


def test_format_inr_crore():
    assert format_inr(6200000000) == "₹6,20,00,000"


def test_format_inr_hundreds():
    assert format_inr(50000) == "₹500"


def test_format_inr_zero():
    assert format_inr(0) == "₹0"


def test_format_inr_negative():
    assert format_inr(-620000000) == "-₹62,00,000"


def test_format_inr_short_lakh():
    assert format_inr_short(620000000) == "₹62.0L"


def test_format_inr_short_crore():
    assert format_inr_short(30300000000) == "₹30.3Cr"


def test_format_inr_short_thousand():
    assert format_inr_short(150000) == "₹1.5K"


def test_metrics_demo_fixture_displays_match_paise():
    totals = store.metrics_demo.totals
    assert format_inr_short(totals.exposure_identified_paise) == totals.exposure_identified_display
    assert format_inr_short(totals.exposure_mitigated_paise) == totals.exposure_mitigated_display


def test_vendor_fixture_dues_displays_match_paise():
    for v in store.vendors.values():
        assert format_inr(v.dues_paise) == v.dues_display


def test_disruption_fixture_exposure_displays_match_paise():
    for d in store.disruptions.values():
        assert format_inr(d.exposure.total_paise) == d.exposure.total_display
        for item in d.exposure.breakdown:
            assert format_inr(item.amount_paise) == item.amount_display


def test_settlement_batch_fixture_displays_match_paise():
    for b in store.settlement_batches.values():
        assert format_inr(b.total_paise) == b.total_display
        for line in b.lines:
            assert format_inr(line.amount_paise) == line.amount_display
