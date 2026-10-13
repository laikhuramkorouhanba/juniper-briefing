"""Lightweight smoke tests for run_tests.py's per-test runner — not the full
CLI (argparse/file writing), just that run_one_test() degrades gracefully for
a test with no mock fixtures instead of crashing the whole sweep."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from juniper.config import load_config
from juniper.io_utils import load_codebook
from run_tests import run_one_test

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_TESTS_DIR = REPO_ROOT / "data" / "tests"


@pytest.fixture
def cleanup_runs():
    created: list[Path] = []
    yield created
    for d in created:
        shutil.rmtree(d, ignore_errors=True)


def test_t01_passes_with_real_fixtures(cleanup_runs):
    config = load_config(provider_override="mock")
    codebook = load_codebook(REPO_ROOT / "codebook.yaml")
    from juniper.metrics import load_answer_key

    answer_key = load_answer_key(REPO_ROOT / "answer_key.json")

    row = run_one_test(
        DATA_TESTS_DIR / "T01_original.csv", "T01", answer_key,
        config=config, label="pytest_t01", skip_baseline=True, codebook=codebook,
    )
    cleanup_runs.append(row["run_dir"])

    assert row["pipeline_status"] == "OK"
    assert row["prototype_success"] is True


def test_t03_degrades_gracefully_with_no_mock_fixtures(cleanup_runs):
    """fixtures/mock/ only covers T01 (CLAUDE.md: 'T01 at least') — a test
    beyond that should fail that one test, not crash run_tests.py's sweep."""
    config = load_config(provider_override="mock")
    codebook = load_codebook(REPO_ROOT / "codebook.yaml")
    from juniper.metrics import load_answer_key

    answer_key = load_answer_key(REPO_ROOT / "answer_key.json")

    row = run_one_test(
        DATA_TESTS_DIR / "T03_extra_duplicate.csv", "T03", answer_key,
        config=config, label="pytest_t03", skip_baseline=False, codebook=codebook,
    )
    cleanup_runs.append(row["run_dir"])

    assert row["pipeline_status"] == "FAIL"
    assert row["pipeline_error"] is not None
