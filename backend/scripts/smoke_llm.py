"""Is IBM wired up? — calls Granite with a trivial structured prompt.

    python scripts/smoke_llm.py

Prints the model id, provider, latency and the parsed output. Exits non-zero if
the call degraded to the stub, so this doubles as a CI-style check that real
credentials still work.
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import BaseModel, Field  # noqa: E402

from app.config import settings  # noqa: E402
from app.llm import prompts  # noqa: E402
from app.llm.client import get_llm  # noqa: E402
from app.llm.runs import NullAgentRunRecorder  # noqa: E402
from app.observability import configure_logging, set_correlation_id  # noqa: E402


class SmokeAnswer(BaseModel):
    answer: str = Field(description="A single short factual sentence.")
    confidence: float = Field(ge=0.0, le=1.0, description="How confident you are, 0 to 1.")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    configure_logging(logging.WARNING)  # keep stdout clean; we print our own summary
    set_correlation_id()

    # Smoke scripts must not write agent_runs rows into the demo database.
    llm = get_llm(recorder=NullAgentRunRecorder())

    print(f"configured provider : {settings.llm_provider}")
    print(f"watsonx configured  : {settings.watsonx_configured}")
    print(f"endpoint            : {settings.watsonx_url}")
    print(f"requested model     : {settings.watsonx_model_id}")
    print("-" * 60)

    result = llm.complete(
        prompts.SMOKE_TEST_V1,
        "Which Indian state is Pune located in, and what is it known for industrially?",
        schema=SmokeAnswer,
        max_tokens=200,
        tag=prompts.TAG_SMOKE_TEST,
    )

    parsed_ok = result.parsed is not None
    print(f"# model: {result.model_id} | provider: {result.provider} | {result.latency_ms:.0f}ms | "
          f"parsed {'OK' if parsed_ok else 'FAILED'}")
    print(f"tokens              : {result.token_usage}")
    print(f"answer              : {result.parsed.answer if parsed_ok else '(none)'}")
    print(f"confidence          : {result.parsed.confidence if parsed_ok else '(none)'}")

    if result.degraded:
        print("\nDEGRADED: watsonx call failed and the stub answered instead.")
        print("Check WATSONX_API_KEY / WATSONX_PROJECT_ID / WATSONX_URL in .env, then re-run.")
        return 1

    if result.provider == "STUB":
        print("\nStub provider in use — no live IBM call was made.")
        print("Set LLM_PROVIDER=auto and populate the watsonx credentials in .env to go live.")
        return 1

    print("\nwatsonx.ai is LIVE.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
