"""Shared text helpers for quote checking.

Quotes must be an exact substring of their source text "after whitespace
normalisation only" (docs/contracts.md 5.5) — case and punctuation are NOT
touched here. This is deliberately a different, stricter normalisation than
stage0_preprocess's duplicate-detection one, which also lowercases.
"""

from __future__ import annotations


def normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def is_exact_substring(quote: str, source_text: str) -> bool:
    return normalize_whitespace(quote) in normalize_whitespace(source_text)
