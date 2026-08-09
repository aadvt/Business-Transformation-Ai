"""The model layer. Every agent goes through this — no agent calls an HTTP model
endpoint directly.

Two implementations behind one interface:
  - `WatsonxLLM` — real watsonx.ai calls (transport isolated in transport.py)
  - `StubLLM`    — canned, schema-valid responses keyed by tag, no network

Shared behaviour (schema injection, fence stripping, the repair round-trip,
agent_runs recording) lives on the `LLMClient` base class so the two
implementations can't drift apart. Subclasses implement one primitive:
`_generate()`.

Degradation: if watsonx fails after its retries, `WatsonxLLM` logs loudly,
records the failure to agent_runs, and hands the call to an internal StubLLM.
The demo never dies because a network call timed out. The returned
`LLMResult.provider` is `"STUB"` in that case, so a caller (and the audit trail)
can always tell what actually answered.
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from app.config import settings
from app.llm import stub_responses
from app.llm.runs import AgentRunRecorder, NullAgentRunRecorder, default_recorder, truncate
from app.llm.transport import LLMTransportError, RawGeneration, get_transport
from app.schemas.money import utc_now

logger = logging.getLogger("sanjeevani.llm")

DEFAULT_MAX_TOKENS = 800
DEFAULT_TEMPERATURE = 0.0

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)


class LLMSchemaError(RuntimeError):
    """The model could not produce output matching the requested schema, even
    after one repair attempt. Callers decide the fallback — this is never
    swallowed silently, because a malformed model string must never reach the
    database."""


@dataclass
class LLMResult:
    text: str
    parsed: BaseModel | None
    model_id: str
    latency_ms: float
    token_usage: dict[str, int]
    provider: str  # "WATSONX" | "STUB"
    raw: dict[str, Any] = field(default_factory=dict)
    degraded: bool = False


def _strip_fences(text: str) -> str:
    """Models like wrapping JSON in ```json fences even when told not to."""
    match = _FENCE_RE.match(text or "")
    if match:
        return match.group(1).strip()
    return (text or "").strip()


def _extract_json_object(text: str) -> str:
    """Salvage the outermost {...} when the model prefixes prose ("Here is the
    JSON you asked for: {...}"). Cheaper and more reliable than a repair call."""
    cleaned = _strip_fences(text)
    if cleaned.startswith("{") and cleaned.endswith("}"):
        return cleaned
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        return cleaned[start : end + 1]
    return cleaned


def _schema_instructions(schema: type[BaseModel]) -> str:
    return (
        "\n\nYou must reply with a single JSON object and nothing else. "
        "No prose before or after it, no markdown code fences, no explanation.\n"
        "The object must validate against this JSON Schema:\n"
        f"{json.dumps(schema.model_json_schema(), indent=2)}"
    )


class LLMClient:
    """Base class holding everything that must behave identically across providers."""

    provider: str = "UNSET"

    def __init__(self, recorder: AgentRunRecorder | None = None) -> None:
        self._recorder = recorder if recorder is not None else default_recorder()

    # --- subclass contract ---------------------------------------------------

    def _generate(
        self, system: str, user: str, max_tokens: int, temperature: float, tag: str
    ) -> RawGeneration:
        raise NotImplementedError

    # --- public API ----------------------------------------------------------

    def complete(
        self,
        system: str,
        user: str,
        *,
        schema: type[BaseModel] | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
        tag: str = "UNTAGGED",
        disruption_id: str | None = None,
    ) -> LLMResult:
        system_prompt = system + _schema_instructions(schema) if schema else system

        started_at = utc_now()
        start = time.monotonic()
        try:
            generation = self._generate(system_prompt, user, max_tokens, temperature, tag)
        except LLMTransportError as exc:
            latency_ms = (time.monotonic() - start) * 1000
            return self._on_transport_failure(
                exc, system=system, user=user, schema=schema, max_tokens=max_tokens,
                temperature=temperature, tag=tag, disruption_id=disruption_id,
                started_at=started_at, latency_ms=latency_ms,
            )

        parsed: BaseModel | None = None
        schema_error: str | None = None
        if schema is not None:
            try:
                parsed = self._parse(generation.text, schema)
            except LLMSchemaError as first_error:
                # One repair round-trip, feeding the parse error back to the model.
                logger.warning(
                    "llm_schema_repair_attempt",
                    extra={"tag": tag, "provider": self.provider, "error": str(first_error)},
                )
                try:
                    generation = self._repair(
                        system_prompt, user, generation.text, str(first_error), max_tokens, temperature, tag
                    )
                    parsed = self._parse(generation.text, schema)
                except LLMTransportError as exc:
                    latency_ms = (time.monotonic() - start) * 1000
                    return self._on_transport_failure(
                        exc, system=system, user=user, schema=schema, max_tokens=max_tokens,
                        temperature=temperature, tag=tag, disruption_id=disruption_id,
                        started_at=started_at, latency_ms=latency_ms,
                    )
                except LLMSchemaError as second_error:
                    schema_error = str(second_error)

        latency_ms = (time.monotonic() - start) * 1000

        self._recorder.record(
            agent=tag,
            status="ERROR" if schema_error else "DONE",
            started_at=started_at,
            ended_at=utc_now(),
            latency_ms=latency_ms,
            model_id=generation.model_id,
            input_summary=truncate(user),
            output_summary=truncate(generation.text),
            error=schema_error,
            token_usage=generation.token_usage,
            disruption_id=disruption_id,
        )

        if schema_error:
            logger.error(
                "llm_schema_failed",
                extra={"tag": tag, "provider": self.provider, "model_id": generation.model_id, "error": schema_error},
            )
            raise LLMSchemaError(schema_error)

        logger.info(
            "llm_call",
            extra={
                "tag": tag,
                "provider": self.provider,
                "model_id": generation.model_id,
                "latency_ms": round(latency_ms, 1),
                "tokens": generation.token_usage.get("total_tokens", 0),
            },
        )

        return LLMResult(
            text=generation.text,
            parsed=parsed,
            model_id=generation.model_id,
            latency_ms=latency_ms,
            token_usage=generation.token_usage,
            provider=self.provider,
            raw=generation.raw,
        )

    # --- internals -----------------------------------------------------------

    def _parse(self, text: str, schema: type[BaseModel]) -> BaseModel:
        candidate = _extract_json_object(text)
        if not candidate:
            raise LLMSchemaError("Model returned an empty response")
        try:
            return schema.model_validate_json(candidate)
        except ValidationError as exc:
            raise LLMSchemaError(f"Response did not match schema: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise LLMSchemaError(f"Response was not valid JSON: {exc}") from exc

    def _repair(
        self, system_prompt: str, user: str, bad_output: str, error: str,
        max_tokens: int, temperature: float, tag: str,
    ) -> RawGeneration:
        repair_user = (
            f"{user}\n\n"
            "---\n"
            "Your previous reply could not be used. It was:\n"
            f"{bad_output[:2000]}\n\n"
            f"The error was: {error}\n\n"
            "Reply again with ONLY the corrected JSON object. No prose, no code fences."
        )
        return self._generate(system_prompt, repair_user, max_tokens, temperature, tag)

    def _on_transport_failure(self, exc: Exception, **kwargs) -> LLMResult:
        """Base behaviour: no fallback available, so re-raise. WatsonxLLM overrides
        this to degrade to StubLLM."""
        raise exc


class StubLLM(LLMClient):
    """Canned, schema-valid responses keyed by tag. Never touches the network."""

    provider = "STUB"
    model_id = "stub/canned-v1"

    def _generate(
        self, system: str, user: str, max_tokens: int, temperature: float, tag: str
    ) -> RawGeneration:
        return RawGeneration(
            text=stub_responses.response_for(tag),
            model_id=self.model_id,
            token_usage={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            raw={"stub": True, "tag": tag},
        )


class WatsonxLLM(LLMClient):
    """Real watsonx.ai calls, degrading to StubLLM on transport failure."""

    provider = "WATSONX"

    def __init__(self, recorder: AgentRunRecorder | None = None) -> None:
        super().__init__(recorder)
        self._fallback = StubLLM(recorder=self._recorder)

    def _generate(
        self, system: str, user: str, max_tokens: int, temperature: float, tag: str
    ) -> RawGeneration:
        return get_transport().chat(system, user, max_tokens=max_tokens, temperature=temperature)

    def _on_transport_failure(
        self, exc: Exception, *, system: str, user: str, schema: type[BaseModel] | None,
        max_tokens: int, temperature: float, tag: str, disruption_id: str | None,
        started_at, latency_ms: float,
    ) -> LLMResult:
        logger.error(
            "watsonx_call_failed_degrading_to_stub",
            extra={
                "tag": tag,
                "model_id": settings.watsonx_model_id,
                "latency_ms": round(latency_ms, 1),
                "error": str(exc),
            },
        )
        self._recorder.record(
            agent=tag,
            status="ERROR",
            started_at=started_at,
            ended_at=utc_now(),
            latency_ms=latency_ms,
            model_id=settings.watsonx_model_id,
            input_summary=truncate(user),
            output_summary="",
            error=f"watsonx unavailable, degraded to stub: {exc}",
            token_usage=None,
            disruption_id=disruption_id,
        )

        result = self._fallback.complete(
            system, user, schema=schema, max_tokens=max_tokens, temperature=temperature,
            tag=tag, disruption_id=disruption_id,
        )
        result.degraded = True
        return result


def get_llm(recorder: AgentRunRecorder | None = None) -> LLMClient:
    """Provider selection. `LLM_PROVIDER=stub` or missing credentials -> StubLLM."""
    provider = (settings.llm_provider or "auto").strip().lower()

    if provider == "stub":
        return StubLLM(recorder=recorder)
    if provider == "watsonx" or (provider == "auto" and settings.watsonx_configured):
        if not settings.watsonx_configured:
            logger.warning("llm_provider_watsonx_requested_but_unconfigured_using_stub")
            return StubLLM(recorder=recorder)
        return WatsonxLLM(recorder=recorder)

    logger.info("llm_provider_stub_selected", extra={"reason": "no watsonx credentials configured"})
    return StubLLM(recorder=recorder)


__all__ = [
    "LLMClient",
    "LLMResult",
    "LLMSchemaError",
    "NullAgentRunRecorder",
    "StubLLM",
    "WatsonxLLM",
    "get_llm",
]
