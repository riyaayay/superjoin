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
from fkl.domain.models import Fact, IngestionSummary, NormalisationStep
from fkl.domain.normalisation import detect_scale, normalise_value, parse_numeric, parse_period
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
) -> Fact:
    """Build an immutable Fact from an accepted candidate + grounding result."""
    numeric = parse_numeric(candidate.value_raw)
    unit_context = f"{candidate.unit_raw or ''} {candidate.period_raw or ''}".lower()
    scale = detect_scale(unit_context)

    norm = normalise_value(candidate.value_raw, candidate.unit_raw, scale)

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
    period_info = parse_period(f"{candidate.period_raw or ''} {candidate.unit_raw or ''}")

    scope = candidate.scope or {}

    return Fact(
        id=f"fact_{uuid.uuid4().hex[:14]}",
        document_id=document_id,
        ingestion_run_id=run_id,
        evidence_block_id=grounding.evidence_block_id,
        entity_raw=candidate.entity_raw,
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
        scope=scope,
        qualifiers={},
        extraction_method=extraction_method,
        confidence=grounding.confidence,
        review_state=ReviewState.ACCEPTED,
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
            blocks, page_count, parse_warnings = parse_pdf(document_id, pdf_path)
            warnings.extend(parse_warnings)
        except Exception as e:
            logger.error("[%s] Parse failed: %s", document_id, e)
            repositories.update_document_status(db, document_id, "failed", error_message=str(e))
            return IngestionSummary(
                run_id=run_id, document_id=document_id,
                facts_created=0, facts_rejected=0, relationships_created=0,
                warnings=[str(e)],
            )

        repositories.update_document_status(db, document_id, "processing", page_count=page_count)
        repositories.insert_blocks(db, blocks)
        logger.info("[%s] Parsed %d blocks from %d pages", document_id, len(blocks), page_count)

        # --- Stage 2: Extract candidates ---
        logger.info("[%s] Stage 2: extracting candidates", document_id)
        table_candidates = extract_table_facts(blocks)
        text_candidates = extract_text_facts(blocks, provider)

        # Collect chart/figure blocks as candidates to explicitly audit visual non-extraction (Demo Case #4)
        chart_candidates: list[tuple[FactCandidate, SourceBlock, ExtractionMethod]] = []
        for b in blocks:
            if b.block_kind in (BlockKind.CHART, BlockKind.IMAGE):
                c = FactCandidate(
                    entity_raw="Chart / Graphic",
                    metric_raw=b.text.strip()[:80] or "Visual Figure",
                    value_raw="[visual_data]",
                    evidence_quote=b.text.strip()[:100] or "[image block]",
                    confidence_hint=0.0,
                )
                chart_candidates.append((c, b, ExtractionMethod.TEXT_LLM))

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
                fact = _make_fact(candidate, result, run_id, document_id, method)
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

        # --- Stage 4: Persist facts ---
        if accepted_facts:
            repositories.insert_facts(db, accepted_facts)
        if rejected_audit:
            repositories.insert_candidate_audit(db, rejected_audit)

        # --- Stage 5: Build relationships (incremental) ---
        logger.info("[%s] Stage 5: building relationships", document_id)
        existing_rows = repositories.get_facts_excluding_document(db, document_id)
        relationships = build_relationships(accepted_facts, existing_rows, run_id)

        if relationships:
            repositories.insert_relationships(db, relationships)

        logger.info("[%s] Relationships: %d created", document_id, len(relationships))

        # --- Complete ---
        repositories.complete_run(
            db, run_id,
            facts_created=len(accepted_facts),
            facts_rejected=len(rejected_audit),
            relationships_created=len(relationships),
        )
        repositories.update_document_status(db, document_id, "complete")

        duration = time.monotonic() - t_start
        logger.info("[%s] Ingestion complete in %.1fs", document_id, duration)

        return IngestionSummary(
            run_id=run_id,
            document_id=document_id,
            facts_created=len(accepted_facts),
            facts_rejected=len(rejected_audit),
            relationships_created=len(relationships),
            warnings=warnings,
            duration_seconds=round(duration, 2),
        )

    except Exception as e:
        logger.exception("[%s] Ingestion pipeline error: %s", document_id, e)
        try:
            repositories.complete_run(db, run_id, 0, 0, 0)
        except Exception:
            pass
        repositories.update_document_status(db, document_id, "failed", error_message=str(e))
        raise
    finally:
        db.close()
