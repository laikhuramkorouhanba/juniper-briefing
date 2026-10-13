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

# Gaps between retries of the SAME model on a retryable error (429 rate-limit/quota,
# 500/503/504 transient server errors — 504 DEADLINE_EXCEEDED was added after it
# showed up live during testing; it's a timeout, the same family as 500/503): 3
# attempts per model means 2 gaps. After these are exhausted on the primary model,
# generate() switches to the fallback model and runs the same schedule there
# before giving up.
_RETRYABLE_CODES = (429, 500, 503, 504)
_RETRY_BACKOFF_S = (2, 4)
_REQUEST_TIMEOUT_MS = 60_000  # free-tier responses can be slow


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

    def generate(self, prompt: str, output_model: Type[BaseModel]) -> tuple[str, int, int, str]:
        """Return (raw_json_text, input_tokens, output_tokens, model_used) — the
        adapter owns model selection (e.g. primary/fallback), so it reports back
        which model actually answered. Raises ProviderUnavailable if every model
        it tried is still failing after its backoff schedule, or any other
        exception on a non-retryable provider failure."""
        ...


# ---------------------------------------------------------------------------
# Mock provider
# ---------------------------------------------------------------------------


def _load_mock_fixture(
    test_id: str, agent_name: str, output_model: Type[T], fixture_key: Optional[str] = None
) -> T:
    """Loads fixtures/mock/<test_id>/<agent_name>.json, or, when an agent makes
    several distinct calls per run (Agent 4: one per (shop, negative theme)),
    fixtures/mock/<test_id>/<agent_name>__<fixture_key>.json. Falls back to the
    unkeyed file if a keyed one isn't there, so single-call agents (1, 2, 5,
    baseline) never need the suffix."""
    candidates = []
    if fixture_key:
        safe_key = fixture_key.replace("/", "_").replace(" ", "_")
        candidates.append(FIXTURES_DIR / test_id / f"{agent_name}__{safe_key}.json")
    candidates.append(FIXTURES_DIR / test_id / f"{agent_name}.json")

    for path in candidates:
        if path.exists():
            data = json.loads(path.read_text())
            return output_model.model_validate(data)

    raise FileNotFoundError(
        f"Mock fixture not found: tried {[str(p) for p in candidates]}. provider: mock "
        "needs no key/network, but it does need a canned response for every "
        "(test_id, agent[, fixture_key]) combination it's asked for."
    )


# ---------------------------------------------------------------------------
# Gemini adapter
# ---------------------------------------------------------------------------


class _ModelExhausted(Exception):
    """Internal control-flow signal: one model's retry budget ran out on a
    retryable error. Never escapes GeminiAdapter.generate()."""


class GeminiAdapter:
    """google-genai SDK, structured output via response_schema=<pydantic class>.

    Model names are never hardcoded: config.gemini_model (primary) and
    config.gemini_fallback_model (fallback) come from the environment. A 429
    (rate-limit/quota), 500 or 503 (transient server error) is retried with
    exponential backoff up to 3 attempts on the current model; if it's still
    failing, the next model in [primary, fallback] is tried the same way. Only
    once both are exhausted does this raise ProviderUnavailable.
    """

    def __init__(self, config: Config):
        api_key = config.gemini_api_key
        if not api_key:
            raise ProviderUnavailable(
                "GEMINI_API_KEY is not set (checked st.secrets, then .env / environment)"
            )
        from google import genai  # imported lazily: never required in mock-only use
        from google.genai import types

        self._client = genai.Client(
            api_key=api_key, http_options=types.HttpOptions(timeout=_REQUEST_TIMEOUT_MS)
        )
        self._temperature = config.temperature
        self._max_tokens = config.max_tokens
        self._primary_model = config.gemini_model
        self._fallback_model = config.gemini_fallback_model

    def available(self) -> bool:
        """Cheap check for the Streamlit app's startup provider list: does a key
        exist at all? Deliberately makes no network call, to avoid spending quota
        just to populate a UI toggle."""
        return True  # __init__ already raised ProviderUnavailable if there's no key

    def generate(self, prompt: str, output_model: Type[BaseModel]) -> tuple[str, int, int, str]:
        last_exc: Optional[BaseException] = None
        for model_name in (self._primary_model, self._fallback_model):
            try:
                text, input_tokens, output_tokens = self._call_model(prompt, output_model, model_name)
                return text, input_tokens, output_tokens, model_name
            except _ModelExhausted as exc:
                last_exc = exc.__cause__ or exc
                continue

        raise ProviderUnavailable(
            f"gemini unavailable on both {self._primary_model!r} and "
            f"{self._fallback_model!r} after retrying each: {last_exc}"
        ) from last_exc

    def _call_model(self, prompt: str, output_model: Type[BaseModel], model_name: str) -> tuple[str, int, int]:
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

        use_schema = True
        last_exc: Optional[BaseException] = None
        for attempt in range(len(_RETRY_BACKOFF_S) + 1):  # 3 attempts: 2 backoff gaps
            try:
                response = _call(use_schema)
                text = response.text or ""
                usage = response.usage_metadata
                input_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
                output_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)
                return text, input_tokens, output_tokens
            except errors.APIError as exc:
                last_exc = exc
                if exc.code == 400 and use_schema:
                    # Schema rejected (e.g. an unusual Optional/nested shape) -> retry
                    # in plain JSON mode with the schema spelled out in the prompt
                    # instead. No backoff needed — it's a deterministic fix, not a
                    # transient failure — but it does use one of the 3 attempt slots.
                    use_schema = False
                    continue
                if exc.code in _RETRYABLE_CODES:
                    if attempt < len(_RETRY_BACKOFF_S):
                        time.sleep(_RETRY_BACKOFF_S[attempt])
                        continue
                    raise _ModelExhausted() from exc
                raise  # non-retryable (e.g. a persistent 400) -> propagate immediately

        raise _ModelExhausted() from last_exc  # pragma: no cover — loop always returns/raises above


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
    fixture_key: Optional[str] = None,
) -> tuple[T, CallLog]:
    """Call the configured provider and return a validated output_model instance
    plus a CallLog.

    On a pydantic/JSON validation failure, retries up to config.max_retries times,
    appending the validation error to the prompt so the model can self-correct. If
    it still fails after retries, raises StructuredCallFailed (carrying the failed
    CallLog) rather than crashing silently.

    `adapter` is an injection point for tests (anything implementing Adapter.generate)
    and is never required in normal use. `fixture_key` disambiguates mock fixtures
    for agents that make several distinct calls per run (Agent 4: one per shop/theme).
    """
    config = config or get_config()
    provider = config.provider
    prompt_version = config.prompt_version(agent_name)

    if provider == "mock":
        if not test_id:
            raise ValueError("provider 'mock' requires a test_id to pick the right fixture")
        start = time.monotonic()
        parsed = _load_mock_fixture(test_id, agent_name, output_model, fixture_key)
        latency = time.monotonic() - start
        return parsed, CallLog(
            agent=agent_name,
            provider="mock",
            model=config.gemini_model,  # label only: mock makes no real call
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
    model_used = None
    for attempt_index in range(config.max_retries + 1):
        raw_text, input_tokens, output_tokens, model_used = live_adapter.generate(
            current_prompt, output_model
        )
        try:
            data = json.loads(raw_text)
            parsed = output_model.model_validate(data)
            return parsed, CallLog(
                agent=agent_name,
                provider=provider,
                model=model_used,
                prompt_version=prompt_version,
                latency_s=time.monotonic() - start,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_eur=0.0,
                cost_eur_if_paid_est=_paid_estimate(config, model_used, input_tokens, output_tokens),
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
        model=model_used,
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
