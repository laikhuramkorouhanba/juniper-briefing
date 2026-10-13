"""Shared "call -> run code checks -> retry with the error message" pattern.

juniper/llm.py's call_structured() already retries on JSON/schema-validation
failure (a response that doesn't parse as the output_model at all). This module
layers a second, independent retry on top: for responses that DO parse, but
fail a business-rule check (a fake quote, an unknown theme, a dropped tag...).
Used by Agent 1, Agent 2 and (Phase 5) Agent 4.
"""

from __future__ import annotations

from typing import Callable, Optional, Type, TypeVar

from pydantic import BaseModel

from juniper.config import Config
from juniper.llm import Adapter, StructuredCallFailed, call_structured
from juniper.models import CallLog

T = TypeVar("T", bound=BaseModel)


class SemanticValidationError(RuntimeError):
    """Raised when an LLM response parses fine but still fails the code checks
    after config.max_retries correction attempts. The caller should mark that
    stage FAIL — this is not a crash-the-pipeline condition by itself."""


def call_with_semantic_retry(
    agent_name: str,
    build_prompt: Callable[[str], str],
    output_model: Type[T],
    validate: Callable[[T], list[str]],
    *,
    config: Config,
    test_id: Optional[str] = None,
    adapter: Optional[Adapter] = None,
    fixture_key: Optional[str] = None,
) -> tuple[T, CallLog]:
    """
    build_prompt(extra_instruction) -> full prompt text. Called with "" on the
      first attempt, and with a correction instruction (summarising the failed
      checks) on every retry.
    validate(parsed) -> list of human-readable error strings; empty = valid.
    `adapter` and `fixture_key` are passed straight through to call_structured.
    """
    extra_instruction = ""
    last_errors: list[str] = []

    for _attempt in range(config.max_retries + 1):
        prompt = build_prompt(extra_instruction)
        try:
            parsed, log = call_structured(
                agent_name, prompt, output_model, config=config, test_id=test_id,
                adapter=adapter, fixture_key=fixture_key,
            )
        except StructuredCallFailed as exc:
            raise SemanticValidationError(str(exc)) from exc

        errors = validate(parsed)
        if not errors:
            return parsed, log

        last_errors = errors
        extra_instruction = (
            "Your previous output failed these checks:\n- "
            + "\n- ".join(errors)
            + "\nReturn corrected JSON that fixes all of these."
        )

    raise SemanticValidationError(
        f"{agent_name}: still failing checks after {config.max_retries} retries: {last_errors}"
    )
