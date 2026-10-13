"""Verification gate (code, not an LLM). See docs/BUILD_SPEC_A.md Phase 6 for the
V1-V10 table this implements. Produces a VerificationResult: a list of per-check
PASS/WARN/FAIL verdicts plus an overall status (the worst of them).

Signature matches what app.py (Phase 8, built in a parallel session) already
calls: verify_run(stage0=..., agent3=..., agent4=..., agent5=..., config=...).
`agent5_warnings` and `briefing_md` are optional extras our own pipeline.py
passes for the checks that need them (V9, V7); without them those two checks
degrade to a WARN/best-effort rather than a hard failure.
"""

from __future__ import annotations

import re
from typing import Optional

from juniper.config import Config
from juniper.models import (
    Agent3Output,
    Agent4Output,
    Agent5Output,
    CheckStatus,
    Stage0Output,
    VerificationCheck,
    VerificationResult,
)
from juniper.text_utils import is_exact_substring

_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\b")
_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\b")

_STATUS_RANK = {"PASS": 0, "WARN": 1, "FAIL": 2}


def _worse(a: CheckStatus, b: CheckStatus) -> CheckStatus:
    return a if _STATUS_RANK[a] >= _STATUS_RANK[b] else b


def _agent4_prose_fields(agent4: Optional[Agent4Output]) -> list[str]:
    if agent4 is None:
        return []
    fields: list[str] = []
    for brief in agent4.briefs:
        fields.extend(
            [brief.summary_of_comments, brief.interpretation, brief.cta.action, brief.cta.success_signal]
        )
        fields.extend(brief.cta.data_needed)
    return fields


def _agent5_prose_fields(agent5: Optional[Agent5Output]) -> list[str]:
    if agent5 is None:
        return []
    fields = [agent5.headline, agent5.network_priority.reason, agent5.network_priority.action]
    fields.extend(s.overview for s in agent5.shops)
    fields.extend(agent5.requests)
    fields.append(agent5.mixed_views_note)
    fields.append(agent5.limitations)
    return fields


def _all_cited_ids(agent4: Optional[Agent4Output], agent5: Optional[Agent5Output]) -> set[str]:
    ids: set[str] = set()
    if agent4 is not None:
        for brief in agent4.briefs:
            ids.update(brief.cited_ids)
            ids.update(kq.comment_id for kq in brief.key_quotes)
    if agent5 is not None:
        for s in agent5.shops:
            ids.update(s.cited_ids)
        ids.update(agent5.network_priority.cited_ids)
    return ids


def _check_v1_v2(
    stage0: Stage0Output, agent4: Optional[Agent4Output], agent5: Optional[Agent5Output]
) -> tuple[VerificationCheck, VerificationCheck]:
    comments_by_id = {c.comment_id: c for c in stage0.clean_comments}

    unknown_ids: set[str] = set()
    wrong_shop: list[str] = []

    if agent4 is not None:
        for brief in agent4.briefs:
            for cid in {*brief.cited_ids, *(kq.comment_id for kq in brief.key_quotes)}:
                comment = comments_by_id.get(cid)
                if comment is None:
                    unknown_ids.add(cid)
                elif comment.branch != brief.shop:
                    wrong_shop.append(f"{cid} cited in Agent 4 brief for {brief.shop} but belongs to {comment.branch}")

    if agent5 is not None:
        for s in agent5.shops:
            for cid in s.cited_ids:
                comment = comments_by_id.get(cid)
                if comment is None:
                    unknown_ids.add(cid)
                elif comment.branch != s.shop:
                    wrong_shop.append(f"{cid} cited in {s.shop}'s section but belongs to {comment.branch}")
        for cid in agent5.network_priority.cited_ids:
            if cid not in comments_by_id:
                unknown_ids.add(cid)

    v1 = VerificationCheck(
        id="V1",
        status="FAIL" if unknown_ids else "PASS",
        details=f"cited ID(s) not in the clean comments: {sorted(unknown_ids)}" if unknown_ids else "ok",
    )
    v2 = VerificationCheck(
        id="V2",
        status="FAIL" if wrong_shop else "PASS",
        details="; ".join(wrong_shop) if wrong_shop else "ok",
    )
    return v1, v2


def _check_v3(stage0: Stage0Output, agent4: Optional[Agent4Output]) -> VerificationCheck:
    comments_by_id = {c.comment_id: c for c in stage0.clean_comments}
    bad: list[str] = []
    if agent4 is not None:
        for brief in agent4.briefs:
            for kq in brief.key_quotes:
                text = comments_by_id.get(kq.comment_id)
                if text is not None and not is_exact_substring(kq.quote, text.text):
                    bad.append(f"{kq.comment_id}: {kq.quote!r} not an exact substring")
    return VerificationCheck(id="V3", status="FAIL" if bad else "PASS", details="; ".join(bad) if bad else "ok")


def _check_v4(
    stage0: Stage0Output, agent3: Agent3Output, agent4: Optional[Agent4Output], agent5: Optional[Agent5Output]
) -> VerificationCheck:
    allowed: set[str] = {str(stage0.comments_total), str(stage0.visits_total)}
    allowed.update(str(v) for v in stage0.visits_by_branch.values())
    for shop_score in agent3.shops.values():
        allowed.add(str(shop_score.visits))
        for ts in shop_score.themes.values():
            allowed.update(str(v) for v in (ts.n_pos, ts.n_neg, ts.n_sug, ts.mentions))
    for net_ts in agent3.network.themes.values():
        allowed.update(str(v) for v in (net_ts.n_pos, net_ts.n_neg))

    unmatched: set[str] = set()
    for text in (*_agent4_prose_fields(agent4), *_agent5_prose_fields(agent5)):
        stripped = _TIME_RE.sub("", text)
        for match in _NUMBER_RE.findall(stripped):
            if match not in allowed:
                unmatched.add(match)

    return VerificationCheck(
        id="V4",
        status="WARN" if unmatched else "PASS",
        details=f"number(s) in prose not found in computed counts: {sorted(unmatched)}" if unmatched else "ok",
    )


def _check_v5(agent3: Agent3Output, agent4: Optional[Agent4Output]) -> VerificationCheck:
    expected = {(shop, theme) for shop, s in agent3.shops.items() for theme in s.negative_themes_ranked}
    got: dict[tuple[str, str], int] = {}
    if agent4 is not None:
        for brief in agent4.briefs:
            key = (brief.shop, brief.theme)
            got[key] = got.get(key, 0) + 1

    missing = sorted(expected - got.keys())
    duplicated = sorted(k for k, n in got.items() if n > 1)
    extra = sorted(got.keys() - expected)

    problems = []
    if missing:
        problems.append(f"missing brief(s): {missing}")
    if duplicated:
        problems.append(f"duplicate brief(s): {duplicated}")
    if extra:
        problems.append(f"brief(s) for a non-negative or unknown (shop, theme): {extra}")

    return VerificationCheck(
        id="V5", status="FAIL" if problems else "PASS", details="; ".join(problems) if problems else "ok"
    )


def _check_v6(
    agent4: Optional[Agent4Output], agent5: Optional[Agent5Output], forbidden_phrases: list[str]
) -> VerificationCheck:
    hits: set[str] = set()
    for text in (*_agent4_prose_fields(agent4), *_agent5_prose_fields(agent5)):
        lowered = text.lower()
        for phrase in forbidden_phrases:
            if phrase.lower() in lowered:
                hits.add(phrase)
    return VerificationCheck(
        id="V6", status="WARN" if hits else "PASS", details=f"forbidden phrase(s) found: {sorted(hits)}" if hits else "ok"
    )


def _check_v7(
    stage0: Stage0Output, agent3: Agent3Output, agent5: Optional[Agent5Output], briefing_md: Optional[str]
) -> VerificationCheck:
    """Duplicates and no-detail comments are disclosed in the limitations or the
    excluded list. render.py always puts both in the rendered markdown's
    'Removed or excluded' section regardless of what the LLM wrote — so when
    briefing_md is passed in, this check mostly confirms that guarantee held;
    without it, it falls back to checking Agent 5's limitations prose alone."""
    disclosed_text = (agent5.limitations if agent5 is not None else "") + "\n" + (briefing_md or "")
    ids_to_check = {d.comment_id for d in stage0.duplicates}
    for shop_score in agent3.shops.values():
        ids_to_check.update(shop_score.no_detail_ids)

    undisclosed = sorted(cid for cid in ids_to_check if cid not in disclosed_text)
    return VerificationCheck(
        id="V7",
        status="FAIL" if undisclosed else "PASS",
        details=f"not disclosed in limitations or the briefing: {undisclosed}" if undisclosed else "ok",
    )


def _check_v8(
    stage0: Stage0Output, agent3: Agent3Output, agent4: Optional[Agent4Output], agent5: Optional[Agent5Output]
) -> VerificationCheck:
    # Every object reaching this point was already validated against its pydantic
    # schema at construction time (every LLM call is parsed through call_structured,
    # which raises before an invalid shape is ever returned). isinstance here is a
    # defensive re-confirmation, not the primary enforcement point.
    problems = []
    if not isinstance(stage0, Stage0Output):
        problems.append("stage0 is not a Stage0Output")
    if not isinstance(agent3, Agent3Output):
        problems.append("agent3 is not an Agent3Output")
    if agent4 is not None and not isinstance(agent4, Agent4Output):
        problems.append("agent4 is not an Agent4Output")
    if agent5 is not None and not isinstance(agent5, Agent5Output):
        problems.append("agent5 is not an Agent5Output")
    return VerificationCheck(
        id="V8", status="FAIL" if problems else "PASS", details="; ".join(problems) if problems else "ok"
    )


def _check_v9(agent5_warnings: Optional[list[str]]) -> VerificationCheck:
    if agent5_warnings is None:
        return VerificationCheck(
            id="V9", status="WARN", details="agent5_warnings not provided to verify_run; cannot confirm pre-overwrite agreement"
        )
    if agent5_warnings:
        return VerificationCheck(id="V9", status="WARN", details="; ".join(agent5_warnings))
    return VerificationCheck(id="V9", status="PASS", details="ok")


def _check_v10(stage0: Stage0Output, agent4: Optional[Agent4Output], agent5: Optional[Agent5Output]) -> VerificationCheck:
    duplicate_ids = {d.comment_id for d in stage0.duplicates}
    cited = _all_cited_ids(agent4, agent5)
    bad = sorted(cited & duplicate_ids)
    return VerificationCheck(
        id="V10", status="FAIL" if bad else "PASS", details=f"duplicate ID(s) cited as evidence: {bad}" if bad else "ok"
    )


def verify_run(
    stage0: Stage0Output,
    agent3: Agent3Output,
    agent4: Optional[Agent4Output],
    agent5: Optional[Agent5Output],
    *,
    config: Config,
    agent5_warnings: Optional[list[str]] = None,
    briefing_md: Optional[str] = None,
) -> VerificationResult:
    v1, v2 = _check_v1_v2(stage0, agent4, agent5)
    checks = [
        v1,
        v2,
        _check_v3(stage0, agent4),
        _check_v4(stage0, agent3, agent4, agent5),
        _check_v5(agent3, agent4),
        _check_v6(agent4, agent5, config.forbidden_phrases),
        _check_v7(stage0, agent3, agent5, briefing_md),
        _check_v8(stage0, agent3, agent4, agent5),
        _check_v9(agent5_warnings),
        _check_v10(stage0, agent4, agent5),
    ]
    overall: CheckStatus = "PASS"
    for c in checks:
        overall = _worse(overall, c.status)
    return VerificationResult(checks=checks, overall_status=overall)
