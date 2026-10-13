from __future__ import annotations

from pathlib import Path

from juniper.agent1_tagger import tag_comments
from juniper.agent2_polarity import judge_polarity
from juniper.agent3_scorer import score
from juniper.agent5_editor import edit_briefing
from juniper.config import load_config
from juniper.io_utils import load_codebook, load_comments
from juniper.models import CTA, Agent2Output, Agent4Output, ThemeBrief
from juniper.render import render_briefing
from juniper.stage0_preprocess import preprocess

REPO_ROOT = Path(__file__).resolve().parent.parent
KNOWN_BRANCHES = ["Central", "Riverside", "Station"]


def test_t01_renders_expected_sections():
    config = load_config(provider_override="mock")
    df = load_comments(REPO_ROOT / "data" / "batch_original.csv")
    codebook = load_codebook(REPO_ROOT / "codebook.yaml")
    stage0 = preprocess(df, KNOWN_BRANCHES)

    agent1_output, _ = tag_comments(stage0.clean_comments, codebook, config=config, test_id="T01")
    agent2_output, _ = judge_polarity(agent1_output, stage0.clean_comments, codebook, config=config, test_id="T01")
    agent3_output = score(agent2_output, stage0.clean_comments, stage0)

    # A couple of hand-built briefs (not going through the LLM): render.py only
    # cares about their shape, not their provenance.
    agent4_output = Agent4Output(
        briefs=[
            ThemeBrief(
                shop="Central", theme="waiting_time",
                summary_of_comments="One visit reported a long queue; another praised quick service.",
                interpretation="Waiting times may vary across the morning peak.",
                cta=CTA(action="Time the queue.", kind="investigate", data_needed=["orders per 15 min"], success_signal="A clear picture."),
                cited_ids=["F01", "F09"], key_quotes=[],
            ),
        ]
    )

    agent5_output, _log, _warnings = edit_briefing(
        stage0, agent3_output, agent4_output, config=config, test_id="T01"
    )

    briefing = render_briefing(stage0, agent3_output, agent4_output, agent5_output, label="dev run")

    assert "# Juniper Café Feedback Briefing" in briefing
    assert "_dev run_" in briefing
    assert "11 visits" in briefing
    assert "12 comments" in briefing
    assert "1 duplicate(s) removed" in briefing
    assert agent5_output.headline in briefing
    assert "## Network priority" in briefing
    assert "## Central" in briefing
    assert "## Riverside" in briefing
    assert "## Station" in briefing
    # the counts table header, injected by render.py (never by Agent 5)
    assert "| Theme | Positive | Negative | Score | Evidence | Comment IDs |" in briefing
    assert "### waiting_time" in briefing
    assert "Time the queue." in briefing
    assert "## Limitations" in briefing
    assert "## Removed or excluded" in briefing
    assert "F07" in briefing  # the duplicate, disclosed
    assert "F11" in briefing  # the no-usable-detail comment, disclosed


def test_zero_visits_short_circuits_render():
    empty_stage0 = preprocess(load_comments(REPO_ROOT / "data" / "batch_original.csv").iloc[0:0], KNOWN_BRANCHES)
    empty_agent3 = score(Agent2Output(items=[]), [], empty_stage0)
    config = load_config(provider_override="mock")
    agent5_output, _log, _warnings = edit_briefing(
        empty_stage0, empty_agent3, Agent4Output(briefs=[]), config=config
    )

    briefing = render_briefing(empty_stage0, empty_agent3, Agent4Output(briefs=[]), agent5_output)

    assert briefing.strip() == "# Juniper Café Feedback Briefing\n\nNo feedback received this week."
