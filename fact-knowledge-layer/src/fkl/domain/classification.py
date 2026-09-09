"""Deterministic fact-pair classification.

No free-text explanation can override the rule-derived verdict or reason_code.
The decision table from the implementation blueprint is implemented here.
"""

from __future__ import annotations

import re

from fkl.domain.enums import ReasonCode, Verdict
from fkl.domain.models import ComparisonResult, Fact
from fkl.domain.normalisation import normalise_text, rounding_tolerance, SCALE_TO_MULTIPLIER


# ---------------------------------------------------------------------------
# Metric / entity matching helpers
# ---------------------------------------------------------------------------

_STOP_WORDS = frozenset(
    ["the", "a", "an", "of", "in", "at", "by", "for", "to", "from", "and", "or", "on", "as"]
)


def _tokens(text: str) -> frozenset[str]:
    """Lower-case, stop-word-filtered word tokens."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return frozenset(w for w in words if w not in _STOP_WORDS and len(w) > 1)


def metric_overlap(a: str, b: str) -> float:
    """Jaccard similarity of metric token sets."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def entity_overlap(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _scope_label(fact: Fact) -> str | None:
    """Extract single canonical scope label if available."""
    scope = fact.scope or {}
    return scope.get("consolidation") or scope.get("scope") or scope.get("level")


def _period_label(fact: Fact) -> str | None:
    if fact.period_start and fact.period_end:
        return f"{fact.period_start}:{fact.period_end}"
    return fact.period_raw


# ---------------------------------------------------------------------------
# Conversion between compatible units
# ---------------------------------------------------------------------------

_SCALE_UNITS = set(SCALE_TO_MULTIPLIER.keys()) - {"percent", "%", ""}


def _try_convert(left: Fact, right: Fact) -> tuple[float | None, float | None, float | None]:
    """Attempt unit-scale conversion. Returns (left_norm, right_norm, factor)."""
    lv, rv = left.normalised_value, right.normalised_value
    if lv is None or rv is None:
        return None, None, None

    lu = (left.normalised_unit or "").lower().strip()
    ru = (right.normalised_unit or "").lower().strip()

    if lu == ru:
        return lv, rv, 1.0

    lm = SCALE_TO_MULTIPLIER.get(lu)
    rm = SCALE_TO_MULTIPLIER.get(ru)

    if lm is None or rm is None:
        return None, None, None
    if lu == "percent" or ru == "percent":
        return None, None, None

    # Convert both to crore
    lv_crore = lv * lm
    rv_crore = rv * rm
    return lv_crore, rv_crore, rm / lm


# ---------------------------------------------------------------------------
# Main classification function
# ---------------------------------------------------------------------------

METRIC_THRESHOLD = 0.35
ENTITY_THRESHOLD = 0.25


def classify(left: Fact, right: Fact) -> ComparisonResult:
    """Apply the decision table and return a ComparisonResult."""
    # Metric and entity matching
    m_score = metric_overlap(left.metric_raw, right.metric_raw)
    e_score = entity_overlap(left.entity_raw, right.entity_raw)

    metric_match = m_score >= METRIC_THRESHOLD
    entity_match = e_score >= ENTITY_THRESHOLD

    # Scope and period
    scope_l = _scope_label(left)
    scope_r = _scope_label(right)
    period_l = _period_label(left)
    period_r = _period_label(right)

    scope_match: bool | None = None
    if scope_l and scope_r:
        scope_match = scope_l.lower() == scope_r.lower()

    period_match: bool | None = None
    if period_l and period_r:
        period_match = period_l == period_r

    # Value comparison
    lv_conv, rv_conv, factor = _try_convert(left, right)
    converted = factor is not None and factor != 1.0
    value_within_tol: bool | None = None
    tolerance: float | None = None

    if lv_conv is not None and rv_conv is not None:
        raw_str = left.value_raw if left.normalised_value is not None else right.value_raw
        scale_m = SCALE_TO_MULTIPLIER.get((left.normalised_unit or "").lower(), 1.0)
        tolerance = rounding_tolerance(raw_str, scale_m) + rounding_tolerance(right.value_raw, SCALE_TO_MULTIPLIER.get((right.normalised_unit or "").lower(), 1.0))
        value_within_tol = abs(lv_conv - rv_conv) <= tolerance

    return ComparisonResult(
        left_fact_id=left.id,
        right_fact_id=right.id,
        metric_match=metric_match,
        entity_match=entity_match,
        period_match=period_match,
        scope_match=scope_match,
        left_normalised=lv_conv,
        right_normalised=rv_conv,
        tolerance=tolerance,
        value_within_tolerance=value_within_tol,
        unit_conversion_applied=converted,
        conversion_factor=factor,
        scope_left=scope_l,
        scope_right=scope_r,
        period_left=period_l,
        period_right=period_r,
        evidence_quality_left=left.confidence,
        evidence_quality_right=right.confidence,
    )


def decide(cmp: ComparisonResult) -> tuple[Verdict, ReasonCode]:
    """Apply the decision table to produce verdict + reason_code."""
    # Insufficient data
    if not cmp.metric_match or not cmp.entity_match:
        return Verdict.INSUFFICIENT_CONTEXT, ReasonCode.INSUFFICIENT_CONTEXT

    if cmp.left_normalised is None or cmp.right_normalised is None:
        return Verdict.INSUFFICIENT_CONTEXT, ReasonCode.LOW_EVIDENCE_QUALITY

    # Period differs → reconcile
    if cmp.period_match is False:
        return Verdict.RECONCILES, ReasonCode.DIFFERENT_PERIOD

    # Scope differs (same period or unknown period) → reconcile
    if cmp.scope_match is False:
        return Verdict.RECONCILES, ReasonCode.DIFFERENT_SCOPE

    # Unit/scale conversion was needed to make values comparable
    if cmp.unit_conversion_applied:
        if cmp.value_within_tolerance:
            return Verdict.CORROBORATES, ReasonCode.UNIT_OR_SCALE_DIFFERENCE
        else:
            # Values differ even after conversion — possible conflict
            if cmp.evidence_quality_left >= 0.6 and cmp.evidence_quality_right >= 0.6:
                return Verdict.LIKELY_CONFLICT, ReasonCode.MATERIAL_VALUE_DIFFERENCE
            return Verdict.INSUFFICIENT_CONTEXT, ReasonCode.UNIT_OR_SCALE_DIFFERENCE

    # Same units
    if cmp.value_within_tolerance:
        tol = cmp.tolerance or 0
        diff = abs((cmp.left_normalised or 0) - (cmp.right_normalised or 0))
        if diff == 0:
            return Verdict.CORROBORATES, ReasonCode.EXACT_MATCH
        return Verdict.CORROBORATES, ReasonCode.ROUNDED_MATCH

    # Values do not overlap
    if cmp.evidence_quality_left >= 0.6 and cmp.evidence_quality_right >= 0.6:
        return Verdict.LIKELY_CONFLICT, ReasonCode.MATERIAL_VALUE_DIFFERENCE
    return Verdict.INSUFFICIENT_CONTEXT, ReasonCode.INSUFFICIENT_CONTEXT


def build_explanation(cmp: ComparisonResult, verdict: Verdict, reason: ReasonCode) -> str:
    """Generate a structured human-readable explanation grounded in the comparison fields."""
    parts: list[str] = []

    if reason == ReasonCode.EXACT_MATCH:
        parts.append(f"Both facts report the same value ({cmp.left_normalised}) for the same metric, entity, and period.")
    elif reason == ReasonCode.ROUNDED_MATCH:
        diff = abs((cmp.left_normalised or 0) - (cmp.right_normalised or 0))
        parts.append(
            f"Values {cmp.left_normalised} and {cmp.right_normalised} differ by {diff:.4g}, "
            f"within display-precision tolerance ±{cmp.tolerance:.4g}. Consistent rounding."
        )
    elif reason == ReasonCode.DIFFERENT_PERIOD:
        parts.append(
            f"Same metric and entity but different reporting periods "
            f"({cmp.period_left} vs {cmp.period_right}). No conflict; reconciled by period."
        )
    elif reason == ReasonCode.DIFFERENT_SCOPE:
        parts.append(
            f"Same metric and period but different reporting scope "
            f"({cmp.scope_left or 'unknown'} vs {cmp.scope_right or 'unknown'}). "
            "Values differ by design; reconciled by scope distinction."
        )
    elif reason == ReasonCode.UNIT_OR_SCALE_DIFFERENCE:
        parts.append(
            f"Different units/scales. After conversion (factor {cmp.conversion_factor:.4g}): "
            f"{cmp.left_normalised:.4g} vs {cmp.right_normalised:.4g}, "
            f"tolerance ±{cmp.tolerance:.4g}."
        )
        if verdict == Verdict.CORROBORATES:
            parts.append("Values agree within precision — corroborated.")
        else:
            parts.append("Values remain outside tolerance after conversion — context insufficient.")
    elif reason == ReasonCode.MATERIAL_VALUE_DIFFERENCE:
        parts.append(
            f"Values {cmp.left_normalised:.4g} and {cmp.right_normalised:.4g} differ materially "
            f"(diff {abs((cmp.left_normalised or 0)-(cmp.right_normalised or 0)):.4g}, "
            f"tolerance ±{cmp.tolerance:.4g}). Both evidence sources have confidence ≥ 0.6. "
            "Flagged as LIKELY_CONFLICT — human review required before confirming."
        )
    elif reason == ReasonCode.INSUFFICIENT_CONTEXT:
        parts.append(
            "Insufficient context to classify: metric, entity, period, scope, or value information is missing or ambiguous."
        )
    else:
        parts.append(f"Verdict: {verdict.value}, Reason: {reason.value}.")

    return " ".join(parts)
