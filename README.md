# Fact Knowledge Layer

A system that ingests PDFs, extracts grounded facts, and identifies where those facts corroborate,
contradict, or reconcile across documents — built for the Superjoin VIT 2026 Engineering Intern
hiring assignment.

---

## Setup and Run Instructions

**Requirements:** Python 3.11, pip.

```bash
git clone <YOUR_REPO_URL>
cd fact-knowledge-layer
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

pip install -r requirements.txt
cp .env.example .env
```

By default the system runs with `FakeLLMProvider` (deterministic, no API key required) so the
whole pipeline — parsing, extraction, grounding, relationship building, and the reviewer UI — can
be evaluated with zero external dependencies. To use real semantic extraction/matching via Gemini,
set in `.env`:

```
LLM_PROVIDER=gemini
GEMINI_API_KEY=<your key>
LLM_MODEL=gemini-2.0-flash
```

Run the app:

```bash
uvicorn fkl.api.main:app --reload
```

Open `http://localhost:8000` — upload a PDF, watch it process, and inspect Facts / Relationships /
Rejected Candidates in the tabs (these aggregate across every document uploaded in this session,
not just the most recent one).

Run the test suite:

```bash
pytest -v
```

To reset the knowledge layer and start from an empty database:

```bash
rm fkl.db   # or the path set in DATABASE_URL
```

---

## Video Demo

[LINK TO BE ADDED — record after the final re-ingestion + verification pass below is confirmed
clean, so the video reflects the fixed pipeline, not a mid-fix state.]

The video shows: one PDF being uploaded and processed end-to-end, then all four required cases
(see below) with each fact's source evidence and the system's reasoning for the relationship
verdict.

---

## Approach

**Pipeline:** parse → extract → ground → normalise → deduplicate → compare (relate).

1. **Parse** (`parse_pdf.py`) — PyMuPDF for text blocks and page structure, with a PyMuPDF-first /
   pdfplumber-fallback strategy for table detection. Charts and images are recorded as their own
   block kind rather than silently dropped, so their non-extraction is an observable, auditable
   outcome rather than an invisible gap.
2. **Extract** — two independent, domain-agnostic extractors run in parallel:
   - `extract_table_facts.py`: deterministic, rule-based. No hard-coded metric names — any
     labelled numeric cell with a recoverable row/column/unit context becomes a candidate.
   - `extract_text_facts.py`: LLM-based, called only on prose blocks selected by a
     domain-agnostic scoring heuristic (digit density, currency/scale words, percentage signs),
     under a hard per-document call budget to stay within API rate limits.
3. **Ground** (`ground_candidates.py`) — the single non-negotiable invariant in the system: a
   candidate only becomes a `Fact` if its value is verbatim-recoverable in the source block's text.
   No candidate becomes a fact on the strength of an LLM's say-so alone. Rejected candidates are
   never discarded — they're persisted to a candidate-audit trail with a reason code, browsable via
   the "Rejected Candidates" tab.
4. **Normalise** — units, scale words (crore/lakh/million), and periods are parsed into structured
   fields. Numeric comparisons use a precision-derived tolerance (`±0.5 / 10^decimal_places` of the
   source string) rather than a single hard-coded epsilon, so a value reported as `"8.9"` and one
   reported as `"8.92"` are compared with the rounding precision each source actually implies.
5. **Deduplicate** — facts are deduplicated on content (entity/metric/value/period), not on which
   internal block produced them, so the same fact detected via two overlapping table-region
   extractions collapses to one.
6. **Compare** (`build_relationships.py` + `classification.py`) — new facts are compared only
   against facts from *other* documents (never within the same document), using independent 2D
   blocking (entity-token overlap AND metric-token overlap must both clear a threshold) before any
   classification is attempted. This keeps the comparison space tractable without an ANN/vector
   index. A deterministic decision table then classifies each blocking-passed pair as
   `CORROBORATES`, `LIKELY_CONFLICT`, `RECONCILES` (with an explicit reason: different period,
   different scope, or unit/scale conversion), or `INSUFFICIENT_CONTEXT`. Metric pairs with
   moderate token overlap (paraphrases like "consolidated revenue" vs "Revenue from operations")
   fall into a gray zone that's resolved with a budgeted LLM semantic-equivalence check,
   prioritized so that pairs with the strongest entity match get first claim on that budget.

**Architecture:** a layered structure — `domain` (pure models, classification rules, no I/O),
`pipeline` (the six stages above, each independently testable), `application` (orchestration —
one `ingest_document()` entry point, wrapped in structured logging and never claiming partial
success on failure), `persistence` (SQLite + repositories), and `api` (FastAPI routes + a
server-rendered reviewer UI). New document types require no schema or code changes — the schema
is driven entirely by what's extractable from the PDF, not a fixed fact taxonomy.

**Key trade-offs:**
- SQL-level 2D blocking instead of a vector/embedding index — simpler to reason about and debug,
  but weaker at catching paraphrased metric names that share few surface tokens; the LLM
  fallback exists specifically to cover that gap within a bounded call budget.
- `FakeLLMProvider` as the default — makes the system runnable and gradeable with zero API key,
  at the cost of prose extraction quality when running in that mode.
- Deterministic tolerance math over a single hard-coded epsilon — more correct across the wide
  range of precision found in real reports, at the cost of being harder to reason about at a glance
  than "±1%."

**AI tools used:** [FILL IN — name the tools actually used across this project: e.g. Claude for
architecture/debugging assistance, Gemini as the runtime LLM provider, [Antigravity / your coding
agent] for implementation. Be specific about what each was used for, per the assignment's ask.]

---

## The Four Required Cases

*(Fill in each relationship ID and re-confirm against the database after the current from-scratch
re-ingestion finishes — do not carry over IDs from a pre-fix run.)*

**1. Corroboration across documents, differently expressed**
`GST Revenue = 8.9` (Economic Survey) vs `Revenue = 8.9` (RBI Annual Report) — same underlying
figure, different source phrasing, verdict `CORROBORATES`.
Relationship ID: `[FILL IN AFTER VERIFICATION]`

**2. Genuine or likely contradiction**
`[FILL IN — confirm post-fix whether Solstice's ~1,950 employees (investor deck) resolves as
LIKELY_CONFLICT against the annual report figures, or as RECONCILES via scope — see Case 3 below.
Use whichever the fixed classifier actually produces; do not force a result.]`
Relationship ID: `[FILL IN AFTER VERIFICATION]`

**3. Apparent contradiction explained by context (scope/period)**
`[FILL IN — the Solstice standalone (1,842) vs consolidated (2,105) full-time-employee figures
from the same annual report, same date, reconciled by consolidation scope, if the scope-tagging
fix lands correctly. Fall back to the existing cement-production period-based example in
docs/demo-cases.md if this one doesn't confirm cleanly.]`
Relationship ID: `[FILL IN AFTER VERIFICATION]`

**4. An extraction or reasoning failure, and how it's handled**
Chart and image blocks are parsed and recorded (`block_kind = chart/image`) but never extracted
into facts — the system discloses this explicitly rather than silently dropping visual data.
Additionally: `[NOTE the entity-resolution and duplicate-table-detection bugs found and fixed
during this project as a second, concrete example of Case 4 — this is arguably a stronger answer
than the chart-handling one, since it shows a failure that was found, diagnosed to root cause, and
fixed, not just disclosed as a known gap.]`
Audit trail: browsable via `/api/relationships/rejected-candidates` and the "Rejected Candidates" tab.

---

## Limitations and Next Steps

- **Blocking is token-overlap based, not semantic.** Two metrics sharing a single generic word
  (e.g. "Steel Consumption" vs "Iron and steel", both containing "steel") can pass blocking and
  need the LLM gray-zone check to correctly resolve as unrelated; conversely, metrics with no
  shared tokens at all never reach the LLM check. A phrase-embedding-based second blocking pass
  (e.g. `sentence-transformers`) is the natural next step — see the `[brownie point]` note below.
- **The metric-equivalence LLM check runs under a fixed per-run call budget**, prioritized by
  entity-match strength so the highest-confidence pairs are resolved first; pairs beyond the
  budget fall back to token-overlap-only classification. This is a deliberate cost/rate-limit
  trade-off, not an oversight, but it means very large multi-document knowledge layers will see
  more `INSUFFICIENT_CONTEXT` verdicts on subtle paraphrases as document count grows.
- **Chart and image data is never extracted**, only disclosed as non-extracted (Case 4). OCR or
  vision-based extraction for chart data is a natural next step.
- **SQLite + background tasks** is adequate for the demo's document sizes but not built for heavy
  concurrent multi-PDF ingestion; a production version would need a proper task queue and a
  database built for concurrent writes.
- **Entity resolution is heuristic**, not a trained NER model — it relies on document metadata,
  corporate-suffix patterns, and layout position. This is generally reliable for corporate filings
  and can misfire on institutional/government reports with no company name to anchor on (a
  specific instance of this was found and fixed during development — see Case 4).

## Additional Notes

[Add anything else worth flagging — e.g. that a significant part of this project's value was in
the debugging process itself: several bugs (an invalid default LLM model name, an ALL-CAPS section
heading being misread as a company name, duplicate table detections doubling fact counts, and an
overly narrow LLM call budget masking real cross-document relationships) were found via systematic
raw-data verification rather than trusting a passing test suite, since the test suite exclusively
exercises a fake/mocked LLM path and could not by construction catch any of them.]
