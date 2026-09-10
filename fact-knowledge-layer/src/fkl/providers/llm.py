"""LLM provider protocol — pipeline is independent of vendor."""

from __future__ import annotations

from typing import Protocol

from fkl.domain.models import ComparisonResult, Fact, FactCandidate, SourceBlock


class FactExtractionProvider(Protocol):
    def extract_facts(
        self, *, block: SourceBlock, document_context: str, canonical_entity: str | None = None
    ) -> list[FactCandidate]: ...

    def canonicalise_metric(self, *, left: Fact, right: Fact) -> dict: ...

    def explain_relationship(self, *, comparison: ComparisonResult) -> str: ...
