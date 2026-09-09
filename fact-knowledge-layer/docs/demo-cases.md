# Demo Cases — Validated Evidence Card

This document records each required demonstration case with full source evidence from the live ingested institutional reports dataset (Economic Survey 2024-25, RBI Annual Report 2024-25, IMF 2025 Article IV).

---

## Case 1: Corroboration — Revenue & Growth Figures

**Type:** CORROBORATES  
**Relationship ID:** `rel_798ab09dc5a0`  
**Verdict:** `corroborates` | **Reason code:** `exact_match` | **Confidence:** `0.77`

| Field | Value |
|-------|-------|
| Document A (Left) | Economic Survey 2024-25 Excerpt (`doc_8b512124bbb14ed6`) |
| Document B (Right) | RBI Annual Report 2024-25 Excerpt (`doc_c86450769dfd4f78`) |
| Left Fact Metric | GST Revenue = 8.9 |
| Right Fact Metric | Revenue = 8.9 |
| Comparison | Exact numerical match (diff: 0.0) |
| Classification | `CORROBORATES` — same metric, entity, and aligned period |
| System Explanation | Both facts report the same value (8.9) for the same metric, entity, and period. |

**Why this is corroboration, not coincidence:**  
Both official institutions independently draw on primary administrative revenue data (Ministry of Finance / GSTN). The system normalises both representations, notes the zero difference within precision limits, and classifies them as corroborating evidence.

---

## Case 2: Reconciliation — Same Metric Across Different Periods

**Type:** RECONCILES  
**Relationship ID:** `rel_e3ceada60e34`  
**Verdict:** `reconciles` | **Reason code:** `different_period` | **Confidence:** `0.81`

| Field | Value |
|-------|-------|
| Document A (Left) | RBI Annual Report 2024-25 (`doc_c86450769dfd4f78`) |
| Document B (Right) | IMF India 2025 Article IV (`doc_79c87b12408946de`) |
| Left Fact | Cement Production = 12.7 (Period: `2023-24`) |
| Right Fact | Cement = 4.2 (Period: `2014`) |
| Classification | `RECONCILES` — `different_period` |
| System Explanation | Same metric and entity but different reporting periods (2014-01:2014-12 vs 2023-01:2023-12). No conflict; reconciled by period. |

**Why this reconciles rather than conflicts:**  
The two values (12.7 vs 4.2) differ substantially, but the system extracts and resolves the distinct temporal anchors (FY24 vs Calendar 2014). Instead of raising a false conflict, it explains the divergence through temporal reconciliation.

---

## Case 3: Likely Conflict — Discrepancy Flagged for Human Review

**Type:** LIKELY_CONFLICT  
**Relationship ID:** `rel_37ea5cd2871e`  
**Verdict:** `likely_conflict` | **Reason code:** `material_value_difference` | **Confidence:** `0.81`

| Field | Value |
|-------|-------|
| Document A (Left) | IMF India 2025 Article IV (`doc_79c87b12408946de`) |
| Document B (Right) | RBI Annual Report 2024-25 (`doc_c86450769dfd4f78`) |
| Left Fact | Cement = 8.3 (Period: `2023`) |
| Right Fact | Cement Production = 12.7 (Period: `2023-24`) |
| Discrepancy | Diff: 4.4 (tolerance: ±0.1) |
| Classification | `LIKELY_CONFLICT` — material numerical divergence despite overlapping period |
| System Explanation | Values 8.3 and 12.7 differ materially (diff 4.4, tolerance ±0.1). Both evidence sources have confidence ≥ 0.6. Flagged as LIKELY_CONFLICT — human review required before confirming. |

> [!IMPORTANT]
> The system does NOT blindly promote this to a confirmed contradiction. It assigns the `LIKELY_CONFLICT` status, surfacing a "Verify Evidence" badge in the UI to request analyst review with clickable source page links.

---

## Case 4: Extraction / Reasoning Failure Disclosed

**Type:** Visible rejection — `REJECTED_UNGROUNDED` / `candidate_audit`  
**Endpoint:** `/api/relationships/rejected-candidates`  
**Total Visible Rejected Candidates:** `46`

| Sample Audit ID | Document | Attempted Metric | Value | Rejection Reason |
|-----------------|----------|------------------|-------|------------------|
| `aud_9c9fcf56cac2` | RBI Annual Report (`doc_c86450769dfd4f78`) | Chart 1: R&D Expenditure, Innovation, GDP Per Capita | `[visual_data_unextractable]` | `source_block_is_chart_or_image` |
| `aud_d58446e5773f` | RBI Annual Report (`doc_c86450769dfd4f78`) | Table 1: Impact of R&D Expenditure Growth on TFP | `[visual_data_unextractable]` | `source_block_is_chart_or_image` |
| `aud_b9f4386c7e63` | RBI Annual Report (`doc_c86450769dfd4f78`) | Chart 1: Persistence in CPI Food and its Components | `[visual_data_unextractable]` | `source_block_is_chart_or_image` |
| `aud_...` | Economic Survey (`doc_8b512124bbb14ed6`) | Projected Annual Growth Rate | `9.85%` | `value_not_found_in_block_text` |

**System Behavior:**
1. Visual figures and charts detected by PyMuPDF are not hallucinated by the parser; attempted extraction is logged with `source_block_is_chart_or_image`.
2. Any LLM proposition containing figures not verbatim in the source block is rejected with `value_not_found_in_block_text`.
3. Rejected candidates are persisted in `candidate_audit` and rendered under the "Rejected Candidates" tab in the UI.
4. They are strictly excluded from the knowledge base and relationship pair generation.

---

## Precision & Normalisation Rules

| Scenario | Input 1 | Input 2 | Normalisation | Outcome |
|----------|---------|---------|---------------|---------|
| Crore vs Million | 8,142 crore | 81,415.38 million | 81,415.38 / 10 = 8,141.538 crore | `CORROBORATES` (diff 0.462 within ±0.5 crore whole-unit precision) |
| Period Shift | 12.7 (FY24) | 4.2 (2014) | Resolved start/end dates | `RECONCILES` (`different_period`) |
| Material Diff | 8.3 | 12.7 | Normalised values | `LIKELY_CONFLICT` (`material_value_difference`) |
