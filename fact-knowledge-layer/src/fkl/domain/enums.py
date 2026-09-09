"""Domain enums — no free-text can override verdict or reason_code."""

from enum import StrEnum


class DocumentStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"


class BlockKind(StrEnum):
    PARAGRAPH = "paragraph"
    TABLE_CELL = "table_cell"
    HEADING = "heading"
    CHART = "chart"
    IMAGE = "image"
    FOOTER = "footer"
    HEADER_BLOCK = "header_block"


class ValueKind(StrEnum):
    NUMERIC = "numeric"
    DATE = "date"
    TEXT = "text"
    BOOLEAN = "boolean"


class UnitDimension(StrEnum):
    CURRENCY = "currency"
    PERCENTAGE = "percentage"
    COUNT = "count"
    RATE = "rate"
    UNKNOWN = "unknown"


class ExtractionMethod(StrEnum):
    TEXT_LLM = "text_llm"
    TABLE_RULE = "table_rule"


class ReviewState(StrEnum):
    ACCEPTED = "accepted"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"


class RelationshipReviewState(StrEnum):
    AUTOMATIC = "automatic"
    HUMAN_VERIFIED = "human_verified"
    REJECTED = "rejected"


class Verdict(StrEnum):
    CORROBORATES = "corroborates"
    RECONCILES = "reconciles"
    LIKELY_CONFLICT = "likely_conflict"
    INSUFFICIENT_CONTEXT = "insufficient_context"


class ReasonCode(StrEnum):
    EXACT_MATCH = "exact_match"
    ROUNDED_MATCH = "rounded_match"
    ALIAS_MATCH = "alias_match"
    DIFFERENT_PERIOD = "different_period"
    DIFFERENT_SCOPE = "different_scope"
    UNIT_OR_SCALE_DIFFERENCE = "unit_or_scale_difference"
    METHODOLOGY_DIFFERENCE = "methodology_difference"
    MATERIAL_VALUE_DIFFERENCE = "material_value_difference"
    LOW_EVIDENCE_QUALITY = "low_evidence_quality"
    INSUFFICIENT_CONTEXT = "insufficient_context"
