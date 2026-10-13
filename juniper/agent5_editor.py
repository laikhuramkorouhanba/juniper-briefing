"""Agent 5 · Final briefing editor (LLM). See docs/contracts.md Section 5.9.

Single call. Agent 5 never produces counts tables (render.py injects those from
Agent 3) and its priority calls are never authoritative — Agent 3's computed
priority_theme / network priority always win; a disagreement is logged as a
warning, not silently dropped.
"""

from __future__ import annotations

from typing import Optional

from juniper.checked_call import call_with_semantic_retry
from juniper.config import Config
from juniper.io_utils import render_prompt
from juniper.llm import Adapter
from juniper.models import (
    Agent3Output,
    Agent4Output,
    Agent5Output,
    CallLog,
    NetworkPriority,
    Stage0Output,
)

AGENT_NAME = "agent5_editor"


def _batch_meta(stage0: Stage0Output) -> dict:
    return {
        "comments_total": stage0.comments_total,
        "visits_total": stage0.visits_total,
        "visits_by_branch": stage0.visits_by_branch,
        "duplicate_ids": [d.comment_id for d in stage0.duplicates],
        "unknown_branches": stage0.unknown_branches,
    }


def _shop_scores_payload(agent3: Agent3Output) -> dict:
    return {
        shop: {
            "visits": s.visits,
            "themes": {theme: ts.model_dump() for theme, ts in s.themes.items()},
            "negative_themes_ranked": s.negative_themes_ranked,
            "priority_theme": s.priority_theme,
        }
        for shop, s in agent3.shops.items()
    }


def _no_detail_payload(agent3: Agent3Output) -> dict:
    return {shop: s.no_detail_ids for shop, s in agent3.shops.items()}


def _priorities_payload(agent3: Agent3Output) -> dict:
    return {
        "per_shop": {shop: s.priority_theme for shop, s in agent3.shops.items()},
        "network": agent3.network.priority_theme,
    }


def _validate(output: Agent5Output, known_shops: set[str]) -> list[str]:
    errors: list[str] = []
    got_shops = {s.shop for s in output.shops}
    missing = known_shops - got_shops
    extra = got_shops - known_shops
    if missing:
        errors.append(f"missing shop(s) in the briefing: {sorted(missing)}")
    if extra:
        errors.append(f"unexpected shop(s) not in this batch: {sorted(extra)}")
    return errors


def edit_briefing(
    stage0: Stage0Output,
    agent3_output: Agent3Output,
    agent4_output: Agent4Output,
    *,
    config: Config,
    test_id: Optional[str] = None,
    adapter: Optional[Adapter] = None,
) -> tuple[Agent5Output, Optional[CallLog], list[str]]:
    """Returns (output, call_log, warnings). call_log is None on the zero-visits
    short-circuit (no LLM call made, cost 0). priority_theme on every shop and
    network_priority.theme are overwritten with Agent 3's values in-place;
    `warnings` lists every case where Agent 5 disagreed (this is also what
    verification check V9 looks at)."""
    if not agent3_output.shops:
        return (
            Agent5Output(
                headline="No feedback received this week.",
                shops=[],
                network_priority=NetworkPriority(theme=None, reason="", action="", cited_ids=[]),
                requests=[],
                mixed_views_note="",
                limitations="No visits in this batch.",
            ),
            None,
            [],
        )

    prompt_version = config.prompt_version(AGENT_NAME)
    known_shops = set(agent3_output.shops.keys())

    batch_meta = _batch_meta(stage0)
    shop_scores = _shop_scores_payload(agent3_output)
    briefs = [b.model_dump() for b in agent4_output.briefs]
    suggestions = [s.model_dump() for s in agent3_output.suggestions]
    no_detail = _no_detail_payload(agent3_output)
    priorities = _priorities_payload(agent3_output)

    def build_prompt(extra_instruction: str) -> str:
        base = render_prompt(
            AGENT_NAME,
            prompt_version,
            batch_meta=batch_meta,
            shop_scores=shop_scores,
            briefs=briefs,
            suggestions=suggestions,
            no_detail=no_detail,
            priorities=priorities,
        )
        return base if not extra_instruction else f"{base}\n\n{extra_instruction}"

    parsed, log = call_with_semantic_retry(
        AGENT_NAME,
        build_prompt,
        Agent5Output,
        lambda output: _validate(output, known_shops),
        config=config,
        test_id=test_id,
        adapter=adapter,
    )

    warnings: list[str] = []

    for shop_summary in parsed.shops:
        expected = agent3_output.shops[shop_summary.shop].priority_theme
        if shop_summary.priority_theme != expected:
            warnings.append(
                f"Agent 5 said {shop_summary.shop}'s priority_theme was "
                f"{shop_summary.priority_theme!r}; overwritten with Agent 3's {expected!r}"
            )
            shop_summary.priority_theme = expected

    expected_network = agent3_output.network.priority_theme
    if parsed.network_priority.theme != expected_network:
        warnings.append(
            f"Agent 5 said the network priority was {parsed.network_priority.theme!r}; "
            f"overwritten with Agent 3's {expected_network!r}"
        )
        parsed.network_priority.theme = expected_network

    return parsed, log, warnings
