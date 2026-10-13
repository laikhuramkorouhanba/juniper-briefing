"""Agent 1 · Theme tagger (LLM). See docs/contracts.md Section 5.5.

Which themes each comment mentions, and the exact quote that shows each one.
Does not judge polarity — that's Agent 2.
"""

from __future__ import annotations

from juniper.checked_call import call_with_semantic_retry
from juniper.config import Config
from juniper.io_utils import codebook_as_text, render_prompt
from juniper.models import Agent1Item, Agent1Output, CallLog, Codebook, Comment
from juniper.text_utils import is_exact_substring

AGENT_NAME = "agent1_tagger"


def _comments_payload(comments: list[Comment]) -> list[dict]:
    return [{"comment_id": c.comment_id, "branch": c.branch, "text": c.text} for c in comments]


def _validate_items(
    items: list[Agent1Item], expected_comments: dict[str, Comment], theme_names: set[str]
) -> list[str]:
    """The checks in docs/contracts.md 5.5:
    - one item per clean comment, no extras, no missing items
    - every theme is in the codebook
    - every quote is an exact substring of the comment text (whitespace-normalised)
    - usable: false implies an empty themes list
    """
    errors: list[str] = []
    expected_ids = set(expected_comments.keys())
    got_ids = [item.comment_id for item in items]
    got_id_set = set(got_ids)

    if len(got_ids) != len(got_id_set):
        errors.append("duplicate comment_id in Agent 1 output")

    missing = expected_ids - got_id_set
    if missing:
        errors.append(f"missing comment_id(s): {sorted(missing)}")

    extra = got_id_set - expected_ids
    if extra:
        errors.append(f"unexpected comment_id(s) not in this batch: {sorted(extra)}")

    for item in items:
        comment = expected_comments.get(item.comment_id)
        if comment is None:
            continue  # already reported above as "extra"

        if item.usable is False and item.themes:
            errors.append(f"{item.comment_id}: usable=false but themes is not empty")

        for tag in item.themes:
            if tag.theme not in theme_names:
                errors.append(f"{item.comment_id}: unknown theme '{tag.theme}'")
            if not is_exact_substring(tag.quote, comment.text):
                errors.append(
                    f"{item.comment_id}: quote {tag.quote!r} is not an exact substring "
                    "of the comment text"
                )

    return errors


def _tag_one_batch(
    comments: list[Comment],
    codebook: Codebook,
    codebook_text: str,
    config: Config,
    test_id: str | None,
) -> tuple[list[Agent1Item], CallLog]:
    expected = {c.comment_id: c for c in comments}
    theme_names = {t.name for t in codebook.themes}
    prompt_version = config.prompt_version(AGENT_NAME)
    payload = _comments_payload(comments)

    def build_prompt(extra_instruction: str) -> str:
        base = render_prompt(AGENT_NAME, prompt_version, codebook=codebook_text, comments=payload)
        return base if not extra_instruction else f"{base}\n\n{extra_instruction}"

    parsed, log = call_with_semantic_retry(
        AGENT_NAME,
        build_prompt,
        Agent1Output,
        lambda output: _validate_items(output.items, expected, theme_names),
        config=config,
        test_id=test_id,
    )
    return parsed.items, log


def tag_comments(
    clean_comments: list[Comment],
    codebook: Codebook,
    *,
    config: Config,
    test_id: str | None = None,
) -> tuple[Agent1Output, list[CallLog]]:
    """Run Agent 1 over every clean comment from Stage 0.

    Returns the merged Agent1Output plus the list of CallLogs made (one for
    whole_batch mode, one per comment for per_comment mode — config.yaml's
    llm.batch_mode.agent1_tagger).
    """
    if not clean_comments:
        return Agent1Output(items=[]), []

    codebook_text = codebook_as_text(codebook)
    batch_mode = config.batch_mode(AGENT_NAME)
    if config.provider == "mock":
        # Mock fixtures are one static whole-batch snapshot; per_comment batching
        # has nothing meaningful to simulate against a canned response, so always
        # make a single call here regardless of the configured batch_mode.
        batch_mode = "whole_batch"

    if batch_mode == "per_comment":
        items: list[Agent1Item] = []
        call_logs: list[CallLog] = []
        for comment in clean_comments:
            batch_items, log = _tag_one_batch([comment], codebook, codebook_text, config, test_id)
            items.extend(batch_items)
            call_logs.append(log)
        return Agent1Output(items=items), call_logs

    items, log = _tag_one_batch(clean_comments, codebook, codebook_text, config, test_id)
    return Agent1Output(items=items), [log]
