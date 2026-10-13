# Iterations log

One entry per change and its test results. Change one thing at a time; never overwrite `v1.md`,
create `v2.md` next to it and bump the version in `config.yaml`.

## Template
```
## <time> · <agent or component> · v1 -> v2
- Change:
- Why (which test or metric failed):
- Result: task success x/12 -> y/12; recall a -> b; cost c -> d; latency e -> f
- Keep? yes / no
```

## Log

## 14:20 · Agent 2 (polarity) · v1 -> v2
- Change: polarity is now assigned per **theme**, not one verdict for the whole comment; added the
  rule "a comment may be positive on one theme and negative on another, and must be labelled
  separately for each."
- Why (which test or metric failed): T06 (opposing views) and the mixed-views case in T01 — v1 gave
  a single polarity per comment, so a comment that praised the coffee and complained about the
  queue was collapsed to one tag, missing the negative on waiting time.
- Result: task success (see `results.md`); polarity accuracy a -> b; cost c -> d; latency e -> f.
  *(Numeric results are filled from Person A's `results.md` after the end-to-end run.)*
- Keep? yes — separating "mentioned" from "complained about" per theme is what makes the
  per-branch priority ranking correct.

## 14:35 · Agent 4 (brief) · v1 -> v2
- Change: each brief must cite at least one real `comment_id` with an exact quote, and may propose
  exactly one action per branch × problem; removed any instruction that invited general advice.
- Why (which test or metric failed): early drafts produced vague actions ("improve the experience")
  that scored low on the §9 rubric for *specific* and *addresses the problem*.
- Result: action quality (see `docs/cta_ratings.csv`); overclaiming rate down; cost unchanged.
  *(Numeric results filled from `results.md` / ratings after the run.)*
- Keep? yes — grounded actions are the point of the briefing; a vague action gives the manager
  nothing to investigate.
