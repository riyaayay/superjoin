"""Repository layer — all database access goes through here."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from fkl.domain.models import Fact, Relationship, SourceBlock
from fkl.persistence.orm import (
    CandidateAuditORM,
    DocumentORM,
    FactORM,
    IngestionRunORM,
    RelationshipORM,
    SourceBlockORM,
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


def get_document(db: Session, document_id: str) -> DocumentORM | None:
    return db.get(DocumentORM, document_id)


def get_document_by_sha(db: Session, sha256: str) -> DocumentORM | None:
    return db.query(DocumentORM).filter(DocumentORM.sha256 == sha256).first()


def create_document(db: Session, **kwargs) -> DocumentORM:
    doc = DocumentORM(**kwargs, created_at=_utcnow())
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def update_document_status(
    db: Session,
    document_id: str,
    status: str,
    page_count: int | None = None,
    error_message: str | None = None,
) -> None:
    doc = db.get(DocumentORM, document_id)
    if doc:
        doc.status = status
        if page_count is not None:
            doc.page_count = page_count
        if error_message is not None:
            doc.error_message = error_message
        elif status == "complete":
            doc.error_message = None
        if status in ("complete", "failed"):
            doc.completed_at = _utcnow()
        db.commit()


def list_documents(db: Session) -> list[DocumentORM]:
    return db.query(DocumentORM).order_by(DocumentORM.created_at.desc()).all()


# ---------------------------------------------------------------------------
# Ingestion runs
# ---------------------------------------------------------------------------


def create_run(
    db: Session, run_id: str, document_id: str, pipeline_version: str, model_name: str | None
) -> IngestionRunORM:
    run = IngestionRunORM(
        id=run_id,
        document_id=document_id,
        pipeline_version=pipeline_version,
        parser_version="pymupdf-1.24",
        model_name=model_name,
        started_at=_utcnow(),
    )
    db.add(run)
    db.commit()
    return run


def complete_run(
    db: Session,
    run_id: str,
    facts_created: int,
    facts_rejected: int,
    relationships_created: int,
) -> None:
    run = db.get(IngestionRunORM, run_id)
    if run:
        run.finished_at = _utcnow()
        run.facts_created = facts_created
        run.facts_rejected = facts_rejected
        run.relationships_created = relationships_created
        db.commit()


# ---------------------------------------------------------------------------
# Source blocks
# ---------------------------------------------------------------------------


def insert_blocks(db: Session, blocks: list[SourceBlock]) -> None:
    for b in blocks:
        row = SourceBlockORM(
            id=b.id,
            document_id=b.document_id,
            pdf_page_index=b.pdf_page_index,
            printed_page_label=b.printed_page_label,
            block_kind=b.block_kind.value,
            bbox_json=json.dumps(b.bbox.model_dump()) if b.bbox else None,
            text=b.text,
            text_normalised=b.text_normalised,
            table_context_json=json.dumps(b.table_context.model_dump()) if b.table_context else None,
            content_hash=b.content_hash,
        )
        db.merge(row)
    db.commit()


def get_block(db: Session, block_id: str) -> SourceBlockORM | None:
    return db.get(SourceBlockORM, block_id)


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------


def insert_facts(db: Session, facts: list[Fact]) -> None:
    for f in facts:
        row = FactORM(
            id=f.id,
            document_id=f.document_id,
            ingestion_run_id=f.ingestion_run_id,
            evidence_block_id=f.evidence_block_id,
            entity_raw=f.entity_raw,
            metric_raw=f.metric_raw,
            metric_key=f.metric_key,
            value_raw=f.value_raw,
            numeric_value=f.numeric_value,
            value_kind=f.value_kind.value,
            unit_raw=f.unit_raw,
            unit_dimension=f.unit_dimension.value,
            scale_raw=f.scale_raw,
            normalised_value=f.normalised_value,
            normalised_unit=f.normalised_unit,
            period_raw=f.period_raw,
            period_start=f.period_start,
            period_end=f.period_end,
            scope_json=json.dumps(f.scope),
            qualifiers_json=json.dumps(f.qualifiers),
            extraction_method=f.extraction_method.value,
            confidence=f.confidence,
            review_state=f.review_state.value,
            normalisation_provenance_json=json.dumps(
                [s.model_dump() for s in f.normalisation_provenance]
            ),
            created_at=f.created_at.isoformat(),
        )
        db.add(row)
    db.commit()


def get_facts_for_document(db: Session, document_id: str) -> list[FactORM]:
    return db.query(FactORM).filter(FactORM.document_id == document_id).all()


def get_facts_excluding_document(db: Session, document_id: str) -> list[FactORM]:
    """Get accepted facts from all OTHER documents — for incremental comparison."""
    return (
        db.query(FactORM)
        .filter(FactORM.document_id != document_id, FactORM.review_state == "accepted")
        .all()
    )


def list_facts(
    db: Session,
    document_id: str | None = None,
    entity: str | None = None,
    metric: str | None = None,
    review_state: str | None = None,
    page: int = 1,
    limit: int = 50,
) -> tuple[list[FactORM], int]:
    q = db.query(FactORM)
    if document_id:
        q = q.filter(FactORM.document_id == document_id)
    if entity:
        q = q.filter(FactORM.entity_raw.ilike(f"%{entity}%"))
    if metric:
        q = q.filter(FactORM.metric_raw.ilike(f"%{metric}%"))
    if review_state:
        q = q.filter(FactORM.review_state == review_state)
    total = q.count()
    items = q.order_by(FactORM.created_at.desc()).offset((page - 1) * limit).limit(limit).all()
    return items, total


def get_fact(db: Session, fact_id: str) -> FactORM | None:
    return db.get(FactORM, fact_id)


# ---------------------------------------------------------------------------
# Relationships
# ---------------------------------------------------------------------------


def insert_relationships(db: Session, rels: list[Relationship]) -> None:
    for r in rels:
        # Canonical ordering: smaller id is always left
        left_id = min(r.left_fact_id, r.right_fact_id)
        right_id = max(r.left_fact_id, r.right_fact_id)
        row = RelationshipORM(
            id=r.id,
            left_fact_id=left_id,
            right_fact_id=right_id,
            reason_code=r.reason_code.value,
            verdict=r.verdict.value,
            explanation=r.explanation,
            comparison_json=json.dumps(r.comparison.model_dump()),
            confidence=r.confidence,
            review_state=r.review_state.value,
            created_by_run_id=r.created_by_run_id,
            created_at=r.created_at.isoformat(),
        )
        db.merge(row)
    db.commit()


def get_relationships_for_fact(db: Session, fact_id: str) -> list[RelationshipORM]:
    return (
        db.query(RelationshipORM)
        .filter(
            (RelationshipORM.left_fact_id == fact_id) | (RelationshipORM.right_fact_id == fact_id)
        )
        .all()
    )


def list_relationships(
    db: Session,
    verdict: str | None = None,
    page: int = 1,
    limit: int = 50,
) -> tuple[list[RelationshipORM], int]:
    q = db.query(RelationshipORM)
    if verdict:
        q = q.filter(RelationshipORM.verdict == verdict)
    total = q.count()
    items = q.order_by(RelationshipORM.created_at.desc()).offset((page - 1) * limit).limit(limit).all()
    return items, total


def update_relationship_review(
    db: Session, relationship_id: str, review_state: str, note: str | None = None
) -> RelationshipORM | None:
    rel = db.get(RelationshipORM, relationship_id)
    if rel:
        rel.review_state = review_state
        db.commit()
    return rel


# ---------------------------------------------------------------------------
# Candidate audit (rejected candidates)
# ---------------------------------------------------------------------------


def insert_candidate_audit(db: Session, records: list[dict]) -> None:
    for rec in records:
        row = CandidateAuditORM(**rec)
        db.add(row)
    db.commit()


def list_rejected_candidates(
    db: Session, document_id: str | None = None, limit: int = 100
) -> list[CandidateAuditORM]:
    q = db.query(CandidateAuditORM)
    if document_id:
        q = q.filter(CandidateAuditORM.document_id == document_id)
    return q.order_by(CandidateAuditORM.created_at.desc()).limit(limit).all()


def get_document_stats(db: Session, document_id: str) -> dict:
    facts_total = db.query(FactORM).filter(FactORM.document_id == document_id).count()
    facts_accepted = (
        db.query(FactORM)
        .filter(FactORM.document_id == document_id, FactORM.review_state == "accepted")
        .count()
    )
    facts_rejected = (
        db.query(CandidateAuditORM)
        .filter(CandidateAuditORM.document_id == document_id)
        .count()
    )
    # Relationships involving this document's facts
    doc_fact_ids = [
        f.id
        for f in db.query(FactORM.id).filter(FactORM.document_id == document_id)
    ]
    rel_count = 0
    if doc_fact_ids:
        rel_count = (
            db.query(RelationshipORM)
            .filter(
                (RelationshipORM.left_fact_id.in_(doc_fact_ids))
                | (RelationshipORM.right_fact_id.in_(doc_fact_ids))
            )
            .count()
        )
    return {
        "facts_total": facts_total,
        "facts_accepted": facts_accepted,
        "facts_rejected_candidates": facts_rejected,
        "relationships": rel_count,
    }
