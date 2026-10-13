"""Agent 3 · Shop scorer (code, not an LLM). See docs/contracts.md Section 5.7.

Counting, scoring and ranking must be exact and reproducible, so this is pure
Python over Agent 2's output — never an LLM call. Counting is per VISIT; since
Stage 0 already keeps at most one clean comment per visit_id, counting by
comment_id here is equivalent to counting by visit_id.
"""

from __future__ import annotations

from juniper.models import (
    Agent2Output,
    Agent3Output,
    Comment,
    NetworkScore,
    NetworkThemeScore,
    ShopScore,
    Stage0Output,
    SuggestionItem,
    ThemeScore,
)


def _round2(x: float) -> float:
    return round(x, 2)


def score(
    agent2_output: Agent2Output,
    clean_comments: list[Comment],
    stage0: Stage0Output,
    *,
    single_mention_max: int = 1,
) -> Agent3Output:
    comments_by_id = {c.comment_id: c for c in clean_comments}

    # shop -> theme -> polarity -> set(comment_id). Sets absorb the "a visit
    # tagged twice with the same theme and polarity counts once" rule for free.
    buckets: dict[str, dict[str, dict[str, set[str]]]] = {}
    no_detail_ids_by_shop: dict[str, list[str]] = {}
    suggestions: list[SuggestionItem] = []

    for item in agent2_output.items:
        comment = comments_by_id.get(item.comment_id)
        if comment is None:
            continue  # not a clean comment in this batch; shouldn't happen post-validation
        shop = comment.branch

        if not item.assessments:
            no_detail_ids_by_shop.setdefault(shop, []).append(item.comment_id)
            continue

        for a in item.assessments:
            bucket = buckets.setdefault(shop, {}).setdefault(
                a.theme, {"positive": set(), "negative": set(), "suggestion": set()}
            )
            bucket[a.polarity].add(item.comment_id)
            if a.polarity == "suggestion":
                suggestions.append(
                    SuggestionItem(shop=shop, theme=a.theme, comment_id=item.comment_id, quote=a.quote)
                )

    # ---- network aggregates (needed for both ranking and the network section) ----

    network_acc: dict[str, dict[str, object]] = {}
    for shop, themes in buckets.items():
        for theme, polarities in themes.items():
            acc = network_acc.setdefault(theme, {"n_pos": 0, "n_neg": 0, "shops_with_negative": set()})
            n_pos = len(polarities["positive"])
            n_neg = len(polarities["negative"])
            acc["n_pos"] += n_pos
            acc["n_neg"] += n_neg
            if n_neg > 0:
                acc["shops_with_negative"].add(shop)

    network_themes = {
        theme: NetworkThemeScore(
            n_pos=acc["n_pos"],
            n_neg=acc["n_neg"],
            shops_with_negative=sorted(acc["shops_with_negative"]),
        )
        for theme, acc in network_acc.items()
    }

    negative_network_themes = [t for t, s in network_themes.items() if s.n_neg > 0]
    if negative_network_themes:
        network_priority_theme = min(
            negative_network_themes,
            key=lambda t: (
                -network_themes[t].n_neg,
                -len(network_themes[t].shops_with_negative),
                network_themes[t].n_pos,
                t,
            ),
        )
    else:
        network_priority_theme = None

    network = NetworkScore(themes=network_themes, priority_theme=network_priority_theme)

    # ---- per-shop scoring ----

    shops: dict[str, ShopScore] = {}
    for shop, visits in stage0.visits_by_branch.items():
        theme_scores: dict[str, ThemeScore] = {}
        for theme, polarities in buckets.get(shop, {}).items():
            n_pos = len(polarities["positive"])
            n_neg = len(polarities["negative"])
            n_sug = len(polarities["suggestion"])
            mentions = n_pos + n_neg
            mention_rate = _round2(mentions / visits) if visits else 0.0
            theme_score = _round2((n_pos - n_neg) / mentions) if mentions > 0 else 0.0
            evidence_level = "single mention" if mentions <= single_mention_max else "repeated"

            theme_scores[theme] = ThemeScore(
                positive_ids=sorted(polarities["positive"]),
                negative_ids=sorted(polarities["negative"]),
                suggestion_ids=sorted(polarities["suggestion"]),
                n_pos=n_pos,
                n_neg=n_neg,
                n_sug=n_sug,
                mentions=mentions,
                mention_rate=mention_rate,
                score=theme_score,
                evidence_level=evidence_level,
                mixed=n_pos > 0 and n_neg > 0,
            )

        negative_themes = [t for t, s in theme_scores.items() if s.n_neg > 0]
        negative_themes_ranked = sorted(
            negative_themes,
            key=lambda t: (
                -theme_scores[t].n_neg,
                -network_themes.get(t, NetworkThemeScore(n_pos=0, n_neg=0)).n_neg,
                theme_scores[t].n_pos,
                t,
            ),
        )
        priority_theme = negative_themes_ranked[0] if negative_themes_ranked else None

        shops[shop] = ShopScore(
            visits=visits,
            themes=theme_scores,
            negative_themes_ranked=negative_themes_ranked,
            priority_theme=priority_theme,
            no_detail_ids=sorted(no_detail_ids_by_shop.get(shop, [])),
        )

    return Agent3Output(
        visits_total=stage0.visits_total,
        shops=shops,
        network=network,
        suggestions=suggestions,
    )
