"""Unit tests for domain-agnostic text facts extraction and section budgeting."""

import pytest

from fkl.domain.enums import BlockKind
from fkl.domain.models import FactCandidate, SourceBlock
from fkl.pipeline.extract_text_facts import _score_block, extract_text_facts
from fkl.providers.fake_llm import FakeLLMProvider


def _block(
    block_id: str,
    text: str,
    kind: BlockKind = BlockKind.PARAGRAPH,
    page: int = 1,
) -> SourceBlock:
    return SourceBlock(
        id=block_id,
        document_id="doc_test",
        pdf_page_index=page,
        block_kind=kind,
        text=text,
        text_normalised=text.lower().strip(),
        content_hash=f"hash_{block_id}",
    )


def test_score_block_domain_agnostic():
    # SaaS/retail text with numbers and zero old macro keywords (no gdp, rbi, crore, etc.)
    text_saas = "In Q3, customer churn dropped to 1.8% while server compute bill reached $45,000 across 3 regions."
    b1 = _block("b1", text_saas)
    score1 = _score_block(b1)
    # Must have non-zero score based on digits, currency symbol $, % and length
    assert score1 > 4.0

    # Plain text without any numbers or currency
    text_plain = "The strategic road-map is aligned with our long-term customer journey initiatives."
    b2 = _block("b2", text_plain)
    score2 = _score_block(b2)
    assert score2 < 1.0
    assert score1 > score2


def test_per_section_budget_coverage():
    # Synthetic document with distinct domain headings
    blocks = [
        _block("h1", "Customer churn analysis", kind=BlockKind.HEADING, page=1),
        _block(
            "p1_1",
            "Monthly recurring customer attrition reached 4.2% across mid-tier accounts.",
            kind=BlockKind.PARAGRAPH,
            page=1,
        ),
        _block(
            "p1_2",
            "Net promoter score surveyed 1,240 subscribers indicating high satisfaction.",
            kind=BlockKind.PARAGRAPH,
            page=1,
        ),
        _block("h2", "Cloud infrastructure spend", kind=BlockKind.HEADING, page=2),
        _block(
            "p2_1",
            "Kubernetes clusters consumed $82,500 with bandwidth peaking at 940 terabytes.",
            kind=BlockKind.PARAGRAPH,
            page=2,
        ),
        _block("h3", "Employee attrition", kind=BlockKind.HEADING, page=3),
        _block(
            "p3_1",
            "Voluntary departures totaled 14 engineers in 2024, down from 29 in 2023.",
            kind=BlockKind.PARAGRAPH,
            page=3,
        ),
    ]

    provider = FakeLLMProvider()
    results, stats = extract_text_facts(blocks, provider)

    assert stats.sections_total == 3
    assert stats.sections_covered == 3
    assert stats.prose_blocks_llm_called == 4
    assert stats.prose_blocks_total == 4
    assert stats.prose_blocks_skipped_due_to_cap == 0
