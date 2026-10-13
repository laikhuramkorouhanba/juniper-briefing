# Decisions log

One line per design decision, with reason. Either teammate may add entries.

## Format
- `<date>` · `<decision>` — `<reason>`

## Log
- 2026-10-13 · Models pinned to `claude-haiku-4-5` and `claude-sonnet-5` in `config.yaml` (not the fictional IDs in the original spec draft) — these are real, currently available Claude model IDs; pricing filled in from the current rate card.
- 2026-10-13 · Agent 3 (shop scorer) implemented as deterministic Python, not an LLM — counts/scores must be exact and reproducible; case explicitly asks which counts can be done deterministically.
- 2026-10-13 · Counting unit is one visit (`visit_id`), not one comment — F07 is a forwarded duplicate of F03 (same visit); counting it again would double-count one visit.
- 2026-10-13 · Codebook fixed at 10 themes with those exact names (`coffee_quality`, `waiting_time`, `staff_service`, `cleanliness`, `price_accuracy`, `product_availability`, `menu_range`, `atmosphere_seating`, `checkout_receipt`, `other`) — the answer key and the tests compare theme names literally, so the vocabulary has to be frozen before any prompt is written.
- 2026-10-13 · Theme tagging (Agent 1) and polarity (Agent 2) are separate agents — a comment can mention a theme without complaining about it; splitting them lets us measure theme recall and polarity accuracy separately, and makes mixed comments (T01 Central waiting time, T06) representable.
- 2026-10-13 · Polarity is per theme, never one verdict per comment — the case explicitly mixes praise and complaint in a single comment; a single verdict would erase half the signal.
- 2026-10-13 · Answer key uses an `extends: T01` mechanism for the tests derived from the routine batch (T03, T04, T05, T07, T12) — the derived tests differ from T01 only in the listed fields, so inheriting keeps the key short and removes any risk of the copies drifting apart.
- 2026-10-13 · Comments are the unit of truth for quotes; a brief may only cite a real `comment_id` with an exact quote — this is the fairness boundary the verification gate enforces, and it stops the LLM from inventing evidence.
- 2026-10-13 · Branch name is called "shop" in the app/data vocabulary (`shop_priorities`, per-shop briefs) to match the case wording, while the CSV column stays `branch` — one label matches the case, the other matches the data contract Person A reads.
