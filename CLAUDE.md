# Juniper Café Feedback Briefing · Claude Code instructions

## What this is
A Streamlit application that turns a CSV of café customer comments into a verified,
traceable weekly briefing for the operations manager. Course sprint project (HEC DSAIB).
Full spec: docs/BUILD_SPEC_A.md. Contracts: docs/contracts.md.

## Architecture (do not change without the team agreeing)
Linear pipeline, fixed order, no loops:
Stage 0 preprocess (code) -> Agent 1 tagger (LLM) -> Agent 2 polarity (LLM)
-> Agent 3 scorer (code) -> Agent 4 brief+CTA (LLM, per shop x negative theme)
-> Agent 5 editor (LLM) -> Verification gate (code) -> Manager review (UI)

## Providers
No paid Anthropic API key is available for this project. Every LLM-calling agent goes
through `juniper/llm.py`, which supports two providers, selected by `config.yaml`'s
`provider` key (or a `--provider` CLI flag):

- **gemini** — free-tier Google Gemini Flash (`google-genai` SDK). Needs `GEMINI_API_KEY`.
  This is the default and what the deployed Streamlit app uses.
- **mock** — canned fixtures from `fixtures/mock/<test_id>/<agent>.json`. No key, no
  network. This is what CI and most unit tests use.

The deployed app uses Gemini or Demo mode (see Phase 8) — no local-only provider.

## Non-negotiable rules
- All counting, scoring, ranking and deduplication is done in Python, never by an LLM.
- The unit of counting is one VISIT (visit_id). Duplicate visits count once.
- Every LLM call uses structured output validated by the pydantic models in juniper/models.py.
- Every quote must be an exact substring of its comment. verify.py enforces this.
- Prompts are read from prompts/<agent>/<version>.md. Never hardcode prompt text in Python.
- Theme list comes from codebook.yaml. Never hardcode themes in Python.
- Every run saves all intermediate outputs to runs/<timestamp>_<label>/.
- Log latency and tokens for every LLM call. Cost is always €0 for gemini (free tier)
  and mock; `cost_eur_if_paid_est` is only populated when `paid_price_per_mtok_eur`
  is set in config.yaml.
- Mock mode (provider: mock in config.yaml) must work with no API key and no network.
- Never print or log an API key.

## Ownership
Person B owns: codebook.yaml, answer_key.json, prompts/, data/tests/, docs/rationale.md,
docs/video_script.md, docs/BUILD_SPEC_B.md. Do not edit these. Use placeholders if missing.

## Commands
python run_pipeline.py data/batch_original.csv --label dev [--provider gemini|mock]
python run_tests.py --label v1 [--provider gemini|mock]
python compare_runs.py runs/<a> runs/<b>
python check_llm.py [--provider gemini|mock]   # smoke test: one structured call
streamlit run app.py
pytest -q
