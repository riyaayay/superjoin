import sys
sys.path.insert(0, "src")
import sqlite3
import json
from fkl.persistence import database
from fkl.persistence.orm import FactORM
from fkl.pipeline.build_relationships import _orm_to_fact, _blocking_keys, ENTITY_BLOCKING_THRESHOLD
from fkl.domain.classification import classify, decide

db = database.get_session()

# Fact 1: 427 Cr
f1_row = db.query(FactORM).filter(FactORM.id == "fact_19df38f1f5ed4d").first()
# Fact 2: 4,268.91
f2_row = db.query(FactORM).filter(FactORM.id == "fact_36483e5aff3d49").first()

f1 = _orm_to_fact(f1_row)
f2 = _orm_to_fact(f2_row)

print("--- Fact 1 (427 Cr) ---")
print("Entity:", f1.entity_raw, "| canonical:", f1.entity_canonical)
print("Metric:", f1.metric_raw, "| key:", f1.metric_key)
print("Value:", f1.value_raw, "| kind:", f1.value_kind, "| dim:", f1.unit_dimension, "| norm:", f1.normalised_value, f1.normalised_unit)
print("Period:", f1.period_raw, f1.period_start, f1.period_end)
print("Scope:", f1.scope)

print("\n--- Fact 2 (4,268.91) ---")
print("Entity:", f2.entity_raw, "| canonical:", f2.entity_canonical)
print("Metric:", f2.metric_raw, "| key:", f2.metric_key)
print("Value:", f2.value_raw, "| kind:", f2.value_kind, "| dim:", f2.unit_dimension, "| norm:", f2.normalised_value, f2.normalised_unit)
print("Period:", f2.period_raw, f2.period_start, f2.period_end)
print("Scope:", f2.scope)

keys1 = _blocking_keys(f1)
keys2 = _blocking_keys(f2)
print("\nKeys 1:", keys1)
print("Keys 2:", keys2)
ent_union = keys1[0] | keys2[0]
ent_jaccard = len(keys1[0] & keys2[0]) / len(ent_union) if ent_union else 0
print(f"Entity Jaccard: {ent_jaccard} (threshold: {ENTITY_BLOCKING_THRESHOLD})")

dim_compat = not (f1.unit_dimension and f2.unit_dimension and f1.unit_dimension.value != "unknown" and f2.unit_dimension.value != "unknown" and f1.unit_dimension != f2.unit_dimension)
kind_compat = not (f1.value_kind and f2.value_kind and f1.value_kind != f2.value_kind)
print(f"Dimension compatible: {dim_compat}")
print(f"Kind compatible: {kind_compat}")

cmp = classify(f1, f2)
verdict, reason = decide(cmp)
print("\nClassification:")
print("Verdict:", verdict)
print("Reason:", reason)
print("Match method:", cmp.match_method)
print("Period overlap:", cmp.period_overlap)
print("Value diff:", cmp.value_difference_relative)
print("Left norm:", cmp.left_normalised_value, "Right norm:", cmp.right_normalised_value)
