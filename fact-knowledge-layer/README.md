# Fact Knowledge Layer

**Evidence-first fact extraction and relationship discovery for PDF documents.**

> A fact knowledge layer is useful only when a reviewer can trace a claimed relationship back to the exact source material, understand why it was classified that way, and see when the system declined to decide.

---

## Quick Start

### Requirements
- Python 3.11+
- A Google Gemini API key (get one free at [aistudio.google.com](https://aistudio.google.com))

### 1. Clone and install

```bash
cd fact-knowledge-layer
pip install -e ".[dev]"
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and set GEMINI_API_KEY=your-key-here
```

For testing without an API key, set `LLM_PROVIDER=fake` in `.env` — the fake provider uses deterministic rules.

### 3. Run

```bash
uvicorn fkl.main:app --reload --port 8000
# Open http://localhost:8000
```

### 4. Upload and test

Upload the three starter PDFs from `../starter-datasets/india-macroeconomy/` via the web UI or API:

```bash
curl -X POST http://localhost:8000/api/documents \
     -F "file=@../starter-datasets/india-macroeconomy/01-india-economic-survey-2024-25-excerpt.pdf"
```

Poll `GET /api/documents/{document_id}` until `status = complete`, then explore facts and relationships.

### 5. Run tests

```bash
pytest tests/ -v
```

---

## Dataset

Three public institutional reports on the Indian economy:

| # | File | Pages | Source |
|---|------|-------|--------|
| 1 | `01-india-economic-survey-2024-25-excerpt.pdf` | 89 | [India Budget](https://www.indiabudget.gov.in) |
| 2 | `02-rbi-annual-report-2024-25-excerpt.pdf` | 100 | [RBI](https://www.rbi.org.in) |
| 3 | `03-imf-india-2025-article-iv-excerpt.pdf` | 95 | [IMF](https://www.imf.org) |

All are public documents. PDFs are not committed to this repository; download from official sources.

---

## Approach

### Architecture

```
PDF upload
   |
   v
Document + ingestion run (SQLite) ──► raw PDF (local upload directory)
   |
   v
PyMuPDF text blocks + dual table extraction (PyMuPDF find_tables + pdfplumber fallback)
   |                        |
   |                        +── deterministic labelled-cell candidates
   +── bounded structured LLM prose candidates (Gemini 3.5 Flash Lite)
                                  |
                                  v
                       grounding gate against SourceBlock
                          | accepted           | rejected / audited
                          v                    v
                    normalized immutable Facts  visible failure signal
                          |
                          v
      deterministic blocking → context/precision comparison → Relationships
                          |
                          v
          FastAPI + small UI: facts, source crop, verdict, decision trace
```

### Key Design Decisions

#### 1. Evidence-first, not extraction-first
Every `Fact` row points to a `source_block` with page index, bounding box, and verbatim text. A candidate is accepted **only** when its value literally appears in the source block text. This means the UI can always show "here is where this fact came from" without pretending the LLM is infallible.

#### 2. Deterministic rules + bounded LLM
Table facts are extracted by deterministic rules (labelled numeric cell with row/column/unit context) using PyMuPDF `find_tables()` (which excels on borderless financial statements) and `pdfplumber` fallback. Prose facts are extracted by Gemini 3.5 Flash Lite with a per-page cap (20 candidates/page) and per-document cap (500 candidates/document). The LLM is never the source of truth — the source block is.

#### 3. Honest uncertainty via the grounding gate
Rejected candidates are persisted in `candidate_audit` and shown in the UI. This is how the system handles ambiguity: not by eliminating failures but by surfacing them. The demo explicitly shows case #4 — a chart-based value that cannot be extracted, and what would improve it.

#### 4. Precision-derived tolerance
Comparison tolerances are derived from the displayed precision of the source value, not a magic global threshold:
- `8,142` (whole crore) → ±0.5 crore
- `6.4%` (1 decimal) → ±0.05%
- `81,415.38` (2 decimals of million) → ±0.005 million

This makes the corroboration of `81,415.38 million ≈ 8,142 crore` traceable and explainable.

#### 5. Incremental ingestion
SHA-256 deduplication prevents re-processing identical files. New documents only compare new facts against existing facts from other documents — old-old pairs are never recomputed.

### Why SQLite, not a graph database
A graph adds a technology dependency without adding correctness. The interesting part is how facts are discovered, grounded, compared, and explained — not the storage format. SQLite is portable, inspectable with standard tools, and sufficient for this prototype. The `relationships` table is a graph in all but name.

### Trade-offs

| Decision | Trade-off |
|----------|-----------|
| Deterministic blocking over ANN | Cheaper, explainable, but may miss metric pairs with wording differences |
| PyMuPDF native tables + pdfplumber | Fast and handles borderless tables, but scanned images require future OCR |
| FastAPI BackgroundTasks over Celery | One-process simplicity, but blocking for large PDFs |
| Gemini 3.5 Flash Lite over heavy models | High speed, predictable rate limits, but requires strict JSON schema enforcement |

---

## Limitations and Next Steps

See [docs/limitations.md](docs/limitations.md) for a full list.

**Most consequential next improvements:**
1. OCR/vision for chart and image blocks
2. Better table header recovery for multi-level headers
3. Phrase embedding as a second blocking pass
4. Production queue for large PDFs

---

## Demo Cases

See [docs/demo-cases.md](docs/demo-cases.md) for the four required cases with evidence cards.

---

## Additional Notes

- **LLM disclosure:** Google Gemini 3.5 Flash Lite is used for prose fact extraction and metric canonicalization with a 15 RPM throttling safeguard. Set `LLM_PROVIDER=fake` to run without any API calls (uses deterministic rules, suitable for testing but lower quality extraction).
- **No credentials committed:** `.env` is gitignored. API keys are never hard-coded.
- **Extension implemented:** Incremental ingestion (SHA-256 dedup + new-only fact comparison).
- **Extensions consciously deferred:** Large-PDF streaming, ANN indexing, graph visualisation, dynamic schema evolution — see limitations doc for reasoning.
- **Sample output:** See `sample-output/` for redacted JSON of facts and relationships from a test run.
- **Automated tests:** 73/73 passing tests covering unit normalisation, classification, grounding gate, and integration endpoints. Run via `pytest tests/ -v` or `npm run test`.
