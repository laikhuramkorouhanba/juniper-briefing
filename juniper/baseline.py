"""Baseline · single-prompt summary. See docs/contracts.md Section 5.10.

The baseline receives the same codebook and the same raw comments as the
pipeline, but NO Stage 0 preprocessing, no code checks, no pipeline. That
isolates exactly what the pipeline adds.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from juniper.config import Config
from juniper.io_utils import codebook_as_text, render_prompt
from juniper.llm import Adapter, call_structured
from juniper.models import BaselineOutput, CallLog, Codebook

AGENT_NAME = "baseline"


def _comments_payload(df: pd.DataFrame) -> list[dict]:
    return [
        {"comment_id": row.comment_id, "branch": row.branch, "text": row.comment}
        for row in df.itertuples(index=False)
    ]


def run_baseline(
    df: pd.DataFrame,
    codebook: Codebook,
    *,
    config: Config,
    test_id: Optional[str] = None,
    adapter: Optional[Adapter] = None,
) -> tuple[BaselineOutput, Optional[CallLog]]:
    """`df` is the RAW loaded batch (juniper.io_utils.load_comments), with every
    row — unlike the pipeline, the baseline never sees Stage 0's deduplication.
    An empty batch short-circuits to a zero-value output with no call, same as
    the pipeline's own zero-visits short-circuit."""
    if len(df) == 0:
        return BaselineOutput(visits_total=0, duplicates_noticed=[], shops=[]), None

    prompt_version = config.prompt_version(AGENT_NAME)
    prompt = render_prompt(
        AGENT_NAME,
        prompt_version,
        codebook=codebook_as_text(codebook),
        comments=_comments_payload(df),
    )
    return call_structured(
        AGENT_NAME, prompt, BaselineOutput, config=config, test_id=test_id, adapter=adapter
    )
