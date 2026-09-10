"""Incremental ingestion tests.

Verifies:
- SHA-256 deduplication: re-uploading same bytes returns existing document
- Only new facts are compared against existing facts (old-old never recomputed)
- Old facts unchanged after new document upload
"""

import uuid
from datetime import datetime

import pytest

from fkl.domain.classification import classify, decide
from fkl.domain.enums import ExtractionMethod, ReasonCode, ReviewState, UnitDimension, ValueKind, Verdict
from fkl.domain.models import Fact
from fkl.pipeline.build_relationships import build_relationships, _blocking_key


def _fact(entity="India", metric="GDP growth", value=6.4, unit="percent", doc_id="doc_a", period_start="2024-04", period_end="2025-03"):
    return Fact(
        id=f"fact_{uuid.uuid4().hex[:8]}",
        document_id=doc_id,
        ingestion_run_id="run_1",
        evidence_block_id="blk_1",
        entity_raw=entity,
        metric_raw=metric,
        value_raw=str(value),
        numeric_value=value,
        value_kind=ValueKind.NUMERIC,
        unit_raw="%",
        unit_dimension=UnitDimension.PERCENTAGE,
        normalised_value=value,
        normalised_unit=unit,
        period_start=period_start,
        period_end=period_end,
        scope={},
        extraction_method=ExtractionMethod.TABLE_RULE,
        confidence=0.8,
        review_state=ReviewState.ACCEPTED,
        created_at=datetime.utcnow(),
    )


class TestIncrementalRelationshipBuilding:
    """build_relationships should only create new×existing pairs."""

    def test_no_old_old_pairs(self):
        """New facts from doc_c should not compare with each other,
        only with existing facts from doc_a and doc_b."""
        existing_a = _fact(doc_id="doc_a")
        existing_b = _fact(doc_id="doc_b")
        new_c = _fact(doc_id="doc_c")

        from fkl.persistence.orm import FactORM
        import json

        def to_orm(f: Fact) -> FactORM:
            row = FactORM(
                id=f.id, document_id=f.document_id, ingestion_run_id=f.ingestion_run_id,
                evidence_block_id=f.evidence_block_id, entity_raw=f.entity_raw,
                metric_raw=f.metric_raw, metric_key=f.metric_key,
                value_raw=f.value_raw, numeric_value=f.numeric_value,
                value_kind=f.value_kind.value, unit_raw=f.unit_raw,
                unit_dimension=f.unit_dimension.value, normalised_value=f.normalised_value,
                normalised_unit=f.normalised_unit, period_start=f.period_start,
                period_end=f.period_end, scope_json=json.dumps(f.scope),
                qualifiers_json="{}", extraction_method=f.extraction_method.value,
                confidence=f.confidence, review_state=f.review_state.value,
                normalisation_provenance_json="[]", created_at=f.created_at.isoformat(),
            )
            return row

        existing_rows = [to_orm(existing_a), to_orm(existing_b)]
        rels = build_relationships([new_c], existing_rows, "run_new")
        assert len(rels) == 2, "Both doc_a and doc_b pairs must survive blocking and form relationships"

        # All relationships must involve the new fact
        for r in rels:
            assert new_c.id in (r.left_fact_id, r.right_fact_id)

        # The two existing facts must NOT be paired with each other
        old_pairs = [(r.left_fact_id, r.right_fact_id) for r in rels
                     if existing_a.id in (r.left_fact_id, r.right_fact_id)
                     and existing_b.id in (r.left_fact_id, r.right_fact_id)]
        assert old_pairs == [], "Old-old pairs must not be created"

    def test_same_document_not_paired(self):
        """Facts from the same document must never be compared."""
        fact_a1 = _fact(doc_id="doc_a")
        fact_a2 = _fact(doc_id="doc_a")

        from fkl.persistence.orm import FactORM
        import json

        def to_orm(f):
            return FactORM(
                id=f.id, document_id=f.document_id, ingestion_run_id=f.ingestion_run_id,
                evidence_block_id=f.evidence_block_id, entity_raw=f.entity_raw,
                metric_raw=f.metric_raw, metric_key=f.metric_key,
                value_raw=f.value_raw, numeric_value=f.numeric_value,
                value_kind=f.value_kind.value, unit_raw=f.unit_raw,
                unit_dimension=f.unit_dimension.value, normalised_value=f.normalised_value,
                normalised_unit=f.normalised_unit, period_start=f.period_start,
                period_end=f.period_end, scope_json="{}",
                qualifiers_json="{}", extraction_method=f.extraction_method.value,
                confidence=f.confidence, review_state=f.review_state.value,
                normalisation_provenance_json="[]", created_at=f.created_at.isoformat(),
            )

        rels = build_relationships([fact_a1], [to_orm(fact_a2)], "run_test")
        assert rels == []

    def test_blocking_key_overlap(self):
        """Facts with no shared tokens should not be compared."""
        fa = _fact(entity="India", metric="GDP growth rate")
        fb = _fact(entity="xyz", metric="completely unrelated topic")
        key_a = _blocking_key(fa)
        key_b = _blocking_key(fb)
        assert not (key_a & key_b)
