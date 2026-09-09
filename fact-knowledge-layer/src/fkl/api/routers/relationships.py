"""Relationships API router."""

from __future__ import annotations

import json

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from fkl.api.deps import get_db
from fkl.persistence import repositories

router = APIRouter(prefix="/api/relationships", tags=["relationships"])


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
            "left_fact": {
                "fact_id": lf.id if lf else None,
                "entity_raw": lf.entity_raw if lf else None,
                "metric_raw": lf.metric_raw if lf else None,
                "value_raw": lf.value_raw if lf else None,
                "period_raw": lf.period_raw if lf else None,
                "document_id": lf.document_id if lf else None,
            },
            "right_fact": {
                "fact_id": rf.id if rf else None,
                "entity_raw": rf.entity_raw if rf else None,
                "metric_raw": rf.metric_raw if rf else None,
                "value_raw": rf.value_raw if rf else None,
                "period_raw": rf.period_raw if rf else None,
                "document_id": rf.document_id if rf else None,
            },
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
    return [
        {
            "id": r.id,
            "document_id": r.document_id,
            "entity_raw": r.entity_raw,
            "metric_raw": r.metric_raw,
            "value_raw": r.value_raw,
            "rejection_reason": r.rejection_reason,
            "extraction_method": r.extraction_method,
            "created_at": r.created_at,
        }
        for r in rows
    ]
