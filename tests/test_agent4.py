from __future__ import annotations

import json
from pathlib import Path

from juniper.agent2_polarity import judge_polarity
from juniper.agent1_tagger import tag_comments
from juniper.agent3_scorer import score
from juniper.agent4_brief import (
    _build_one_brief,
    _evidence_payload,
    _quotes_by_comment_theme,
    _validate_brief,
    write_briefs,
)
from juniper.config import load_config
from juniper.io_utils import load_codebook, load_comments
from juniper.models import Agent2Output, CTA, KeyQuote, ThemeBrief
from juniper.stage0_preprocess import preprocess

REPO_ROOT = Path(__file__).resolve().parent.parent
KNOWN_BRANCHES = ["Central", "Riverside", "Station"]


def _t01_stage0():
    df = load_comments(REPO_ROOT / "data" / "batch_original.csv")
    return preprocess(df, KNOWN_BRANCHES)


def _dummy_cta() -> CTA:
    return CTA(action="Do a thing", kind="investigate", data_needed=[], success_signal="A clear signal.")


def test_validate_brief_catches_cited_id_not_in_evidence():
    brief = ThemeBrief(
        shop="Central", theme="waiting_time",
        summary_of_comments="...", interpretation="...",
        cta=_dummy_cta(), cited_ids=["F99"], key_quotes=[],
    )

    errors = _validate_brief(brief, allowed_ids={"F01", "F09"}, texts_by_id={"F01": "x", "F09": "y"})

    assert any("not in the evidence given" in e for e in errors)


def test_validate_brief_catches_fake_key_quote():
    brief = ThemeBrief(
        shop="Central", theme="waiting_time",
        summary_of_comments="...", interpretation="...",
        cta=_dummy_cta(), cited_ids=["F01"],
        key_quotes=[KeyQuote(comment_id="F01", quote="this text is not in the comment")],
    )

    errors = _validate_brief(brief, allowed_ids={"F01"}, texts_by_id={"F01": "queued for 15 minutes"})

    assert any("is not an exact substring" in e for e in errors)


def test_t01_central_waiting_time_mock_fixture_passes():
    """The T01 mock fixture (fixtures/mock/T01/agent4_brief.json) is exactly the
    Central/waiting_time example from docs/contracts.md — call just that one
    (shop, theme) pair directly, since a single static fixture can't answer every
    (shop, theme) write_briefs() would otherwise ask for."""
    config = load_config(provider_override="mock")
    stage0 = _t01_stage0()
    codebook = load_codebook(REPO_ROOT / "codebook.yaml")

    agent1_output, _ = tag_comments(stage0.clean_comments, codebook, config=config, test_id="T01")
    agent2_output, _ = judge_polarity(agent1_output, stage0.clean_comments, codebook, config=config, test_id="T01")
    agent3_output = score(agent2_output, stage0.clean_comments, stage0)

    theme = "waiting_time"
    shop_score = agent3_output.shops["Central"]
    theme_score = shop_score.themes[theme]
    theme_def = next(t for t in codebook.themes if t.name == theme)
    comments_by_id = {c.comment_id: c for c in stage0.clean_comments}
    quotes = _quotes_by_comment_theme(agent2_output)
    stats = {"visits": shop_score.visits, "n_pos": theme_score.n_pos, "n_neg": theme_score.n_neg}

    brief, log = _build_one_brief(
        "Central", theme, theme_def.label, theme_def.definition, stats,
        _evidence_payload(theme_score.negative_ids, theme, comments_by_id, quotes),
        _evidence_payload(theme_score.positive_ids, theme, comments_by_id, quotes),
        config=config, test_id="T01", adapter=None,
    )

    assert log.ok
    assert brief.shop == "Central"
    assert brief.theme == "waiting_time"
    assert set(brief.cited_ids) <= {"F01", "F09"}


class _TrackingFakeAdapter:
    """Always returns a trivially-valid ThemeBrief (empty cited_ids/key_quotes
    pass every check regardless of which (shop, theme) pair asked). Used to test
    write_briefs()' parallel orchestration without a real network call."""

    def __init__(self):
        self.calls = 0
        self.prompts: list[str] = []

    def generate(self, prompt, output_model):
        self.calls += 1
        self.prompts.append(prompt)
        body = json.dumps(
            {
                "shop": "irrelevant",
                "theme": "irrelevant",
                "summary_of_comments": "...",
                "interpretation": "...",
                "cta": {"action": "Do a thing", "kind": "investigate", "data_needed": [], "success_signal": "..."},
                "cited_ids": [],
                "key_quotes": [],
            }
        )
        return body, 10, 5, "fake-model"


def test_write_briefs_orchestrates_one_call_per_shop_theme():
    config = load_config(provider_override="gemini")  # irrelevant: adapter is injected
    stage0 = _t01_stage0()
    codebook = load_codebook(REPO_ROOT / "codebook.yaml")

    mock_config = load_config(provider_override="mock")
    agent1_output, _ = tag_comments(stage0.clean_comments, codebook, config=mock_config, test_id="T01")
    agent2_output, _ = judge_polarity(agent1_output, stage0.clean_comments, codebook, config=mock_config, test_id="T01")
    agent3_output = score(agent2_output, stage0.clean_comments, stage0)

    fake = _TrackingFakeAdapter()
    agent4_output, call_logs = write_briefs(
        agent3_output, agent2_output, stage0.clean_comments, codebook, config=config, adapter=fake
    )

    expected_jobs = sum(len(s.negative_themes_ranked) for s in agent3_output.shops.values())
    assert expected_jobs > 0
    assert fake.calls == expected_jobs
    assert len(agent4_output.briefs) == expected_jobs
    assert len(call_logs) == expected_jobs
    assert all(log.ok for log in call_logs)


def test_write_briefs_empty_when_no_negative_themes():
    config = load_config(provider_override="mock")
    codebook = load_codebook(REPO_ROOT / "codebook.yaml")
    empty_stage0 = preprocess(load_comments(REPO_ROOT / "data" / "batch_original.csv").iloc[0:0], KNOWN_BRANCHES)
    agent3_output = score(Agent2Output(items=[]), [], empty_stage0)

    agent4_output, call_logs = write_briefs(
        agent3_output, Agent2Output(items=[]), [], codebook, config=config
    )

    assert agent4_output.briefs == []
    assert call_logs == []
