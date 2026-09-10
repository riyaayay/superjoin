"""Relationship builder — deterministic blocking + decision table.

Uses SQL-level blocking (not ANN/FAISS). Only new facts are compared against
accepted facts from other documents. Old-old pairs are never recomputed.
"""

from __future__ import annotations

import logging
from typing import Any
import uuid
from datetime import datetime, timezone

from fkl.domain.classification import build_explanation, classify, decide
from fkl.domain.enums import RelationshipReviewState, UnitDimension
from fkl.domain.models import ExtractionStats, Fact, Relationship
from fkl.persistence.orm import FactORM

logger = logging.getLogger(__name__)


def _orm_to_fact(row: FactORM) -> Fact:
    """Convert ORM row back to domain Fact for classification."""
    import json
    from fkl.domain.enums import ExtractionMethod, ReviewState, ValueKind
    from fkl.domain.models import NormalisationStep

    scope_data = json.loads(row.scope_json or "{}")
    role_status = scope_data.get("role_status")

    return Fact(
        id=row.id,
        document_id=row.document_id,
        ingestion_run_id=row.ingestion_run_id,
        evidence_block_id=row.evidence_block_id,
        entity_raw=row.entity_raw,
        entity_canonical=row.entity_canonical or row.entity_raw,
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
        role_status=role_status,
        scope=scope_data,
        qualifiers=json.loads(row.qualifiers_json or "{}"),
        extraction_method=ExtractionMethod(row.extraction_method),
        confidence=row.confidence,
        review_state=ReviewState(row.review_state),
        normalisation_provenance=[
            NormalisationStep(**s) for s in json.loads(row.normalisation_provenance_json or "[]")
        ],
        created_at=datetime.fromisoformat(row.created_at),
    )


_STOP_WORDS = frozenset({"the", "a", "an", "of", "in", "at", "by", "for", "to", "from", "and", "or", "on", "as", "is"})
ENTITY_BLOCKING_THRESHOLD = 0.25
# Metric blocking is intentionally disabled: zero-overlap synonyms (Revenue vs Turnover)
# must reach classify() so the LLM gray-zone path can fire. Only entity overlap is gated.


def _tokenize(text: str) -> frozenset[str]:
    import re
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return frozenset(t for t in tokens if t not in _STOP_WORDS and len(t) > 2)


def _blocking_keys(fact: Fact) -> tuple[frozenset[str], frozenset[str]]:
    """Return separate entity and metric token sets for independent blocking."""
    ent_text = fact.entity_canonical or fact.entity_raw
    met_text = fact.metric_key or fact.metric_raw
    return _tokenize(ent_text), _tokenize(met_text)


def _blocking_key(fact: Fact) -> frozenset[str]:
    """Compatibility helper for legacy code and unit tests."""
    ent_tokens, met_tokens = _blocking_keys(fact)
    return ent_tokens | met_tokens


def _passes_blocking(
    left: tuple[frozenset[str], frozenset[str]] | Fact | FactORM,
    right: tuple[frozenset[str], frozenset[str]] | Fact | FactORM,
) -> bool:
    """A pair passes blocking if entity overlap meets threshold.

    Metric blocking is intentionally absent: synonym pairs like 'Revenue' vs 'Turnover'
    have zero Jaccard overlap but are semantically equivalent. The LLM gray-zone path
    inside classify() handles this disambiguation — but only if the pair passes blocking
    first. Gating on metric Jaccard would suppress exactly the pairs that need LLM help.
    """
    l_ent, _l_met = left if isinstance(left, tuple) else _blocking_keys(left)
    r_ent, _r_met = right if isinstance(right, tuple) else _blocking_keys(right)

    ent_union = l_ent | r_ent
    if not ent_union:
        return False
    ent_jaccard = len(l_ent & r_ent) / len(ent_union)
    return ent_jaccard >= ENTITY_BLOCKING_THRESHOLD


class _CallCappedProvider:
    """Wraps provider to strictly enforce a maximum number of LLM invocations per run."""
    def __init__(self, inner: Any, max_calls: int = 5):
        self._inner = inner
        self._max_calls = max_calls
        self.calls = 0

    def canonicalise_metric(self, left: Fact, right: Fact) -> dict:
        if self.calls >= self._max_calls:
            return {"same": False, "canonical": left.metric_raw, "similarity": 0.0}
        self.calls += 1
        return self._inner.canonicalise_metric(left=left, right=right)

    def __getattr__(self, name: str):
        return getattr(self._inner, name)


def build_relationships(
    new_facts: list[Fact],
    existing_fact_rows: list[FactORM],
    run_id: str,
    metric_provider: Any = None,
    insufficient_context_counter: list[int] | None = None,
    stats: ExtractionStats | None = None,
) -> list[Relationship]:
    """
    Compare each new_fact against existing accepted facts from other documents.

    Incremental: only pairs touching a new fact are evaluated.
    Old-old pairs are never recomputed.
    Pairs failing blocking or resolving to INSUFFICIENT_CONTEXT are not persisted.
    """
    relationships: list[Relationship] = []
    seen_pairs: set[tuple[str, str]] = set()

    existing_facts = [_orm_to_fact(row) for row in existing_fact_rows]
    existing_keys = [(f, _blocking_keys(f)) for f in existing_facts]

    provider_to_pass = (
        _CallCappedProvider(metric_provider, max_calls=5)
        if metric_provider is not None and hasattr(metric_provider, "canonicalise_metric")
        else metric_provider
    )

    for new_fact in new_facts:
        new_keys = _blocking_keys(new_fact)

        for existing_fact, ex_keys in existing_keys:
            # Must be from a different document
            if existing_fact.document_id == new_fact.document_id:
                continue

            # Incompatible dimensions cannot match
            if (
                new_fact.unit_dimension
                and existing_fact.unit_dimension
                and new_fact.unit_dimension != UnitDimension.UNKNOWN
                and existing_fact.unit_dimension != UnitDimension.UNKNOWN
                and new_fact.unit_dimension != existing_fact.unit_dimension
            ):
                continue

            # Incompatible value kinds cannot match
            if new_fact.value_kind and existing_fact.value_kind and new_fact.value_kind != existing_fact.value_kind:
                continue

            # Independent 2D blocking (entity AND metric dimensions)
            if not _passes_blocking(new_keys, ex_keys):
                continue

            # Canonical pair ordering to avoid duplicates
            pair = (min(new_fact.id, existing_fact.id), max(new_fact.id, existing_fact.id))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            if stats is not None:
                stats.relationship_pairs_total += 1

            # Classify
            left = new_fact
            right = existing_fact
            cmp = classify(left, right, metric_provider=provider_to_pass)
            verdict, reason = decide(cmp)

            # Transparency: do not let INSUFFICIENT_CONTEXT dominate /api/relationships
            from fkl.domain.enums import Verdict
            if verdict == Verdict.INSUFFICIENT_CONTEXT:
                if stats is not None:
                    stats.relationship_pairs_insufficient_context += 1
                if insufficient_context_counter is not None:
                    insufficient_context_counter[0] += 1
                continue

            if stats is not None:
                if cmp.match_method == "llm_fallback":
                    stats.relationship_pairs_llm_fallback_matched += 1
                elif cmp.match_method == "jaccard":
                    stats.relationship_pairs_jaccard_matched += 1

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
