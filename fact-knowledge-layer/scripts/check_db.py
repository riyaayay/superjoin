import sqlite3

conn = sqlite3.connect("data/fkl.sqlite3")
cur = conn.cursor()
tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print("Tables:", tables)
runs = cur.execute("SELECT id, document_id, facts_created, facts_rejected, relationships_created, model_name FROM ingestion_runs").fetchall()
print("Ingestion runs:")
for r in runs:
    print(" ", r)
audit_count = cur.execute("SELECT count(*) FROM candidate_audit").fetchone()[0]
print("Candidate audit count:", audit_count)
methods = cur.execute("SELECT extraction_method, count(*) FROM facts GROUP BY extraction_method").fetchall()
print("Facts by extraction method:", methods)
rels_verdict = cur.execute("SELECT verdict, count(*) FROM relationships GROUP BY verdict").fetchall()
print("Relationships by verdict:", rels_verdict)
