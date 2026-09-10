"""Unit tests for normalisation module."""

import pytest
from fkl.domain.normalisation import (
    detect_scale,
    normalise_value,
    parse_numeric,
    parse_period,
    rounding_tolerance,
)


class TestParseNumeric:
    def test_plain_integer(self):
        assert parse_numeric("1234") == 1234.0

    def test_comma_separated(self):
        assert parse_numeric("81,415.38") == pytest.approx(81415.38)

    def test_parentheses_negative(self):
        assert parse_numeric("(249)") == pytest.approx(-249.0)

    def test_percentage_suffix(self):
        assert parse_numeric("6.4%") == pytest.approx(6.4)

    def test_currency_prefix(self):
        assert parse_numeric("₹8,142") == pytest.approx(8142.0)

    def test_non_numeric_returns_none(self):
        assert parse_numeric("N/A") is None

    def test_empty_returns_none(self):
        assert parse_numeric("") is None


class TestDetectScale:
    def test_crore(self):
        assert detect_scale("₹ in crore") == "crore"

    def test_million(self):
        assert detect_scale("USD million") == "million"

    def test_lakh_crore(self):
        assert detect_scale("₹ lakh crore") == "lakh crore"

    def test_percent(self):
        assert detect_scale("growth %") == "percent"

    def test_no_scale(self):
        assert detect_scale("GDP") == ""


class TestRoundingTolerance:
    def test_whole_number(self):
        # "8,142" → 0.5
        assert rounding_tolerance("8,142") == pytest.approx(0.5)

    def test_one_decimal(self):
        # "6.4" → 0.05
        assert rounding_tolerance("6.4") == pytest.approx(0.05)

    def test_two_decimals(self):
        # "81,415.38" → 0.005
        assert rounding_tolerance("81,415.38") == pytest.approx(0.005)

    def test_with_scale_multiplier(self):
        # "8,142" with scale 0.1 (million→crore) → 0.5 * 0.1 = 0.05
        assert rounding_tolerance("8,142", 0.1) == pytest.approx(0.05)


class TestNormaliseValue:
    def test_million_to_crore(self):
        prov = normalise_value("81415.38", "₹ million", "million")
        assert prov.normalised_value == pytest.approx(8141.538)

    def test_crore_unchanged(self):
        prov = normalise_value("8142", "₹ crore", "crore")
        assert prov.normalised_value == pytest.approx(8142.0)

    def test_negative_parentheses(self):
        prov = normalise_value("(249)", None, None)
        assert prov.normalised_value == pytest.approx(-249.0)

    def test_percent_no_conversion(self):
        prov = normalise_value("6.4", "%", "percent")
        assert prov.normalised_value == pytest.approx(6.4)

    def test_non_numeric_no_value(self):
        prov = normalise_value("N/A", None, None)
        assert prov.normalised_value is None

    def test_provenance_steps_recorded(self):
        prov = normalise_value("81415.38", "₹ million", "million")
        assert any(s.operation == "scale_conversion" for s in prov.steps)


class TestParsePeriod:
    def test_fy_short_with_context(self):
        p = parse_period("FY24", doc_context="The company's fiscal year ending March 31, 2024.")
        assert p["start"] == "2023-04"
        assert p["end"] == "2024-03"

    def test_fy_full_with_context(self):
        p = parse_period("FY 2024-25", doc_context="financial year ends 31 March.")
        assert p["start"] == "2024-04"
        assert p["end"] == "2025-03"

    def test_q4_fy24_with_context(self):
        p = parse_period("Q4 FY24", doc_context="year ended 31.03.2024")
        assert p["start"] == "2024-01"
        assert p["end"] == "2024-03"

    def test_q1_fy25_with_context(self):
        p = parse_period("Q1 FY25", doc_context="fiscal year ending March 31")
        assert p["start"] == "2024-04"
        assert p["end"] == "2024-06"

    def test_fy_without_context_returns_unknown(self):
        p = parse_period("FY24")
        assert p["start"] is None
        assert p["end"] is None
        assert p.get("period_convention") == "unknown"

    def test_fy_december_end(self):
        p = parse_period("FY24", doc_context="Company fiscal year ending December 31.")
        assert p["start"] == "2024-01"
        assert p["end"] == "2024-12"

    def test_calendar_year(self):
        p = parse_period("2024")
        assert p["start"] == "2024-01"
        assert p["end"] == "2024-12"

    def test_no_period(self):
        p = parse_period("no period here")
        assert p["start"] is None
        assert p["end"] is None

    def test_year_ended_period(self):
        p = parse_period("Year ended 31.03.2023 (Audited)")
        assert p["start"] == "2022-04"
        assert p["end"] == "2023-03"

    def test_parenthesised_token_preserved(self):
        """Header strings ending with a parenthesised token (e.g. '(Audited)', '(Rs. in Lakhs)') must retain closing paren."""
        from fkl.pipeline.parse_pdf import _balance_parens
        from fkl.pipeline.extract_table_facts import _balance_parens as tbl_balance

        raw_audited = "Year ended 31.03.2023 (Audited)"
        truncated_audited = "Year ended 31.03.2023 (Audited"
        assert _balance_parens(raw_audited) == "Year ended 31.03.2023 (Audited)"
        assert _balance_parens(truncated_audited) == "Year ended 31.03.2023 (Audited)"
        assert tbl_balance(truncated_audited) == "Year ended 31.03.2023 (Audited)"

        truncated_unit = "Stand-alone Financial Results (Rs. in Lakhs"
        assert _balance_parens(truncated_unit) == "Stand-alone Financial Results (Rs. in Lakhs)"
        assert tbl_balance(truncated_unit) == "Stand-alone Financial Results (Rs. in Lakhs)"
