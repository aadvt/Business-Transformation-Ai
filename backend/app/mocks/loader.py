"""Loads the two things still fixture-backed after the move to real Neon
persistence: /forecast/{sku} (no forecast/projection data exists in the DB —
building real TTM forecasting is a separate task) and the guardrails/
briefing/history_summary portion of /vendors/{id}/context (needs either
real LLM-generated narrative or actual business-policy config, neither of
which exists as stored data yet — see app/routers/vendors.py).

Everything else that used to live here (vendors, disruptions, agents,
settlement_batches, audit, and the four idempotency dicts) now comes from
Postgres — see app/db.py, app/db_models.py, app/idempotency.py, and the
routers themselves.
"""

import json
from pathlib import Path
from typing import Any

from app.schemas.forecast import Forecast

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_json(name: str) -> Any:
    with open(FIXTURES_DIR / name, encoding="utf-8") as f:
        return json.load(f)


class Store:
    def __init__(self) -> None:
        self.forecasts: dict[str, Forecast] = {
            sku: Forecast.model_validate(f) for sku, f in _load_json("forecasts.json").items()
        }
        self.vendor_context_raw: dict[str, dict] = _load_json("vendor_context.json")


store = Store()
