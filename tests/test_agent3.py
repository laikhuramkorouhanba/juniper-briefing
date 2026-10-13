from __future__ import annotations

from pathlib import Path

from juniper.agent3_scorer import score
from juniper.config import load_config
from juniper.io_utils import load_codebook, load_comments
from juniper.llm import call_structured
from juniper.models import Agent2Output
from juniper.stage0_preprocess import preprocess

REPO_ROOT = Path(__file__).resolve().parent.parent
KNOWN_BRANCHES = ["Central", "Riverside", "Station"]


def _t01_stage0():
    df = load_comments(REPO_ROOT / "data" / "batch_original.csv")
    return preprocess(df, KNOWN_BRANCHES)


def _t01_agent2_output() -> Agent2Output:
    config = load_config(provider_override="mock")
    parsed, _log = call_structured(
        "agent2_polarity", "unused in mock mode", Agent2Output, config=config, test_id="T01"
    )
    return parsed


def test_t01_scores_match_expectations():
    stage0 = _t01_stage0()
    agent2_output = _t01_agent2_output()

    result = score(agent2_output, stage0.clean_comments, stage0, single_mention_max=1)

    assert result.visits_total == 11

    # docs/contracts.md 5.7's worked example, reproduced exactly by our T01 fixture:
    central = result.shops["Central"]
    assert central.themes["waiting_time"].n_pos == 1
    assert central.themes["waiting_time"].n_neg == 1
    assert central.themes["waiting_time"].mentions == 2
    assert central.themes["waiting_time"].mention_rate == 0.4
    assert central.themes["waiting_time"].score == 0.0
    assert central.themes["waiting_time"].evidence_level == "repeated"
    assert central.themes["waiting_time"].mixed is True
    assert central.negative_themes_ranked == ["waiting_time", "cleanliness", "product_availability"]
    assert central.no_detail_ids == ["F11"]

    # priority_theme = waiting_time for every shop
    for shop in ("Central", "Riverside", "Station"):
        assert result.shops[shop].priority_theme == "waiting_time"

    # network priority = waiting_time
    assert result.network.priority_theme == "waiting_time"
    assert result.network.themes["waiting_time"].n_neg == 3
    assert result.network.themes["waiting_time"].shops_with_negative == ["Central", "Riverside", "Station"]

    # suggestions list contains F08
    suggestion_ids = [s.comment_id for s in result.suggestions]
    assert "F08" in suggestion_ids
    f08 = next(s for s in result.suggestions if s.comment_id == "F08")
    assert f08.shop == "Riverside"
    assert f08.theme == "menu_range"


def test_visit_denominator_matches_branch_counts():
    stage0 = _t01_stage0()
    agent2_output = _t01_agent2_output()

    result = score(agent2_output, stage0.clean_comments, stage0)

    assert result.shops["Central"].visits == 5
    assert result.shops["Riverside"].visits == 4
    assert result.shops["Station"].visits == 2


def test_empty_batch_short_circuits():
    stage0 = preprocess(load_comments(REPO_ROOT / "data" / "batch_original.csv").iloc[0:0], KNOWN_BRANCHES)
    result = score(Agent2Output(items=[]), [], stage0)

    assert result.visits_total == 0
    assert result.shops == {}
    assert result.network.priority_theme is None
    assert result.suggestions == []
