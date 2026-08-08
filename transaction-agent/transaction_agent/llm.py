"""ChatWatsonx (IBM Granite) setup and structured extraction of payment
instructions from free text.

Credentials come from the environment only:

    WATSONX_API_KEY
    WATSONX_PROJECT_ID
    WATSONX_URL

If any are missing this fails loudly with setup instructions rather than
silently falling back to another provider or to --offline mode.
"""

from __future__ import annotations

import json
import os
import re

from pydantic import ValidationError

from .models import ParsedTransactionList

DEFAULT_MODEL_ID = os.environ.get("WATSONX_MODEL_ID", "ibm/granite-4-h-small")

_REQUIRED_ENV_VARS = ("WATSONX_API_KEY", "WATSONX_PROJECT_ID", "WATSONX_URL")

_SETUP_INSTRUCTIONS = """\
Missing watsonx.ai credentials: {missing}

Set these environment variables before running with the LLM parser:

    export WATSONX_API_KEY="your-api-key"
    export WATSONX_PROJECT_ID="your-project-id"
    export WATSONX_URL="https://<region>.ml.cloud.ibm.com"

Get an API key and project id from https://cloud.ibm.com/iam/apikeys and
your watsonx.ai project settings. Run `python smoke_test.py` to verify auth.

Alternatively, run with --offline to use the regex parser and skip the LLM
entirely (no credentials needed).\
"""


class WatsonxConfigError(RuntimeError):
    pass


def check_env() -> None:
    missing = [name for name in _REQUIRED_ENV_VARS if not os.environ.get(name)]
    if missing:
        raise WatsonxConfigError(_SETUP_INSTRUCTIONS.format(missing=", ".join(missing)))


def get_llm(model_id: str = DEFAULT_MODEL_ID, temperature: float = 0.0):
    """Build a ChatWatsonx client. Raises WatsonxConfigError if credentials are missing."""
    check_env()
    from langchain_ibm import ChatWatsonx

    return ChatWatsonx(
        model_id=model_id,
        url=os.environ["WATSONX_URL"],
        project_id=os.environ["WATSONX_PROJECT_ID"],
        api_key=os.environ["WATSONX_API_KEY"],
        params={"temperature": temperature},
    )


_EXTRACTION_SYSTEM_PROMPT = """\
You extract structured payment instructions from a user's free-text request.

Find every distinct payment the user wants to make. For each one, extract:
- recipient: who the money goes to (name)
- amount: the numeric amount, no currency symbols or thousands separators
- currency: ISO-ish currency code; default to INR if not stated
- purpose: the stated reason for the payment, or null if not stated

Only extract payments explicitly mentioned. Do not invent recipients or
amounts. If the text contains no payment instructions, return an empty list.\
"""

_JSON_SCHEMA_HINT = """\
Respond with ONLY a single JSON object, no markdown fences, no commentary,
matching exactly this shape:

{"transactions": [{"recipient": "<string>", "amount": <number>, "currency": "INR", "purpose": "<string or null>"}]}\
"""

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _strip_fences(text: str) -> str:
    return _FENCE_RE.sub("", text).strip()


def _parse_via_structured_output(llm, text: str) -> ParsedTransactionList:
    structured_llm = llm.with_structured_output(ParsedTransactionList)
    result = structured_llm.invoke(
        [
            ("system", _EXTRACTION_SYSTEM_PROMPT),
            ("human", text),
        ]
    )
    if isinstance(result, ParsedTransactionList):
        return result
    return ParsedTransactionList.model_validate(result)


def _parse_via_json_prompting(llm, text: str, max_attempts: int = 3) -> ParsedTransactionList:
    messages = [
        ("system", _EXTRACTION_SYSTEM_PROMPT + "\n\n" + _JSON_SCHEMA_HINT),
        ("human", text),
    ]
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        response = llm.invoke(messages)
        raw = _strip_fences(response.content if hasattr(response, "content") else str(response))
        try:
            data = json.loads(raw)
            return ParsedTransactionList.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = exc
            messages.append(("ai", raw))
            messages.append(
                (
                    "human",
                    f"That was invalid ({exc}). Reply again with ONLY the corrected JSON object, "
                    "matching the schema exactly.",
                )
            )
    raise WatsonxConfigError(
        f"LLM failed to produce valid structured output after {max_attempts} attempts: {last_error}"
    )


def parse_with_llm(text: str, llm=None) -> ParsedTransactionList:
    """Extract payment instructions using structured output, falling back to
    JSON-prompting + Pydantic validation retries if that's unreliable."""
    llm = llm or get_llm()
    try:
        return _parse_via_structured_output(llm, text)
    except Exception:
        return _parse_via_json_prompting(llm, text)
