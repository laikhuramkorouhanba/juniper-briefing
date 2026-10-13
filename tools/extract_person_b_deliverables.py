#!/usr/bin/env python3
"""
Extract Person B's data deliverables verbatim out of BUILD_SPEC_B.md.

Everything a deliverable needs to be exact is already written inside the spec:
  - the full answer key JSON (section 7.2)
  - every test CSV (section 7.3)

Hand-typing those would risk transcription errors, and Person B's own fairness
rule says the answer key must match the tests exactly. So this tool copies each
fenced block straight out of the spec and writes the real deliverable files.
Nothing here invents content; it only relocates what the spec already says.

Usage:  python tools/extract_person_b_deliverables.py <repo_root>
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
from pathlib import Path


def extract_fenced(text: str, fence: str) -> list[str]:
    """Return the body of every ```<fence> block, in order."""
    pattern = re.compile(r"```" + re.escape(fence) + r"\n(.*?)```", re.DOTALL)
    return [m.group(1) for m in pattern.finditer(text)]


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    spec_path = root / "docs" / "BUILD_SPEC_B.md"
    if not spec_path.exists():
        print(f"Spec not found: {spec_path}")
        return 1
    spec = spec_path.read_text(encoding="utf-8")

    # ---- 1. Answer key ------------------------------------------------------
    json_blocks = extract_fenced(spec, "json")
    answer_key: dict | None = None
    for body in json_blocks:
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and {"T01", "T12"}.issubset(data.keys()):
            answer_key = data
            break
    if answer_key is None:
        print("ERROR: could not find the T01..T12 answer key JSON in the spec")
        return 1

    answer_path = root / "answer_key.json"
    answer_path.write_text(
        json.dumps(answer_key, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Wrote {answer_path.relative_to(root)}  ({len(answer_key):d} tests)")

    # ---- 2. Test CSVs -------------------------------------------------------
    csv_blocks = extract_fenced(spec, "csv")
    tests_dir = root / "data" / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)

    written: dict[str, Path] = {}
    for body in csv_blocks:
        rows = list(csv.reader(io.StringIO(body)))
        if not rows:
            continue
        header = rows[0]
        # only the Juniper test batches, recognised by their exact header
        if header[0:4] != ["comment_id", "visit_id", "branch", "comment"]:
            continue
        # find the name marker: the most recent **`NAME.csv`** before this block
        start = spec.find("\n".join(rows[:2])[:40])
        if start == -1:
            continue
        before = spec[:start]
        names = re.findall(r"\*\*`([A-Za-z0-9_]+\.csv)`\*\*", before)
        name = names[-1] if names else ""
        if not name:
            continue
        target = tests_dir / name
        target.write_text(body.strip() + "\n", encoding="utf-8")
        written[name] = target
        print(f"Wrote {target.relative_to(root)}  ({len(rows) - 1:d} comments)")

    print(f"\nTotal test CSVs written: {len(written)}")

    # ---- 3. Self-check: every ID referenced in the answer key is present -----
    ids_in_files: dict[str, tuple[str, str]] = {}   # comment_id -> (branch, theme)
    for name, path in written.items():
        with path.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                ids_in_files[row["comment_id"]] = (row["branch"], row["comment"])

    problems = 0
    for tid, entry in answer_key.items():
        for tag in entry.get("required_tags", []):
            cid, theme, _ = tag
            if cid not in ids_in_files:
                print(f"  [{tid}] required tag references missing comment {cid}")
                problems += 1
            else:
                branch, comment = ids_in_files[cid]
                if theme.startswith(branch.lower()):  # crude sanity, ignore
                    pass
        for dup_src, dup_tgt in entry.get("duplicates", {}).items():
            if dup_src not in ids_in_files or dup_tgt not in ids_in_files:
                print(f"  [{tid}] duplicate maps missing id {dup_src}->{dup_tgt}")
                problems += 1

    if problems:
        print(f"\nValidation found {problems} problem(s) — FIX ME")
        return 1
    print("\nValidation OK: every answer-key ID is present in the test files.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # pragma: no cover
        print(f"FATAL: {exc}")
        sys.exit(1)
