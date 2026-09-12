"""Clean database and re-ingest all 7 documents from scratch."""

import os
import sys
import time
from pathlib import Path

os.environ["MAX_METRIC_LLM_CALLS_PER_RUN"] = "450"
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

# Ingestion order: Group A (Macro) -> Group B (Solstice) -> Group C (Meridian)
documents_in_order = [
    ("doc_8b512124bbb14ed6", "01-india-economic-survey-2024-25-excerpt.pdf"),
    ("doc_c86450769dfd4f78", "02-rbi-annual-report-2024-25-excerpt.pdf"),
    ("doc_79c87b12408946de", "03-imf-india-2025-article-iv-excerpt.pdf"),
    ("doc_d6c660577ee44afd", "01-solstice-prospectus-2021.pdf"),
    ("doc_b1278d3ccb0c419d", "02-solstice-annual-report-fy23.pdf"),
    ("doc_4f0034e7245d44e0", "03-solstice-investor-deck-q2-fy24.pdf"),
    ("doc_d792b170cbb54935", "04-unseen-meridian-coop-notice.pdf"),
]

print("=" * 80, flush=True)
print("WIPING ALL EXISTING RUNS, FACTS, BLOCKS, AND RELATIONSHIPS FOR FRESH RUN", flush=True)
print("=" * 80, flush=True)

db.query(RelationshipORM).delete(synchronize_session=False)
db.query(CandidateAuditORM).delete(synchronize_session=False)
db.query(FactORM).delete(synchronize_session=False)
db.query(SourceBlockORM).delete(synchronize_session=False)
db.query(IngestionRunORM).delete(synchronize_session=False)
db.commit()

print("Database cleared cleanly.\n", flush=True)

start_total = time.monotonic()

for idx, (doc_id, filename) in enumerate(documents_in_order, start=1):
    print("=" * 80, flush=True)
    print(f"[{idx}/{len(documents_in_order)}] Ingesting {filename} ({doc_id})...", flush=True)
    print("=" * 80, flush=True)
    t0 = time.monotonic()
    
    try:
        summary = ingest_document(doc_id)
        dur = time.monotonic() - t0
        facts = repositories.get_facts_for_document(db, doc_id)
        rejected = repositories.list_rejected_candidates(db, doc_id)
        table_facts = [f for f in facts if f.extraction_method == "table_rule"]
        prose_facts = [f for f in facts if f.extraction_method == "text_llm"]
        
        print(f"-> SUCCESS in {dur:.1f}s: {len(facts)} facts accepted ({len(table_facts)} table, {len(prose_facts)} prose), {len(rejected)} candidates rejected.", flush=True)
        if prose_facts:
            print(f"   Sample prose facts ({len(prose_facts)} total):", flush=True)
            for pf in prose_facts[:4]:
                print(f"     * [{pf.entity_raw}] {pf.metric_raw} = {pf.value_raw} ({pf.period_raw}) | scope={pf.scope_json}", flush=True)
    except Exception as e:
        print(f"-> ERROR ingesting {filename}: {e}", flush=True)
        import traceback
        traceback.print_exc()

total_dur = time.monotonic() - start_total
print("\n" + "=" * 80, flush=True)
print(f"ALL 7 DOCUMENTS INGESTED FROM SCRATCH IN {total_dur:.1f}s", flush=True)
print("=" * 80, flush=True)
