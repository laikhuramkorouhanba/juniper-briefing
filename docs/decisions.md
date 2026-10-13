# Decisions log

One line per design decision, with reason. Either teammate may add entries.

## Format
- `<date>` · `<decision>` — `<reason>`

## Log
- 2026-10-13 · Models pinned to `claude-haiku-4-5` and `claude-sonnet-5` in `config.yaml` (not the fictional IDs in the original spec draft) — these are real, currently available Claude model IDs; pricing filled in from the current rate card. **Superseded same day**, see below: no paid API key turned out to be available for this project.
- 2026-10-13 · Agent 3 (shop scorer) implemented as deterministic Python, not an LLM — counts/scores must be exact and reproducible; case explicitly asks which counts can be done deterministically.
- 2026-10-13 · Counting unit is one visit (`visit_id`), not one comment — F07 is a forwarded duplicate of F03 (same visit); counting it again would double-count one visit.
- 2026-10-13 · No paid API available. Primary: free Gemini Flash. Local fallback: Qwen 2.5 7B via Ollama. Small models are sufficient because each agent has one narrow task and all counting and verification is done in code. Ollama is local-only; the deployed app uses Gemini, with Demo mode as a fallback.
