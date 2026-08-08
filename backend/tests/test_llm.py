"""Model-layer tests. StubLLM only — this file must never touch the network.

Anything that would reach watsonx is exercised through a fake transport, so the
suite runs offline, in CI, and on venue wifi.
"""

import json

import pytest
from pydantic import BaseModel, Field

from app.llm import prompts
from app.llm.client import (
    DEFAULT_MAX_TOKENS,
    LLMClient,
    LLMResult,
    LLMSchemaError,
    StubLLM,
    WatsonxLLM,
    _extract_json_object,
    _strip_fences,
)
from app.llm.guardian import GuardianClient, GuardianMode, GuardianRisk
from app.llm.runs import NullAgentRunRecorder, truncate
from app.llm.transport import LLMTransportError, RawGeneration


class Answer(BaseModel):
    answer: str
    confidence: float = Field(ge=0.0, le=1.0)


@pytest.fixture()
def stub() -> StubLLM:
    return StubLLM(recorder=NullAgentRunRecorder())


# --- StubLLM basics ----------------------------------------------------------


def test_stub_returns_llmresult(stub):
    result = stub.complete("system", "user", tag=prompts.TAG_SMOKE_TEST)
    assert isinstance(result, LLMResult)
    assert result.provider == "STUB"
    assert result.model_id == "stub/canned-v1"
    assert result.latency_ms >= 0
    assert result.text


def test_stub_parses_into_schema(stub):
    result = stub.complete("system", "user", schema=Answer, tag=prompts.TAG_SMOKE_TEST)
    assert isinstance(result.parsed, Answer)
    assert result.parsed.answer
    assert 0.0 <= result.parsed.confidence <= 1.0


def test_stub_response_varies_by_tag(stub):
    smoke = stub.complete("s", "u", tag=prompts.TAG_SMOKE_TEST).text
    diagnosis = stub.complete("s", "u", tag=prompts.TAG_DIAGNOSIS_NARRATIVE).text
    assert smoke != diagnosis


def test_stub_unknown_tag_falls_back_to_default(stub):
    result = stub.complete("s", "u", tag="NO_SUCH_TAG")
    assert result.text
    assert "recorded and routed for review" in result.text


def test_every_registered_tag_has_a_parseable_stub_response(stub):
    """Guards the promise that StubLLM responses are schema-valid: every canned
    response must at least be valid JSON where the tag implies structure."""
    from app.llm.stub_responses import STUB_RESPONSES

    for tag, response in STUB_RESPONSES.items():
        json.loads(response), f"stub response for {tag} is not valid JSON"


def test_stub_never_writes_agent_runs_with_null_recorder(stub):
    # NullAgentRunRecorder is a no-op; this just asserts no exception path.
    stub.complete("s", "u", tag=prompts.TAG_SMOKE_TEST)


# --- fence stripping / JSON salvage -----------------------------------------


def test_strip_fences_plain_json():
    assert _strip_fences('{"a": 1}') == '{"a": 1}'


def test_strip_fences_json_fence():
    assert _strip_fences('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_strip_fences_bare_fence():
    assert _strip_fences('```\n{"a": 1}\n```') == '{"a": 1}'


def test_extract_json_object_ignores_surrounding_prose():
    text = 'Sure! Here is the JSON you asked for:\n{"a": 1}\nHope that helps.'
    assert _extract_json_object(text) == '{"a": 1}'


def test_extract_json_object_handles_fenced_prose_combo():
    text = '```json\n{"answer": "x", "confidence": 0.5}\n```'
    assert json.loads(_extract_json_object(text))["answer"] == "x"


# --- schema failure + repair round-trip --------------------------------------


class _ScriptedLLM(LLMClient):
    """Returns a scripted sequence of raw texts, so we can drive the repair path
    deterministically without any network."""

    provider = "STUB"

    def __init__(self, texts: list[str]) -> None:
        super().__init__(recorder=NullAgentRunRecorder())
        self.texts = list(texts)
        self.calls = 0

    def _generate(self, system, user, max_tokens, temperature, tag) -> RawGeneration:
        self.calls += 1
        text = self.texts.pop(0) if self.texts else ""
        return RawGeneration(text=text, model_id="scripted", token_usage={}, raw={})


def test_repair_round_trip_recovers_from_bad_first_response():
    llm = _ScriptedLLM(["not json at all", '{"answer": "recovered", "confidence": 0.4}'])
    result = llm.complete("s", "u", schema=Answer, tag="T")
    assert llm.calls == 2, "should have made exactly one repair attempt"
    assert result.parsed.answer == "recovered"


def test_repair_is_attempted_only_once_then_raises():
    llm = _ScriptedLLM(["garbage", "still garbage"])
    with pytest.raises(LLMSchemaError):
        llm.complete("s", "u", schema=Answer, tag="T")
    assert llm.calls == 2, "must not retry the repair indefinitely"


def test_schema_error_on_valid_json_wrong_shape():
    llm = _ScriptedLLM(['{"unrelated": true}', '{"still": "wrong"}'])
    with pytest.raises(LLMSchemaError):
        llm.complete("s", "u", schema=Answer, tag="T")


def test_no_schema_means_no_parse_and_no_repair():
    llm = _ScriptedLLM(["free-form prose, definitely not json"])
    result = llm.complete("s", "u", tag="T")
    assert result.parsed is None
    assert llm.calls == 1


def test_schema_instructions_are_appended_to_system_prompt():
    captured = {}

    class _Capture(_ScriptedLLM):
        def _generate(self, system, user, max_tokens, temperature, tag):
            captured["system"] = system
            return super()._generate(system, user, max_tokens, temperature, tag)

    llm = _Capture(['{"answer": "a", "confidence": 0.1}'])
    llm.complete("BASE PROMPT", "u", schema=Answer, tag="T")
    assert "BASE PROMPT" in captured["system"]
    assert "JSON Schema" in captured["system"]
    assert "confidence" in captured["system"], "the model's schema must reach the prompt"


# --- degradation --------------------------------------------------------------


class _AlwaysFailingWatsonx(WatsonxLLM):
    def _generate(self, system, user, max_tokens, temperature, tag) -> RawGeneration:
        raise LLMTransportError("simulated outage")


def test_watsonx_degrades_to_stub_instead_of_raising():
    llm = _AlwaysFailingWatsonx(recorder=NullAgentRunRecorder())
    result = llm.complete("s", "u", schema=Answer, tag=prompts.TAG_SMOKE_TEST)
    assert result.provider == "STUB", "degraded result must report the stub as the provider"
    assert result.degraded is True
    assert isinstance(result.parsed, Answer), "degraded result still satisfies the schema"


def test_degraded_flag_is_false_on_normal_stub_call(stub):
    result = stub.complete("s", "u", tag=prompts.TAG_SMOKE_TEST)
    assert result.degraded is False


# --- Guardian (no network) ---------------------------------------------------


def test_guardian_unavailable_when_disabled(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "guardian_enabled", False)
    verdict = GuardianClient(recorder=NullAgentRunRecorder()).check(
        "some text", risk=GuardianRisk.GROUNDEDNESS, context="ctx"
    )
    assert verdict.status == "UNAVAILABLE"
    assert verdict.mode == GuardianMode.NONE


def test_unavailable_verdict_passes_but_demands_human_review(monkeypatch):
    """The critical safety property: passed=True on UNAVAILABLE is NOT approval."""
    from app.config import settings

    monkeypatch.setattr(settings, "guardian_enabled", False)
    verdict = GuardianClient(recorder=NullAgentRunRecorder()).check(
        "text", risk=GuardianRisk.GROUNDEDNESS, context=None
    )
    assert verdict.passed is True
    assert verdict.needs_human_review is True
    assert verdict.is_real_guardian is False


def test_guardian_risk_enum_covers_the_three_pipeline_risks():
    assert {r.value for r in GuardianRisk} == {
        "GROUNDEDNESS",
        "FUNCTION_CALL_HALLUCINATION",
        "HARM",
    }


def test_every_risk_has_a_definition():
    from app.llm.guardian import _RISK_DEFINITIONS

    for risk in GuardianRisk:
        assert _RISK_DEFINITIONS[risk].strip()


# --- observability helpers ---------------------------------------------------


def test_truncate_caps_at_limit():
    assert len(truncate("x" * 900)) <= 500


def test_truncate_collapses_whitespace():
    assert truncate("a  \n  b") == "a b"


def test_truncate_handles_none():
    assert truncate(None) == ""


def test_correlation_id_is_set_and_readable():
    from app.observability import get_correlation_id, set_correlation_id

    cid = set_correlation_id("test-cid-123")
    assert cid == "test-cid-123"
    assert get_correlation_id() == "test-cid-123"


def test_json_formatter_emits_single_line_json():
    import logging

    from app.observability import JsonFormatter

    record = logging.LogRecord("n", logging.INFO, "p", 1, "hello", None, None)
    record.custom_field = "kept"
    line = JsonFormatter().format(record)
    payload = json.loads(line)
    assert "\n" not in line
    assert payload["message"] == "hello"
    assert payload["custom_field"] == "kept"
    assert "correlation_id" in payload


# --- prompt registry ---------------------------------------------------------


def test_prompt_tags_fit_the_agent_runs_column():
    tags = [v for k, v in vars(prompts).items() if k.startswith("TAG_")]
    assert tags
    for tag in tags:
        assert len(tag) <= 30, f"{tag} exceeds agent_runs.agent column width"


def test_prompts_are_non_empty_and_versioned():
    versioned = {k: v for k, v in vars(prompts).items() if k.endswith("_V1") and isinstance(v, str)}
    assert versioned
    for name, text in versioned.items():
        assert text.strip(), f"{name} is empty"


def test_default_max_tokens_is_sane():
    assert 100 <= DEFAULT_MAX_TOKENS <= 4000
