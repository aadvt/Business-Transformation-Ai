"""watsonx.ai HTTP transport — IAM token exchange + inference calls.

This is the ONLY file in the codebase that knows watsonx's wire format. Swapping
to the official `ibm-watsonx-ai` SDK means rewriting this file and nothing else.

Why raw httpx instead of the SDK: the SDK pulls pandas, numpy and the full IBM
COS/S3 SDK (~25MB of transitive dependencies) to do what is, for our purposes,
two POST requests. httpx is already a dependency. The Phase 3 brief explicitly
allows this trade ("fall back to raw httpx REST if the SDK is heavy or awkward")
as long as the choice is isolated — hence this module boundary.
"""

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger("sanjeevani.llm.transport")

# Refresh the IAM token this many seconds before it actually expires, so a call
# that starts just under the wire doesn't land with a token that died in flight.
_TOKEN_REFRESH_MARGIN_SECONDS = 300

_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class LLMTransportError(RuntimeError):
    """A watsonx call failed in a way the caller should degrade on, not crash on."""


@dataclass(frozen=True)
class RawGeneration:
    text: str
    model_id: str
    token_usage: dict[str, int]
    raw: dict[str, Any]


class _IAMTokenCache:
    """Exchanges the API key for a bearer token and caches it until near expiry.

    IBM Cloud IAM tokens last an hour; minting one per request would add a full
    extra round-trip to every model call. Guarded by a lock so concurrent
    requests during a demo don't stampede the IAM endpoint on cold start.
    """

    def __init__(self) -> None:
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._lock = threading.Lock()

    def get(self, client: httpx.Client) -> str:
        with self._lock:
            now = time.time()
            if self._token and now < self._expires_at - _TOKEN_REFRESH_MARGIN_SECONDS:
                return self._token

            response = client.post(
                settings.watsonx_iam_url,
                headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
                data={
                    "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                    "apikey": settings.watsonx_api_key,
                },
            )
            if response.status_code != 200:
                # Body may echo the key back in an error envelope — log status only.
                raise LLMTransportError(f"IAM token exchange failed with HTTP {response.status_code}")

            payload = response.json()
            self._token = payload["access_token"]
            self._expires_at = now + int(payload.get("expires_in", 3600))
            logger.info("iam_token_refreshed", extra={"expires_in_s": int(payload.get("expires_in", 3600))})
            return self._token

    def invalidate(self) -> None:
        with self._lock:
            self._token = None
            self._expires_at = 0.0


class WatsonxTransport:
    def __init__(self) -> None:
        self._tokens = _IAMTokenCache()
        self._client = httpx.Client(timeout=settings.llm_timeout_seconds)

    def close(self) -> None:
        self._client.close()

    # --- public API used by app/llm/client.py and app/llm/guardian.py ---------

    def chat(self, system: str, user: str, *, max_tokens: int, temperature: float) -> RawGeneration:
        """Chat-completions call — used for general generation with a system prompt."""
        body = {
            "model_id": settings.watsonx_model_id,
            "project_id": settings.watsonx_project_id,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        payload = self._post("/ml/v1/text/chat", body)
        choices = payload.get("choices") or []
        text = choices[0].get("message", {}).get("content", "") if choices else ""
        usage = payload.get("usage") or {}
        return RawGeneration(
            text=text or "",
            model_id=payload.get("model_id", settings.watsonx_model_id),
            token_usage={
                "input_tokens": int(usage.get("prompt_tokens", 0)),
                "output_tokens": int(usage.get("completion_tokens", 0)),
                "total_tokens": int(usage.get("total_tokens", 0)),
            },
            raw=payload,
        )

    def generate(
        self, prompt: str, *, model_id: str, max_tokens: int, temperature: float,
        top_n_tokens: int | None = None,
    ) -> RawGeneration:
        """Raw text-generation call — used by Guardian, which needs its own prompt
        template applied verbatim rather than wrapped in a chat envelope."""
        parameters: dict[str, Any] = {
            "decoding_method": "greedy" if temperature == 0 else "sample",
            "max_new_tokens": max_tokens,
            "min_new_tokens": 1,
        }
        if temperature > 0:
            parameters["temperature"] = temperature
        if top_n_tokens:
            # Lets Guardian report a confidence from the Yes/No token distribution.
            parameters["return_options"] = {"top_n_tokens": top_n_tokens, "generated_tokens": True}

        body = {
            "model_id": model_id,
            "project_id": settings.watsonx_project_id,
            "input": prompt,
            "parameters": parameters,
        }
        payload = self._post("/ml/v1/text/generation", body)
        results = payload.get("results") or []
        first = results[0] if results else {}
        return RawGeneration(
            text=first.get("generated_text", "") or "",
            model_id=payload.get("model_id", model_id),
            token_usage={
                "input_tokens": int(first.get("input_token_count", 0)),
                "output_tokens": int(first.get("generated_token_count", 0)),
                "total_tokens": int(first.get("input_token_count", 0)) + int(first.get("generated_token_count", 0)),
            },
            raw=payload,
        )

    # --- internals -----------------------------------------------------------

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """POST with bounded retries. Retries only on timeouts and 5xx/429 —
        a 400 means our request is wrong and will be wrong every time."""
        url = f"{settings.watsonx_url.rstrip('/')}{path}?version={settings.watsonx_api_version}"
        last_error: str | None = None

        for attempt in range(1, settings.llm_max_attempts + 1):
            try:
                token = self._tokens.get(self._client)
                response = self._client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    json=body,
                )

                if response.status_code == 200:
                    return response.json()

                if response.status_code == 401:
                    # Token rejected — drop it and let the next attempt re-mint.
                    self._tokens.invalidate()
                    last_error = "HTTP 401 (token rejected)"
                elif response.status_code in _RETRYABLE_STATUS:
                    last_error = f"HTTP {response.status_code}"
                else:
                    raise LLMTransportError(
                        f"watsonx {path} returned HTTP {response.status_code}: {response.text[:300]}"
                    )

            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"

            if attempt < settings.llm_max_attempts:
                backoff = 0.5 * (2 ** (attempt - 1))  # 0.5s, 1s, 2s...
                logger.warning(
                    "watsonx_retry",
                    extra={"path": path, "attempt": attempt, "error": last_error, "backoff_s": backoff},
                )
                time.sleep(backoff)

        raise LLMTransportError(
            f"watsonx {path} failed after {settings.llm_max_attempts} attempts: {last_error}"
        )


_transport: WatsonxTransport | None = None
_transport_lock = threading.Lock()


def get_transport() -> WatsonxTransport:
    """Process-wide singleton, so the IAM token cache is actually shared."""
    global _transport
    with _transport_lock:
        if _transport is None:
            _transport = WatsonxTransport()
        return _transport
