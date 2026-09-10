"""Unit tests validating all 7 diagnosed bug fixes."""

import fitz
import pytest
from datetime import datetime
from fkl.domain.enums import ExtractionMethod, ReviewState, ValueKind, UnitDimension, Verdict, ReasonCode, BlockKind
from fkl.domain.models import Fact, FactCandidate
from fkl.pipeline.parse_pdf import resolve_canonical_entity, _balance_parens
from fkl.pipeline.build_relationships import _passes_blocking
from fkl.domain.classification import decide
from fkl.application.ingest_document import _make_fact
from fkl.pipeline.ground_candidates import GroundingResult


def _sample_fact(
    id="f1",
    doc_id="doc1",
    entity="Reliance Industries Limited",
    metric="Revenue from Operations",
    value=100.0,
    unit="crore",
    p_start="2023-04",
    p_end="2024-03",
    canonical_entity=None,
) -> Fact:
    is_num = isinstance(value, (int, float))
    return Fact(
        id=id,
        document_id=doc_id,
        ingestion_run_id="run1",
        evidence_block_id="blk1",
        entity_raw=entity,
        entity_canonical=canonical_entity or entity,
        metric_raw=metric,
        metric_key=metric.lower(),
        value_raw=str(value),
        numeric_value=float(value) if is_num else None,
        value_kind=ValueKind.NUMERIC if is_num else ValueKind.TEXT,
        unit_raw=unit if is_num else None,
        unit_dimension=UnitDimension.CURRENCY if is_num else UnitDimension.UNKNOWN,
        scale_raw="crore" if is_num else None,
        normalised_value=float(value) if is_num else None,
        normalised_unit=unit if is_num else None,
        period_raw=f"{p_start} to {p_end}",
        period_start=p_start,
        period_end=p_end,
        scope={},
        extraction_method=ExtractionMethod.TABLE_RULE,
        confidence=0.9,
        review_state=ReviewState.ACCEPTED,
        created_at=datetime.utcnow(),
    )


class TestFix1CanonicalEntity:
    def test_canonical_entity_detection_prefers_corporate_entity(self):
        doc = fitz.open()
        page = doc.new_page()
        # Page header with company name in larger font
        page.insert_text(fitz.Point(50, 50), "TATA MOTORS LIMITED", fontsize=16)
        page.insert_text(fitz.Point(50, 80), "CIN: L28920MH1945PLC004520", fontsize=10)
        page.insert_text(fitz.Point(50, 110), "Financial Results for Quarter Ended June 30, 2024", fontsize=12)

        entity = resolve_canonical_entity(doc)
        assert entity == "TATA MOTORS LIMITED"
        doc.close()

    def test_canonical_entity_falls_back_to_author_metadata_if_present(self):
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text(fitz.Point(50, 50), "Overview of Economic Growth", fontsize=12)
        doc.set_metadata({"author": "Reserve Bank of India"})

        entity = resolve_canonical_entity(doc)
        assert entity == "Reserve Bank of India"
        doc.close()

    def test_fact_construction_prefers_canonical_entity_over_table_caption(self):
        cand = FactCandidate(
            entity_raw="Consolidated Statement of Profit and Loss (Extract)",
            metric_raw="Total Income",
            value_raw="5000",
            unit_raw="crore",
            evidence_quote="5000",
            confidence_hint=0.8,
        )
        grounding = GroundingResult(
            accepted=True,
            evidence_block_id="blk1",
            confidence=0.85,
        )
        fact = _make_fact(
            cand, grounding, "run1", "doc1", ExtractionMethod.TABLE_RULE,
            canonical_entity="Tata Consultancy Services Limited"
        )
        assert fact.entity_canonical == "Tata Consultancy Services Limited"
        assert fact.entity_raw == "Tata Consultancy Services Limited"

    def test_fact_construction_with_specific_non_generic_entity(self):
        cand = FactCandidate(
            entity_raw="Solstice Renewable Power",
            metric_raw="Installed Capacity",
            value_raw="1200",
            unit_raw="MW",
            evidence_quote="1200",
            confidence_hint=0.9,
        )
        grounding = GroundingResult(
            accepted=True,
            evidence_block_id="blk1",
            confidence=0.9,
        )
        # Table rule method overrides to canonical entity
        fact_table = _make_fact(
            cand, grounding, "run1", "doc1", ExtractionMethod.TABLE_RULE,
            canonical_entity="Solstice Energy Limited"
        )
        assert fact_table.entity_canonical == "Solstice Energy Limited"

        # Text LLM method with specific entity
        fact_text = _make_fact(
            cand, grounding, "run1", "doc1", ExtractionMethod.TEXT_LLM,
            canonical_entity="Solstice Energy Limited"
        )
        assert fact_text.entity_canonical == "Solstice Energy Limited"


class TestFix2TwoDimensionalBlocking:
    def test_both_entity_and_metric_overlap_passes(self):
        f1 = _sample_fact(entity="Reliance Industries", metric="Net Revenue from Operations")
        f2 = _sample_fact(entity="Reliance Industries Ltd", metric="Revenue from Operations")
        assert _passes_blocking(f1, f2) is True

    def test_entity_overlap_but_metric_mismatch_fails_blocking(self):
        f1 = _sample_fact(entity="Reliance Industries", metric="Net Revenue from Operations")
        f2 = _sample_fact(entity="Reliance Industries", metric="Employee Benefit Expenses")
        assert _passes_blocking(f1, f2) is False

    def test_metric_overlap_but_entity_mismatch_fails_blocking(self):
        f1 = _sample_fact(entity="Reliance Industries", metric="Revenue from Operations")
        f2 = _sample_fact(entity="Tata Motors Limited", metric="Revenue from Operations")
        assert _passes_blocking(f1, f2) is False


from fkl.domain.models import Fact, FactCandidate, ComparisonResult


class TestFix3MetricEquivalenceGate:
    def test_metric_equivalence_gate_rejects_spurious_corroboration(self):
        """If metrics are not equivalent, verdict must NOT be corroborates or likely_conflict."""
        cmp = ComparisonResult(
            left_fact_id="f1",
            right_fact_id="f2",
            metric_match=True,
            entity_match=True,
            metric_equivalent=False,
            period_match=True,
            scope_match=True,
            left_normalised=100.0,
            right_normalised=100.0,
            tolerance=0.5,
            value_within_tolerance=True,
            evidence_quality_left=0.9,
            evidence_quality_right=0.9,
        )
        verdict, code = decide(cmp)
        assert verdict == Verdict.INSUFFICIENT_CONTEXT
        assert code == ReasonCode.INSUFFICIENT_CONTEXT

    def test_metric_equivalence_allows_corroboration_when_equivalent(self):
        cmp = ComparisonResult(
            left_fact_id="f1",
            right_fact_id="f2",
            metric_match=True,
            entity_match=True,
            metric_equivalent=True,
            period_match=True,
            scope_match=True,
            left_normalised=100.0,
            right_normalised=100.0,
            tolerance=0.5,
            value_within_tolerance=True,
            evidence_quality_left=0.9,
            evidence_quality_right=0.9,
        )
        verdict, code = decide(cmp)
        assert verdict == Verdict.CORROBORATES
        assert code == ReasonCode.EXACT_MATCH


class TestFix6And7ParenthesesAndSkippedBlocks:
    def test_balance_parens_preserves_well_formed_and_fixes_truncated(self):
        assert _balance_parens("Year ended 31.03.2023 (Audited)") == "Year ended 31.03.2023 (Audited)"
        assert _balance_parens("Year ended 31.03.2023 (Audited") == "Year ended 31.03.2023 (Audited)"
        assert _balance_parens("Rs. in Lakhs (Except EPS (in Rs.)") == "Rs. in Lakhs (Except EPS (in Rs.))"


class TestRegressionTableExtraction:
    def test_four_column_financial_table_extraction(self):
        """Table with FY23, FY23 Pro forma, FY22, FY22 Restated produces table_rule facts with intact periods and canonical entity."""
        from fkl.domain.models import TableContext, BoundingBox, SourceBlock
        from fkl.pipeline.extract_table_facts import extract_table_facts
        from fkl.pipeline.ground_candidates import ground

        columns = [
            ["Year ended Mar 31, 2023"],
            ["Year ended Mar 31, 2023 (Pro forma)"],
            ["Year ended Mar 31, 2022"],
            ["Year ended Mar 31, 2022 (Restated)"],
        ]
        values = ["4,268.91", "4,401.20", "3,014.55", "3,058.10"]

        blocks = []
        for i, (col, val) in enumerate(zip(columns, values)):
            b = SourceBlock(
                id=f"blk_cell_{i}",
                document_id="doc_test",
                pdf_page_index=1,
                block_kind=BlockKind.TABLE_CELL,
                text=val,
                text_normalised=val,
                content_hash=f"hash_{i}",
                table_context=TableContext(
                    table_title="Consolidated Statement of Profit and Loss (Extract)",
                    row_header="Revenue from operations",
                    column_headers=col,
                    cell_value=val,
                    unit_note="Rs. million",
                ),
            )
            blocks.append(b)

        canonical = "SOLSTICE ROBOTICS LIMITED"
        candidates = extract_table_facts(blocks, canonical_entity=canonical)
        assert len(candidates) == 4

        facts = []
        for cand, block in candidates:
            res = ground(cand, block)
            assert res.accepted is True
            fact = _make_fact(cand, res, "run1", "doc_test", ExtractionMethod.TABLE_RULE, canonical_entity=canonical)
            facts.append(fact)

        for f in facts:
            assert f.extraction_method == ExtractionMethod.TABLE_RULE
            assert f.entity_canonical == "SOLSTICE ROBOTICS LIMITED"
            assert f.entity_raw == "SOLSTICE ROBOTICS LIMITED"
            assert f.period_raw is not None and len(f.period_raw) > 0
            assert f.metric_raw == "Revenue from operations"
            # Ensure balanced parentheses
            assert f.period_raw.count("(") == f.period_raw.count(")")

        # Verify qualifier scope
        pro_forma_fact = [f for f in facts if "Pro forma" in f.period_raw][0]
        assert pro_forma_fact.scope.get("qualifier") == "pro_forma"
        restated_fact = [f for f in facts if "Restated" in f.period_raw][0]
        assert restated_fact.scope.get("qualifier") == "restated"

    def test_table_bounding_box_suppression(self):
        """Text blocks overlapping table bounding boxes are suppressed."""
        from fkl.pipeline.parse_pdf import _block_overlaps_table

        table_bboxes = [(78.0, 180.0, 540.0, 290.0)]
        # Block inside table
        inside_bbox = (82.0, 200.0, 490.0, 215.0)
        assert _block_overlaps_table(inside_bbox, table_bboxes) is True

        # Block outside table (heading above)
        outside_above = (78.0, 60.0, 350.0, 85.0)
        assert _block_overlaps_table(outside_above, table_bboxes) is False

        # Block outside table (footnote below)
        outside_below = (78.0, 300.0, 500.0, 340.0)
        assert _block_overlaps_table(outside_below, table_bboxes) is False

    def test_table_like_text_detection_in_prose_extractor(self):
        """Raw tabular numeric rows are detected and excluded from prose LLM calls."""
        from fkl.pipeline.extract_text_facts import _is_table_like_text

        table_row = "Revenue from operations 18 4,268.91 4,401.20 3,014.55 3,058.10"
        assert _is_table_like_text(table_row) is True

        prose_sentence = "The company recorded a 14.2% growth in renewable power capacity during FY2023."
        assert _is_table_like_text(prose_sentence) is False


class TestFix8MetricGroundingAndRoleStatus:
    """R9 — All 12 regression tests for metric grounding and role_status disambiguation."""

    @pytest.fixture
    def rohan_block(self):
        from fkl.domain.normalisation import normalise_text
        from fkl.domain.models import SourceBlock
        text = "Mr. Rohan Sequeira (Independent Director, appointed August 19, 2022)."
        return SourceBlock(
            id="blk_rohan",
            document_id="doc_test",
            pdf_page_index=1,
            block_kind=BlockKind.PARAGRAPH,
            text=text,
            text_normalised=normalise_text(text),
            content_hash="hash_rohan",
        )

    @pytest.fixture
    def arjun_block(self):
        from fkl.domain.normalisation import normalise_text
        from fkl.domain.models import SourceBlock
        text = "Mr. Arjun Mehta, Independent Director, resigned from the Board effective June 30, 2022, citing other professional commitments."
        return SourceBlock(
            id="blk_arjun",
            document_id="doc_test",
            pdf_page_index=1,
            block_kind=BlockKind.PARAGRAPH,
            text=text,
            text_normalised=normalise_text(text),
            content_hash="hash_arjun",
        )

    @pytest.fixture
    def fin_block(self):
        from fkl.domain.normalisation import normalise_text
        from fkl.domain.models import SourceBlock
        text = "Revenue from operations for FY23 was INR 8,142 crore with EBITDA margin of 14%."
        return SourceBlock(
            id="blk_fin",
            document_id="doc_test",
            pdf_page_index=2,
            block_kind=BlockKind.PARAGRAPH,
            text=text,
            text_normalised=normalise_text(text),
            content_hash="hash_fin",
        )

    def test_1_exact_original_case_rejected(self, rohan_block):
        """1. Exact original case: metric_raw = 'Chief Executive Officer Appointment' -> rejected."""
        from fkl.pipeline.ground_candidates import ground
        cand = FactCandidate(
            entity_raw="Mr. Rohan Sequeira",
            metric_raw="Chief Executive Officer Appointment",
            value_raw="appointed",
            evidence_quote="appointed August 19, 2022",
        )
        res = ground(cand, rohan_block)
        assert res.accepted is False
        assert res.rejection_reason == "metric_label_not_grounded"

    def test_2_plausible_but_wrong_coo_rejected(self, rohan_block):
        """2. Plausible-but-wrong variant: metric_raw = 'Chief Operating Officer Appointment' -> rejected."""
        from fkl.pipeline.ground_candidates import ground
        cand = FactCandidate(
            entity_raw="Mr. Rohan Sequeira",
            metric_raw="Chief Operating Officer Appointment",
            value_raw="appointed",
            evidence_quote="appointed August 19, 2022",
        )
        res = ground(cand, rohan_block)
        assert res.accepted is False
        assert res.rejection_reason == "metric_label_not_grounded"

    def test_3_category_prefix_fabrication_rejected(self, rohan_block):
        """3. Category-prefix fabrication: metric_raw = 'Board Position: Chief Executive Officer' -> rejected."""
        from fkl.pipeline.ground_candidates import ground
        cand = FactCandidate(
            entity_raw="Mr. Rohan Sequeira",
            metric_raw="Board Position: Chief Executive Officer",
            value_raw="Independent Director",
            evidence_quote="Independent Director, appointed August 19, 2022",
        )
        res = ground(cand, rohan_block)
        assert res.accepted is False
        assert res.rejection_reason == "metric_label_not_grounded"

    def test_4_fabricated_financial_metric_rejected(self, fin_block):
        """4. Fabricated financial metric: metric_raw = 'Gross Profit Margin' -> rejected."""
        from fkl.pipeline.ground_candidates import ground
        cand = FactCandidate(
            entity_raw="Solstice Power Technologies",
            metric_raw="Gross Profit Margin",
            value_raw="14%",
            evidence_quote="EBITDA margin of 14%",
        )
        res = ground(cand, fin_block)
        assert res.accepted is False
        assert res.rejection_reason == "metric_label_not_grounded"

    def test_5_valid_event_noun_verb_pairing_accepted(self, arjun_block):
        """5. Valid event-noun/verb pairing: metric_raw = 'Board Resignation' -> accepted via root resign."""
        from fkl.pipeline.ground_candidates import ground
        cand = FactCandidate(
            entity_raw="Mr. Arjun Mehta",
            metric_raw="Board Resignation",
            value_raw="resigned",
            evidence_quote="resigned from the Board effective June 30, 2022",
        )
        res = ground(cand, arjun_block)
        assert res.accepted is True

    def test_6_valid_role_title_with_category_prefix_accepted(self, rohan_block):
        """6. Valid role title with category prefix: metric_raw = 'Board Position: Independent Director' -> accepted."""
        from fkl.pipeline.ground_candidates import ground
        cand = FactCandidate(
            entity_raw="Mr. Rohan Sequeira",
            metric_raw="Board Position: Independent Director",
            value_raw="Independent Director",
            evidence_quote="Independent Director, appointed August 19, 2022",
        )
        res = ground(cand, rohan_block)
        assert res.accepted is True

    def test_7_valid_role_title_no_colon_unconditional_filtering(self, arjun_block):
        """7. Valid role title with no colon: metric_raw = 'Board Position' -> accepted via unconditional taxonomy filtering."""
        from fkl.pipeline.ground_candidates import ground
        cand = FactCandidate(
            entity_raw="Mr. Arjun Mehta",
            metric_raw="Board Position",
            value_raw="Independent Director",
            evidence_quote="Independent Director, resigned from the Board",
        )
        res = ground(cand, arjun_block)
        assert res.accepted is True

    def test_8_zero_content_word_rejected(self, rohan_block):
        """8. Zero-content-word rejection: metric_raw = 'The of' -> rejected."""
        from fkl.pipeline.ground_candidates import ground
        cand = FactCandidate(
            entity_raw="Mr. Rohan Sequeira",
            metric_raw="The of",
            value_raw="appointed",
            evidence_quote="appointed",
        )
        res = ground(cand, rohan_block)
        assert res.accepted is False
        assert res.rejection_reason == "metric_label_not_grounded"

    def test_9_zero_content_word_taxonomy_only_rejected(self, rohan_block):
        """9. Zero-content-word rejection, taxonomy-only: metric_raw = 'Position' -> rejected."""
        from fkl.pipeline.ground_candidates import ground
        cand = FactCandidate(
            entity_raw="Mr. Rohan Sequeira",
            metric_raw="Position",
            value_raw="Independent Director",
            evidence_quote="Independent Director",
        )
        res = ground(cand, rohan_block)
        assert res.accepted is False
        assert res.rejection_reason == "metric_label_not_grounded"

    def test_10_invalid_category_prefix_rejected(self, rohan_block):
        """10. Invalid category prefix: 'Chief Executive Officer Position: Independent Director' -> rejected."""
        from fkl.pipeline.ground_candidates import ground
        cand = FactCandidate(
            entity_raw="Mr. Rohan Sequeira",
            metric_raw="Chief Executive Officer Position: Independent Director",
            value_raw="Independent Director",
            evidence_quote="Independent Director, appointed August 19, 2022",
        )
        res = ground(cand, rohan_block)
        assert res.accepted is False
        assert res.rejection_reason == "metric_label_not_grounded"

    def test_11_role_status_classification_reconciles(self):
        """11. Role-status classification: active vs resigned with equivalent metric -> RECONCILES / DIFFERENT_SCOPE."""
        from fkl.domain.classification import classify, decide
        fact_active = _sample_fact(
            id="f_act",
            entity="Mr. Arjun Mehta",
            metric="Board Position: Independent Director",
            value="Independent Director",
        )
        fact_active.role_status = "active"
        fact_active.scope = {"role_status": "active"}

        fact_resigned = _sample_fact(
            id="f_res",
            entity="Mr. Arjun Mehta",
            metric="Board Position: Independent Director",
            value="Independent Director",
        )
        fact_resigned.role_status = "resigned"
        fact_resigned.scope = {"role_status": "resigned"}

        cmp = classify(fact_active, fact_resigned)
        verdict, reason = decide(cmp)
        assert verdict == Verdict.RECONCILES
        assert reason == ReasonCode.DIFFERENT_SCOPE

    def test_12_metric_mismatch_classification_insufficient(self):
        """12. Metric-mismatch classification: Board Position vs Board Resignation -> INSUFFICIENT_CONTEXT."""
        from fkl.domain.classification import classify, decide
        fact_pos = _sample_fact(
            id="f_pos",
            entity="Mr. Arjun Mehta",
            metric="Board Position",
            value="Independent Director",
        )
        fact_pos.role_status = "active"

        fact_res = _sample_fact(
            id="f_res2",
            entity="Mr. Arjun Mehta",
            metric="Board Resignation",
            value="resigned",
        )
        fact_res.role_status = "resigned"

        cmp = classify(fact_pos, fact_res)
        verdict, reason = decide(cmp)
        assert verdict == Verdict.INSUFFICIENT_CONTEXT
        assert reason == ReasonCode.INSUFFICIENT_CONTEXT

    def test_consolidation_of_arjun_mehta_fragments(self, arjun_block):
        """Verify R7 consolidation pass merges event fact and position fact for Arjun Mehta."""
        from fkl.pipeline.deduplicate import deduplicate_candidates
        f_event = _sample_fact(
            id="f_ev",
            entity="Mr. Arjun Mehta",
            metric="Board Resignation",
            value="resigned",
        )
        f_event.evidence_block_id = arjun_block.id
        f_event.role_status = "resigned"
        f_event.period_raw = "June 30, 2022"

        f_pos = _sample_fact(
            id="f_pos",
            entity="Mr. Arjun Mehta",
            metric="Board Position",
            value="Independent Director",
        )
        f_pos.evidence_block_id = arjun_block.id
        f_pos.role_status = "resigned"
        f_pos.period_raw = "effective June 30, 2022"

        consolidated = deduplicate_candidates([f_event, f_pos])
        assert len(consolidated) == 1
        merged = consolidated[0]
        assert merged.entity_raw == "Mr. Arjun Mehta"
        assert merged.metric_raw == "Board Position: Independent Director"
        assert merged.value_raw == "Independent Director"
        assert merged.role_status == "resigned"
        assert merged.period_raw == "effective June 30, 2022"
        assert merged.scope.get("role_status") == "resigned"
        assert merged.qualifiers.get("role_status") == "resigned"
