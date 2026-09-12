"""Relationships API router."""

from __future__ import annotations

import json

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from fkl.api.deps import get_db
from fkl.persistence import repositories

router = APIRouter(prefix="/api/relationships", tags=["relationships"])


def _format_fact_with_evidence(fact, db: Session) -> dict | None:
    """Return fact fields + evidence block fields needed for inline accordion display."""
    if not fact:
        return None
    block = repositories.get_block(db, fact.evidence_block_id)
    tc = json.loads(block.table_context_json) if (block and block.table_context_json) else None
    bbox = json.loads(block.bbox_json) if (block and block.bbox_json) else None
    return {
        "fact_id": fact.id,
        "entity_raw": fact.entity_raw,
        "metric_raw": fact.metric_raw,
        "value_raw": fact.value_raw,
        "unit_raw": fact.unit_raw,
        "period_raw": fact.period_raw,
        "document_id": fact.document_id,
        "extraction_method": fact.extraction_method,
        "evidence": {
            "block_id": block.id if block else None,
            "pdf_page_index": block.pdf_page_index if block else None,
            "printed_page_label": block.printed_page_label if block else None,
            "block_kind": block.block_kind if block else None,
            "text": (block.text[:800] if block else None),
            "bbox": bbox,
            "table_context": tc,
        } if block else None,
    }


@router.get("")
def list_relationships(
    verdict: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    rels, total = repositories.list_relationships(db, verdict=verdict, page=page, limit=limit)
    items = []
    for r in rels:
        lf = repositories.get_fact(db, r.left_fact_id)
        rf = repositories.get_fact(db, r.right_fact_id)
        items.append({
            "relationship_id": r.id,
            "verdict": r.verdict,
            "reason_code": r.reason_code,
            "explanation": r.explanation,
            "confidence": r.confidence,
            "review_state": r.review_state,
            "comparison": json.loads(r.comparison_json),
            "left_fact": _format_fact_with_evidence(lf, db),
            "right_fact": _format_fact_with_evidence(rf, db),
        })
    return {"total": total, "page": page, "limit": limit, "items": items}


@router.post("/{relationship_id}/review")
def review_relationship(
    relationship_id: str,
    review_state: str = Body(..., embed=True),
    note: str | None = Body(None, embed=True),
    db: Session = Depends(get_db),
):
    """Mark a relationship as human_verified or rejected. No auth — demo only."""
    allowed = {"human_verified", "rejected", "automatic"}
    if review_state not in allowed:
        raise HTTPException(status_code=400, detail=f"review_state must be one of {allowed}")

    rel = repositories.update_relationship_review(db, relationship_id, review_state, note)
    if not rel:
        raise HTTPException(status_code=404, detail="Relationship not found")
    return {"relationship_id": relationship_id, "review_state": rel.review_state}


@router.get("/rejected-candidates")
def list_rejected_candidates(
    document_id: str | None = Query(None),
    limit: int = Query(50),
    db: Session = Depends(get_db),
):
    """Return visible rejected candidates — demo case #4."""
    rows = repositories.list_rejected_candidates(db, document_id=document_id, limit=limit)
    result = []
    for r in rows:
        block = repositories.get_block(db, r.evidence_block_id) if r.evidence_block_id else None
        result.append({
            "id": r.id,
            "document_id": r.document_id,
            "entity_raw": r.entity_raw,
            "metric_raw": r.metric_raw,
            "value_raw": r.value_raw,
            "rejection_reason": r.rejection_reason,
            "extraction_method": r.extraction_method,
            "created_at": r.created_at,
            "source_text": block.text[:400] if block else None,
            "pdf_page_index": block.pdf_page_index if block else None,
            "block_kind": block.block_kind if block else None,
        })
    return result
