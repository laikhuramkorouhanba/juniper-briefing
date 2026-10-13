#!/usr/bin/env python3
"""Smoke test: one tiny structured call to the configured provider.

Usage:
    python check_llm.py                  # uses config.yaml's provider
    python check_llm.py --provider gemini
    python check_llm.py --provider mock
"""

from __future__ import annotations

import argparse
import sys

from pydantic import BaseModel

from juniper.config import load_config
from juniper.llm import ProviderUnavailable, StructuredCallFailed, call_structured


class PingResponse(BaseModel):
    ok: bool
    note: str


PING_PROMPT = (
    "This is a connectivity check for the Juniper Café feedback briefing pipeline. "
    "Reply with ok=true and a short note confirming you received this message."
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=["gemini", "mock"], default=None)
    args = parser.parse_args()

    config = load_config(provider_override=args.provider)
    print(f"provider: {config.provider}")

    if config.provider == "mock":
        # Mock mode is always "available" by construction — it's local fixture files,
        # not a network connection — so there's nothing live to smoke-test here.
        print("OK: mock mode needs no connectivity check (reads local fixtures)")
        return 0

    try:
        parsed, log = call_structured("agent1_tagger", PING_PROMPT, PingResponse, config=config)
    except ProviderUnavailable as exc:
        print(f"UNAVAILABLE: {exc}")
        return 1
    except StructuredCallFailed as exc:
        print(f"FAILED: {exc}")
        return 1

    print(f"OK: ok={parsed.ok} note={parsed.note!r}")
    print(
        f"latency_s={log.latency_s:.2f} model={log.model} "
        f"input_tokens={log.input_tokens} output_tokens={log.output_tokens}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
