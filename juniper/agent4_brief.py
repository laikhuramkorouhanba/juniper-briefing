"""Agent 4 · Theme brief + CTA writer (LLM). See docs/contracts.md Section 5.8.

One call per (shop, negative theme), run in parallel (config.yaml's
llm.agent4_concurrency). Each call gets that theme's Agent 3 numbers plus the
negative (and, for mixed views, positive) evidence for that one (shop, theme)
pair — never the whole batch.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from juniper.checked_call import call_with_semantic_retry
from juniper.config import Config
from juniper.io_utils import render_prompt
from juniper.llm import Adapter
from juniper.models import (
    Agent2Output,
    Agent3Output,
    Agent4Output,
    CallLog,
    Codebook,
    Comment,
    ThemeBrief,
)
from juniper.text_utils import is_exact_substring

AGENT_NAME = "agent4_brief"


def _quotes_by_comment_theme(agent2_output: Agent2Output) -> dict[tuple[str, str], str]:
    quotes: dict[tuple[str, str], str] = {}
    for item in agent2_output.items:
        for a in item.assessments:
            quotes[(item.comment_id, a.theme)] = a.quote
    return quotes


def _evidence_payload(
    ids: list[str],
    theme: str,
    comments_by_id: dict[str, Comment],
    quotes: dict[tuple[str, str], str],
) -> list[dict]:
    payload = []
    for comment_id in ids:
        comment = comments_by_id.get(comment_id)
        if comment is None:
            continue  # shouldn't happen: ids come straight from Agent 3's own scoring
        payload.append(
            {
                "comment_id": comment_id,
                "text": comment.text,
                "quote": quotes.get((comment_id, theme), ""),
            }
        )
    return payload


def _validate_brief(brief: ThemeBrief, allowed_ids: set[str], texts_by_id: dict[str, str]) -> list[str]:
    """The checks in docs/contracts.md 5.8: cited_ids must be a subset of the
    evidence passed in, and key_quotes must be exact substrings."""
    errors: list[str] = []

    extra_cited = set(brief.cited_ids) - allowed_ids
    if extra_cited:
        errors.append(f"cited_ids not in the evidence given to this call: {sorted(extra_cited)}")

    for kq in brief.key_quotes:
        text = texts_by_id.get(kq.comment_id)
        if text is None:
            errors.append(
                f"key_quotes references comment_id '{kq.comment_id}', not in the evidence given to this call"
            )
            continue
        if not is_exact_substring(kq.quote, text):
            errors.append(
                f"{kq.comment_id}: key_quote {kq.quote!r} is not an exact substring of the comment text"
            )

    return errors


def _build_one_brief(
    shop: str,
    theme: str,
    theme_label: str,
    theme_definition: str,
    stats: dict,
    negative_evidence: list[dict],
    positive_evidence: list[dict],
    *,
    config: Config,
    test_id: Optional[str],
    adapter: Optional[Adapter],
) -> tuple[ThemeBrief, CallLog]:
    prompt_version = config.prompt_version(AGENT_NAME)
    allowed_ids = {e["comment_id"] for e in negative_evidence} | {e["comment_id"] for e in positive_evidence}
    texts_by_id = {e["comment_id"]: e["text"] for e in (*negative_evidence, *positive_evidence)}

    def build_prompt(extra_instruction: str) -> str:
        base = render_prompt(
            AGENT_NAME,
            prompt_version,
            shop=shop,
            theme=theme,
            theme_label=theme_label,
            theme_definition=theme_definition,
            stats=stats,
            negative_evidence=negative_evidence,
            positive_evidence=positive_evidence,
        )
        return base if not extra_instruction else f"{base}\n\n{extra_instruction}"

    return call_with_semantic_retry(
        AGENT_NAME,
        build_prompt,
        ThemeBrief,
        lambda brief: _validate_brief(brief, allowed_ids, texts_by_id),
        config=config,
        test_id=test_id,
        adapter=adapter,
    )


def write_briefs(
    agent3_output: Agent3Output,
    agent2_output: Agent2Output,
    clean_comments: list[Comment],
    codebook: Codebook,
    *,
    config: Config,
    test_id: Optional[str] = None,
    adapter: Optional[Adapter] = None,
) -> tuple[Agent4Output, list[CallLog]]:
    """One ThemeBrief per (shop, negative theme) across the whole batch, run in
    parallel with ThreadPoolExecutor(max_workers=config.agent4_concurrency()).
    `adapter` is a test injection point (never required in normal use)."""
    comments_by_id = {c.comment_id: c for c in clean_comments}
    theme_defs = {t.name: t for t in codebook.themes}
    quotes = _quotes_by_comment_theme(agent2_output)

    jobs: list[tuple[str, str, str, str, dict, list[dict], list[dict]]] = []
    for shop, shop_score in agent3_output.shops.items():
        for theme in shop_score.negative_themes_ranked:
            theme_score = shop_score.themes[theme]
            theme_def = theme_defs.get(theme)
            stats = {
                "visits": shop_score.visits,
                "n_pos": theme_score.n_pos,
                "n_neg": theme_score.n_neg,
                "mentions": theme_score.mentions,
                "mention_rate": theme_score.mention_rate,
                "score": theme_score.score,
                "evidence_level": theme_score.evidence_level,
                "mixed": theme_score.mixed,
            }
            jobs.append(
                (
                    shop,
                    theme,
                    theme_def.label if theme_def else theme,
                    theme_def.definition if theme_def else "",
                    stats,
                    _evidence_payload(theme_score.negative_ids, theme, comments_by_id, quotes),
                    _evidence_payload(theme_score.positive_ids, theme, comments_by_id, quotes),
                )
            )

    if not jobs:
        return Agent4Output(briefs=[]), []

    def _run(job: tuple) -> tuple[ThemeBrief, CallLog]:
        shop, theme, label, definition, stats, neg_ev, pos_ev = job
        return _build_one_brief(
            shop, theme, label, definition, stats, neg_ev, pos_ev,
            config=config, test_id=test_id, adapter=adapter,
        )

    with ThreadPoolExecutor(max_workers=config.agent4_concurrency()) as pool:
        # pool.map preserves input order in its results, regardless of which
        # worker finishes first, so output ordering stays deterministic.
        results = list(pool.map(_run, jobs))

    briefs = [r[0] for r in results]
    call_logs = [r[1] for r in results]
    return Agent4Output(briefs=briefs), call_logs
