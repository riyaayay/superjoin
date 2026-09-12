"""LLM-based prose fact extraction.

Calls the LLM only on compact blocks; never on entire PDFs.
Caps:
- MAX_LLM_CALLS_PER_DOCUMENT: hard limit on API calls per doc (rate-limit budget)
- MAX_CANDIDATES_PER_PAGE: soft limit on candidates from one page
- MAX_CANDIDATES_PER_DOCUMENT: soft limit on total candidates

Block selection under the call budget uses domain-agnostic structural signals:
- Count of digit sequences (bare numbers count)
- Currency symbols or generic scale words
- Percentage symbol (%)
- Length bonus
Budget is distributed per section (defined by preceding headings) to ensure
coverage across all document sections.
"""

from __future__ import annotations

import logging
import re

from fkl.domain.enums import BlockKind
from fkl.domain.models import ExtractionStats, FactCandidate, SourceBlock
from fkl.domain.normalisation import SCALE_TO_MULTIPLIER
from fkl.providers.llm import FactExtractionProvider

logger = logging.getLogger(__name__)

# Per-page and per-document caps
MAX_CANDIDATES_PER_PAGE = 20
MAX_CANDIDATES_PER_DOCUMENT = 500

# Hard cap on LLM API calls per document (stay within free-tier 5 RPM budget)
# At 5 RPM: 30 calls = ~6 minutes of processing per document.
MAX_LLM_CALLS_PER_DOCUMENT = 30

# Block kinds to send to LLM (not tables, charts, images)
_LLM_KINDS = {BlockKind.PARAGRAPH, BlockKind.HEADING}

# Minimum block length to bother calling LLM
_MIN_PROSE_LEN = 40

_GENERIC_ENTITIES = frozenset([
    "the company", "company", "the group", "group",
    "the corporation", "corporation", "the bank", "the firm", "entity", "",
])

_NUMERIC_CELL_RE = re.compile(r"^[\(\-]?[\d,]+\.?\d*\%?\)?$")

_DIGIT_SEQ_RE = re.compile(r"\b\d+[\d,]*\.?\d*\b")
_SCALE_WORDS = [k for k in SCALE_TO_MULTIPLIER.keys() if k and k not in ("percent", "%")]
_CURRENCY_OR_SCALE_RE = re.compile(
    r"([₹$€£¥]|(?:\b(?:rs\.?|inr|usd|eur|gbp|" + "|".join(re.escape(k) for k in _SCALE_WORDS) + r")\b))",
    re.IGNORECASE,
)
_PERCENT_RE = re.compile(r"(%|\bpercent\b)", re.IGNORECASE)


def _is_table_like_text(text: str) -> bool:
    """Detect if a text block is essentially a raw tabular row or numeric data grid."""
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    for line in lines:
        tokens = line.split()
        if not tokens:
            continue
        num_tokens = sum(1 for t in tokens if _NUMERIC_CELL_RE.match(t.strip()))
        if num_tokens >= 3 and (num_tokens / len(tokens)) >= 0.4:
            return True
        if len(tokens) >= 4 and (num_tokens / len(tokens)) >= 0.5:
            return True
    return False


def _score_block(block: SourceBlock) -> float:
    """Score a block by domain-agnostic likelihood of containing extractable facts."""
    text = block.text
    digit_count = len(_DIGIT_SEQ_RE.findall(text))
    currency_or_scale = 1.5 if _CURRENCY_OR_SCALE_RE.search(text) else 0.0
    percent_bonus = 1.0 if _PERCENT_RE.search(text) else 0.0
    length_bonus = min(len(text) / 500.0, 1.0)
    return digit_count * 2.0 + currency_or_scale + percent_bonus + length_bonus


def extract_text_facts(
    blocks: list[SourceBlock],
    provider: FactExtractionProvider,
    canonical_entity: str | None = None,
) -> tuple[list[tuple[FactCandidate, SourceBlock]], ExtractionStats]:
    """
    For each prose block, call the LLM with the block + nearest heading context.

    Uses domain-agnostic structural scoring and per-section budget allocation.
    Returns (results, extraction_stats).
    """
    results: list[tuple[FactCandidate, SourceBlock]] = []
    total_candidates = 0
    llm_calls = 0

    # Build a page → heading map for context, and map blocks to preceding headings
    page_headings: dict[int, str] = {}
    current_heading = "Overview"
    block_section_map: dict[str, str] = {}

    for block in blocks:
        if block.block_kind == BlockKind.HEADING:
            page_headings[block.pdf_page_index] = block.text[:200]
            current_heading = block.text.strip()[:100] or "Section"
        block_section_map[block.id] = current_heading

    # Filter eligible blocks — exclude table-like numeric grids
    eligible = [
        b for b in blocks
        if b.block_kind in _LLM_KINDS
        and len(b.text.strip()) >= _MIN_PROSE_LEN
        and not _is_table_like_text(b.text)
    ]

    # Group eligible blocks by section
    sections: dict[str, list[SourceBlock]] = {}
    for b in eligible:
        sec = block_section_map.get(b.id, "Overview")
        sections.setdefault(sec, []).append(b)

    # Sort blocks within each section by domain-agnostic score
    for sec in sections:
        sections[sec].sort(key=_score_block, reverse=True)

    # Allocate per-section budget
    selected_blocks_set: set[str] = set()
    num_sections = len(sections)

    if num_sections > 0:
        k = max(1, MAX_LLM_CALLS_PER_DOCUMENT // num_sections)
        # Guarantee top k from each section (or at least 1)
        for sec, sec_blocks in sections.items():
            for b in sec_blocks[:k]:
                if len(selected_blocks_set) < MAX_LLM_CALLS_PER_DOCUMENT:
                    selected_blocks_set.add(b.id)

        # Fill leftover budget document-wide with next highest-scoring
        if len(selected_blocks_set) < MAX_LLM_CALLS_PER_DOCUMENT:
            remaining = [b for b in eligible if b.id not in selected_blocks_set]
            remaining.sort(key=_score_block, reverse=True)
            for b in remaining:
                if len(selected_blocks_set) >= MAX_LLM_CALLS_PER_DOCUMENT:
                    break
                selected_blocks_set.add(b.id)

    # Process selected in original document order
    selected = [b for b in blocks if b.id in selected_blocks_set]

    # Compute coverage stats
    sections_covered = len(set(block_section_map.get(b.id, "Overview") for b in selected))
    stats = ExtractionStats(
        prose_blocks_total=len(eligible),
        prose_blocks_llm_called=len(selected),
        prose_blocks_skipped_due_to_cap=max(0, len(eligible) - len(selected)),
        sections_total=num_sections,
        sections_covered=sections_covered,
    )

    logger.info(
        "Text extractor: %d eligible blocks across %d sections, selected %d (covered %d sections, skipped %d)",
        len(eligible), num_sections, len(selected), sections_covered, stats.prose_blocks_skipped_due_to_cap,
    )

    per_page_counts: dict[int, int] = {}

    for block in selected:
        if total_candidates >= MAX_CANDIDATES_PER_DOCUMENT:
            logger.warning("Reached per-document candidate cap (%d)", MAX_CANDIDATES_PER_DOCUMENT)
            break
        if llm_calls >= MAX_LLM_CALLS_PER_DOCUMENT:
            logger.info("Reached per-document LLM call cap (%d)", MAX_LLM_CALLS_PER_DOCUMENT)
            break

        page = block.pdf_page_index
        if per_page_counts.get(page, 0) >= MAX_CANDIDATES_PER_PAGE:
            continue

        context = page_headings.get(page, "")
        try:
            candidates = provider.extract_facts(
                block=block, document_context=context, canonical_entity=canonical_entity
            )
            llm_calls += 1
        except Exception as e:
            logger.error("LLM extract_facts failed for block %s: %s", block.id, e)
            llm_calls += 1
            candidates = []

        for cand in candidates:
            # Generic entity resolution with scope preservation
            raw_ent = cand.entity_raw.strip().lower()
            if raw_ent in _GENERIC_ENTITIES:
                if "group" in raw_ent:
                    cand.scope.setdefault("consolidation", "consolidated")
                elif "company" in raw_ent:
                    cand.scope.setdefault("consolidation", "standalone")
                if canonical_entity:
                    cand.entity_raw = canonical_entity

            # Preserve standalone/consolidated scope from metric or evidence quote (Priority 2)
            cand_text = f"{cand.metric_raw} {cand.evidence_quote or ''}".lower()
            if "standalone" in cand_text:
                cand.scope.setdefault("consolidation", "standalone")
            elif "consolidated" in cand_text:
                cand.scope.setdefault("consolidation", "consolidated")

            results.append((cand, block))
            per_page_counts[page] = per_page_counts.get(page, 0) + 1
            total_candidates += 1

    stats.prose_blocks_llm_called = llm_calls

    logger.info(
        "Text extractor produced %d candidates across %d LLM calls (from %d total blocks, skipped %d)",
        total_candidates, llm_calls, len(blocks), stats.prose_blocks_skipped_due_to_cap,
    )
    return results, stats
