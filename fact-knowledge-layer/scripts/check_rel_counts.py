"""Full relationship count audit — surfaces doc card vs run row discrepancy."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from fkl.persistence import database, repositories

db = database.get_session()
docs = repositories.list_documents(db)

print(f"{'Document':<45} {'Card rels':>9} {'Run rels':>8} {'Match':>6} {'Page ct':>7}")
print("-" * 82)
for doc in docs:
    stats = repositories.get_document_stats(db, doc.id)
    card_rels = stats["relationships"]
    for r in doc.runs:
        run_rels = r.relationships_created
        match = "OK" if card_rels == run_rels else "MISMATCH"
        print(f"{doc.original_filename:<45} {card_rels:>9} {run_rels:>8} {match:>6} {doc.page_count:>7}")

db.close()
