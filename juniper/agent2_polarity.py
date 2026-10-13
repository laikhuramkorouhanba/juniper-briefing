"""Agent 2 · Polarity judge (LLM). See docs/contracts.md Section 5.6.

For each (comment, theme) pair Agent 1 already tagged, decide the customer's
stance: positive, negative or suggestion.
"""

from __future__ import annotations

from juniper.checked_call import call_with_semantic_retry
from juniper.config import Config
from juniper.io_utils import codebook_as_text, render_prompt
from juniper.models import (
    Agent1Item,
    Agent1Output,
    Agent2Item,
    Agent2Output,
    CallLog,
    Codebook,
    Comment,
)

AGENT_NAME = "agent2_polarity"


def _tagged_comments_payload(items: list[Agent1Item], comments_by_id: dict[str, Comment]) -> list[dict]:
    payload = []
    for item in items:
        comment = comments_by_id[item.comment_id]
        payload.append(
            {
                "comment_id": item.comment_id,
                "text": comment.text,
                "themes": [{"theme": t.theme, "quote": t.quote} for t in item.themes],
            }
        )
    return payload


def _expected_pairs(agent1_output: Agent1Output) -> dict[str, set[tuple[str, str]]]:
    return {
        item.comment_id: {(t.theme, t.quote) for t in item.themes}
        for item in agent1_output.items
    }


def _validate_items(items: list[Agent2Item], expected_pairs: dict[str, set[tuple[str, str]]]) -> list[str]:
    """The check in docs/contracts.md 5.6: the set of (comment_id, theme) pairs
    must equal Agent 1's set exactly — no added or dropped themes, quotes unchanged."""
    errors: list[str] = []
    expected_ids = set(expected_pairs.keys())
    got_ids = [item.comment_id for item in items]
    got_id_set = set(got_ids)

    if len(got_ids) != len(got_id_set):
        errors.append("duplicate comment_id in Agent 2 output")

    missing = expected_ids - got_id_set
    if missing:
        errors.append(f"missing comment_id(s): {sorted(missing)}")

    extra = got_id_set - expected_ids
    if extra:
        errors.append(f"unexpected comment_id(s) not tagged by Agent 1: {sorted(extra)}")

    for item in items:
        expected = expected_pairs.get(item.comment_id)
        if expected is None:
            continue  # already reported above as "extra"

        got = {(a.theme, a.quote) for a in item.assessments}
        added = got - expected
        dropped = expected - got
        if added:
            errors.append(f"{item.comment_id}: added theme/quote pair(s) not from Agent 1: {sorted(added)}")
        if dropped:
            errors.append(f"{item.comment_id}: dropped theme/quote pair(s) from Agent 1: {sorted(dropped)}")

    return errors


def _judge_one_batch(
    items: list[Agent1Item],
    comments_by_id: dict[str, Comment],
    codebook_text: str,
    config: Config,
    test_id: str | None,
) -> tuple[list[Agent2Item], CallLog]:
    expected_pairs = _expected_pairs(Agent1Output(items=items))
    prompt_version = config.prompt_version(AGENT_NAME)
    payload = _tagged_comments_payload(items, comments_by_id)

    def build_prompt(extra_instruction: str) -> str:
        base = render_prompt(
            AGENT_NAME, prompt_version, codebook=codebook_text, tagged_comments=payload
        )
        return base if not extra_instruction else f"{base}\n\n{extra_instruction}"

    parsed, log = call_with_semantic_retry(
        AGENT_NAME,
        build_prompt,
        Agent2Output,
        lambda output: _validate_items(output.items, expected_pairs),
        config=config,
        test_id=test_id,
    )
    return parsed.items, log


def judge_polarity(
    agent1_output: Agent1Output,
    clean_comments: list[Comment],
    codebook: Codebook,
    *,
    config: Config,
    test_id: str | None = None,
) -> tuple[Agent2Output, list[CallLog]]:
    """Run Agent 2 over Agent 1's tagged comments. Returns the validated
    Agent2Output plus the list of CallLogs made (one for whole_batch mode, one
    per comment for per_comment mode — config.yaml's llm.batch_mode.agent2_polarity)."""
    if not agent1_output.items:
        return Agent2Output(items=[]), []

    comments_by_id = {c.comment_id: c for c in clean_comments}
    codebook_text = codebook_as_text(codebook)
    batch_mode = config.batch_mode(AGENT_NAME)
    if config.provider == "mock":
        # Same reasoning as Agent 1: a mock fixture is one static whole-batch
        # snapshot, so per-comment batching has nothing meaningful to simulate.
        batch_mode = "whole_batch"

    if batch_mode == "per_comment":
        items: list[Agent2Item] = []
        call_logs: list[CallLog] = []
        for agent1_item in agent1_output.items:
            batch_items, log = _judge_one_batch([agent1_item], comments_by_id, codebook_text, config, test_id)
            items.extend(batch_items)
            call_logs.append(log)
        return Agent2Output(items=items), call_logs

    items, log = _judge_one_batch(agent1_output.items, comments_by_id, codebook_text, config, test_id)
    return Agent2Output(items=items), [log]
