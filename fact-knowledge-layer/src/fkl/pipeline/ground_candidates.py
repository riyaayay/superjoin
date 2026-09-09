"""Grounding gate — the most important file.

A candidate is accepted only when its value literally appears in the source block.
Rejected candidates are persisted; they are never silently dropped.
"""

from __future__ import annotations

import logging
import re

from fkl.domain.enums import BlockKind
from fkl.domain.models import FactCandidate, GroundingResult, SourceBlock
from fkl.domain.normalisation import normalise_text, parse_numeric

logger = logging.getLogger(__name__)

_NUMERIC_CHARS = re.compile(r"[^\d\.\-]")


def _strip_numeric(s: str) -> str:
    """Strip formatting to bare number for fuzzy matching."""
    return _NUMERIC_CHARS.sub("", s.strip())


def _value_in_text(value_raw: str, text_normalised: str) -> bool:
    """Check that the candidate value appears in the source block text."""
    # Direct substring
    val_norm = normalise_text(value_raw)
    if val_norm and val_norm in text_normalised:
        return True

    # Numeric-only fallback: strip commas, currency symbols and match
    bare = _strip_numeric(value_raw)
    if bare and bare in text_normalised.replace(",", "").replace(" ", ""):
        return True

    # Allow percentage shorthand: "6.4%" matches "6.4 percent"
    if "%" in value_raw:
        num_part = value_raw.replace("%", "").strip()
        if num_part in text_normalised:
            return True

    return False


def ground(
    candidate: FactCandidate,
    block: SourceBlock,
) -> GroundingResult:
    """
    Apply the evidence invariant:

    1. The literal value must appear in the source block text.
    2. Required fields (entity, metric, value) must be non-empty.
    3. Image/chart blocks cannot ground numeric facts.
    4. Table-cell candidates validate value against cell_value, not substring.
    """
    # Chart/image blocks cannot produce grounded numeric facts
    if block.block_kind in (BlockKind.CHART, BlockKind.IMAGE):
        return GroundingResult(
            accepted=False,
            rejection_reason="source_block_is_chart_or_image",
        )

    # Table-cell: row header must be present
    if block.block_kind == BlockKind.TABLE_CELL:
        if not (block.table_context and block.table_context.row_header and block.table_context.row_header.strip()):
            return GroundingResult(
                accepted=False,
                rejection_reason="table_missing_row_header",
            )

    # Required fields
    required = {
        "entity_raw": candidate.entity_raw,
        "metric_raw": candidate.metric_raw,
        "value_raw": candidate.value_raw,
    }
    missing = [k for k, v in required.items() if not str(v).strip()]
    if missing:
        return GroundingResult(
            accepted=False,
            rejection_reason=f"missing_required_fields:{','.join(missing)}",
        )

    # Table-cell: value must match the stored cell_value exactly
    if block.block_kind == BlockKind.TABLE_CELL and block.table_context:
        cell_val = normalise_text(block.table_context.cell_value)
        cand_val = normalise_text(candidate.value_raw)
        if cand_val != cell_val and _strip_numeric(candidate.value_raw) != _strip_numeric(
            block.table_context.cell_value
        ):
            return GroundingResult(
                accepted=False,
                rejection_reason="table_cell_value_mismatch",
            )
        confidence = _score(candidate, block, table_match=True)
        return GroundingResult(
            accepted=True,
            evidence_block_id=block.id,
            confidence=confidence,
        )

    # Prose block: value must appear in text
    if not _value_in_text(candidate.value_raw, block.text_normalised):
        return GroundingResult(
            accepted=False,
            rejection_reason="value_not_found_in_block_text",
        )

    # Optional: check evidence_quote
    quote_ok = True
    if candidate.evidence_quote:
        quote_ok = normalise_text(candidate.evidence_quote) in block.text_normalised

    confidence = _score(candidate, block, table_match=False, quote_ok=quote_ok)
    return GroundingResult(
        accepted=True,
        evidence_block_id=block.id,
        confidence=confidence,
    )


def _score(
    candidate: FactCandidate,
    block: SourceBlock,
    *,
    table_match: bool,
    quote_ok: bool = True,
) -> float:
    """Compute a grounding confidence score."""
    base = candidate.confidence_hint
    if table_match:
        base = max(base, 0.75)  # table cells have structural evidence
    if quote_ok:
        base = min(base + 0.1, 1.0)
    # Penalise short blocks (less context)
    if len(block.text) < 40:
        base *= 0.85
    # Penalise if period/unit is absent
    if not candidate.period_raw:
        base *= 0.9
    if not candidate.unit_raw:
        base *= 0.9
    return round(min(base, 0.98), 3)
