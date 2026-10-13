"""Builds briefing.md. Counts tables are injected here from Agent 3's output —
Agent 5 never produces them (docs/contracts.md 5.9). See BUILD_SPEC_A Phase 5
for the section order this follows.
"""

from __future__ import annotations

from juniper.models import Agent3Output, Agent4Output, Agent5Output, ShopScore, Stage0Output


def _counts_table(shop_score: ShopScore) -> str:
    lines = [
        "| Theme | Positive | Negative | Score | Evidence | Comment IDs |",
        "|---|---|---|---|---|---|",
    ]
    for theme, ts in shop_score.themes.items():
        ids = ", ".join(sorted(set(ts.positive_ids) | set(ts.negative_ids) | set(ts.suggestion_ids)))
        lines.append(f"| {theme} | {ts.n_pos} | {ts.n_neg} | {ts.score} | {ts.evidence_level} | {ids} |")
    if len(lines) == 2:
        lines.append("| _no themes mentioned_ | | | | | |")
    return "\n".join(lines)


def render_briefing(
    stage0: Stage0Output,
    agent3_output: Agent3Output,
    agent4_output: Agent4Output,
    agent5_output: Agent5Output,
    *,
    label: str = "",
) -> str:
    """Short-circuits to "No feedback received this week." when there are 0
    visits — no LLM calls happen upstream in that case either, so this is
    purely a formatting concern here."""
    if stage0.visits_total == 0:
        return "# Juniper Café Feedback Briefing\n\nNo feedback received this week.\n"

    briefs_by_shop: dict[str, list] = {}
    for brief in agent4_output.briefs:
        briefs_by_shop.setdefault(brief.shop, []).append(brief)

    lines: list[str] = ["# Juniper Café Feedback Briefing"]
    if label:
        lines.append(f"_{label}_")
    lines.append("")
    lines.append(
        f"**{stage0.visits_total} visits** from **{stage0.comments_total} comments** "
        f"({len(stage0.duplicates)} duplicate(s) removed)."
    )
    lines.append("")
    lines.append(f"## {agent5_output.headline}")
    lines.append("")

    np = agent5_output.network_priority
    lines.append("## Network priority")
    lines.append(f"**{np.theme or 'None'}** — {np.reason}")
    lines.append("")
    lines.append(f"**Action:** {np.action}")
    if np.cited_ids:
        lines.append(f"_Evidence: {', '.join(np.cited_ids)}_")
    lines.append("")

    for shop_summary in agent5_output.shops:
        shop = shop_summary.shop
        lines.append(f"## {shop}")
        lines.append(shop_summary.overview)
        lines.append("")

        shop_score = agent3_output.shops.get(shop)
        if shop_score is not None:
            lines.append(_counts_table(shop_score))
            lines.append("")

        for brief in briefs_by_shop.get(shop, []):
            lines.append(f"### {brief.theme}")
            lines.append(brief.summary_of_comments)
            lines.append("")
            # Agent 4's own prompt instructs it to phrase this as an interpretation
            # (e.g. "Possible reading: ..." per docs/contracts.md 5.8's example) —
            # render.py doesn't add its own prefix on top of that.
            lines.append(f"_{brief.interpretation}_")
            lines.append("")
            lines.append(f"**Suggested action ({brief.cta.kind}):** {brief.cta.action}")
            if brief.cta.data_needed:
                lines.append(f"- Data needed: {', '.join(brief.cta.data_needed)}")
            lines.append(f"- Success signal: {brief.cta.success_signal}")
            lines.append("")

    if agent5_output.requests:
        lines.append("## Requests")
        for r in agent5_output.requests:
            lines.append(f"- {r}")
        lines.append("")

    if agent5_output.mixed_views_note:
        lines.append("## Mixed views")
        lines.append(agent5_output.mixed_views_note)
        lines.append("")

    lines.append("## Limitations")
    lines.append(agent5_output.limitations)
    lines.append("")

    lines.append("## Removed or excluded")
    any_excluded = False

    if stage0.duplicates:
        any_excluded = True
        lines.append("**Duplicates:**")
        for d in stage0.duplicates:
            lines.append(f"- {d.comment_id} (duplicate of {d.duplicate_of}, visit {d.visit_id})")

    no_detail_all = sorted({cid for s in agent3_output.shops.values() for cid in s.no_detail_ids})
    if no_detail_all:
        any_excluded = True
        lines.append("**No usable detail:**")
        for cid in no_detail_all:
            lines.append(f"- {cid}")

    if stage0.possible_text_duplicates:
        any_excluded = True
        lines.append("**Possible text duplicates (kept, flagged for review):**")
        for p in stage0.possible_text_duplicates:
            lines.append(f"- {p.comment_id} (same text as {p.duplicate_of}, different visit)")

    if not any_excluded:
        lines.append("_None._")

    return "\n".join(lines) + "\n"
