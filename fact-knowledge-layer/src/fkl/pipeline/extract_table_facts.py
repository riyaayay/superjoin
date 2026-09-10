"""Deterministic table fact extractor.

Produces FactCandidate objects from SourceBlock records of kind TABLE_CELL.
No hard-coded metric names or document-specific logic.
Generic rule: a labelled numeric cell with recoverable row, column, and unit context.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from fkl.domain.enums import BlockKind
from fkl.domain.models import ExtractionStats, FactCandidate, SourceBlock
from fkl.domain.normalisation import detect_scale

logger = logging.getLogger(__name__)

# Generic row labels to skip — they carry no semantic meaning as facts
_SKIP_ROW_LABELS = frozenset(
    [
        "particulars", "total", "subtotal", "grand total", "net total",
        "q1", "q2", "q3", "q4", "year", "period",
        "", "s.no", "sl.no", "sr. no",
    ]
)

_YEAR_HEADER_RE = re.compile(r"^(19|20)\d{2}$")
_FY_HEADER_RE = re.compile(r"^fy\s?\d{2,4}(-\d{2,4})?$", re.IGNORECASE)


def _is_period_header(label: str) -> bool:
    clean = label.strip()
    return bool(_YEAR_HEADER_RE.match(clean) or _FY_HEADER_RE.match(clean))


# Must look like a number (optionally with comma, sign, parens, %)
_NUMERIC_RE = re.compile(r"^[\(\-]?[\d,]+\.?\d*\%?\)?$")

_CURRENCY_SYMBOLS = ("₹", "$", "€", "£", "¥")
_TRAILING_SUFFIXES = ("bps", "bp", "x")


def _clean_numeric_cell(cell_value: str) -> tuple[bool, str, str | None]:
    """
    Check if cell_value represents a number with optional currency, unicode minus, or suffix.
    Returns (is_numeric, cleaned_value, stripped_unit).
    """
    s = cell_value.strip().replace(" ", "")
    s = s.replace("\u2212", "-")
    stripped_unit: str | None = None

    for sym in _CURRENCY_SYMBOLS:
        if s.startswith(sym):
            stripped_unit = sym
            s = s[len(sym):].strip()
            break
        elif s.startswith("(" + sym):
            stripped_unit = sym
            s = "(" + s[1 + len(sym):].strip()
            break
        elif s.startswith("-" + sym):
            stripped_unit = sym
            s = "-" + s[1 + len(sym):].strip()
            break

    s_lower = s.lower()
    for suf in _TRAILING_SUFFIXES:
        if s_lower.endswith(suf):
            stripped_unit = stripped_unit or suf
            s = s[: -len(suf)].strip()
            break
        elif s_lower.endswith(suf + ")"):
            stripped_unit = stripped_unit or suf
            s = s[: -(len(suf) + 1)].strip() + ")"
            break

    if bool(_NUMERIC_RE.match(s)):
        return True, s, stripped_unit
    return False, cell_value, None


def is_numeric_cell(cell_value: str) -> bool:
    is_num, _, _ = _clean_numeric_cell(cell_value)
    return is_num


def _balance_parens(s: str) -> str:
    diff = s.count("(") - s.count(")")
    return s + (")" * diff) if diff > 0 else s


_KNOWN_NON_QUALIFIERS = frozenset([
    "fy", "q1", "q2", "q3", "q4", "year", "ended", "quarter", "months",
    "audited", "inr", "rs", "crore", "lakh", "million", "usd", "eur", "gbp",
    "standalone", "consolidated", "group", "particulars", "notes", "note",
])


def extract_table_facts(
    blocks: list[SourceBlock],
    canonical_entity: str | None = None,
    stats: ExtractionStats | None = None,
) -> list[tuple[FactCandidate, SourceBlock]]:
    """
    Iterate over TABLE_CELL blocks and produce (FactCandidate, SourceBlock) pairs.

    Only emits candidates when:
    - row_header is present and non-generic
    - cell_value is numeric (or emitted as low-confidence unrecognized_numeric for audit)
    - column_header(s) are available to infer period/scope
    """
    results: list[tuple[FactCandidate, SourceBlock]] = []

    for block in blocks:
        if block.block_kind != BlockKind.TABLE_CELL:
            continue
        ctx = block.table_context
        if not ctx:
            continue

        if stats is not None:
            stats.table_cells_total += 1

        cell_value = ctx.cell_value.strip()
        is_num, cleaned_cell, stripped_unit = _clean_numeric_cell(cell_value)

        entity_raw = ctx.company_name or canonical_entity or "Entity"
        col_headers = ctx.column_headers or []
        raw_period_str = " | ".join(h for h in col_headers if h)[:200]
        period_raw = _balance_parens(raw_period_str) if raw_period_str else None

        if not is_num:
            if stats is not None:
                stats.table_cells_rejected_not_numeric += 1
            # Emit low-confidence candidate for grounding audit trail instead of silent loss
            cand = FactCandidate(
                entity_raw=entity_raw,
                metric_raw=(ctx.row_header or "").strip() or "Table Cell",
                value_raw=cell_value,
                unit_raw=ctx.unit_note,
                period_raw=period_raw,
                scope={"unrecognized_numeric": True},
                evidence_quote=cell_value,
                confidence_hint=0.10,
            )
            results.append((cand, block))
            continue

        # Tag plausible year values for grounding audit rather than silently skipping
        is_plausible_year = False
        try:
            bare = float(cleaned_cell.replace(",", "").strip("()%"))
            if bare == int(bare) and 1900 < bare < 2100:
                is_plausible_year = True
        except ValueError:
            pass

        row_header = (ctx.row_header or "").strip()
        if not row_header or row_header.lower() in _SKIP_ROW_LABELS or _is_period_header(row_header):
            if not row_header:
                if stats is not None:
                    stats.table_cells_rejected_missing_header += 1
                # Capture missing-header numeric cell for grounding audit
                cand = FactCandidate(
                    entity_raw=entity_raw,
                    metric_raw="",
                    value_raw=cell_value,
                    unit_raw=ctx.unit_note or stripped_unit,
                    period_raw=period_raw,
                    scope={},
                    evidence_quote=cell_value,
                    confidence_hint=0.2,
                )
                results.append((cand, block))
            continue

        # Build period_raw from column header(s)
        combined_col = " ".join(col_headers).lower().strip()
        if combined_col in ("note", "notes", "ref", "schedule", "sl no", "s.no", "sr no"):
            continue

        # Detect unit from unit_note or column header, or carried over from stripped symbol
        unit_context = " ".join(filter(None, [ctx.unit_note] + col_headers))
        scale = detect_scale(unit_context)
        unit_raw = ctx.unit_note or (scale if scale else None) or stripped_unit

        # Build scope from column headers and table title
        scope: dict[str, Any] = {}
        if is_plausible_year:
            scope["plausible_year_value"] = True

        combined_context = (" ".join(col_headers) + " " + (ctx.table_title or "")).lower()
        if "standalone" in combined_context:
            scope["consolidation"] = "standalone"
        elif "consolidated" in combined_context or "group" in combined_context:
            scope["consolidation"] = "consolidated"

        # Financial statement qualifiers: pro forma, restated, revised, budget
        if "pro forma" in combined_context or "proforma" in combined_context:
            scope["qualifier"] = "pro_forma"
        elif "restated" in combined_context:
            scope["qualifier"] = "restated"
        elif "budget" in combined_context:
            scope["qualifier"] = "budget"
        elif "revised" in combined_context:
            scope["qualifier"] = "revised"
        else:
            # Fallback for unrecognized qualifiers (Task 7)
            for h in col_headers:
                words = re.findall(r"\b[a-zA-Z]{4,}\b", h.lower())
                unrec = [
                    w for w in words
                    if w not in _KNOWN_NON_QUALIFIERS
                    and not _is_period_header(w)
                    and not detect_scale(w)
                ]
                if unrec:
                    scope["unrecognized_qualifier"] = unrec[0]
                    break

        confidence_hint = 0.15 if is_plausible_year else 0.85

        candidate = FactCandidate(
            entity_raw=entity_raw,
            metric_raw=row_header,
            value_raw=cell_value,
            unit_raw=unit_raw,
            period_raw=period_raw,
            scope=scope,
            evidence_quote=cell_value,  # for table: exact cell value is the quote
            confidence_hint=confidence_hint,
        )
        results.append((candidate, block))

    logger.debug("Table extractor produced %d candidates", len(results))
    return results
