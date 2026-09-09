# Fact Knowledge Layer - implementation blueprint

This is a build plan, not a product specification. Its priority is a small, reliable,
auditable prototype that a reviewer can run and understand in minutes. The solution must
be implemented against the three supplied Delhivery PDFs; no implementation branch may be
based on a filename, a company name, a page number, or a known fact in those PDFs.

## 0. Submission thesis

> A fact knowledge layer is useful only when a reviewer can trace a claimed relationship
> back to the exact source material, understand why it was classified that way, and see
> when the system declined to decide.

The differentiator is not a graph, a large model, or a long architecture diagram. It is
an evidence-first flow that handles real financial-document ambiguity: reporting scope,
period, units, rounding, and incomplete extraction.

### Scope contract

Build the compulsory core plus **one** extension: incremental ingestion. Do not start
dynamic schema evolution, ANN indexing, OCR, background workers, or graph visualisation until
the demo cases, tests, and video are complete.

| Build now | Explicitly defer |
| --- | --- |
| PDF upload and status polling | Large-PDF streaming/performance work |
| Text and table-cell facts | ANN/FAISS and distributed queues |
| Verifiable text-span and table-cell evidence | Full document ontology/schema induction |
| Context-aware pair classification | OCR for difficult scanned/chart pages |
| UI for facts, evidence, and relationships | Graph database and node-link graph |
| Incremental append-only ingestion | Bulk multi-tenant scaling |

This is intentionally narrower than the original plan. The assignment says a smaller,
understandable prototype is preferred to a large system whose behaviour is unclear.

## 1. Source-correct demo strategy

The supplied source set is:

1. `01-delhivery-prospectus-2022-excerpt.pdf`
2. `02-delhivery-annual-report-fy24-excerpt.pdf`
3. `03-delhivery-q4-fy24-earnings-presentation.pdf`

The old plan's statements that these documents were unavailable and that the implementation
used an India-macroeconomy dataset must be removed entirely. They conflict with the assignment
and will undermine trust.

### Demonstration cases to validate before recording

The following are **validation targets**, not hard-coded rules. The code must find them from
uploaded source content; the test fixtures may assert them after extraction.

| Case | Candidate evidence | Expected outcome |
| --- | --- | --- |
| Corroboration | Annual report PDF page 22 reports FY24 consolidated revenue from operations as `81,415.38` million. The Q4 deck PDF page 17 (printed deck page 16) reports FY24 revenue from services/customers as `8,142` crore. | `CORROBORATES` after million-to-crore conversion and display-precision/rounding tolerance. |
| Reconciliation | The annual-report table on PDF page 22 reports FY24 standalone revenue as `74,540.82` million and consolidated revenue as `81,415.38` million. | `RECONCILES` with `DIFFERENT_SCOPE`; same period, different consolidation scope. |
| Failure | Select a page whose useful values are rendered only in a chart/image or whose table extraction loses a header. | The system shows a visible `REJECTED_UNGROUNDED`/`NEEDS_REVIEW` record, never a fabricated fact. The demo explains that OCR/chart extraction is a next step. |
| Likely/genuine contradiction | Discover a candidate from the actual three PDFs, then manually validate entity, metric, period, scope, unit, precision, and primary evidence before promoting it to the demo. | Only promote if it survives review. Otherwise show a labelled `INSUFFICIENT_CONTEXT` result and continue the source audit; never fake this case. |

The earnings deck expressly notes that totals may not sum because of rounding. Therefore the
revenue pair is an excellent corroboration example, but it must never be called a contradiction
because of the small numerical difference.

### Demo evidence standard

For every displayed case, record this review card in `docs/demo-cases.md`:

```md
## Case: FY24 revenue corroboration
- Uploaded document IDs: ...
- PDF page indexes: annual 22; deck 17
- Printed page labels: annual 40/41 if detected; deck 16
- Source quote/cell context: ...
- Normalisation: 81,415.38 million INR / 10 = 8,141.538 crore INR
- Comparison: 8,141.538 versus 8,142 crore; difference is within the reported whole-crore rounding precision.
- Classification: ...
- Reviewer: <your name>, date: ...
```

The deliberately visible scale calculation is important: the actual figure `81,415.38 million`
equals **₹8,141.538 crore**. The card is a guardrail against exactly the kind of zero-loss unit
error a financial fact layer must avoid.

## 2. Technology choices

Use a conventional Python monolith. It is easy to run, test, and explain.

| Concern | Choice | Why |
| --- | --- | --- |
| Web/API | FastAPI + Uvicorn | Typed request models and automatic API docs. |
| HTML UI | Jinja2 + small vanilla JavaScript | One process; no separate frontend build or node setup. |
| Database | SQLite + SQLAlchemy 2 | Portable submission, inspectable with a standard tool. |
| PDF text/geometry | PyMuPDF (`fitz`) | Fast page text extraction with bounding boxes and source coordinates. |
| Table candidates | pdfplumber | Practical table/cell extraction; use only where it returns header/cell geometry. |
| Validation | Pydantic v2 | Contracts at API, provider, and persistence boundaries. |
| LLM | One configured structured-output provider | Used for candidate facts and semantic canonicalisation, never as the evidence source. |
| Tests | pytest + httpx | Unit, contract, and end-to-end coverage. |
| Formatting/lint | Ruff + Black | A predictable code-quality baseline. |

`Docling` is an optional parser experiment, not a required runtime dependency. Add it only if
it has been tested on the target machine and demonstrably improves a target page. A submission
that installs and runs cleanly is worth more than a sophisticated parser that fails at setup.

## 3. Repository layout

```text
fact-knowledge-layer/
├── README.md
├── pyproject.toml
├── uv.lock                         # commit if using uv
├── .env.example                    # no real secret
├── .gitignore
├── Makefile                         # optional convenience commands
├── src/
│   └── fkl/
│       ├── __init__.py
│       ├── main.py                  # FastAPI application factory
│       ├── config.py                # Settings; fail clearly on missing LLM key
│       ├── api/
│       │   ├── deps.py              # dependency injection
│       │   ├── errors.py            # API error mapping
│       │   └── routers/
│       │       ├── documents.py
│       │       ├── facts.py
│       │       ├── relationships.py
│       │       └── health.py
│       ├── application/
│       │   ├── ingest_document.py   # orchestration use case
│       │   ├── query_facts.py
│       │   ├── compare_new_facts.py
│       │   └── review_case.py
│       ├── domain/
│       │   ├── enums.py
│       │   ├── models.py             # immutable domain/Pydantic models
│       │   ├── evidence.py
│       │   ├── normalisation.py
│       │   └── classification.py
│       ├── pipeline/
│       │   ├── parse_pdf.py
│       │   ├── extract_text_facts.py
│       │   ├── extract_table_facts.py
│       │   ├── ground_candidates.py
│       │   ├── deduplicate.py
│       │   └── build_relationships.py
│       ├── providers/
│       │   ├── llm.py                # protocol/interface only
│       │   ├── openai_provider.py    # one concrete provider
│       │   └── fake_llm.py           # deterministic tests, never production
│       ├── persistence/
│       │   ├── database.py
│       │   ├── orm.py
│       │   ├── repositories.py
│       │   └── migrations/           # Alembic after schema stabilises
│       ├── web/
│       │   ├── templates/
│       │   │   ├── base.html
│       │   │   ├── index.html
│       │   │   ├── document.html
│       │   │   └── fact_detail.html
│       │   └── static/
│       │       ├── app.js
│       │       └── app.css
│       └── observability/
│           ├── logging.py
│           └── run_manifest.py
├── tests/
│   ├── unit/
│   ├── contract/
│   ├── integration/
│   ├── fixtures/
│   │   ├── synthetic/                # small PDFs/text, committed
│   │   └── expected/                 # fixture assertions, not extraction logic
│   └── conftest.py
├── scripts/
│   ├── seed_demo.py
│   ├── audit_demo_cases.py
│   └── export_sample_output.py
├── docs/
│   ├── architecture.md
│   ├── demo-cases.md
│   ├── limitations.md
│   └── decisions/
│       ├── 001-evidence-model.md
│       └── 002-incremental-ingestion.md
├── data/                             # gitignored runtime data
│   ├── uploads/
│   ├── renders/
│   └── fkl.sqlite3
└── sample-output/                    # safe, redacted JSON/screenshots for graders
```

Never put the original PDFs or API keys in Git unless their licences permit it. The README can
tell reviewers how to obtain the public PDFs and can include small, committed sample JSON.

## 4. Data model: facts are immutable claims, evidence is first class

Do not use a graph database. SQLite relationships are easier to inspect and sufficient for this
assignment. A fact has a stable structural envelope; its metric and qualifiers originate from
document content.

### 4.1 Tables

```sql
CREATE TABLE documents (
  id TEXT PRIMARY KEY,
  original_filename TEXT NOT NULL,
  sha256 TEXT NOT NULL UNIQUE,
  stored_path TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  page_count INTEGER,
  status TEXT NOT NULL,               -- queued | processing | complete | failed
  error_message TEXT,
  created_at TEXT NOT NULL,
  completed_at TEXT
);

CREATE TABLE ingestion_runs (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES documents(id),
  pipeline_version TEXT NOT NULL,
  parser_version TEXT NOT NULL,
  model_name TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  facts_created INTEGER NOT NULL DEFAULT 0,
  facts_rejected INTEGER NOT NULL DEFAULT 0,
  relationships_created INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE source_blocks (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES documents(id),
  pdf_page_index INTEGER NOT NULL,     -- one-based index in uploaded PDF
  printed_page_label TEXT,             -- optional: text detected from source footer
  block_kind TEXT NOT NULL,            -- paragraph | table_cell | heading | chart | image
  bbox_json TEXT,                      -- [x0, y0, x1, y1] in PDF coordinates
  text TEXT NOT NULL,
  text_normalised TEXT NOT NULL,
  table_context_json TEXT,             -- row header, col header, table title, cell value
  content_hash TEXT NOT NULL
);

CREATE TABLE facts (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES documents(id),
  ingestion_run_id TEXT NOT NULL REFERENCES ingestion_runs(id),
  evidence_block_id TEXT NOT NULL REFERENCES source_blocks(id),
  entity_raw TEXT NOT NULL,
  metric_raw TEXT NOT NULL,
  metric_key TEXT,                     -- LLM/rule-derived generic canonical text
  value_raw TEXT NOT NULL,
  numeric_value REAL,
  value_kind TEXT NOT NULL,            -- numeric | date | text | boolean
  unit_raw TEXT,
  unit_dimension TEXT,                 -- currency | percentage | count | unknown
  scale_raw TEXT,                      -- million | crore | thousands | null
  normalised_value REAL,
  normalised_unit TEXT,
  period_raw TEXT,
  period_start TEXT,
  period_end TEXT,
  scope_json TEXT NOT NULL DEFAULT '{}',
  qualifiers_json TEXT NOT NULL DEFAULT '{}',
  extraction_method TEXT NOT NULL,     -- text_llm | table_rule
  confidence REAL NOT NULL,
  review_state TEXT NOT NULL,          -- accepted | needs_review | rejected
  created_at TEXT NOT NULL
);

CREATE TABLE relationships (
  id TEXT PRIMARY KEY,
  left_fact_id TEXT NOT NULL REFERENCES facts(id),
  right_fact_id TEXT NOT NULL REFERENCES facts(id),
  reason_code TEXT NOT NULL,
  verdict TEXT NOT NULL,               -- corroborates | reconciles | likely_conflict | insufficient_context
  explanation TEXT NOT NULL,
  comparison_json TEXT NOT NULL,       -- all normalized fields and rule decisions
  confidence REAL NOT NULL,
  review_state TEXT NOT NULL,          -- automatic | human_verified | rejected
  created_by_run_id TEXT NOT NULL REFERENCES ingestion_runs(id),
  UNIQUE(left_fact_id, right_fact_id)
);
```

### 4.2 Evidence invariant

Persist a fact only when all of these are true:

1. It points to one `source_blocks` record from the uploaded PDF.
2. Its value appears in that block's exact extracted text or table-cell value.
3. The page index and bounding box are present.
4. Its entity/metric/period assumptions are either literally supported by the block context or
   stored as uncertain/null.

For prose, `source_blocks.text` is a literal source excerpt. For tables, it is a compact,
reproducible source representation such as:

```json
{
  "table_title": "Financial Performance",
  "row_header": "Revenue from Operations",
  "column_header": "Consolidated - FY ended March 31, 2024",
  "cell_value": "81,415.38",
  "unit": "₹ in Million"
}
```

This is better than trying to claim that a row label, a multilevel column header, and a cell
value form one contiguous character span. The UI renders that context and links to the original
page/crop.

### 4.3 Required enums

```python
class Verdict(StrEnum):
    CORROBORATES = "corroborates"
    RECONCILES = "reconciles"
    LIKELY_CONFLICT = "likely_conflict"
    INSUFFICIENT_CONTEXT = "insufficient_context"

class ReasonCode(StrEnum):
    EXACT_MATCH = "exact_match"
    ROUNDED_MATCH = "rounded_match"
    ALIAS_MATCH = "alias_match"
    DIFFERENT_PERIOD = "different_period"
    DIFFERENT_SCOPE = "different_scope"
    UNIT_OR_SCALE_DIFFERENCE = "unit_or_scale_difference"
    METHODOLOGY_DIFFERENCE = "methodology_difference"
    MATERIAL_VALUE_DIFFERENCE = "material_value_difference"
    LOW_EVIDENCE_QUALITY = "low_evidence_quality"
    INSUFFICIENT_CONTEXT = "insufficient_context"
```

No free-text explanation can override the rule-derived `verdict` or `reason_code`.

## 5. Module-by-module implementation contracts

### `config.py`

Use `pydantic-settings`. Settings include `DATABASE_URL`, `UPLOAD_DIR`, `LLM_PROVIDER`,
`LLM_MODEL`, `LLM_API_KEY`, `MAX_UPLOAD_MB`, and `PIPELINE_VERSION`. Production startup raises a
human-readable error when a selected provider needs a missing key. Tests use `FakeLLM` and never
read an external credential.

### `pipeline/parse_pdf.py`

Input: `document_id`, stored PDF path. Output: `list[SourceBlock]` plus page count.

Algorithm:

1. Open with PyMuPDF and obtain one-based `pdf_page_index`.
2. Extract text blocks using `page.get_text("blocks", sort=True)`; discard whitespace-only blocks.
3. Normalise only for matching: collapse whitespace, convert non-breaking spaces, preserve raw
   source text separately.
4. Infer an optional printed-page label only from obvious page-footer/header text. Never replace
   the durable PDF page index with it.
5. For each page run pdfplumber table extraction. Persist table cells only when row/column
   context can be identified. Do not turn an unlabeled grid of numbers into facts.
6. Record chart/image blocks as `block_kind=chart` or `image` so that their non-extraction is
   observable rather than invisible.
7. Save `SourceBlock` rows before any LLM call so every later candidate has an anchor.

Failure behaviour: malformed/encrypted PDFs set the document job to `failed` with a safe error;
one bad page yields a page-level warning and the remaining pages continue.

### `providers/llm.py`

Define a protocol so the pipeline is independent of a vendor:

```python
class FactExtractionProvider(Protocol):
    def extract_facts(self, *, block: SourceBlock, document_context: str) -> list[FactCandidate]: ...
    def canonicalise_metric(self, *, left: Fact, right: Fact) -> MetricMatch: ...
    def explain_relationship(self, *, comparison: ComparisonResult) -> str: ...
```

`FactCandidate` must be a strict Pydantic schema. It includes `entity_raw`, `metric_raw`,
`value_raw`, `unit_raw`, `period_raw`, `scope`, and `evidence_quote`. Include `evidence_quote`
only to validate it; it never replaces the source block.

Prompt rules:

- Extract only claims expressed in the supplied block/context.
- Do not calculate a missing value or infer an unstated date/scope.
- Return `[]` if there is no useful fact.
- For a numeric candidate, quote the literal value and source phrase/table context.
- Do not use document filename or source-set-specific examples in prompts.

Use structured output / JSON schema. That guarantees parseable shape, not truth; grounding is the
next mandatory stage.

### `pipeline/extract_table_facts.py`

This is deterministic and covers well-formed financial tables.

1. Identify header rows and leftmost row labels.
2. For each numeric cell, form `TableCellContext` from nearest title, row header, all applicable
   column-header levels, unit note, cell text, and coordinates.
3. Create a candidate only if its row header is semantic (for example, `Revenue from Operations`),
   not a generic heading (`FY24`, `Particulars`, `Total`).
4. Parse signs expressed by parentheses, commas, percentage suffixes, currencies, and footnote
   markers. Preserve the untouched original in `value_raw`.
5. Flag, rather than guess, merged cells, repeated headers, or ambiguous unit placement.

Do **not** implement metrics specifically for Delhivery. The generic rule is "labelled numeric
cell with recoverable row, column, and unit context."

### `pipeline/extract_text_facts.py`

Call the LLM only on compact blocks: a paragraph plus nearest heading, never an entire PDF.

```python
for block in prose_blocks:
    candidates = provider.extract_facts(block=block, document_context=nearby_heading)
    enqueue_for_grounding(candidates, block)
```

Set a per-page and per-document candidate cap (for example 20/page, 500/document) to contain
cost and pathological model output. Log token/call count in the ingestion run.

### `pipeline/ground_candidates.py`

This is the most important file.

```python
def ground(candidate: FactCandidate, block: SourceBlock) -> GroundingResult:
    quote_ok = normalise(candidate.evidence_quote) in normalise(block.text)
    value_ok = normalise(candidate.value_raw) in normalise(block.text)
    required = [candidate.entity_raw, candidate.metric_raw, candidate.value_raw]
    missing = [field for field in required if not field.strip()]
    if missing or not value_ok:
        return Rejected(reason="value_or_quote_not_found")
    return Accepted(evidence_block_id=block.id, confidence=score(...))
```

For a table candidate, bypass substring assumptions and validate that `candidate.value_raw`
equals the stored `cell_value`, while row/column/unit come from the stored table context.

Rejected candidates are persisted in a small `candidate_audit` table or JSON run manifest with
their rejection reason. They are not facts and cannot participate in relationships.

### `domain/normalisation.py`

Keep raw and normalized values side by side. Implement only transparent transformations:

- Currency scale: INR million to crore divides by 10; crore to million multiplies by 10.
- Percent: `6.5%` becomes `6.5`, unit `percent`, never `0.065` unless a formula explicitly asks.
- Parentheses: `(249)` becomes `-249` with display value preserved.
- Period: parse `FY24`, `FY 2023-24`, `Q4 FY24`, and explicit calendar dates when unambiguous.
- Scope: extract simple source-backed terms such as `standalone`, `consolidated`, `company`,
  `group`, `service`, or `segment`; otherwise retain null/unknown.

Every transformation returns a provenance object:

```json
{
  "operation": "scale_conversion",
  "input": "81,415.38",
  "input_unit": "₹ million",
  "output": 8141.538,
  "output_unit": "₹ crore",
  "rule_version": "1.0"
}
```

Never use a magic universal 0.5% conflict threshold. Derive tolerance from reported precision:

```python
def rounding_tolerance(raw: str, scale: float) -> float:
    # 8,142 shown to the nearest whole crore permits +/- 0.5 crore.
    # 81,415.38 shown to two decimals of million permits +/- 0.005 million.
    return half_of_last_displayed_unit(raw) * scale
```

### `pipeline/build_relationships.py`

For this small dataset, use deterministic blocking, not embeddings or ANN. It is faster to build,
cheaper to run, and easier to explain.

1. Build keys from normalized entity tokens, metric tokens, value kind, and compatible unit
   dimension.
2. Compare new accepted facts only with accepted facts from a different document whose keys
   overlap. A simple SQLite/SQL query is sufficient.
3. Optionally call `canonicalise_metric` only for pairs that pass deterministic blocking but have
   wording differences. Record this as an input signal, not ground truth.
4. Apply the decision table below.
5. Generate an explanation from the computed `ComparisonResult`; validate that it contains no
   values absent from the comparison payload.

| Preconditions | Verdict | Reason code |
| --- | --- | --- |
| Metric/entity/period/scope align; normalized values overlap under display precision | `corroborates` | `exact_match` or `rounded_match` |
| Metric/entity align but period differs | `reconciles` | `different_period` |
| Metric/entity/period align but source-backed scope differs | `reconciles` | `different_scope` |
| Metric/entity/period align and conversion makes values overlap | `reconciles` or `corroborates` | `unit_or_scale_difference` |
| Metric/entity/period/scope align; high-quality evidence; values do not overlap | `likely_conflict` | `material_value_difference` |
| Any material field is unknown, ambiguous, or evidence weak | `insufficient_context` | `insufficient_context` |

`likely_conflict` is never auto-promoted to a "genuine contradiction". The UI must show a
`Verify evidence` badge. A human reviewer can mark the exact relationship `human_verified` once
both original PDF pages have been checked.

### `application/ingest_document.py`

This is the single orchestration use case:

```python
def ingest(document_id: str) -> IngestionSummary:
    run = runs.start(document_id, versions=settings.versions)
    blocks = parser.parse(documents.path(document_id))
    blocks_repo.insert(blocks)
    raw_candidates = table_extractor.extract(blocks) + text_extractor.extract(blocks)
    accepted, rejected = grounding.validate(raw_candidates, blocks)
    facts = normaliser.normalise_and_make_facts(accepted, run.id)
    facts_repo.insert_many(facts)
    relationships = matcher.compare_new_facts(new=facts, existing=facts_repo.others(document_id))
    relationships_repo.insert_many(relationships)
    return runs.complete(run, counts=...)
```

Wrap each stage with structured logs and stage timings. On a failure, mark the run/document
failed, retain raw file and diagnostics, and do not claim a partial upload is complete.

## 6. Incremental-ingestion extension

This is the only brownie-point extension because it naturally follows from clean data ownership.

Rules:

1. SHA-256 deduplicates identical uploaded bytes. Re-uploading a file returns its existing
   document ID and does not create duplicate facts.
2. A newly uploaded document creates new blocks and facts only for that document.
3. Existing documents, blocks, facts, and their extraction runs are never mutated or re-extracted.
4. Only pairs touching a new fact are evaluated. The relationship run can add new cross-document
   edges, but it does not recompute old-old pairs.
5. The demo shows run manifests before and after the third upload: old fact counts unchanged,
   `reparsed_document_count = 1`, and every new relationship has at least one new fact.

This is a truthful incremental claim without pretending to have solved billion-document ANN
indexing.

## 7. API contract

### `POST /api/documents`

Multipart field `file`. Validate PDF MIME/signature and maximum size. Store a UUID filename, not
the user-provided filename. Response:

```json
{"document_id":"doc_...","status":"queued","deduplicated":false}
```

Use FastAPI `BackgroundTasks` for the demo. State in the README that a persistent queue is a
next step for long jobs.

### `GET /api/documents/{document_id}`

Returns status, page count, facts/relationship totals, warnings, current/past ingestion run IDs,
and failure message if any.

### `GET /api/facts`

Filters: `document_id`, `entity`, `metric`, `review_state`, `page`, `limit`. Returns paginated
facts with a concise evidence preview, never the whole PDF blob.

### `GET /api/facts/{fact_id}`

Returns the raw and normalized fields, normalization provenance, table/text evidence context,
page index, coordinates, and an image/PDF-page URL.

### `GET /api/facts/{fact_id}/relationships`

Returns the pair, verdict, reason code, comparison payload, explanation, evidence for *both*
facts, and human-review state.

### `POST /api/relationships/{relationship_id}/review`

Local-demo endpoint, no authentication. Allows `human_verified` or `rejected` with a short note.
It is valuable because it makes the "likely conflict" safety rule visible.

### `GET /api/documents/{document_id}/pages/{page_index}`

Streams a rendered page PNG or a PDF range/page link. The UI uses it to show the evidence crop;
never pretend an extracted quote alone is sufficient proof.

## 8. UI specification

One responsive page is enough.

```text
┌ Upload PDF ───────────────── document status/progress ───────────────────┐
│ [Choose PDF] [Upload]        Complete: 47 facts, 6 relationships          │
├ Filters ─────────────────── Fact table ───────────────────────────────────┤
│ document | metric | state    Entity | Metric | Value | Period | Evidence  │
├ Selected fact ────────────── Relationship/evidence panel ─────────────────┤
│ Raw + normalized value       Verdict: Reconciles - DIFFERENT_SCOPE         │
│ Page 22, source crop         Left evidence       Right evidence             │
│ Row/column/table context     Normalisation and decision trace              │
└───────────────────────────────────────────────────────────────────────────┘
```

Required interaction details:

- Poll job status every two seconds while processing; stop polling on completion/failure.
- A fact row always shows raw value and period; normalized values are detail-only, never hidden.
- Relationship cards use text labels and colour but never colour alone.
- `needs_review`, `rejected`, and `insufficient_context` have equally visible presentation.
- Evidence opens the source page plus a highlighted/cropped bounding box. If crop rendering
  fails, show the page index and verbatim evidence context instead.

## 9. Test plan

The test suite should prove properties, not just show screenshots.

### Unit tests

| File | Key assertions |
| --- | --- |
| `test_normalisation.py` | crore/million conversion, negative parentheses, percentages, FY/Q parsing, rounding tolerance. |
| `test_grounding.py` | fabricated value rejected; literal source value accepted; table cell needs label and unit context. |
| `test_classification.py` | exact match, rounded match, period reconciliation, scope reconciliation, conflict, insufficient context. |
| `test_incremental.py` | only new facts become left/right side of new comparisons; old facts unchanged. |
| `test_prompt_contract.py` | fake provider payload must validate strict candidate schema. |

### Integration tests

1. Upload a small synthetic PDF and poll until complete.
2. Assert every accepted fact has document ID, source block, page index, evidence text/context,
   and source coordinates.
3. Upload synthetic documents representing the same metric in million and crore; assert a rounded
   corroboration.
4. Upload standalone and consolidated facts; assert `different_scope`, not conflict.
5. Upload the same bytes twice; assert deduplication and no additional fact rows.
6. Force parser/LLM failure; assert status `failed`/warning and no false completion.

### Manual validation gate

Before recording, inspect at least 20 stratified accepted facts:

- 10 table-derived and 10 prose-derived where available;
- mixed confidence levels and all three documents;
- independently check quoted value, row/column/period/scope, and page/crop;
- publish result as `18/20 correct in this sampled audit`, not an invented global accuracy score.

Any mismatch becomes either a fix or the documented failure case.

## 10. Build sequence and commits

Do not create a fake commit history. Make real, narrow commits as each tested milestone works.

| Milestone | Deliverable | Suggested commit |
| --- | --- | --- |
| 0 | Scaffold, CI/lint, health endpoint, README run command | `chore: scaffold FastAPI fact layer` |
| 1 | Upload, SHA storage, SQLite documents/jobs, status page | `feat: add PDF upload and ingestion status` |
| 2 | PyMuPDF blocks with page/bbox evidence, page rendering | `feat: persist source blocks with PDF coordinates` |
| 3 | Deterministic table extractor and numerical normalization tests | `feat: extract grounded table facts` |
| 4 | Structured text extraction, grounding/rejection audit | `feat: add grounded prose fact extraction` |
| 5 | Pair blocking and decision-table classifier | `feat: classify fact relationships with context` |
| 6 | Fact/relationship detail UI and evidence crop | `feat: expose inspectable evidence UI` |
| 7 | Incremental-ingestion invariants and demo manifest | `feat: compare new document facts incrementally` |
| 8 | Audit target docs, demo script, sample output, video | `docs: add validated demo cases and limitations` |

**Cut line:** if milestone 5 is not robust, do not begin milestone 7. Polish the core and four
cases instead. A working core with no extension is preferable to an unfinished extension.

## 11. README and video plan

### README outline

1. **Setup and Run Instructions** - one copy/paste install path, environment variables, and
   sample-data command. State exact Python version.
2. **Video Demo** - direct video link, duration under three minutes.
3. **Approach** - one diagram, evidence model, extraction/grounding/comparison flow, and why
   SQLite plus deterministic rules were chosen.
4. **Limitations and Next Steps** - no OCR/chart extraction, no production queue, heuristic
   table parser, semantic matching limitations, and source-audit sample result.
5. **Additional Notes** - LLM/provider disclosure, no credentials, data-source links/licensing,
   and incremental-ingestion boundary.

### Three-minute recording script

| Time | What is visible | What you say |
| --- | --- | --- |
| 0:00-0:20 | README and running app | State the evidence-first problem and no-hardcoding design. |
| 0:20-0:45 | Upload a PDF and status changes | Show real processing, not a preloaded screen. |
| 0:45-1:20 | Corroborated revenue pair | Show both source pages, scale conversion, rounding rule, and verdict. |
| 1:20-1:45 | Standalone vs consolidated pair | Show same-period scope distinction and `DIFFERENT_SCOPE`. |
| 1:45-2:10 | Verified likely conflict | Show both evidence pages and review badge. If no valid candidate exists, do not conceal it; explain the source audit is incomplete and do not claim this case is done. |
| 2:10-2:30 | Failure/rejection record | Show an ungrounded/chart or malformed-table extraction rejected with reason. |
| 2:30-2:50 | Upload third document / run manifest | Demonstrate only new facts were parsed/compared. |
| 2:50-3:00 | Limitations page | Name the most consequential next improvements honestly. |

## 12. Architecture diagram

```text
PDF upload
   |
   v
Document + ingestion run (SQLite) ----> raw PDF (local upload directory)
   |
   v
PyMuPDF text blocks + pdfplumber table cells
   |                        |
   |                        +-- deterministic labelled-cell candidates
   +-- bounded structured LLM prose candidates
                                  |
                                  v
                       grounding gate against SourceBlock
                          | accepted           | rejected/audited
                          v                    v
                    normalized immutable Facts  visible failure signal
                          |
                          v
      deterministic blocking -> context/precision comparison -> Relationships
                          |
                          v
          FastAPI + small UI: facts, source crop, verdict, decision trace
```

## 13. Non-negotiable quality gates before submission

- `ruff check .`, `black --check .`, and `pytest` pass in a clean environment.
- A fresh clone runs using the README alone.
- An unseen PDF can be uploaded without filename-specific logic or manual database edits.
- Every accepted fact has evidence, a one-based PDF page index, coordinates, and raw source text
  or table-cell context.
- Every displayed relation includes two evidence objects and a machine-readable reason code.
- No relationship has been presented as a genuine conflict without a human side-by-side source
  review.
- The four required demo cases are captured in `docs/demo-cases.md`; no case is fabricated.
- `.env`, uploads, SQLite runtime data, and generated renders are ignored by Git.
- `git log` reflects the actual staged build.

## 14. What makes this competitive

Most submissions will show a chat-with-PDF wrapper or a graph. This implementation wins by
making truth conditions visible: it distinguishes source text from model output, raw values from
normalized values, a rounded match from a conflict, scope reconciliation from an error, and a
rejected candidate from a missing result. That is sophisticated engineering without pretending
to be a production data platform.
