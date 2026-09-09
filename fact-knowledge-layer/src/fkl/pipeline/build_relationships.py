"""Relationship builder — deterministic blocking + decision table.

Uses SQL-level blocking (not ANN/FAISS). Only new facts are compared against
accepted facts from other documents. Old-old pairs are never recomputed.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fkl.domain.classification import build_explanation, classify, decide
from fkl.domain.enums import RelationshipReviewState, UnitDimension
from fkl.domain.models import Fact, Relationship
from fkl.persistence.orm import FactORM

logger = logging.getLogger(__name__)


def _orm_to_fact(row: FactORM) -> Fact:
    """Convert ORM row back to domain Fact for classification."""
    import json
    from fkl.domain.enums import ExtractionMethod, ReviewState, ValueKind
    from fkl.domain.models import NormalisationStep

    return Fact(
        id=row.id,
        document_id=row.document_id,
        ingestion_run_id=row.ingestion_run_id,
        evidence_block_id=row.evidence_block_id,
        entity_raw=row.entity_raw,
        metric_raw=row.metric_raw,
        metric_key=row.metric_key,
        value_raw=row.value_raw,
        numeric_value=row.numeric_value,
        value_kind=ValueKind(row.value_kind),
        unit_raw=row.unit_raw,
        unit_dimension=UnitDimension(row.unit_dimension),
        scale_raw=row.scale_raw,
        normalised_value=row.normalised_value,
        normalised_unit=row.normalised_unit,
        period_raw=row.period_raw,
        period_start=row.period_start,
        period_end=row.period_end,
        scope=json.loads(row.scope_json or "{}"),
        qualifiers=json.loads(row.qualifiers_json or "{}"),
        extraction_method=ExtractionMethod(row.extraction_method),
        confidence=row.confidence,
        review_state=ReviewState(row.review_state),
        normalisation_provenance=[
            NormalisationStep(**s) for s in json.loads(row.normalisation_provenance_json or "[]")
        ],
        created_at=datetime.fromisoformat(row.created_at),
    )


def _blocking_key(fact: Fact) -> frozenset[str]:
    """
    Deterministic blocking key from entity + metric tokens.
    Two facts share a key-overlap if they might be about the same measurement.
    """
    import re
    tokens = re.findall(r"[a-z0-9]+", (fact.entity_raw + " " + fact.metric_raw).lower())
    stop = {"the", "a", "an", "of", "in", "at", "by", "for", "to", "from", "and", "or", "on"}
    meaningful = frozenset(t for t in tokens if t not in stop and len(t) > 2)
    return meaningful


def _keys_overlap(a: frozenset[str], b: frozenset[str]) -> bool:
    return bool(a & b)


def build_relationships(
    new_facts: list[Fact],
    existing_fact_rows: list[FactORM],
    run_id: str,
) -> list[Relationship]:
    """
    Compare each new_fact against existing accepted facts from other documents.

    Incremental: only pairs touching a new fact are evaluated.
    Old-old pairs are never recomputed.
    """
    relationships: list[Relationship] = []
    seen_pairs: set[tuple[str, str]] = set()

    existing_facts = [_orm_to_fact(row) for row in existing_fact_rows]

    for new_fact in new_facts:
        new_key = _blocking_key(new_fact)

        for existing_fact in existing_facts:
            # Must be from a different document
            if existing_fact.document_id == new_fact.document_id:
                continue

            # Blocking: must share at least one meaningful token
            ex_key = _blocking_key(existing_fact)
            if not _keys_overlap(new_key, ex_key):
                continue

            # Canonical pair ordering to avoid duplicates
            pair = (min(new_fact.id, existing_fact.id), max(new_fact.id, existing_fact.id))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            # Classify
            left = new_fact
            right = existing_fact
            cmp = classify(left, right)
            verdict, reason = decide(cmp)
            explanation = build_explanation(cmp, verdict, reason)

            rel = Relationship(
                id=f"rel_{uuid.uuid4().hex[:12]}",
                left_fact_id=pair[0],
                right_fact_id=pair[1],
                reason_code=reason,
                verdict=verdict,
                explanation=explanation,
                comparison=cmp,
                confidence=(cmp.evidence_quality_left + cmp.evidence_quality_right) / 2,
                review_state=RelationshipReviewState.AUTOMATIC,
                created_by_run_id=run_id,
            )
            relationships.append(rel)

    logger.info(
        "build_relationships: %d new facts × %d existing → %d relationships",
        len(new_facts), len(existing_facts), len(relationships),
    )
    return relationships
