# Fact Knowledge Layer

A system that ingests PDFs, extracts grounded facts, and identifies where
those facts corroborate, contradict, or reconcile across documents — built
for the Superjoin VIT 2026 Engineering Intern hiring assignment.

## Setup and Run Instructions

Requirements: Python 3.11, pip.

```
git clone <YOUR_REPO_URL>
cd fact-knowledge-layer
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

pip install -r requirements.txt
pip install -e .              # required — the app imports `fkl` as an
                               # installed package; without this, uvicorn
                               # will fail with ModuleNotFoundError: No
                               # module named 'fkl'
cp .env.example .env
```

By default the system runs with `FakeLLMProvider` (deterministic, no API key
required) so the whole pipeline — parsing, extraction, grounding,
relationship building, and the reviewer UI — can be evaluated with zero
external dependencies. To use real semantic extraction/matching via Gemini,
set in `.env`:

```
LLM_PROVIDER=gemini
GEMINI_API_KEY=<your key>
LLM_MODEL=<verify current model name before submitting — see note below>
```

**⚠ Verify the model name right before submission.** Gemini's available
model names changed multiple times during this project's development (an
earlier default, `gemini-3.5-flash-lite`, did not exist and silently broke
all LLM-based extraction). The last model confirmed working during
development was `gemini-3.1-flash-lite`, but Gemini's model lineup is not
stable enough to hardcode with confidence — run
`genai.list_models()` yourself before recording the final demo or handing
off the repo, and update `.env.example` and this README to match whatever
you actually confirm.

Run the app:

```
uvicorn fkl.main:app --reload
```

**⚠ Confirm this module path.** Earlier drafts of this README (and possibly
this codebase) referenced `fkl.api.main:app`; the module path actually
exercised successfully during development was `fkl.main:app`. Confirm which
one is correct in the current codebase before publishing — a reviewer
hitting an import error on the very first command is the worst possible
first impression.

Open `http://localhost:8000` — upload a PDF, watch it process, and inspect
Facts / Relationships / Rejected Candidates in the tabs (these aggregate
across every document uploaded in this session, not just the most recent
one).

Run the test suite:

```
pytest -v
```

**Note on what the test suite does and doesn't cover:** every existing test
uses `FakeLLMProvider` or a mocked response. A passing suite confirms the
deterministic pipeline (parsing, rule-based table extraction, grounding,
classification logic) is correct — it does **not** exercise a real call to
the configured Gemini model. Several real bugs in this project (see
Additional Notes) were invisible to the test suite for exactly this reason
and were only caught by manually querying the database against real
ingestion runs. If you add CI, a smoke test that makes one real,
key-gated Gemini call would close this gap.

To reset the knowledge layer and start from an empty database:

```
rm fkl.db   # or the path set in DATABASE_URL
```

## Video Demo

[LINK](https://drive.google.com/file/d/1qFKr4kdSrsyX9x8HUnsDFhzbHk6K-58c/view?usp=sharing) — recorded against the locked-down 4-document Solstice/Meridian
synthetic set, with the 3 official Delhivery starter documents pre-loaded
at the start to demonstrate the system running on the actual provided
dataset. Shows all four required cases with source evidence and reasoning
for the first three.

## Approach

Pipeline: **parse → extract → ground → normalise → deduplicate → compare
(relate)**.

- **Parse** (`parse_pdf.py`) — PyMuPDF for text blocks and page structure,
  with a PyMuPDF-first / pdfplumber-fallback strategy for table detection.
  Charts and images are recorded as their own block kind rather than
  silently dropped, so their handling is an observable, auditable outcome.
  Blocks with interleaved/corrupted text (a real, reproducible PDF-parsing
  failure — see Case 4) are flagged and routed to rejection rather than
  accepted as garbled facts.

- **Extract** — two independent, domain-agnostic extractors run in parallel:
  - `extract_table_facts.py`: deterministic, rule-based. No hard-coded
    metric names — any labelled numeric cell with a recoverable
    row/column/unit context becomes a candidate.
  - `extract_text_facts.py`: LLM-based, called only on prose blocks selected
    by a domain-agnostic scoring heuristic (digit density, currency/scale
    words, percentage signs — not a fixed vocabulary of "expected" terms, so
    it isn't tied to any one document's subject matter), under a hard
    per-document call budget to stay within API rate limits, with that
    budget allocated across document sections rather than globally, so one
    densely-worded section can't consume the entire budget and starve
    others.

- **Ground** (`ground_candidates.py`) — the single non-negotiable invariant
  in the system: a candidate only becomes a Fact if its value is
  verbatim-recoverable in the source block's text. No candidate becomes a
  fact on the strength of an LLM's say-so alone. Rejected candidates are
  never discarded — they're persisted to a candidate-audit trail with a
  reason code, browsable via the "Rejected Candidates" tab.

- **Normalise** — units, scale words (crore/lakh/million), and periods are
  parsed into structured fields. Numeric comparisons use a
  precision-derived tolerance (±0.5 / 10^decimal_places of the source
  string) rather than a single hard-coded epsilon. Where a document's
  fiscal-year convention can't be determined explicitly from its own text,
  the period is recorded as unknown rather than assumed — an earlier
  version silently assumed an April–March fiscal year for every "FY"
  string, which would have been wrong for any non-Indian filing.

- **Deduplicate** — facts are deduplicated on normalised content
  (entity/metric/value/period, case- and whitespace-insensitive), not on
  which internal block produced them.

- **Compare** (`build_relationships.py` + `classification.py`) — new facts
  are compared only against facts from other documents (never within the
  same document). Candidate pairs are filtered by **entity-token overlap
  only** before classification is attempted — an earlier design also
  required metric-token overlap to clear a threshold at this stage, but that
  meant two genuinely different phrasings of the same metric (e.g.
  "Revenue" vs. "Turnover," zero shared tokens) could never reach the
  semantic-equivalence check downstream. Metric equivalence is now resolved
  entirely inside `classify()`: a token-overlap score above threshold
  resolves directly; anything below threshold — including zero overlap —
  falls into a gray zone resolved by a budgeted LLM semantic-equivalence
  check, prioritized so pairs with the strongest entity match get first
  claim on that budget. A deterministic decision table then classifies each
  pair as `CORROBORATES`, `LIKELY_CONFLICT`, `RECONCILES` (with an explicit
  reason: different period, different scope, or unit/scale conversion), or
  `INSUFFICIENT_CONTEXT`.

**Architecture:** a layered structure — `domain` (pure models,
classification rules, no I/O), `pipeline` (the stages above, each
independently testable), `application` (orchestration — one
`ingest_document()` entry point, with facts committed independently of
whether downstream relationship-building succeeds, so a bug in comparison
logic can't erase already-grounded facts), `persistence` (SQLite +
repositories), and `api` (FastAPI routes + a server-rendered reviewer UI).
New document types require no schema or code changes — the schema is driven
entirely by what's extractable from the PDF, not a fixed fact taxonomy
(demonstrated by an unrelated cooperative-society notice producing new fact
types — membership counts, trading surplus — with zero code changes).

### Key trade-offs

- **Entity-based blocking instead of a vector/embedding index** — simpler to
  reason about and debug, cheaper to run, and the LLM fallback covers the
  metric-paraphrase gap this leaves. The cost: entity blocking is itself a
  plain token-overlap threshold with no verification that two matched
  "entities" are actually the same legal entity — see Limitations, this is
  a real gap found during testing against the real starter dataset, not
  hypothetical.
- **`FakeLLMProvider` as the default** — makes the system runnable and
  gradeable with zero API key, at the cost of prose-extraction quality and
  semantic matching when running in that mode.
- **Deterministic tolerance math over a single hard-coded epsilon** — more
  correct across the range of precision found in real reports, at the cost
  of being harder to reason about at a glance than "±1%."

### AI tools used

- **Claude** — architecture review, root-cause debugging across several
  multi-session investigations (an invalid default LLM model name, a
  missing-attribute crash from two features integrated without a shared
  field, a blocking-gate design flaw), demo-script planning, and this
  README.
- **Gemini** (`google-generativeai` SDK) — the runtime LLM provider for
  prose fact extraction and semantic metric-equivalence matching.
- **[Antigravity / name your coding agent]** — implementation of every
  pipeline stage, the web UI, and the test suite, working from specific,
  scoped task prompts.

## The Four Required Cases

### 1. Corroboration across documents, differently expressed

Ms. Priya Ahluwalia's role as Independent Director is independently
confirmed in both the 2021 IPO prospectus and the FY23 annual report — two
documents two years apart, matched and classified `CORROBORATES`
(`exact_match`, confidence 0.85) without human intervention.

**Known gap, disclosed honestly:** revenue is also independently stated in
both the annual report (Rs. 4,268.91 million) and the investor deck
(~Rs. 427 Cr) — the same figure in different units, which is a better
illustration of "expressed differently." Both values are correctly
extracted as facts, but the pair does not currently clear the relationship
comparison stage — see Limitations.

### 2. Genuine or likely contradiction

**Disclosed honestly, not forced.** The investor deck states approximately
1,950 employees as of fiscal year end; the annual report gives 1,842 on a
standalone basis and 2,105 on a consolidated basis for the same date — 1,950
doesn't cleanly match either figure, with no reconciling note in either
document. On the current dataset, the classifier does not flag this as
`LIKELY_CONFLICT` — the `LIKELY_CONFLICT` decision path exists and is
covered by unit tests, but has not been observed to fire on real extracted
data from this document set. Rather than manufacture an example, this is
disclosed directly: testing the same decision path against a second,
real-world dataset (the official Delhivery starter documents) did surface
`LIKELY_CONFLICT` verdicts, but also surfaced a more serious bug in the
process (see Case 4 and Limitations) that means those results aren't
trustworthy yet either.

### 3. Apparent contradiction explained by context

Three independently verified examples from the annual report and related
documents:
- **Scope:** 1,842 employees (standalone) vs. 2,105 employees
  (consolidated) as of the same date — reconciled via `different_scope`.
- **Period:** Revenue of ~1,842.60M (nine months ended Sep 2021) vs.
  ~4,268.91M (full year FY23) — reconciled via `different_period`.
- **Reporting basis:** Pro forma income (giving effect to an in-year
  acquisition) vs. reported income for the same period — reconciled via
  `different_scope`.

### 4. Extraction or reasoning failure

Two distinct, real failures — one caught and handled, one caught and not
yet fixed:

- **Extraction failure, handled:** a table with character-interleaved
  column headers (a genuine PDF-parsing artifact, reproduced directly from
  the source PDF, not manufactured) produces corrupted text. The system
  detects this via a coherence heuristic and rejects the resulting
  candidates with reason `suspected_text_corruption` rather than accepting
  garbled values as facts.
- **Reasoning failure, found but not yet fixed:** testing the relationship
  engine against the real Delhivery starter documents surfaced a case where
  two facts about **different, unrelated named entities** — the reporting
  company and an unrelated party referenced in its own disclosure notes —
  were compared and classified `LIKELY_CONFLICT` purely because they shared
  a metric label. This is a direct consequence of loosening the blocking
  gate to catch metric paraphrases (see Approach) without pairing it with a
  same-entity verification step. Diagnosed to root cause; not yet fixed.
  See Limitations for the planned fix.

Audit trail for all rejected/flagged candidates: browsable via
`/api/relationships/rejected-candidates` and the "Rejected Candidates" tab.

## Limitations and Next Steps

- **Highest priority: entity blocking has no same-entity verification.**
  Blocking now runs on entity-token overlap alone (see Approach). This
  correctly let genuine metric paraphrases through, but it means two facts
  about different entities can still be compared if their entity names
  share enough surface tokens or if extraction mislabeled `entity_raw`.
  Found via direct testing against the real starter dataset — see Case 4.
  Next step: verify entity identity (exact match or a resolved canonical-ID
  match) as a hard precondition before any value comparison, independent of
  metric-label similarity.
- **Revenue corroboration across different units is extracted but not yet
  matched.** Both figures (Rs. 4,268.91 million and ~Rs. 427 Cr) are
  correctly extracted as facts; the pair does not currently clear the
  relationship-comparison stage. Root cause not yet isolated — worth a
  targeted regression test for this exact pair before trusting
  unit-conversion corroboration generally.
- **`LIKELY_CONFLICT` is implemented and unit-tested but unproven on clean
  extracted data.** It has fired on the real Delhivery dataset, but
  alongside the entity-blocking bug above, so those specific results aren't
  trustworthy yet. Needs re-validation once the entity-verification fix
  lands.
- **Metric-equivalence LLM check runs under a fixed per-run budget**,
  prioritized by entity-match strength. This is a deliberate cost/rate-limit
  trade-off, not an oversight — but it means larger multi-document knowledge
  layers will see more `INSUFFICIENT_CONTEXT` verdicts on subtle paraphrases
  as document count grows, once the per-run budget is exhausted.
- **Chart and image extraction: [confirm current status before publishing].**
  [If vision-based extraction via the LLM is confirmed working post the
  model-name fix: describe it here, note results are capped at low
  confidence and routed to `needs_review`, never `accepted`, since they
  can't be verbatim-grounded the way text can. If not yet re-verified after
  the model fix: state plainly that charts/images are parsed and recorded
  as their own block kind but not yet reliably extracted into facts.]
- **SQLite + background tasks**: WAL mode and a busy-timeout are configured
  to handle light concurrent ingestion without lock errors. This is not a
  substitute for a real job queue and a concurrent-write database — heavy
  simultaneous multi-PDF uploads in production would need both.
- **The Gemini Python SDK (`google-generativeai`) is end-of-life** per its
  own runtime deprecation warning, not just deprecated — migrating to
  `google-genai` is a known next step, not yet done.

## Additional Notes

A meaningful part of this project's value was in the debugging process
itself, not just the final pipeline. Verified findings from this
development history:

- An invalid default LLM model name (`gemini-3.5-flash-lite`, which does
  not exist) caused every single LLM-based extraction call to fail
  silently — caught only by manually querying real ingestion results
  against the actual database, since the test suite exclusively exercises
  a fake/mocked LLM path and could not, by construction, catch this class
  of bug.
- Two features (a gray-zone semantic-matching path and a per-run coverage
  counter) were each implemented correctly in isolation but referenced a
  shared field (`metric_score`) that neither actually added to the data
  model — a real integration gap between two otherwise-correct pieces of
  work, caught the same way, by inspecting real ingestion output rather
  than trusting a green test suite.
- A blocking-gate design flaw meant two genuinely different phrasings of
  the same metric (zero shared tokens) could never reach the
  semantic-equivalence check meant to catch exactly that case — the
  fallback existed but was unreachable for its primary use case until this
  was found and fixed.
- The entity cross-matching bug described in Case 4 was found the same way:
  by testing against real data and reading actual output rows, not by
  trusting an aggregate relationship count.

**[Verify before keeping]:** earlier notes on this project also referenced
an "ALL-CAPS section heading misread as a company name" bug and a
"duplicate table detection doubling fact counts" bug as fixed. Neither of
these was directly confirmed in the development history reflected in this
README — confirm both actually happened and were fixed before including
them, or remove these two specific claims. Overclaiming fixed bugs is worse
than under-claiming them, especially in a submission whose whole
throughline is honesty about what works and what doesn't.
