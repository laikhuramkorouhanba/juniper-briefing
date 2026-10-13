# Juniper Café Feedback Briefing · Design rationale

**Team:** Person A (build, pipeline, tests) · Person B (prompts, codebook, evaluation design, rationale)

## Problem and user
The operations manager of Juniper Café (3 branches) reads customer comments before the weekly
meeting. Dramatic complaints dominate while recurring, quieter issues are missed, and comments
are often duplicated or mixed. Manual preparation takes about 15 minutes (estimate) and
produces no traceable evidence.

## EDGE target
Mainly **Decisions**: a shorter, evidence-backed briefing so the manager picks the right issue
to investigate. Secondary **Efficiency**: less preparation time and cost per week.

## 5A choice: Application (Streamlit)
- Access (pasting into a chatbot) is our baseline: it cannot count reliably or show evidence.
- An Assistant (saved prompt) is reusable but still counts with the LLM, so counts are not verifiable.
- An Application lets code do what code does best (deduplication, counting, ranking, checks)
  and the LLM do what it does best (reading comments, writing briefs).
- Automation (scheduled weekly run) is a natural next step, not needed to prove value.
- A free-roaming agent is not justified: there is nothing to fetch and no action to take.

## Workflow: linear multi-agent pipeline
| Step | Role | Why it is a separate role |
|---|---|---|
| Stage 0 (code) | Deduplicate by visit, count visits | Exact rule; the case requires a clear denominator |
| Agent 1 (LLM) | Tag themes with exact quotes | Recall task; measured separately (theme recall) |
| Agent 2 (LLM) | Positive / negative / suggestion per theme | Comments mix praise and complaints; separating "mentioned" from "complained about" reduced errors and is measured separately (polarity accuracy) |
| Agent 3 (code) | Counts, scores, priority ranking | Counts must be exact, so no LLM |
| Agent 4 (LLM) | One brief + one action per branch × problem | A small, focused evidence set per call keeps briefs grounded; calls run in parallel |
| Agent 5 (LLM) | Assemble final briefing and limitations | Editing role only; may not add facts |
| Gate (code) | Check quotes, IDs, numbers, overclaiming | "Verified outputs" before a human sees it |

**Why linear, not delegating agents:** the order of work never changes, so a fixed pipeline is
predictable, cheaper, and every intermediate output can be inspected and tested.
Trade-off: more LLM calls than one prompt; latency measured against the baseline over the full
test batch (see `results.md`).

## Human responsibilities
The manager reviews the briefing with its evidence, sees warnings from the gate, and approves,
edits or rejects. The tool suggests what to investigate; it never decides or sends anything.

## Measures
- Primary: task success (correct visit counts, correct theme counts, every problem has a brief and action, gate not failed): prototype vs baseline over T01–T12 (see `results.md`).
- Quality boundary: zero invented feedback (every claim cites a real comment ID and exact quote).
- Theme recall, polarity accuracy, factual support: reported in `results.md`.
- Action quality (human rating, likely to address the theme): see `docs/cta_ratings.csv` (scores ≥ 6/8 = likely to address the theme).
- Latency and cost per batch: prototype vs baseline, reported in `results.md` (estimates from token counts).

> Metric values above are filled from Person A's `results.md` after the end-to-end run; the
> design and the method are the parts fixed in this version.

## Limitations
Small convenience sample, not a survey. Theme tagging still benefits from a human glance.
Action quality is a human judgement. Costs are estimates. Next step: week-over-week trends and
a scheduled weekly run.
