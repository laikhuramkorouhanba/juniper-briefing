"""LLM client: structured output, retries, mock mode, call log.

One function, one interface, regardless of provider:

    call_structured(agent_name, prompt_text, output_model) -> (parsed_model, CallLog)

Providers (config.yaml's `provider`, or a `--provider` CLI flag): `gemini` (free-tier
Google Gemini Flash) and `mock` (canned fixtures, no key, no network). See
docs/decisions.md for why there's no local-model fallback.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional, Protocol, Type, TypeVar

from pydantic import BaseModel, ValidationError

from juniper.config import Config, get_config
from juniper.models import CallLog

T = TypeVar("T", bound=BaseModel)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "mock"

# Exponential backoff schedule for rate-limit / quota errors, per docs/contracts.md.
_RATE_LIMIT_BACKOFF_S = (2, 4, 8)


class ProviderUnavailable(RuntimeError):
    """The configured provider can't serve a request right now: no key, the host is
    unreachable, or it's rate-limited/out of quota after the backoff schedule.
    Callers — especially the Streamlit app — must catch this and degrade gracefully
    (e.g. point the user at the Demo tab) rather than crash."""


class StructuredCallFailed(RuntimeError):
    """Raised when the provider still returns invalid output after max_retries.
    Carries the CallLog (ok=False) so the caller can log it and mark that stage FAIL
    without the whole pipeline crashing uncontrolled."""

    def __init__(self, message: str, call_log: CallLog):
        super().__init__(message)
        self.call_log = call_log


class Adapter(Protocol):
    """What call_structured needs from a provider adapter. Tests inject a fake
    implementing just this — they never need a real network client."""

    def generate(self, prompt: str, output_model: Type[BaseModel], model_name: str) -> tuple[str, int, int]:
        """Return (raw_json_text, input_tokens, output_tokens). Raises
        ProviderUnavailable on a rate-limit/quota error that survived the backoff
        schedule, or any other exception on a non-retryable provider failure."""
        ...


# ---------------------------------------------------------------------------
# Mock provider
# ---------------------------------------------------------------------------


def _load_mock_fixture(test_id: str, agent_name: str, output_model: Type[T]) -> T:
    path = FIXTURES_DIR / test_id / f"{agent_name}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"Mock fixture not found: {path}. provider: mock needs no key/network, "
            "but it does need a canned response for every (test_id, agent) pair it's "
            "asked for."
        )
    data = json.loads(path.read_text())
    return output_model.model_validate(data)


# ---------------------------------------------------------------------------
# Gemini adapter
# ---------------------------------------------------------------------------


class GeminiAdapter:
    """google-genai SDK, structured output via response_schema=<pydantic class>."""

    def __init__(self, config: Config):
        api_key = config.gemini_api_key
        if not api_key:
            raise ProviderUnavailable(
                "GEMINI_API_KEY is not set (checked st.secrets, then .env / environment)"
            )
        from google import genai  # imported lazily: never required in mock-only use

        self._client = genai.Client(api_key=api_key)
        self._temperature = config.temperature
        self._max_tokens = config.max_tokens

    def available(self) -> bool:
        """Cheap check for the Streamlit app's startup provider list: does a key
        exist at all? Deliberately makes no network call, to avoid spending quota
        just to populate a UI toggle."""
        return True  # __init__ already raised ProviderUnavailable if there's no key

    def generate(self, prompt: str, output_model: Type[BaseModel], model_name: str) -> tuple[str, int, int]:
        from google.genai import errors, types

        def _config(use_schema: bool) -> "types.GenerateContentConfig":
            kwargs: dict[str, Any] = {
                "temperature": self._temperature,
                "max_output_tokens": self._max_tokens,
                "response_mime_type": "application/json",
            }
            if use_schema:
                kwargs["response_schema"] = output_model
            return types.GenerateContentConfig(**kwargs)

        def _call(use_schema: bool):
            return self._client.models.generate_content(
                model=model_name,
                contents=prompt if use_schema else _plain_json_prompt(prompt, output_model),
                config=_config(use_schema),
            )

        last_exc: Optional[BaseException] = None
        attempt = 0
        use_schema = True
        while True:
            try:
                response = _call(use_schema)
                text = response.text or ""
                usage = response.usage_metadata
                input_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
                output_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)
                return text, input_tokens, output_tokens
            except errors.APIError as exc:
                if exc.code == 429:
                    if attempt >= len(_RATE_LIMIT_BACKOFF_S):
                        raise ProviderUnavailable(
                            f"gemini rate-limited / out of quota after backoff: {exc}"
                        ) from exc
                    time.sleep(_RATE_LIMIT_BACKOFF_S[attempt])
                    attempt += 1
                    last_exc = exc
                    continue
                if exc.code == 400 and use_schema:
                    # Schema rejected (e.g. an unusual Optional/nested shape) -> retry
                    # once in plain JSON mode with the schema spelled out in the prompt.
                    use_schema = False
                    last_exc = exc
                    continue
                raise
        raise ProviderUnavailable(f"gemini request failed: {last_exc}")  # pragma: no cover


def _plain_json_prompt(prompt: str, output_model: Type[BaseModel]) -> str:
    schema = json.dumps(output_model.model_json_schema(), indent=2)
    return (
        f"{prompt}\n\n"
        "Return ONLY JSON matching exactly this JSON schema, with no other text:\n"
        f"{schema}"
    )


# ---------------------------------------------------------------------------
# Adapter selection + cost estimate
# ---------------------------------------------------------------------------


def _get_adapter(provider: str, config: Config) -> Adapter:
    if provider == "gemini":
        return GeminiAdapter(config)
    raise ValueError(f"No live adapter for provider {provider!r}")


def _paid_estimate(
    config: Config, model_name: str, input_tokens: int, output_tokens: int
) -> Optional[float]:
    prices = config.paid_price_per_mtok_eur(model_name)
    price_in, price_out = prices.get("input"), prices.get("output")
    if price_in is None or price_out is None:
        return None
    return (input_tokens / 1_000_000) * price_in + (output_tokens / 1_000_000) * price_out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def call_structured(
    agent_name: str,
    prompt_text: str,
    output_model: Type[T],
    *,
    config: Optional[Config] = None,
    test_id: Optional[str] = None,
    adapter: Optional[Adapter] = None,
) -> tuple[T, CallLog]:
    """Call the configured provider and return a validated output_model instance
    plus a CallLog.

    On a pydantic/JSON validation failure, retries up to config.max_retries times,
    appending the validation error to the prompt so the model can self-correct. If
    it still fails after retries, raises StructuredCallFailed (carrying the failed
    CallLog) rather than crashing silently.

    `adapter` is an injection point for tests (anything implementing Adapter.generate)
    and is never required in normal use.
    """
    config = config or get_config()
    provider = config.provider
    model_name = config.model_for(agent_name, provider)
    prompt_version = config.prompt_version(agent_name)

    if provider == "mock":
        if not test_id:
            raise ValueError("provider 'mock' requires a test_id to pick the right fixture")
        start = time.monotonic()
        parsed = _load_mock_fixture(test_id, agent_name, output_model)
        latency = time.monotonic() - start
        return parsed, CallLog(
            agent=agent_name,
            provider="mock",
            model=model_name,
            prompt_version=prompt_version,
            latency_s=latency,
            input_tokens=0,
            output_tokens=0,
            cost_eur=0.0,
            cost_eur_if_paid_est=None,
            retries=0,
            ok=True,
        )

    live_adapter = adapter or _get_adapter(provider, config)

    current_prompt = prompt_text
    last_error: Optional[Exception] = None
    start = time.monotonic()

    # attempt_index 0 is the first (non-retry) try; up to max_retries further
    # retries follow, so this runs at most max_retries + 1 times in total.
    for attempt_index in range(config.max_retries + 1):
        raw_text, input_tokens, output_tokens = live_adapter.generate(
            current_prompt, output_model, model_name
        )
        try:
            data = json.loads(raw_text)
            parsed = output_model.model_validate(data)
            return parsed, CallLog(
                agent=agent_name,
                provider=provider,
                model=model_name,
                prompt_version=prompt_version,
                latency_s=time.monotonic() - start,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_eur=0.0,
                cost_eur_if_paid_est=_paid_estimate(config, model_name, input_tokens, output_tokens),
                retries=attempt_index,
                ok=True,
            )
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = exc
            current_prompt = (
                f"{prompt_text}\n\n"
                f"Your previous output failed validation: {exc}\n"
                "Return corrected JSON that matches the required schema exactly."
            )

    failed_log = CallLog(
        agent=agent_name,
        provider=provider,
        model=model_name,
        prompt_version=prompt_version,
        latency_s=time.monotonic() - start,
        input_tokens=0,
        output_tokens=0,
        cost_eur=0.0,
        cost_eur_if_paid_est=None,
        retries=config.max_retries,
        ok=False,
    )
    raise StructuredCallFailed(
        f"{agent_name}: still invalid after {config.max_retries} retries: {last_error}",
        call_log=failed_log,
    )
