"""Deduplication utilities.

SHA-256 deduplication of uploaded files is handled at the API layer (documents router).
This module provides fact-level deduplication helpers for pipeline use.
"""

from __future__ import annotations

from fkl.domain.models import Fact


def deduplicate_candidates(facts: list[Fact]) -> list[Fact]:
    """Remove duplicate facts (same document, same block, same metric+value).

    Keeps the first occurrence. This is a safety net; the grounding gate
    should prevent most duplicates from being accepted.
    """
    seen: set[tuple[str, str, str]] = set()
    result: list[Fact] = []
    for f in facts:
        key = (f.document_id, f.evidence_block_id, f.metric_key or f.metric_raw, f.value_raw)
        if key not in seen:
            seen.add(key)
            result.append(f)
    return result
