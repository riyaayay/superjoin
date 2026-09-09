import sqlite3

conn = sqlite3.connect("data/fkl.sqlite3")
cur = conn.cursor()

print("--- CORROBORATES ---")
for row in cur.execute("""
    SELECT r.id, r.verdict, r.confidence, r.reason_code, r.explanation,
           lf.entity_raw, lf.metric_raw, lf.value_raw, lf.period_raw,
           rf.entity_raw, rf.metric_raw, rf.value_raw, rf.period_raw
    FROM relationships r
    JOIN facts lf ON r.left_fact_id = lf.id
    JOIN facts rf ON r.right_fact_id = rf.id
    WHERE r.verdict = 'corroborates'
""").fetchall():
    print(row)

print("\n--- SAMPLE RECONCILES (up to 5) ---")
for row in cur.execute("""
    SELECT r.id, r.verdict, r.confidence, r.reason_code, r.explanation,
           lf.entity_raw, lf.metric_raw, lf.value_raw, lf.period_raw,
           rf.entity_raw, rf.metric_raw, rf.value_raw, rf.period_raw
    FROM relationships r
    JOIN facts lf ON r.left_fact_id = lf.id
    JOIN facts rf ON r.right_fact_id = rf.id
    WHERE r.verdict = 'reconciles'
    LIMIT 5
""").fetchall():
    print(row)

print("\n--- SAMPLE LIKELY CONFLICTS (up to 5) ---")
for row in cur.execute("""
    SELECT r.id, r.verdict, r.confidence, r.reason_code, r.explanation,
           lf.entity_raw, lf.metric_raw, lf.value_raw, lf.period_raw,
           rf.entity_raw, rf.metric_raw, rf.value_raw, rf.period_raw
    FROM relationships r
    JOIN facts lf ON r.left_fact_id = lf.id
    JOIN facts rf ON r.right_fact_id = rf.id
    WHERE r.verdict = 'likely_conflict'
    LIMIT 5
""").fetchall():
    print(row)
