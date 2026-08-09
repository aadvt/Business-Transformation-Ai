"""Guardian check — runs one clean and one deliberately ungrounded string.

    python scripts/smoke_guardian.py

The clean claim is fully supported by the context; the ungrounded one invents a
ticket number, a cause, and a rupee figure that appear nowhere in the context.
A working Guardian should PASS the first and FAIL the second.
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.llm.guardian import GuardianRisk, get_guardian  # noqa: E402
from app.llm.runs import NullAgentRunRecorder  # noqa: E402
from app.observability import configure_logging, set_correlation_id  # noqa: E402

CONTEXT = (
    "Purchase order PO-SCN-A-001 was placed with Bharat Casting Industries for 1200 mounting "
    "brackets. It was promised on 5 August 2026 and has not been delivered. The vendor's last "
    "three orders were each delivered two to three days late. No reply has been received to the "
    "dispatch follow-up message sent on WhatsApp."
)

GROUNDED_CLAIM = (
    "Bharat Casting Industries has missed the promised delivery date on PO-SCN-A-001, and their "
    "previous three orders were also delivered late, which points to an ongoing capacity problem."
)

UNGROUNDED_CLAIM = (
    "Bharat Casting Industries confirmed in support ticket CT-99412 that a fire at their Rajkot "
    "foundry destroyed the tooling, and they have agreed to pay a penalty of Rs 4,50,000 as "
    "compensation for the eight-week delay."
)


def _report(name: str, verdict) -> None:
    outcome = "PASS" if verdict.passed else "FAIL"
    if verdict.status != "OK":
        outcome = f"{outcome} (status={verdict.status})"
    print(f"groundedness: {outcome:<28} [{name}]")
    print(f"    raw_label     : {verdict.raw_label!r}")
    print(f"    confidence    : {verdict.confidence}")
    print(f"    mode          : {verdict.mode.value}")
    print(f"    model_id      : {verdict.model_id}")
    print(f"    latency_ms    : {verdict.latency_ms:.0f}")
    print(f"    needs_review  : {verdict.needs_human_review}")
    if verdict.detail:
        print(f"    detail        : {verdict.detail}")
    print()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    configure_logging(logging.WARNING)
    set_correlation_id()

    guardian = get_guardian(recorder=NullAgentRunRecorder())

    print(f"guardian enabled : {settings.guardian_enabled}")
    print(f"guardian model   : {settings.guardian_model_id}")
    print("-" * 60)

    clean = guardian.check(GROUNDED_CLAIM, risk=GuardianRisk.GROUNDEDNESS, context=CONTEXT)
    _report("clean", clean)

    dirty = guardian.check(UNGROUNDED_CLAIM, risk=GuardianRisk.GROUNDEDNESS, context=CONTEXT)
    _report("ungrounded", dirty)

    if clean.status != "OK" or dirty.status != "OK":
        print("Guardian was UNAVAILABLE — callers that enforce must flag for human review.")
        return 1

    if clean.passed and not dirty.passed:
        if clean.is_real_guardian:
            print("Granite Guardian is LIVE and discriminating correctly.")
        else:
            print(f"Guardian gate is LIVE and discriminating correctly, but in {clean.mode.value} mode:")
            print(f"  no granite-guardian-* model is available on this account/region, so risk scoring")
            print(f"  is done by {clean.model_id} against Guardian's risk definitions.")
            print("  Do NOT report this as Granite Guardian. See README integration table.")
        return 0

    print("Guardian responded but did not discriminate as expected "
          f"(clean passed={clean.passed}, ungrounded passed={dirty.passed}).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
