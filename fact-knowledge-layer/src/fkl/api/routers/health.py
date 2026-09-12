"""Health check router."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from fkl.api.deps import get_db
from fkl.persistence.orm import DocumentORM, FactORM, RelationshipORM

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    return {"status": "ok", "service": "fact-knowledge-layer"}


@router.get("/api/stats")
def global_stats(db: Session = Depends(get_db)):
    """Global aggregate counts for landing page summary strip."""
    from sqlalchemy import func
    total_docs = db.query(DocumentORM).count()
    total_facts = db.query(FactORM).filter(FactORM.review_state == "accepted").count()
    verdict_counts = (
        db.query(RelationshipORM.verdict, func.count(RelationshipORM.id).label("n"))
        .group_by(RelationshipORM.verdict)
        .all()
    )
    total_rels = db.query(RelationshipORM).count()
    return {
        "total_documents": total_docs,
        "total_facts": total_facts,
        "total_relationships": total_rels,
        "verdicts": {row.verdict: row.n for row in verdict_counts},
    }
