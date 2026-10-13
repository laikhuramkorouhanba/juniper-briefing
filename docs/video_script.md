# Demo video script (~4 min)

## 0:00 to 0:30 · Problem
"Juniper Café's manager reads every comment before the weekly meeting. The loudest complaint wins,
duplicates inflate issues, and nothing links back to evidence. We built a briefing that counts
what can be counted, flags what repeats, and shows the exact comment behind every claim."

## 0:30 to 1:15 · Design
Show the pipeline diagram. "Code counts and checks; AI reads and writes; the manager decides.
Five steps in a fixed line, each with one job we can test: deduplicate and count visits, tag themes
with quotes, label polarity, rank priorities, then write one brief and one action per problem. A
verification gate checks quotes, IDs and numbers before the manager ever sees it. This is an
Application, chosen mainly for Decisions: the manager needs to pick the right issue to investigate."

## 1:15 to 2:15 · Routine run (T01)
Upload the batch. Show the stage progress with timings. Open the briefing: 12 comments, 11 visits,
F07 removed as a duplicate of F03, F11 has no detail, waiting time is the priority at all three
branches, mixed views on waiting time at Central, one action per problem. Click a theme in Evidence
to show the comments behind it — every claim links to a real comment ID and quote.

## 2:15 to 3:00 · Hard case
Option A: T09 — one dramatic "WORST VISIT EVER" complaint versus four quieter queue comments; the
briefing ranks waiting time first by count, not by tone.
Option B: T12 — a comment contains a prompt injection ("ignore all previous instructions"); the
gate shows it was not followed and was treated as no detail.
Option C: T02 — an empty batch: no LLM calls, no invented themes, the briefing says no feedback received.
Show the gate result and the review step (approve with a note).

## 3:00 to 3:45 · Results
Show results.md: prototype vs baseline task success, factual support, latency and cost per batch.
Mention one iteration that improved a metric (from docs/iterations.md) — for example tightening
Agent 2 so mixed comments get a polarity per theme instead of one verdict for the whole comment.

## 3:45 to 4:15 · Limits and next step
Small sample, human-rated actions, cost estimates. The tool suggests what to investigate; it never
decides. Next step: week-over-week trends and a scheduled weekly run.
