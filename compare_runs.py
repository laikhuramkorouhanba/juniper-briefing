#!/usr/bin/env python3
"""CLI: show the delta for every metric between two run_tests.py runs.

    python compare_runs.py runs/<v1_label> runs/<v2_label>

Each argument is a run folder produced by run_tests.py (containing results.csv).
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path


def _load_results(run_dir: Path) -> dict[str, dict]:
    path = run_dir / "results.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found — is this a run_tests.py output folder?")
    with path.open(newline="") as f:
        return {row["test"]: row for row in csv.DictReader(f)}


_NUMERIC_FIELDS = [
    "prototype_latency_s", "prototype_cost_eur", "prototype_calls",
    "baseline_latency_s", "baseline_cost_eur", "baseline_calls",
]


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2

    dir_a, dir_b = Path(sys.argv[1]), Path(sys.argv[2])
    results_a = _load_results(dir_a)
    results_b = _load_results(dir_b)

    all_tests = sorted(set(results_a.keys()) | set(results_b.keys()))
    print(f"Comparing {dir_a.name} -> {dir_b.name}\n")

    for test_id in all_tests:
        a, b = results_a.get(test_id), results_b.get(test_id)
        if a is None:
            print(f"{test_id}: new in {dir_b.name}")
            continue
        if b is None:
            print(f"{test_id}: missing in {dir_b.name} (was present in {dir_a.name})")
            continue

        print(f"{test_id}:")
        if a["prototype_success"] != b["prototype_success"]:
            print(f"  prototype_success: {a['prototype_success']} -> {b['prototype_success']}")
        if a["gate"] != b["gate"]:
            print(f"  gate: {a['gate']} -> {b['gate']}")
        for field in _NUMERIC_FIELDS:
            try:
                va, vb = float(a[field]), float(b[field])
            except (ValueError, TypeError):
                continue
            if va != vb:
                delta = vb - va
                sign = "+" if delta >= 0 else ""
                print(f"  {field}: {va:g} -> {vb:g} ({sign}{delta:g})")

    n = len(all_tests)
    proto_pass_a = sum(1 for r in results_a.values() if r["prototype_success"] == "PASS")
    proto_pass_b = sum(1 for r in results_b.values() if r["prototype_success"] == "PASS")
    print(f"\nTask success: {proto_pass_a}/{len(results_a)} -> {proto_pass_b}/{len(results_b)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
