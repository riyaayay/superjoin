"""Deduplication and governance fact consolidation utilities.

SHA-256 deduplication of uploaded files is handled at the API layer (documents router).
This module provides fact-level deduplication and governance fact consolidation helpers.
"""

from __future__ import annotations

from fkl.domain.models import Fact, FactCandidate
from fkl.domain.normalisation import normalise_text

_RESIGNED_TERMS = frozenset([
    "resigned", "resignation", "stepped down", "stepped-down", "ceased",
    "retired", "retirement", "terminated", "termination",
])
_APPOINTED_TERMS = frozenset([
    "appointed", "appointment", "elected", "election", "joined",
    "promoted", "promotion", "named",
])


def detect_role_status(
    candidate: FactCandidate | Fact,
    block_text: str | None = None,
) -> str | None:
    """
    Detect role_status ('active', 'appointed', 'resigned') for governance/personnel facts (R6).
    Returns None for non-governance facts (e.g. purely economic/financial metrics).
    """
    gov_keywords = {
        "board", "director", "officer", "position", "resignation", "appointment",
        "retirement", "cfo", "ceo", "managing director", "executive", "role",
        "governance", "committee", "trustee", "tenure",
    }
    action_keywords = {"resigned", "appointed", "elected", "stepped down", "joined", "retired"}
    person_honorifics = {"mr.", "ms.", "mrs.", "dr."}

    m_lower = (candidate.metric_raw or "").lower()
    v_lower = (candidate.value_raw or "").lower()
    e_lower = (candidate.entity_raw or "").lower()
    scope = candidate.scope or {}
    scope_action = str(scope.get("action", "")).lower()

    is_governance = (
        any(k in m_lower for k in gov_keywords)
        or any(k in v_lower for k in action_keywords)
        or any(e_lower.startswith(h) for h in person_honorifics)
        or bool(scope_action)
        or "role_status" in scope
    )

    if not is_governance:
        return None

    # Explicit role_status if already set
    if getattr(candidate, "role_status", None):
        return candidate.role_status.lower()
    if scope.get("role_status"):
        return str(scope["role_status"]).lower()

    # Prioritize specific event verbs in value_raw, metric_raw, or scope action
    primary_text = f"{v_lower} {m_lower} {scope_action}"
    if any(term in primary_text for term in _RESIGNED_TERMS):
        return "resigned"
    if any(term in primary_text for term in _APPOINTED_TERMS):
        return "appointed"

    # Contextual clues in period_raw, evidence_quote, or block_text
    cand_quote = getattr(candidate, "evidence_quote", "") or ""
    secondary_text = f"{candidate.period_raw or ''} {cand_quote}".lower()
    if block_text:
        secondary_text = f"{secondary_text} {block_text.lower()}"

    if any(term in secondary_text for term in _RESIGNED_TERMS):
        return "resigned"
    if any(term in secondary_text for term in _APPOINTED_TERMS):
        return "appointed"

    # Default for governance/personnel disclosures is active
    return "active"


def consolidate_governance_facts(facts: list[Fact]) -> list[Fact]:
    """
    Consolidate fragmented governance facts from the same block and person (R7).

    When one block yields both an event fact (e.g. metric_raw='Board Resignation', value_raw='resigned')
    and a position fact (e.g. metric_raw='Board Position', value_raw='Independent Director') for the
    same person, merge into one canonical fact:
      metric_raw:  'Board Position: Independent Director'
      value_raw:   'Independent Director' (clean role title — never the verb 'resigned')
      role_status: 'resigned'
      period_raw:  'effective June 30, 2022'
      scope:       {'role_status': 'resigned'}
      qualifiers:  {'role_status': 'resigned'}
    """
    from collections import defaultdict

    groups: dict[tuple[str, str, str], list[Fact]] = defaultdict(list)
    other_facts: list[Fact] = []

    for f in facts:
        e_lower = (f.entity_canonical or f.entity_raw).strip().lower()
        # Governance entities typically have honorifics or are individual names with governance metrics
        is_gov = (
            any(e_lower.startswith(h) for h in ("mr.", "ms.", "mrs.", "dr."))
            or any(k in f.metric_raw.lower() for k in ("board", "director", "officer", "position", "resignation"))
        )
        if is_gov:
            groups[(f.document_id, f.evidence_block_id, e_lower)].append(f)
        else:
            other_facts.append(f)

    consolidated: list[Fact] = []

    for _, group in groups.items():
        if len(group) == 1:
            f = group[0]
            if f.metric_raw.strip().lower() == "board position" and f.value_raw:
                f.metric_raw = f"Board Position: {f.value_raw}"
                f.metric_key = f.metric_raw.lower().strip()
            consolidated.append(f)
            continue

        # Check for event fact + position fact pair
        event_facts = [
            f for f in group
            if any(k in f.metric_raw.lower() for k in ("resignation", "appointment"))
            or f.value_raw.lower() in ("resigned", "appointed", "stepped down")
        ]
        position_facts = [
            f for f in group
            if f.metric_raw.lower().startswith("board position")
            or any(k in f.value_raw.lower() for k in ("director", "officer", "member", "chairman"))
        ]

        if event_facts and position_facts:
            ef = event_facts[0]
            pf = position_facts[0]

            role_title = pf.value_raw
            status = ef.role_status or pf.role_status or detect_role_status(ef) or "resigned"
            best_period = pf.period_raw or ef.period_raw

            pf.metric_raw = f"Board Position: {role_title}"
            pf.metric_key = pf.metric_raw.lower().strip()
            pf.value_raw = role_title
            pf.role_status = status
            pf.period_raw = best_period
            pf.scope["role_status"] = status
            pf.qualifiers["role_status"] = status

            # Discard ef, keep pf and any unrelated facts
            discard_ids = {ef.id}
            for f in group:
                if f.id not in discard_ids:
                    consolidated.append(f)
        else:
            for f in group:
                if f.metric_raw.strip().lower() == "board position" and f.value_raw:
                    f.metric_raw = f"Board Position: {f.value_raw}"
                    f.metric_key = f.metric_raw.lower().strip()
                consolidated.append(f)

    return other_facts + consolidated


def deduplicate_candidates(facts: list[Fact]) -> list[Fact]:
    """Remove duplicate facts and consolidate fragmented governance facts (R7)."""
    facts = consolidate_governance_facts(facts)
    seen: set[tuple[str, str, str, str, str]] = set()
    result: list[Fact] = []
    for f in facts:
        key = (
            f.document_id,
            normalise_text(f.entity_canonical or f.entity_raw),
            normalise_text(f.metric_key or f.metric_raw),
            normalise_text(f.value_raw),
            str(f.period_raw or ""),
        )
        if key not in seen:
            seen.add(key)
            result.append(f)
    return result
