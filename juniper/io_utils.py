"""CSV / codebook loading and prompt template rendering.

Theme names come from codebook.yaml — never hardcode them in Python. Prompt text
comes from prompts/<agent>/<version>.md — never hardcode prompt text in Python.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from juniper.models import Codebook

REQUIRED_CSV_COLUMNS = ["comment_id", "visit_id", "branch", "comment"]

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


class MissingColumnError(ValueError):
    pass


class CodebookError(ValueError):
    pass


class PromptRenderError(ValueError):
    pass


def load_comments(csv_path: str | Path) -> pd.DataFrame:
    """Load the raw feedback batch CSV.

    Returns a DataFrame with exactly REQUIRED_CSV_COLUMNS (dtype str, NaN -> "").
    Raises MissingColumnError with a clear message if a required column is absent.
    An empty batch (header only, or a file with zero data rows) is not an error —
    it comes back as a zero-row DataFrame so the pipeline can short-circuit.
    """
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    missing = [c for c in REQUIRED_CSV_COLUMNS if c not in df.columns]
    if missing:
        raise MissingColumnError(
            f"{csv_path}: missing required column(s) {missing}; "
            f"expected columns {REQUIRED_CSV_COLUMNS}"
        )
    df = df[REQUIRED_CSV_COLUMNS].copy()
    for col in REQUIRED_CSV_COLUMNS:
        df[col] = df[col].fillna("")
    return df


def load_codebook(path: str | Path) -> Codebook:
    """Load and validate codebook.yaml.

    Validates that theme names are unique and that an 'other' theme exists, per
    docs/contracts.md Section 5.2.
    """
    raw = yaml.safe_load(Path(path).read_text())
    codebook = Codebook.model_validate(raw)

    names = [t.name for t in codebook.themes]
    seen: set[str] = set()
    dupes = {n for n in names if n in seen or seen.add(n)}  # type: ignore[func-returns-value]
    if dupes:
        raise CodebookError(f"{path}: duplicate theme name(s) {sorted(dupes)}")
    if "other" not in names:
        raise CodebookError(f"{path}: codebook must define an 'other' theme")

    return codebook


def codebook_as_text(codebook: Codebook) -> str:
    """Render the codebook as readable text for the {{codebook}} prompt variable."""
    lines: list[str] = []
    for theme in codebook.themes:
        lines.append(f"- {theme.name} ({theme.label}): {theme.definition}")
        if theme.includes:
            lines.append(f"  includes: {', '.join(theme.includes)}")
        if theme.excludes:
            lines.append(f"  excludes: {', '.join(theme.excludes)}")
    return "\n".join(lines)


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, indent=2, ensure_ascii=False)


def render_prompt(agent: str, version: str, prompts_dir: str | Path = "prompts", **vars: Any) -> str:
    """Render prompts/<agent>/<version>.md with {{variable}} -> str(value).

    Non-string values are JSON-serialised (this is how {{comments}}, {{stats}}, etc.
    are passed in, per docs/contracts.md Section 5.3). Raises PromptRenderError if
    any {{...}} placeholder remains unresolved, or if the template references a
    variable that wasn't supplied.
    """
    template_path = Path(prompts_dir) / agent / f"{version}.md"
    if not template_path.exists():
        raise PromptRenderError(f"Prompt template not found: {template_path}")
    template = template_path.read_text()

    used_in_template = set(_PLACEHOLDER_RE.findall(template))
    missing = used_in_template - set(vars.keys())
    if missing:
        raise PromptRenderError(
            f"{template_path}: template references undefined variable(s) {sorted(missing)}"
        )

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return _stringify(vars[key])

    rendered = _PLACEHOLDER_RE.sub(_replace, template)

    if "{{" in rendered:
        raise PromptRenderError(
            f"{template_path}: unresolved '{{{{' remains in rendered prompt — "
            "check for a malformed placeholder"
        )
    return rendered
