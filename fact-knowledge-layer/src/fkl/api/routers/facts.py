"""Facts API router."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from fkl.api.deps import get_db
from fkl.persistence import repositories

router = APIRouter(prefix="/api/facts", tags=["facts"])


def _format_fact(f, block=None) -> dict:
    prov = json.loads(f.normalisation_provenance_json or "[]")
    scope = json.loads(f.scope_json or "{}")
    result = {
        "fact_id": f.id,
        "document_id": f.document_id,
        "entity_raw": f.entity_raw,
        "entity_canonical": f.entity_canonical,
        "metric_raw": f.metric_raw,
        "metric_key": f.metric_key,
        "value_raw": f.value_raw,
        "numeric_value": f.numeric_value,
        "value_kind": f.value_kind,
        "unit_raw": f.unit_raw,
        "unit_dimension": f.unit_dimension,
        "scale_raw": f.scale_raw,
        "normalised_value": f.normalised_value,
        "normalised_unit": f.normalised_unit,
        "period_raw": f.period_raw,
        "period_start": f.period_start,
        "period_end": f.period_end,
        "role_status": scope.get("role_status"),
        "scope": scope,
        "extraction_method": f.extraction_method,
        "confidence": f.confidence,
        "review_state": f.review_state,
        "normalisation_provenance": prov,
        "created_at": f.created_at,
    }
    if block:
        tc = json.loads(block.table_context_json) if block.table_context_json else None
        bbox = json.loads(block.bbox_json) if block.bbox_json else None
        result["evidence"] = {
            "block_id": block.id,
            "pdf_page_index": block.pdf_page_index,
            "printed_page_label": block.printed_page_label,
            "block_kind": block.block_kind,
            "text": block.text[:500],
            "bbox": bbox,
            "table_context": tc,
        }
    return result


@router.get("")
def list_facts(
    document_id: str | None = Query(None),
    entity: str | None = Query(None),
    metric: str | None = Query(None),
    review_state: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    facts, total = repositories.list_facts(
        db, document_id=document_id, entity=entity,
        metric=metric, review_state=review_state, page=page, limit=limit
    )
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "items": [_format_fact(f) for f in facts],
    }


@router.get("/{fact_id}")
def get_fact(fact_id: str, db: Session = Depends(get_db)):
    fact = repositories.get_fact(db, fact_id)
    if not fact:
        raise HTTPException(status_code=404, detail="Fact not found")
    block = repositories.get_block(db, fact.evidence_block_id)
    return _format_fact(fact, block)


@router.get("/{fact_id}/relationships")
def get_fact_relationships(fact_id: str, db: Session = Depends(get_db)):
    fact = repositories.get_fact(db, fact_id)
    if not fact:
        raise HTTPException(status_code=404, detail="Fact not found")

    rels = repositories.get_relationships_for_fact(db, fact_id)
    result = []
    for r in rels:
        other_id = r.right_fact_id if r.left_fact_id == fact_id else r.left_fact_id
        left_fact = repositories.get_fact(db, r.left_fact_id)
        right_fact = repositories.get_fact(db, r.right_fact_id)
        left_block = repositories.get_block(db, left_fact.evidence_block_id) if left_fact else None
        right_block = repositories.get_block(db, right_fact.evidence_block_id) if right_fact else None

        result.append({
            "relationship_id": r.id,
            "verdict": r.verdict,
            "reason_code": r.reason_code,
            "explanation": r.explanation,
            "confidence": r.confidence,
            "review_state": r.review_state,
            "comparison": json.loads(r.comparison_json),
            "left_fact": _format_fact(left_fact, left_block) if left_fact else None,
            "right_fact": _format_fact(right_fact, right_block) if right_fact else None,
        })
    return result
