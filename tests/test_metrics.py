from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from juniper.baseline import run_baseline
from juniper.config import load_config
from juniper.io_utils import load_codebook, load_comments
from juniper.metrics import load_answer_key, score_baseline, score_prototype
from juniper.pipeline import run_pipeline

REPO_ROOT = Path(__file__).resolve().parent.parent
ANSWER_KEY_PATH = REPO_ROOT / "answer_key.json"
BATCH_CSV = REPO_ROOT / "data" / "batch_original.csv"


def test_load_answer_key_resolves_all_twelve():
    ak = load_answer_key(ANSWER_KEY_PATH)
    assert set(ak.keys()) == {f"T{i:02d}" for i in range(1, 13)}


def test_extends_inherits_unset_fields_and_keeps_overrides():
    ak = load_answer_key(ANSWER_KEY_PATH)
    t01, t03 = ak["T01"], ak["T03"]

    # T03 extends T01 and only overrides comments_total/duplicates.
    assert t03.visits_total == t01.visits_total
    assert t03.visits_by_branch == t01.visits_by_branch
    assert t03.comments_total == 13  # its own override
    assert t03.duplicates == {"F07": "F03", "F13": "F06"}  # its own override


def test_add_required_tags_appends_to_inherited_required_tags():
    ak = load_answer_key(ANSWER_KEY_PATH)
    t01, t05 = ak["T01"], ak["T05"]

    assert len(t05.required_tags) == len(t01.required_tags) + 1
    assert ["F13", "price_accuracy", "negative"] in t05.required_tags
    # everything T01 had is still there too
    assert all(tag in t05.required_tags for tag in t01.required_tags)


def test_circular_extends_raises():
    from juniper.metrics import _merge_entry

    raw_all = {"A": {"extends": "B"}, "B": {"extends": "A"}}
    with pytest.raises(ValueError, match="circular"):
        _merge_entry("A", raw_all)


@pytest.fixture
def cleanup_runs():
    created: list[Path] = []
    yield created
    for d in created:
        shutil.rmtree(d, ignore_errors=True)


def test_t01_prototype_scores_perfectly_against_the_real_answer_key(cleanup_runs):
    """The T01 mock fixtures were hand-built to match the real answer key
    exactly — this is as much a consistency check on those fixtures as it is
    on score_prototype()."""
    config = load_config(provider_override="mock")
    ak = load_answer_key(ANSWER_KEY_PATH)

    result = run_pipeline(BATCH_CSV, label="metrics_t01", config=config, test_id="T01")
    cleanup_runs.append(result.run_dir)
    assert result.status == "OK"

    m = score_prototype(
        ak["T01"],
        stage0=result.stage0, agent1=result.agent1, agent2=result.agent2,
        agent3=result.agent3, agent4=result.agent4, gate=result.verification,
        call_logs=result.call_logs,
    )

    assert m.dedupe_ok is True
    assert m.visit_count_ok is True
    assert m.theme_recall == 1.0
    assert m.polarity_accuracy == 1.0
    assert m.count_accuracy == 1.0
    assert m.negative_coverage == 1.0
    assert m.priority_ok is True
    assert m.factual_support == 1.0
    assert m.special_ok is True
    assert m.task_success() is True


def test_t01_baseline_scores_against_the_real_answer_key():
    config = load_config(provider_override="mock")
    ak = load_answer_key(ANSWER_KEY_PATH)
    df = load_comments(BATCH_CSV)
    codebook = load_codebook(REPO_ROOT / "codebook.yaml")

    baseline_output, log = run_baseline(df, codebook, config=config, test_id="T01")
    call_logs = [log] if log else []

    m = score_baseline(ak["T01"], raw_df=df, baseline=baseline_output, call_logs=call_logs)

    # priority_ok is explicitly n/a for the baseline (BaselineOutput has no
    # network-priority concept) per the spec's metric table.
    assert m.priority_ok is None
    # a plausible score, not necessarily perfect — the hand-built baseline
    # fixture only covers 3 of T01's 8 themes.
    assert m.theme_recall is not None and 0.0 <= m.theme_recall <= 1.0
    assert m.llm_calls == 1


def test_missing_answer_key_entry_degrades_to_all_none_not_a_crash():
    config = load_config(provider_override="mock")
    m = score_prototype(
        None, stage0=None, agent1=None, agent2=None, agent3=None, agent4=None,
        gate=None, call_logs=[],
    )
    assert m.dedupe_ok is None
    assert m.task_success() is None


def test_zero_llm_calls_special_check():
    from juniper.metrics import _check_special_prototype
    from juniper.stage0_preprocess import preprocess

    empty_stage0 = preprocess(load_comments(BATCH_CSV).iloc[0:0], ["Central", "Riverside", "Station"])

    assert _check_special_prototype("zero_llm_calls", stage0=empty_stage0, agent3=None, agent4=None, call_logs=[]) is True
    assert _check_special_prototype("zero_llm_calls", stage0=empty_stage0, agent3=None, agent4=None, call_logs=[object()]) is False  # type: ignore[list-item]
