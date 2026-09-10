"""Unit tests for table fact extraction."""

import pytest
from fkl.domain.enums import BlockKind
from fkl.domain.models import SourceBlock, TableContext
from fkl.pipeline.extract_table_facts import _is_period_header, extract_table_facts


def test_is_period_header_patterns():
    # Valid period headers that must be detected and filtered
    assert _is_period_header("2026") is True
    assert _is_period_header("2024") is True
    assert _is_period_header("1999") is True
    assert _is_period_header("FY28") is True
    assert _is_period_header("fy24") is True
    assert _is_period_header("FY 2027-28") is True
    assert _is_period_header("FY2023-2024") is True

    # Real metric row headers that must NOT be filtered
    assert _is_period_header("Revenue from operations") is False
    assert _is_period_header("Employee count") is False
    assert _is_period_header("Total assets") is False
    assert _is_period_header("EBITDA") is False


def test_table_row_period_header_skipped():
    ctx_year = TableContext(
        row_header="2026",
        cell_value="150.0",
        column_headers=["FY26"],
    )
    b_year = SourceBlock(
        id="blk_1",
        document_id="doc_test",
        pdf_page_index=1,
        block_kind=BlockKind.TABLE_CELL,
        text="150.0",
        text_normalised="150.0",
        table_context=ctx_year,
        content_hash="h1",
    )

    ctx_fy = TableContext(
        row_header="FY 2027-28",
        cell_value="250.0",
        column_headers=["Projections"],
    )
    b_fy = SourceBlock(
        id="blk_2",
        document_id="doc_test",
        pdf_page_index=1,
        block_kind=BlockKind.TABLE_CELL,
        text="250.0",
        text_normalised="250.0",
        table_context=ctx_fy,
        content_hash="h2",
    )

    ctx_metric = TableContext(
        row_header="Operating Revenue",
        cell_value="350.0",
        column_headers=["FY26"],
    )
    b_metric = SourceBlock(
        id="blk_3",
        document_id="doc_test",
        pdf_page_index=1,
        block_kind=BlockKind.TABLE_CELL,
        text="350.0",
        text_normalised="350.0",
        table_context=ctx_metric,
        content_hash="h3",
    )

    candidates = extract_table_facts([b_year, b_fy, b_metric])
    # The first two (period headers) should be skipped; only the third should be emitted
    assert len(candidates) == 1
    cand, block = candidates[0]
    assert cand.metric_raw == "Operating Revenue"
    assert cand.value_raw == "350.0"


def test_broadened_numeric_cells():
    from fkl.domain.normalisation import parse_numeric
    from fkl.pipeline.ground_candidates import ground

    def _make_block(val: str, bid: str) -> SourceBlock:
        ctx = TableContext(
            row_header="Debt to Equity Multiple",
            cell_value=val,
            column_headers=["FY24"],
        )
        return SourceBlock(
            id=bid,
            document_id="doc_test",
            pdf_page_index=1,
            block_kind=BlockKind.TABLE_CELL,
            text=val,
            text_normalised=val,
            table_context=ctx,
            content_hash=f"h_{bid}",
        )

    b1 = _make_block("8.3x", "b1")
    b2 = _make_block("₹8.3", "b2")
    b3 = _make_block("\u22128.3", "b3")
    b4 = _make_block("See Note 4", "b4")

    candidates = extract_table_facts([b1, b2, b3, b4])
    assert len(candidates) == 4

    c1, _ = candidates[0]
    assert c1.value_raw == "8.3x"
    assert c1.unit_raw == "x"
    assert parse_numeric(c1.value_raw) == pytest.approx(8.3)
    res1 = ground(c1, b1)
    assert res1.accepted is True

    c2, _ = candidates[1]
    assert c2.value_raw == "₹8.3"
    assert c2.unit_raw == "₹"
    assert parse_numeric(c2.value_raw) == pytest.approx(8.3)
    res2 = ground(c2, b2)
    assert res2.accepted is True

    c3, _ = candidates[2]
    assert c3.value_raw == "\u22128.3"
    assert parse_numeric(c3.value_raw) == pytest.approx(-8.3)
    res3 = ground(c3, b3)
    assert res3.accepted is True

    c4, _ = candidates[3]
    assert c4.value_raw == "See Note 4"
    assert c4.scope.get("unrecognized_numeric") is True
    res4 = ground(c4, b4)
    assert res4.accepted is False
    assert res4.rejection_reason == "cell_value_not_recognized_as_numeric"


def test_unrecognized_qualifier_capture():
    ctx = TableContext(
        row_header="Revenue",
        cell_value="1200.0",
        column_headers=["Unaudited — Q2 FY24"],
    )
    block = SourceBlock(
        id="blk_qual",
        document_id="doc_test",
        pdf_page_index=1,
        block_kind=BlockKind.TABLE_CELL,
        text="1200.0",
        text_normalised="1200.0",
        table_context=ctx,
        content_hash="h_qual",
    )
    candidates = extract_table_facts([block])
    assert len(candidates) == 1
    cand, _ = candidates[0]
    assert cand.scope.get("unrecognized_qualifier") == "unaudited"
