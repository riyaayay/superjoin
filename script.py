import sys
sys.path.insert(0, 'src')
from fkl.persistence import database
from fkl.persistence.orm import FactORM, RelationshipORM

db = database.get_session()

print("Total facts:", db.query(FactORM).count())
print("By document:")
for row in db.query(FactORM.document_id, FactORM.id).all():
    pass  # just counting below
from collections import Counter
doc_counts = Counter(f.document_id for f in db.query(FactORM).all())
print(doc_counts)

# Sample a handful of insufficient_context pairs to see what's actually being compared
sample = db.query(RelationshipORM).filter(RelationshipORM.verdict == "insufficient_context").limit(10).all()
for r in sample:
    lf = db.query(FactORM).filter(FactORM.id == r.left_fact_id).first()
    rf = db.query(FactORM).filter(FactORM.id == r.right_fact_id).first()
    print("---")
    print("L:", lf.entity_raw, "|", lf.metric_raw, "=", lf.value_raw)
    print("R:", rf.entity_raw, "|", rf.metric_raw, "=", rf.value_raw)
    print("reason:", r.reason_code, "| explanation:", r.explanation)