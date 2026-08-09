"""Is IBM's TTM (Granite TinyTimeMixer) really wired up? — loads the model,
runs a zero-shot forecast on one seeded SKU, prints the crossing point and
inference latency.

    python scripts/smoke_ttm.py [SKU]

Defaults to CRS-2MM (the seeded stockout-risk golden path). Exits non-zero if
the model can't be loaded or there isn't enough history — this doubles as a
"is IBM really wired up" check for a demo dry-run.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.detectors import ttm_forecast  # noqa: E402
from app.constants import DEFAULT_ORG_ID  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402


def _format_horizon(hours: float) -> str:
    if hours < 24:
        return f"{hours:.0f} hours"
    return f"{hours / 24:.1f} days"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    sku = sys.argv[1] if len(sys.argv) > 1 else "CRS-2MM"

    print("Loading ibm-granite/granite-timeseries-ttm-r2 ...")
    ttm_forecast.load_model()

    if not ttm_forecast.is_available():
        print("\nTTM model FAILED to load — detector will stay disabled.")
        print("Check: is granite-tsfm installed? Are weights cached (or is there network access)?")
        return 1

    with SessionLocal() as session:
        history = ttm_forecast.fetch_history(session, DEFAULT_ORG_ID, sku)

        if len(history) < 512:
            print(f"\nsku: {sku} | only {len(history)} inventory_snapshots points found, need >= 512.")
            print("Run `python -m app.seed --reset` to populate the seeded SKUs.")
            return 1

        result = ttm_forecast.run_forecast(sku, history)

    if result is None:
        print(f"\nsku: {sku} | forecast could not be computed.")
        return 1

    if result.projected_breach_at is not None:
        hours_out = (result.projected_breach_at - result.history[-1].at).total_seconds() / 3600
        crossing = f"forecast crosses reorder point in {_format_horizon(hours_out)}"
    else:
        crossing = "forecast does not cross reorder point within the horizon"

    print(
        f"\nsku: {sku} | model: {result.model_id.split('/')[-1]} | {crossing} | {result.latency_ms:.0f}ms"
    )
    print(f"  reorder_point       : {result.reorder_point}")
    print(f"  current on-hand     : {result.history[-1].value}")
    print(f"  forecast horizon    : {len(result.forecast)} steps")
    print(f"  forecast min/max    : {min(p.value for p in result.forecast):.1f} / {max(p.value for p in result.forecast):.1f}")
    if result.projected_breach_at:
        print(f"  projected_breach_at : {result.projected_breach_at.isoformat()}")

    print("\nTTM is LIVE.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
