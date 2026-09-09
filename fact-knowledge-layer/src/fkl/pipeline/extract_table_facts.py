"""Deterministic table fact extractor.

Produces FactCandidate objects from SourceBlock records of kind TABLE_CELL.
No hard-coded metric names or document-specific logic.
Generic rule: a labelled numeric cell with recoverable row, column, and unit context.
"""

from __future__ import annotations

import logging
import re

from fkl.domain.enums import BlockKind
from fkl.domain.models import FactCandidate, SourceBlock
from fkl.domain.normalisation import parse_numeric, detect_scale

logger = logging.getLogger(__name__)

# Generic row labels to skip — they carry no semantic meaning as facts
_SKIP_ROW_LABELS = frozenset(
    [
        "particulars", "total", "subtotal", "grand total", "net total",
        "fy24", "fy23", "fy25", "2024", "2023", "2025",
        "q1", "q2", "q3", "q4", "year", "period",
        "", "s.no", "sl.no", "sr. no",
    ]
)

# Must look like a number (optionally with comma, sign, parens, %)
_NUMERIC_RE = re.compile(r"^[\(\-]?[\d,]+\.?\d*\%?\)?$")


def is_numeric_cell(cell_value: str) -> bool:
    s = cell_value.strip().replace(" ", "")
    return bool(_NUMERIC_RE.match(s))


def extract_table_facts(blocks: list[SourceBlock]) -> list[tuple[FactCandidate, SourceBlock]]:
    """
    Iterate over TABLE_CELL blocks and produce (FactCandidate, SourceBlock) pairs.

    Only emits candidates when:
    - row_header is present and non-generic
    - cell_value is numeric
    - column_header(s) are available to infer period/scope
    """
    results: list[tuple[FactCandidate, SourceBlock]] = []

    for block in blocks:
        if block.block_kind != BlockKind.TABLE_CELL:
            continue
        ctx = block.table_context
        if not ctx:
            continue

        cell_value = ctx.cell_value.strip()
        if not is_numeric_cell(cell_value):
            continue

        # Skip pure page/section numbers
        try:
            bare = float(cell_value.replace(",", "").strip("()%"))
            if bare == int(bare) and 1900 < bare < 2100:
                continue  # looks like a year
        except ValueError:
            pass

        row_header = (ctx.row_header or "").strip()
        if not row_header or row_header.lower() in _SKIP_ROW_LABELS:
            if not row_header:
                # Capture missing-header numeric cell for grounding audit
                cand = FactCandidate(
                    entity_raw=ctx.table_title or "Table Cell",
                    metric_raw="",
                    value_raw=cell_value,
                    unit_raw=ctx.unit_note,
                    period_raw=" | ".join(ctx.column_headers or [])[:200] or None,
                    scope={},
                    evidence_quote=cell_value,
                    confidence_hint=0.2,
                )
                results.append((cand, block))
            continue

        # Build period_raw from column header(s)
        col_headers = ctx.column_headers or []
        combined_col = " ".join(col_headers).lower().strip()
        if combined_col in ("note", "notes", "ref", "schedule", "sl no", "s.no", "sr no"):
            continue

        period_raw = " | ".join(h for h in col_headers if h)[:200] or None

        # Detect unit from unit_note or column header
        unit_context = " ".join(filter(None, [ctx.unit_note] + col_headers))
        scale = detect_scale(unit_context)
        unit_raw = ctx.unit_note or (scale if scale else None)

        # Build scope from column headers
        scope: dict[str, Any] = {}
        combined = " ".join(col_headers).lower()
        if "standalone" in combined:
            scope["consolidation"] = "standalone"
        elif "consolidated" in combined:
            scope["consolidation"] = "consolidated"
        elif "group" in combined:
            scope["consolidation"] = "group"

        # Financial statement qualifiers: pro forma, restated, revised, budget
        if "pro forma" in combined or "proforma" in combined:
            scope["qualifier"] = "pro_forma"
        elif "restated" in combined:
            scope["qualifier"] = "restated"
        elif "budget" in combined:
            scope["qualifier"] = "budget"
        elif "revised" in combined:
            scope["qualifier"] = "revised"

        # Entity: use table title if present, else nearby row label, else row header
        entity_raw = ctx.table_title or row_header

        candidate = FactCandidate(
            entity_raw=entity_raw,
            metric_raw=row_header,
            value_raw=cell_value,
            unit_raw=unit_raw,
            period_raw=period_raw,
            scope=scope,
            evidence_quote=cell_value,  # for table: exact cell value is the quote
            confidence_hint=0.8,
        )
        results.append((candidate, block))

    logger.debug("Table extractor produced %d candidates", len(results))
    return results
