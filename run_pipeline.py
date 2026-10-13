#!/usr/bin/env python3
"""CLI: run the pipeline once on a single CSV.

    python run_pipeline.py data/batch_original.csv --label dev
    python run_pipeline.py data/batch_original.csv --label dev --provider mock --test-id T01
    python run_pipeline.py data/batch_original.csv --label cp1 --until agent2
    python run_pipeline.py data/batch_original.csv --label dev2 --from agent4 --reuse runs/<earlier_run>
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from juniper.config import load_config
from juniper.pipeline import STAGE_ORDER, run_pipeline

_TEST_ID_RE = re.compile(r"^(T\d+)", re.IGNORECASE)


def _guess_test_id(csv_path: Path) -> str | None:
    match = _TEST_ID_RE.match(csv_path.stem)
    return match.group(1) if match else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv_path", type=Path, help="Path to the feedback batch CSV")
    parser.add_argument("--label", required=True, help="Short label for this run, used in runs/<ts>_<label>/")
    parser.add_argument("--provider", choices=["gemini", "mock"], default=None, help="Overrides config.yaml's provider")
    parser.add_argument("--test-id", default=None, help="Mock fixture id (guessed from the filename if omitted)")
    parser.add_argument("--until", choices=STAGE_ORDER, default=None, help="Stop after this stage")
    parser.add_argument("--from", dest="from_stage", choices=STAGE_ORDER, default=None, help="Reuse earlier stages from --reuse")
    parser.add_argument("--reuse", dest="reuse_run_dir", type=Path, default=None, help="Run folder to reuse earlier stages from (with --from)")
    args = parser.parse_args()

    config = load_config(provider_override=args.provider)
    test_id = args.test_id or (_guess_test_id(args.csv_path) if config.provider == "mock" else None)

    if config.provider == "mock" and test_id is None:
        print("provider: mock needs a --test-id (or a filename starting with T<n>, e.g. T01_...)", file=sys.stderr)
        return 2

    result = run_pipeline(
        args.csv_path,
        label=args.label,
        config=config,
        test_id=test_id,
        from_stage=args.from_stage,
        reuse_run_dir=args.reuse_run_dir,
        until=args.until,
    )

    print(f"provider: {result.provider}")
    print(f"run dir:  {result.run_dir}")
    print(f"status:   {result.status}" + (f" — {result.error}" if result.error else ""))
    if result.verification is not None:
        print(f"gate:     {result.verification.overall_status}")
        for c in result.verification.checks:
            if c.status != "PASS":
                print(f"  {c.id}: {c.status} — {c.details}")
    if result.call_logs:
        total_tokens = sum(l.input_tokens + l.output_tokens for l in result.call_logs)
        print(f"calls:    {len(result.call_logs)} ({total_tokens} tokens, €{sum(l.cost_eur for l in result.call_logs):.2f})")
    if result.briefing_md:
        print()
        print(result.briefing_md)

    return 0 if result.status == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
