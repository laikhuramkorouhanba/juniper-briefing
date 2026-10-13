from __future__ import annotations

import json
from pathlib import Path

from juniper.agent1_tagger import tag_comments
from juniper.agent2_polarity import judge_polarity
from juniper.agent3_scorer import score
from juniper.agent5_editor import edit_briefing
from juniper.config import load_config
from juniper.io_utils import load_codebook, load_comments
from juniper.models import Agent4Output
from juniper.stage0_preprocess import preprocess

REPO_ROOT = Path(__file__).resolve().parent.parent
KNOWN_BRANCHES = ["Central", "Riverside", "Station"]


def _t01_pipeline_through_agent3(config):
    df = load_comments(REPO_ROOT / "data" / "batch_original.csv")
    codebook = load_codebook(REPO_ROOT / "codebook.yaml")
    stage0 = preprocess(df, KNOWN_BRANCHES)
    agent1_output, _ = tag_comments(stage0.clean_comments, codebook, config=config, test_id="T01")
    agent2_output, _ = judge_polarity(agent1_output, stage0.clean_comments, codebook, config=config, test_id="T01")
    agent3_output = score(agent2_output, stage0.clean_comments, stage0)
    return stage0, agent3_output


def test_t01_mock_agent5_runs():
    config = load_config(provider_override="mock")
    stage0, agent3_output = _t01_pipeline_through_agent3(config)

    agent5_output, log, warnings = edit_briefing(
        stage0, agent3_output, Agent4Output(briefs=[]), config=config, test_id="T01"
    )

    assert log is not None and log.ok
    assert {s.shop for s in agent5_output.shops} == set(agent3_output.shops.keys())
    # the T01 fixture already says waiting_time everywhere, matching Agent 3 exactly
    assert warnings == []
    for s in agent5_output.shops:
        assert s.priority_theme == agent3_output.shops[s.shop].priority_theme
    assert agent5_output.network_priority.theme == agent3_output.network.priority_theme


class _FakeAgent5Adapter:
    """Always returns the same (wrong-on-purpose) priority fields, to test that
    edit_briefing() overwrites them with Agent 3's values and logs a warning."""

    def __init__(self, response_json: str):
        self.response_json = response_json

    def generate(self, prompt, output_model):
        return self.response_json, 10, 5, "fake-model"


def test_agent5_priority_is_overwritten_on_disagreement():
    config = load_config(provider_override="gemini")  # irrelevant: adapter injected
    stage0, agent3_output = _t01_pipeline_through_agent3(load_config(provider_override="mock"))

    wrong_response = json.dumps(
        {
            "headline": "Headline",
            "shops": [
                {"shop": shop, "overview": "o", "priority_theme": "coffee_quality", "cited_ids": []}
                for shop in agent3_output.shops
            ],
            "network_priority": {
                "theme": "coffee_quality",
                "reason": "wrong on purpose",
                "action": "a",
                "cited_ids": [],
            },
            "requests": [],
            "mixed_views_note": "",
            "limitations": "l",
        }
    )
    fake = _FakeAgent5Adapter(wrong_response)

    agent5_output, log, warnings = edit_briefing(
        stage0, agent3_output, Agent4Output(briefs=[]), config=config, adapter=fake
    )

    assert log.ok
    assert len(warnings) == len(agent3_output.shops) + 1  # every shop + the network priority
    for s in agent5_output.shops:
        assert s.priority_theme == agent3_output.shops[s.shop].priority_theme
        assert s.priority_theme != "coffee_quality"
    assert agent5_output.network_priority.theme == agent3_output.network.priority_theme


def test_zero_visits_short_circuits_with_no_llm_call():
    config = load_config(provider_override="mock")
    empty_stage0 = preprocess(load_comments(REPO_ROOT / "data" / "batch_original.csv").iloc[0:0], KNOWN_BRANCHES)
    from juniper.models import Agent2Output

    empty_agent3 = score(Agent2Output(items=[]), [], empty_stage0)

    agent5_output, log, warnings = edit_briefing(
        empty_stage0, empty_agent3, Agent4Output(briefs=[]), config=config, test_id="DOES_NOT_MATTER"
    )

    assert log is None  # no LLM call made
    assert warnings == []
    assert agent5_output.headline == "No feedback received this week."
    assert agent5_output.shops == []
