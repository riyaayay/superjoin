"""Deterministic fact-pair classification.

No free-text explanation can override the rule-derived verdict or reason_code.
The decision table from the implementation blueprint is implemented here.
"""

from __future__ import annotations

import re
from typing import Any, Literal

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
    """Extract single canonical scope label incorporating role_status if present."""
    scope = fact.scope or {}
    base_scope = scope.get("consolidation") or scope.get("scope") or scope.get("level")
    role_status = getattr(fact, "role_status", None) or scope.get("role_status")
    if base_scope and role_status:
        return f"{base_scope}:{role_status}"
    return base_scope or role_status


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
METRIC_GRAY_LOW = 0.10
ENTITY_THRESHOLD = 0.25


_CONFLICTING_METRIC_PAIRS = [
    ({"income", "revenue"}, {"expense", "expenses", "expenditure", "cost", "costs"}),
    ({"asset", "assets"}, {"liability", "liabilities"}),
    ({"import", "imports"}, {"export", "exports"}),
    ({"revenue from operations"}, {"other income"}),
    ({"operating profit", "ebit"}, {"net profit", "pat"}),
    ({"employee", "employees", "workforce", "headcount", "personnel"}, {"income", "revenue", "expense", "expenses", "profit", "assets", "liabilities", "consumption", "power", "electricity"}),
    ({"consumption", "electricity", "energy", "power"}, {"income", "revenue", "expense", "expenses", "profit", "employee", "employees", "workforce"}),
]


def is_conflicting_metric(left_raw: str, right_raw: str) -> bool:
    """Return True if two metric names express mutually exclusive/opposing financial concepts."""
    import re
    l_tokens = set(re.findall(r"[a-z0-9]+", (left_raw or "").lower()))
    r_tokens = set(re.findall(r"[a-z0-9]+", (right_raw or "").lower()))
    for group_a, group_b in _CONFLICTING_METRIC_PAIRS:
        if (l_tokens & group_a and r_tokens & group_b) or (l_tokens & group_b and r_tokens & group_a):
            return True
    return False


def check_metric_equivalence(
    left: Fact,
    right: Fact,
    metric_provider: Any = None,
) -> bool:
    """
    Mandatory metric equivalence check before CORROBORATES or LIKELY_CONFLICT.
    Requires that two metrics measure the same economic/financial concept.
    """
    l_raw = (left.metric_raw or "").strip().lower()
    r_raw = (right.metric_raw or "").strip().lower()
    if l_raw == r_raw:
        return True

    if is_conflicting_metric(l_raw, r_raw):
        return False

    # High lexical overlap threshold for synonymous phrasing without conflicting keywords
    score = metric_overlap(left.metric_raw, right.metric_raw)
    return score >= METRIC_THRESHOLD


def classify(
    left: Fact,
    right: Fact,
    metric_provider: Any = None,
    metric_equivalent: bool | None = None,
) -> ComparisonResult:
    """Apply the decision table and return a ComparisonResult."""
    # Metric and entity matching (using canonical entity when available)
    left_ent = left.entity_canonical or left.entity_raw
    right_ent = right.entity_canonical or right.entity_raw
    m_score = metric_overlap(left.metric_raw, right.metric_raw)
    e_score = entity_overlap(left_ent, right_ent)

    canonical_metric_label: str | None = None
    alias_matched = False
    match_method: Literal["jaccard", "llm_fallback", "none"] = "none"

    if m_score >= METRIC_THRESHOLD:
        metric_match = True
        match_method = "jaccard"
    elif METRIC_GRAY_LOW <= m_score < METRIC_THRESHOLD and metric_provider is not None:
        l_raw = (left.metric_raw or "").strip().lower()
        r_raw = (right.metric_raw or "").strip().lower()
        if is_conflicting_metric(l_raw, r_raw):
            metric_match = False
        elif hasattr(metric_provider, "canonicalise_metric"):
            try:
                res = metric_provider.canonicalise_metric(left=left, right=right)
                if isinstance(res, dict) and res.get("same") is True and res.get("similarity", 0) >= 0.7:
                    metric_match = True
                    alias_matched = True
                    canonical_metric_label = res.get("canonical_label") or res.get("canonical")
                    match_method = "llm_fallback"
                else:
                    metric_match = False
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning("Semantic metric canonicalisation failed: %s", e)
                metric_match = False
        else:
            metric_match = False
    else:
        metric_match = False

    entity_match = e_score >= ENTITY_THRESHOLD

    if metric_equivalent is None:
        if alias_matched:
            metric_equivalent = True
        elif metric_match:
            metric_equivalent = not is_conflicting_metric(left.metric_raw, right.metric_raw)
        else:
            metric_equivalent = False

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
    elif left.value_raw and right.value_raw and left.value_kind.value == "text" and right.value_kind.value == "text":
        if normalise_text(left.value_raw) == normalise_text(right.value_raw):
            value_within_tol = True

    return ComparisonResult(
        left_fact_id=left.id,
        right_fact_id=right.id,
        metric_match=metric_match,
        entity_match=entity_match,
        metric_equivalent=metric_equivalent,
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
        canonical_metric_label=canonical_metric_label,
        metric_score=m_score,
        match_method=match_method,
    )


def decide(cmp: ComparisonResult) -> tuple[Verdict, ReasonCode]:
    """Apply the decision table to produce verdict + reason_code (R8 order)."""
    # 1. Entity & Metric token matching
    if not cmp.metric_match or not cmp.entity_match:
        return Verdict.INSUFFICIENT_CONTEXT, ReasonCode.INSUFFICIENT_CONTEXT

    # 2. Mandatory metric equivalence gate (must run before scope/role_status)
    if not cmp.metric_equivalent:
        return Verdict.INSUFFICIENT_CONTEXT, ReasonCode.INSUFFICIENT_CONTEXT

    # 3. Scope differs (folds in role_status via _scope_label) → reconcile
    if cmp.scope_match is False:
        return Verdict.RECONCILES, ReasonCode.DIFFERENT_SCOPE

    # 4. Period differs → reconcile
    if cmp.period_match is False:
        return Verdict.RECONCILES, ReasonCode.DIFFERENT_PERIOD

    # Check if this was an alias match
    is_alias = bool(getattr(cmp, "canonical_metric_label", None))

    # Non-numeric / semantic facts with matching metric, entity, scope, period
    if cmp.left_normalised is None or cmp.right_normalised is None:
        if cmp.value_within_tolerance:
            return Verdict.CORROBORATES, ReasonCode.ALIAS_MATCH if is_alias else ReasonCode.EXACT_MATCH
        return Verdict.INSUFFICIENT_CONTEXT, ReasonCode.LOW_EVIDENCE_QUALITY

    # Unit/scale conversion was needed to make values comparable
    if cmp.unit_conversion_applied:
        if cmp.value_within_tolerance:
            return Verdict.CORROBORATES, ReasonCode.ALIAS_MATCH if is_alias else ReasonCode.UNIT_OR_SCALE_DIFFERENCE
        else:
            # Values differ even after conversion — possible conflict
            if cmp.evidence_quality_left >= 0.6 and cmp.evidence_quality_right >= 0.6:
                return Verdict.LIKELY_CONFLICT, ReasonCode.MATERIAL_VALUE_DIFFERENCE
            return Verdict.INSUFFICIENT_CONTEXT, ReasonCode.UNIT_OR_SCALE_DIFFERENCE

    # Same units
    if cmp.value_within_tolerance:
        if is_alias:
            return Verdict.CORROBORATES, ReasonCode.ALIAS_MATCH
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
        val_str = str(cmp.left_normalised) if cmp.left_normalised is not None else "the reported value"
        parts.append(f"Both facts report the same value ({val_str}) for the same metric, entity, and period.")
    elif reason == ReasonCode.ALIAS_MATCH:
        label = cmp.canonical_metric_label or "semantic equivalent"
        parts.append(f"Metrics matched via semantic alias ('{label}'). Values corroborated within precision.")
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
