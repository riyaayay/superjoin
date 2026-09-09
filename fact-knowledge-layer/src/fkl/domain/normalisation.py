"""Transparent numerical and semantic normalisation.

All transformations return provenance objects — no magic constants.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from fkl.domain.models import NormalisationStep, NormalisationProvenance

RULE_VERSION = "1.0"

# Known scale multipliers to a common base (INR ones)
SCALE_TO_MULTIPLIER: dict[str, float] = {
    "crore": 1.0,
    "cr": 1.0,
    "lakh crore": 100.0,
    "lakh": 0.01,
    "million": 0.1,  # 1 million INR = 0.1 crore
    "mn": 0.1,
    "billion": 100.0,  # 1 billion INR = 100 crore
    "bn": 100.0,
    "trillion": 100_000.0,
    "thousand": 0.00001,
    "percent": 1.0,  # kept as-is
    "%": 1.0,
    "": 1.0,  # no scale
}

SCALE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\blakh\s*crore\b", re.I), "lakh crore"),
    (re.compile(r"\bcrore\b", re.I), "crore"),
    (re.compile(r"\bcr\b", re.I), "crore"),
    (re.compile(r"\blakh\b", re.I), "lakh"),
    (re.compile(r"\bmillion\b", re.I), "million"),
    (re.compile(r"\bmn\b", re.I), "million"),
    (re.compile(r"\bbillion\b", re.I), "billion"),
    (re.compile(r"\bbn\b", re.I), "billion"),
    (re.compile(r"\btrillion\b", re.I), "trillion"),
    (re.compile(r"\bthousand\b", re.I), "thousand"),
    (re.compile(r"%", re.I), "percent"),
    (re.compile(r"\bpercent\b", re.I), "percent"),
]


def detect_scale(text: str) -> str:
    """Return the canonical scale name or '' if none detected."""
    for pattern, name in SCALE_PATTERNS:
        if pattern.search(text):
            return name
    return ""


def parse_numeric(raw: str) -> float | None:
    """Parse a numeric string, handling commas, parentheses, and % suffixes."""
    s = raw.strip()
    negative = s.startswith("(") and s.endswith(")")
    s = s.lstrip("(").rstrip(")")
    s = s.rstrip("%").strip()
    s = s.replace(",", "").replace("₹", "").replace("$", "").strip()
    try:
        val = float(Decimal(s))
        return -val if negative else val
    except (InvalidOperation, ValueError):
        return None


def rounding_tolerance(raw: str, scale_multiplier: float = 1.0) -> float:
    """Derive tolerance from displayed precision, not a magic global threshold.

    e.g. "8,142" (whole units) → ±0.5
         "6.4" (1 decimal) → ±0.05
         "81,415.38" (2 decimals) → ±0.005
    """
    s = raw.strip().lstrip("(").rstrip(")")
    s = s.rstrip("%").strip().replace(",", "")
    if "." in s:
        decimals = len(s.split(".")[-1])
        half_unit = 0.5 * (10 ** -decimals)
    else:
        half_unit = 0.5
    return half_unit * scale_multiplier


def normalise_value(
    value_raw: str,
    unit_raw: str | None,
    scale_raw: str | None = None,
) -> NormalisationProvenance:
    """Normalise a raw value with transparent provenance."""
    steps: list[NormalisationStep] = []

    numeric = parse_numeric(value_raw)
    if numeric is None:
        return NormalisationProvenance(steps=steps)

    # Detect scale from context
    context = f"{unit_raw or ''} {scale_raw or ''}".lower()
    scale = detect_scale(context) if not scale_raw else (scale_raw.lower().strip())
    multiplier = SCALE_TO_MULTIPLIER.get(scale, 1.0)

    # Parentheses negative
    is_negative = value_raw.strip().startswith("(") and value_raw.strip().endswith(")")
    if is_negative:
        steps.append(
            NormalisationStep(
                operation="parentheses_negative",
                input=value_raw,
                output=-abs(numeric),
                rule_version=RULE_VERSION,
            )
        )
        numeric = -abs(numeric)

    # Scale conversion to crore (for INR) or keep as-is for %/other
    if scale and scale != "crore" and scale != "percent":
        converted = numeric * multiplier
        steps.append(
            NormalisationStep(
                operation="scale_conversion",
                input=str(numeric),
                input_unit=f"{unit_raw or ''} {scale}".strip(),
                output=converted,
                output_unit=f"{unit_raw or ''} crore".strip() if "inr" in context or "₹" in (unit_raw or "") else "crore-equivalent",
                rule_version=RULE_VERSION,
            )
        )
        numeric = converted
        normalised_unit = "crore" if "inr" in context or "₹" in (unit_raw or "").lower() else scale
    else:
        normalised_unit = scale or (unit_raw or "")

    # Period parsing
    period_prov = parse_period(unit_raw or "")

    return NormalisationProvenance(
        steps=steps,
        normalised_value=numeric,
        normalised_unit=normalised_unit,
        period_start=period_prov.get("start"),
        period_end=period_prov.get("end"),
    )


# ---------------------------------------------------------------------------
# Period parsing
# ---------------------------------------------------------------------------

_FY_FULL = re.compile(r"FY\s*(\d{2,4})-(\d{2,4})", re.I)
_FY_SHORT = re.compile(r"FY\s*(\d{2,4})", re.I)
_QFY = re.compile(r"Q([1-4])\s*FY\s*(\d{2,4})", re.I)
_CAL_YEAR = re.compile(r"\b(20\d{2})\b")


def parse_period(text: str) -> dict[str, str | None]:
    """Extract period start/end from raw period text."""
    m = _QFY.search(text)
    if m:
        q, fy_short = int(m.group(1)), int(m.group(2))
        fy = 2000 + fy_short if fy_short < 100 else fy_short
        q_starts = {1: f"{fy-1}-04", 2: f"{fy-1}-07", 3: f"{fy-1}-10", 4: f"{fy}-01"}
        q_ends = {1: f"{fy-1}-06", 2: f"{fy-1}-09", 3: f"{fy-1}-12", 4: f"{fy}-03"}
        return {"start": q_starts[q], "end": q_ends[q]}

    m = _FY_FULL.search(text)
    if m:
        start_y = int(m.group(1)) if int(m.group(1)) > 100 else 2000 + int(m.group(1))
        end_y = int(m.group(2)) if int(m.group(2)) > 100 else 2000 + int(m.group(2))
        return {"start": f"{start_y}-04", "end": f"{end_y}-03"}

    m = _FY_SHORT.search(text)
    if m:
        fy = int(m.group(1))
        fy = 2000 + fy if fy < 100 else fy
        return {"start": f"{fy-1}-04", "end": f"{fy}-03"}

    m = _CAL_YEAR.search(text)
    if m:
        y = int(m.group(1))
        return {"start": f"{y}-01", "end": f"{y}-12"}

    return {"start": None, "end": None}


# ---------------------------------------------------------------------------
# Text normalisation for matching
# ---------------------------------------------------------------------------

_WS = re.compile(r"\s+")
_NBSP = re.compile(r"\u00a0|\u200b|\ufeff")


def normalise_text(text: str) -> str:
    """Collapse whitespace, strip non-breaking spaces, lowercase for matching."""
    text = _NBSP.sub(" ", text)
    text = _WS.sub(" ", text)
    return text.strip().lower()
