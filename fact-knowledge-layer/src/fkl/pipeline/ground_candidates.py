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


_STOP_WORDS = frozenset([
    "a", "an", "the", "and", "or", "of", "in", "for", "on", "at", "to", "by",
    "with", "from", "as", "is", "was", "are", "were", "be", "been", "being",
    "it", "its", "that", "this", "these", "those",
])

_TAXONOMY_DESCRIPTORS = frozenset(["position", "role", "status", "date"])

_CANONICAL_CATEGORIES = frozenset([
    "Board Position", "Board Resignation", "Board Appointment",
    "Executive Position", "Executive Appointment", "Executive Resignation",
])
_CANONICAL_CATEGORIES_LOWER = frozenset(c.lower() for c in _CANONICAL_CATEGORIES)

_ROOT_SUFFIXES = ("ation", "ition", "ement", "ment", "sion", "tion", "ion", "ing", "ies", "es", "ed", "s")


def get_canonical_roots(word: str) -> set[str]:
    """Extract canonical morphological roots using deterministic longest-suffix-first stripping."""
    w = word.lower()
    roots = {w}
    for suffix in _ROOT_SUFFIXES:
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            base = w[:-len(suffix)]
            roots.add(base)
            if suffix in ("ation", "ition", "ed") and not base.endswith("e"):
                roots.add(base + "e")
            if suffix == "ies":
                roots.add(base + "y")
    return roots


def words_match(w1: str, w2: str) -> bool:
    """Exact match or canonical root intersection."""
    r1 = get_canonical_roots(w1)
    r2 = get_canonical_roots(w2)
    return bool(r1 & r2)


def _metric_in_text(metric_raw: str, search_text: str) -> bool:
    """Check that metric_raw is semantically grounded in search_text (R1-R4)."""
    raw = metric_raw.strip()
    if not raw:
        return False

    # R4: Category-prefix handling with closed-set validation
    if ":" in raw:
        category, _, label = raw.partition(":")
        if category.strip().lower() not in _CANONICAL_CATEGORIES_LOWER:
            return False
        phrase = label.strip()
    else:
        phrase = raw

    m_tokens = re.findall(r"\b[a-z0-9]+\b", phrase.lower())
    if not m_tokens:
        return False

    search_tokens = set(re.findall(r"\b[a-z0-9]+\b", search_text.lower()))

    # R2: Three-tier classification — filter stop words and taxonomy descriptors unconditionally
    content_words = [w for w in m_tokens if w not in _STOP_WORDS and w not in _TAXONOMY_DESCRIPTORS]

    # If zero content words remain, reject immediately (no vacuous pass)
    if not content_words:
        return False

    # R3: 100% of content words must match via exact match or canonical root
    for cw in content_words:
        if not any(words_match(cw, st) for st in search_tokens):
            return False

    return True


_DISCLAIMER_RE = re.compile(
    r"\b(fictional|synthetic|for (?:evaluation|testing|demo|demonstration) purposes|not an actual company|hypothetical scenario)\b",
    re.I,
)


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
    5. Prose block metric labels must be grounded in the block text or evidence quote.
    """
    # Priority 1: Reject meta-disclaimers / synthetic boilerplate
    combined_cand_text = f"{candidate.metric_raw or ''} {candidate.value_raw or ''} {candidate.evidence_quote or ''}"
    if _DISCLAIMER_RE.search(combined_cand_text) or (
        block.block_kind != BlockKind.TABLE_CELL
        and len(block.text.strip()) < 300
        and _DISCLAIMER_RE.search(block.text)
    ):
        return GroundingResult(
            accepted=False,
            rejection_reason="meta_disclaimer_not_a_fact",
        )

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
        if block.table_context and block.table_context.parse_quality == "suspect_interleaving":
            return GroundingResult(
                accepted=False,
                rejection_reason="suspected_text_corruption",
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

        if candidate.scope.get("plausible_year_value") and candidate.confidence_hint < 0.3:
            return GroundingResult(
                accepted=False,
                rejection_reason="plausible_year_value_low_confidence",
            )

        if candidate.scope.get("unrecognized_numeric"):
            return GroundingResult(
                accepted=False,
                rejection_reason="cell_value_not_recognized_as_numeric",
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

    # Prose block: metric label must be grounded in block text or evidence quote
    search_context = f"{block.text_normalised} {normalise_text(candidate.evidence_quote or '')}"
    if not _metric_in_text(candidate.metric_raw, search_context):
        return GroundingResult(
            accepted=False,
            rejection_reason="metric_label_not_grounded",
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
