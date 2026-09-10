"""PDF parser — PyMuPDF text blocks + pdfplumber table cells.

Outputs SourceBlock records with page index, bounding box, and raw text.
Chart/image blocks are recorded with block_kind=chart|image so their
non-extraction is observable rather than invisible.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from pathlib import Path

import fitz  # PyMuPDF
import pdfplumber

from fkl.domain.enums import BlockKind
from fkl.domain.models import BoundingBox, SourceBlock, TableContext
from fkl.domain.normalisation import normalise_text

logger = logging.getLogger(__name__)

_PAGE_NUMBER_RE = re.compile(r"^\s*\d{1,4}\s*$")
_WS_ONLY = re.compile(r"^\s*$")

# Minimum text length to be worth keeping
_MIN_BLOCK_LEN = 10


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def _balance_parens(s: str) -> str:
    """Ensure any string ending with unbalanced open parentheses gets balanced."""
    if not s:
        return s
    diff = s.count("(") - s.count(")")
    return s + (")" * diff) if diff > 0 else s


def _block_overlaps_table(
    bbox_raw: tuple[float, float, float, float] | list[float] | None,
    table_bboxes: list[tuple[float, float, float, float]],
) -> bool:
    """Return True if block significantly overlaps or is inside any table bounding box."""
    if not bbox_raw or not table_bboxes:
        return False
    bx0, by0, bx1, by1 = bbox_raw
    b_area = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    if b_area <= 0:
        return False

    for tx0, ty0, tx1, ty1 in table_bboxes:
        ix0 = max(bx0, tx0)
        iy0 = max(by0, ty0)
        ix1 = min(bx1, tx1)
        iy1 = min(by1, ty1)

        if ix1 > ix0 and iy1 > iy0:
            inter_area = (ix1 - ix0) * (iy1 - iy0)
            cx = (bx0 + bx1) / 2.0
            cy = (by0 + by1) / 2.0
            if (inter_area / b_area >= 0.4) or (tx0 <= cx <= tx1 and ty0 <= cy <= ty1):
                return True
    return False


def _detect_printed_label(page_text_blocks: list[dict]) -> str | None:
    """Attempt to identify a printed page label from footer/header blocks."""
    for block in page_text_blocks:
        text = block.get("text", "").strip()
        if _PAGE_NUMBER_RE.match(text):
            return text
    return None


def resolve_canonical_entity(mupdf_doc: fitz.Document) -> str | None:
    """
    Resolve a single canonical entity name for the document once during ingestion.
    Prioritises corporate/institutional indicators, followed by topmost/largest headings on page 1.
    """
    if len(mupdf_doc) == 0:
        return None

    # Check author metadata if it represents an organization/institution
    author = (mupdf_doc.metadata.get("author") or "").strip()
    if author and author.lower() not in ("", "(anonymous)", "unknown", "admin", "unspecified") and not author.endswith(".pdf"):
        if any(w in author.lower() for w in ["imf", "bank", "ministry", "limited", "ltd", "corp", "corporation", "fund", "government", "reserve bank"]):
            return author

    ignore_re = re.compile(
        r"^(contents|table of contents|preface|acknowledgement|abbreviations|chapter|part\s+\w+|volume|index|page(\s+no\.?)?|\d+|[ivxlcdm]+$)",
        re.I,
    )
    toc_dots_re = re.compile(r"\.{4,}")
    corp_re = re.compile(
        r"\b(limited|ltd|corporation|corp|inc|bank|ministry|department|fund|council|board|trust|government|reserve bank)\b",
        re.I,
    )

    candidates: list[tuple[float, str]] = []
    for page_idx in range(min(3, len(mupdf_doc))):
        page = mupdf_doc[page_idx]
        d = page.get_text("dict")
        for b in d.get("blocks", []):
            if "lines" in b:
                for l in b["lines"]:
                    spans = [s for s in l["spans"] if s.get("text", "").strip()]
                    if not spans:
                        continue
                    line_text = " ".join(s["text"].strip() for s in spans)
                    line_clean = line_text.strip()
                    if not line_clean or len(line_clean) < 3 or len(line_clean) > 100:
                        continue
                    if ignore_re.search(line_clean) or toc_dots_re.search(line_clean):
                        continue

                    max_sz = max(s.get("size", 10.0) for s in spans)
                    y0 = l["bbox"][1]
                    is_corp = bool(corp_re.search(line_clean))
                    score = (100 if is_corp else 0) + max_sz + (20 if page_idx == 0 else 0) - (y0 * 0.01)
                    candidates.append((score, line_clean))

    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    return author or None


def parse_pdf(document_id: str, pdf_path: Path) -> tuple[list[SourceBlock], int, list[str], str | None]:
    """
    Parse a PDF into SourceBlock records.

    Returns:
        (blocks, page_count, warnings, canonical_entity)

    One bad page yields a warning; remaining pages continue.
    """
    blocks: list[SourceBlock] = []
    warnings: list[str] = []

    try:
        mupdf_doc = fitz.open(str(pdf_path))
    except Exception as e:
        raise RuntimeError(f"Cannot open PDF: {e}") from e

    page_count = len(mupdf_doc)
    canonical_entity = resolve_canonical_entity(mupdf_doc)
    if not canonical_entity:
        warnings.append("entity resolution failed for this document — facts may have inconsistent entity attribution")

    try:
        plumber_doc = pdfplumber.open(str(pdf_path))
    except Exception as e:
        logger.warning("pdfplumber failed to open (tables disabled): %s", e)
        plumber_doc = None
        warnings.append(f"pdfplumber open failed: {e}")

    for page_idx in range(page_count):
        pdf_page_index = page_idx + 1  # 1-based
        try:
            mupdf_page = mupdf_doc[page_idx]
            raw_blocks = mupdf_page.get_text("blocks", sort=True)  # type: ignore[attr-defined]
            page_dict_blocks = [
                {"text": b[4], "bbox": b[:4], "type": b[6]} for b in raw_blocks
            ]
        except Exception as e:
            warnings.append(f"Page {pdf_page_index}: PyMuPDF extraction error — {e}")
            continue

        printed_label = _detect_printed_label(page_dict_blocks)

        # 1. Identify tables and table bboxes first
        table_blocks: list[SourceBlock] = []
        table_bboxes: list[tuple[float, float, float, float]] = []

        mupdf_tables = _extract_mupdf_tables(
            document_id, pdf_page_index, printed_label, mupdf_page, page_dict_blocks
        )
        if mupdf_tables:
            table_blocks = mupdf_tables
            try:
                tabs = mupdf_page.find_tables()
                for tab in tabs.tables:
                    table_bboxes.append(tuple(tab.bbox))
            except Exception:
                pass
        elif plumber_doc:
            try:
                plumber_page = plumber_doc.pages[page_idx]
                table_blocks = _extract_table_blocks(
                    document_id, pdf_page_index, printed_label, plumber_page
                )
                try:
                    ptabs = plumber_page.find_tables()
                    for ptab in ptabs:
                        table_bboxes.append(tuple(ptab.bbox))
                except Exception:
                    pass
            except Exception as e:
                warnings.append(f"Page {pdf_page_index}: pdfplumber table error — {e}")

        # Fallback to cell bboxes if find_tables didn't collect bboxes
        if not table_bboxes and table_blocks:
            for tb in table_blocks:
                if tb.bbox:
                    bb = tb.bbox
                    btup = (bb.x0, bb.y0, bb.x1, bb.y1)
                    if btup not in table_bboxes:
                        table_bboxes.append(btup)

        # 2. Extract non-table blocks, filtering out blocks that overlap detected tables
        for b_info in page_dict_blocks:
            text = b_info["text"]
            block_type = b_info.get("type", 0)
            bbox_raw = b_info.get("bbox")

            if _WS_ONLY.match(text):
                continue

            # block_type 1 = image in PyMuPDF
            if block_type == 1:
                block_id = f"blk_{uuid.uuid4().hex[:12]}"
                blocks.append(
                    SourceBlock(
                        id=block_id,
                        document_id=document_id,
                        pdf_page_index=pdf_page_index,
                        printed_page_label=printed_label,
                        block_kind=BlockKind.IMAGE,
                        bbox=BoundingBox(x0=bbox_raw[0], y0=bbox_raw[1], x1=bbox_raw[2], y1=bbox_raw[3]) if bbox_raw else None,
                        text="[IMAGE BLOCK — non-extractable]",
                        text_normalised="image block non-extractable",
                        content_hash=_content_hash(f"image_{block_id}"),
                    )
                )
                continue

            if len(text.strip()) < _MIN_BLOCK_LEN:
                continue

            # Filter out text blocks that fall inside a detected table bounding box
            if _block_overlaps_table(bbox_raw, table_bboxes):
                continue

            bbox = BoundingBox(x0=bbox_raw[0], y0=bbox_raw[1], x1=bbox_raw[2], y1=bbox_raw[3]) if bbox_raw else None

            # Detect approximate block kind from size/position heuristics
            kind = _classify_block_kind(text, bbox, mupdf_page.rect.height)

            block_id = f"blk_{uuid.uuid4().hex[:12]}"
            blocks.append(
                SourceBlock(
                    id=block_id,
                    document_id=document_id,
                    pdf_page_index=pdf_page_index,
                    printed_page_label=printed_label,
                    block_kind=kind,
                    bbox=bbox,
                    text=text,
                    text_normalised=normalise_text(text),
                    content_hash=_content_hash(text),
                )
            )

        # 3. Add table blocks (TABLE_CELL)
        if table_blocks:
            blocks.extend(table_blocks)

    if plumber_doc:
        try:
            plumber_doc.close()
        except Exception:
            pass
    mupdf_doc.close()

    return blocks, page_count, warnings, canonical_entity


def _classify_block_kind(text: str, bbox: BoundingBox | None, page_height: float) -> BlockKind:
    """Heuristic block kind from content and position."""
    stripped = text.strip()
    # Short ALL_CAPS or short blocks at top/bottom are likely headings or footers
    if len(stripped) < 80 and (stripped.isupper() or stripped.istitle()):
        if bbox and bbox.y0 > page_height * 0.85:
            return BlockKind.FOOTER
        return BlockKind.HEADING
    # Chart/figure captions
    if re.match(r"^(figure|chart|exhibit|graph|diagram|table)\s+\d", stripped, re.I):
        return BlockKind.CHART
    return BlockKind.PARAGRAPH


def _extract_mupdf_tables(
    document_id: str,
    pdf_page_index: int,
    printed_label: str | None,
    mupdf_page,
    page_dict_blocks: list[dict],
) -> list[SourceBlock]:
    """Extract labelled table cells using PyMuPDF native find_tables()."""
    result: list[SourceBlock] = []
    try:
        tabs = mupdf_page.find_tables()
    except Exception as e:
        logger.debug("mupdf find_tables error on page %d: %s", pdf_page_index, e)
        return []

    if not tabs or not getattr(tabs, "tables", None):
        return []

    for t in tabs.tables:
        try:
            rows = t.extract()
        except Exception:
            continue
        if not rows or len(rows) < 2:
            continue

        # Look for table title, company name, and unit note strictly above table bbox
        table_title = None
        company_title = None
        unit_note = None

        for b in page_dict_blocks:
            bbox = b.get("bbox", [0, 0, 0, 0])
            if bbox[3] > t.bbox[1] + 5:
                continue
            txt = b.get("text", "").strip()
            if not txt:
                continue
            if company_title is None and len(txt) < 80 and (txt.isupper() or "Limited" in txt or "Ltd" in txt or "Corporation" in txt):
                company_title = txt
            if re.search(r"(statement|profit|loss|balance|income|particulars|review|table|financial)", txt, re.I):
                table_title = txt.split("\n")[0].strip()
            if re.search(r"(all figures|figures in|in rs|in inr|in usd|million|crore|lakh|%)", txt, re.I):
                m = re.search(r"(all figures are in [^.]+?\b(?:million|crore|lakh|billion|inr|rs\.?|usd)\b|in rs\.?\s*(?:million|crore|lakh)|in ₹\s*(?:million|crore|lakh)|in (?:million|crore|lakh))", txt, re.I)
                if m:
                    unit_note = m.group(1).strip()
                else:
                    unit_note = txt.split(".")[0].strip()

        # Keep table title and company title genuinely separate (Fix 1)
        col_headers = None
        for b in page_dict_blocks:
            bbox = b.get("bbox", [0, 0, 0, 0])
            if abs(bbox[1] - t.bbox[1]) < 25 or (bbox[1] <= t.bbox[1] and bbox[3] >= t.bbox[1]):
                lines = [l.strip() for l in b.get("text", "").split("\n") if l.strip()]
                if len(lines) >= len(rows[0]) - 1:
                    col_headers = lines
                    break

        if not col_headers:
            col_headers = [str(h).strip() if h else "" for h in (rows[0] or [])]

        # Ensure parenthetical qualifiers in column headers are balanced (Fix 6)
        col_headers = [_balance_parens(h) for h in col_headers]

        # Extract data rows
        for row in rows[1:]:
            if not row or all(not cell for cell in row):
                continue
            row_header = str(row[0]).strip() if row[0] else ""
            if not row_header or row_header.lower() in ("", "particulars", "total", "subtotal", "grand total"):
                continue

            for col_idx, cell in enumerate(row[1:], start=1):
                if not cell:
                    continue
                cell_text = str(cell).strip()
                if not cell_text or cell_text in ("-", "–", "—", "N/A", "NA", "nil", "null"):
                    continue

                col_header = col_headers[col_idx] if col_idx < len(col_headers) else ""
                
                # Skip footnote/note reference columns
                if col_header.lower() in ("note", "notes", "ref", "schedule", "sl no", "s.no", "sr no"):
                    continue

                table_ctx = TableContext(
                    table_title=table_title,
                    company_name=company_title,
                    row_header=row_header,
                    column_headers=[col_header] if col_header else [],
                    cell_value=cell_text,
                    unit_note=unit_note,
                )

                full_text = json.dumps(table_ctx.model_dump(), ensure_ascii=False)
                block_id = f"blk_{uuid.uuid4().hex[:12]}"
                result.append(
                    SourceBlock(
                        id=block_id,
                        document_id=document_id,
                        pdf_page_index=pdf_page_index,
                        printed_page_label=printed_label,
                        block_kind=BlockKind.TABLE_CELL,
                        bbox=BoundingBox(x0=t.bbox[0], y0=t.bbox[1], x1=t.bbox[2], y1=t.bbox[3]),
                        text=full_text,
                        text_normalised=normalise_text(full_text),
                        table_context=table_ctx,
                        content_hash=_content_hash(full_text),
                    )
                )

    return result


def _extract_table_blocks(
    document_id: str,
    pdf_page_index: int,
    printed_label: str | None,
    plumber_page,
) -> list[SourceBlock]:
    """Extract labelled table cells from a pdfplumber page."""
    result: list[SourceBlock] = []
    tables = plumber_page.extract_tables(
        table_settings={"vertical_strategy": "lines", "horizontal_strategy": "lines"}
    )
    if not tables:
        # Try text-based strategy as fallback
        tables = plumber_page.extract_tables(
            table_settings={"vertical_strategy": "text", "horizontal_strategy": "text"}
        )

    for table in tables:
        if not table or len(table) < 2:
            continue

        # Try to find header row(s)
        header_row = table[0]
        data_rows = table[1:]

        # Skip if header row is all empty/None
        if all(not cell for cell in header_row):
            continue

        # Detect unit note (often the last row or a row that starts with "₹" / "%" / "in ")
        unit_note = _detect_unit_note(table)

        # Detect table title from nearby text (heuristic: not available here, use None)
        table_title = None

        for row in data_rows:
            if not row or all(not cell for cell in row):
                continue
            row_header = str(row[0]).strip() if row[0] else None
            if not row_header or row_header.lower() in ("", "particulars", "total", "subtotal"):
                continue

            for col_idx, cell in enumerate(row[1:], start=1):
                if not cell:
                    continue
                cell_text = str(cell).strip()
                if not cell_text or cell_text in ("-", "–", "—", "N/A", "NA"):
                    continue

                col_header = str(header_row[col_idx]).strip() if col_idx < len(header_row) else None

                table_ctx = TableContext(
                    table_title=table_title,
                    row_header=row_header,
                    column_headers=[col_header] if col_header else [],
                    cell_value=cell_text,
                    unit_note=unit_note,
                )

                full_text = json.dumps(table_ctx.model_dump(), ensure_ascii=False)
                block_id = f"blk_{uuid.uuid4().hex[:12]}"
                result.append(
                    SourceBlock(
                        id=block_id,
                        document_id=document_id,
                        pdf_page_index=pdf_page_index,
                        printed_page_label=printed_label,
                        block_kind=BlockKind.TABLE_CELL,
                        bbox=None,  # pdfplumber cell bbox extraction is costly; skip for now
                        text=full_text,
                        text_normalised=normalise_text(full_text),
                        table_context=table_ctx,
                        content_hash=_content_hash(full_text),
                    )
                )

    return result


def _detect_unit_note(table: list[list]) -> str | None:
    """Look for a row that looks like a unit declaration."""
    for row in table:
        if not row:
            continue
        first_cell = str(row[0]).strip() if row[0] else ""
        if re.search(r"(₹|rs\.|inr|\$|usd|%|percent|million|crore|lakh|billion)", first_cell, re.I):
            return first_cell
    return None
