import sqlite3
import json

conn = sqlite3.connect("data/fkl.sqlite3")
cur = conn.cursor()

print("=" * 60)
print("DOCUMENTS:")
docs = cur.execute("SELECT id, original_filename, page_count, status FROM documents").fetchall()
for d in docs:
    print(f"  {d[0]} | {d[1]} ({d[2]} pages) - status: {d[3]}")

print("\n" * 1 + "=" * 60)
print("FACTS PER DOCUMENT:")
for d in docs:
    facts = cur.execute("SELECT extraction_method, count(*) FROM facts WHERE document_id=? GROUP BY extraction_method", (d[0],)).fetchall()
    total = sum(c for _, c in facts)
    print(f"  {d[1]} ({d[0]}): total={total}, breakdown={facts}")

print("\n" * 1 + "=" * 60)
print("SAMPLE FACTS FOR SOLSTICE & MERIDIAN:")
for d in docs:
    if "solstice" in d[1].lower() or "meridian" in d[1].lower():
        print(f"\n--- {d[1]} ---")
        facts = cur.execute("SELECT id, extraction_method, entity_raw, metric_raw, value_raw, period_raw, scope_json FROM facts WHERE document_id=?", (d[0],)).fetchall()
        for f in facts:
            print(f"    [{f[1]}] {f[2]} | {f[3]} = {f[4]} (period: {f[5]}) | scope: {f[6]}")

print("\n" * 1 + "=" * 60)
print("ALL RELATIONSHIPS:")
rels = cur.execute("""
    SELECT r.id, r.verdict, r.reason_code, r.confidence, r.explanation,
           lf.document_id, lf.entity_raw, lf.metric_raw, lf.value_raw, lf.period_raw,
           rf.document_id, rf.entity_raw, rf.metric_raw, rf.value_raw, rf.period_raw
    FROM relationships r
    JOIN facts lf ON r.left_fact_id = lf.id
    JOIN facts rf ON r.right_fact_id = rf.id
""").fetchall()
print(f"Total relationships: {len(rels)}")
for r in rels:
    print(f"\n[{r[1].upper()}] ({r[2]}) conf={r[3]:.2f}")
    print(f"  Left : [{r[5]}] {r[6]} | {r[7]} = {r[8]} ({r[9]})")
    print(f"  Right: [{r[10]}] {r[11]} | {r[12]} = {r[13]} ({r[14]})")
    exp = (r[4] or "").encode("ascii", "replace").decode("ascii")
    print(f"  Exp  : {exp}")

print("\n" * 1 + "=" * 60)
print("CANDIDATE AUDIT / REJECTED:")
for r in cur.execute("SELECT document_id, rejection_reason, count(*) FROM candidate_audit GROUP BY document_id, rejection_reason").fetchall():
    print(f"  Doc {r[0]} | {r[1]}: {r[2]}")

print("\nSAMPLE REJECTED FOR MERIDIAN:")
meridian_doc = None
for d in docs:
    if "meridian" in d[1].lower():
        meridian_doc = d[0]
if meridian_doc:
    for row in cur.execute("SELECT id, metric_raw, value_raw, rejection_reason FROM candidate_audit WHERE document_id=?", (meridian_doc,)).fetchall():
        print(f"  [{row[3]}] {row[1]} = {row[2]}")
