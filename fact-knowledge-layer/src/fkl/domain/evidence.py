"""Evidence utilities — helpers for evidence display and validation."""

from __future__ import annotations

from fkl.domain.models import SourceBlock, TableContext


def evidence_summary(block: SourceBlock) -> dict:
    """Return a concise evidence summary for display."""
    base = {
        "block_id": block.id,
        "pdf_page_index": block.pdf_page_index,
        "printed_page_label": block.printed_page_label,
        "block_kind": block.block_kind.value,
    }
    if block.table_context:
        base["table_context"] = block.table_context.model_dump()
        base["text_preview"] = (
            f"Table: {block.table_context.row_header} | "
            f"Col: {', '.join(block.table_context.column_headers)} | "
            f"Value: {block.table_context.cell_value}"
        )
    else:
        base["text_preview"] = block.text[:300]
    if block.bbox:
        base["bbox"] = block.bbox.model_dump()
    return base
