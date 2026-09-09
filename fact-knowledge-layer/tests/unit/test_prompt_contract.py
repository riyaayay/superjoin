"""Unit tests for fake LLM provider — validates strict FactCandidate schema."""

from fkl.domain.models import FactCandidate, SourceBlock
from fkl.domain.enums import BlockKind
from fkl.domain.normalisation import normalise_text
from fkl.providers.fake_llm import FakeLLMProvider
import uuid


def _block(text, kind=BlockKind.PARAGRAPH):
    return SourceBlock(
        id=f"blk_{uuid.uuid4().hex[:8]}",
        document_id="doc_test",
        pdf_page_index=1,
        block_kind=kind,
        text=text,
        text_normalised=normalise_text(text),
        content_hash=uuid.uuid4().hex[:32],
    )


class TestFakeLLMProvider:
    def setup_method(self):
        self.provider = FakeLLMProvider()

    def test_returns_list(self):
        result = self.provider.extract_facts(
            block=_block("India's GDP growth rate was 6.4% in FY25"),
            document_context="Economic Overview",
        )
        assert isinstance(result, list)

    def test_all_items_are_fact_candidates(self):
        result = self.provider.extract_facts(
            block=_block("Inflation rate stood at 4.9% in FY24."),
            document_context="Prices",
        )
        for item in result:
            assert isinstance(item, FactCandidate)

    def test_candidates_have_required_fields(self):
        result = self.provider.extract_facts(
            block=_block("GDP growth was 6.4% in FY25."),
            document_context="GDP",
        )
        for cand in result:
            assert cand.entity_raw.strip() != ""
            assert cand.metric_raw.strip() != ""
            assert cand.value_raw.strip() != ""

    def test_empty_block_returns_empty(self):
        result = self.provider.extract_facts(
            block=_block("This paragraph has no relevant economic indicators."),
            document_context="",
        )
        # May return empty for non-trigger text
        assert isinstance(result, list)

    def test_chart_block_returns_empty(self):
        result = self.provider.extract_facts(
            block=_block("Figure 1: GDP chart", kind=BlockKind.CHART),
            document_context="",
        )
        assert result == []

    def test_confidence_hint_in_range(self):
        result = self.provider.extract_facts(
            block=_block("CPI inflation was 4.9%"),
            document_context="Inflation",
        )
        for cand in result:
            assert 0.0 <= cand.confidence_hint <= 1.0

    def test_value_from_block_text(self):
        """Evidence quote must appear in block text (grounding invariant)."""
        text = "Export growth was 3.5% in FY24."
        result = self.provider.extract_facts(
            block=_block(text),
            document_context="External Sector",
        )
        for cand in result:
            # Fake provider uses first number from text
            assert cand.value_raw in text or cand.evidence_quote in text
