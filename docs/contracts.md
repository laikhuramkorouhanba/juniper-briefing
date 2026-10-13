# Contracts (copy of BUILD_SPEC_A Section 5; single source of truth for A and B)

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
