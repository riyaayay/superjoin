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
