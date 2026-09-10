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
    """Parse a numeric string, handling commas, parentheses, currencies, unicode minus, and suffixes."""
    s = raw.strip().replace("\u2212", "-")
    negative = (s.startswith("(") and s.endswith(")")) or s.startswith("-")
    s = s.lstrip("(").rstrip(")").lstrip("-").strip()
    s = s.rstrip("%").strip()
    for sym in ("₹", "$", "€", "£", "¥"):
        s = s.replace(sym, "")
    s = s.strip()
    s_lower = s.lower()
    for suf in ("bps", "bp", "x"):
        if s_lower.endswith(suf):
            s = s[: -len(suf)].strip()
            break
    s = s.replace(",", "").strip()
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
    doc_context: str | None = None,
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
    period_prov = parse_period(unit_raw or "", doc_context=doc_context)

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
_YEAR_ENDED = re.compile(r"year\s+ended\s+(\d{1,2})[\.\/-](\d{1,2})[\.\/-](\d{4})", re.I)
_QUARTER_ENDED = re.compile(r"(?:quarter|3\s*months?)\s+ended\s+(\d{1,2})[\.\/-](\d{1,2})[\.\/-](\d{4})", re.I)
_DATE_DMY = re.compile(r"\b(\d{1,2})[\.\/-](\d{1,2})[\.\/-](\d{4})\b")
_CAL_YEAR = re.compile(r"\b(20\d{2})\b")

_MONTH_NAMES = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}

_FY_END_RE = re.compile(
    r"(?:fiscal\s+year|financial\s+year|year)\s+(?:ends|ended|ending)\s+(?:on\s+)?([a-z0-9\.\/-]+(?:\s+[a-z0-9]+)?)",
    re.IGNORECASE,
)
_DATE_DD_MM = re.compile(r"(\d{1,2})[\.\/-](\d{1,2})")


def detect_fy_end_month(text: str | None) -> int | None:
    """Find explicit fiscal year end month from text (e.g. 'fiscal year ending March 31')."""
    if not text:
        return None
    m = _FY_END_RE.search(text)
    if not m:
        return None
    matched_phrase = m.group(1).lower()
    for name, month_num in _MONTH_NAMES.items():
        if name in matched_phrase:
            return month_num
    dm = _DATE_DD_MM.search(matched_phrase)
    if dm:
        return int(dm.group(2))
    return None


def parse_period(text: str, *, doc_context: str | None = None) -> dict[str, str | None]:
    """Extract period start/end from raw period text, using doc_context for ambiguous FY conventions."""
    # Year ended DD.MM.YYYY
    m = _YEAR_ENDED.search(text)
    if m:
        month, year = int(m.group(2)), int(m.group(3))
        if month == 3:
            return {"start": f"{year-1}-04", "end": f"{year}-03"}
        elif month == 12:
            return {"start": f"{year}-01", "end": f"{year}-12"}
        else:
            start_y = year if month == 12 else year - 1
            start_m = (month % 12) + 1
            return {"start": f"{start_y}-{start_m:02d}", "end": f"{year}-{month:02d}"}

    # Quarter / 3 months ended DD.MM.YYYY
    m = _QUARTER_ENDED.search(text)
    if m:
        month, year = int(m.group(2)), int(m.group(3))
        q_start_month = max(1, month - 2)
        return {"start": f"{year}-{q_start_month:02d}", "end": f"{year}-{month:02d}"}

    # Ambiguous fiscal year strings: Q[1-4] FY..., FY YYYY-YY, FY YY
    is_qfy = _QFY.search(text)
    is_fy_full = _FY_FULL.search(text)
    is_fy_short = _FY_SHORT.search(text)

    if is_qfy or is_fy_full or is_fy_short:
        fy_end_m = detect_fy_end_month(doc_context) or detect_fy_end_month(text)
        if fy_end_m is None:
            return {"start": None, "end": None, "period_convention": "unknown"}

        start_m = (fy_end_m % 12) + 1

        if is_qfy:
            q, fy_short = int(is_qfy.group(1)), int(is_qfy.group(2))
            fy = 2000 + fy_short if fy_short < 100 else fy_short
            offset = (q - 1) * 3
            q_start_m = (start_m - 1 + offset) % 12 + 1
            q_end_m = (q_start_m + 2 - 1) % 12 + 1
            y_start = fy if (fy_end_m == 12 or q_start_m < start_m) else fy - 1
            y_end = fy if (fy_end_m == 12 or (q_end_m <= fy_end_m and q_end_m >= q_start_m)) else fy - 1
            return {"start": f"{y_start}-{q_start_m:02d}", "end": f"{y_end}-{q_end_m:02d}"}

        if is_fy_full:
            start_y = int(is_fy_full.group(1)) if int(is_fy_full.group(1)) > 100 else 2000 + int(is_fy_full.group(1))
            end_y = int(is_fy_full.group(2)) if int(is_fy_full.group(2)) > 100 else 2000 + int(is_fy_full.group(2))
            return {"start": f"{start_y}-{start_m:02d}", "end": f"{end_y}-{fy_end_m:02d}"}

        if is_fy_short:
            fy = int(is_fy_short.group(1))
            fy = 2000 + fy if fy < 100 else fy
            start_y = fy if fy_end_m == 12 else fy - 1
            return {"start": f"{start_y}-{start_m:02d}", "end": f"{fy}-{fy_end_m:02d}"}

    # Explicit DMY date
    m = _DATE_DMY.search(text)
    if m:
        month, year = int(m.group(2)), int(m.group(3))
        return {"start": f"{year}-{month:02d}", "end": f"{year}-{month:02d}"}

    # Calendar year
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
