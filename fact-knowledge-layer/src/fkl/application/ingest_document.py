"""Ingestion orchestration use case.

Single entry point for the full pipeline: parse → extract → ground → normalise → compare.
Every stage is wrapped with structured logs and timings.
On any failure: mark run/document failed, retain diagnostics, never claim partial completion.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fkl.config import get_settings
from fkl.domain.enums import BlockKind, ExtractionMethod, ReviewState, UnitDimension, ValueKind
from fkl.domain.models import Fact, FactCandidate, IngestionSummary, NormalisationStep, SourceBlock
from fkl.domain.normalisation import detect_fy_end_month, detect_scale, normalise_value, parse_numeric, parse_period
from fkl.persistence import database, repositories
from fkl.pipeline.build_relationships import build_relationships
from fkl.pipeline.extract_table_facts import extract_table_facts
from fkl.pipeline.extract_text_facts import extract_text_facts
from fkl.pipeline.ground_candidates import ground
from fkl.pipeline.parse_pdf import parse_pdf

logger = logging.getLogger(__name__)


def _get_provider():
    """Instantiate LLM provider from settings."""
    settings = get_settings()
    if settings.llm_provider == "gemini":
        from fkl.providers.gemini_provider import GeminiProvider
        return GeminiProvider(api_key=settings.gemini_api_key, model_name=settings.llm_model)
    else:
        from fkl.providers.fake_llm import FakeLLMProvider
        return FakeLLMProvider()


def _make_fact(
    candidate,
    grounding,
    run_id: str,
    document_id: str,
    extraction_method: ExtractionMethod,
    canonical_entity: str | None = None,
    doc_context: str | None = None,
) -> Fact:
    """Build an immutable Fact from an accepted candidate + grounding result."""
    numeric = parse_numeric(candidate.value_raw)
    unit_context = f"{candidate.unit_raw or ''} {candidate.period_raw or ''}".lower()
    scale = detect_scale(unit_context)

    norm = normalise_value(candidate.value_raw, candidate.unit_raw, scale, doc_context=doc_context)

    # Determine value kind
    if numeric is not None:
        vkind = ValueKind.NUMERIC
    else:
        vkind = ValueKind.TEXT

    # Unit dimension
    u = (candidate.unit_raw or "").lower()
    if "%" in u or "percent" in u:
        udim = UnitDimension.PERCENTAGE
    elif any(c in u for c in ["₹", "inr", "rs", "$", "usd", "crore", "million", "lakh"]):
        udim = UnitDimension.CURRENCY
    else:
        udim = UnitDimension.UNKNOWN

    # Period
    period_info = parse_period(
        f"{candidate.period_raw or ''} {candidate.unit_raw or ''}",
        doc_context=doc_context,
    )

    scope = candidate.scope or {}

    ent_raw = (candidate.entity_raw or "").strip()
    _GENERIC_ENTITIES = {
        "the company", "company", "the group", "group",
        "the corporation", "corporation", "the bank", "the firm", "entity", ""
    }
    _TABLE_TITLE_INDICATORS = (
        "statement of", "balance sheet", "profit and loss", "profit & loss",
        "cash flow", "financial results", "income statement", "comprehensive income",
        "extract", "notes to", "particulars", "annual report", "unaudited", "audited"
    )
    is_table_caption = any(ind in ent_raw.lower() for ind in _TABLE_TITLE_INDICATORS)
    is_generic = ent_raw.lower() in _GENERIC_ENTITIES

    if canonical_entity and (extraction_method == ExtractionMethod.TABLE_RULE or is_table_caption or is_generic):
        entity_canonical = canonical_entity
        entity_raw = canonical_entity
    elif canonical_entity and ent_raw.lower() == canonical_entity.lower():
        entity_canonical = canonical_entity
        entity_raw = canonical_entity
    elif canonical_entity:
        entity_canonical = canonical_entity
        entity_raw = ent_raw if ent_raw else canonical_entity
    else:
        entity_canonical = ent_raw if ent_raw else "Entity"
        entity_raw = ent_raw or "Entity"

    # Wire confidence threshold to review state (Fix 4)
    review_state = ReviewState.NEEDS_REVIEW if grounding.confidence < 0.65 else ReviewState.ACCEPTED

    # Wire role status for governance/personnel facts (R6)
    from fkl.pipeline.deduplicate import detect_role_status
    role_status = getattr(candidate, "role_status", None) or detect_role_status(candidate)
    qualifiers = {}
    if period_info.get("period_convention") == "unknown":
        qualifiers["period_convention"] = "unknown"
    if role_status:
        scope["role_status"] = role_status
        qualifiers["role_status"] = role_status
    if scope.get("unrecognized_qualifier"):
        qualifiers["unrecognized_qualifier"] = scope["unrecognized_qualifier"]

    return Fact(
        id=f"fact_{uuid.uuid4().hex[:14]}",
        document_id=document_id,
        ingestion_run_id=run_id,
        evidence_block_id=grounding.evidence_block_id,
        entity_raw=entity_raw,
        entity_canonical=entity_canonical,
        metric_raw=candidate.metric_raw,
        metric_key=candidate.metric_raw.lower().strip(),
        value_raw=candidate.value_raw,
        numeric_value=numeric,
        value_kind=vkind,
        unit_raw=candidate.unit_raw,
        unit_dimension=udim,
        scale_raw=scale or None,
        normalised_value=norm.normalised_value,
        normalised_unit=norm.normalised_unit,
        period_raw=candidate.period_raw,
        period_start=period_info.get("start"),
        period_end=period_info.get("end"),
        role_status=role_status,
        scope=scope,
        qualifiers=qualifiers,
        extraction_method=extraction_method,
        confidence=grounding.confidence,
        review_state=review_state,
        normalisation_provenance=norm.steps,
        created_at=datetime.now(timezone.utc),
    )


def ingest_document(document_id: str) -> IngestionSummary:
    """Full ingestion pipeline for a single document. Called from background task."""
    settings = get_settings()
    t_start = time.monotonic()
    warnings: list[str] = []

    db = database.get_session()
    try:
        doc = repositories.get_document(db, document_id)
        if not doc:
            raise RuntimeError(f"Document {document_id} not found in database")

        pdf_path = Path(doc.stored_path)
        if not pdf_path.exists():
            raise RuntimeError(f"Stored PDF not found at {pdf_path}")

        # Create ingestion run
        provider = _get_provider()
        model_name = settings.llm_model if settings.llm_provider != "fake" else None
        run = repositories.create_run(
            db, f"run_{uuid.uuid4().hex[:12]}", document_id,
            settings.pipeline_version, model_name
        )
        run_id = run.id

        repositories.update_document_status(db, document_id, "processing")

        # --- Stage 1: Parse PDF ---
        logger.info("[%s] Stage 1: parsing PDF", document_id)
        try:
            blocks, page_count, parse_warnings, canonical_entity = parse_pdf(document_id, pdf_path)
            warnings.extend(parse_warnings)
        except Exception as e:
            logger.error("[%s] Parse failed: %s", document_id, e)
            repositories.update_document_status(db, document_id, "failed", error_message=str(e))
            return IngestionSummary(
                run_id=run_id, document_id=document_id,
                facts_created=0, facts_rejected=0, relationships_created=0,
                warnings=[str(e)],
            )

        repositories.update_document_status(
            db, document_id, "processing", page_count=page_count, canonical_entity=canonical_entity
        )
        repositories.insert_blocks(db, blocks)
        logger.info(
            "[%s] Parsed %d blocks from %d pages (canonical entity: %s)",
            document_id, len(blocks), page_count, canonical_entity
        )

        # Extract doc_context for fiscal year convention from heading and paragraph blocks (first match stop)
        doc_context: str | None = None
        for b in blocks:
            if b.block_kind in (BlockKind.HEADING, BlockKind.PARAGRAPH):
                if detect_fy_end_month(b.text):
                    doc_context = b.text
                    break

        # --- Stage 2: Extract candidates ---
        logger.info("[%s] Stage 2: extracting candidates", document_id)
        text_candidates, text_stats = extract_text_facts(
            blocks, provider, canonical_entity=canonical_entity
        )
        table_candidates = extract_table_facts(
            blocks, canonical_entity=canonical_entity, stats=text_stats
        )
        blocks_skipped_due_to_cap = text_stats.prose_blocks_skipped_due_to_cap

        # Route chart/figure blocks to vision extraction if provider supports it (Task B)
        chart_candidates: list[tuple[FactCandidate, SourceBlock, ExtractionMethod]] = []
        for b in blocks:
            if b.block_kind in (BlockKind.CHART, BlockKind.IMAGE):
                if hasattr(provider, "extract_from_image"):
                    try:
                        page_heading = next(
                            (blk.text[:200] for blk in blocks
                             if blk.block_kind == BlockKind.HEADING and blk.pdf_page_index == b.pdf_page_index),
                            "Chart / Figure",
                        )
                        visual_candidates = provider.extract_from_image(
                            block=b,
                            document_context=page_heading,
                            canonical_entity=canonical_entity,
                        )
                        for vc in visual_candidates:
                            chart_candidates.append((vc, b, ExtractionMethod.TEXT_LLM))
                        if not visual_candidates:
                            logger.debug("[%s] No facts extracted from visual block %s", document_id, b.id)
                    except Exception as ve:
                        logger.warning("[%s] Vision extraction failed for block %s: %s", document_id, b.id, ve)
                else:
                    # Provider doesn't support vision: audit block as visual_only rejection
                    logger.debug("[%s] Provider has no extract_from_image — skipping chart block %s", document_id, b.id)

        all_candidates = (
            [(c, b, ExtractionMethod.TABLE_RULE) for c, b in table_candidates]
            + [(c, b, ExtractionMethod.TEXT_LLM) for c, b in text_candidates]
            + chart_candidates
        )

        logger.info(
            "[%s] Candidates: %d table, %d prose, %d visual/chart",
            document_id, len(table_candidates), len(text_candidates), len(chart_candidates)
        )

        # --- Stage 3: Ground candidates ---
        logger.info("[%s] Stage 3: grounding", document_id)
        accepted_facts: list[Fact] = []
        rejected_audit: list[dict] = []

        for candidate, block, method in all_candidates:
            result = ground(candidate, block)
            if result.accepted:
                fact = _make_fact(
                    candidate, result, run_id, document_id, method,
                    canonical_entity=canonical_entity, doc_context=doc_context
                )
                accepted_facts.append(fact)
            else:
                rejected_audit.append({
                    "id": f"aud_{uuid.uuid4().hex[:12]}",
                    "document_id": document_id,
                    "ingestion_run_id": run_id,
                    "evidence_block_id": block.id,
                    "entity_raw": candidate.entity_raw,
                    "metric_raw": candidate.metric_raw,
                    "value_raw": candidate.value_raw,
                    "rejection_reason": result.rejection_reason or "unknown",
                    "extraction_method": method.value,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })

        logger.info(
            "[%s] Grounding: %d accepted, %d rejected",
            document_id, len(accepted_facts), len(rejected_audit)
        )

        # --- Stage 4: Deduplicate & Persist facts ---
        from fkl.pipeline.deduplicate import deduplicate_candidates
        if accepted_facts:
            accepted_facts = deduplicate_candidates(accepted_facts)
            repositories.insert_facts(db, accepted_facts)
        if rejected_audit:
            repositories.insert_candidate_audit(db, rejected_audit)

        # Document-level entity consistency check
        distinct_entities = set(f.entity_canonical for f in accepted_facts if f.entity_canonical)
        if len(distinct_entities) > 2:
            warn_msg = (
                f"Document contains {len(distinct_entities)} distinct canonical entities: {distinct_entities}. "
                "Possible inconsistent entity attribution."
            )
            logger.warning("[%s] %s", document_id, warn_msg)
            warnings.append(warn_msg)

        # --- Stage 5: Build relationships (incremental) ---
        logger.info("[%s] Stage 5: building relationships", document_id)
        relationships: list[Relationship] = []
        insufficient_context_count = 0
        relationships_error: str | None = None

        try:
            existing_rows = repositories.get_facts_excluding_document(db, document_id)
            insufficient_counter = [0]
            relationships = build_relationships(
                accepted_facts,
                existing_rows,
                run_id,
                metric_provider=provider,
                insufficient_context_counter=insufficient_counter,
                stats=text_stats,
            )
            insufficient_context_count = insufficient_counter[0]

            if relationships:
                repositories.insert_relationships(db, relationships)

            logger.info(
                "[%s] Relationships: %d created (%d insufficient context skipped)",
                document_id, len(relationships), insufficient_context_count
            )
        except Exception as rel_err:
            logger.exception("[%s] Stage 5 relationship building failed: %s", document_id, rel_err)
            relationships_error = str(rel_err)
            warnings.append(f"Relationship building failed: {rel_err}")

        # --- Complete ---
        repositories.complete_run(
            db, run_id,
            facts_created=len(accepted_facts),
            facts_rejected=len(rejected_audit),
            relationships_created=len(relationships),
            insufficient_context_count=insufficient_context_count,
            blocks_skipped_due_to_cap=blocks_skipped_due_to_cap,
            stats=text_stats,
            relationships_error=relationships_error,
        )
        final_status = "relationships_failed" if relationships_error else "complete"
        repositories.update_document_status(
            db, document_id, final_status,
            error_message=relationships_error if relationships_error else None,
        )
        duration = time.monotonic() - t_start
        logger.info("[%s] Ingestion complete (status: %s) in %.1fs", document_id, final_status, duration)

        return IngestionSummary(
            run_id=run_id,
            document_id=document_id,
            facts_created=len(accepted_facts),
            facts_rejected=len(rejected_audit),
            relationships_created=len(relationships),
            warnings=warnings,
            duration_seconds=round(duration, 2),
            stats=text_stats,
        )

    except Exception as e:
        logger.exception("[%s] Ingestion pipeline error: %s", document_id, e)
        try:
            fc = len(accepted_facts) if "accepted_facts" in locals() else 0
            fr = len(rejected_audit) if "rejected_audit" in locals() else 0
            repositories.complete_run(db, run_id, fc, fr, 0)
        except Exception:
            pass
        repositories.update_document_status(db, document_id, "failed", error_message=str(e))
        raise
    finally:
        db.close()
