"""Granite Guardian — risk scoring for model output.

Guardian is prompted differently from a general model: it is given a piece of
text, a named risk definition, and answers with a single Yes/No token. "Yes"
means the risk IS present, so `passed` is the inverse of the raw label.

Used at two points in the pipeline (deliberately generic, not tied to either):
  - Phase 4: diagnosis narrative groundedness against the gathered evidence
  - Phase 6: negotiation outcome groundedness / function-call hallucination

Availability semantics matter here. If Guardian is unreachable we return
`status=UNAVAILABLE` with `passed=True` and log it — but that is NOT an
approval. Callers that enforce (Phase 6's negotiation write-back) must treat
UNAVAILABLE as "flag for human review". `passed=True` on an UNAVAILABLE verdict
exists only so a non-enforcing caller doesn't block the pipeline; never read
`passed` without also reading `status`.

Two scoring modes, reported on every verdict as `mode`:
  - `GRANITE_GUARDIAN` — the real ibm/granite-guardian-* model, prompted with
    Guardian's own template and scored on its Yes/No token.
  - `LLM_SURROGATE`   — the same risk definitions judged by the general Granite
    chat model, used only when no Guardian model is available on the account's
    region/plan (which is the case for our current credentials: the eu-de
    foundation_model_specs list contains no granite-guardian-* entry). This
    keeps the safety gate functional and discriminating, but it is NOT Granite
    Guardian and must never be reported as such — hence the explicit mode field
    on every verdict and in every agent_runs row.

The mode is resolved lazily on first use and cached, so a missing Guardian model
costs one 404, not one per call.
"""

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.config import settings
from app.llm import prompts
from app.llm.runs import AgentRunRecorder, default_recorder, truncate
from app.llm.transport import LLMTransportError, get_transport
from app.schemas.money import utc_now

logger = logging.getLogger("sanjeevani.llm.guardian")


class GuardianRisk(StrEnum):
    GROUNDEDNESS = "GROUNDEDNESS"
    FUNCTION_CALL_HALLUCINATION = "FUNCTION_CALL_HALLUCINATION"
    HARM = "HARM"


class GuardianMode(StrEnum):
    GRANITE_GUARDIAN = "GRANITE_GUARDIAN"
    LLM_SURROGATE = "LLM_SURROGATE"
    NONE = "NONE"


_RISK_DEFINITIONS = {
    GuardianRisk.GROUNDEDNESS: prompts.GUARDIAN_RISK_DEFINITION_GROUNDEDNESS,
    GuardianRisk.FUNCTION_CALL_HALLUCINATION: prompts.GUARDIAN_RISK_DEFINITION_FUNCTION_CALL_HALLUCINATION,
    GuardianRisk.HARM: prompts.GUARDIAN_RISK_DEFINITION_HARM,
}

_YES_RE = re.compile(r"\byes\b", re.IGNORECASE)
_NO_RE = re.compile(r"\bno\b", re.IGNORECASE)


def _is_model_unavailable(exc: Exception) -> bool:
    """Distinguishes 'this account has no Guardian model' (fall back to the
    surrogate) from a transient outage (stay unavailable, don't silently
    downgrade the safety layer on a blip)."""
    message = str(exc)
    return "model_not_supported" in message or "was not found" in message


@dataclass
class GuardianVerdict:
    passed: bool
    risk: GuardianRisk
    raw_label: str
    confidence: float | None
    model_id: str
    latency_ms: float
    status: str  # "OK" | "UNAVAILABLE"
    mode: GuardianMode = GuardianMode.NONE
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def needs_human_review(self) -> bool:
        """True when a verdict must not be treated as an automated approval:
        either Guardian flagged the risk, or Guardian could not be reached."""
        return self.status != "OK" or not self.passed

    @property
    def is_real_guardian(self) -> bool:
        """False when the verdict came from the surrogate judge. Anything that
        reports Guardian provenance to a user or judge must check this."""
        return self.mode == GuardianMode.GRANITE_GUARDIAN


def _confidence_from_top_tokens(raw: dict[str, Any]) -> float | None:
    """Guardian's answer is one token, so the Yes/No probability at position 0 is
    a usable confidence. Absent if the endpoint didn't return top_tokens."""
    try:
        tokens = raw["results"][0].get("generated_tokens") or []
        if not tokens:
            return None
        top = tokens[0].get("top_tokens") or []
        for candidate in top:
            text = (candidate.get("text") or "").strip().lower()
            if text in ("yes", "no"):
                logprob = candidate.get("logprob")
                if logprob is None:
                    return None
                import math

                return round(math.exp(logprob), 4)
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    return None


class _ModeCache:
    """Remembers whether a real Guardian model exists on this account, so an
    unavailable one costs a single 404 rather than one per call."""

    def __init__(self) -> None:
        self._mode: GuardianMode | None = None
        self._lock = threading.Lock()

    def get(self) -> GuardianMode | None:
        return self._mode

    def set(self, mode: GuardianMode) -> None:
        with self._lock:
            self._mode = mode

    def reset(self) -> None:
        with self._lock:
            self._mode = None


_mode_cache = _ModeCache()


class GuardianClient:
    def __init__(self, recorder: AgentRunRecorder | None = None) -> None:
        self._recorder = recorder if recorder is not None else default_recorder()

    def check(
        self,
        text: str,
        *,
        risk: GuardianRisk,
        context: str | None = None,
        disruption_id: str | None = None,
    ) -> GuardianVerdict:
        tag = f"GUARDIAN_{risk.value}"[:30]
        started_at = utc_now()
        start = time.monotonic()

        if not settings.guardian_enabled or not settings.watsonx_configured:
            reason = "guardian disabled" if not settings.guardian_enabled else "watsonx not configured"
            return self._unavailable(risk, reason, started_at, (time.monotonic() - start) * 1000, tag, text, disruption_id)

        try:
            generation, mode = self._score(text, risk, context)
        except LLMTransportError as exc:
            latency_ms = (time.monotonic() - start) * 1000
            logger.error(
                "guardian_unavailable",
                extra={"risk": risk.value, "error": str(exc), "latency_ms": round(latency_ms, 1)},
            )
            return self._unavailable(risk, str(exc), started_at, latency_ms, tag, text, disruption_id)

        latency_ms = (time.monotonic() - start) * 1000
        raw_label = (generation.text or "").strip()

        # "Yes" = risk present = did NOT pass.
        if _YES_RE.search(raw_label):
            passed = False
        elif _NO_RE.search(raw_label):
            passed = True
        else:
            # Unparseable verdict is not an approval — treat as unavailable.
            logger.error("guardian_unparseable_verdict", extra={"risk": risk.value, "raw_label": raw_label[:100]})
            return self._unavailable(
                risk, f"unparseable verdict: {raw_label[:100]!r}", started_at, latency_ms, tag, text, disruption_id
            )

        confidence = _confidence_from_top_tokens(generation.raw)

        self._recorder.record(
            agent=tag,
            status="DONE",
            started_at=started_at,
            ended_at=utc_now(),
            latency_ms=latency_ms,
            model_id=generation.model_id,
            input_summary=truncate(text),
            output_summary=f"{raw_label} (passed={passed}, mode={mode.value})",
            error=None,
            token_usage=generation.token_usage,
            disruption_id=disruption_id,
        )

        logger.info(
            "guardian_check",
            extra={
                "risk": risk.value,
                "passed": passed,
                "mode": mode.value,
                "raw_label": raw_label,
                "confidence": confidence,
                "model_id": generation.model_id,
                "latency_ms": round(latency_ms, 1),
            },
        )

        return GuardianVerdict(
            passed=passed,
            risk=risk,
            raw_label=raw_label,
            confidence=confidence,
            model_id=generation.model_id,
            latency_ms=latency_ms,
            status="OK",
            mode=mode,
        )

    # --- scoring paths -------------------------------------------------------

    def _score(self, text: str, risk: GuardianRisk, context: str | None):
        """Returns (RawGeneration, GuardianMode). Tries the real Guardian model
        first; on `model_not_supported` falls back to the surrogate judge and
        caches that decision."""
        risk_definition = _RISK_DEFINITIONS[risk]
        user_text = context or "(no context provided)"
        mode = _mode_cache.get()

        if mode in (None, GuardianMode.GRANITE_GUARDIAN):
            try:
                generation = get_transport().generate(
                    prompts.GUARDIAN_TEMPLATE_V1.format(
                        user_text=user_text, assistant_text=text, risk_definition=risk_definition
                    ),
                    model_id=settings.guardian_model_id,
                    max_tokens=8,
                    temperature=0.0,
                    top_n_tokens=5,
                )
                _mode_cache.set(GuardianMode.GRANITE_GUARDIAN)
                return generation, GuardianMode.GRANITE_GUARDIAN
            except LLMTransportError as exc:
                if not _is_model_unavailable(exc):
                    raise
                logger.warning(
                    "guardian_model_unavailable_using_surrogate",
                    extra={
                        "guardian_model_id": settings.guardian_model_id,
                        "surrogate_model_id": settings.watsonx_model_id,
                    },
                )
                _mode_cache.set(GuardianMode.LLM_SURROGATE)

        generation = get_transport().chat(
            prompts.GUARDIAN_SURROGATE_SYSTEM_V1,
            prompts.GUARDIAN_SURROGATE_USER_V1.format(
                risk_definition=risk_definition, user_text=user_text, assistant_text=text
            ),
            max_tokens=8,
            temperature=0.0,
        )
        return generation, GuardianMode.LLM_SURROGATE

    def _unavailable(
        self, risk: GuardianRisk, reason: str, started_at, latency_ms: float,
        tag: str, text: str, disruption_id: str | None,
    ) -> GuardianVerdict:
        logger.warning("guardian_verdict_unavailable", extra={"risk": risk.value, "reason": reason})
        self._recorder.record(
            agent=tag,
            status="ERROR",
            started_at=started_at,
            ended_at=utc_now(),
            latency_ms=latency_ms,
            model_id=settings.guardian_model_id,
            input_summary=truncate(text),
            output_summary="",
            error=f"guardian unavailable: {reason}",
            token_usage=None,
            disruption_id=disruption_id,
        )
        return GuardianVerdict(
            passed=True,  # see module docstring — NOT an approval, read `status`
            risk=risk,
            raw_label="",
            confidence=None,
            model_id=settings.guardian_model_id,
            latency_ms=latency_ms,
            status="UNAVAILABLE",
            mode=GuardianMode.NONE,
            detail={"reason": reason},
        )


def get_guardian(recorder: AgentRunRecorder | None = None) -> GuardianClient:
    return GuardianClient(recorder=recorder)


__all__ = ["GuardianClient", "GuardianMode", "GuardianRisk", "GuardianVerdict", "get_guardian"]
