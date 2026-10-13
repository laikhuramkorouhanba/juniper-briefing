"""Scores a run against answer_key.json. See docs/BUILD_SPEC_A.md Phase 7 for
the metric table and docs/BUILD_SPEC_B.md Section 7.1 for the answer key format.

Every metric is Optional: when the inputs needed to compute it aren't
available (no answer key entry, that stage didn't run, etc.) it's None,
reported as "n/a" — never silently guessed at or defaulted to a passing value.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd
from pydantic import BaseModel, Field

from juniper.models import (
    Agent1Output,
    Agent2Output,
    Agent3Output,
    Agent4Output,
    BaselineOutput,
    CallLog,
    Stage0Output,
    VerificationResult,
)

# ---------------------------------------------------------------------------
# Answer key
# ---------------------------------------------------------------------------


class AnswerKeyEntry(BaseModel):
    description: str = ""
    condition: str = ""
    comments_total: Optional[int] = None
    visits_total: Optional[int] = None
    visits_by_branch: dict[str, int] = Field(default_factory=dict)
    duplicates: dict[str, str] = Field(default_factory=dict)  # duplicate_id -> kept_id
    possible_text_duplicates: list[list[str]] = Field(default_factory=list)  # [[new_id, existing_id]]
    unknown_branches: list[str] = Field(default_factory=list)
    no_detail: list[str] = Field(default_factory=list)
    required_tags: list[list[str]] = Field(default_factory=list)  # [comment_id, theme, polarity]
    optional_tags: list[list[str]] = Field(default_factory=list)
    expected_counts: dict[str, dict[str, list[int]]] = Field(default_factory=dict)  # shop -> theme -> [n_pos, n_neg]
    negative_briefs_expected: list[list[str]] = Field(default_factory=list)  # [shop, theme]
    mixed_views: list[list[str]] = Field(default_factory=list)
    shop_priorities: dict[str, Optional[str]] = Field(default_factory=dict)
    network_priority: Optional[str] = None
    special: list[str] = Field(default_factory=list)


def _merge_entry(test_id: str, raw_all: dict[str, dict], seen: frozenset[str] = frozenset()) -> dict:
    raw = raw_all[test_id]
    extends = raw.get("extends")
    if not extends:
        return {k: v for k, v in raw.items() if k != "extends"}
    if extends in seen:
        raise ValueError(f"circular 'extends' chain: {test_id} -> {extends}")
    parent = _merge_entry(extends, raw_all, seen | {test_id})
    merged = dict(parent)
    for key, value in raw.items():
        if key in ("extends", "add_required_tags"):
            continue
        merged[key] = value
    if "add_required_tags" in raw:
        merged["required_tags"] = [*parent.get("required_tags", []), *raw["add_required_tags"]]
    return merged


def load_answer_key(path: str | Path) -> dict[str, AnswerKeyEntry]:
    """Resolves every test's `extends` chain, then validates each entry."""
    raw_all = json.loads(Path(path).read_text())
    return {test_id: AnswerKeyEntry.model_validate(_merge_entry(test_id, raw_all)) for test_id in raw_all}


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


@dataclass
class Metrics:
    dedupe_ok: Optional[bool] = None
    visit_count_ok: Optional[bool] = None
    theme_recall: Optional[float] = None
    theme_precision: Optional[float] = None
    polarity_accuracy: Optional[float] = None
    count_accuracy: Optional[float] = None
    negative_coverage: Optional[float] = None
    priority_ok: Optional[bool] = None
    factual_support: Optional[float] = None
    special_ok: Optional[bool] = None
    latency_s: float = 0.0
    cost_eur_est: float = 0.0
    llm_calls: int = 0
    notes: list[str] = field(default_factory=list)  # which special checks failed, etc.

    def task_success(self) -> Optional[bool]:
        """Every hard expectation passes: dedupe_ok, visit_count_ok,
        count_accuracy == 1, negative_coverage == 1, special_ok. (Gate-not-FAIL
        is folded in by the caller, since Metrics doesn't carry the gate
        itself.) None (not False) if any hard metric couldn't be computed at all."""
        hard = [
            self.dedupe_ok,
            self.visit_count_ok,
            None if self.count_accuracy is None else self.count_accuracy == 1,
            None if self.negative_coverage is None else self.negative_coverage == 1,
            self.special_ok,
        ]
        if any(h is None for h in hard):
            return None
        return all(hard)

    def as_dict(self) -> dict:
        d = {
            "dedupe_ok": self.dedupe_ok,
            "visit_count_ok": self.visit_count_ok,
            "theme_recall": self.theme_recall,
            "theme_precision": self.theme_precision,
            "polarity_accuracy": self.polarity_accuracy,
            "count_accuracy": self.count_accuracy,
            "negative_coverage": self.negative_coverage,
            "priority_ok": self.priority_ok,
            "factual_support": self.factual_support,
            "special_ok": self.special_ok,
            "latency_s": round(self.latency_s, 2),
            "cost_eur_est": round(self.cost_eur_est, 4),
            "llm_calls": self.llm_calls,
        }
        return d


def _required_pairs(entry: AnswerKeyEntry) -> dict[tuple[str, str], str]:
    """(comment_id, theme) -> expected polarity, last one wins on a dup key."""
    return {(cid, theme): polarity for cid, theme, polarity in entry.required_tags}


def _allowed_pairs(entry: AnswerKeyEntry) -> set[tuple[str, str, str]]:
    return {tuple(t) for t in (*entry.required_tags, *entry.optional_tags)}


# ---------------------------------------------------------------------------
# Special checks
# ---------------------------------------------------------------------------


def _check_special_prototype(
    tag: str,
    *,
    stage0: Stage0Output,
    agent3: Optional[Agent3Output],
    agent4: Optional[Agent4Output],
    call_logs: list[CallLog],
) -> Optional[bool]:
    if tag == "zero_llm_calls":
        return len(call_logs) == 0
    if tag == "no_negative_briefs":
        if agent4 is not None:
            return len(agent4.briefs) == 0
        # agent4 never ran (e.g. the zero-visits short-circuit): trivially true
        # only when there was genuinely nothing to process, else unknown.
        return True if not stage0.clean_comments else None
    if tag == "network_priority_null":
        if agent3 is not None:
            return agent3.network.priority_theme is None
        return True if not stage0.clean_comments else None
    if tag.startswith("unknown_branch_flagged:"):
        branch = tag.split(":", 1)[1]
        return branch in stage0.unknown_branches
    if tag.startswith("text_differs_flagged:"):
        cid = tag.split(":", 1)[1]
        return any(d.comment_id == cid and d.text_differs for d in stage0.duplicates)
    if tag.startswith("possible_text_duplicate_flagged:"):
        cid = tag.split(":", 1)[1]
        return any(p.comment_id == cid for p in stage0.possible_text_duplicates)
    if tag.startswith("injection_not_followed:"):
        cid = tag.split(":", 1)[1]
        if agent3 is None:
            return None
        return any(cid in s.no_detail_ids for s in agent3.shops.values())
    if tag == "quotes_in_original_language":
        # Best-effort heuristic: can't verify generically without an answer-key
        # pointer to which comment/quote to check, so this one is reported
        # "n/a" (None) rather than guessed at.
        return None
    return None  # unknown tag: n/a, not a silent pass


def _check_special_baseline(tag: str, *, baseline: Optional[BaselineOutput], call_logs: list[CallLog]) -> Optional[bool]:
    if tag == "zero_llm_calls":
        return len(call_logs) == 0
    if tag == "no_negative_briefs":
        return baseline is not None and all(len(s.actions) == 0 for s in baseline.shops)
    # network_priority_null, unknown_branch_flagged, text_differs_flagged,
    # possible_text_duplicate_flagged, injection_not_followed and
    # quotes_in_original_language all depend on structure the baseline schema
    # (docs/contracts.md 5.10) simply doesn't have (no network priority, no
    # duplicate/branch/injection detection of its own) — "n/a", not a pass.
    return None


# ---------------------------------------------------------------------------
# Prototype scoring
# ---------------------------------------------------------------------------


def score_prototype(
    entry: Optional[AnswerKeyEntry],
    *,
    stage0: Stage0Output,
    agent1: Optional[Agent1Output],
    agent2: Optional[Agent2Output],
    agent3: Optional[Agent3Output],
    agent4: Optional[Agent4Output],
    gate: Optional[VerificationResult],
    call_logs: list[CallLog],
) -> Metrics:
    m = Metrics(
        latency_s=sum(c.latency_s for c in call_logs),
        cost_eur_est=sum(c.cost_eur for c in call_logs),
        llm_calls=len(call_logs),
    )

    if entry is None:
        return m

    # dedupe_ok
    got_dupes = {d.comment_id: d.duplicate_of for d in stage0.duplicates}
    m.dedupe_ok = got_dupes == entry.duplicates

    # visit_count_ok
    if entry.visits_total is not None:
        m.visit_count_ok = (
            stage0.visits_total == entry.visits_total
            and stage0.visits_by_branch == entry.visits_by_branch
        )

    # theme_recall / theme_precision / polarity_accuracy (Agent 2)
    if agent2 is not None:
        found_pairs = {
            (item.comment_id, a.theme): a.polarity for item in agent2.items for a in item.assessments
        }
        found_triples = {
            (item.comment_id, a.theme, a.polarity) for item in agent2.items for a in item.assessments
        }
        required = _required_pairs(entry)
        if required:
            found_count = sum(1 for k in required if k in found_pairs)
            m.theme_recall = found_count / len(required)
            matched = [k for k in required if k in found_pairs]
            if matched:
                correct = sum(1 for k in matched if found_pairs[k] == required[k])
                m.polarity_accuracy = correct / len(matched)
        allowed = _allowed_pairs(entry)
        if found_triples:
            matched_triples = sum(1 for t in found_triples if t in allowed)
            m.theme_precision = matched_triples / len(found_triples)

    # count_accuracy (Agent 3). No expected cells (e.g. the zero-visits test) ->
    # vacuously 1.0, same treatment as negative_coverage below.
    if not entry.expected_counts:
        m.count_accuracy = 1.0
    elif agent3 is not None:
        total_cells = 0
        correct_cells = 0
        for shop, themes in entry.expected_counts.items():
            shop_score = agent3.shops.get(shop)
            for theme, (exp_pos, exp_neg) in themes.items():
                total_cells += 1
                ts = shop_score.themes.get(theme) if shop_score else None
                if ts is not None and ts.n_pos == exp_pos and ts.n_neg == exp_neg:
                    correct_cells += 1
        m.count_accuracy = correct_cells / total_cells if total_cells else None

    # negative_coverage (Agent 4)
    if not entry.negative_briefs_expected:
        m.negative_coverage = 1.0
    elif agent4 is not None:
        got_pairs = {(b.shop, b.theme) for b in agent4.briefs}
        expected_pairs = {tuple(p) for p in entry.negative_briefs_expected}
        m.negative_coverage = len(expected_pairs & got_pairs) / len(expected_pairs)

    # priority_ok (Agent 3; prototype only — "n/a" for baseline per the spec table)
    if agent3 is not None:
        m.priority_ok = agent3.network.priority_theme == entry.network_priority

    # factual_support (gate, checks V1-V3 and V10)
    if gate is not None:
        relevant = [c for c in gate.checks if c.id in ("V1", "V2", "V3", "V10")]
        if relevant:
            m.factual_support = sum(1 for c in relevant if c.status == "PASS") / len(relevant)

    # special_ok
    if entry.special:
        results = [
            _check_special_prototype(tag, stage0=stage0, agent3=agent3, agent4=agent4, call_logs=call_logs)
            for tag in entry.special
        ]
        if any(r is None for r in results):
            m.notes.append("one or more special checks are n/a (see entry.special)")
        known = [r for r in results if r is not None]
        m.special_ok = all(known) if known else None
        if known and not all(known):
            failed = [tag for tag, r in zip(entry.special, results) if r is False]
            m.notes.append(f"failed special check(s): {failed}")
    else:
        m.special_ok = True

    return m


# ---------------------------------------------------------------------------
# Baseline scoring
# ---------------------------------------------------------------------------


def score_baseline(
    entry: Optional[AnswerKeyEntry],
    *,
    raw_df: pd.DataFrame,
    baseline: Optional[BaselineOutput],
    call_logs: list[CallLog],
) -> Metrics:
    m = Metrics(
        latency_s=sum(c.latency_s for c in call_logs),
        cost_eur_est=sum(c.cost_eur for c in call_logs),
        llm_calls=len(call_logs),
    )

    if entry is None or baseline is None:
        return m

    all_comment_ids = set(raw_df["comment_id"]) if len(raw_df) else set()
    branch_by_id = {row.comment_id: row.branch for row in raw_df.itertuples(index=False)}

    # dedupe_ok: duplicates_noticed + visits_total, per the spec table
    noticed = set(baseline.duplicates_noticed)
    expected_noticed = set(entry.duplicates.keys())
    m.dedupe_ok = noticed == expected_noticed and (
        entry.visits_total is None or baseline.visits_total == entry.visits_total
    )

    # visit_count_ok: baseline counts (visits_total + per-shop visits)
    if entry.visits_total is not None:
        per_shop_ok = all(
            shop.visits == entry.visits_by_branch.get(shop.shop) for shop in baseline.shops
        ) and {s.shop for s in baseline.shops} == set(entry.visits_by_branch.keys())
        m.visit_count_ok = baseline.visits_total == entry.visits_total and per_shop_ok

    # theme_recall / theme_precision / polarity_accuracy (baseline theme IDs)
    found_pairs: dict[tuple[str, str], str] = {}
    found_triples: set[tuple[str, str, str]] = set()
    for shop in baseline.shops:
        for t in shop.themes:
            for cid in t.positive_ids:
                found_pairs[(cid, t.theme)] = "positive"
                found_triples.add((cid, t.theme, "positive"))
            for cid in t.negative_ids:
                found_pairs[(cid, t.theme)] = "negative"
                found_triples.add((cid, t.theme, "negative"))
    required = _required_pairs(entry)
    if required:
        found_count = sum(1 for k in required if k in found_pairs)
        m.theme_recall = found_count / len(required)
        matched = [k for k in required if k in found_pairs]
        if matched:
            correct = sum(1 for k in matched if found_pairs[k] == required[k])
            m.polarity_accuracy = correct / len(matched)
    allowed = _allowed_pairs(entry)
    if found_triples:
        m.theme_precision = sum(1 for t in found_triples if t in allowed) / len(found_triples)

    # count_accuracy (baseline counts). No expected cells -> vacuously 1.0.
    if not entry.expected_counts:
        m.count_accuracy = 1.0
    else:
        total_cells = 0
        correct_cells = 0
        baseline_counts = {
            shop.shop: {t.theme: (t.n_pos, t.n_neg) for t in shop.themes} for shop in baseline.shops
        }
        for shop, themes in entry.expected_counts.items():
            for theme, (exp_pos, exp_neg) in themes.items():
                total_cells += 1
                got = baseline_counts.get(shop, {}).get(theme)
                if got == (exp_pos, exp_neg):
                    correct_cells += 1
        m.count_accuracy = correct_cells / total_cells if total_cells else None

    # negative_coverage (baseline actions)
    if not entry.negative_briefs_expected:
        m.negative_coverage = 1.0
    else:
        got_pairs = {(shop.shop, a.theme) for shop in baseline.shops for a in shop.actions}
        expected_pairs = {tuple(p) for p in entry.negative_briefs_expected}
        m.negative_coverage = len(expected_pairs & got_pairs) / len(expected_pairs)

    # priority_ok: n/a for baseline (BaselineOutput has no network priority concept)
    m.priority_ok = None

    # factual_support: a reduced V1/V2/V10-style check over the baseline's own
    # cited IDs. No V3 analogue — BaselineThemeCount carries no quotes to check
    # (docs/contracts.md 5.10), so this averages over 3 checks, not 4.
    cited_ids = {cid for (cid, _theme) in found_pairs}
    if cited_ids:
        v1_ok = all(cid in all_comment_ids for cid in cited_ids)
        v2_ok = all(
            branch_by_id.get(cid) == shop.shop
            for shop in baseline.shops
            for t in shop.themes
            for cid in (*t.positive_ids, *t.negative_ids)
        )
        v10_ok = not (cited_ids & set(entry.duplicates.keys()))
        m.factual_support = sum([v1_ok, v2_ok, v10_ok]) / 3

    # special_ok
    if entry.special:
        results = [_check_special_baseline(tag, baseline=baseline, call_logs=call_logs) for tag in entry.special]
        known = [r for r in results if r is not None]
        m.special_ok = all(known) if known else None
    else:
        m.special_ok = True

    return m
