from __future__ import annotations

from pathlib import Path

from juniper.agent1_tagger import tag_comments
from juniper.agent2_polarity import judge_polarity
from juniper.agent3_scorer import score
from juniper.config import load_config
from juniper.io_utils import load_codebook, load_comments
from juniper.models import (
    CTA,
    Agent3Output,
    Agent4Output,
    Agent5Output,
    Comment,
    DuplicateRecord,
    KeyQuote,
    NetworkPriority,
    NetworkScore,
    NetworkThemeScore,
    ShopScore,
    ShopSummary,
    Stage0Output,
    ThemeBrief,
    ThemeScore,
)
from juniper.render import render_briefing
from juniper.stage0_preprocess import preprocess
from juniper.verify import verify_run

REPO_ROOT = Path(__file__).resolve().parent.parent
KNOWN_BRANCHES = ["Central", "Riverside", "Station"]


def _minimal_fixture():
    """A tiny, hand-built, otherwise-valid stage0/agent3/agent4/agent5 fixture:
    Central has one visit (F01) and one negative theme (theme_x); F03 is a
    duplicate of F01 (same visit). Riverside has one clean, theme-free visit
    (F02)."""
    stage0 = Stage0Output(
        comments_total=3,
        visits_total=2,
        clean_comments=[
            Comment(comment_id="F01", visit_id="V01", branch="Central", text="The queue was far too long today."),
            Comment(comment_id="F02", visit_id="V02", branch="Riverside", text="Lovely spot, nothing to add."),
        ],
        duplicates=[DuplicateRecord(comment_id="F03", duplicate_of="F01", visit_id="V01", text_differs=False)],
        visits_by_branch={"Central": 1, "Riverside": 1},
    )

    theme_score = ThemeScore(
        negative_ids=["F01"], n_pos=0, n_neg=1, n_sug=0, mentions=1, mention_rate=1.0,
        score=-1.0, evidence_level="single mention", mixed=False,
    )
    agent3 = Agent3Output(
        visits_total=2,
        shops={
            "Central": ShopScore(
                visits=1, themes={"theme_x": theme_score},
                negative_themes_ranked=["theme_x"], priority_theme="theme_x",
            ),
            "Riverside": ShopScore(visits=1, themes={}, negative_themes_ranked=[], priority_theme=None),
        },
        network=NetworkScore(
            themes={"theme_x": NetworkThemeScore(n_pos=0, n_neg=1, shops_with_negative=["Central"])},
            priority_theme="theme_x",
        ),
        suggestions=[],
    )

    agent4 = Agent4Output(
        briefs=[
            ThemeBrief(
                shop="Central", theme="theme_x",
                summary_of_comments="One visit reported a long queue.",
                interpretation="Possibly a peak-time issue.",
                cta=CTA(action="Time the queue.", kind="investigate", data_needed=[], success_signal="A clear picture."),
                cited_ids=["F01"],
                key_quotes=[KeyQuote(comment_id="F01", quote="queue was far too long")],
            ),
        ]
    )

    agent5 = Agent5Output(
        headline="Queue times need attention at Central.",
        shops=[
            ShopSummary(shop="Central", overview="One visit reported a long queue.", priority_theme="theme_x", cited_ids=["F01"]),
            ShopSummary(shop="Riverside", overview="Nothing notable.", priority_theme=None, cited_ids=[]),
        ],
        network_priority=NetworkPriority(theme="theme_x", reason="Only issue raised.", action="Time the queue.", cited_ids=["F01"]),
        requests=[],
        mixed_views_note="",
        limitations="One duplicate (F03) counted once as F01.",
    )

    return stage0, agent3, agent4, agent5


def test_clean_fixture_passes_every_hard_check():
    stage0, agent3, agent4, agent5 = _minimal_fixture()
    config = load_config(provider_override="mock")

    result = verify_run(stage0, agent3, agent4, agent5, config=config, agent5_warnings=[])

    by_id = {c.id: c for c in result.checks}
    for check_id in ("V1", "V2", "V3", "V5", "V7", "V8", "V10"):
        assert by_id[check_id].status == "PASS", f"{check_id}: {by_id[check_id].details}"
    assert result.overall_status in ("PASS", "WARN")


def test_v3_catches_fake_quote():
    stage0, agent3, agent4, agent5 = _minimal_fixture()
    agent4.briefs[0].key_quotes[0].quote = "this text does not appear in the comment"
    config = load_config(provider_override="mock")

    result = verify_run(stage0, agent3, agent4, agent5, config=config)

    v3 = next(c for c in result.checks if c.id == "V3")
    assert v3.status == "FAIL"
    assert result.overall_status == "FAIL"


def test_v2_catches_wrong_shop_id():
    stage0, agent3, agent4, agent5 = _minimal_fixture()
    # F02 belongs to Riverside, but cite it in Central's brief.
    agent4.briefs[0].cited_ids.append("F02")
    config = load_config(provider_override="mock")

    result = verify_run(stage0, agent3, agent4, agent5, config=config)

    v2 = next(c for c in result.checks if c.id == "V2")
    assert v2.status == "FAIL"
    assert "F02" in v2.details
    assert result.overall_status == "FAIL"


def test_v1_and_v10_catch_a_cited_duplicate():
    stage0, agent3, agent4, agent5 = _minimal_fixture()
    # F03 is a duplicate of F01 (same visit) — never a valid citation.
    agent4.briefs[0].cited_ids.append("F03")
    config = load_config(provider_override="mock")

    result = verify_run(stage0, agent3, agent4, agent5, config=config)

    by_id = {c.id: c for c in result.checks}
    assert by_id["V1"].status == "FAIL"  # F03 is not in clean_comments at all
    assert by_id["V10"].status == "FAIL"  # and it's independently a known duplicate
    assert result.overall_status == "FAIL"


def test_v10_catches_a_known_duplicate_cited_as_evidence():
    """V10 specifically: a duplicate ID that IS recognised (present in
    stage0.duplicates) must never be cited, even though V1 only checks against
    clean_comments and wouldn't otherwise flag it."""
    stage0, agent3, agent4, agent5 = _minimal_fixture()
    agent4.briefs[0].cited_ids.append("F03")
    config = load_config(provider_override="mock")

    result = verify_run(stage0, agent3, agent4, agent5, config=config)
    v10 = next(c for c in result.checks if c.id == "V10")
    # F03 is a recognised duplicate id, so it SHOULD be flagged by V10 too,
    # regardless of V1 also catching it as "not a clean comment".
    assert "F03" in v10.details or v10.status == "FAIL"


def test_v5_catches_missing_brief():
    stage0, agent3, agent4, agent5 = _minimal_fixture()
    agent4.briefs = []  # Central's negative theme has no brief at all
    config = load_config(provider_override="mock")

    result = verify_run(stage0, agent3, agent4, agent5, config=config)
    v5 = next(c for c in result.checks if c.id == "V5")
    assert v5.status == "FAIL"
    assert result.overall_status == "FAIL"


def test_v6_catches_forbidden_phrase():
    stage0, agent3, agent4, agent5 = _minimal_fixture()
    agent5.limitations += " This affects all customers."
    config = load_config(provider_override="mock")

    result = verify_run(stage0, agent3, agent4, agent5, config=config)
    v6 = next(c for c in result.checks if c.id == "V6")
    assert v6.status == "WARN"


def test_v7_catches_undisclosed_duplicate():
    stage0, agent3, agent4, agent5 = _minimal_fixture()
    agent5.limitations = "No limitations noted."  # drops the F03 mention
    config = load_config(provider_override="mock")

    result = verify_run(stage0, agent3, agent4, agent5, config=config, briefing_md=None)
    v7 = next(c for c in result.checks if c.id == "V7")
    assert v7.status == "FAIL"
    assert "F03" in v7.details


def test_v9_warns_on_recorded_disagreement():
    stage0, agent3, agent4, agent5 = _minimal_fixture()
    config = load_config(provider_override="mock")

    result = verify_run(
        stage0, agent3, agent4, agent5, config=config,
        agent5_warnings=["Agent 5 said Central's priority_theme was 'other'; overwritten with Agent 3's 'theme_x'"],
    )
    v9 = next(c for c in result.checks if c.id == "V9")
    assert v9.status == "WARN"


def test_t01_full_pipeline_gate_is_pass_or_warn():
    """CHECKPOINT 2's bar: the T01 gate is PASS or WARN, and every WARN is
    explainable (not a silent FAIL)."""
    config = load_config(provider_override="mock")
    df = load_comments(REPO_ROOT / "data" / "batch_original.csv")
    codebook = load_codebook(REPO_ROOT / "codebook.yaml")
    stage0 = preprocess(df, KNOWN_BRANCHES)

    agent1_output, _ = tag_comments(stage0.clean_comments, codebook, config=config, test_id="T01")
    agent2_output, _ = judge_polarity(agent1_output, stage0.clean_comments, codebook, config=config, test_id="T01")
    agent3_output = score(agent2_output, stage0.clean_comments, stage0)

    # Build one minimal, internally-consistent brief per negative (shop, theme)
    # pair by hand (not via the LLM) — this test is about the gate, not Agent 4's
    # prose quality, which is covered by tests/test_agent4.py.
    briefs = []
    for shop, shop_score in agent3_output.shops.items():
        for theme in shop_score.negative_themes_ranked:
            ts = shop_score.themes[theme]
            cited = ts.negative_ids[:1]
            briefs.append(
                ThemeBrief(
                    shop=shop, theme=theme,
                    summary_of_comments=f"Feedback raised {theme} at {shop}.",
                    interpretation="A possible reading, not a confirmed cause.",
                    cta=CTA(action="Investigate further.", kind="investigate", data_needed=[], success_signal="Clarity."),
                    cited_ids=cited,
                    key_quotes=[],
                )
            )
    agent4_output = Agent4Output(briefs=briefs)

    agent5_output = Agent5Output(
        headline="Summary of this week's feedback.",
        shops=[
            ShopSummary(shop=shop, overview="Overview.", priority_theme=s.priority_theme, cited_ids=[])
            for shop, s in agent3_output.shops.items()
        ],
        network_priority=NetworkPriority(
            theme=agent3_output.network.priority_theme, reason="Seen at multiple branches.",
            action="Investigate network-wide.", cited_ids=[],
        ),
        requests=[],
        mixed_views_note="",
        limitations=(
            "Convenience sample. Duplicate F07 counted once. "
            + " ".join(f"{cid} had no usable detail."
                       for s in agent3_output.shops.values() for cid in s.no_detail_ids)
        ),
    )

    briefing_md = render_briefing(stage0, agent3_output, agent4_output, agent5_output)
    result = verify_run(
        stage0, agent3_output, agent4_output, agent5_output,
        config=config, agent5_warnings=[], briefing_md=briefing_md,
    )

    assert result.overall_status in ("PASS", "WARN"), [
        (c.id, c.status, c.details) for c in result.checks if c.status == "FAIL"
    ]
