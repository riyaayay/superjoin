import sys
sys.path.insert(0, 'src')
from fkl.persistence import database
from fkl.persistence.orm import FactORM

db = database.get_session()

# 1. Confirm: are duplicates specifically the table-derived facts, and where do they come from?
d6_facts = db.query(FactORM).filter(FactORM.document_id == 'doc_d6c660577ee44afd').all()
from collections import defaultdict
groups = defaultdict(list)
for f in d6_facts:
    key = (f.entity_raw, f.metric_raw, f.value_raw, f.period_raw)
    groups[key].append(f)
print("Duplicated facts (appearing 2+ times):")
for key, items in groups.items():
    if len(items) > 1:
        print(f"  {key} -> {len(items)}x, extraction_method={[i.extraction_method for i in items]}, block_id={[i.evidence_block_id for i in items]}")

# 2. Is this duplication document-wide, or specific to d6c660577?
print("\nDuplication check across all docs:")
all_facts = db.query(FactORM).all()
by_doc = defaultdict(list)
for f in all_facts:
    by_doc[f.document_id].append(f)
for doc_id, facts in by_doc.items():
    seen = defaultdict(int)
    for f in facts:
        seen[(f.entity_raw, f.metric_raw, f.value_raw, f.period_raw)] += 1
    dupes = sum(c - 1 for c in seen.values() if c > 1)
    print(f"  {doc_id}: {len(facts)} facts, {dupes} apparent duplicate extractions")

# 3. Find the actual FY23 counterpart to the investor deck's 427 / ~1,950
b1_facts = db.query(FactORM).filter(FactORM.document_id == 'doc_b1278d3ccb0c419d').all()
print(f"\ndoc_b1278d3ccb0c419d facts ({len(b1_facts)}):")
for f in b1_facts:
    print(" -", f.entity_raw, "|", f.metric_raw, "=", f.value_raw, f.period_raw)