"""Load config.yaml + .env into a single Config object.

Secrets precedence for GEMINI_API_KEY and an optional PROVIDER override:
1. st.secrets, when running under Streamlit and the key exists there
2. .env / process environment

Never print or log the key itself (Config never stores it as a field — every read
goes through a property that re-reads the source each time).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config.yaml"


def _read_streamlit_secret(key: str) -> Optional[str]:
    """Best-effort read from st.secrets.

    Returns None for any reason it isn't available: not running under Streamlit,
    no secrets.toml / no Cloud secrets configured, or the key just isn't set there.
    Streamlit's own secrets access can raise in all of those cases, so this is
    deliberately a broad catch.
    """
    try:
        import streamlit as st  # imported lazily: never required outside the app

        if key in st.secrets:
            value = st.secrets[key]
            return str(value) if value is not None else None
    except Exception:
        return None
    return None


@dataclass
class Config:
    raw: dict[str, Any]
    provider_override: Optional[str] = None

    # ---- provider -----------------------------------------------------

    @property
    def provider(self) -> str:
        override = (
            self.provider_override
            or _read_streamlit_secret("PROVIDER")
            or os.environ.get("PROVIDER")
        )
        value = (override or self.raw["provider"]).strip().lower()
        if value not in ("gemini", "mock"):
            raise ValueError(f"Unknown provider {value!r}; expected gemini or mock")
        return value

    @property
    def gemini_api_key(self) -> Optional[str]:
        return _read_streamlit_secret("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY") or None

    # ---- models ---------------------------------------------------------

    def model_for(self, agent: str, provider: Optional[str] = None) -> str:
        """The model name configured for `agent` under `provider` (default: the
        active provider). Mock mode has no model of its own; it reports the gemini
        name for display purposes only (no call is actually made)."""
        provider = provider or self.provider
        lookup = provider if provider != "mock" else "gemini"
        return self.raw["models"][lookup][agent]

    def prompt_version(self, agent: str) -> str:
        return self.raw["prompt_versions"][agent]

    # ---- llm settings -----------------------------------------------------

    @property
    def temperature(self) -> float:
        return self.raw["llm"]["temperature"]

    @property
    def max_tokens(self) -> int:
        return self.raw["llm"]["max_tokens"]

    @property
    def max_retries(self) -> int:
        return self.raw["llm"]["max_retries"]

    def agent4_concurrency(self, provider: Optional[str] = None) -> int:
        provider = provider or self.provider
        value = self.raw["llm"]["agent4_concurrency"]
        if isinstance(value, dict):
            return int(value.get(provider, 1))
        return int(value)

    def batch_mode(self, agent: str) -> str:
        return self.raw["llm"]["batch_mode"].get(agent, "whole_batch")

    # ---- pricing (optional, paid-tier estimate only) -----------------------

    def paid_price_per_mtok_eur(self, model: str) -> dict[str, Optional[float]]:
        table = self.raw.get("paid_price_per_mtok_eur", {})
        return table.get(model, {"input": None, "output": None})

    # ---- misc ---------------------------------------------------------------

    @property
    def known_branches(self) -> list[str]:
        return self.raw.get("known_branches", [])

    @property
    def single_mention_max(self) -> int:
        return self.raw["scoring"]["single_mention_max"]

    @property
    def forbidden_phrases(self) -> list[str]:
        return self.raw["verify"]["forbidden_phrases"]

    @property
    def max_live_runs_per_session(self) -> int:
        return self.raw.get("app", {}).get("max_live_runs_per_session", 5)


def load_config(
    path: Path | str = DEFAULT_CONFIG_PATH,
    provider_override: Optional[str] = None,
) -> Config:
    """Load config.yaml and .env (idempotent: dotenv never overrides an already-set
    environment variable, so real deployment secrets always win over a stray .env)."""
    load_dotenv(REPO_ROOT / ".env", override=False)
    raw = yaml.safe_load(Path(path).read_text())
    return Config(raw=raw, provider_override=provider_override)


@lru_cache(maxsize=None)
def get_config() -> Config:
    """Cached default Config for modules that just want the standard config.yaml.
    Tests and CLIs that need a different path or provider should call load_config()
    directly instead."""
    return load_config()
