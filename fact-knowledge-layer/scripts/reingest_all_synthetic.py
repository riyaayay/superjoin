"""Re-ingest all 4 synthetic documents and audit extraction/grounding results."""

import sys
import time
from pathlib import Path

sys.path.insert(0, "src")

from fkl.persistence import database, repositories
from fkl.persistence.orm import (
    CandidateAuditORM,
    DocumentORM,
    FactORM,
    IngestionRunORM,
    RelationshipORM,
    SourceBlockORM,
)
from fkl.application.ingest_document import ingest_document

db = database.get_session()

synthetic_docs = [
    ("doc_d6c660577ee44afd", "01-solstice-prospectus-2021.pdf"),
    ("doc_b1278d3ccb0c419d", "02-solstice-annual-report-fy23.pdf"),
    ("doc_4f0034e7245d44e0", "03-solstice-investor-deck-q2-fy24.pdf"),
    ("doc_d792b170cbb54935", "04-unseen-meridian-coop-notice.pdf"),
]

print("=" * 70, flush=True)
print("RE-INGESTING ALL 4 SYNTHETIC DOCUMENTS WITH GEMINI-3.1-FLASH-LITE", flush=True)
print("=" * 70, flush=True)

# Clean all 4 synthetic docs first to ensure clean cross-document relationship state
all_doc_ids = [d[0] for d in synthetic_docs]
for doc_id in all_doc_ids:
    fact_ids = [r[0] for r in db.query(FactORM.id).filter(FactORM.document_id == doc_id).all()]
    run_ids = [r[0] for r in db.query(IngestionRunORM.id).filter(IngestionRunORM.document_id == doc_id).all()]

    if fact_ids:
        db.query(RelationshipORM).filter(
            (RelationshipORM.left_fact_id.in_(fact_ids)) | (RelationshipORM.right_fact_id.in_(fact_ids))
        ).delete(synchronize_session=False)
    if run_ids:
        db.query(RelationshipORM).filter(
            RelationshipORM.created_by_run_id.in_(run_ids)
        ).delete(synchronize_session=False)

    db.query(CandidateAuditORM).filter(CandidateAuditORM.document_id == doc_id).delete(synchronize_session=False)
    db.query(FactORM).filter(FactORM.document_id == doc_id).delete(synchronize_session=False)
    db.query(SourceBlockORM).filter(SourceBlockORM.document_id == doc_id).delete(synchronize_session=False)
    db.query(IngestionRunORM).filter(IngestionRunORM.document_id == doc_id).delete(synchronize_session=False)

db.commit()
print("Cleaned state for all 4 synthetic documents.", flush=True)

# Now ingest one by one in order
for doc_id, filename in synthetic_docs:
    print("\n" + "-" * 70, flush=True)
    print(f"Ingesting {filename} ({doc_id})...", flush=True)
    t0 = time.monotonic()
    summary = ingest_document(doc_id)
    dur = time.monotonic() - t0

    facts = repositories.get_facts_for_document(db, doc_id)
    rejected = repositories.list_rejected_candidates(db, doc_id)

    table_facts = [f for f in facts if f.extraction_method == "table_rule"]
    prose_facts = [f for f in facts if f.extraction_method == "text_llm"]

    print(f"Done in {dur:.1f}s: {len(facts)} accepted ({len(table_facts)} table, {len(prose_facts)} prose), {len(rejected)} rejected candidates.", flush=True)

    if prose_facts:
        print(f"\nSample prose facts ({len(prose_facts)} total):", flush=True)
        for f in prose_facts[:8]:
            print(f"  [{f.extraction_method}] {f.entity_raw} | {f.metric_raw} = {f.value_raw} ({f.period_raw}) | scope: {f.scope_json}", flush=True)

    if rejected:
        print(f"\nSample rejected candidates ({len(rejected)} total):", flush=True)
        for r in rejected[:6]:
            print(f"  [REJECTED] metric={r.metric_raw!r}, val={r.value_raw!r}, reason={r.rejection_reason!r}", flush=True)

print("\n" + "=" * 70, flush=True)
print("FINAL CROSS-DOCUMENT RELATIONSHIPS AUDIT", flush=True)
print("=" * 70, flush=True)
syn_fact_ids = set(r[0] for r in db.query(FactORM.id).filter(FactORM.document_id.in_(all_doc_ids)).all())
rels = db.query(RelationshipORM).all()
syn_rels = [r for r in rels if r.left_fact_id in syn_fact_ids or r.right_fact_id in syn_fact_ids]
print(f"Total relationships across all documents: {len(rels)}", flush=True)
print(f"Synthetic document relationships: {len(syn_rels)}", flush=True)

verdicts = {}
for r in syn_rels:
    verdicts[r.verdict] = verdicts.get(r.verdict, 0) + 1
print("Synthetic relationships verdict breakdown:", verdicts, flush=True)

for r in syn_rels:
    left = repositories.get_fact(db, r.left_fact_id)
    right = repositories.get_fact(db, r.right_fact_id)
    if left and right:
        exp = (r.explanation or "").encode("ascii", "replace").decode("ascii")
        l_doc = left.document_id[:12]
        r_doc = right.document_id[:12]
        print(f"[{r.verdict.upper()}] ({r.reason_code}) [{l_doc}] {left.entity_raw} ({left.metric_raw}: {left.value_raw}) <-> [{r_doc}] {right.entity_raw} ({right.metric_raw}: {right.value_raw})", flush=True)
        print(f"    -> Explanation: {exp}", flush=True)

