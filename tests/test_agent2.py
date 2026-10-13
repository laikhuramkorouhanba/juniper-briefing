from __future__ import annotations

from pathlib import Path

from juniper.agent1_tagger import tag_comments
from juniper.agent2_polarity import _validate_items, judge_polarity
from juniper.config import load_config
from juniper.io_utils import load_codebook, load_comments
from juniper.models import Agent2Item, Assessment
from juniper.stage0_preprocess import preprocess

REPO_ROOT = Path(__file__).resolve().parent.parent
KNOWN_BRANCHES = ["Central", "Riverside", "Station"]


def test_t01_mock_passes_checks():
    config = load_config(provider_override="mock")
    df = load_comments(REPO_ROOT / "data" / "batch_original.csv")
    codebook = load_codebook(REPO_ROOT / "codebook.yaml")
    stage0 = preprocess(df, KNOWN_BRANCHES)

    agent1_output, _ = tag_comments(stage0.clean_comments, codebook, config=config, test_id="T01")
    agent2_output, call_logs = judge_polarity(
        agent1_output, stage0.clean_comments, codebook, config=config, test_id="T01"
    )

    assert call_logs and all(log.ok for log in call_logs)
    assert {item.comment_id for item in agent2_output.items} == {
        item.comment_id for item in agent1_output.items
    }
    # every (comment_id, theme) Agent 1 tagged must appear in Agent 2's assessments
    expected_pairs = {
        (item.comment_id, tag.theme) for item in agent1_output.items for tag in item.themes
    }
    got_pairs = {
        (item.comment_id, a.theme) for item in agent2_output.items for a in item.assessments
    }
    assert expected_pairs == got_pairs


def test_validate_items_catches_added_theme():
    expected_pairs = {"F01": {("coffee_quality", "Lovely coffee")}}
    items = [
        Agent2Item(
            comment_id="F01",
            assessments=[
                Assessment(theme="coffee_quality", polarity="positive", quote="Lovely coffee", rationale="r"),
                Assessment(theme="waiting_time", polarity="negative", quote="queued", rationale="not from agent 1"),
            ],
        )
    ]

    errors = _validate_items(items, expected_pairs)

    assert any("added theme/quote pair" in e for e in errors)


def test_validate_items_catches_dropped_theme():
    expected_pairs = {
        "F01": {("coffee_quality", "Lovely coffee"), ("waiting_time", "queued for 15 minutes")}
    }
    items = [
        Agent2Item(
            comment_id="F01",
            assessments=[
                Assessment(theme="coffee_quality", polarity="positive", quote="Lovely coffee", rationale="r"),
            ],
        )
    ]

    errors = _validate_items(items, expected_pairs)

    assert any("dropped theme/quote pair" in e for e in errors)


def test_validate_items_catches_missing_comment():
    expected_pairs = {
        "F01": {("coffee_quality", "Lovely coffee")},
        "F02": set(),
    }
    items = [
        Agent2Item(
            comment_id="F01",
            assessments=[
                Assessment(theme="coffee_quality", polarity="positive", quote="Lovely coffee", rationale="r"),
            ],
        )
    ]

    errors = _validate_items(items, expected_pairs)

    assert any("missing comment_id" in e and "F02" in e for e in errors)
