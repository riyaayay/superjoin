"""Unit tests for the grounding gate."""

import uuid
from fkl.domain.enums import BlockKind
from fkl.domain.models import BoundingBox, FactCandidate, SourceBlock, TableContext
from fkl.domain.normalisation import normalise_text
from fkl.pipeline.ground_candidates import ground


def _make_block(text: str, kind: BlockKind = BlockKind.PARAGRAPH, table_ctx=None) -> SourceBlock:
    return SourceBlock(
        id=f"blk_{uuid.uuid4().hex[:8]}",
        document_id="doc_test",
        pdf_page_index=1,
        block_kind=kind,
        text=text,
        text_normalised=normalise_text(text),
        table_context=table_ctx,
        content_hash=uuid.uuid4().hex[:32],
    )


def _make_candidate(**kwargs) -> FactCandidate:
    defaults = dict(
        entity_raw="India",
        metric_raw="GDP growth",
        value_raw="6.4%",
        unit_raw="%",
        period_raw="FY25",
        evidence_quote="6.4%",
        confidence_hint=0.7,
    )
    defaults.update(kwargs)
    return FactCandidate(**defaults)


class TestGrounding:
    def test_literal_value_accepted(self):
        block = _make_block("India's real GDP growth was 6.4% in FY25, according to the survey.")
        cand = _make_candidate()
        result = ground(cand, block)
        assert result.accepted is True
        assert result.evidence_block_id == block.id
        assert result.confidence > 0

    def test_fabricated_value_rejected(self):
        block = _make_block("India's real GDP growth was 6.4% in FY25.")
        cand = _make_candidate(value_raw="9.9%", evidence_quote="9.9%")
        result = ground(cand, block)
        assert result.accepted is False
        assert "not_found" in result.rejection_reason

    def test_missing_entity_rejected(self):
        block = _make_block("Real GDP growth was 6.4% in FY25.")
        cand = _make_candidate(entity_raw="")
        result = ground(cand, block)
        assert result.accepted is False
        assert "missing_required" in result.rejection_reason

    def test_missing_metric_rejected(self):
        block = _make_block("Real GDP growth was 6.4% in FY25.")
        cand = _make_candidate(metric_raw="")
        result = ground(cand, block)
        assert result.accepted is False

    def test_chart_block_rejected(self):
        block = _make_block("Figure 3: GDP growth chart", kind=BlockKind.CHART)
        cand = _make_candidate()
        result = ground(cand, block)
        assert result.accepted is False
        assert "chart_or_image" in result.rejection_reason

    def test_image_block_rejected(self):
        block = _make_block("[IMAGE BLOCK — non-extractable]", kind=BlockKind.IMAGE)
        cand = _make_candidate()
        result = ground(cand, block)
        assert result.accepted is False

    def test_table_cell_accepted_with_correct_value(self):
        tc = TableContext(
            row_header="Real GDP growth",
            column_headers=["FY2024-25"],
            cell_value="6.4",
            unit_note="% change",
        )
        block = _make_block('{"row_header": "Real GDP growth", "cell_value": "6.4"}',
                             kind=BlockKind.TABLE_CELL, table_ctx=tc)
        cand = _make_candidate(value_raw="6.4", evidence_quote="6.4")
        result = ground(cand, block)
        assert result.accepted is True
        assert result.confidence >= 0.7

    def test_table_cell_wrong_value_rejected(self):
        tc = TableContext(
            row_header="Real GDP growth",
            column_headers=["FY2024-25"],
            cell_value="6.4",
            unit_note="% change",
        )
        block = _make_block('{"row_header": "Real GDP growth", "cell_value": "6.4"}',
                             kind=BlockKind.TABLE_CELL, table_ctx=tc)
        cand = _make_candidate(value_raw="7.0", evidence_quote="7.0")
        result = ground(cand, block)
        assert result.accepted is False

    def test_table_cell_without_row_header_rejected(self):
        tc = TableContext(
            row_header=None,
            column_headers=["FY2024-25"],
            cell_value="6.4",
        )
        block = _make_block('{"cell_value": "6.4"}', kind=BlockKind.TABLE_CELL, table_ctx=tc)
        cand = _make_candidate(value_raw="6.4", evidence_quote="6.4")
        result = ground(cand, block)
        assert result.accepted is False
        assert "missing_row_header" in result.rejection_reason

    def test_comma_formatted_value_accepted(self):
        """Comma-formatted numbers should be found via numeric stripping."""
        block = _make_block("The fiscal deficit was ₹16,85,494 crore in FY24.")
        cand = _make_candidate(
            metric_raw="Fiscal deficit",
            value_raw="16,85,494",
            evidence_quote="16,85,494",
        )
        result = ground(cand, block)
        assert result.accepted is True

    def test_low_confidence_fact_needs_review(self):
        """Candidates with confidence < 0.65 must receive review_state == 'needs_review'."""
        from fkl.application.ingest_document import _make_fact
        from fkl.domain.enums import ExtractionMethod, ReviewState
        from fkl.pipeline.ground_candidates import GroundingResult

        cand = _make_candidate(confidence_hint=0.55)
        grounding = GroundingResult(
            accepted=True,
            evidence_block_id="blk_123",
            confidence=0.55,
        )
        fact = _make_fact(cand, grounding, "run_1", "doc_1", ExtractionMethod.TEXT_LLM)
        assert fact.review_state == ReviewState.NEEDS_REVIEW
        assert fact.review_state.value == "needs_review"

    def test_high_confidence_fact_accepted(self):
        """Candidates with confidence >= 0.65 must receive review_state == 'accepted'."""
        from fkl.application.ingest_document import _make_fact
        from fkl.domain.enums import ExtractionMethod, ReviewState
        from fkl.pipeline.ground_candidates import GroundingResult

        cand = _make_candidate(confidence_hint=0.85)
        grounding = GroundingResult(
            accepted=True,
            evidence_block_id="blk_123",
            confidence=0.85,
        )
        fact = _make_fact(cand, grounding, "run_1", "doc_1", ExtractionMethod.TEXT_LLM)
        assert fact.review_state == ReviewState.ACCEPTED
        assert fact.review_state.value == "accepted"


class TestPlausibleYearGrounding:
    def test_plausible_year_low_confidence_rejected(self):
        ctx = TableContext(
            row_header="Employee count",
            cell_value="2025",
            column_headers=["FY24"],
        )
        block = SourceBlock(
            id="blk_year_1",
            document_id="doc_1",
            pdf_page_index=1,
            block_kind=BlockKind.TABLE_CELL,
            text="2025",
            text_normalised="2025",
            table_context=ctx,
            content_hash="h_year_1",
        )
        cand = FactCandidate(
            entity_raw="Solstice Robotics",
            metric_raw="Employee count",
            value_raw="2025",
            scope={"plausible_year_value": True},
            confidence_hint=0.15,
        )
        res = ground(cand, block)
        assert res.accepted is False
        assert res.rejection_reason == "plausible_year_value_low_confidence"

    def test_plausible_year_high_confidence_accepted(self):
        ctx = TableContext(
            row_header="Employee count",
            cell_value="2025",
            column_headers=["Headcount"],
        )
        block = SourceBlock(
            id="blk_year_2",
            document_id="doc_1",
            pdf_page_index=1,
            block_kind=BlockKind.TABLE_CELL,
            text="2025",
            text_normalised="2025",
            table_context=ctx,
            content_hash="h_year_2",
        )
        cand = FactCandidate(
            entity_raw="Solstice Robotics",
            metric_raw="Employee count",
            value_raw="2025",
            scope={"plausible_year_value": True},
            confidence_hint=0.85,
        )
        res = ground(cand, block)
        assert res.accepted is True

    def test_suspected_text_corruption_rejection(self):
        """Table cells flagged with suspect_interleaving must be rejected with suspected_text_corruption."""
        ctx = TableContext(
            row_header="with effect from March 1, 20",
            cell_value="25.",
            column_headers=["OCERY"],
            parse_quality="suspect_interleaving",
        )
        block = SourceBlock(
            id="blk_corrupt_1",
            document_id="doc_1",
            pdf_page_index=1,
            block_kind=BlockKind.TABLE_CELL,
            text="25.",
            text_normalised="25",
            table_context=ctx,
            content_hash="h_corrupt_1",
        )
        cand = FactCandidate(
            entity_raw="Meridian Grocery Co-operative Society",
            metric_raw="with effect from March 1, 20",
            value_raw="25.",
            evidence_quote="25.",
            confidence_hint=0.85,
        )
        res = ground(cand, block)
        assert res.accepted is False
        assert res.rejection_reason == "suspected_text_corruption"

    def test_check_suspect_interleaving_heuristics(self):
        """Check that suspect interleaving heuristics distinguish corrupted fragments from valid headers."""
        from fkl.pipeline.parse_pdf import check_suspect_interleaving

        # Meridian broken fragments
        assert check_suspect_interleaving("with effect from March 1, 20", ["OCERY"]) is True
        assert check_suspect_interleaving("average annual purchase va", ["OCERY", "CO-OP", "ERATIVE", "SOCIET", "Y"]) is True
        assert check_suspect_interleaving(None, ["OCERY", "CO-OP", "ERATIVE", "SOCIET", "Y"]) is True
        assert check_suspect_interleaving("The Managing Committee n", ["SOCIET"]) is True

        # Valid headers
        assert check_suspect_interleaving("Revenue from operations", ["FY23", "FY22"]) is False
        assert check_suspect_interleaving("Active deployed robot units", ["YoY", "Q2 FY24", "Q2 FY23"]) is False
        assert check_suspect_interleaving("Total employees (standalone, as of period end)", ["Nine months ended Sep 30, 2021"]) is False
        assert check_suspect_interleaving("Gross Margin (%)", ["Q1", "Q2", "FY24"]) is False

