"""Temporary Stage-2 diagnostic.

Run as:
  py -3.11 scripts/diagnose_stage2.py <document_id>

Prints:
- block kind distribution from parse_pdf
- what extract_text_facts() returns (count, first 3 candidates)
- what extract_table_facts() returns (count, first 3)
- the full all_candidates list before grounding
- for each accepted fact: method, entity, metric, value
"""

import sys
import os
import logging
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s %(name)s: %(message)s',
)

def main():
    if len(sys.argv) < 2:
        print("Usage: py -3.11 scripts/diagnose_stage2.py <document_id>")
        sys.exit(1)

    document_id = sys.argv[1]

    from fkl.config import get_settings
    from fkl.persistence import database, repositories
    from fkl.pipeline.parse_pdf import parse_pdf
    from fkl.pipeline.extract_text_facts import extract_text_facts
    from fkl.pipeline.extract_table_facts import extract_table_facts
    from fkl.pipeline.ground_candidates import ground
    from fkl.domain.enums import BlockKind, ExtractionMethod
    from pathlib import Path
    from collections import Counter

    settings = get_settings()
    db = database.get_session()

    try:
        doc = repositories.get_document(db, document_id)
        if not doc:
            print(f"ERROR: Document {document_id} not found")
            sys.exit(1)

        print(f"\n{'='*60}")
        print(f"Document: {doc.original_filename}")
        print(f"Status:   {doc.status}")
        print(f"{'='*60}")

        pdf_path = Path(doc.stored_path)
        if not pdf_path.exists():
            print(f"ERROR: PDF not found at {pdf_path}")
            sys.exit(1)

        # ── Stage 1: Parse ────────────────────────────────────────
        print("\n[Stage 1] Parsing PDF...")
        blocks, page_count, parse_warnings, canonical_entity = parse_pdf(document_id, pdf_path)

        kind_counts = Counter(b.block_kind.value for b in blocks)
        print(f"  page_count      = {page_count}")
        print(f"  canonical_entity= {canonical_entity!r}")
        print(f"  total blocks    = {len(blocks)}")
        print(f"  block kinds     = {dict(kind_counts)}")
        if parse_warnings:
            print(f"  parse_warnings  = {parse_warnings[:3]}")

        # Sample PARAGRAPH and HEADING blocks
        para_blocks = [b for b in blocks if b.block_kind == BlockKind.PARAGRAPH]
        head_blocks = [b for b in blocks if b.block_kind == BlockKind.HEADING]
        print(f"\n  PARAGRAPH blocks (total {len(para_blocks)}) — first 3 texts:")
        for b in para_blocks[:3]:
            print(f"    [{b.pdf_page_index}] {b.text[:100]!r}")
        print(f"\n  HEADING blocks (total {len(head_blocks)}) — first 3 texts:")
        for b in head_blocks[:3]:
            print(f"    [{b.pdf_page_index}] {b.text[:100]!r}")

        # ── Stage 2a: extract_text_facts ──────────────────────────
        print(f"\n[Stage 2a] Calling extract_text_facts()...")

        # Use FakeLLMProvider so we don't burn API calls
        from fkl.providers.fake_llm import FakeLLMProvider
        fake_provider = FakeLLMProvider()

        text_candidates, text_stats = extract_text_facts(
            blocks, fake_provider, canonical_entity=canonical_entity
        )
        print(f"  text_candidates count = {len(text_candidates)}")
        print(f"  prose_blocks_total    = {text_stats.prose_blocks_total}")
        print(f"  prose_blocks_llm_called = {text_stats.prose_blocks_llm_called}")
        print(f"  skipped_due_to_cap    = {text_stats.prose_blocks_skipped_due_to_cap}")
        print(f"  sections_total        = {text_stats.sections_total}")
        print(f"  sections_covered      = {text_stats.sections_covered}")

        if text_candidates:
            print(f"\n  First 3 TEXT candidates:")
            for cand, blk in text_candidates[:3]:
                print(f"    entity={cand.entity_raw!r} metric={cand.metric_raw!r} value={cand.value_raw!r}")
                print(f"    block_kind={blk.block_kind.value} page={blk.pdf_page_index}")
        else:
            print("  *** NO text candidates returned ***")

        # ── Stage 2b: extract_table_facts ─────────────────────────
        print(f"\n[Stage 2b] Calling extract_table_facts()...")
        table_candidates = extract_table_facts(
            blocks, canonical_entity=canonical_entity, stats=text_stats
        )
        print(f"  table_candidates count = {len(table_candidates)}")
        if table_candidates:
            print(f"\n  First 3 TABLE candidates:")
            for cand, blk in table_candidates[:3]:
                print(f"    entity={cand.entity_raw!r} metric={cand.metric_raw!r} value={cand.value_raw!r}")

        # ── all_candidates before grounding ───────────────────────
        all_candidates = (
            [(c, b, ExtractionMethod.TABLE_RULE) for c, b in table_candidates]
            + [(c, b, ExtractionMethod.TEXT_LLM) for c, b in text_candidates]
        )
        print(f"\n[Pre-Grounding] all_candidates = {len(all_candidates)}")
        method_dist = Counter(m.value for _, _, m in all_candidates)
        print(f"  by method: {dict(method_dist)}")

        # ── Stage 3: Ground ───────────────────────────────────────
        print(f"\n[Stage 3] Grounding {len(all_candidates)} candidates...")
        accepted = []
        rejected = []
        for candidate, block, method in all_candidates:
            result = ground(candidate, block)
            if result.accepted:
                accepted.append((candidate, method, result))
            else:
                rejected.append((candidate, method, result))

        print(f"  accepted: {len(accepted)}")
        print(f"  rejected: {len(rejected)}")

        method_accepted = Counter(m.value for _, m, _ in accepted)
        print(f"  accepted by method: {dict(method_accepted)}")

        if accepted:
            print(f"\n  First 5 ACCEPTED facts:")
            for cand, method, res in accepted[:5]:
                print(f"    [{method.value}] entity={cand.entity_raw!r} metric={cand.metric_raw!r} value={cand.value_raw!r} conf={res.confidence:.2f}")

        if rejected[:5]:
            print(f"\n  First 5 REJECTED candidates:")
            for cand, method, res in rejected[:5]:
                print(f"    [{method.value}] entity={cand.entity_raw!r} metric={cand.metric_raw!r} reason={res.rejection_reason!r}")

        print(f"\n{'='*60}")
        print("DIAGNOSIS COMPLETE")
        print(f"{'='*60}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
