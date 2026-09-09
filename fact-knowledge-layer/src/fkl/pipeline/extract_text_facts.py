"""LLM-based prose fact extraction.

Calls the LLM only on compact blocks; never on entire PDFs.
Caps:
- MAX_LLM_CALLS_PER_DOCUMENT: hard limit on API calls per doc (rate-limit budget)
- MAX_CANDIDATES_PER_PAGE: soft limit on candidates from one page
- MAX_CANDIDATES_PER_DOCUMENT: soft limit on total candidates

Block selection under the call budget uses a priority score based on:
- Number of numeric tokens (digits with % / crore / million / lakh)
- Known economic keywords (growth, inflation, deficit, GDP, revenue, etc.)

This ensures the limited free-tier RPM quota is spent on the blocks most
likely to contain extractable facts.
"""

from __future__ import annotations

import logging
import re

from fkl.domain.enums import BlockKind
from fkl.domain.models import FactCandidate, SourceBlock
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

# Keywords that indicate a block likely contains facts
_FACT_KEYWORDS = re.compile(
    r"\b(gdp|growth|inflation|deficit|surplus|revenue|expenditure|debt|fiscal|monetary|"
    r"crore|lakh|million|billion|percent|per cent|%|bps|basis points|rate|ratio|"
    r"index|output|export|import|current account|trade|remittance|forex|reserve|"
    r"profit|loss|margin|ebitda|income|expense|sales|cost|tax|dividend|asset|liability|"
    r"cash|flow|employee|employees|workforce|headcount|staff|emission|emissions|ghg|tco2e|"
    r"kwh|electricity|power|energy|capacity|volume|production|unit|units|customer|customers|"
    r"subscriber|subscribers|shipment|shipments|package|delivery|fleet|vehicle|facility|warehouse|"
    r"director|officer|compensation|salary|share|shares|equity|capital|investment|acquisition|"
    r"rbi|mospi|nso|imf|world bank|gross|net|real|nominal|year.on.year|y.o.y|"
    r"fy\d{2}|fy 20|q[1-4]|quarter|annual|monthly|weekly)\b",
    re.IGNORECASE,
)

_NUMERIC_PATTERN = re.compile(
    r"\b\d[\d,]*\.?\d*\s*(%|crore|lakh|million|billion|rs|₹|inr|usd|kwh|tco2e|tonnes|units|employees|mw|gw)?\b",
    re.IGNORECASE,
)


def _score_block(block: SourceBlock) -> float:
    """Score a block by likelihood of containing extractable facts. Higher = better."""
    text = block.text
    numeric_matches = len(_NUMERIC_PATTERN.findall(text))
    keyword_matches = len(_FACT_KEYWORDS.findall(text))
    length_bonus = min(len(text) / 500, 1.0)  # prefer moderate-length blocks
    return numeric_matches * 2.0 + keyword_matches * 1.5 + length_bonus


def extract_text_facts(
    blocks: list[SourceBlock],
    provider: FactExtractionProvider,
) -> list[tuple[FactCandidate, SourceBlock]]:
    """
    For each prose block, call the LLM with the block + nearest heading context.

    Blocks are scored by fact-density and the top MAX_LLM_CALLS_PER_DOCUMENT
    are processed in page order. Returns list of (FactCandidate, SourceBlock).
    """
    results: list[tuple[FactCandidate, SourceBlock]] = []
    total_candidates = 0
    llm_calls = 0

    # Build a page → heading map for context
    page_headings: dict[int, str] = {}
    for block in blocks:
        if block.block_kind == BlockKind.HEADING:
            page_headings[block.pdf_page_index] = block.text[:200]

    # Filter eligible blocks
    eligible = [
        b for b in blocks
        if b.block_kind in _LLM_KINDS and len(b.text.strip()) >= _MIN_PROSE_LEN
    ]

    # Score and rank — then restore page order for the top N
    scored = sorted(eligible, key=_score_block, reverse=True)
    top_blocks = set(id(b) for b in scored[:MAX_LLM_CALLS_PER_DOCUMENT])
    # Process in original page order for readable logs
    selected = [b for b in blocks if id(b) in top_blocks]

    logger.info(
        "Text extractor: %d eligible blocks, selected top %d by fact-density score",
        len(eligible), len(selected),
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
            candidates = provider.extract_facts(block=block, document_context=context)
            llm_calls += 1
        except Exception as e:
            logger.error("LLM extract_facts failed for block %s: %s", block.id, e)
            llm_calls += 1
            candidates = []

        for cand in candidates:
            results.append((cand, block))
            per_page_counts[page] = per_page_counts.get(page, 0) + 1
            total_candidates += 1

    logger.info(
        "Text extractor produced %d candidates across %d LLM calls (from %d total blocks)",
        total_candidates, llm_calls, len(blocks),
    )
    return results
