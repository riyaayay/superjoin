import sqlite3

conn = sqlite3.connect("data/fkl.sqlite3")
cur = conn.cursor()

print("INGESTION RUNS:")
runs = cur.execute("SELECT id, document_id, started_at, facts_created, facts_rejected, relationships_created, relationship_pairs_llm_fallback_matched, metric_llm_calls_skipped_due_to_cap FROM ingestion_runs").fetchall()
for r in runs:
    print(r)

print("\nCHECKING DECK FACTS:")
deck_facts = cur.execute("SELECT id, entity_raw, metric_raw, value_raw, period_raw, scope_json FROM facts WHERE document_id='doc_b409c8b7ae174676'").fetchall()
for f in deck_facts:
    print(f)

print("\nCHECKING AR FACTS:")
ar_facts = cur.execute("SELECT id, entity_raw, metric_raw, value_raw, period_raw, scope_json FROM facts WHERE document_id='doc_0ec6c32422194000' AND (metric_raw LIKE '%revenue%' OR metric_raw LIKE '%employee%' OR value_raw LIKE '%1,842%' OR value_raw LIKE '%2,105%')").fetchall()
for f in ar_facts:
    print(f)
