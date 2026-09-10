# Fact Knowledge Layer (FKL)

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![PyMuPDF](https://img.shields.io/badge/PyMuPDF-1.24+-red.svg)](https://pymupdf.readthedocs.io/)
[![Gemini 3.5 Flash Lite](https://img.shields.io/badge/LLM-Gemini%203.5%20Flash%20Lite-4285F4.svg?logo=google&logoColor=white)](https://aistudio.google.com/)
[![SQLite](https://img.shields.io/badge/Storage-SQLite-003B57.svg?logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![Tests Passing](https://img.shields.io/badge/Tests-87%2F87%20Passing-brightgreen.svg)](#running-tests)

> **Evidence-first fact extraction, normalisation, and relationship discovery for financial and economic PDF documents.**

---

## 💡 Core Philosophy & Thesis

> *"A fact knowledge layer is useful only when a reviewer can trace a claimed relationship back to the exact source material, understand why it was classified that way, and see when the system declined to decide."*

In high-stakes financial and macro analysis, an opaque LLM extraction engine is a liability. Hallucinated numbers, ungrounded syntheses, and uncalibrated certainty degrade analyst trust. 

**Fact Knowledge Layer (FKL)** is designed around four foundational pillars:
1. **Verifiable Grounding Gate**: Every accepted fact is mathematically bound to a physical `source_block` (page number, bounding box coordinates, and verbatim text). If a candidate number cannot be found verbatim in the source block, it is **strictly rejected**.
2. **Honest Handling of Failure & Ambiguity**: The system explicitly discloses what it cannot extract (e.g., charts, vector graphics, ungrounded propositions) via `/api/relationships/rejected-candidates` and an audit trail.
3. **Display-Precision Tolerances**: Numeric comparisons derive their tolerances from the display precision of the original source text (e.g., `8,142` whole crore implies $\pm0.5$ crore; `6.4%` implies $\pm0.05\%$; `81,415.38` implies $\pm0.005$ million), allowing deterministic unit-converted cross-document corroboration.
4. **Zero Document-Specific Hardcoding**: The pipeline generalizes out-of-the-box to unseen PDFs across varying layouts, borderless financial tables, and institutional reports without relying on company names, filenames, or hardcoded page branches.

---

> 📖 **Complete Architecture & Pipeline Deep Dive:** See [ARCHITECTURE_AND_PIPELINE.md](ARCHITECTURE_AND_PIPELINE.md) for detailed function specifications, prompt engineering schemas, rate-limiting algorithms, and precision tolerance formulas.

## 🏛️ System Architecture

```mermaid
flowchart TD
    A[PDF Upload] --> B[PyMuPDF Parser]
    B --> C1[Borderless & Grid Table Extraction\nPyMuPDF find_tables + pdfplumber fallback]
    B --> C2[Prose & Narrative Text Blocks\nMulti-column text layout]
    
    C1 --> D1[Deterministic Table Fact Candidates\nRow header + Column header + Unit/Footnote context]
    C2 --> D2[Bounded LLM Prose Candidates\nGemini 3.5 Flash Lite / Structured Extraction]
    
    D1 --> E[GROUNDING GATE]
    D2 --> E
    
    E -- Rejected (Ungrounded / Chart / Missing) --> F[Candidate Audit Log\nTransparent Failure Disclosure]
    E -- Accepted (Verbatim Evidence Verified) --> G[Fact Normalisation Engine\nMetric Canonicalisation | Period Anchoring | Unit Scale]
    
    G --> H[(SQLite Database\nImmutable Fact Store)]
    H --> I[Incremental Deduplication & Blocking Engine\nSHA-256 Checksum | Only New-vs-Existing Pairs]
    
    I --> J[Pairwise Comparison & Classification]
    J --> K1[CORROBORATES\nWithin precision tolerance]
    J --> K2[RECONCILES\nDifferent period, scope, or accounting standard]
    J --> K3[LIKELY_CONFLICT\nMaterial numerical divergence flagged for human review]
    J --> K4[NO_RELATION]
    
    K1 & K2 & K3 & K4 --> L[(Relationships Store)]
    L --> M[FastAPI + Responsive Reviewer UI\nSide-by-side evidence, page bbox crops, audit trail]
```

---

## 🎯 The Four Key Demonstration Cases

All four cases are validated against real institutional reports (`Economic Survey 2024-25`, `RBI Annual Report 2024-25`, `IMF Article IV 2025`):

| Case | Relationship | Left Document & Fact | Right Document & Fact | System Decision & Rationale |
| :--- | :--- | :--- | :--- | :--- |
| **1. Corroboration** | `CORROBORATES` | **Economic Survey 2024-25**<br>`GST Revenue = 8.9` | **RBI Annual Report 2024-25**<br>`Revenue = 8.9` | **Exact numerical match (diff: 0.0)**.<br>Both institutions cite primary GSTN figures. The system normalises metric representations and confirms corroboration within precision limits. |
| **2. Reconciliation** | `RECONCILES` | **RBI Annual Report 2024-25**<br>`Cement Production = 12.7`<br>*(Period: FY 2023-24)* | **IMF India 2025 Article IV**<br>`Cement = 4.2`<br>*(Period: CY 2014)* | **Reconciled by Period**.<br>Values differ substantially (12.7 vs 4.2), but temporal anchoring resolves distinct reporting windows (FY24 vs CY14), preventing false contradictions. |
| **3. Likely Conflict** | `LIKELY_CONFLICT` | **IMF India 2025 Article IV**<br>`Cement = 8.3`<br>*(Period: CY 2023)* | **RBI Annual Report 2024-25**<br>`Cement Production = 12.7`<br>*(Period: FY 2023-24)* | **Material Value Difference (Diff: 4.4, Tol: ±0.1)**.<br>Overlapping periods with material divergence. Flagged with `LIKELY_CONFLICT` and a *"Verify Evidence"* badge for human analyst review rather than unearned automated certainty. |
| **4. Failure Disclosure** | `REJECTED_UNGROUNDED` | **RBI Annual Report 2024-25**<br>*(Chart 1: R&D Expenditure & GDP Per Capita)* | N/A (Candidate Audit) | **Explicit Abstention**.<br>Visual chart detected; parser logs `source_block_is_chart_or_image` in `candidate_audit`. Disclosed transparently in UI and via API. Never hallucinates unsupported facts. |

*(Detailed evidence cards and JSON snapshots are available in [fact-knowledge-layer/docs/demo-cases.md](fact-knowledge-layer/docs/demo-cases.md) and [sample-output/](fact-knowledge-layer/sample-output/)).*

---

## 🚀 Quick Start

### Prerequisites
- **Python 3.11+** installed
- **Node.js 18+** (optional, for root `npm` shortcuts)
- Google Gemini API key ([Get one free from Google AI Studio](https://aistudio.google.com))

### 1. Installation

You can run commands from the root directory or inside `fact-knowledge-layer/`:

```bash
# Clone the repository
git clone https://github.com/riyaayay/superjoin.git
cd superjoin

# Install Python package in editable mode
cd fact-knowledge-layer
pip install -e ".[dev]"
```

### 2. Configure Environment Variables

```bash
# Inside fact-knowledge-layer directory
cp .env.example .env
```

Edit `.env` to configure your API key:
```ini
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-3.5-flash-lite
LLM_PROVIDER=gemini
APP_ENV=development
```

> **Note:** To run completely offline without an API key, set `LLM_PROVIDER=fake`. The fake provider uses deterministic heuristic rules for candidate extraction and pair classification.

### 3. Launch Development Server

From the root directory:
```bash
npm run dev
```

Or using Python directly:
```bash
cd fact-knowledge-layer
python -c "import sys; sys.path.insert(0, 'src'); import uvicorn; uvicorn.run('fkl.main:app', host='127.0.0.1', port=8000, reload=True)"
```

Open your browser at **[http://127.0.0.1:8000](http://127.0.0.1:8000)**.  
Interactive OpenAPI/Swagger documentation is available at **[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)**.

---

## 🧪 Testing & Verification

The test suite includes 73 automated tests covering:
- Unit tests for deterministic normalisation (currencies, percentages, millions-to-crores, dates).
- Grounding gate acceptance and rejection logic.
- Rule-based and LLM pair classification.
- Incremental ingestion and SHA-256 deduplication.
- End-to-end FastAPI integration endpoints.

Run all tests:
```bash
# Root shortcut
npm run test

# Or directly with pytest
cd fact-knowledge-layer
pytest tests/ -v
```

Run demo case audit:
```bash
npm run audit
```

---

## ⚡ Key Engineering Highlights

### 1. Dual-Engine Table Extraction (Generalisation to Unseen Layouts)
Financial statements often use borderless, line-free tables that break standard line-detection extractors. FKL implements a resilient dual-strategy:
- **PyMuPDF `find_tables()`**: Uses word bounding-box clustering to accurately identify table columns and header bands even in completely borderless financial layouts (e.g. Solstice Robotics FY23 statement).
- **Fallback to `pdfplumber`**: For structured bordered grid layouts.
- **Context Preservation**: Extracts table titles, currency/unit statements (e.g., *(in $ Millions)* or *(in ₹ Crore)*), and footnote reference columns (`Note 18`, `Ref`).

### 2. Grounding Gate
Before any candidate number becomes an immutable `Fact`:
- The candidate's raw value must be found verbatim within the text of its associated `SourceBlock`.
- Metric names are canonicalized without altering numerical ground truth.
- Failed extractions are logged with structured rejection reasons (`source_block_is_chart_or_image`, `value_not_found_in_block_text`).

### 3. Precision-Aware Comparison & Unit Normalisation
- Scales metrics across international and Indian financial denominations (Million, Billion, Crore, Lakh).
- Comparison tolerances are dynamically anchored to the number of significant digits in the source document.
- Overlapping periods are reconciled via ISO 8601 date ranges (`YYYY-MM-DD`).

### 4. Incremental Ingestion
- Uploading an existing file triggers an instant cache hit via SHA-256 checksum comparison.
- When new documents are ingested, fact pair comparisons are strictly bounded to $(Facts_{new} \times Facts_{existing})$. Prior pairs are never re-evaluated.

### 5. Architectural Generalization & Diagnosed Fixes (Fixes 1–7)
To ensure robust generalization over diverse corporate filings (e.g. Reliance, Tata Motors) and economic reports:
- **Fix 1 (Canonical Entity Resolution)**: Resolves document-level corporate identity (`resolve_canonical_entity`) and strictly prevents table captions (e.g. *"Consolidated Statement of Profit and Loss"*) from masquerading as entities.
- **Fix 2 (2D Disjoint Blocking Gate)**: Evaluates entity overlap ($\ge 0.25$) and metric overlap ($\ge 0.35$) independently, eliminating false matches between unrelated companies or distinct line items.
- **Fix 3 (Mandatory Metric Equivalence Gate)**: Mandates positive metric equivalence (`metric_equivalent is True`) before allowing `CORROBORATES` or `LIKELY_CONFLICT`, demoting non-equivalent comparisons to `INSUFFICIENT_CONTEXT`.
- **Fix 4 (Confidence Thresholds to Review States)**: Automatically flags facts with grounding confidence $< 0.65$ as `NEEDS_REVIEW` rather than `ACCEPTED`.
- **Fix 5 (Semantic Qualitative Extraction)**: Extracts corporate appointments, resignations, and governance events as `ValueKind.TEXT` with full verbatim grounding.
- **Fix 6 (Period Parsing & Parenthesis Balancing)**: Automatically balances truncated table headers (e.g. `(Audited`) and parses dates like `Year ended 31.03.2023`.
- **Fix 7 (Prose Extraction Transparency)**: Tracks and displays `blocks_skipped_due_to_cap` directly on the document dashboard whenever prose extraction is capped.

---

## 🌐 API Overview

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/documents` | Upload a PDF document for asynchronous ingestion |
| `GET` | `/api/documents` | List all ingested documents and their status |
| `GET` | `/api/documents/{id}` | Ingestion status, page count, canonical entity, and run stats |
| `GET` | `/api/facts` | Query extracted facts with filtering by metric, period, or entity |
| `GET` | `/api/facts/{id}` | Detailed fact view including verbatim source block coordinates |
| `GET` | `/api/relationships` | Query classified relationships (`corroborates`, `reconciles`, `likely_conflict`) |
| `GET` | `/api/relationships/rejected-candidates` | Audited rejected candidates with explicit failure reasons |

---

## 📂 Repository Structure

```
superjoin/
├── README.md                                  # Repository overview and guide (this file)
├── ARCHITECTURE_AND_PIPELINE.md               # Deep technical specification & model prompt analysis
├── package.json                               # Root workspace orchestration scripts
├── superjoin-implementation-blueprint.md      # Implementation blueprint and requirements
├── starter-datasets/                          # Evaluation datasets
│   └── india-macroeconomy/                    # Institutional economic reports (Economic Survey, RBI, IMF)
└── fact-knowledge-layer/                      # Core application package
    ├── pyproject.toml                         # Python dependencies & build config
    ├── .env.example                           # Environment configuration template
    ├── Makefile                               # CLI build shortcuts
    ├── docs/
    │   ├── demo-cases.md                      # Detailed evidence cards for the 4 demo cases
    │   └── limitations.md                     # Transparent disclosure of technical limitations
    ├── sample-output/                         # Sample facts, relationships, and rejected audits
    ├── scripts/                               # Seeding, audit, and diagnostic utilities
    ├── src/fkl/
    │   ├── api/                               # FastAPI routes (documents, facts, relationships)
    │   ├── application/                       # Ingestion orchestration & workflows
    │   ├── domain/                            # Core models, enums, normalisation, and classification
    │   ├── persistence/                       # SQLite schema, ORM, and repositories
    │   ├── pipeline/                          # PDF parsing, table extraction, grounding, relationships
    │   ├── providers/                         # Gemini 3.5 Flash Lite provider and offline fallback
    │   └── web/                               # Web UI templates & static assets
    └── tests/                                 # Unit, integration, and contract tests (87 passing)
```

---

## 📄 License

MIT License. Designed for open, reproducible evaluation.
