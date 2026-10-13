from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from juniper.io_utils import MissingColumnError, load_comments
from juniper.stage0_preprocess import preprocess

KNOWN_BRANCHES = ["Central", "Riverside", "Station"]
REPO_ROOT = Path(__file__).resolve().parent.parent


def _df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["comment_id", "visit_id", "branch", "comment"])


def test_original_batch_counts():
    df = load_comments(REPO_ROOT / "data" / "batch_original.csv")
    result = preprocess(df, KNOWN_BRANCHES)

    assert result.comments_total == 12
    assert result.visits_total == 11
    assert result.visits_by_branch == {"Central": 5, "Riverside": 4, "Station": 2}

    dup_ids = {d.comment_id: d.duplicate_of for d in result.duplicates}
    assert dup_ids == {"F07": "F03"}
    assert result.duplicates[0].text_differs is False

    assert result.possible_text_duplicates == []
    assert result.unknown_branches == []

    clean_ids = [c.comment_id for c in result.clean_comments]
    assert "F07" not in clean_ids
    assert len(clean_ids) == 11


def test_empty_csv_short_circuits():
    df = _df([])
    result = preprocess(df, KNOWN_BRANCHES)

    assert result.comments_total == 0
    assert result.visits_total == 0
    assert result.clean_comments == []
    assert result.visits_by_branch == {}


def test_missing_column_raises_clear_error():
    bad = REPO_ROOT / "tests" / "_tmp_missing_column.csv"
    bad.write_text("comment_id,visit_id,comment\nF01,V01,Hello\n")
    try:
        with pytest.raises(MissingColumnError, match="branch"):
            load_comments(bad)
    finally:
        bad.unlink()


def test_unknown_branch_is_kept_and_flagged():
    df = _df(
        [
            {"comment_id": "F01", "visit_id": "V01", "branch": "Airport", "comment": "Nice coffee."},
        ]
    )
    result = preprocess(df, KNOWN_BRANCHES)

    assert result.unknown_branches == ["Airport"]
    assert any("Airport" in w for w in result.warnings)
    # still kept as a visit, with its own (unknown) branch denominator
    assert result.visits_total == 1
    assert result.visits_by_branch == {"Airport": 1}


def test_same_visit_different_text_flags_text_differs():
    df = _df(
        [
            {"comment_id": "F01", "visit_id": "V01", "branch": "Central", "comment": "Great coffee."},
            {"comment_id": "F02", "visit_id": "V01", "branch": "Central", "comment": "Slow service though."},
        ]
    )
    result = preprocess(df, KNOWN_BRANCHES)

    assert result.visits_total == 1
    assert len(result.duplicates) == 1
    assert result.duplicates[0].comment_id == "F02"
    assert result.duplicates[0].duplicate_of == "F01"
    assert result.duplicates[0].text_differs is True


def test_same_text_different_visits_flags_possible_duplicate():
    df = _df(
        [
            {"comment_id": "F01", "visit_id": "V01", "branch": "Central", "comment": "Lovely coffee."},
            {"comment_id": "F02", "visit_id": "V02", "branch": "Central", "comment": "lovely   coffee."},
        ]
    )
    result = preprocess(df, KNOWN_BRANCHES)

    # both are real, separate visits -> both kept
    assert result.visits_total == 2
    assert result.duplicates == []
    assert len(result.possible_text_duplicates) == 1
    assert result.possible_text_duplicates[0].comment_id == "F02"
    assert result.possible_text_duplicates[0].duplicate_of == "F01"


def test_empty_comment_text_kept_with_warning():
    df = _df(
        [
            {"comment_id": "F11", "visit_id": "V11", "branch": "Central", "comment": "   "},
        ]
    )
    result = preprocess(df, KNOWN_BRANCHES)

    assert result.visits_total == 1
    assert any("F11" in w and "empty" in w.lower() for w in result.warnings)
