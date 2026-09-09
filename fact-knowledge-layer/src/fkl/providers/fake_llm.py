"""Deterministic fake LLM provider for tests — never used in production."""

from __future__ import annotations

from fkl.domain.models import ComparisonResult, Fact, FactCandidate, SourceBlock

_NUMERIC_PATTERN = __import__("re").compile(r"\b\d[\d,\.]*\b")

# Sentinel phrases that indicate the block looks like a chart/image caption
_CHART_HINTS = ["figure", "chart", "graph", "exhibit", "illustration"]


class FakeLLMProvider:
    """Returns deterministic structured output for unit/integration tests.

    Rules:
    - If the block text contains a recognisable numeric value alongside a word like
      'GDP', 'CPI', 'inflation', 'growth', 'revenue', 'rate', emit a single candidate.
    - Otherwise return [].
    - Never fabricates values absent from block.text.
    """

    _FACT_TRIGGERS = [
        "gdp", "cpi", "inflation", "growth", "revenue", "rate", "deficit",
        "export", "import", "fiscal", "monetary", "interest", "trade",
    ]

    def extract_facts(
        self, *, block: SourceBlock, document_context: str
    ) -> list[FactCandidate]:
        # Skip chart/image blocks
        text_lower = block.text.lower()
        if any(hint in text_lower for hint in _CHART_HINTS) and len(block.text) < 120:
            return []

        # Check trigger words
        has_trigger = any(t in text_lower for t in self._FACT_TRIGGERS)
        if not has_trigger:
            return []

        nums = _NUMERIC_PATTERN.findall(block.text)
        if not nums:
            return []

        # Build one candidate per trigger × first numeric
        trigger = next(t for t in self._FACT_TRIGGERS if t in text_lower)
        return [
            FactCandidate(
                entity_raw="Test entity",
                metric_raw=trigger.title(),
                value_raw=nums[0],
                unit_raw="%",
                period_raw="FY25",
                evidence_quote=nums[0],
                confidence_hint=0.55,
            )
        ]

    def canonicalise_metric(self, *, left: Fact, right: Fact) -> dict:
        """Return a simple similarity score for test purposes."""
        from fkl.domain.classification import metric_overlap

        score = metric_overlap(left.metric_raw, right.metric_raw)
        return {"canonical_key": left.metric_raw.lower(), "similarity": score}

    def explain_relationship(self, *, comparison: ComparisonResult) -> str:
        return f"[FAKE] Left={comparison.left_normalised}, Right={comparison.right_normalised}"
