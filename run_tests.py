#!/usr/bin/env python3
"""CLI: run every data/tests/T*.csv through the prototype (full pipeline) and
the baseline, score both against answer_key.json, and write
runs/<ts>_<label>/results.csv and results.md.

    python run_tests.py --label v1
    python run_tests.py --label v1 --only T05
    python run_tests.py --label v1 --skip-baseline
    python run_tests.py --label v1 --provider mock   # default: config.yaml's provider
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from juniper.baseline import run_baseline
from juniper.checked_call import SemanticValidationError
from juniper.config import Config, load_config
from juniper.io_utils import load_codebook, load_comments
from juniper.llm import ProviderUnavailable, StructuredCallFailed
from juniper.metrics import AnswerKeyEntry, Metrics, load_answer_key, score_baseline, score_prototype
from juniper.pipeline import RUNS_DIR, run_pipeline

REPO_ROOT = Path(__file__).resolve().parent
DATA_TESTS_DIR = REPO_ROOT / "data" / "tests"
ANSWER_KEY_PATH = REPO_ROOT / "answer_key.json"
CODEBOOK_PATH = REPO_ROOT / "codebook.yaml"

_TEST_ID_RE = re.compile(r"^(T\d+)", re.IGNORECASE)


def _test_id_from_path(path: Path) -> Optional[str]:
    match = _TEST_ID_RE.match(path.stem)
    return match.group(1).upper() if match else None


def _fmt(value) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "PASS" if value else "FAIL"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _cost_cell(cost_eur: float, cost_eur_if_paid_est: Optional[float]) -> str:
    # Gemini free tier + mock are always €0; this is purely a display choice —
    # see config.yaml's paid_price_per_mtok_eur and docs/decisions.md.
    label = "€0 (free tier)" if cost_eur == 0.0 else f"€{cost_eur:.4f}"
    if cost_eur_if_paid_est:
        label += f" (paid tier est. €{cost_eur_if_paid_est:.4f})"
    return label


def run_one_test(
    csv_path: Path,
    test_id: str,
    answer_key: dict[str, AnswerKeyEntry],
    *,
    config: Config,
    label: str,
    skip_baseline: bool,
    codebook,
) -> dict:
    entry = answer_key.get(test_id)

    result = run_pipeline(csv_path, label=f"{label}_{test_id}", config=config, test_id=test_id)
    gate_status = result.verification.overall_status if result.verification else "n/a"
    proto_metrics = score_prototype(
        entry, stage0=result.stage0, agent1=result.agent1, agent2=result.agent2,
        agent3=result.agent3, agent4=result.agent4, gate=result.verification,
        call_logs=result.call_logs,
    )
    proto_success = proto_metrics.task_success()
    if proto_success is True and gate_status == "FAIL":
        proto_success = False  # task success also requires gate status not FAIL

    base_metrics = Metrics()
    base_success: Optional[bool] = None
    base_error: Optional[str] = None
    if not skip_baseline:
        try:
            df = load_comments(csv_path)
            baseline_output, base_log = run_baseline(df, codebook, config=config, test_id=test_id)
            base_call_logs = [base_log] if base_log else []
            base_metrics = score_baseline(entry, raw_df=df, baseline=baseline_output, call_logs=base_call_logs)
            base_success = base_metrics.task_success()
        except (FileNotFoundError, StructuredCallFailed, SemanticValidationError, ProviderUnavailable) as exc:
            # provider: mock with no baseline fixture for this test_id (fixtures/mock/
            # is scoped to "T01 at least"), or a real-provider failure — either way,
            # one test's baseline failing shouldn't crash the whole sweep.
            base_error = str(exc)

    return {
        "test": test_id,
        "condition": entry.condition if entry else "n/a",
        "description": entry.description if entry else "(no answer_key.json entry)",
        "gate": gate_status,
        "prototype_success": proto_success,
        "baseline_success": base_success,
        "prototype": proto_metrics,
        "baseline": base_metrics,
        "run_dir": result.run_dir,
        "pipeline_status": result.status,
        "pipeline_error": result.error,
        "baseline_error": base_error,
    }


def write_results(rows: list[dict], out_dir: Path) -> None:
    csv_path = out_dir / "results.csv"
    with csv_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "test", "condition", "pipeline_status", "gate",
            "prototype_success", "baseline_success",
            "prototype_latency_s", "prototype_cost_eur", "prototype_calls",
            "baseline_latency_s", "baseline_cost_eur", "baseline_calls",
        ])
        for r in rows:
            p, b = r["prototype"], r["baseline"]
            writer.writerow([
                r["test"], r["condition"], r["pipeline_status"], r["gate"],
                _fmt(r["prototype_success"]), _fmt(r["baseline_success"]),
                round(p.latency_s, 2), round(p.cost_eur_est, 4), p.llm_calls,
                round(b.latency_s, 2), round(b.cost_eur_est, 4), b.llm_calls,
            ])

    md_path = out_dir / "results.md"
    lines = ["# Test results", "", "| Test | Condition | Expected behaviour | Baseline | Prototype | Pass/Fail | Latency (proto) | Cost (proto) |"]
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in rows:
        p = r["prototype"]
        pass_fail = "✅" if r["prototype_success"] else ("❌" if r["prototype_success"] is False else "n/a")
        if r["pipeline_status"] != "OK":
            pass_fail = f"❌ ({r['pipeline_status']})"
        baseline_cell = _fmt(r["baseline_success"])
        prototype_cell = f"{_fmt(r['prototype_success'])} (gate: {r['gate']})"
        lines.append(
            f"| {r['test']} | {r['condition']} | {r['description']} | {baseline_cell} | "
            f"{prototype_cell} | {pass_fail} | {p.latency_s:.2f}s | {_cost_cell(p.cost_eur_est, None)} |"
        )

    n = len(rows)
    proto_pass = sum(1 for r in rows if r["prototype_success"] is True)
    base_pass = sum(1 for r in rows if r["baseline_success"] is True)
    total_proto_latency = sum(r["prototype"].latency_s for r in rows)
    total_base_latency = sum(r["baseline"].latency_s for r in rows)
    total_proto_cost = sum(r["prototype"].cost_eur_est for r in rows)
    total_base_cost = sum(r["baseline"].cost_eur_est for r in rows)

    lines += [
        "",
        "## Summary",
        "",
        f"- Task success: prototype {proto_pass}/{n}, baseline {base_pass}/{n}",
        f"- Total latency: prototype {total_proto_latency:.1f}s, baseline {total_base_latency:.1f}s "
        f"(mean {total_proto_latency/n:.1f}s vs {total_base_latency/n:.1f}s)" if n else "",
        f"- Total cost: prototype {_cost_cell(total_proto_cost, None)}, baseline {_cost_cell(total_base_cost, None)}",
    ]
    md_path.write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--label", required=True)
    parser.add_argument("--provider", choices=["gemini", "mock"], default=None)
    parser.add_argument("--only", default=None, help="Run a single test id, e.g. T05")
    parser.add_argument("--skip-baseline", action="store_true")
    args = parser.parse_args()

    config = load_config(provider_override=args.provider)
    answer_key = load_answer_key(ANSWER_KEY_PATH) if ANSWER_KEY_PATH.exists() else {}
    codebook = load_codebook(CODEBOOK_PATH)

    test_csvs = sorted(DATA_TESTS_DIR.glob("T*.csv"))
    if args.only:
        test_csvs = [p for p in test_csvs if _test_id_from_path(p) == args.only.upper()]
        if not test_csvs:
            print(f"No test CSV found for --only {args.only}", file=sys.stderr)
            return 2

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = RUNS_DIR / f"{ts}_{args.label}"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for csv_path in test_csvs:
        test_id = _test_id_from_path(csv_path)
        if test_id is None:
            continue
        print(f"Running {test_id} ({csv_path.name})...")
        row = run_one_test(
            csv_path, test_id, answer_key, config=config, label=args.label,
            skip_baseline=args.skip_baseline, codebook=codebook,
        )
        rows.append(row)
        print(f"  pipeline={row['pipeline_status']} gate={row['gate']} "
              f"prototype={_fmt(row['prototype_success'])} baseline={_fmt(row['baseline_success'])}")

    write_results(rows, out_dir)
    print(f"\nWrote {out_dir / 'results.csv'} and {out_dir / 'results.md'}")

    n = len(rows)
    proto_pass = sum(1 for r in rows if r["prototype_success"] is True)
    print(f"\nTask success: prototype {proto_pass}/{n}" + (f", baseline {sum(1 for r in rows if r['baseline_success'] is True)}/{n}" if not args.skip_baseline else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
