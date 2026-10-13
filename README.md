# Juniper Café Feedback Briefing

Turns a CSV of café customer comments into a concise, traceable weekly briefing
for the operations manager of Juniper Café (branches: Central, Riverside, Station).
Built for the HEC DSAIB afternoon AI solution sprint (Case 04).

- **User / EDGE target:** operations manager · mainly Decisions, secondary Efficiency
- **5A form:** Application (Streamlit)
- **Workflow:** linear 5-agent pipeline, fixed order, no loops

```
CSV ──► Stage 0 Preprocess (code: dedupe by visit, validate, count visits)
    ──► Agent 1 Theme tagger (LLM)
    ──► Agent 2 Polarity judge (LLM)
    ──► Agent 3 Shop scorer (code: counts, score, evidence level, priority ranking)
    ──► Agent 4 Theme brief + CTA writer (LLM, one call per shop × negative theme)
    ──► Agent 5 Final briefing editor (LLM)
    ──► Verification gate (code)
    ──► Manager review (Streamlit): approve / edit / reject
```

Full design spec: [docs/BUILD_SPEC_A.md](docs/BUILD_SPEC_A.md) (Person A / Claude Code)
and [docs/BUILD_SPEC_B.md](docs/BUILD_SPEC_B.md) (Person B / Mimiwork).
Stage contracts: [docs/contracts.md](docs/contracts.md).

## Status

Repo scaffold complete (Phase 1 in progress). See `docs/BUILD_SPEC_A.md` Section 6
for the build phases and `docs/iterations.md` / `docs/decisions.md` for the running log.

Files marked `# PLACEHOLDER: Person B will replace this` (codebook, prompts, answer
key, test batches) are seeded with starting drafts so the pipeline is runnable, but
are owned by Person B and awaiting their real v1.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# edit .env and set ANTHROPIC_API_KEY=sk-ant-...
```

## Run

```bash
python run_pipeline.py data/batch_original.csv --label dev   # run the pipeline once
python run_tests.py --label v1                                # run all tests, prototype + baseline
python compare_runs.py runs/<a> runs/<b>                      # metric deltas between two runs
streamlit run app.py                                           # manager review app
pytest -q                                                       # unit tests
```

Set `provider: mock` in `config.yaml` to run everything with no API key, using
canned fixtures in `fixtures/mock/`.

## Repo structure and ownership

See [docs/BUILD_SPEC_A.md](docs/BUILD_SPEC_A.md) Section 3 for the full table.
In short:

- **Person A (Claude Code)** owns: `CLAUDE.md`, `requirements.txt`, `.gitignore`,
  `.env.example`, `config.yaml`, `juniper/`, `run_pipeline.py`, `run_tests.py`,
  `compare_runs.py`, `app.py`, `fixtures/`, `tests/`.
- **Person B (Mimiwork)** owns: `codebook.yaml`, `answer_key.json`, `prompts/`,
  `data/tests/`, `docs/rationale.md`, `docs/video_script.md`, `docs/BUILD_SPEC_B.md`.
  Person A never edits these — only creates a clearly marked placeholder if one
  is missing.
- Both: `docs/decisions.md`, `docs/iterations.md`.

## Team contributions

_To be completed in Phase 9 — copied from `BUILD_SPEC_B.md` Section 12._

## Known limitations

- The feedback batch is a convenience sample, not a survey.
- `codebook.yaml`, prompts, `answer_key.json` and test batches beyond T01 are
  placeholders until Person B delivers the real versions (see Status above).
