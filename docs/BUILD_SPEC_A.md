# Build Spec A · Claude Code · Juniper Café Feedback Briefing

**Owner:** Person A (builds and runs everything in the repo with Claude Code)
**Teammate:** Person B (Mimiwork) owns the codebook, prompts, answer key, test batches, rationale and video script. See `BUILD_SPEC_B_mimiwork.md`.

---

## 0. How to use this file

1. **Human (Person A):** do Section 2 yourself. It takes about 5 minutes.
2. Save this file in the repo as `docs/BUILD_SPEC_A.md`, and Person B's file as `docs/BUILD_SPEC_B.md`.
3. Open Claude Code in the repo folder and paste:

> Read CLAUDE.md and docs/BUILD_SPEC_A.md. Build the project phase by phase exactly as specified in Section 6. After each phase, run the tests for that phase and show me the result. Stop at every CHECKPOINT and wait for me before continuing. Never edit files owned by Person B (listed in Section 3); if one is missing, create a clearly marked placeholder and tell me.

---

## 1. Guardrails (agreed by both teammates, do not change without both agreeing)

| Item | Decision |
|---|---|
| **User** | Café / restaurant operations manager (Juniper Café, 3 branches: Central, Riverside, Station) |
| **EDGE target** | Mainly **Decisions** (faster, evidence-backed choices). Secondary: **Efficiency** (less time and cost to prepare the weekly briefing) |
| **5A form** | **Application** (Streamlit) |
| **Workflow** | **Linear multi-agent pipeline**: 5 agents in a fixed order, no loops, no delegation back and forth |
| **Success measure** | A concise, traceable briefing where the main themes clearly appear, each theme lists the comments that support it, and each problem has an action to take next |
| **Measured by** | Useful theme coverage, factual support, and whether the action is likely to address the theme (human rating) |
| **Must also report** | Task success, latency and cost, compared with a simple baseline (required by the course slide) |
| **Human control** | The manager reviews, edits, approves or rejects. Nothing is sent anywhere automatically |

### The five agents (linear)

```
CSV ──► [Stage 0: Preprocess (code)]
          dedupe by visit_id, validate, count visits
     ──► [Agent 1: Theme tagger (LLM)]
          which themes each comment mentions + exact quote
     ──► [Agent 2: Polarity judge (LLM)]
          positive / negative / suggestion for each tagged theme
     ──► [Agent 3: Shop scorer (code)]
          per shop × theme: counts, score, evidence level, priority ranking
     ──► [Agent 4: Theme brief + CTA writer (LLM, one call per shop × negative theme)]
          what comments say, possible reading, one small action
     ──► [Agent 5: Final briefing editor (LLM)]
          per-shop briefing + network priority + limitations
     ──► [Verification gate (code)]
          quotes real, IDs valid, numbers match, no overclaiming
     ──► [Manager review in Streamlit]
          approve / edit / reject
```

**Two additions to the agreed design, both pure code, both inside the linear flow:**

- **Stage 0 (Preprocess)** exists because the case requires duplicates to be handled explicitly and counts to use a clear denominator (visits).
- **The verification gate** exists because the slide grades "verified outputs and limits".

**Agent 3 is implemented as deterministic code, not an LLM.** Counting and scoring must be exact, and the case explicitly asks which counts can be done deterministically. It is still the third agent in the pipeline; it just doesn't need language. If the team later wants an LLM-written one-line summary per shop, add it as an optional step in Agent 3 behind a config flag. The numbers always stay computed by code.

---

## 2. Human setup steps (Person A does these before starting Claude Code)

```bash
# 1. Create the repo (GitHub CLI). Or create it on github.com and clone it.
gh repo create juniper-briefing --private --clone
cd juniper-briefing

# 2. Invite Person B (replace with their GitHub username)
gh api -X PUT repos/<your-username>/juniper-briefing/collaborators/<B-username> -f permission=push

# 3. Python environment
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate

# 4. API key (never commit this file)
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env

# 5. Put both spec files in docs/
mkdir docs
# copy BUILD_SPEC_A_claude_code.md -> docs/BUILD_SPEC_A.md
# copy BUILD_SPEC_B_mimiwork.md   -> docs/BUILD_SPEC_B.md

git add docs && git commit -m "Add build specs" && git push
```

Tell Person B the repo is ready.

**Daily git rule:** `git pull --rebase` before every new phase, commit after every phase. Each person only edits the files they own (Section 3), so conflicts should be rare.

---

## 3. Repo structure and file ownership

```
juniper-briefing/
├── CLAUDE.md                      A   instructions Claude Code reads every session
├── README.md                      A   run instructions (part of the appendix)
├── requirements.txt               A
├── .env.example                   A   ANTHROPIC_API_KEY=
├── .gitignore                     A
├── config.yaml                    A   models, prompt versions, pricing, thresholds (B may edit prompt_versions)
│
├── codebook.yaml                  B   themes: name, label, definition, includes, excludes
├── answer_key.json                B   expected results per test
├── prompts/                       B
│   ├── agent1_tagger/v1.md
│   ├── agent2_polarity/v1.md
│   ├── agent4_brief/v1.md
│   ├── agent5_editor/v1.md
│   └── baseline/v1.md
├── data/
│   ├── batch_original.csv         A   created at setup from the case pack (Section 5.1)
│   └── tests/                     B   T01_original.csv ... T12_injection.csv
│
├── juniper/                       A   the Python package
│   ├── __init__.py
│   ├── config.py                  load config.yaml + .env
│   ├── models.py                  pydantic contracts for every stage (Section 5)
│   ├── io_utils.py                load CSV, load codebook, render prompt templates
│   ├── llm.py                     LLM client: structured output, retries, mock mode, call log
│   ├── stage0_preprocess.py
│   ├── agent1_tagger.py
│   ├── agent2_polarity.py
│   ├── agent3_scorer.py
│   ├── agent4_brief.py
│   ├── agent5_editor.py
│   ├── verify.py                  verification gate
│   ├── render.py                  builds briefing.md (counts tables injected by code)
│   ├── pipeline.py                runs the linear flow, saves every stage's output
│   ├── baseline.py                single-prompt baseline
│   └── metrics.py                 scores a run against answer_key.json
│
├── run_pipeline.py                A   CLI: run one CSV
├── run_tests.py                   A   CLI: run all tests, prototype + baseline, write results table
├── compare_runs.py                A   CLI: metric deltas between two labelled runs
├── app.py                         A   Streamlit app
│
├── fixtures/mock/                 A   canned LLM responses for mock mode (T01 at least)
├── tests/                         A   pytest unit tests
├── runs/                          A   one folder per run (gitignored, except runs/final/)
│
└── docs/
    ├── BUILD_SPEC_A.md            A
    ├── BUILD_SPEC_B.md            B
    ├── contracts.md               A   copy of Section 5 (single source of truth for both)
    ├── decisions.md               both   one line per design decision, with reason
    ├── iterations.md              both   one entry per change and its test results
    ├── rationale.md               B   one-page EDGE / 5A rationale
    └── video_script.md            B
```

**Rule for Claude Code:** never edit files owned by B. If `codebook.yaml`, a prompt, `answer_key.json` or a test CSV is missing, create a placeholder whose first line is `# PLACEHOLDER: Person B will replace this`, and report it.

---

## 4. Files to create first

### 4.1 `CLAUDE.md`

```markdown
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

## Non-negotiable rules
- All counting, scoring, ranking and deduplication is done in Python, never by an LLM.
- The unit of counting is one VISIT (visit_id). Duplicate visits count once.
- Every LLM call uses structured output validated by the pydantic models in juniper/models.py.
- Every quote must be an exact substring of its comment. verify.py enforces this.
- Prompts are read from prompts/<agent>/<version>.md. Never hardcode prompt text in Python.
- Theme list comes from codebook.yaml. Never hardcode themes in Python.
- Every run saves all intermediate outputs to runs/<timestamp>_<label>/.
- Log latency and tokens for every LLM call.
- Mock mode (provider: mock in config.yaml) must work with no API key.

## Ownership
Person B owns: codebook.yaml, answer_key.json, prompts/, data/tests/, docs/rationale.md,
docs/video_script.md, docs/BUILD_SPEC_B.md. Do not edit these. Use placeholders if missing.

## Commands
python run_pipeline.py data/batch_original.csv --label dev
python run_tests.py --label v1
python compare_runs.py runs/<a> runs/<b>
streamlit run app.py
pytest -q
```

### 4.2 `requirements.txt`

> **Amended 2026-10-13:** no paid Anthropic API key is available. Provider is now
> **Gemini (free tier), mock as the safety net**. No local-model fallback — the team
> can't run it online, so it isn't worth the extra code path. See `docs/decisions.md`.

```
streamlit>=1.38
pandas>=2.2
pydantic>=2.7
python-dotenv>=1.0
pyyaml>=6.0
pytest>=8.0
google-genai>=1.2.0
```

Pin versions that install cleanly on Streamlit Community Cloud (the deploy target).

### 4.3 `.gitignore`

```
.venv/
.env
__pycache__/
*.pyc
runs/*
!runs/final/
.streamlit/secrets.toml
```

### 4.4 `config.yaml`

> **Amended 2026-10-13:** `provider` is now `gemini | mock` (no `anthropic`, no local
> model — Ollama was dropped: it can't run on the deployed app, so it isn't worth a
> second code path for a sprint project). Pricing is reframed as an optional paid-tier
> estimate, since Gemini free tier and mock both cost €0. See `docs/decisions.md`.

```yaml
provider: gemini                # gemini | mock
                                 # gemini: free-tier Gemini Flash (needs GEMINI_API_KEY)
                                 # mock: no key, no network — reads fixtures/mock/

models:
  gemini:
    agent1_tagger: gemini-3.5-flash
    agent2_polarity: gemini-3.5-flash
    agent4_brief: gemini-3.5-flash
    agent5_editor: gemini-3.5-flash
    baseline: gemini-3.5-flash  # baseline uses the same model as the pipeline, so the comparison is fair

prompt_versions:                # bump to v2, v3... when iterating (B edits these)
  agent1_tagger: v1
  agent2_polarity: v1
  agent4_brief: v1
  agent5_editor: v1
  baseline: v1

llm:
  temperature: 0
  max_tokens: 4000
  max_retries: 3                # retry on schema validation failure, sending the error back
  agent4_concurrency: 1          # keep gemini free-tier rate limits happy
  batch_mode:
    agent1_tagger: per_comment  # small/free models are more reliable one comment at a time
    agent2_polarity: per_comment

paid_price_per_mtok_eur:        # optional; shows what the same run would cost on a paid tier.
                                 # null by default -> reported as "n/a (pricing not set)"
  gemini-3.5-flash: {input: null, output: null}

known_branches: [Central, Riverside, Station]

scoring:
  single_mention_max: 1         # mentions <= 1 -> "single mention"
  # mentions >= 2 -> "repeated"

verify:
  forbidden_phrases:            # overclaiming / causal language -> WARN
    - "all customers"
    - "every customer"
    - "customers always"
    - "everyone"
    - "caused by"
    - "because of"
    - "due to"
    - "the reason is"

app:
  max_live_runs_per_session: 5  # quota protection in the Streamlit app
```

### 4.5 `.env.example`

```
GEMINI_API_KEY=
```

`juniper/config.py` reads `GEMINI_API_KEY` and an optional `PROVIDER` override from
`st.secrets` when running under Streamlit and they exist there, otherwise from `.env` /
environment variables. Never print or log the key.

---

## 5. Contracts (copy this whole section into `docs/contracts.md`)

These are the handoff formats between stages and between Person A and Person B. Implement each as a pydantic model in `juniper/models.py`.

### 5.1 Input CSV

Columns, in this order: `comment_id,visit_id,branch,comment`

Create `data/batch_original.csv` at setup with exactly this content (from the case pack):

```csv
comment_id,visit_id,branch,comment
F01,V01,Central,"Lovely coffee, but I queued for 15 minutes before work."
F02,V02,Central,"The team was friendly. I could not find a clean table."
F03,V03,Station,"The price on the board differed from what I paid. Staff corrected it."
F04,V04,Riverside,"Quiet seats and friendly service. Good place to read."
F05,V05,Central,"Oat milk was sold out when I arrived."
F06,V06,Station,"The queue took ten minutes and I nearly missed my train."
F07,V03,Station,"The price on the board differed from what I paid. Staff corrected it."
F08,V08,Riverside,"I like the quiet corner. Could you offer a vegan pastry?"
F09,V09,Central,"Quick service today, even during the morning rush."
F10,V10,Riverside,"I ordered ahead but still waited ten minutes to collect."
F11,V11,Central,"Disappointing."
F12,V12,Riverside,"Great coffee. I had to ask twice for my receipt."
```

### 5.2 `codebook.yaml` (written by B, read by A)

```yaml
themes:
  - name: waiting_time            # snake_case, used everywhere in code
    label: Waiting time and speed # shown to the manager
    definition: Queue length, speed of service, time to collect an order (including order-ahead).
    includes: ["queue", "waited", "quick service", "slow"]
    excludes: ["staff attitude (use staff_service)"]
  # ... more themes ...
  - name: other
    label: Other
    definition: A clear topic that fits no theme above.
```

`juniper/io_utils.py` must:
- validate that names are unique and that `other` exists
- expose `codebook_as_text()`, which renders the YAML as readable text for the `{{codebook}}` prompt variable

### 5.3 Prompt templates (written by B, rendered by A)

Plain markdown with `{{variable}}` placeholders, rendered with simple string replacement. If a template still contains `{{` after rendering, raise an error.

| Prompt file | Variables it receives |
|---|---|
| `agent1_tagger/vN.md` | `{{codebook}}`, `{{comments}}` (JSON list of `{comment_id, branch, text}`) |
| `agent2_polarity/vN.md` | `{{codebook}}`, `{{tagged_comments}}` (JSON list of `{comment_id, text, themes:[{theme, quote}]}`) |
| `agent4_brief/vN.md` | `{{shop}}`, `{{theme}}`, `{{theme_label}}`, `{{theme_definition}}`, `{{stats}}` (JSON), `{{negative_evidence}}` (JSON list of `{comment_id, text, quote}`), `{{positive_evidence}}` (same shape, may be empty) |
| `agent5_editor/vN.md` | `{{batch_meta}}`, `{{shop_scores}}`, `{{briefs}}`, `{{suggestions}}`, `{{no_detail}}`, `{{priorities}}` (all JSON) |
| `baseline/vN.md` | `{{codebook}}`, `{{comments}}` (same as Agent 1) |

### 5.4 Stage 0 output: `stage0_preprocess.json` (code)

```json
{
  "comments_total": 12,
  "visits_total": 11,
  "clean_comments": [
    {"comment_id": "F01", "visit_id": "V01", "branch": "Central", "text": "Lovely coffee, ..."}
  ],
  "duplicates": [
    {"comment_id": "F07", "duplicate_of": "F03", "visit_id": "V03", "text_differs": false}
  ],
  "possible_text_duplicates": [],
  "visits_by_branch": {"Central": 5, "Riverside": 4, "Station": 2},
  "unknown_branches": [],
  "warnings": []
}
```

Rules:
- **Same `visit_id`:** keep the first comment, mark later ones as duplicates. Set `text_differs: true` if the normalised text differs.
- **Same normalised text, different `visit_id`:** keep both, add to `possible_text_duplicates`.
- **Branch not in `known_branches`:** keep it, add to `unknown_branches` and `warnings`.
- **Empty or blank comment text:** keep as a visit, add a warning. It will end up as "no usable detail".
- **Missing column, or empty CSV:** a clear error for a missing column. For an empty batch, return zero counts so the pipeline can short-circuit.

### 5.5 Agent 1 output: `agent1_tagger.json` (LLM)

```json
{
  "items": [
    {
      "comment_id": "F01",
      "usable": true,
      "themes": [
        {"theme": "coffee_quality", "quote": "Lovely coffee"},
        {"theme": "waiting_time", "quote": "queued for 15 minutes"}
      ],
      "new_theme_suggestion": null
    },
    {"comment_id": "F11", "usable": false, "themes": [], "new_theme_suggestion": null}
  ]
}
```

Code checks after the call. Retry with the error message on failure; still failing after retries means the run is marked FAIL for that stage.
- one item per clean comment, no extras, no missing items
- every theme is in the codebook
- every quote is an exact substring of the comment text, after whitespace normalisation only
- `usable: false` implies an empty themes list

### 5.6 Agent 2 output: `agent2_polarity.json` (LLM)

```json
{
  "items": [
    {
      "comment_id": "F01",
      "assessments": [
        {"theme": "coffee_quality", "polarity": "positive", "quote": "Lovely coffee", "rationale": "Praises the coffee."},
        {"theme": "waiting_time", "polarity": "negative", "quote": "queued for 15 minutes", "rationale": "Reports a long queue."}
      ]
    }
  ]
}
```

- `polarity` is one of `positive`, `negative`, `suggestion`.
- **Code check:** the set of (comment_id, theme) pairs must equal Agent 1's set exactly. No added or dropped themes, and quotes unchanged.

### 5.7 Agent 3 output: `agent3_scores.json` (code)

```json
{
  "visits_total": 11,
  "shops": {
    "Central": {
      "visits": 5,
      "themes": {
        "waiting_time": {
          "positive_ids": ["F09"], "negative_ids": ["F01"], "suggestion_ids": [],
          "n_pos": 1, "n_neg": 1, "n_sug": 0,
          "mentions": 2,
          "mention_rate": 0.4,
          "score": 0.0,
          "evidence_level": "repeated",
          "mixed": true
        }
      },
      "negative_themes_ranked": ["waiting_time", "cleanliness", "product_availability"],
      "priority_theme": "waiting_time",
      "no_detail_ids": ["F11"]
    }
  },
  "network": {
    "themes": {"waiting_time": {"n_pos": 1, "n_neg": 3, "shops_with_negative": ["Central", "Riverside", "Station"]}},
    "priority_theme": "waiting_time"
  },
  "suggestions": [{"shop": "Riverside", "theme": "menu_range", "comment_id": "F08", "quote": "Could you offer a vegan pastry?"}]
}
```

**Formulas** (document these in the README and in `docs/decisions.md`):
- `mentions = n_pos + n_neg` (suggestions are counted separately and are not part of the score)
- `mention_rate = mentions / shop visits`, rounded to 2 decimals
- `score = (n_pos - n_neg) / mentions` when mentions > 0. Range -1 (all negative) to +1 (all positive)
- `evidence_level`: `single mention` if mentions ≤ 1, otherwise `repeated`
- `mixed = n_pos > 0 and n_neg > 0`
- **Ranking negative themes within a shop** (themes with n_neg > 0), sorted by:
  1. shop `n_neg`, descending
  2. network `n_neg`, descending
  3. shop `n_pos`, ascending
  4. theme name, alphabetical
- `priority_theme`: the first ranked negative theme, or `null` if there are none
- **Network priority:** the theme with the highest network `n_neg`. Ties: the most shops affected, then the lowest network `n_pos`, then alphabetical. `null` if there are no negatives.
- Counting is per **visit**. A visit tagged twice with the same theme and polarity counts once.

### 5.8 Agent 4 output: one `ThemeBrief` per (shop, negative theme), saved as `agent4_briefs.json`

```json
{
  "shop": "Central",
  "theme": "waiting_time",
  "summary_of_comments": "One visit reported a 15-minute queue before work (F01). Another visit said service was quick during the morning rush (F09), so views are mixed.",
  "interpretation": "Possible reading: waiting times at Central may vary across the morning peak.",
  "cta": {
    "action": "Time the queue at Central between 8:00 and 9:30 on three weekdays.",
    "kind": "investigate",
    "data_needed": ["orders per 15 minutes", "staff on shift at peak"],
    "success_signal": "A clear picture of when queues exceed 10 minutes, or confirmation they rarely do."
  },
  "cited_ids": ["F01", "F09"],
  "key_quotes": [{"comment_id": "F01", "quote": "queued for 15 minutes"}]
}
```

- `kind` is `investigate` or `small_test`.
- **Code checks:** `cited_ids` must be a subset of the evidence passed in, and `key_quotes` must be exact substrings.

### 5.9 Agent 5 output: `agent5_final.json` (LLM)

```json
{
  "headline": "Waiting time is the only issue raised at all three branches this week.",
  "shops": [
    {
      "shop": "Central",
      "overview": "Customers praised the coffee and friendly staff. Problems raised: waiting time (mixed views), table cleanliness, oat milk availability.",
      "priority_theme": "waiting_time",
      "cited_ids": ["F01", "F02", "F05", "F09"]
    }
  ],
  "network_priority": {
    "theme": "waiting_time",
    "reason": "Raised at Central, Riverside and Station; the only problem seen at more than one branch.",
    "action": "Time queues at all three branches during the morning peak for one week.",
    "cited_ids": ["F01", "F06", "F10"]
  },
  "requests": ["Riverside: a customer asked for a vegan pastry option (F08)."],
  "mixed_views_note": "Central: one visit reported a long queue (F01), another praised quick service (F09).",
  "limitations": "Convenience sample of 11 visits, not a survey. One forwarded duplicate (F07) counted once. One comment had no usable detail (F11). Station has only 2 visits."
}
```

- `priority_theme` must equal Agent 3's value. Code overwrites it if the LLM disagrees, and logs a warning.
- **Agent 5 never produces counts tables.** `render.py` injects them from `agent3_scores.json`.

### 5.10 Baseline output: `baseline.json` (single LLM call, scored with the same metrics)

```json
{
  "visits_total": 12,
  "duplicates_noticed": [],
  "shops": [
    {
      "shop": "Central",
      "visits": 5,
      "themes": [
        {"theme": "waiting_time", "n_pos": 1, "n_neg": 1, "positive_ids": ["F09"], "negative_ids": ["F01"]}
      ],
      "summary": "...",
      "actions": [{"theme": "waiting_time", "action": "..."}]
    }
  ]
}
```

The baseline receives the same codebook and the same comments, but no preprocessing, no code checks and no pipeline. That isolates exactly what the pipeline adds.

### 5.11 Review record: `review.json` (written by the Streamlit app)

```json
{
  "status": "approved",
  "edited_markdown": null,
  "notes": "Will time the queues this week.",
  "gate_status_at_review": "WARN",
  "override_gate": false,
  "reviewed_at": "2026-10-13T16:40:00+02:00"
}
```

`status` is `approved`, `edited` or `rejected`.

---

## 6. Build phases

Each phase ends with passing tests and a commit. Times are elapsed sprint time.

### Phase 1 · Foundation (0:20 to 0:40)

1. Create the files in Section 4, plus `data/batch_original.csv`.
2. `juniper/config.py`: load `config.yaml` and `.env`. Expose a `Config` object.
3. `juniper/models.py`: pydantic models for every contract in Section 5.
4. `juniper/io_utils.py`: `load_comments(csv_path)`, `load_codebook(path)`, `codebook_as_text()`, `render_prompt(agent, version, **vars)`.
5. `juniper/stage0_preprocess.py`, implementing every rule in 5.4.
6. **Placeholders** for anything B hasn't delivered yet: `codebook.yaml` with the 10 starter themes from `BUILD_SPEC_B` Section 5, plus minimal prompt files.
7. **Tests** (`tests/test_stage0.py`): the original batch gives 12 comments, 11 visits, F07 as a duplicate of F03, and Central 5 / Riverside 4 / Station 2. Also test an empty CSV, an unknown branch, the same visit with different text, and the same text with different visits.

Commit: `Phase 1: foundation and preprocessing`

### Phase 2 · LLM client and mock mode (0:40 to 0:55)

> **Amended 2026-10-13:** replaces the Anthropic-only version. No paid API key is
> available; providers are Gemini (free tier) and mock (safety net). No local-model
> fallback — the team can't run Ollama online, so it was dropped rather than carry a
> second, mostly-unused code path. See `docs/decisions.md`.

`juniper/llm.py` — same interface regardless of provider:

- `call_structured(agent_name, prompt_text, output_model) -> (parsed_model, CallLog)`
- **Gemini** (`google-genai` SDK): `temperature=0`, `response_mime_type="application/json"`,
  `response_schema` set to the pydantic model class itself (the SDK converts it,
  including `Optional` and nested fields, without a hand-built JSON schema). If the
  API rejects the schema, fall back to plain JSON mode and append the JSON schema to
  the prompt text instead.
- **Mock provider:** if `provider: mock`, load `fixtures/mock/<test_id>/<agent>.json` and
  return it with latency 0 and tokens 0. Create mock fixtures for T01 by hand, matching
  the expected answer in `BUILD_SPEC_B` Section 7.1.
- Comment text is always wrapped in `<comments>...</comments>` delimiters inside the
  prompt (B's templates already do this).
- **On validation error:** always validate the parsed response with pydantic; on
  failure, retry up to `max_retries` times, appending the validation error to the
  prompt ("Your previous output failed validation: ... Return corrected JSON.").
- **On rate-limit / quota error** (HTTP 429 or "resource exhausted"): back off
  exponentially (2s, 4s, 8s), then raise a clear `ProviderUnavailable` error — callers
  (the Streamlit app especially) must catch this and degrade gracefully, not crash.
- **`CallLog`:** `agent, provider, model, prompt_version, latency_s, input_tokens,
  output_tokens, cost_eur (always 0.0 for gemini free tier and mock),
  cost_eur_if_paid_est (null unless `paid_price_per_mtok_eur` is set), retries, ok`.

`check_llm.py`: a CLI that sends one tiny structured request to the configured
provider and prints OK, latency and tokens. Supports `--provider`.

**Tests:** in mock mode, every agent's fixture validates against its model; the retry
logic works correctly against a fake client that fails validation once then succeeds.

Commit: `Phase 2: LLM client (gemini/mock) with structured output and retries`

### Phase 3 · Agents 1 and 2 (0:55 to 1:10)

- `agent1_tagger.py`: build the `{{comments}}` JSON from Stage 0's clean comments, call the LLM, then run the checks in 5.5. `batch_mode: per_comment` makes one call per comment and merges the results (same output shape).
- `agent2_polarity.py`: build `{{tagged_comments}}` from the Agent 1 output plus the text, call the LLM, then run the checks in 5.6.
- Both write their JSON to the run folder.

**Tests:** in mock mode, T01 passes all the checks. Unit tests should also show the checks catching a fake quote, an unknown theme, a missing comment, and an added or dropped theme in Agent 2.

Commit: `Phase 3: agents 1 and 2 with validation`

### ⏸ CHECKPOINT 1 (about 1:10) · with Person B

- Pull B's real `codebook.yaml` and the Agent 1 and 2 prompts.
- Run `python run_pipeline.py data/batch_original.csv --label cp1 --until agent2` with the real provider.
- Compare the tags with B's answer key for T01 together. Fix prompts (B) or code (A) before moving on.

### Phase 4 · Agent 3 scorer (1:10 to 1:20)

`agent3_scorer.py` implements every formula and ranking rule in 5.7 exactly. Pure Python, no LLM.

**Tests:** fed with the T01 mock Agent 2 output, the result must match B's T01 expectations exactly:
- the score per shop and theme
- `priority_theme` = `waiting_time` for every shop
- network priority = `waiting_time`
- the suggestions list contains F08

Commit: `Phase 4: deterministic shop scorer`

### Phase 5 · Agents 4 and 5, rendering (1:20 to 1:40)

- **`agent4_brief.py`:** one call for every (shop, theme) where `n_neg > 0`, run in parallel with `ThreadPoolExecutor(max_workers=agent4_concurrency)`. Pass `stats` = that theme's Agent 3 entry plus shop visits. Pass negative evidence and positive evidence (for mixed views). Check the outputs as in 5.8.
- **`agent5_editor.py`:** a single call. Then overwrite `priority_theme` and `network_priority.theme` with Agent 3's values, logging a warning if they differed.
- **`render.py`:** build `briefing.md` with:
  1. a header (week, visits, comments, duplicates removed)
  2. the headline
  3. network priority with its action
  4. one section per shop: overview, a **counts table from Agent 3** (theme | positive | negative | score | evidence | comment IDs), then the Agent 4 briefs for that shop, each with its CTA
  5. requests
  6. mixed views
  7. limitations
  8. a "Removed or excluded" list (duplicates, no detail, possible text duplicates)
- **Short-circuit:** if there are 0 visits, skip all LLM calls and render "No feedback received this week." Cost 0.

Commit: `Phase 5: briefs, final editor, rendering`

### Phase 6 · Verification gate (1:40 to 1:50)

`verify.py` produces `verification.json`: a list of checks, each with `PASS`, `WARN` or `FAIL` plus details, and an overall status (the worst of them).

| ID | Check | Failure level |
|---|---|---|
| V1 | Every cited ID (Agents 4 and 5) exists in the clean comments | FAIL |
| V2 | Every ID cited in a shop section belongs to that shop | FAIL |
| V3 | Every quote is an exact substring of its comment | FAIL |
| V4 | Every number written in LLM prose (Agents 4 and 5) exists in that shop's or the network's Agent 3 numbers or in `batch_meta`. Extract digits with a regex and ignore times like "8:00" | WARN |
| V5 | Every (shop, negative theme) has exactly one brief with a CTA | FAIL |
| V6 | No forbidden phrases (from config) in LLM prose | WARN |
| V7 | Duplicates and no-detail comments are disclosed in the limitations or the excluded list | FAIL |
| V8 | Every stage's output validated against its schema | FAIL |
| V9 | Agent 5's priority agrees with Agent 3's (before the overwrite) | WARN |
| V10 | A duplicate comment ID (for example F07) is never cited as evidence | FAIL |

`pipeline.py` runs the stages in order, saves every output to `runs/<timestamp>_<label>/` (including a `config_snapshot.yaml` and `call_log.json`), and returns a `RunResult`. It supports `--from <stage>` to reuse saved upstream outputs from an earlier run folder, so iterating on Agent 4 doesn't re-pay for Agents 1 and 2.

**Tests:** the gate catches an injected fake quote, a wrong shop ID and a cited duplicate.

Commit: `Phase 6: verification gate and pipeline`

### ⏸ CHECKPOINT 2 (about 1:50) · FEATURE FREEZE

Do a full real run on T01, then open `briefing.md` together. From here on: fixes only, and tests.

### Phase 7 · Baseline, metrics and test runner (1:50 to 2:05)

> **Amended 2026-10-13:** `run_pipeline.py` and `run_tests.py` accept `--provider`
> (`gemini | mock`). The results table reports cost as "€0 (free tier)" and shows
> `cost_eur_if_paid_est` only when `paid_price_per_mtok_eur` is set.

- **`baseline.py`:** a single call with `prompts/baseline/vN.md` and the `baseline` model, output schema 5.10. Logs latency and cost the same way.
- **`metrics.py`** scores any run against `answer_key.json[test_id]`:

| Metric | Definition | Prototype source | Baseline source |
|---|---|---|---|
| `dedupe_ok` | duplicates found equal the expected ones | Stage 0 | `duplicates_noticed` and `visits_total` |
| `visit_count_ok` | total and per-branch visits exact | Stage 0 | baseline counts |
| `theme_recall` | required tags found / required tags | Agent 2 | baseline theme IDs |
| `theme_precision` | found tags in (required ∪ optional) / found tags | Agent 2 | baseline |
| `polarity_accuracy` | correct polarity / matched tags | Agent 2 | baseline pos/neg IDs |
| `count_accuracy` | shop × theme (n_pos, n_neg) exactly right / expected cells | Agent 3 | baseline |
| `negative_coverage` | expected (shop, negative theme) with a brief and CTA / expected | Agent 4 | baseline actions |
| `priority_ok` | network priority equals expected | Agent 3 | n/a |
| `factual_support` | share of verification checks V1 to V3 and V10 that pass | gate | run the same checks on the baseline's IDs |
| `special_ok` | the test's special expectation holds (see B's answer key: empty batch, injection, new branch...) | run | baseline |
| `latency_s` | total wall-clock time | call log | call log |
| `cost_eur_est` | sum over calls | call log | call log |
| `llm_calls` | number of calls | call log | call log |

**Task success for a test** = every hard expectation passes: `dedupe_ok`, `visit_count_ok`, `count_accuracy == 1`, `negative_coverage == 1`, `special_ok`, and gate status not FAIL. Recall, precision and polarity are reported but are soft.

- **`run_tests.py`:**
  - For each `data/tests/T*.csv`, run the prototype and the baseline and score both.
  - Write `runs/<ts>_<label>/results.csv` and `results.md`. The markdown table has the columns: test, condition, expected behaviour (from the answer key `description`), baseline result, prototype result, pass/fail, latency, cost.
  - Print a summary: task success rate, mean metrics, total and mean latency, total cost, for both systems.
  - Flags: `--only T05`, `--skip-baseline`, `--label`.
- **`compare_runs.py`:** shows the delta for every metric between two run folders. Use it to show iteration gains.

Commit: `Phase 7: baseline, metrics, test runner`

### Phase 8 · Streamlit app (2:05 to 2:20, can run in parallel with testing)

> **Amended 2026-10-13:** the app must be deployable on Streamlit Community Cloud with
> one click, with no guarantee of a Gemini key at any given moment (free-tier quota,
> or no key configured at all). See the four additions below, folded into the tab list.

`app.py`. Keep it clean and simple, using `st.tabs`:

1. **Run:**
   - a sample-batch dropdown listing every file in `data/tests/` (default `T01`), so the
     reviewer doesn't need to upload anything; uploading a CSV is still allowed
   - a startup availability check for Gemini (is a key configured?); if not, the Run
     tab falls back to mock and says so
   - a "Run pipeline" button, disabled past `app.max_live_runs_per_session` live runs
     for this session
   - a live progress line per stage using `st.status`, showing the stage name, its time
     and its token cost
   - results are cached with `st.cache_data`, keyed by a hash of the CSV + config +
     provider, so re-running the same input doesn't re-spend quota
   - if `ProviderUnavailable` is raised, show "Live model unavailable right now, see the
     Demo tab" instead of crashing
2. **Briefing:** the rendered `briefing.md`, with the gate status badge at the top (green PASS, amber WARN, red FAIL) and expanders listing every WARN and FAIL.
3. **Evidence:**
   - a filter by shop and theme
   - a table of comment ID, branch, comment text, themes and polarity
   - duplicates and no-detail comments shown greyed with a reason
4. **Pipeline trace:** one expander per stage showing its raw JSON output, its latency and its tokens. This shows the linear multi-agent flow in the demo.
5. **Review:**
   - an editable text area with the briefing markdown
   - Approve / Save edits / Reject buttons, plus notes
   - if the gate is FAIL, Approve is disabled unless "I have checked the failures" is ticked and a note is written
   - writes `review.json`
6. **Metrics:** if a `results.md` exists for the latest test run, display it.
7. **Demo (saved results):** loads `runs/final/` — briefing, evidence, pipeline trace,
   verification and `results.md` (prototype vs baseline). Works with no key and no
   network. If no live provider is available at startup, this tab opens by default with
   the note "Showing saved results from our final test run."

Caching: `st.session_state` holds the current `RunResult`.

Commit: `Phase 8: Streamlit review app`

### Phase 9 · Test phase support and packaging (2:20 to 3:00)

- Run `python run_tests.py --label v1`. Share `results.md` with B.
- B changes prompts, as new versions (v2) only. Bump `config.yaml`, then run `python run_tests.py --label v2` and `python compare_runs.py runs/<v1> runs/<v2>`.
- Copy the final run folder to `runs/final/` and commit it. It's evidence for the appendix.
- **README.md:**
  - what it does
  - the architecture diagram (the one from Section 1)
  - setup (venv, `.env`)
  - how to run the pipeline, the tests and the app
  - mock mode
  - the models used
  - the scoring formulas
  - where results are
  - known limitations
  - team contributions (copy from `BUILD_SPEC_B` Section 12)
  - **Try it online:** the app link, with a note that the first load can take a minute
    because the app sleeps
  - **Run locally with Gemini:** get a free key from Google AI Studio, put it in `.env`
  - **Run with no key at all:** `--provider mock`, or just the Streamlit app's Demo tab
  - **Deploy:** share.streamlit.io, main file `app.py`, Secrets containing
    `GEMINI_API_KEY` and `PROVIDER = "gemini"`
- **Appendix zip:** `git archive -o juniper-briefing.zip HEAD`, plus `runs/final/`.

---

## 7. Built-in room for iteration

| Lever | How to change it | Where results show |
|---|---|---|
| Prompt wording | B adds `prompts/<agent>/v2.md` and bumps `prompt_versions` | `compare_runs.py v1 v2` |
| Model per agent | edit `models:` in `config.yaml` (for example Haiku vs Sonnet for Agent 1) | latency, cost and accuracy deltas |
| Batch vs per-comment tagging | `batch_mode` | recall vs latency trade-off |
| Codebook | B edits `codebook.yaml` (log it in `iterations.md`) | recall and precision |
| Scoring and ranking rules | `agent3_scorer.py` + `docs/decisions.md` entry | priority_ok |
| Rerun from a stage | `run_pipeline.py --from agent4 --reuse runs/<folder>` | saves cost while iterating |
| New test | B adds `data/tests/T13_*.csv` + answer key entry | picked up automatically |

**Every change gets one entry in `docs/iterations.md`:**

```markdown
## <time> · <agent or component> · v1 -> v2
- Change:
- Why (which test or metric failed):
- Result: task success x/12 -> y/12; recall a -> b; cost c -> d; latency e -> f
- Keep? yes / no
```

**Possible later iterations (only after all tests pass):**
- an optional LLM one-line summary in Agent 3 behind a flag
- week-over-week trend comparison
- a scheduled weekly run (Automation)
- voice-note input transcribed to CSV, labelled as a simulated integration

---

## 8. Definition of done (Person A)

- [ ] `pytest -q` passes
- [ ] `python run_pipeline.py data/batch_original.csv` works in mock mode, and in gemini mode when a key is available
- [ ] `python run_tests.py` produces `results.md` for 12 or more tests, prototype vs baseline, with latency and cost
- [ ] the T01 gate is PASS or WARN, and every WARN is explained
- [ ] the Streamlit app runs: sample-batch dropdown or upload, run, briefing, evidence, trace, review, metrics, demo tab
- [ ] the app is deployed on Streamlit Community Cloud and loads with no key (Demo tab)
- [ ] `review.json` is written on approval
- [ ] `runs/final/` committed
- [ ] README complete, with run instructions and contributions
- [ ] appendix zip created

---

## 9. Handoffs with Person B

| When | A gives B | B gives A |
|---|---|---|
| 0:20 | repo ready, `docs/contracts.md` | n/a |
| 0:50 | n/a | `codebook.yaml`, prompts v1 for Agents 1 and 2, `answer_key.json` (T01) |
| 1:10 | Checkpoint 1 output (tags) | prompt fixes if needed |
| 1:30 | n/a | prompts v1 for Agents 4, 5 and the baseline, test CSVs T02 to T12, answer key complete |
| 2:05 | first `results.md` | review ratings for CTAs (rubric in B's spec), prompt v2s |
| 2:40 | `runs/final/`, README | rationale, video script |
