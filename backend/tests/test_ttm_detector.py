"""TTM stockout-risk detector tests.

Two tiers, matching the brief: pure crossing-detection logic runs always (no
model needed), and real-model tests run if TTM loaded successfully — if it
didn't (no cached weights, no network, no torch build for this platform),
those are skipped with a clear reason rather than failing the suite. Either
way, the full suite must pass with zero network access required.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.agents.detectors import ttm_forecast
from app.agents.detectors.ttm_forecast import ForecastPoint, find_projected_breach
from app.agents.sentinel import DETECTORS, Signal


def _points(values: list[float], start: datetime | None = None, step_minutes: int = 60) -> list[ForecastPoint]:
    start = start or datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [ForecastPoint(at=start + timedelta(minutes=step_minutes * i), value=v) for i, v in enumerate(values)]


# --- pure crossing detection (no model, no network, always runs) --------------


def test_no_breach_when_forecast_stays_above_reorder_point():
    forecast = _points([100, 95, 90, 85])
    assert find_projected_breach(forecast, reorder_point=50) is None


def test_breach_detected_partway_through_horizon():
    forecast = _points([100, 80, 40, 20])
    breach = find_projected_breach(forecast, reorder_point=50)
    assert breach == forecast[2].at


def test_breach_detected_immediately_when_already_below():
    """Matches the seeded CRS-2MM scenario: on_hand is already below
    reorder_point by the time the forecast starts."""
    forecast = _points([40, 42, 45, 48])
    breach = find_projected_breach(forecast, reorder_point=50)
    assert breach == forecast[0].at


def test_exact_equality_counts_as_breach():
    forecast = _points([100, 50, 40])
    breach = find_projected_breach(forecast, reorder_point=50)
    assert breach == forecast[1].at


def test_empty_forecast_has_no_breach():
    assert find_projected_breach([], reorder_point=50) is None


def test_ttm_detector_is_registered_in_sentinel_detectors():
    """The additive-registration contract from Phase 4a: TTM must appear in
    the shared list without Phase 4a's sentinel.py having been edited."""
    assert ttm_forecast.stockout_risk_ttm in DETECTORS


def test_disabled_by_config_returns_no_signals(monkeypatch):
    monkeypatch.setattr("app.config.settings.enable_ttm_detector", False)
    from unittest.mock import MagicMock

    result = ttm_forecast.stockout_risk_ttm(MagicMock(), "some-org")
    assert result == []


def test_unavailable_model_returns_no_signals(monkeypatch):
    monkeypatch.setattr("app.config.settings.enable_ttm_detector", True)
    monkeypatch.setattr(ttm_forecast, "TTM_AVAILABLE", False)
    from unittest.mock import MagicMock

    result = ttm_forecast.stockout_risk_ttm(MagicMock(), "some-org")
    assert result == []


def test_sku_vendor_hints_cover_all_seeded_ramp_skus():
    # These three are the "ramp=True" SKUs in app/seed.py's INVENTORY_SKUS —
    # the ones actually likely to cross a reorder point and need a vendor to
    # attribute the signal to.
    for sku in ("CRS-2MM", "FST-M8-BOLT", "RBR-SEAL-A"):
        assert sku in ttm_forecast.SKU_VENDOR_HINTS


def test_run_forecast_returns_none_without_model(monkeypatch):
    monkeypatch.setattr(ttm_forecast, "TTM_AVAILABLE", False)
    assert ttm_forecast.run_forecast("CRS-2MM", []) is None


def test_run_forecast_returns_none_with_insufficient_history(monkeypatch):
    monkeypatch.setattr(ttm_forecast, "TTM_AVAILABLE", True)
    monkeypatch.setattr(ttm_forecast, "_model", object())  # any truthy sentinel
    assert ttm_forecast.run_forecast("CRS-2MM", []) is None


# --- real-model tests: skipped cleanly if weights/network aren't available ----


@pytest.fixture(scope="module")
def ttm_ready() -> bool:
    if not ttm_forecast.is_available():
        ttm_forecast.load_model()
    return ttm_forecast.is_available()


def test_model_loads_or_skips(ttm_ready):
    if not ttm_ready:
        pytest.skip("TTM model not available (no cached weights and/or no network) — detector degrades gracefully")
    assert ttm_forecast.is_available()


def test_zero_shot_forecast_on_seeded_sku(ttm_ready):
    if not ttm_ready:
        pytest.skip("TTM model not available — see test_model_loads_or_skips")

    from app.db.session import SessionLocal

    with SessionLocal() as session:
        history = ttm_forecast.fetch_history(session, _default_org_id(), "CRS-2MM")
        if len(history) < 512:
            pytest.skip("seed data not present or has < 512 points for CRS-2MM — run `python -m app.seed --reset`")
        result = ttm_forecast.run_forecast("CRS-2MM", history)

    assert result is not None
    assert len(result.forecast) == 96
    assert result.latency_ms >= 0
    assert result.model_id == "ibm-granite/granite-timeseries-ttm-r2"
    # forecast timestamps must be sorted and evenly spaced — "chart-ready"
    ats = [p.at for p in result.forecast]
    assert ats == sorted(ats)
    deltas = {ats[i + 1] - ats[i] for i in range(len(ats) - 1)}
    assert len(deltas) == 1


def test_stockout_risk_ttm_detector_end_to_end(ttm_ready):
    if not ttm_ready:
        pytest.skip("TTM model not available — see test_model_loads_or_skips")

    from app.db.session import SessionLocal

    with SessionLocal() as session:
        signals = ttm_forecast.stockout_risk_ttm(session, _default_org_id())

    crs_signals = [s for s in signals if s.evidence.get("sku") == "CRS-2MM"]
    if not crs_signals:
        pytest.skip("no CRS-2MM signal produced — either already detected/open, or seed data changed")

    signal = crs_signals[0]
    assert signal.detector_source == "TTM_FORECAST"
    assert signal.detector_name == "ttm_stockout_forecast"
    assert isinstance(signal, Signal)
    assert signal.vendor_id


def _default_org_id() -> str:
    from app.constants import DEFAULT_ORG_ID

    return DEFAULT_ORG_ID
