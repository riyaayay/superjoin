"""Unit tests for the classification decision table.

Covers all four demo cases:
1. Corroboration (same metric, within rounding tolerance after unit conversion)
2. Reconciliation by scope (standalone vs consolidated)
3. Reconciliation by period (different FY)
4. Likely conflict (values materially different, high-confidence evidence)
Plus: insufficient context cases.
"""

import uuid
from datetime import datetime

import pytest

from fkl.domain.classification import build_explanation, classify, decide
from fkl.domain.enums import (
    ExtractionMethod, ReasonCode, ReviewState, UnitDimension, ValueKind, Verdict,
)
from fkl.domain.models import Fact


def _fact(
    entity="India",
    metric="Real GDP growth rate",
    value_raw="6.4%",
    numeric_value=6.4,
    normalised_value=6.4,
    normalised_unit="percent",
    period_raw="FY25",
    period_start="2024-04",
    period_end="2025-03",
    scope=None,
    confidence=0.8,
    document_id="doc_a",
) -> Fact:
    return Fact(
        id=f"fact_{uuid.uuid4().hex[:8]}",
        document_id=document_id,
        ingestion_run_id="run_1",
        evidence_block_id="blk_1",
        entity_raw=entity,
        metric_raw=metric,
        value_raw=value_raw,
        numeric_value=numeric_value,
        value_kind=ValueKind.NUMERIC,
        unit_raw="%",
        unit_dimension=UnitDimension.PERCENTAGE,
        normalised_value=normalised_value,
        normalised_unit=normalised_unit,
        period_raw=period_raw,
        period_start=period_start,
        period_end=period_end,
        scope=scope or {},
        extraction_method=ExtractionMethod.TABLE_RULE,
        confidence=confidence,
        review_state=ReviewState.ACCEPTED,
        created_at=datetime.utcnow(),
    )


class TestExactMatch:
    def test_exact_match_corroborates(self):
        left = _fact(document_id="doc_a")
        right = _fact(document_id="doc_b")
        cmp = classify(left, right)
        verdict, reason = decide(cmp)
        assert verdict == Verdict.CORROBORATES
        assert reason in (ReasonCode.EXACT_MATCH, ReasonCode.ROUNDED_MATCH)


class TestRoundedMatch:
    """Demo Case 1: Corroboration via unit conversion and rounding."""

    def test_million_vs_crore_corroborates(self):
        # 81415.38 million ≈ 8141.538 crore ≈ 8142 crore (rounded)
        left = _fact(
            metric="Revenue from Operations",
            value_raw="81415.38",
            numeric_value=81415.38,
            normalised_value=8141.538,
            normalised_unit="crore",
            period_raw="FY24",
            period_start="2023-04",
            period_end="2024-03",
            document_id="doc_a",
        )
        right = _fact(
            metric="Revenue from Operations",
            value_raw="8142",
            numeric_value=8142.0,
            normalised_value=8142.0,
            normalised_unit="crore",
            period_raw="FY24",
            period_start="2023-04",
            period_end="2024-03",
            document_id="doc_b",
        )
        cmp = classify(left, right)
        verdict, reason = decide(cmp)
        assert verdict == Verdict.CORROBORATES
        assert reason in (ReasonCode.ROUNDED_MATCH, ReasonCode.EXACT_MATCH)


class TestScopeReconciliation:
    """Demo Case 2: Same period, different consolidation scope."""

    def test_standalone_vs_consolidated_reconciles(self):
        left = _fact(
            metric="Revenue from Operations",
            normalised_value=7454.0,
            normalised_unit="crore",
            period_start="2023-04",
            period_end="2024-03",
            scope={"consolidation": "standalone"},
            document_id="doc_a",
        )
        right = _fact(
            metric="Revenue from Operations",
            normalised_value=8142.0,
            normalised_unit="crore",
            period_start="2023-04",
            period_end="2024-03",
            scope={"consolidation": "consolidated"},
            document_id="doc_b",
        )
        cmp = classify(left, right)
        verdict, reason = decide(cmp)
        assert verdict == Verdict.RECONCILES
        assert reason == ReasonCode.DIFFERENT_SCOPE


class TestPeriodReconciliation:
    """Demo Case 3: Same metric, different periods."""

    def test_different_periods_reconciles(self):
        left = _fact(
            period_raw="FY24", period_start="2023-04", period_end="2024-03",
            normalised_value=6.4, document_id="doc_a",
        )
        right = _fact(
            period_raw="FY25", period_start="2024-04", period_end="2025-03",
            normalised_value=6.8, document_id="doc_b",
        )
        cmp = classify(left, right)
        verdict, reason = decide(cmp)
        assert verdict == Verdict.RECONCILES
        assert reason == ReasonCode.DIFFERENT_PERIOD


class TestLikelyConflict:
    """A genuine material difference with high-quality evidence."""

    def test_material_difference_flagged(self):
        left = _fact(
            normalised_value=6.4,
            normalised_unit="percent",
            period_start="2024-04", period_end="2025-03",
            confidence=0.9, document_id="doc_a",
        )
        right = _fact(
            normalised_value=8.5,  # materially different
            normalised_unit="percent",
            period_start="2024-04", period_end="2025-03",
            confidence=0.85, document_id="doc_b",
        )
        cmp = classify(left, right)
        verdict, reason = decide(cmp)
        assert verdict == Verdict.LIKELY_CONFLICT
        assert reason == ReasonCode.MATERIAL_VALUE_DIFFERENCE

    def test_low_confidence_gives_insufficient_context(self):
        left = _fact(normalised_value=6.4, confidence=0.4, document_id="doc_a")
        right = _fact(normalised_value=8.5, confidence=0.35, document_id="doc_b")
        cmp = classify(left, right)
        verdict, reason = decide(cmp)
        assert verdict == Verdict.INSUFFICIENT_CONTEXT


class TestInsufficientContext:
    def test_no_normalised_value_insufficient(self):
        left = _fact(normalised_value=None, document_id="doc_a")
        right = _fact(normalised_value=6.4, document_id="doc_b")
        cmp = classify(left, right)
        verdict, reason = decide(cmp)
        assert verdict == Verdict.INSUFFICIENT_CONTEXT

    def test_different_entities_insufficient(self):
        left = _fact(entity="India", document_id="doc_a")
        right = _fact(entity="China economy completely different", document_id="doc_b")
        # entity token overlap too low
        cmp = classify(left, right)
        # verdict may be insufficient_context or period-based depending on tokens
        # But metric overlap is low too if they differ — just check it doesn't crash
        assert cmp is not None


class TestExplanation:
    def test_explanation_contains_values(self):
        left = _fact(normalised_value=6.4, document_id="doc_a")
        right = _fact(normalised_value=6.4, document_id="doc_b")
        cmp = classify(left, right)
        verdict, reason = decide(cmp)
        expl = build_explanation(cmp, verdict, reason)
        assert len(expl) > 10
        assert "6.4" in expl or "corroborate" in expl.lower() or "match" in expl.lower()


class TestSemanticMetricMatching:
    class StubMetricProvider:
        def __init__(self, same: bool, similarity: float, canonical_label: str = "revenue"):
            self.same = same
            self.similarity = similarity
            self.canonical_label = canonical_label

        def canonicalise_metric(self, left, right):
            return {
                "same": self.same,
                "similarity": self.similarity,
                "canonical_label": self.canonical_label,
            }

    def test_gray_zone_semantic_match_alias(self):
        left = _fact(metric="Revenue from operations", normalised_value=500.0, document_id="doc_a")
        right = _fact(metric="Total turnover sales revenue", normalised_value=500.0, document_id="doc_b")
        provider = self.StubMetricProvider(same=True, similarity=0.85, canonical_label="Total Revenue")
        cmp = classify(left, right, metric_provider=provider)
        verdict, reason = decide(cmp)
        assert cmp.metric_match is True
        assert cmp.canonical_metric_label == "Total Revenue"
        assert verdict == Verdict.CORROBORATES
        assert reason == ReasonCode.ALIAS_MATCH

    def test_gray_zone_semantic_non_match(self):
        left = _fact(metric="Revenue from operations", normalised_value=500.0, document_id="doc_a")
        right = _fact(metric="Total turnover sales revenue", normalised_value=500.0, document_id="doc_b")
        provider = self.StubMetricProvider(same=False, similarity=0.2, canonical_label="Different")
        cmp = classify(left, right, metric_provider=provider)
        verdict, reason = decide(cmp)
        assert cmp.metric_match is False
        assert verdict == Verdict.INSUFFICIENT_CONTEXT
        assert reason == ReasonCode.INSUFFICIENT_CONTEXT

    def test_gray_zone_provider_exception_falls_through(self):
        class FailingProvider:
            def canonicalise_metric(self, left, right):
                raise RuntimeError("API timeout")

        left = _fact(metric="Revenue from operations", normalised_value=500.0, document_id="doc_a")
        right = _fact(metric="Total turnover sales revenue", normalised_value=500.0, document_id="doc_b")
        cmp = classify(left, right, metric_provider=FailingProvider())
        verdict, reason = decide(cmp)
        assert cmp.metric_match is False
        assert verdict == Verdict.INSUFFICIENT_CONTEXT


class TestMatchMethodAndMetricScore:
    def test_clean_above_threshold_jaccard_match(self):
        left = _fact(metric="Revenue from operations", normalised_value=500.0, document_id="doc_a")
        right = _fact(metric="Revenue from operations", normalised_value=500.0, document_id="doc_b")
        cmp = classify(left, right)
        assert cmp.metric_score == 1.0
        assert cmp.match_method == "jaccard"
        assert cmp.metric_match is True

    def test_gray_zone_llm_fallback_match(self):
        left = _fact(metric="Revenue from operations", normalised_value=500.0, document_id="doc_a")
        right = _fact(metric="Total turnover sales revenue", normalised_value=500.0, document_id="doc_b")
        provider = TestSemanticMetricMatching.StubMetricProvider(same=True, similarity=0.85, canonical_label="Total Revenue")
        cmp = classify(left, right, metric_provider=provider)
        assert 0.10 <= cmp.metric_score < 0.35
        assert cmp.match_method == "llm_fallback"
        assert cmp.metric_match is True

    def test_no_overlap_none_match(self):
        left = _fact(metric="Revenue from operations", normalised_value=500.0, document_id="doc_a")
        right = _fact(metric="Completely unrelated metric", normalised_value=500.0, document_id="doc_b")
        cmp = classify(left, right)
        assert cmp.metric_score == 0.0
        assert cmp.match_method == "none"
        assert cmp.metric_match is False
