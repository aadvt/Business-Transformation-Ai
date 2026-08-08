"""Loads JSON fixtures into validated in-memory stores.

This is the entire "database" for the contract-and-mocks phase: a process-lifetime
dict of pydantic models, populated once at import time. Routers mutate these dicts
directly (e.g. on approval decisions) to keep responses consistent across calls
within a single server run. Nothing here is persisted across restarts.
"""

import json
from pathlib import Path
from typing import Any

from app.schemas.agents import AgentState
from app.schemas.audit import AuditEntry
from app.schemas.disruptions import Disruption
from app.schemas.forecast import Forecast
from app.schemas.metrics import MetricsDemo
from app.schemas.settlement import SettlementBatch
from app.schemas.vendors import Vendor

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_json(name: str) -> Any:
    with open(FIXTURES_DIR / name, encoding="utf-8") as f:
        return json.load(f)


class Store:
    def __init__(self) -> None:
        self.vendors: dict[str, Vendor] = {
            v["id"]: Vendor.model_validate(v) for v in _load_json("vendors.json")
        }
        self.disruptions: dict[str, Disruption] = {
            d["id"]: Disruption.model_validate(d) for d in _load_json("disruptions.json")
        }
        self.agents: dict[str, AgentState] = {
            a["name"]: AgentState.model_validate(a) for a in _load_json("agents.json")
        }
        self.vendor_context_raw: dict[str, dict] = _load_json("vendor_context.json")
        self.forecasts: dict[str, Forecast] = {
            sku: Forecast.model_validate(f) for sku, f in _load_json("forecasts.json").items()
        }
        self.settlement_batches: dict[str, SettlementBatch] = {
            b["id"]: SettlementBatch.model_validate(b)
            for b in _load_json("settlement_batches.json")
        }
        self.audit: dict[str, list[AuditEntry]] = {
            disruption_id: [AuditEntry.model_validate(e) for e in entries]
            for disruption_id, entries in _load_json("audit.json").items()
        }
        self.metrics_demo: MetricsDemo = MetricsDemo.model_validate(_load_json("metrics_demo.json"))
        # idempotency caches: idempotency_key -> stored response payload (dict)
        self.approval_idempotency: dict[str, dict] = {}
        self.settlement_execute_idempotency: dict[str, dict] = {}
        self.settlement_confirm_idempotency: dict[str, dict] = {}
        self.negotiation_outcome_idempotency: dict[str, dict] = {}


store = Store()
