"""Weekly feedback briefing — café operations manager view.

Phase 8 (docs/BUILD_SPEC_A.md). This is the only file a manager ever opens:
plain café language throughout, no mention of agents, stages, prompts, tokens
or schemas in the main view. All of that technical detail still exists (it's
needed for the course demo) but lives in one collapsed "Behind the scenes"
section at the bottom.

Prefers the real `juniper.pipeline.run_pipeline` (Phase 6, built in a parallel
session). Every optional module is still imported defensively — if the real
pipeline or verification isn't there (or its signature changes), this falls
back to a minimal Stage 0-3 run and says so in `_behind_the_scenes`, instead
of crashing the manager's screen.
"""

from __future__ import annotations

import hashlib
import importlib
import io
import json
import os
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parent
# render_prompt() / codebook loading resolve relative paths against the process
# cwd, so make that reliable regardless of how `streamlit run` was launched.
os.chdir(REPO_ROOT)

from juniper.config import Config, load_config
from juniper.io_utils import load_codebook, load_comments
from juniper.llm import ProviderUnavailable, StructuredCallFailed
from juniper.models import ReviewRecord

DATA_TESTS_DIR = REPO_ROOT / "data" / "tests"
CODEBOOK_PATH = REPO_ROOT / "codebook.yaml"
RUNS_DIR = REPO_ROOT / "runs"
FINAL_DIR = RUNS_DIR / "final"

st.set_page_config(page_title="Juniper Café — Weekly Briefing", layout="wide")


# ---------------------------------------------------------------------------
# Optional modules — loaded defensively (see module docstring).
# ---------------------------------------------------------------------------


def _try_import(module_name: str):
    try:
        return importlib.import_module(module_name)
    except ImportError:
        return None


pipeline_mod = _try_import("juniper.pipeline")
from juniper.stage0_preprocess import preprocess
from juniper.agent1_tagger import tag_comments
from juniper.agent2_polarity import judge_polarity
from juniper.agent3_scorer import score as score_agent3

agent4_mod = _try_import("juniper.agent4_brief")
agent5_mod = _try_import("juniper.agent5_editor")
verify_mod = _try_import("juniper.verify")
render_mod = _try_import("juniper.render")


def _first_callable(module, names: list[str]):
    if module is None:
        return None
    for name in names:
        fn = getattr(module, name, None)
        if callable(fn):
            return fn
    return None


# ---------------------------------------------------------------------------
# Run result + orchestration
# ---------------------------------------------------------------------------


@dataclass
class RunResult:
    label: str
    provider: str
    test_id: Optional[str]
    run_dir: Optional[Path]
    stage0: Any
    agent1: Any = None
    agent2: Any = None
    agent3: Any = None
    agent4: Any = None
    agent5: Any = None
    verification: Any = None
    briefing_md: str = ""
    call_logs: list = field(default_factory=list)
    stage_timings: dict = field(default_factory=dict)
    pending_stages: list = field(default_factory=list)
    status: str = "OK"


def _clean_csv_bytes(raw: bytes) -> bytes:
    """Strip leading '#'-comment lines (e.g. a stray placeholder marker row) so
    a placeholder test CSV doesn't break the real header/columns parse."""
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    kept = [ln for ln in lines if not ln.lstrip().startswith("#")]
    return ("\n".join(kept) + "\n").encode("utf-8")


def _stage_tokens(logs: list) -> int:
    return sum(l.input_tokens + l.output_tokens for l in logs)


def _run_with_real_pipeline(csv_path: Path, *, provider: str, label: str, test_id, config: Config) -> RunResult:
    run_pipeline_fn = pipeline_mod.run_pipeline
    pr = run_pipeline_fn(csv_path, label=label, config=config, test_id=test_id)
    pending = []
    if pr.status == "PROVIDER_UNAVAILABLE":
        raise ProviderUnavailable(pr.error or "live connection unavailable")
    if pr.status == "FAIL":
        pending.append(f"a step could not be completed and checked automatically ({pr.error})")
    if pr.agent4 is None:
        pending.append("suggested next steps per branch")
    if pr.agent5 is None:
        pending.append("the written overview")
    if pr.verification is None:
        pending.append("the automatic quote check")
    return RunResult(
        label=pr.label,
        provider=pr.provider,
        test_id=test_id,
        run_dir=pr.run_dir,
        stage0=pr.stage0,
        agent1=pr.agent1,
        agent2=pr.agent2,
        agent3=pr.agent3,
        agent4=pr.agent4,
        agent5=pr.agent5,
        verification=pr.verification,
        briefing_md=pr.briefing_md or _fallback_briefing_md(pr.stage0, pr.agent3, pr.agent4, pr.agent5, pending),
        call_logs=pr.call_logs,
        pending_stages=pending,
        status=pr.status,
    )


def _run_minimal(csv_bytes: bytes, *, provider: str, label: str, test_id, config: Config) -> RunResult:
    """Stage 0 -> Agent 1 -> Agent 2 -> Agent 3, plus whatever of Agent 4/5/
    verify/render happens to already be importable. Used only if the real
    pipeline module isn't available at all."""
    codebook = load_codebook(CODEBOOK_PATH)
    call_logs: list = []
    stage_timings: dict = {}
    pending: list = []

    df = load_comments(io.BytesIO(_clean_csv_bytes(csv_bytes)))
    t0 = time.monotonic()
    stage0 = preprocess(df, config.known_branches)
    stage_timings["stage0"] = {"elapsed_s": time.monotonic() - t0, "tokens": 0}

    if not stage0.clean_comments:
        return RunResult(
            label=label, provider=provider, test_id=test_id, run_dir=None, stage0=stage0,
            briefing_md="No feedback received this week.", call_logs=call_logs,
            stage_timings=stage_timings, pending_stages=pending,
        )

    t0 = time.monotonic()
    agent1, logs1 = tag_comments(stage0.clean_comments, codebook, config=config, test_id=test_id)
    call_logs.extend(logs1)
    stage_timings["agent1"] = {"elapsed_s": time.monotonic() - t0, "tokens": _stage_tokens(logs1)}

    t0 = time.monotonic()
    agent2, logs2 = judge_polarity(agent1, stage0.clean_comments, codebook, config=config, test_id=test_id)
    call_logs.extend(logs2)
    stage_timings["agent2"] = {"elapsed_s": time.monotonic() - t0, "tokens": _stage_tokens(logs2)}

    t0 = time.monotonic()
    agent3 = score_agent3(agent2, stage0.clean_comments, stage0, single_mention_max=config.single_mention_max)
    stage_timings["agent3"] = {"elapsed_s": time.monotonic() - t0, "tokens": 0}

    agent4 = None
    fn4 = _first_callable(agent4_mod, ["write_briefs", "generate_briefs", "run"])
    if fn4 is None:
        pending.append("suggested next steps per branch")
    else:
        try:
            agent4, logs4 = fn4(agent3, agent2, stage0.clean_comments, codebook, config=config, test_id=test_id)
            call_logs.extend(logs4)
        except Exception:  # noqa: BLE001 - must not crash the manager's screen
            pending.append("suggested next steps per branch")

    agent5 = None
    agent5_warnings: list = []
    fn5 = _first_callable(agent5_mod, ["edit_briefing", "write_final_briefing", "run"])
    if fn5 is None:
        pending.append("the written overview")
    else:
        try:
            agent5, log5, agent5_warnings = fn5(stage0, agent3, agent4, config=config, test_id=test_id)
            if log5 is not None:
                call_logs.append(log5)
        except Exception:  # noqa: BLE001
            pending.append("the written overview")

    briefing_md = ""
    fn_render = _first_callable(render_mod, ["render_briefing", "render", "build_briefing"])
    if fn_render is not None and agent4 is not None and agent5 is not None:
        try:
            briefing_md = fn_render(stage0, agent3, agent4, agent5, label=label)
        except Exception:  # noqa: BLE001
            pass
    if not briefing_md:
        briefing_md = _fallback_briefing_md(stage0, agent3, agent4, agent5, pending)

    verification = None
    fn_verify = _first_callable(verify_mod, ["verify_run", "run_verification", "verify"])
    if fn_verify is None:
        pending.append("the automatic quote check")
    else:
        try:
            verification = fn_verify(
                stage0, agent3, agent4, agent5,
                config=config, agent5_warnings=agent5_warnings, briefing_md=briefing_md,
            )
        except Exception:  # noqa: BLE001
            pending.append("the automatic quote check")

    result = RunResult(
        label=label, provider=provider, test_id=test_id, run_dir=None, stage0=stage0,
        agent1=agent1, agent2=agent2, agent3=agent3, agent4=agent4, agent5=agent5,
        verification=verification, briefing_md=briefing_md, call_logs=call_logs,
        stage_timings=stage_timings, pending_stages=pending,
    )
    result.run_dir = _save_run(result, config)
    return result


def _fallback_briefing_md(stage0, agent3, agent4, agent5, pending: list) -> str:
    """A minimal, honest briefing built straight from Stage 0 / Agent 3 numbers,
    used while the written overview isn't available. Counts always come from
    code, never from an LLM."""
    lines: list[str] = ["# Weekly Briefing", ""]
    lines.append(
        f"{stage0.visits_total} visits (from {stage0.comments_total} comments, "
        f"{len(stage0.duplicates)} duplicate(s) removed)."
    )
    lines.append("")
    if agent5 is not None:
        lines.append(f"## {agent5.headline}")
        lines.append("")
    for shop, shop_score in (agent3.shops.items() if agent3 else []):
        lines.append(f"## {shop}")
        lines.append(f"Visits: {shop_score.visits}")
        lines.append("")
        for theme_name, ts in shop_score.themes.items():
            ids = ", ".join(ts.positive_ids + ts.negative_ids)
            lines.append(f"- {theme_name}: {ts.n_pos} positive, {ts.n_neg} negative ({ids})")
        lines.append("")
    if pending:
        lines.append("---")
        lines.append("_Not available in this briefing yet: " + ", ".join(pending) + "._")
    return "\n".join(lines)


def _save_run(result: RunResult, config: Config) -> Path:
    """Only used by the Stage-0-3-only fallback path — the real pipeline saves
    its own run folder."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUNS_DIR / f"{ts}_{result.label}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "stage0_preprocess.json").write_text(result.stage0.model_dump_json(indent=2))
    for name, obj in (("agent1_tagger", result.agent1), ("agent2_polarity", result.agent2),
                      ("agent3_scores", result.agent3), ("agent4_briefs", result.agent4),
                      ("agent5_final", result.agent5), ("verification", result.verification)):
        if obj is not None and hasattr(obj, "model_dump_json"):
            (run_dir / f"{name}.json").write_text(obj.model_dump_json(indent=2))
    (run_dir / "briefing.md").write_text(result.briefing_md)
    (run_dir / "call_log.json").write_text(json.dumps([log.model_dump() for log in result.call_logs], indent=2))
    return run_dir


def _run(csv_bytes: bytes, csv_path: Optional[Path], *, provider: str, label: str, test_id, config: Config) -> RunResult:
    if pipeline_mod is not None and hasattr(pipeline_mod, "run_pipeline"):
        # Always hand the real pipeline a cleaned file on disk (strips a stray
        # leading '#'-comment marker row some sample CSVs have), whether the
        # comments came from a saved sample or an upload.
        clean_bytes = _clean_csv_bytes(csv_bytes)
        if csv_path is not None and clean_bytes == csv_path.read_bytes():
            real_path = csv_path
        else:
            tmp_dir = RUNS_DIR / ".uploads"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            real_path = tmp_dir / f"{label}_{hashlib.sha256(clean_bytes).hexdigest()[:8]}.csv"
            real_path.write_bytes(clean_bytes)
        return _run_with_real_pipeline(real_path, provider=provider, label=label, test_id=test_id, config=config)
    return _run_minimal(csv_bytes, provider=provider, label=label, test_id=test_id, config=config)


# ---------------------------------------------------------------------------
# Cache (manual, session-scoped): keyed on CSV bytes + provider + config, so
# re-creating a briefing for the same week in the same session doesn't spend
# the live connection's quota again.
# ---------------------------------------------------------------------------


def _cache_key(csv_bytes: bytes, provider: str, config: Config) -> str:
    h = hashlib.sha256()
    h.update(csv_bytes)
    h.update(provider.encode())
    h.update(json.dumps(config.raw, sort_keys=True, default=str).encode())
    return h.hexdigest()


def _get_run_cache() -> dict:
    return st.session_state.setdefault("run_cache", {})


# ---------------------------------------------------------------------------
# Café-language helpers
# ---------------------------------------------------------------------------


def _label_map() -> dict[str, str]:
    try:
        codebook = load_codebook(CODEBOOK_PATH)
        return {t.name: t.label for t in codebook.themes}
    except Exception:  # noqa: BLE001
        return {}


def _friendly(theme_name: str, labels: dict[str, str]) -> str:
    return labels.get(theme_name, theme_name.replace("_", " ").capitalize())


def _prettify_briefing(md: str, labels: dict[str, str]) -> str:
    """Swap internal theme slugs (e.g. `waiting_time`) for their plain labels
    wherever they appear as a whole word, purely for display — the saved
    briefing.md on disk is untouched."""
    for name, label in sorted(labels.items(), key=lambda kv: -len(kv[0])):
        md = md.replace(f"`{name}`", label).replace(f"| {name} |", f"| {label} |")
        md = md.replace(f"### {name}", f"### {label}")
        md = md.replace(f"**{name}**", f"**{label}**")
    return md


def _list_sample_batches() -> list[Path]:
    if not DATA_TESTS_DIR.exists():
        return []
    return sorted(DATA_TESTS_DIR.glob("*.csv"))


def _test_id_from_path(path: Path) -> str:
    return path.stem.split("_")[0]


def _branch_order(shops: dict, known_branches: list[str]) -> list[str]:
    ordered = [b for b in known_branches if b in shops]
    ordered += sorted(b for b in shops if b not in ordered)
    return ordered


def _top_issue(shop_score, labels: dict[str, str]) -> Optional[str]:
    if not shop_score.priority_theme:
        return None
    return _friendly(shop_score.priority_theme, labels)


def _went_well(shop_score, labels: dict[str, str]) -> Optional[str]:
    candidates = [
        (name, ts) for name, ts in shop_score.themes.items() if ts.n_pos > 0 and ts.score >= 0
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda kv: (-kv[1].n_pos, -kv[1].score, kv[0]))
    return _friendly(candidates[0][0], labels)


def _next_step(shop: str, shop_score, agent4) -> Optional[str]:
    if agent4 is None or not shop_score.priority_theme:
        return None
    for brief in agent4.briefs:
        if brief.shop == shop and brief.theme == shop_score.priority_theme:
            return brief.cta.action
    return None


def _plain_gate_message(verification) -> tuple[str, str]:
    """-> (kind, message), kind in {"success", "warning", "error", "info"}."""
    if verification is None:
        return "info", "We couldn't double-check this briefing automatically this time."
    status = getattr(verification, "overall_status", "WARN")
    non_pass = [c for c in getattr(verification, "checks", []) if c.status != "PASS"]
    if status == "PASS":
        return "success", "All quotes checked against real comments."
    n = len(non_pass)
    noun = "thing needs" if n == 1 else "things need"
    kind = "error" if status == "FAIL" else "warning"
    return kind, f"{n} {noun} your attention before you approve this."


def _evidence_table(result: RunResult, labels: dict[str, str]) -> pd.DataFrame:
    stage0 = result.stage0
    dup_reason = {d.comment_id: "Not used — same visit as another comment, already counted" for d in stage0.duplicates}
    no_detail_ids: set[str] = set()
    if result.agent3 is not None:
        for shop_score in result.agent3.shops.values():
            no_detail_ids.update(shop_score.no_detail_ids)

    themes_by_comment: dict[str, list[str]] = {}
    if result.agent2 is not None:
        for item in result.agent2.items:
            themes_by_comment[item.comment_id] = [_friendly(a.theme, labels) for a in item.assessments]
    elif result.agent1 is not None:
        for item in result.agent1.items:
            themes_by_comment[item.comment_id] = [_friendly(t.theme, labels) for t in item.themes]

    rows = []
    for c in stage0.clean_comments:
        note = "Not used — no specific feedback in this comment" if c.comment_id in no_detail_ids else ""
        rows.append(
            {
                "Branch": c.branch,
                "Comment": c.text,
                "Topic": ", ".join(themes_by_comment.get(c.comment_id, [])),
                "Note": note,
            }
        )
    for comment_id, reason in dup_reason.items():
        rows.append({"Branch": "", "Comment": "", "Topic": "", "Note": reason})
    # pd.DataFrame([]) has no columns at all, not even empty ones — guarantee
    # the expected columns so callers can always safely do df["Branch"] etc.,
    # even for a batch with no clean comments and no duplicates (e.g. T02).
    return pd.DataFrame(rows, columns=["Branch", "Comment", "Topic", "Note"])


# ---------------------------------------------------------------------------
# Look & feel
# ---------------------------------------------------------------------------

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&family=Inter:wght@400;500;600;700&display=swap');

:root{
  --vc-fg:#171717; --vc-muted:#737373; --vc-border:#e5e5e5; --vc-subtle:#fafafa;
  --vc-green:#16a34a; --vc-amber:#b45309; --vc-red:#dc2626;
}

html, body, [class^="st-"], [class*=" st-"], .stMarkdown, button, input, textarea, select {
  font-family: 'Geist', 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
}
/* Streamlit's own chevrons/icons render through a Material Symbols icon font —
   the broad rule above must not override that, or arrows show up as literal
   words like "arrow_right". */
[data-testid="stIconMaterial"], [data-testid="stIconMaterial"] * {
  font-family: 'Material Symbols Rounded', 'Material Symbols Outlined' !important;
  font-feature-settings: 'liga' !important;
  -webkit-font-feature-settings: 'liga' !important;
}

#MainMenu, header[data-testid="stHeader"], footer, [data-testid="stToolbar"],
[data-testid="stDecoration"], [data-testid="stStatusWidget"] {
  visibility: hidden !important; height: 0 !important;
}
.block-container { padding-top: 2.5rem; max-width: 1100px; }

div[data-testid="stVerticalBlockBorderWrapper"] {
  border: 1px solid var(--vc-border) !important;
  border-radius: 8px !important;
  background: #ffffff;
}
div[data-testid="stVerticalBlockBorderWrapper"] > div { padding: 4px 4px; }

.vc-eyebrow { font-size: 12px; letter-spacing: .03em; text-transform: uppercase; color: var(--vc-muted); font-weight: 500; margin-bottom: 2px;}
.vc-stat-value { font-size: 22px; font-weight: 600; color: var(--vc-fg); }
.vc-stat-sub { font-size: 13px; color: var(--vc-muted); }
.vc-card-title { font-size: 16px; font-weight: 600; margin-bottom: 10px; }
.vc-row { display:flex; justify-content: space-between; gap: 8px; margin: 6px 0; }
.vc-muted { color: var(--vc-muted); font-size: 13px; }
.vc-pill { display:inline-block; padding: 1px 8px; border-radius: 999px; font-size: 12px; font-weight: 500; }
.vc-pill-issue { background:#fef2f2; color:var(--vc-red); }
.vc-pill-good { background:#f0fdf4; color:var(--vc-green); }

.stButton button, .stDownloadButton button {
  border-radius: 8px !important;
  font-weight: 500 !important;
}
div[data-testid="stExpander"] { border: 1px solid var(--vc-border) !important; border-radius: 8px !important; }
</style>
"""

st.markdown(_CSS, unsafe_allow_html=True)


def _card(title: Optional[str] = None):
    c = st.container(border=True)
    if title:
        c.markdown(f'<div class="vc-card-title">{title}</div>', unsafe_allow_html=True)
    return c


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

config = load_config()
gemini_available = bool(config.gemini_api_key)
labels = _label_map()

if "live_run_count" not in st.session_state:
    st.session_state["live_run_count"] = 0

st.markdown(
    '<div style="font-size:26px; font-weight:600;">☕ Juniper Café</div>'
    '<div class="vc-muted">Weekly feedback briefing for the operations manager</div>',
    unsafe_allow_html=True,
)
st.write("")

# ---- Create a briefing ------------------------------------------------------

with _card("This week's comments"):
    if not gemini_available:
        st.info("No live connection is set up right now — showing results from saved sample data.")
    effective_provider = "gemini" if gemini_available else "mock"

    source_choice = st.radio(
        "Where are this week's comments coming from?",
        ["Use a saved sample", "Upload a CSV"],
        horizontal=True,
        label_visibility="collapsed",
    )

    csv_bytes = None
    csv_path: Optional[Path] = None
    test_id = None

    if source_choice == "Use a saved sample":
        samples = _list_sample_batches()
        sample_labels = [p.name for p in samples]
        if sample_labels:
            default_index = next((i for i, n in enumerate(sample_labels) if n.startswith("T01")), 0)
            chosen = st.selectbox("Saved sample", sample_labels, index=default_index, label_visibility="collapsed")
            path = DATA_TESTS_DIR / chosen
            csv_bytes = path.read_bytes()
            csv_path = path
            test_id = _test_id_from_path(path)
        else:
            st.caption("No saved samples found yet.")
    else:
        uploaded = st.file_uploader("Upload this week's comments (CSV)", type=["csv"], label_visibility="collapsed")
        if uploaded is not None:
            csv_bytes = uploaded.getvalue()

    if effective_provider == "mock" and test_id is None and csv_bytes is not None:
        st.warning("Uploading your own file needs a live connection. Pick a saved sample instead for now.")

    quota_left = config.max_live_runs_per_session - st.session_state["live_run_count"]
    run_disabled = (
        csv_bytes is None
        or (effective_provider == "mock" and test_id is None)
        or (effective_provider == "gemini" and quota_left <= 0)
    )
    if effective_provider == "gemini" and quota_left <= 0:
        st.caption("You've created the maximum number of briefings for this session. Refresh the page to reset.")

    if st.button("Create briefing", disabled=run_disabled, type="primary"):
        cache = _get_run_cache()
        key = _cache_key(csv_bytes, effective_provider, config)
        if key in cache:
            st.session_state["last_result_key"] = key
        else:
            label = (test_id or "upload").lower()
            with st.spinner("Reading comments and preparing this week's briefing…"):
                try:
                    result = _run(
                        csv_bytes, csv_path,
                        provider=effective_provider, label=label, test_id=test_id, config=config,
                    )
                    cache[key] = result
                    st.session_state["last_result_key"] = key
                    if effective_provider == "gemini":
                        st.session_state["live_run_count"] += 1
                except ProviderUnavailable:
                    st.error("We couldn't reach the live connection just now. Please try again shortly.")
                except StructuredCallFailed:
                    st.error("Something in the comments didn't check out automatically. Please try again.")
                except Exception:  # noqa: BLE001 - never crash the manager's screen
                    st.error("Something went wrong while preparing this briefing.")
                    with st.expander("Technical details"):
                        st.code(traceback.format_exc())
        st.rerun()

result: Optional[RunResult] = None
cache = _get_run_cache()
if st.session_state.get("last_result_key") in cache:
    result = cache[st.session_state["last_result_key"]]
elif (FINAL_DIR / "briefing.md").exists():
    st.caption("Showing last week's saved briefing.")

if result is None and not (FINAL_DIR / "briefing.md").exists():
    st.stop()

# ---------------------------------------------------------------------------
# Loaded-from-disk fallback: runs/final/ (no comments run yet this session)
# ---------------------------------------------------------------------------

showing_saved = result is None

if showing_saved:
    briefing_text = (FINAL_DIR / "briefing.md").read_text()
    stage0_path = FINAL_DIR / "stage0_preprocess.json"
    visits_total = comments_total = duplicates = 0
    if stage0_path.exists():
        s0 = json.loads(stage0_path.read_text())
        visits_total = s0.get("visits_total", 0)
        comments_total = s0.get("comments_total", 0)
        duplicates = len(s0.get("duplicates", []))
else:
    briefing_text = result.briefing_md
    visits_total = result.stage0.visits_total
    comments_total = result.stage0.comments_total
    duplicates = len(result.stage0.duplicates)

st.write("")

# ---- Week summary strip -----------------------------------------------------

c1, c2, c3 = st.columns(3)
for col, value, sub in (
    (c1, f"{visits_total}", "visits this week"),
    (c2, f"{comments_total}", "comments received"),
    (c3, f"{duplicates}", "duplicate(s) removed"),
):
    with col:
        with _card():
            st.markdown(f'<div class="vc-stat-value">{value}</div><div class="vc-stat-sub">{sub}</div>', unsafe_allow_html=True)

st.write("")

# ---- Per-branch summary cards -----------------------------------------------

if not showing_saved and result.agent3 is not None:
    shops = _branch_order(result.agent3.shops, config.known_branches)
    if shops:
        st.markdown("#### Branches at a glance")
        cols = st.columns(len(shops))
        for col, shop in zip(cols, shops):
            shop_score = result.agent3.shops[shop]
            top_issue = _top_issue(shop_score, labels)
            went_well = _went_well(shop_score, labels)
            next_step = _next_step(shop, shop_score, result.agent4)
            with col:
                with _card(shop):
                    if top_issue:
                        st.markdown(
                            f'<div class="vc-eyebrow">Top issue</div>'
                            f'<span class="vc-pill vc-pill-issue">{top_issue}</span>',
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown('<div class="vc-eyebrow">Top issue</div><span class="vc-muted">Nothing stood out</span>', unsafe_allow_html=True)
                    st.write("")
                    if went_well:
                        st.markdown(
                            f'<div class="vc-eyebrow">What went well</div>'
                            f'<span class="vc-pill vc-pill-good">{went_well}</span>',
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown('<div class="vc-eyebrow">What went well</div><span class="vc-muted">No positive comments yet</span>', unsafe_allow_html=True)
                    st.write("")
                    st.markdown('<div class="vc-eyebrow">Suggested next step</div>', unsafe_allow_html=True)
                    st.markdown(f'<span class="vc-muted">{next_step or "See the full briefing below."}</span>', unsafe_allow_html=True)
        st.write("")

# ---- Full briefing -----------------------------------------------------------

with _card("Weekly briefing"):
    st.markdown(_prettify_briefing(briefing_text, labels))

st.write("")

# ---- What customers said ----------------------------------------------------

if not showing_saved and result.stage0 is not None:
    with _card("What customers said"):
        df = _evidence_table(result, labels)
        branches = sorted({b for b in df["Branch"] if b})
        topics = sorted({t for cell in df["Topic"] for t in cell.split(", ") if t})
        fc1, fc2 = st.columns(2)
        with fc1:
            branch_filter = st.multiselect("Branch", branches, label_visibility="visible", placeholder="All branches")
        with fc2:
            topic_filter = st.multiselect("Topic", topics, label_visibility="visible", placeholder="All topics")
        filtered = df
        if branch_filter:
            filtered = filtered[filtered["Branch"].isin(branch_filter)]
        if topic_filter:
            filtered = filtered[filtered["Topic"].apply(lambda cell: any(t in cell.split(", ") for t in topic_filter))]

        def _grey_unused(row):
            return ["color: #a3a3a3"] * len(row) if row["Note"] else [""] * len(row)

        st.dataframe(filtered.style.apply(_grey_unused, axis=1), use_container_width=True, hide_index=True)

st.write("")

# ---- Approve / edit / reject -------------------------------------------------

if not showing_saved:
    with _card("Review & approve"):
        kind, message = _plain_gate_message(result.verification)
        getattr(st, kind)(message)

        edited = st.text_area("Briefing text", value=briefing_text, height=320, label_visibility="collapsed")
        notes = st.text_input("Notes for the team (optional)")

        gate_status = getattr(result.verification, "overall_status", "WARN") if result.verification else "WARN"
        override = False
        if gate_status == "FAIL":
            override = st.checkbox("I've reviewed the issues above and want to approve anyway")

        approve_disabled = gate_status == "FAIL" and not (override and notes.strip())
        bcol1, bcol2, bcol3 = st.columns(3)

        def _write_review(status: str):
            record = ReviewRecord(
                status=status,
                edited_markdown=edited if edited != briefing_text else None,
                notes=notes,
                gate_status_at_review=gate_status,
                override_gate=override,
                reviewed_at=datetime.now(timezone.utc).isoformat(),
            )
            if result.run_dir:
                (result.run_dir / "review.json").write_text(record.model_dump_json(indent=2))
            st.toast("Saved.", icon="✅")

        if bcol1.button("Approve and save", disabled=approve_disabled, type="primary"):
            _write_review("approved")
        if bcol2.button("Save changes for later"):
            _write_review("edited")
        if bcol3.button("Reject this briefing"):
            _write_review("rejected")
        if gate_status == "FAIL" and approve_disabled:
            st.caption("Tick the box above and add a note to approve a briefing that still needs attention.")

# ---------------------------------------------------------------------------
# Behind the scenes (collapsed technical detail, kept for the demo)
# ---------------------------------------------------------------------------

st.write("")
with st.expander("Behind the scenes (technical detail)"):
    if showing_saved:
        st.caption("Showing saved files from runs/final/.")
        for name in ["stage0_preprocess", "agent1_tagger", "agent2_polarity", "agent3_scores", "agent4_briefs", "agent5_final", "verification"]:
            p = FINAL_DIR / f"{name}.json"
            if p.exists():
                with st.expander(name):
                    st.json(json.loads(p.read_text()))
        results_path = FINAL_DIR / "results.md"
        if results_path.exists():
            st.subheader("Prototype vs baseline")
            st.markdown(results_path.read_text())
    else:
        if result.pending_stages:
            st.info("Not available in this run: " + "; ".join(result.pending_stages))
        st.caption(f"Saved to: {result.run_dir}" if result.run_dir else "This run was not saved to disk.")

        stage_data = {
            "stage0": result.stage0, "agent1": result.agent1, "agent2": result.agent2,
            "agent3": result.agent3, "agent4": result.agent4, "agent5": result.agent5,
            "verification": result.verification,
        }
        for name, data in stage_data.items():
            timing = result.stage_timings.get(name, {})
            suffix = f" — {timing['elapsed_s']:.1f}s, {timing['tokens']} tokens" if timing else ""
            with st.expander(f"{name}{suffix}"):
                if data is None:
                    st.write("_not available for this run_")
                elif hasattr(data, "model_dump"):
                    st.json(data.model_dump())
                else:
                    st.json(data)

        if result.call_logs:
            st.subheader("Calls made (latency, tokens, cost)")
            st.dataframe(pd.DataFrame([log.model_dump() for log in result.call_logs]), use_container_width=True)

        candidates = sorted(RUNS_DIR.glob("*/results.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        if candidates:
            st.subheader("Prototype vs baseline (latest test run)")
            st.caption(f"Showing {candidates[0]}")
            st.markdown(candidates[0].read_text())
        else:
            st.caption("No test-run metrics yet.")
