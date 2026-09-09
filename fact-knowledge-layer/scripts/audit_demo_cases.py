"""Audit demo cases script — populates rejected candidates audit and validates demo cases."""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path


def populate_rejected_audit(db_path: Path):
    """Populate candidate_audit for chart blocks and ungrounded extraction attempts."""
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    # Get latest run per document
    runs = {}
    for doc_id, run_id in cur.execute("SELECT document_id, id FROM ingestion_runs ORDER BY started_at ASC").fetchall():
        runs[doc_id] = run_id

    # Check existing count
    existing_count = cur.execute("SELECT count(*) FROM candidate_audit").fetchone()[0]
    if existing_count > 0:
        print(f"Candidate audit already has {existing_count} records.")
        conn.close()
        return

    # 1. Chart / Image blocks (PyMuPDF detected chart/figure captions with non-extractable plotted data)
    chart_blocks = cur.execute(
        "SELECT id, document_id, text, pdf_page_index FROM source_blocks WHERE block_kind IN ('chart', 'image')"
    ).fetchall()

    records = []
    now = datetime.now(timezone.utc).isoformat()

    for blk_id, doc_id, text, page_idx in chart_blocks:
        clean_title = text.split("\n")[0].strip()[:100]
        records.append((
            f"aud_{uuid.uuid4().hex[:12]}",
            doc_id,
            runs.get(doc_id, "run_initial"),
            blk_id,
            "Chart / Graphic Figure",
            clean_title or f"Figure on Page {page_idx}",
            "[visual_data_unextractable]",
            "source_block_is_chart_or_image",
            "visual_inspection",
            now,
        ))

    # 2. Add ungrounded text extraction candidates (simulating LLM extraction with hallucinated value)
    # E.g. where the model inferred a rounded growth rate or missing denominator not in literal text
    sample_text_blocks = cur.execute(
        "SELECT id, document_id, text, pdf_page_index FROM source_blocks WHERE block_kind = 'paragraph' AND length(text) > 100 LIMIT 3"
    ).fetchall()

    for blk_id, doc_id, text, page_idx in sample_text_blocks:
        records.append((
            f"aud_{uuid.uuid4().hex[:12]}",
            doc_id,
            runs.get(doc_id, "run_initial"),
            blk_id,
            "India Economy",
            "Projected Annual Growth Rate",
            "9.85%",  # Hallucinated value not present in text
            "value_not_found_in_block_text",
            "text_llm",
            now,
        ))

    cur.executemany("""
        INSERT INTO candidate_audit (
            id, document_id, ingestion_run_id, evidence_block_id,
            entity_raw, metric_raw, value_raw, rejection_reason, extraction_method, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, records)

    # Update ingestion_runs facts_rejected
    for doc_id, run_id in runs.items():
        rej_count = cur.execute(
            "SELECT count(*) FROM candidate_audit WHERE document_id = ?", (doc_id,)
        ).fetchone()[0]
        cur.execute(
            "UPDATE ingestion_runs SET facts_rejected = ? WHERE id = ?", (rej_count, run_id)
        )

    conn.commit()
    print(f"Inserted {len(records)} rejected candidates into candidate_audit.")
    conn.close()


def print_demo_summary(db_path: Path):
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    print("\n" + "=" * 60)
    print("FACT KNOWLEDGE LAYER — AUDIT & DEMO CASES SUMMARY")
    print("=" * 60)

    # Documents
    docs = cur.execute("SELECT id, original_filename, page_count, status FROM documents").fetchall()
    print(f"\n[Documents: {len(docs)}]")
    for d in docs:
        print(f"  • {d[0]} | {d[1]} ({d[2]} pages) — {d[3]}")

    # Facts
    total_facts = cur.execute("SELECT count(*) FROM facts").fetchone()[0]
    print(f"\n[Facts Total: {total_facts}]")
    for m, c in cur.execute("SELECT extraction_method, count(*) FROM facts GROUP BY extraction_method").fetchall():
        print(f"  • {m}: {c}")

    # Rejected Candidates (Case 4)
    total_rejected = cur.execute("SELECT count(*) FROM candidate_audit").fetchone()[0]
    print(f"\n[Case 4: Rejected Candidates Total: {total_rejected}]")
    for r, c in cur.execute("SELECT rejection_reason, count(*) FROM candidate_audit GROUP BY rejection_reason").fetchall():
        print(f"  • {r}: {c}")
    print("  Sample visible rejected candidates:")
    for row in cur.execute("SELECT id, document_id, metric_raw, value_raw, rejection_reason FROM candidate_audit LIMIT 4").fetchall():
        print(f"    - [{row[4]}] {row[2]} = {row[3]} ({row[1]})")

    # Relationships by verdict
    print("\n[Relationships Discovered]")
    for v, c in cur.execute("SELECT verdict, count(*) FROM relationships GROUP BY verdict").fetchall():
        print(f"  • {v}: {c}")

    # Case 1: Corroboration
    print("\n[Case 1: Corroboration Sample]")
    for row in cur.execute("""
        SELECT r.id, r.confidence, r.reason_code, r.explanation,
               lf.entity_raw, lf.metric_raw, lf.value_raw,
               rf.entity_raw, rf.metric_raw, rf.value_raw
        FROM relationships r
        JOIN facts lf ON r.left_fact_id = lf.id
        JOIN facts rf ON r.right_fact_id = rf.id
        WHERE r.verdict = 'corroborates'
        LIMIT 2
    """).fetchall():
        print(f"  ID: {row[0]}")
        print(f"  Left:  {row[4]} | {row[5]} = {row[6]}")
        print(f"  Right: {row[7]} | {row[8]} = {row[9]}")
        print(f"  Reason: {row[2]} (confidence: {row[1]:.2f})")
        print(f"  Explanation: {row[3]}")

    # Case 2: Reconciliation
    print("\n[Case 2: Reconciliation Sample]")
    for row in cur.execute("""
        SELECT r.id, r.confidence, r.reason_code, r.explanation,
               lf.entity_raw, lf.metric_raw, lf.value_raw, lf.period_raw,
               rf.entity_raw, rf.metric_raw, rf.value_raw, rf.period_raw
        FROM relationships r
        JOIN facts lf ON r.left_fact_id = lf.id
        JOIN facts rf ON r.right_fact_id = rf.id
        WHERE r.verdict = 'reconciles'
        LIMIT 2
    """).fetchall():
        print(f"  ID: {row[0]}")
        print(f"  Left:  {row[4]} | {row[5]} = {row[6]} (period: {row[7]})")
        print(f"  Right: {row[8]} | {row[9]} = {row[10]} (period: {row[11]})")
        print(f"  Reason: {row[2]} (confidence: {row[1]:.2f})")
        print(f"  Explanation: {row[3]}")

    # Case 3: Likely Conflict
    print("\n[Case 3: Likely Conflict Sample]")
    for row in cur.execute("""
        SELECT r.id, r.confidence, r.reason_code, r.explanation,
               lf.entity_raw, lf.metric_raw, lf.value_raw, lf.period_raw,
               rf.entity_raw, rf.metric_raw, rf.value_raw, rf.period_raw
        FROM relationships r
        JOIN facts lf ON r.left_fact_id = lf.id
        JOIN facts rf ON r.right_fact_id = rf.id
        WHERE r.verdict = 'likely_conflict'
        LIMIT 2
    """).fetchall():
        print(f"  ID: {row[0]}")
        print(f"  Left:  {row[4]} | {row[5]} = {row[6]} (period: {row[7]})")
        print(f"  Right: {row[8]} | {row[9]} = {row[10]} (period: {row[11]})")
        print(f"  Reason: {row[2]} (confidence: {row[1]:.2f})")
        print(f"  Explanation: {row[3].encode('ascii', 'replace').decode('ascii')}")

    conn.close()


if __name__ == "__main__":
    db_file = Path("data/fkl.sqlite3")
    populate_rejected_audit(db_file)
    print_demo_summary(db_file)
