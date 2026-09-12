"""Unit tests for fact deduplication key normalization (Task 8)."""

from fkl.domain.models import ExtractionMethod, Fact, ReviewState, ValueKind
from fkl.pipeline.deduplicate import deduplicate_candidates


def _make_dummy_fact(
    fact_id: str,
    doc_id: str,
    block_id: str,
    metric_raw: str,
    value_raw: str,
    metric_key: str | None = None,
) -> Fact:
    return Fact(
        id=fact_id,
        document_id=doc_id,
        ingestion_run_id="run_1",
        evidence_block_id=block_id,
        entity_raw="India",
        metric_raw=metric_raw,
        metric_key=metric_key,
        value_raw=value_raw,
        value_kind=ValueKind.NUMERIC,
        extraction_method=ExtractionMethod.TABLE_RULE,
        confidence=0.9,
        review_state=ReviewState.ACCEPTED,
    )


def test_deduplicate_metric_casing_and_whitespace():
    f1 = _make_dummy_fact("f1", "doc1", "b1", "GDP Growth", "8.2%")
    f2 = _make_dummy_fact("f2", "doc1", "b1", "  gdp  growth  ", "8.2%")
    
    deduped = deduplicate_candidates([f1, f2])
    assert len(deduped) == 1
    assert deduped[0].id == "f1"


def test_deduplicate_value_casing_and_whitespace():
    f1 = _make_dummy_fact("f1", "doc1", "b1", "Revenue", "USD 100M")
    f2 = _make_dummy_fact("f2", "doc1", "b1", "revenue", " usd  100m ")
    
    deduped = deduplicate_candidates([f1, f2])
    assert len(deduped) == 1
    assert deduped[0].id == "f1"


def test_deduplicate_across_blocks_and_documents():
    """Identical facts across different blocks in the same document deduplicate; different docs do not (Bug 3)."""
    f1 = _make_dummy_fact("f1", "doc1", "b1", "GDP Growth", "8.2%")
    f2 = _make_dummy_fact("f2", "doc1", "b2", "GDP Growth", "8.2%")
    f3 = _make_dummy_fact("f3", "doc2", "b1", "GDP Growth", "8.2%")
    
    deduped = deduplicate_candidates([f1, f2, f3])
    # f1 and f2 in doc1 deduplicate to 1; f3 in doc2 remains distinct
    assert len(deduped) == 2
    assert {f.document_id for f in deduped} == {"doc1", "doc2"}


def test_no_deduplicate_different_metrics_or_values():
    f1 = _make_dummy_fact("f1", "doc1", "b1", "GDP Growth", "8.2%")
    f2 = _make_dummy_fact("f2", "doc1", "b1", "Inflation Rate", "8.2%")
    f3 = _make_dummy_fact("f3", "doc1", "b1", "GDP Growth", "7.5%")
    
    deduped = deduplicate_candidates([f1, f2, f3])
    assert len(deduped) == 3
