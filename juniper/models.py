"""Pydantic contracts for every stage of the pipeline.

Single source of truth for the shapes in docs/contracts.md (BUILD_SPEC_A Section 5).
Person B's prompts must match these field names; juniper/llm.py builds the Gemini/
Ollama structured-output schema straight from model_json_schema() on these classes.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 5.2 codebook.yaml
# ---------------------------------------------------------------------------


class Theme(BaseModel):
    name: str
    label: str
    definition: str
    includes: list[str] = Field(default_factory=list)
    excludes: list[str] = Field(default_factory=list)


class Codebook(BaseModel):
    themes: list[Theme]


# ---------------------------------------------------------------------------
# 5.1 / 5.4 Stage 0 preprocessing
# ---------------------------------------------------------------------------


class Comment(BaseModel):
    """One clean (surviving) comment, ready to be sent to Agent 1."""

    comment_id: str
    visit_id: str
    branch: str
    text: str


class DuplicateRecord(BaseModel):
    """A later comment sharing a visit_id with an earlier, kept comment."""

    comment_id: str
    duplicate_of: str
    visit_id: str
    text_differs: bool


class PossibleTextDuplicate(BaseModel):
    """Same normalised text, different visit_id. Both are kept; flagged for review."""

    comment_id: str
    visit_id: str
    duplicate_of: str
    duplicate_of_visit_id: str


class Stage0Output(BaseModel):
    comments_total: int
    visits_total: int
    clean_comments: list[Comment]
    duplicates: list[DuplicateRecord] = Field(default_factory=list)
    possible_text_duplicates: list[PossibleTextDuplicate] = Field(default_factory=list)
    visits_by_branch: dict[str, int] = Field(default_factory=dict)
    unknown_branches: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 5.5 Agent 1 · theme tagger (LLM)
# ---------------------------------------------------------------------------


class ThemeTag(BaseModel):
    theme: str
    quote: str


class Agent1Item(BaseModel):
    comment_id: str
    usable: bool
    themes: list[ThemeTag] = Field(default_factory=list)
    new_theme_suggestion: Optional[str] = None


class Agent1Output(BaseModel):
    items: list[Agent1Item]


# ---------------------------------------------------------------------------
# 5.6 Agent 2 · polarity judge (LLM)
# ---------------------------------------------------------------------------

Polarity = Literal["positive", "negative", "suggestion"]


class Assessment(BaseModel):
    theme: str
    polarity: Polarity
    quote: str
    rationale: str


class Agent2Item(BaseModel):
    comment_id: str
    assessments: list[Assessment] = Field(default_factory=list)


class Agent2Output(BaseModel):
    items: list[Agent2Item]


# ---------------------------------------------------------------------------
# 5.7 Agent 3 · shop scorer (code)
# ---------------------------------------------------------------------------

EvidenceLevel = Literal["single mention", "repeated"]


class ThemeScore(BaseModel):
    positive_ids: list[str] = Field(default_factory=list)
    negative_ids: list[str] = Field(default_factory=list)
    suggestion_ids: list[str] = Field(default_factory=list)
    n_pos: int
    n_neg: int
    n_sug: int
    mentions: int
    mention_rate: float
    score: float
    evidence_level: EvidenceLevel
    mixed: bool


class ShopScore(BaseModel):
    visits: int
    themes: dict[str, ThemeScore] = Field(default_factory=dict)
    negative_themes_ranked: list[str] = Field(default_factory=list)
    priority_theme: Optional[str] = None
    no_detail_ids: list[str] = Field(default_factory=list)


class NetworkThemeScore(BaseModel):
    n_pos: int
    n_neg: int
    shops_with_negative: list[str] = Field(default_factory=list)


class NetworkScore(BaseModel):
    themes: dict[str, NetworkThemeScore] = Field(default_factory=dict)
    priority_theme: Optional[str] = None


class SuggestionItem(BaseModel):
    shop: str
    theme: str
    comment_id: str
    quote: str


class Agent3Output(BaseModel):
    visits_total: int
    shops: dict[str, ShopScore] = Field(default_factory=dict)
    network: NetworkScore
    suggestions: list[SuggestionItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 5.8 Agent 4 · theme brief + CTA writer (LLM, one call per shop x negative theme)
# ---------------------------------------------------------------------------

CTAKind = Literal["investigate", "small_test"]


class CTA(BaseModel):
    action: str
    kind: CTAKind
    data_needed: list[str] = Field(default_factory=list)
    success_signal: str


class KeyQuote(BaseModel):
    comment_id: str
    quote: str


class ThemeBrief(BaseModel):
    shop: str
    theme: str
    summary_of_comments: str
    interpretation: str
    cta: CTA
    cited_ids: list[str] = Field(default_factory=list)
    key_quotes: list[KeyQuote] = Field(default_factory=list)


class Agent4Output(BaseModel):
    """Saved as agent4_briefs.json: the list of ThemeBrief, one per LLM call."""

    briefs: list[ThemeBrief] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 5.9 Agent 5 · final briefing editor (LLM)
# ---------------------------------------------------------------------------


class ShopSummary(BaseModel):
    shop: str
    overview: str
    priority_theme: Optional[str] = None
    cited_ids: list[str] = Field(default_factory=list)


class NetworkPriority(BaseModel):
    theme: Optional[str] = None
    reason: str
    action: str
    cited_ids: list[str] = Field(default_factory=list)


class Agent5Output(BaseModel):
    headline: str
    shops: list[ShopSummary]
    network_priority: NetworkPriority
    requests: list[str] = Field(default_factory=list)
    mixed_views_note: str
    limitations: str


# ---------------------------------------------------------------------------
# 5.10 Baseline (single LLM call, no pipeline)
# ---------------------------------------------------------------------------


class BaselineThemeCount(BaseModel):
    theme: str
    n_pos: int
    n_neg: int
    positive_ids: list[str] = Field(default_factory=list)
    negative_ids: list[str] = Field(default_factory=list)


class BaselineAction(BaseModel):
    theme: str
    action: str


class BaselineShop(BaseModel):
    shop: str
    visits: int
    themes: list[BaselineThemeCount] = Field(default_factory=list)
    summary: str
    actions: list[BaselineAction] = Field(default_factory=list)


class BaselineOutput(BaseModel):
    visits_total: int
    duplicates_noticed: list[str] = Field(default_factory=list)
    shops: list[BaselineShop] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 5.11 Review record (written by the Streamlit app)
# ---------------------------------------------------------------------------

ReviewStatus = Literal["approved", "edited", "rejected"]


class ReviewRecord(BaseModel):
    status: ReviewStatus
    edited_markdown: Optional[str] = None
    notes: str = ""
    gate_status_at_review: str
    override_gate: bool = False
    reviewed_at: str


# ---------------------------------------------------------------------------
# Verification gate (Phase 6)
# ---------------------------------------------------------------------------

CheckStatus = Literal["PASS", "WARN", "FAIL"]


class VerificationCheck(BaseModel):
    id: str
    status: CheckStatus
    details: str = ""


class VerificationResult(BaseModel):
    checks: list[VerificationCheck]
    overall_status: CheckStatus


# ---------------------------------------------------------------------------
# Phase 2 · LLM call logging (provider: gemini | ollama | mock)
# ---------------------------------------------------------------------------

Provider = Literal["gemini", "ollama", "mock"]


class CallLog(BaseModel):
    agent: str
    provider: Provider
    model: str
    prompt_version: str
    latency_s: float
    input_tokens: int
    output_tokens: int
    cost_eur: float = 0.0
    cost_eur_if_paid_est: Optional[float] = None
    retries: int = 0
    ok: bool
