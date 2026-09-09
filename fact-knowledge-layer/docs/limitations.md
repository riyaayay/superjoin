# Limitations and Next Steps

## Known Limitations

### 1. No OCR for Charts and Images
PyMuPDF extracts text blocks but cannot read values plotted inside bar charts, line graphs, or pie charts.
The system records these blocks with `block_kind = chart | image` so the non-extraction is **visible** rather than silent.
**Next step:** Integrate pytesseract or a vision-capable LLM call for image blocks.

### 2. Heuristic Table Parser
pdfplumber's table detection works well on clearly-bordered financial tables but struggles with:
- Multi-level merged column headers
- Borderless text-alignment tables common in government reports
- Tables spanning multiple pages
**Next step:** Evaluate Camelot or Docling for better table structure recovery.

### 3. LLM Extraction Quality Varies
Gemini 2.0 Flash is good at structured extraction from clean prose, but may:
- Hallucinate values (caught by the grounding gate)
- Merge adjacent facts into one candidate
- Miss facts in dense tables (where the table extractor takes over)
**Mitigation in place:** All candidates pass the grounding gate; fabricated values cannot become facts.

### 4. Semantic Metric Matching is Approximate
The blocking key uses Jaccard overlap of word tokens. Two metrics like "GDP at market prices" and "Gross Domestic Product (market)" may not share enough tokens to be blocked together. The LLM canonicalization call helps but is not used for all pairs (only those that pass deterministic blocking).
**Next step:** Add phrase embeddings (e.g., sentence-transformers) as a second blocking pass for pairs missed by token overlap.

### 5. No Production Queue
The API uses FastAPI `BackgroundTasks` for simplicity. For large PDFs or high concurrency, this blocks the server. A persistent queue (Celery + Redis, or Temporal) is the next step for production.

### 6. No Authentication
The review endpoint (`POST /api/relationships/{id}/review`) has no authentication. Fine for a local demo, not for deployment.

### 7. Printed Page Labels
The parser attempts to detect printed page labels from footer text, but the heuristic is fragile for PDFs with complex layouts or multiple columns.

## Explicitly Deferred (Brownie Points)

| Item | Status | Reason |
|------|--------|--------|
| Large PDF streaming / performance | Deferred | Core correctness first; background task model sufficient for ≤100 pages |
| Many PDFs in one knowledge layer | Partially supported (incremental ingestion works) | ANN indexing not implemented |
| Dynamic schema evolution | Deferred | Schema is already generic; evolving it requires migration tooling |
| Graph visualisation | Deferred | SQLite + UI sufficient for demo; graph adds complexity without correctness benefit |

## Source Audit Result

Before recording the demo, we manually inspected a stratified sample of extracted facts:
- **Table-derived:** _N_ facts inspected, _M_ correct (to be filled after extraction)
- **Prose-derived:** _N_ facts inspected, _M_ correct (to be filled after extraction)
- Known issues: chart-only pages produce visible rejections (see demo case #4)

Report: `X/20 correct in sampled audit` — this is the honest accuracy bound, not an invented global score.
