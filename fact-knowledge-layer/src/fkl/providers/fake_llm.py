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
        self,
        *,
        block: SourceBlock,
        document_context: str,
        canonical_entity: str | None = None,
    ) -> list[FactCandidate]:
        # Skip chart/image blocks
        text_lower = block.text.lower()
        if any(hint in text_lower for hint in _CHART_HINTS) and len(block.text) < 120:
            return []

        # Check for semantic governance / event facts (e.g. board changes)
        import re
        gov_match = re.search(
            r"((?:Mr\.|Ms\.|Mrs\.|Dr\.)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+).*?\b(resigned|appointed|elected|stepped down|joined)\b",
            block.text,
            re.IGNORECASE,
        )
        if gov_match:
            person_name = gov_match.group(1).strip()
            action = gov_match.group(2).lower()
            return [
                FactCandidate(
                    entity_raw=person_name,
                    metric_raw=f"Board {action.capitalize()}",
                    value_raw=action,
                    unit_raw=None,
                    period_raw=None,
                    scope={"action": action},
                    evidence_quote=gov_match.group(0),
                    confidence_hint=0.90,
                )
            ]

        # Check trigger words for numeric facts
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
                entity_raw=canonical_entity or "Test entity",
                metric_raw=trigger.title(),
                value_raw=nums[0],
                unit_raw="%",
                period_raw="FY25",
                evidence_quote=nums[0],
                confidence_hint=0.55,
            )
        ]

    def canonicalise_metric(self, *, left: Fact, right: Fact) -> dict:
        """Return a simple similarity score for test purposes with accounting conflict detection."""
        import re
        from fkl.domain.classification import metric_overlap

        l_raw = left.metric_raw.strip().lower()
        r_raw = right.metric_raw.strip().lower()
        if l_raw == r_raw:
            return {"same": True, "canonical_key": l_raw, "similarity": 1.0}

        conflicts = [
            ({"income", "revenue"}, {"expense", "expenses", "expenditure", "cost"}),
            ({"asset", "assets"}, {"liability", "liabilities"}),
            ({"revenue from operations"}, {"other income"}),
        ]
        l_words = set(re.findall(r"[a-z0-9]+", l_raw))
        r_words = set(re.findall(r"[a-z0-9]+", r_raw))
        for a, b in conflicts:
            if (l_words & a and r_words & b) or (l_words & b and r_words & a):
                return {"same": False, "canonical_key": l_raw, "similarity": 0.0}

        score = metric_overlap(left.metric_raw, right.metric_raw)
        return {"same": score >= 0.75, "canonical_key": l_raw, "similarity": score}

    def explain_relationship(self, *, comparison: ComparisonResult) -> str:
        return f"[FAKE] Left={comparison.left_normalised}, Right={comparison.right_normalised}"
