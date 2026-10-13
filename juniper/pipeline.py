"""Runs the linear pipeline end to end: Stage 0 -> Agent 1 -> Agent 2 -> Agent 3
-> Agent 4 -> Agent 5 -> render -> verify. Saves every stage's output to
runs/<timestamp>_<label>/ (including config_snapshot.yaml and call_log.json)
and returns a RunResult. See docs/BUILD_SPEC_A.md Phase 6.

`--from <stage>` + a `reuse_run_dir` loads every stage before it from an earlier
run folder instead of recomputing it, so iterating on Agent 4 doesn't re-pay for
Agents 1-2. `--until <stage>` stops after that stage (used at CHECKPOINT 1 to
compare Agent 1/2 tags without spending Agent 4/5 calls).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Type, TypeVar

import yaml
from pydantic import BaseModel

from juniper.agent1_tagger import tag_comments
from juniper.agent2_polarity import judge_polarity
from juniper.agent3_scorer import score as score_agent3
from juniper.agent4_brief import write_briefs
from juniper.agent5_editor import edit_briefing
from juniper.checked_call import SemanticValidationError
from juniper.config import Config, get_config
from juniper.io_utils import load_codebook, load_comments
from juniper.llm import ProviderUnavailable, StructuredCallFailed
from juniper.models import (
    Agent1Output,
    Agent2Output,
    Agent3Output,
    Agent4Output,
    Agent5Output,
    CallLog,
    Stage0Output,
    VerificationResult,
)
from juniper.render import render_briefing
from juniper.stage0_preprocess import preprocess
from juniper.verify import verify_run

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = REPO_ROOT / "runs"
CODEBOOK_PATH = REPO_ROOT / "codebook.yaml"

STAGE_ORDER = ["stage0", "agent1", "agent2", "agent3", "agent4", "agent5", "render", "verify"]

T = TypeVar("T", bound=BaseModel)


class _StopAtRequestedStage(Exception):
    """Internal control flow for `until` — never escapes run_pipeline()."""


@dataclass
class RunResult:
    label: str
    run_dir: Path
    provider: str
    stage0: Stage0Output
    agent1: Optional[Agent1Output] = None
    agent2: Optional[Agent2Output] = None
    agent3: Optional[Agent3Output] = None
    agent4: Optional[Agent4Output] = None
    agent5: Optional[Agent5Output] = None
    verification: Optional[VerificationResult] = None
    briefing_md: str = ""
    call_logs: list[CallLog] = field(default_factory=list)
    agent5_warnings: list[str] = field(default_factory=list)
    status: str = "OK"  # OK | FAIL | PROVIDER_UNAVAILABLE
    error: Optional[str] = None


def _new_run_dir(label: str) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUNS_DIR / f"{ts}_{label}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _save_json(run_dir: Path, name: str, model: Optional[BaseModel]) -> None:
    if model is not None:
        (run_dir / f"{name}.json").write_text(model.model_dump_json(indent=2))


def _load_stage(reuse_dir: Path, name: str, model_cls: Type[T]) -> T:
    path = reuse_dir / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"--from requires {path} from the reused run folder, but it's missing")
    return model_cls.model_validate_json(path.read_text())


def _save_call_log(run_dir: Path, call_logs: list[CallLog]) -> None:
    (run_dir / "call_log.json").write_text(json.dumps([log.model_dump() for log in call_logs], indent=2))


def _save_config_snapshot(run_dir: Path, config: Config) -> None:
    (run_dir / "config_snapshot.yaml").write_text(yaml.safe_dump(config.raw, sort_keys=False))


def run_pipeline(
    csv_path: str | Path,
    *,
    label: str,
    config: Optional[Config] = None,
    test_id: Optional[str] = None,
    from_stage: Optional[str] = None,
    reuse_run_dir: Optional[str | Path] = None,
    until: Optional[str] = None,
) -> RunResult:
    config = config or get_config()
    run_dir = _new_run_dir(label)
    reuse_dir = Path(reuse_run_dir) if reuse_run_dir else None
    if from_stage and reuse_dir is None:
        raise ValueError("from_stage requires reuse_run_dir (the folder to load earlier stages from)")

    call_logs: list[CallLog] = []
    agent5_warnings: list[str] = []
    agent1 = agent2 = agent3 = agent4 = agent5 = verification = None
    briefing_md = ""
    status = "OK"
    error: Optional[str] = None

    def reused(stage: str) -> bool:
        return from_stage is not None and STAGE_ORDER.index(stage) < STAGE_ORDER.index(from_stage)

    def stop_after(stage: str) -> None:
        if until is not None and STAGE_ORDER.index(stage) >= STAGE_ORDER.index(until):
            raise _StopAtRequestedStage()

    try:
        # ---- Stage 0 --------------------------------------------------------
        if reused("stage0"):
            stage0 = _load_stage(reuse_dir, "stage0_preprocess", Stage0Output)
        else:
            df = load_comments(csv_path)
            stage0 = preprocess(df, config.known_branches)
        _save_json(run_dir, "stage0_preprocess", stage0)

        if not stage0.clean_comments:
            # Short-circuit per contracts.md 5.5 / BUILD_SPEC_A Phase 5: 0 usable
            # comments -> skip every LLM call, cost 0. render_briefing() has the
            # same check built in, so passing None downstream is safe here.
            briefing_md = render_briefing(stage0, None, None, None)  # type: ignore[arg-type]
            (run_dir / "briefing.md").write_text(briefing_md)
            _save_call_log(run_dir, call_logs)
            _save_config_snapshot(run_dir, config)
            return RunResult(
                label=label, run_dir=run_dir, provider=config.provider, stage0=stage0,
                briefing_md=briefing_md, call_logs=call_logs,
            )

        codebook = load_codebook(CODEBOOK_PATH)
        stop_after("stage0")

        # ---- Agent 1 ----------------------------------------------------------
        if reused("agent1"):
            agent1 = _load_stage(reuse_dir, "agent1_tagger", Agent1Output)
        else:
            agent1, logs1 = tag_comments(stage0.clean_comments, codebook, config=config, test_id=test_id)
            call_logs.extend(logs1)
        _save_json(run_dir, "agent1_tagger", agent1)
        stop_after("agent1")

        # ---- Agent 2 ----------------------------------------------------------
        if reused("agent2"):
            agent2 = _load_stage(reuse_dir, "agent2_polarity", Agent2Output)
        else:
            agent2, logs2 = judge_polarity(agent1, stage0.clean_comments, codebook, config=config, test_id=test_id)
            call_logs.extend(logs2)
        _save_json(run_dir, "agent2_polarity", agent2)
        stop_after("agent2")

        # ---- Agent 3 (code) -----------------------------------------------------
        if reused("agent3"):
            agent3 = _load_stage(reuse_dir, "agent3_scores", Agent3Output)
        else:
            agent3 = score_agent3(agent2, stage0.clean_comments, stage0, single_mention_max=config.single_mention_max)
        _save_json(run_dir, "agent3_scores", agent3)
        stop_after("agent3")

        # ---- Agent 4 (parallel) -------------------------------------------------
        if reused("agent4"):
            agent4 = _load_stage(reuse_dir, "agent4_briefs", Agent4Output)
        else:
            agent4, logs4 = write_briefs(agent3, agent2, stage0.clean_comments, codebook, config=config, test_id=test_id)
            call_logs.extend(logs4)
        _save_json(run_dir, "agent4_briefs", agent4)
        stop_after("agent4")

        # ---- Agent 5 --------------------------------------------------------------
        if reused("agent5"):
            agent5 = _load_stage(reuse_dir, "agent5_final", Agent5Output)
        else:
            agent5, log5, agent5_warnings = edit_briefing(stage0, agent3, agent4, config=config, test_id=test_id)
            if log5 is not None:
                call_logs.append(log5)
        _save_json(run_dir, "agent5_final", agent5)
        stop_after("agent5")

        # ---- Render -----------------------------------------------------------------
        briefing_md = render_briefing(stage0, agent3, agent4, agent5, label=label)
        (run_dir / "briefing.md").write_text(briefing_md)
        stop_after("render")

        # ---- Verification gate --------------------------------------------------------
        verification = verify_run(
            stage0, agent3, agent4, agent5, config=config,
            agent5_warnings=agent5_warnings, briefing_md=briefing_md,
        )
        _save_json(run_dir, "verification", verification)

    except _StopAtRequestedStage:
        pass
    except (StructuredCallFailed, SemanticValidationError) as exc:
        status = "FAIL"
        error = str(exc)
        log = getattr(exc, "call_log", None)
        if log is not None:
            call_logs.append(log)
    except FileNotFoundError as exc:
        # provider: mock with no fixture for this test_id/agent — fixtures/mock/
        # is scoped to "T01 at least" (CLAUDE.md), so this is expected for most
        # tests beyond T01, not a crash-the-suite condition.
        status = "FAIL"
        error = str(exc)
    except ProviderUnavailable as exc:
        status = "PROVIDER_UNAVAILABLE"
        error = str(exc)

    _save_call_log(run_dir, call_logs)
    _save_config_snapshot(run_dir, config)

    return RunResult(
        label=label,
        run_dir=run_dir,
        provider=config.provider,
        stage0=stage0,
        agent1=agent1,
        agent2=agent2,
        agent3=agent3,
        agent4=agent4,
        agent5=agent5,
        verification=verification,
        briefing_md=briefing_md,
        call_logs=call_logs,
        agent5_warnings=agent5_warnings,
        status=status,
        error=error,
    )
