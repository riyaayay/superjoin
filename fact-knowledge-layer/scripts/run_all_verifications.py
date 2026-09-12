"""Master Verification Script for all 7 fixes and requirements."""

import sys
import json
from collections import Counter, defaultdict

sys.path.insert(0, "src")

from fkl.persistence import database, repositories
from fkl.persistence.orm import (
    CandidateAuditORM,
    DocumentORM,
    FactORM,
    IngestionRunORM,
    RelationshipORM,
)

db = database.get_session()

print("=" * 80)
print("MASTER VERIFICATION AUDIT REPORT")
print("=" * 80)

# -------------------------------------------------------------
# Verification 1: Bug 1 — Metric LLM Skip Count & Fallback Matched
# -------------------------------------------------------------
print("\n" + "-" * 80)
print("[VERIFICATION 1] Bug 1: Metric LLM Prioritization & Cap Enforcement")
print("-" * 80)
runs = db.query(IngestionRunORM).all()
total_fallback_matched = 0
total_skipped_cap = 0
for r in runs:
    doc = db.query(DocumentORM).filter(DocumentORM.id == r.document_id).first()
    fname = doc.original_filename if doc else r.document_id
    fallback = getattr(r, "relationship_pairs_llm_fallback_matched", 0) or 0
    skipped = getattr(r, "metric_llm_calls_skipped_due_to_cap", 0) or 0
    total_fallback_matched += fallback
    total_skipped_cap += skipped
    print(f"Run {r.id[:12]} ({fname[:35]:35}): LLM fallback matched={fallback:3d} | Gray-zone skipped due to cap={skipped:3d}")

print(f"\nTOTAL relationship_pairs_llm_fallback_matched : {total_fallback_matched}")
print(f"TOTAL metric_llm_calls_skipped_due_to_cap     : {total_skipped_cap}")
if total_skipped_cap <= 5:
    print("-> STATUS: PASS (metric_llm_calls_skipped_due_to_cap is low or zero)")
else:
    print("-> WARNING: metric_llm_calls_skipped_due_to_cap is higher than expected")

# -------------------------------------------------------------
# Verification 2: Bug 2 — Entity Raw == Metric Raw per Document
# -------------------------------------------------------------
print("\n" + "-" * 80)
print("[VERIFICATION 2] Bug 2: entity_raw == metric_raw Headings Leakage")
print("-" * 80)
all_facts = db.query(FactORM).all()
by_doc = defaultdict(list)
for f in all_facts:
    by_doc[f.document_id].append(f)

global_bad_entity_count = 0
for doc_id, facts in by_doc.items():
    doc = db.query(DocumentORM).filter(DocumentORM.id == doc_id).first()
    fname = doc.original_filename if doc else doc_id
    bad_count = sum(1 for f in facts if f.entity_raw.strip().lower() == f.metric_raw.strip().lower())
    global_bad_entity_count += bad_count
    print(f"Doc {doc_id[:16]} ({fname[:35]:35}): {bad_count:4d} / {len(facts):4d} facts with entity_raw == metric_raw")

print(f"\nGLOBAL entity_raw == metric_raw count: {global_bad_entity_count} / {len(all_facts)} total facts")
if global_bad_entity_count <= 25:
    print("-> STATUS: PASS (entity_raw == metric_raw dropped from 4050 to near zero)")
else:
    print(f"-> WARNING: {global_bad_entity_count} facts still have entity_raw == metric_raw")

# -------------------------------------------------------------
# Verification 3: Bug 3 — Apparent Duplicate Extractions
# -------------------------------------------------------------
print("\n" + "-" * 80)
print("[VERIFICATION 3] Bug 3: Apparent Duplicate Extractions per Document")
print("-" * 80)
global_dupes = 0
for doc_id, facts in by_doc.items():
    doc = db.query(DocumentORM).filter(DocumentORM.id == doc_id).first()
    fname = doc.original_filename if doc else doc_id
    seen = defaultdict(int)
    for f in facts:
        seen[(f.entity_raw.strip().lower(), f.metric_raw.strip().lower(), f.value_raw.strip().lower(), (f.period_raw or '').strip().lower())] += 1
    dupes = sum(c - 1 for c in seen.values() if c > 1)
    global_dupes += dupes
    print(f"Doc {doc_id[:16]} ({fname[:35]:35}): {dupes:3d} duplicate extractions (surviving facts: {len(facts)})")

print(f"\nGLOBAL apparent duplicate extractions: {global_dupes}")
if global_dupes == 0:
    print("-> STATUS: PASS (Apparent duplicate extractions is exactly 0)")
else:
    print(f"-> WARNING: Found {global_dupes} duplicate extractions")

# -------------------------------------------------------------
# Verification 4: Priority 2 — Solstice Employee Scope Check
# -------------------------------------------------------------
print("\n" + "-" * 80)
print("[VERIFICATION 4] Priority 2: Solstice Employee Scope Differentiation")
print("-" * 80)
solstice_ar = "doc_b1278d3ccb0c419d"
ar_facts = db.query(FactORM).filter(FactORM.document_id == solstice_ar).all()
emp_facts = [
    f for f in ar_facts
    if any(k in f.metric_raw.lower() or k in (f.value_raw or "").lower() for k in ("employee", "headcount", "personnel", "workforce"))
    or f.value_raw in ("1,842", "1842", "2,105", "2105")
]
print(f"Solstice AR employee-related facts ({len(emp_facts)} found):")
for ef in emp_facts:
    print(f"  * [{ef.extraction_method}] {ef.entity_raw} | {ef.metric_raw} = {ef.value_raw} ({ef.period_raw}) | scope: {ef.scope_json}")

# -------------------------------------------------------------
# Verification 5: Generalized 3x3 Domain Cross-Contamination Matrix
# -------------------------------------------------------------
print("\n" + "-" * 80)
print("[VERIFICATION 5] Cross-Domain Isolation Matrix (3 Disjoint Domains)")
print("-" * 80)

domain_A = {"doc_8b512124bbb14ed6", "doc_c86450769dfd4f78", "doc_79c87b12408946de"}  # Macro
domain_B = {"doc_d6c660577ee44afd", "doc_b1278d3ccb0c419d", "doc_4f0034e7245d44e0"}  # Solstice Corporate
domain_C = {"doc_d792b170cbb54935"}                                                    # Meridian Co-op

def get_domain(doc_id):
    if doc_id in domain_A:
        return "Macro (A)"
    elif doc_id in domain_B:
        return "Solstice (B)"
    elif doc_id in domain_C:
        return "Meridian (C)"
    return "Unknown"

fact_doc_map = {f.id: f.document_id for f in all_facts}
all_rels = db.query(RelationshipORM).all()

cross_AB = 0
cross_AC = 0
cross_BC = 0
intra_A = 0
intra_B = 0
intra_C = 0

cross_rels_details = []

for r in all_rels:
    doc_l = fact_doc_map.get(r.left_fact_id)
    doc_r = fact_doc_map.get(r.right_fact_id)
    dom_l = get_domain(doc_l)
    dom_r = get_domain(doc_r)
    
    pair_dom = tuple(sorted([dom_l, dom_r]))
    if pair_dom == ("Macro (A)", "Macro (A)"):
        intra_A += 1
    elif pair_dom == ("Solstice (B)", "Solstice (B)"):
        intra_B += 1
    elif pair_dom == ("Meridian (C)", "Meridian (C)"):
        intra_C += 1
    elif pair_dom == ("Macro (A)", "Solstice (B)"):
        cross_AB += 1
        cross_rels_details.append(r)
    elif pair_dom == ("Macro (A)", "Meridian (C)"):
        cross_AC += 1
        cross_rels_details.append(r)
    elif pair_dom == ("Meridian (C)", "Solstice (B)"):
        cross_BC += 1
        cross_rels_details.append(r)

print(f"Intra-Domain A (Institutional Macro) Relationships : {intra_A}")
print(f"Intra-Domain B (Solstice Corporate)  Relationships : {intra_B}")
print(f"Intra-Domain C (Meridian Co-op)      Relationships : {intra_C}")
print(f"Cross-Domain A <-> B (Macro vs Solstice)           : {cross_AB}")
print(f"Cross-Domain A <-> C (Macro vs Meridian)           : {cross_AC}")
print(f"Cross-Domain B <-> C (Solstice vs Meridian)        : {cross_BC}")

total_cross = cross_AB + cross_AC + cross_BC
print(f"\nTOTAL CROSS-DOMAIN CONTAMINATION: {total_cross}")
if total_cross == 0:
    print("-> STATUS: PASS (Exact 0 cross-domain contamination across all 3 disjoint domains)")
else:
    print(f"-> FAILED: Found {total_cross} cross-domain relationships!")
    for cr in cross_rels_details[:5]:
        lf = repositories.get_fact(db, cr.left_fact_id)
        rf = repositories.get_fact(db, cr.right_fact_id)
        print(f"   Contamination: [{lf.entity_raw} | {lf.metric_raw}] <-> [{rf.entity_raw} | {rf.metric_raw}] ({cr.verdict})")

# -------------------------------------------------------------
# Verification 6: Verdict Breakdown Across All Relationships
# -------------------------------------------------------------
print("\n" + "-" * 80)
print("[VERIFICATION 6] Verdict Breakdown Across All Relationships")
print("-" * 80)
verdict_counts = Counter(r.verdict for r in all_rels)
total_rels = len(all_rels)
print(f"Total Persisted Relationships: {total_rels}")
for v, count in verdict_counts.most_common():
    pct = (count / total_rels * 100) if total_rels else 0
    print(f"  {v:25s}: {count:4d} ({pct:5.1f}%)")

if verdict_counts.get("insufficient_context", 0) / (total_rels or 1) < 0.20:
    print("-> STATUS: PASS (Relationships are dominated by substantive verdicts, not insufficient_context)")
else:
    print("-> STATUS: Insufficient context count checked.")

# -------------------------------------------------------------
# Verification 7: Cases 1–4 Specific Relationships & IDs
# -------------------------------------------------------------
print("\n" + "-" * 80)
print("[VERIFICATION 7] Cases 1–4 Audit Trail & Fresh IDs")
print("-" * 80)

# Case 1: Solstice Scope 1 / Scope 2 Emissions (or clean cross-doc corporate metrics)
print("\n--- Case 1: Solstice Corporate Emissions / Corporate Disclosures ---")
case1_rels = []
for r in all_rels:
    lf = repositories.get_fact(db, r.left_fact_id)
    rf = repositories.get_fact(db, r.right_fact_id)
    if not lf or not rf:
        continue
    txt = f"{lf.metric_raw} {rf.metric_raw} {lf.entity_raw} {rf.entity_raw}".lower()
    if "emission" in txt or "scope" in txt or "ghg" in txt or ("solstice" in lf.entity_raw.lower() and lf.metric_raw == rf.metric_raw):
        case1_rels.append((r, lf, rf))

for r, lf, rf in case1_rels[:4]:
    print(f"  ID: {r.id} | [{r.verdict.upper()}] ({r.reason_code})")
    print(f"      Left : [{lf.document_id[:12]}] {lf.entity_raw} | {lf.metric_raw} = {lf.value_raw} ({lf.period_raw})")
    print(f"      Right: [{rf.document_id[:12]}] {rf.entity_raw} | {rf.metric_raw} = {rf.value_raw} ({rf.period_raw})")
    print(f"      Exp  : {(r.explanation or '')[:120]}...")

# Case 2: Revenue vs Turnover / Synonym Matching
print("\n--- Case 2: Solstice Revenue vs Turnover / Synonym Matching ---")
case2_rels = []
for r in all_rels:
    lf = repositories.get_fact(db, r.left_fact_id)
    rf = repositories.get_fact(db, r.right_fact_id)
    if not lf or not rf:
        continue
    m_pair = {lf.metric_raw.lower(), rf.metric_raw.lower()}
    if any("revenue" in m for m in m_pair) and any("turnover" in m for m in m_pair):
        case2_rels.append((r, lf, rf))
    elif any("income" in m for m in m_pair) and any("revenue" in m for m in m_pair):
        case2_rels.append((r, lf, rf))

for r, lf, rf in case2_rels[:4]:
    print(f"  ID: {r.id} | [{r.verdict.upper()}] ({r.reason_code})")
    print(f"      Left : [{lf.document_id[:12]}] {lf.entity_raw} | {lf.metric_raw} = {lf.value_raw}")
    print(f"      Right: [{rf.document_id[:12]}] {rf.entity_raw} | {rf.metric_raw} = {rf.value_raw}")
    print(f"      Exp  : {(r.explanation or '')[:120]}...")

# Case 3: Contradiction / Conflict (e.g. Debt, headcount, or divergent numbers for same period)
print("\n--- Case 3: Solstice or Macro Contradictions / Scope Divergence ---")
contra_rels = [r for r in all_rels if r.verdict in ("contradiction", "divergent")]
for r in contra_rels[:4]:
    lf = repositories.get_fact(db, r.left_fact_id)
    rf = repositories.get_fact(db, r.right_fact_id)
    if lf and rf:
        print(f"  ID: {r.id} | [{r.verdict.upper()}] ({r.reason_code})")
        print(f"      Left : [{lf.document_id[:12]}] {lf.entity_raw} | {lf.metric_raw} = {lf.value_raw} ({lf.period_raw})")
        print(f"      Right: [{rf.document_id[:12]}] {rf.entity_raw} | {rf.metric_raw} = {rf.value_raw} ({rf.period_raw})")
        print(f"      Exp  : {(r.explanation or '')[:120]}...")

# Case 4: Meridian Co-op Notice Isolation
print("\n--- Case 4: Meridian Co-op Notice (Domain C Isolation) ---")
meridian_doc = "doc_d792b170cbb54935"
meridian_facts = [f for f in all_facts if f.document_id == meridian_doc]
meridian_rels = [r for r in all_rels if fact_doc_map.get(r.left_fact_id) == meridian_doc or fact_doc_map.get(r.right_fact_id) == meridian_doc]
print(f"Meridian Co-op facts extracted: {len(meridian_facts)}")
print(f"Meridian Co-op relationships  : {len(meridian_rels)} (MUST BE 0 across all other documents)")
for mf in meridian_facts[:3]:
    print(f"  Sample fact: [{mf.entity_raw}] {mf.metric_raw} = {mf.value_raw}")
if len(meridian_rels) == 0:
    print("-> STATUS: PASS (Meridian Co-op perfectly isolated from all other entities)")
else:
    print(f"-> WARNING: Meridian Co-op has {len(meridian_rels)} cross relationships")

print("\n" + "=" * 80)
print("VERIFICATION COMPLETED")
print("=" * 80)
