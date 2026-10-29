# Juniper Café Feedback Briefing

Live app: https://juniper-briefing.streamlit.app

Juniper Café is a small café with three shops. Every week, its manager has to read through lots of customer comments and work out what really needs fixing. It's easy to focus on the one angry message and miss the smaller problems that keep coming up.

This app reads the comments for them. It shows what customers keep mentioning at each shop, how many people said it, and their actual words, then suggests one small thing to try first. The manager still decides what to do.

## How it works

The work is split so that AI only does the parts that need judgement. Counting,
duplicate checks and ranking are plain code.

```
CSV ──► Clean up (code): remove duplicate visits, check the data, count visits
    ──► Tag topics (Gemini)
    ──► Judge positive or negative (Gemini)
    ──► Score and rank issues per branch (code)
    ──► Write a short brief and next step per issue (Gemini)
    ──► Edit everything into one briefing (Gemini)
    ──► Check the briefing (code)
    ──► Manager review in Streamlit: approve / edit / reject
```

- **User:** the operations manager
- **Goal:** better decisions first, less prep time second
- **Form:** a Streamlit app
- **Model:** Google Gemini Flash (free tier)

## Testing

We compared the app against a simple baseline (one prompt doing everything) on 12 test
batches in `data/tests/`, including:

- the original batch from the case
- an empty file
- extra duplicates, and the same visit with new text
- a comment with two opposing opinions
- a new branch the app hasn't seen before
- comments with no real detail
- a batch where everything is positive
- one dramatic complaint against several quieter repeated ones
- comments in French
- a comment that tries to give the AI instructions (prompt injection)

`answer_key.json` holds the expected results, and `compare_runs.py` shows how two runs
differ.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# edit .env and set GEMINI_API_KEY=...
```

No API key? Set `provider: mock` in `config.yaml` and everything runs on saved sample
outputs in `fixtures/mock/`.

## Run

```bash
streamlit run app.py                                          # the manager app
python run_pipeline.py data/batch_original.csv --label dev    # run once from the command line
python run_tests.py --label v1                                # run all test batches, app + baseline
python compare_runs.py runs/<a> runs/<b>                      # compare two runs
pytest -q                                                     # unit tests
```

## Limitations

- The comments are a convenience sample, not a survey, so the counts show what was
  mentioned, not how all customers feel.
- The app points to things worth checking. It does not say why a problem happens.
- It runs on Gemini's free tier, so a full briefing can take a little while and live
  runs in the app are capped per session.
- The café, branches and comments are fictional teaching material.
