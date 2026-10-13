"""Stage 0 · Preprocess (code, no LLM).

Deduplicates by visit_id, validates branches, counts visits with a clear
denominator. See docs/contracts.md Section 5.4 for the exact rules this
implements.
"""

from __future__ import annotations

import pandas as pd

from juniper.models import Comment, DuplicateRecord, PossibleTextDuplicate, Stage0Output


def _normalize(text: str) -> str:
    """Whitespace- and case-insensitive normalisation, used only for duplicate
    detection. The original text is always kept verbatim in clean_comments."""
    return " ".join(text.strip().split()).lower()


def preprocess(df: pd.DataFrame, known_branches: list[str]) -> Stage0Output:
    """Run Stage 0 over a loaded comments DataFrame (see io_utils.load_comments).

    Rules (docs/contracts.md 5.4):
    - Same visit_id: keep the first comment, mark later ones as duplicates.
    - Same normalised text, different visit_id: keep both, flag as a possible
      text duplicate.
    - Branch not in known_branches: keep the comment, record the branch as unknown.
    - Empty/blank comment text: keep as a visit (ends up as "no usable detail"),
      with a warning.
    - An empty batch (zero rows) returns zero counts so the pipeline can
      short-circuit; this is not an error.
    """
    comments_total = len(df)

    if comments_total == 0:
        return Stage0Output(
            comments_total=0,
            visits_total=0,
            clean_comments=[],
            duplicates=[],
            possible_text_duplicates=[],
            visits_by_branch={},
            unknown_branches=[],
            warnings=[],
        )

    clean_comments: list[Comment] = []
    duplicates: list[DuplicateRecord] = []
    possible_text_duplicates: list[PossibleTextDuplicate] = []
    visits_by_branch: dict[str, int] = {}
    unknown_branches: list[str] = []
    warnings: list[str] = []

    seen_visits: dict[str, tuple[str, str]] = {}  # visit_id -> (comment_id, normalized_text)
    seen_text: dict[str, tuple[str, str]] = {}  # normalized_text -> (comment_id, visit_id)

    for row in df.itertuples(index=False):
        comment_id = row.comment_id
        visit_id = row.visit_id
        branch = row.branch
        text = row.comment
        normalized = _normalize(text)

        if branch not in known_branches:
            if branch not in unknown_branches:
                unknown_branches.append(branch)
            warnings.append(f"Unknown branch '{branch}' for comment {comment_id}")

        if not text.strip():
            warnings.append(
                f"Comment {comment_id} (visit {visit_id}) has empty text; "
                "treated as no usable detail"
            )

        if visit_id in seen_visits:
            first_comment_id, first_normalized = seen_visits[visit_id]
            duplicates.append(
                DuplicateRecord(
                    comment_id=comment_id,
                    duplicate_of=first_comment_id,
                    visit_id=visit_id,
                    text_differs=normalized != first_normalized,
                )
            )
            continue

        seen_visits[visit_id] = (comment_id, normalized)

        if normalized and normalized in seen_text:
            other_comment_id, other_visit_id = seen_text[normalized]
            possible_text_duplicates.append(
                PossibleTextDuplicate(
                    comment_id=comment_id,
                    visit_id=visit_id,
                    duplicate_of=other_comment_id,
                    duplicate_of_visit_id=other_visit_id,
                )
            )
        elif normalized:
            seen_text[normalized] = (comment_id, visit_id)

        clean_comments.append(
            Comment(comment_id=comment_id, visit_id=visit_id, branch=branch, text=text)
        )
        visits_by_branch[branch] = visits_by_branch.get(branch, 0) + 1

    return Stage0Output(
        comments_total=comments_total,
        visits_total=len(clean_comments),
        clean_comments=clean_comments,
        duplicates=duplicates,
        possible_text_duplicates=possible_text_duplicates,
        visits_by_branch=visits_by_branch,
        unknown_branches=unknown_branches,
        warnings=warnings,
    )
