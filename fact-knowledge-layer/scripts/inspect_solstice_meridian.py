import sqlite3
import json

conn = sqlite3.connect("data/fkl.sqlite3")
cur = conn.cursor()

with open("scripts/solstice_dump.txt", "w", encoding="utf-8") as out:
    docs = cur.execute("SELECT id, original_filename FROM documents WHERE original_filename LIKE '%solstice%' OR original_filename LIKE '%meridian%' ORDER BY original_filename").fetchall()
    out.write(f"DOCS: {docs}\n\n")

    out.write("="*80 + "\nFACTS PER DOCUMENT:\n")
    for d in docs:
        out.write(f"\n=== {d[1]} ({d[0]}) ===\n")
        facts = cur.execute("SELECT id, extraction_method, entity_raw, metric_raw, value_raw, period_raw, scope_json FROM facts WHERE document_id=?", (d[0],)).fetchall()
        out.write(f"Total facts: {len(facts)}\n")
        for f in facts:
            out.write(f"  [{f[1]}] {f[2]} | {f[3]} = {f[4]} ({f[5]}) | scope: {f[6]}\n")

    out.write("\n" + "="*80 + "\nRELATIONSHIPS:\n")
    doc_ids = [d[0] for d in docs]
    placeholders = ",".join("?" for _ in doc_ids)
    query = f"""
        SELECT r.id, r.verdict, r.reason_code, r.confidence, r.explanation,
               lf.document_id, lf.entity_raw, lf.metric_raw, lf.value_raw, lf.period_raw, lf.scope_json,
               rf.document_id, rf.entity_raw, rf.metric_raw, rf.value_raw, rf.period_raw, rf.scope_json
        FROM relationships r
        JOIN facts lf ON r.left_fact_id = lf.id
        JOIN facts rf ON r.right_fact_id = rf.id
        WHERE lf.document_id IN ({placeholders}) OR rf.document_id IN ({placeholders})
    """
    rels = cur.execute(query, doc_ids + doc_ids).fetchall()
    out.write(f"Total relationships involving these documents: {len(rels)}\n")
    for r in rels:
        out.write(f"\n[{r[1].upper()}] ({r[2]}) conf={r[3]:.2f}\n")
        out.write(f"  L: [{r[5]}] {r[6]} | {r[7]} = {r[8]} ({r[9]}) scope={r[10]}\n")
        out.write(f"  R: [{r[11]}] {r[12]} | {r[13]} = {r[14]} ({r[15]}) scope={r[16]}\n")
        exp = (r[4] or "")
        out.write(f"  Exp: {exp}\n")
