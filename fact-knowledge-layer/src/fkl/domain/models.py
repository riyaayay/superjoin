"""Immutable domain/Pydantic models shared across the application."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from fkl.domain.enums import (
    BlockKind,
    DocumentStatus,
    ExtractionMethod,
    ReasonCode,
    RelationshipReviewState,
    ReviewState,
    UnitDimension,
    ValueKind,
    Verdict,
)


# ---------------------------------------------------------------------------
# Source evidence models
# ---------------------------------------------------------------------------


class BoundingBox(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float


class TableContext(BaseModel):
    """Structured evidence for a fact extracted from a table cell."""

    table_title: str | None = None
    row_header: str | None = None
    column_headers: list[str] = Field(default_factory=list)
    cell_value: str = ""
    unit_note: str | None = None
    footnote: str | None = None


class SourceBlock(BaseModel):
    """One block of source content from a parsed PDF page."""

    id: str
    document_id: str
    pdf_page_index: int  # 1-based
    printed_page_label: str | None = None
    block_kind: BlockKind
    bbox: BoundingBox | None = None
    text: str
    text_normalised: str
    table_context: TableContext | None = None
    content_hash: str


# ---------------------------------------------------------------------------
# Fact candidate (pre-grounding)
# ---------------------------------------------------------------------------


class FactCandidate(BaseModel):
    """Strict schema for LLM/rule-produced candidates before grounding."""

    entity_raw: str
    metric_raw: str
    value_raw: str
    unit_raw: str | None = None
    period_raw: str | None = None
    scope: dict[str, Any] = Field(default_factory=dict)
    evidence_quote: str = ""  # used only for grounding validation
    confidence_hint: float = Field(default=0.5, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Grounding result
# ---------------------------------------------------------------------------


class GroundingResult(BaseModel):
    accepted: bool
    evidence_block_id: str | None = None
    confidence: float = 0.0
    rejection_reason: str | None = None


# ---------------------------------------------------------------------------
# Normalisation provenance
# ---------------------------------------------------------------------------


class NormalisationStep(BaseModel):
    operation: str
    input: str
    input_unit: str | None = None
    output: Any
    output_unit: str | None = None
    rule_version: str = "1.0"


class NormalisationProvenance(BaseModel):
    steps: list[NormalisationStep] = Field(default_factory=list)
    normalised_value: float | None = None
    normalised_unit: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    scope_tokens: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Fact (persisted, immutable)
# ---------------------------------------------------------------------------


class Fact(BaseModel):
    id: str
    document_id: str
    ingestion_run_id: str
    evidence_block_id: str
    entity_raw: str
    metric_raw: str
    metric_key: str | None = None
    value_raw: str
    numeric_value: float | None = None
    value_kind: ValueKind
    unit_raw: str | None = None
    unit_dimension: UnitDimension = UnitDimension.UNKNOWN
    scale_raw: str | None = None
    normalised_value: float | None = None
    normalised_unit: str | None = None
    period_raw: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    scope: dict[str, Any] = Field(default_factory=dict)
    qualifiers: dict[str, Any] = Field(default_factory=dict)
    extraction_method: ExtractionMethod
    confidence: float
    review_state: ReviewState
    normalisation_provenance: list[NormalisationStep] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Relationship
# ---------------------------------------------------------------------------


class ComparisonResult(BaseModel):
    """All fields and rule decisions that drove the verdict."""

    left_fact_id: str
    right_fact_id: str
    metric_match: bool
    entity_match: bool
    period_match: bool | None = None
    scope_match: bool | None = None
    left_normalised: float | None = None
    right_normalised: float | None = None
    tolerance: float | None = None
    value_within_tolerance: bool | None = None
    unit_conversion_applied: bool = False
    conversion_factor: float | None = None
    scope_left: str | None = None
    scope_right: str | None = None
    period_left: str | None = None
    period_right: str | None = None
    evidence_quality_left: float = 0.0
    evidence_quality_right: float = 0.0


class Relationship(BaseModel):
    id: str
    left_fact_id: str
    right_fact_id: str
    reason_code: ReasonCode
    verdict: Verdict
    explanation: str
    comparison: ComparisonResult
    confidence: float
    review_state: RelationshipReviewState = RelationshipReviewState.AUTOMATIC
    created_by_run_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Ingestion summary
# ---------------------------------------------------------------------------


class IngestionSummary(BaseModel):
    run_id: str
    document_id: str
    facts_created: int
    facts_rejected: int
    relationships_created: int
    warnings: list[str] = Field(default_factory=list)
    duration_seconds: float = 0.0
