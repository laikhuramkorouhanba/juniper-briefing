from __future__ import annotations

from pathlib import Path

from juniper.agent1_tagger import _validate_items, tag_comments
from juniper.config import load_config
from juniper.io_utils import load_codebook, load_comments
from juniper.models import Agent1Item, Comment, ThemeTag
from juniper.stage0_preprocess import preprocess

REPO_ROOT = Path(__file__).resolve().parent.parent
KNOWN_BRANCHES = ["Central", "Riverside", "Station"]


def _comment(comment_id="F01", text="Lovely coffee, but I queued for 15 minutes."):
    return Comment(comment_id=comment_id, visit_id="V01", branch="Central", text=text)


def test_t01_mock_passes_all_checks():
    config = load_config(provider_override="mock")
    df = load_comments(REPO_ROOT / "data" / "batch_original.csv")
    codebook = load_codebook(REPO_ROOT / "codebook.yaml")
    stage0 = preprocess(df, KNOWN_BRANCHES)

    output, call_logs = tag_comments(stage0.clean_comments, codebook, config=config, test_id="T01")

    assert {item.comment_id for item in output.items} == {c.comment_id for c in stage0.clean_comments}
    assert all(log.ok for log in call_logs)
    # mock mode always collapses to one whole-batch call, regardless of the
    # configured batch_mode — a canned fixture has nothing per-comment to simulate.
    assert len(call_logs) == 1


def test_validate_items_catches_fake_quote():
    comment = _comment()
    expected = {comment.comment_id: comment}
    items = [
        Agent1Item(
            comment_id=comment.comment_id,
            usable=True,
            themes=[ThemeTag(theme="coffee_quality", quote="This quote is not in the comment")],
        )
    ]

    errors = _validate_items(items, expected, theme_names={"coffee_quality", "waiting_time"})

    assert any("not an exact substring" in e for e in errors)


def test_validate_items_catches_unknown_theme():
    comment = _comment()
    expected = {comment.comment_id: comment}
    items = [
        Agent1Item(
            comment_id=comment.comment_id,
            usable=True,
            themes=[ThemeTag(theme="not_a_real_theme", quote="Lovely coffee")],
        )
    ]

    errors = _validate_items(items, expected, theme_names={"coffee_quality", "waiting_time"})

    assert any("unknown theme" in e for e in errors)


def test_validate_items_catches_missing_comment():
    c1 = _comment("F01")
    c2 = _comment("F02", "The team was friendly.")
    expected = {c1.comment_id: c1, c2.comment_id: c2}
    # Only F01 returned — F02 is missing.
    items = [Agent1Item(comment_id="F01", usable=True, themes=[])]

    errors = _validate_items(items, expected, theme_names={"coffee_quality"})

    assert any("missing comment_id" in e and "F02" in e for e in errors)


def test_validate_items_catches_unusable_with_themes():
    comment = _comment()
    expected = {comment.comment_id: comment}
    items = [
        Agent1Item(
            comment_id=comment.comment_id,
            usable=False,
            themes=[ThemeTag(theme="coffee_quality", quote="Lovely coffee")],
        )
    ]

    errors = _validate_items(items, expected, theme_names={"coffee_quality"})

    assert any("usable=false but themes is not empty" in e for e in errors)
