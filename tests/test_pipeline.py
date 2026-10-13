from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from juniper.config import load_config
from juniper.io_utils import load_comments
from juniper.pipeline import run_pipeline

REPO_ROOT = Path(__file__).resolve().parent.parent
BATCH_CSV = REPO_ROOT / "data" / "batch_original.csv"


@pytest.fixture
def cleanup_runs():
    """Tracks run_dirs created during a test and removes them afterward, so
    tests don't litter runs/ (which is otherwise gitignored, but still clutters
    a local checkout across repeated test runs)."""
    created: list[Path] = []
    yield created
    for d in created:
        shutil.rmtree(d, ignore_errors=True)


def test_t01_full_mock_run_is_ok_with_pass_or_warn_gate(cleanup_runs):
    config = load_config(provider_override="mock")

    result = run_pipeline(BATCH_CSV, label="test_full", config=config, test_id="T01")
    cleanup_runs.append(result.run_dir)

    assert result.status == "OK", result.error
    assert result.verification is not None
    assert result.verification.overall_status in ("PASS", "WARN")
    assert "waiting_time" in result.briefing_md or result.briefing_md  # non-empty, sanity
    assert (result.run_dir / "stage0_preprocess.json").exists()
    assert (result.run_dir / "agent1_tagger.json").exists()
    assert (result.run_dir / "agent2_polarity.json").exists()
    assert (result.run_dir / "agent3_scores.json").exists()
    assert (result.run_dir / "agent4_briefs.json").exists()
    assert (result.run_dir / "agent5_final.json").exists()
    assert (result.run_dir / "verification.json").exists()
    assert (result.run_dir / "briefing.md").exists()
    assert (result.run_dir / "call_log.json").exists()
    assert (result.run_dir / "config_snapshot.yaml").exists()


def test_until_stage_stops_early(cleanup_runs):
    config = load_config(provider_override="mock")

    result = run_pipeline(BATCH_CSV, label="test_until", config=config, test_id="T01", until="agent2")
    cleanup_runs.append(result.run_dir)

    assert result.agent1 is not None
    assert result.agent2 is not None
    assert result.agent3 is None
    assert result.agent4 is None
    assert result.agent5 is None
    assert result.verification is None
    assert not (result.run_dir / "agent3_scores.json").exists()


def test_from_stage_reuses_earlier_run(cleanup_runs):
    config = load_config(provider_override="mock")

    first = run_pipeline(BATCH_CSV, label="test_first", config=config, test_id="T01")
    cleanup_runs.append(first.run_dir)
    assert first.status == "OK"

    second = run_pipeline(
        BATCH_CSV, label="test_second", config=config, test_id="T01",
        from_stage="agent4", reuse_run_dir=first.run_dir,
    )
    cleanup_runs.append(second.run_dir)

    assert second.status == "OK"
    # Reused stages should be byte-identical to the first run's saved JSON.
    assert second.agent1.model_dump() == first.agent1.model_dump()
    assert second.agent2.model_dump() == first.agent2.model_dump()
    assert second.agent3.model_dump() == first.agent3.model_dump()
    # Agent 1/2 calls shouldn't appear in the second run's own call log (reused,
    # not recomputed) — only Agent 4/5's calls should.
    second_call_agents = {log.agent for log in second.call_logs}
    assert "agent1_tagger" not in second_call_agents
    assert "agent2_polarity" not in second_call_agents


def test_zero_visits_short_circuits_with_no_calls(cleanup_runs, tmp_path):
    empty_csv = tmp_path / "empty.csv"
    empty_csv.write_text("comment_id,visit_id,branch,comment\n")
    config = load_config(provider_override="mock")

    result = run_pipeline(empty_csv, label="test_empty", config=config)
    cleanup_runs.append(result.run_dir)

    assert result.status == "OK"
    assert result.call_logs == []
    assert "No feedback received this week." in result.briefing_md
    assert result.agent1 is None
