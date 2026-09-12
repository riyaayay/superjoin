/* =========================================================
   Fact Knowledge Layer — Application JavaScript
   ========================================================= */

const API = {
  async json(url, opts = {}) {
    const r = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...opts });
    if (!r.ok) { const e = await r.json().catch(() => ({ detail: r.statusText })); throw new Error(e.detail || r.statusText); }
    return r.json();
  },
  documents: () => API.json('/api/documents'),
  document: (id) => API.json(`/api/documents/${id}`),
  deleteDocument: (id) => API.json(`/api/documents/${id}`, { method: 'DELETE' }),
  uploadDocument: (formData) => fetch('/api/documents', { method: 'POST', body: formData }).then(r => r.json()),
  facts: (params) => API.json('/api/facts?' + new URLSearchParams(params)),
  fact: (id) => API.json(`/api/facts/${id}`),
  factRelationships: (id) => API.json(`/api/facts/${id}/relationships`),
  relationships: (params) => API.json('/api/relationships?' + new URLSearchParams(params)),
  rejectedCandidates: (params) => API.json('/api/relationships/rejected-candidates?' + new URLSearchParams(params)),
  reviewRelationship: (id, state, note) => API.json(`/api/relationships/${id}/review`, {
    method: 'POST', body: JSON.stringify({ review_state: state, note })
  }),
  stats: () => API.json('/api/stats'),
};

// ── Toast ─────────────────────────────────────────────────
function toast(msg, type = 'info') {
  let container = document.querySelector('.toast-container');
  if (!container) {
    container = document.createElement('div');
    container.className = 'toast-container';
    document.body.appendChild(container);
  }
  const t = document.createElement('div');
  t.className = `toast toast--${type}`;
  t.textContent = msg;
  container.appendChild(t);
  setTimeout(() => t.remove(), 4000);
}

// ── Verdict badge ─────────────────────────────────────────
function verdictBadge(verdict) {
  const labels = {
    corroborates: '✓ Corroborates',
    reconciles: '⟺ Reconciles',
    likely_conflict: '⚠ Likely Conflict',
    insufficient_context: '? Insufficient Context',
  };
  return `<span class="badge badge-${verdict}">${labels[verdict] || verdict}</span>`;
}

function statusBadge(status) {
  const icons = { queued: '⏳', processing: '⚙', complete: '✓', failed: '✗', relationships_failed: '⚠' };
  const labels = { relationships_failed: 'relationships failed' };
  return `<span class="badge badge-${status}">${icons[status] || ''} ${labels[status] || status}</span>`;
}

function reviewBadge(state) {
  const map = { automatic: 'Auto', human_verified: '✓ Verified', rejected: '✗ Rejected' };
  const cls = { automatic: '', human_verified: 'badge-accepted', rejected: 'badge-rejected' };
  return `<span class="badge ${cls[state] || ''}">${map[state] || state}</span>`;
}

// ── Number formatting ─────────────────────────────────────
function fmt(v, unit) {
  if (v === null || v === undefined) return '—';
  const n = typeof v === 'number' ? v.toLocaleString('en-IN', { maximumFractionDigits: 4 }) : v;
  return unit ? `${n} ${unit}` : n;
}

// ── Polling helper ────────────────────────────────────────
function pollUntilDone(docId, onUpdate, intervalMs = 2000) {
  const poll = async () => {
    try {
      const doc = await API.document(docId);
      onUpdate(doc);
      if (doc.status === 'queued' || doc.status === 'processing') {
        setTimeout(poll, intervalMs);
      }
    } catch (e) { console.warn('Poll error', e); }
  };
  poll();
}

// ── Inline evidence renderer ──────────────────────────────
// Used both in the accordion rows (relationships panel) and in the fact detail page.
// valueToHighlight: the raw value string to <mark> inside prose text.
function renderEvidenceInline(evidence, docId, valueToHighlight) {
  if (!evidence) return '<p class="text-muted" style="font-size:.78rem;margin-top:8px">No evidence data</p>';
  const tc = evidence.table_context;
  let textHtml = '';
  if (tc) {
    const rows = [
      tc.table_title && `<tr><td class="kv-key">Table</td><td class="kv-val">${esc(tc.table_title)}</td></tr>`,
      tc.row_header && `<tr><td class="kv-key">Row</td><td class="kv-val">${esc(tc.row_header)}</td></tr>`,
      tc.column_headers?.length && `<tr><td class="kv-key">Column</td><td class="kv-val">${esc(tc.column_headers.join(' | '))}</td></tr>`,
      tc.cell_value && `<tr><td class="kv-key">Cell value</td><td class="kv-val mono text-cyan">${esc(tc.cell_value)}</td></tr>`,
      tc.unit_note && `<tr><td class="kv-key">Unit note</td><td class="kv-val">${esc(tc.unit_note)}</td></tr>`,
    ].filter(Boolean);
    textHtml = `<table class="kv-list" style="width:100%;margin-top:8px">${rows.join('')}</table>`;
  } else if (evidence.text) {
    const highlighted = highlightValue(evidence.text, valueToHighlight);
    textHtml = `<div class="evidence-quote evidence-quote--compact">${highlighted}</div>`;
  }

  const pageLabel = evidence.printed_page_label
    ? `p.${evidence.printed_page_label}`
    : `page ${evidence.pdf_page_index}`;

  const docShort = docId ? docId.slice(-8) : '—';

  return `
    <div class="inline-evidence">
      <div class="inline-evidence-header">
        <span class="badge" style="font-size:.65rem">${esc(evidence.block_kind || '')}</span>
        <span class="text-muted" style="font-size:.72rem">📄 ${pageLabel} · doc …${docShort}</span>
        ${evidence.pdf_page_index != null ? `<a class="page-render-link" style="font-size:.72rem" href="/api/documents/${docId}/pages/${evidence.pdf_page_index}" target="_blank">View page →</a>` : ''}
      </div>
      ${textHtml}
    </div>`;
}

// ── Evidence panel (full, used on fact detail page) ───────
function renderEvidence(evidence, valueToHighlight) {
  if (!evidence) return '<p class="text-muted">No evidence data</p>';
  const tc = evidence.table_context;
  let textHtml = '';
  if (tc) {
    const rows = [
      tc.table_title && `<tr><td class="kv-key">Table</td><td class="kv-val">${esc(tc.table_title)}</td></tr>`,
      tc.row_header && `<tr><td class="kv-key">Row</td><td class="kv-val">${esc(tc.row_header)}</td></tr>`,
      tc.column_headers?.length && `<tr><td class="kv-key">Column</td><td class="kv-val">${esc(tc.column_headers.join(' | '))}</td></tr>`,
      tc.cell_value && `<tr><td class="kv-key">Cell value</td><td class="kv-val mono text-cyan">${esc(tc.cell_value)}</td></tr>`,
      tc.unit_note && `<tr><td class="kv-key">Unit note</td><td class="kv-val">${esc(tc.unit_note)}</td></tr>`,
    ].filter(Boolean);
    textHtml = `<table class="kv-list" style="width:100%">${rows.join('')}</table>`;
  } else {
    // Task 3: highlight the grounded value inside prose text
    const highlighted = highlightValue(evidence.text || '', valueToHighlight);
    textHtml = `<div class="evidence-quote">${highlighted}</div>`;
  }

  return `
    <div class="evidence-panel">
      <h3>📄 Source Evidence — Page ${evidence.pdf_page_index}
        <span class="badge">${evidence.block_kind || ''}</span>
        ${evidence.printed_page_label ? `<span class="text-muted">(printed: ${evidence.printed_page_label})</span>` : ''}
      </h3>
      ${textHtml}
      <div class="evidence-meta">
        ${evidence.bbox ? `<span>📍 bbox: [${evidence.bbox.x0?.toFixed(0)}, ${evidence.bbox.y0?.toFixed(0)}, ${evidence.bbox.x1?.toFixed(0)}, ${evidence.bbox.y1?.toFixed(0)}]</span>` : ''}
        <span>📄 PDF page index: ${evidence.pdf_page_index}</span>
      </div>
      <a class="page-render-link" href="/api/documents/${evidence.block_id?.split('_')[0] || ''}/pages/${evidence.pdf_page_index}" target="_blank">
        🔍 View source page →
      </a>
    </div>`;
}

// ── Task 3: highlight exact value match in source text ────
// Returns escaped HTML string with <mark> around matched substring.
function highlightValue(rawText, valueToHighlight) {
  const escaped = esc(rawText);
  if (!valueToHighlight) return escaped;

  // Try exact substring match first (after escaping both for safety)
  const escapedVal = esc(valueToHighlight);
  const idx = escaped.indexOf(escapedVal);
  if (idx !== -1) {
    return escaped.slice(0, idx)
      + '<mark class="evidence-highlight">' + escapedVal + '</mark>'
      + escaped.slice(idx + escapedVal.length);
  }

  // Fallback: strip commas/currency symbols and try again on the raw text
  const stripped = valueToHighlight.replace(/[,₹$€£\s]/g, '');
  if (stripped && stripped !== valueToHighlight) {
    const rawIdx = rawText.indexOf(stripped);
    if (rawIdx !== -1) {
      const pre = esc(rawText.slice(0, rawIdx));
      const match = esc(rawText.slice(rawIdx, rawIdx + stripped.length));
      const post = esc(rawText.slice(rawIdx + stripped.length));
      return pre + '<mark class="evidence-highlight">' + match + '</mark>' + post;
    }
  }

  return escaped; // no match — return plain escaped text
}

function renderNormTrace(steps) {
  if (!steps || !steps.length) return '';
  const html = steps.map(s => `
    <div class="norm-step">
      <span class="op">${esc(s.operation)}</span>
      <span class="arrow">→</span>
      <span>${esc(String(s.input))} ${s.input_unit ? `(${esc(s.input_unit)})` : ''}</span>
      <span class="arrow">⟹</span>
      <span class="result">${esc(String(s.output))} ${s.output_unit ? `(${esc(s.output_unit)})` : ''}</span>
    </div>`).join('');
  return `<div class="norm-trace"><h4>Normalisation trace</h4>${html}</div>`;
}

function esc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Verdict connector symbol ───────────────────────────────
function verdictSymbol(verdict) {
  return { corroborates: '≈', reconciles: '⟺', likely_conflict: '⚡', insufficient_context: '?' }[verdict] || '·';
}

// ── Reason code human descriptions (Task 2) ───────────────
const REASON_DESCRIPTIONS = {
  exact_match: 'The values are numerically identical after normalisation.',
  rounded_match: 'One value is a rounded version of the other — a common presentation difference.',
  alias_match: 'The entities or metric names differ slightly (e.g. abbreviation vs. full name) but refer to the same concept.',
  different_period: 'The facts cover different reporting periods (e.g. FY2023 vs. H1 FY2024).',
  different_scope: 'The facts cover different scopes (e.g. standalone vs. consolidated entity).',
  unit_or_scale_difference: 'The values appear to differ due to unit or scale (e.g. crores vs. lakhs).',
  methodology_difference: 'The values reflect different accounting or reporting methodologies.',
  material_value_difference: 'The values are materially different and cannot be explained by rounding, period, or scope alone.',
  low_evidence_quality: 'The source block had low-quality or ambiguous text that could not be reliably interpreted.',
  insufficient_context: 'There was not enough context to determine whether the values agree or conflict.',
};

const REJECTION_DESCRIPTIONS = {
  // Actual codes present in the DB
  meta_disclaimer_not_a_fact: 'The text is boilerplate or disclaimer language (e.g. "this is a synthetic document") rather than a reportable fact.',
  suspected_text_corruption: 'The extracted text looked scrambled or garbled — e.g. column headers interleaved with cell text — so it was not trusted rather than guessed at.',
  metric_label_not_grounded: 'The extracted metric label could not be found verbatim in the source block text, so the candidate was rejected to avoid mis-attribution.',
  value_not_found_in_block_text: 'The numeric value could not be located in the source block, failing the verbatim grounding check.',
  cell_value_not_recognized_as_numeric: 'The cell contained text rather than a number or date — only quantitative facts are ingested.',
  source_block_is_chart_or_image: 'The source block is a chart or embedded image; text extraction from images is not supported in this version.',
  // Generic fallbacks
  missing_row_header: 'The table cell had no row label, so there was no way to identify what metric it represents.',
  not_numeric: 'The extracted value was not a number or date — only quantitative facts are ingested.',
  below_confidence_threshold: 'The extraction confidence was too low to accept the candidate reliably.',
  duplicate: 'An identical fact (same entity, metric, value, period) was already accepted from another source.',
  failed_grounding: 'The candidate value could not be found verbatim in the source block text.',
  entity_heading_leak: 'The extracted entity was a section heading rather than a real corporate entity.',
};

function rejectionDesc(code) {
  return REJECTION_DESCRIPTIONS[code] || REASON_DESCRIPTIONS[code] || 'See reason code for details.';
}

// ── Index page logic ──────────────────────────────────────
function initIndexPage() {
  const uploadZone = document.getElementById('upload-zone');
  const fileInput = document.getElementById('file-input');
  const uploadBtn = document.getElementById('upload-btn');
  const selectedFile = document.getElementById('selected-file');
  const uploadStatus = document.getElementById('upload-status');
  const docsGrid = document.getElementById('docs-grid');

  let currentFiles = [];
  let activePolls = new Set();
  let activeRelVerdict = '';  // currently selected chip filter

  // Drag & drop
  uploadZone?.addEventListener('click', () => fileInput?.click());
  uploadZone?.addEventListener('dragover', e => { e.preventDefault(); uploadZone.classList.add('drag-over'); });
  uploadZone?.addEventListener('dragleave', () => uploadZone.classList.remove('drag-over'));
  uploadZone?.addEventListener('drop', e => {
    e.preventDefault();
    uploadZone.classList.remove('drag-over');
    const files = Array.from(e.dataTransfer.files).filter(f => f.type === 'application/pdf' || f.name.endsWith('.pdf'));
    if (files.length) handleFilesSelect(files);
  });
  fileInput?.addEventListener('change', () => {
    if (fileInput.files.length) handleFilesSelect(Array.from(fileInput.files));
  });

  function handleFilesSelect(files) {
    currentFiles = files;
    if (selectedFile) {
      const names = files.length === 1
        ? `${files[0].name}  (${(files[0].size/1024/1024).toFixed(1)} MB)`
        : `${files.length} files selected`;
      selectedFile.innerHTML = `<div class="selected-file-pill"><span>📎</span><span class="pill-name">${esc(names)}</span></div>`;
    }
    if (uploadBtn) uploadBtn.disabled = false;
  }

  uploadBtn?.addEventListener('click', async () => {
    if (!currentFiles.length) return;
    uploadBtn.disabled = true;
    uploadBtn.innerHTML = '<span class="spinner"></span> Uploading…';
    if (uploadStatus) uploadStatus.innerHTML = '';

    const results = [];
    for (const file of currentFiles) {
      try {
        const fd = new FormData();
        fd.append('file', file);
        const res = await API.uploadDocument(fd);
        if (res.deduplicated) {
          toast(`${file.name}: already uploaded — returning existing.`, 'info');
        } else {
          toast(`${file.name}: upload successful! Processing started.`, 'success');
        }
        results.push(res);
        startPollingDoc(res.document_id);
      } catch (e) {
        toast(`${file.name}: ${e.message}`, 'error');
        if (uploadStatus) uploadStatus.innerHTML += `<span class="text-red">${esc(file.name)}: ${esc(e.message)}</span><br>`;
      }
    }

    if (results.length) {
      if (uploadStatus) uploadStatus.innerHTML = results
        .map(r => `<span class="badge badge-${r.status}">${r.status}</span> <span class="text-muted mono" style="font-size:.75rem">${r.document_id}</span>`)
        .join('<br>');
      loadDocuments();
    }

    currentFiles = [];
    if (selectedFile) selectedFile.innerHTML = '';
    if (fileInput) fileInput.value = '';
    uploadBtn.disabled = true;
    uploadBtn.innerHTML = '⬆ Upload PDF';
  });

  function startPollingDoc(docId) {
    if (activePolls.has(docId)) return;
    activePolls.add(docId);
    pollUntilDone(docId, (doc) => {
      updateDocCard(doc);
      if (doc.status === 'complete' || doc.status === 'failed') {
        activePolls.delete(docId);
        loadFacts();
        loadRelationships();
        loadStats();
      }
    });
  }

  function updateDocCard(doc) {
    const card = document.querySelector(`[data-doc-id="${doc.document_id}"]`);
    if (card) {
      const statusEl = card.querySelector('.doc-status');
      if (statusEl) statusEl.innerHTML = statusBadge(doc.status);
      const statsEl = card.querySelector('.doc-stats');
      if (statsEl && doc.stats) {
        statsEl.textContent = `${doc.stats.facts_accepted} facts · ${doc.stats.relationships} relationships`;
      }
    }
  }

  async function loadDocuments() {
    if (!docsGrid) return;
    try {
      const docs = await API.documents();
      if (!docs.length) {
        docsGrid.innerHTML = '<div class="empty-state"><div class="empty-icon">📂</div><p>No documents yet. Upload a PDF to begin.</p></div>';
        return;
      }
      docsGrid.innerHTML = docs.map(d => `
        <div class="doc-card-wrap" style="position:relative">
          <a href="/documents/${d.document_id}" class="doc-card" data-doc-id="${d.document_id}">
            <div class="flex items-center justify-between mb-8">
              <span class="doc-status">${statusBadge(d.status)}</span>
              <span class="text-muted" style="font-size:.72rem;margin-right:24px">${d.created_at?.slice(0,10) || ''}</span>
            </div>
            <h3>📄 ${esc(d.original_filename)}</h3>
            <div class="doc-meta">
              <span class="doc-stat">📑 ${d.page_count ?? '?'} pages</span>
              <span class="doc-stat doc-stats">Loading…</span>
            </div>
            ${d.error_message ? `<div class="text-red mt-8" style="font-size:.75rem">⚠ ${esc(d.error_message)}</div>` : ''}
          </a>
          <button class="btn-card-delete" title="Delete document" data-delete-id="${d.document_id}" data-filename="${esc(d.original_filename)}" style="position:absolute;top:12px;right:12px;background:none;border:none;color:var(--text-muted,#888);cursor:pointer;font-size:14px;padding:4px;border-radius:4px;line-height:1;transition:color 0.2s;">🗑</button>
        </div>`).join('');

      docsGrid.querySelectorAll('.btn-card-delete').forEach(btn => {
        btn.addEventListener('click', async (e) => {
          e.preventDefault();
          e.stopPropagation();
          const docId = btn.dataset.deleteId;
          const fname = btn.dataset.filename || docId;
          if (!confirm(`Are you sure you want to delete "${fname}" and all its extracted facts?`)) return;
          try {
            await API.deleteDocument(docId);
            toast(`Deleted ${fname}`, 'success');
            loadDocuments();
            loadFacts();
            loadRelationships();
            loadStats();
          } catch (err) {
            toast(err.message || 'Failed to delete', 'error');
          }
        });
      });

      for (const d of docs) {
        try {
          const full = await API.document(d.document_id);
          const card = docsGrid.querySelector(`[data-doc-id="${d.document_id}"]`);
          if (card) {
            const statsEl = card.querySelector('.doc-stats');
            if (statsEl && full.stats) {
              statsEl.textContent = `${full.stats.facts_accepted} facts · ${full.stats.relationships} rel.`;
            }
          }
          if (d.status === 'processing' || d.status === 'queued') startPollingDoc(d.document_id);
        } catch (_) {}
      }
    } catch (e) {
      docsGrid.innerHTML = `<p class="text-red">Failed to load documents: ${esc(e.message)}</p>`;
    }
  }

  // ── Task 4: Global stats strip ────────────────────────────
  async function loadStats() {
    try {
      const s = await API.stats();
      const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val ?? '—'; };
      set('stat-docs', s.total_documents);
      set('stat-facts', s.total_facts);
      set('stat-rels', s.total_relationships);
      set('stat-corr', s.verdicts?.corroborates ?? 0);
      set('stat-rec', s.verdicts?.reconciles ?? 0);
      set('stat-conf', s.verdicts?.likely_conflict ?? 0);
      set('stat-ins', s.verdicts?.insufficient_context ?? 0);
    } catch (e) {
      console.warn('Stats load failed', e);
    }
  }

  // ── Facts tab ─────────────────────────────────────────────
  let factsPage = 1;
  let factsFilters = {};
  async function loadFacts() {
    const tbody = document.getElementById('facts-tbody');
    const totalEl = document.getElementById('facts-total');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:20px"><span class="spinner"></span></td></tr>';
    try {
      const params = { page: factsPage, limit: 50, ...factsFilters };
      const res = await API.facts(params);
      if (totalEl) totalEl.textContent = res.total;
      if (!res.items.length) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:30px;color:var(--text-muted)">No facts found</td></tr>';
        return;
      }
      tbody.innerHTML = res.items.map(f => `
        <tr onclick="window.location='/facts/${f.fact_id}'" title="Click to inspect">
          <td><span class="fact-entity text-truncate" style="max-width:140px">${esc(f.entity_raw)}</span></td>
          <td><span class="fact-metric text-truncate" style="max-width:180px">${esc(f.metric_raw)}</span></td>
          <td><span class="fact-value">${esc(f.value_raw)}</span></td>
          <td class="text-secondary" style="font-size:.75rem">${esc(f.period_raw || '—')}</td>
          <td class="text-muted" style="font-size:.72rem">${esc(f.unit_raw || '—')}</td>
          <td><span class="badge badge-${f.review_state}">${f.review_state}</span></td>
          <td class="text-muted" style="font-size:.72rem">${esc(f.document_id?.slice(-8) || '')}</td>
        </tr>`).join('');
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="7" class="text-red">${esc(e.message)}</td></tr>`;
    }
  }

  // ── Task 1: Relationships tab with accordion rows ─────────
  async function loadRelationships() {
    const list = document.getElementById('rels-list');
    if (!list) return;
    list.innerHTML = '<div style="padding:40px;text-align:center"><span class="spinner"></span></div>';
    try {
      const params = { limit: 100 };
      if (activeRelVerdict) params.verdict = activeRelVerdict;
      const res = await API.relationships(params);

      if (!res.items.length) {
        const emptyMsg = activeRelVerdict
          ? `No ${activeRelVerdict.replace(/_/g, ' ')} relationships found in the current knowledge layer.`
          : 'No relationships yet. Upload multiple documents to discover cross-document facts.';
        list.innerHTML = `<div class="empty-state"><div class="empty-icon">🔗</div><p>${esc(emptyMsg)}</p></div>`;
        return;
      }

      list.innerHTML = res.items.map((r, i) => {
        const lf = r.left_fact;
        const rf = r.right_fact;
        const sym = verdictSymbol(r.verdict);
        const rcLabel = r.reason_code ? r.reason_code.replace(/_/g, ' ') : '';
        const rcDesc = REASON_DESCRIPTIONS[r.reason_code] || '';
        const rowId = `rel-row-${r.relationship_id}`;
        const bodyId = `rel-body-${r.relationship_id}`;

        return `
          <div class="rel-accordion rel-accordion--${r.verdict}" id="${rowId}">
            <!-- Accordion header: summary row -->
            <button class="rel-accordion-header" onclick="toggleRelAccordion('${bodyId}', this)" aria-expanded="false">
              <div class="rel-accordion-left">
                ${verdictBadge(r.verdict)}
                ${r.reason_code ? `<span class="reason-chip">${esc(rcLabel)}</span>` : ''}
              </div>
              <div class="rel-accordion-facts">
                <span class="rel-accordion-entity">${esc(lf?.entity_raw || '—')}</span>
                <span class="rel-accordion-metric">${esc(lf?.metric_raw || '—')}</span>
                <span class="rel-accordion-value">${esc(lf?.value_raw || '—')}</span>
                <span class="rel-connector-sym">${sym}</span>
                <span class="rel-accordion-entity">${esc(rf?.entity_raw || '—')}</span>
                <span class="rel-accordion-metric">${esc(rf?.metric_raw || '—')}</span>
                <span class="rel-accordion-value">${esc(rf?.value_raw || '—')}</span>
              </div>
              <div class="rel-accordion-right">
                ${reviewBadge(r.review_state)}
                <span class="accordion-chevron">▸</span>
              </div>
            </button>

            <!-- Accordion body: full inline evidence -->
            <div class="rel-accordion-body hidden" id="${bodyId}">
              <!-- Two-column fact evidence -->
              <div class="rel-evidence-grid">
                <div class="rel-evidence-col">
                  <div class="rel-evidence-label">Source A</div>
                  <div class="rel-fact-summary">
                    <div class="entity">${esc(lf?.entity_raw || '—')}</div>
                    <div class="metric">${esc(lf?.metric_raw || '—')}</div>
                    <div class="value">${esc(lf?.value_raw || '—')}</div>
                    ${lf?.unit_raw ? `<div class="text-muted" style="font-size:.72rem">${esc(lf.unit_raw)}</div>` : ''}
                    ${lf?.period_raw ? `<div class="text-muted" style="font-size:.72rem">${esc(lf.period_raw)}</div>` : ''}
                    ${lf?.extraction_method ? `<span class="badge" style="font-size:.62rem;margin-top:4px">${esc(lf.extraction_method.replace('_',' '))}</span>` : ''}
                    ${lf ? `<a href="/facts/${lf.fact_id}" class="fact-link">Inspect fact →</a>` : ''}
                  </div>
                  ${renderEvidenceInline(lf?.evidence, lf?.document_id, lf?.value_raw)}
                </div>
                <div class="rel-evidence-divider">${sym}</div>
                <div class="rel-evidence-col">
                  <div class="rel-evidence-label">Source B</div>
                  <div class="rel-fact-summary">
                    <div class="entity">${esc(rf?.entity_raw || '—')}</div>
                    <div class="metric">${esc(rf?.metric_raw || '—')}</div>
                    <div class="value">${esc(rf?.value_raw || '—')}</div>
                    ${rf?.unit_raw ? `<div class="text-muted" style="font-size:.72rem">${esc(rf.unit_raw)}</div>` : ''}
                    ${rf?.period_raw ? `<div class="text-muted" style="font-size:.72rem">${esc(rf.period_raw)}</div>` : ''}
                    ${rf?.extraction_method ? `<span class="badge" style="font-size:.62rem;margin-top:4px">${esc(rf.extraction_method.replace('_',' '))}</span>` : ''}
                    ${rf ? `<a href="/facts/${rf.fact_id}" class="fact-link">Inspect fact →</a>` : ''}
                  </div>
                  ${renderEvidenceInline(rf?.evidence, rf?.document_id, rf?.value_raw)}
                </div>
              </div>

              <!-- Verdict reasoning -->
              <div class="rel-reasoning">
                <div class="reasoning-verdict">
                  ${verdictBadge(r.verdict)}
                  ${r.reason_code ? `<span class="reason-chip">${esc(rcLabel)}</span>` : ''}
                  <span class="text-muted" style="font-size:.75rem">confidence: ${(r.confidence * 100).toFixed(0)}%</span>
                </div>
                ${rcDesc ? `<p class="reasoning-rc-desc">${esc(rcDesc)}</p>` : ''}
                ${r.explanation ? `<p class="reasoning-explanation">${esc(r.explanation)}</p>` : ''}
              </div>

              <!-- Human review actions -->
              ${r.verdict === 'likely_conflict' ? `
                <div class="rel-actions">
                  <button class="btn btn-sm btn-success" onclick="reviewRel('${r.relationship_id}', 'human_verified', this)">✓ Verify Conflict</button>
                  <button class="btn btn-sm btn-danger" onclick="reviewRel('${r.relationship_id}', 'rejected', this)">✗ Reject</button>
                </div>` : ''}
            </div>
          </div>`;
      }).join('');
    } catch (e) {
      list.innerHTML = `<p class="text-red">${esc(e.message)}</p>`;
    }
  }

  window.toggleRelAccordion = (bodyId, btn) => {
    const body = document.getElementById(bodyId);
    if (!body) return;
    const isOpen = !body.classList.contains('hidden');
    body.classList.toggle('hidden', isOpen);
    if (btn) {
      btn.setAttribute('aria-expanded', String(!isOpen));
      const chevron = btn.querySelector('.accordion-chevron');
      if (chevron) chevron.textContent = isOpen ? '▸' : '▾';
      btn.classList.toggle('is-open', !isOpen);
    }
  };

  window.reviewRel = async (id, state, btn) => {
    btn.disabled = true;
    try {
      await API.reviewRelationship(id, state, null);
      toast(`Relationship marked as ${state}`, 'success');
      loadRelationships();
    } catch (e) { toast(e.message, 'error'); btn.disabled = false; }
  };

  // Verdict chip clicks
  document.querySelectorAll('.verdict-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      document.querySelectorAll('.verdict-chip').forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      activeRelVerdict = chip.dataset.verdict || '';
      loadRelationships();
    });
  });

  // ── Task 2: Rejected candidates grouped by reason code ────
  async function loadRejected() {
    const container = document.getElementById('rejected-groups');
    if (!container) return;
    container.innerHTML = '<div style="padding:40px;text-align:center"><span class="spinner"></span></div>';
    try {
      const rows = await API.rejectedCandidates({ limit: 500 });
      if (!rows.length) {
        container.innerHTML = '<div class="empty-state"><div class="empty-icon">✓</div><p>No rejected candidates found.</p></div>';
        return;
      }

      // Group by rejection_reason
      const groups = {};
      for (const r of rows) {
        const key = r.rejection_reason || 'unknown';
        if (!groups[key]) groups[key] = [];
        groups[key].push(r);
      }

      // Sort groups by count descending
      const sortedGroups = Object.entries(groups).sort((a, b) => b[1].length - a[1].length);

      container.innerHTML = sortedGroups.map(([reason, items]) => {
        const groupId = `rg-${reason.replace(/[^a-z0-9]/gi, '_')}`;
        const bodyId = `rgb-${reason.replace(/[^a-z0-9]/gi, '_')}`;
        const desc = rejectionDesc(reason);
        const label = reason.replace(/_/g, ' ');
        return `
          <div class="rejected-group" id="${groupId}">
            <button class="rejected-group-header" onclick="toggleRejectedGroup('${bodyId}', this)" aria-expanded="false">
              <div class="rg-left">
                <span class="rg-count">${items.length}</span>
                <span class="rg-label">× ${esc(label)}</span>
              </div>
              <span class="accordion-chevron">▸</span>
            </button>
            <div class="rg-desc">${esc(desc)}</div>
            <div class="rejected-group-body hidden" id="${bodyId}">
              ${items.map(r => `
                <div class="rejected-entry">
                  <div class="re-header">
                    <span class="re-entity">${esc(r.entity_raw || '—')}</span>
                    <span class="re-sep">·</span>
                    <span class="re-metric">${esc(r.metric_raw || '—')}</span>
                    <span class="re-sep">·</span>
                    <span class="re-value">${esc(r.value_raw || '—')}</span>
                    ${r.pdf_page_index != null ? `<span class="text-muted" style="font-size:.7rem">p.${r.pdf_page_index}</span>` : ''}
                    <span class="badge" style="font-size:.62rem">${esc(r.extraction_method || '')}</span>
                  </div>
                  ${r.source_text ? `<div class="re-source-text">${esc(r.source_text)}</div>` : ''}
                </div>`).join('')}
            </div>
          </div>`;
      }).join('');
    } catch (e) {
      container.innerHTML = `<p class="text-red">${esc(e.message)}</p>`;
    }
  }

  window.toggleRejectedGroup = (bodyId, btn) => {
    const body = document.getElementById(bodyId);
    if (!body) return;
    const isOpen = !body.classList.contains('hidden');
    body.classList.toggle('hidden', isOpen);
    if (btn) {
      btn.setAttribute('aria-expanded', String(!isOpen));
      const chevron = btn.querySelector('.accordion-chevron');
      if (chevron) chevron.textContent = isOpen ? '▸' : '▾';
    }
  };

  // ── Tabs ──────────────────────────────────────────────────
  const tabBtns = document.querySelectorAll('.tab');
  const tabPanels = document.querySelectorAll('.tab-panel');
  tabBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      tabBtns.forEach(b => b.classList.remove('active'));
      tabPanels.forEach(p => p.classList.add('hidden'));
      btn.classList.add('active');
      const target = document.getElementById(btn.dataset.tab);
      if (target) target.classList.remove('hidden');
      if (btn.dataset.tab === 'rels-panel') loadRelationships();
      if (btn.dataset.tab === 'facts-panel') loadFacts();
      if (btn.dataset.tab === 'rejected-panel') loadRejected();
    });
  });

  // Filters
  document.getElementById('entity-filter')?.addEventListener('input', (e) => {
    factsFilters.entity = e.target.value;
    factsPage = 1;
    loadFacts();
  });
  document.getElementById('metric-filter')?.addEventListener('input', (e) => {
    factsFilters.metric = e.target.value;
    factsPage = 1;
    loadFacts();
  });
  document.getElementById('state-filter')?.addEventListener('change', (e) => {
    factsFilters.review_state = e.target.value;
    factsPage = 1;
    loadFacts();
  });

  // Init — load stats + relationships (primary) first
  loadStats();
  loadDocuments();
  loadRelationships();  // primary tab is now Relationships
}

// ── Document detail page ──────────────────────────────────
function initDocumentPage(documentId) {
  const statusEl = document.getElementById('doc-status');
  const pageCountEl = document.getElementById('doc-pages');
  const statsEl = document.getElementById('doc-stats');
  const runsEl = document.getElementById('runs-list');
  const errorEl = document.getElementById('doc-error');

  async function load() {
    try {
      const doc = await API.document(documentId);
      if (statusEl) statusEl.innerHTML = statusBadge(doc.status);
      if (pageCountEl) pageCountEl.textContent = doc.page_count ?? '?';
      if (statsEl) statsEl.innerHTML = `
        ${doc.canonical_entity ? `<span class="badge" style="background:var(--accent-dim);color:var(--accent)">🏛 ${esc(doc.canonical_entity)}</span>` : ''}
        <span>✓ ${doc.stats?.facts_accepted ?? 0} accepted facts</span>
        <span>✗ ${doc.stats?.facts_rejected_candidates ?? 0} rejected</span>
        <span>🔗 ${doc.stats?.relationships ?? 0} relationships</span>`;
      if (runsEl) {
        runsEl.innerHTML = (doc.runs || []).map(r => `
          <div class="card mt-8">
            <div class="kv-list">
              <span class="kv-key">Run ID</span><span class="kv-val mono">${r.run_id}</span>
              <span class="kv-key">Started</span><span class="kv-val">${r.started_at?.slice(0,19) || ''}</span>
              <span class="kv-key">Finished</span><span class="kv-val">${r.finished_at?.slice(0,19) || '(in progress)'}</span>
              <span class="kv-key">Facts created</span><span class="kv-val text-green">${r.facts_created}</span>
              <span class="kv-key">Facts rejected</span><span class="kv-val text-amber">${r.facts_rejected}</span>
              <span class="kv-key">Relationships</span><span class="kv-val text-accent">${r.relationships_created}</span>
              ${r.blocks_skipped_due_to_cap ? `<span class="kv-key">Prose blocks skipped</span><span class="kv-val text-amber">${r.blocks_skipped_due_to_cap} (cap: 40)</span>` : ''}
            </div>
            ${r.blocks_skipped_due_to_cap ? `<div class="mt-8 text-amber" style="font-size:.8rem">⚠ Note: Prose extraction was capped at 40 blocks; ${r.blocks_skipped_due_to_cap} blocks were skipped.</div>` : ''}
          </div>`).join('');
      }
      if (doc.error_message && errorEl) {
        errorEl.innerHTML = `<div class="evidence-panel" style="border-color:var(--red)"><strong class="text-red">Error:</strong> ${esc(doc.error_message)}</div>`;
      }
      if (doc.status === 'processing' || doc.status === 'queued') {
        setTimeout(load, 2000);
      }
    } catch (e) {
      if (statusEl) statusEl.innerHTML = `<span class="text-red">${esc(e.message)}</span>`;
    }
  }

  async function loadDocFacts() {
    const tbody = document.getElementById('doc-facts-tbody');
    if (!tbody) return;
    try {
      const res = await API.facts({ document_id: documentId, limit: 100 });
      if (!res.items.length) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:20px">No facts yet</td></tr>';
        return;
      }
      tbody.innerHTML = res.items.map(f => `
        <tr onclick="window.location='/facts/${f.fact_id}'" style="cursor:pointer">
          <td>${esc(f.entity_raw)}</td>
          <td class="text-secondary">${esc(f.metric_raw)}</td>
          <td class="fact-value">${esc(f.value_raw)}</td>
          <td class="text-muted">${esc(f.period_raw || '—')}</td>
          <td><span class="badge badge-${f.review_state}">${f.review_state}</span></td>
          <td class="text-muted" style="font-size:.72rem">${esc(f.extraction_method)}</td>
        </tr>`).join('');
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="6" class="text-red">${esc(e.message)}</td></tr>`;
    }
  }

  load();
  loadDocFacts();
}

// ── Fact detail page ──────────────────────────────────────
function initFactPage(factId) {
  const container = document.getElementById('fact-container');
  if (!container) return;

  async function load() {
    try {
      const fact = await API.fact(factId);
      const rels = await API.factRelationships(factId);

      container.innerHTML = `
        <div class="flex items-center gap-12 mb-24">
          <h1 style="font-size:1.5rem;font-weight:700;letter-spacing:-0.02em">${esc(fact.metric_raw)}</h1>
          <span class="badge badge-${fact.review_state}">${fact.review_state}</span>
          <span class="badge">${fact.extraction_method?.replace('_',' ')}</span>
        </div>

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:24px">
          <div class="card">
            <div class="card-title mb-16">📊 Fact Details</div>
            <div class="kv-list">
              <span class="kv-key">Entity</span><span class="kv-val">${esc(fact.entity_raw)}</span>
              <span class="kv-key">Metric</span><span class="kv-val">${esc(fact.metric_raw)}</span>
              <span class="kv-key">Value (raw)</span><span class="kv-val text-cyan mono">${esc(fact.value_raw)}</span>
              <span class="kv-key">Unit</span><span class="kv-val">${esc(fact.unit_raw || '—')}</span>
              <span class="kv-key">Period</span><span class="kv-val">${esc(fact.period_raw || '—')}</span>
              <span class="kv-key">Period start</span><span class="kv-val">${esc(fact.period_start || '—')}</span>
              <span class="kv-key">Period end</span><span class="kv-val">${esc(fact.period_end || '—')}</span>
              <span class="kv-key">Scope</span><span class="kv-val">${esc(JSON.stringify(fact.scope || {}))}</span>
              <span class="kv-key">Confidence</span><span class="kv-val">${(fact.confidence * 100).toFixed(0)}%</span>
            </div>
          </div>
          <div class="card">
            <div class="card-title mb-16">⚡ Normalised Values</div>
            <div class="kv-list">
              <span class="kv-key">Numeric value</span><span class="kv-val text-green mono">${fmt(fact.numeric_value)}</span>
              <span class="kv-key">Normalised value</span><span class="kv-val text-green mono">${fmt(fact.normalised_value, fact.normalised_unit)}</span>
              <span class="kv-key">Scale</span><span class="kv-val">${esc(fact.scale_raw || '—')}</span>
              <span class="kv-key">Value kind</span><span class="kv-val">${esc(fact.value_kind)}</span>
              <span class="kv-key">Unit dimension</span><span class="kv-val">${esc(fact.unit_dimension)}</span>
            </div>
            ${renderNormTrace(fact.normalisation_provenance)}
          </div>
        </div>

        ${renderEvidence(fact.evidence, fact.value_raw)}

        <div class="mt-32">
          <div class="section-header">
            <h2><span class="section-icon">🔗</span> Relationships (${rels.length})</h2>
          </div>
          ${rels.length ? `<div class="rel-grid">` + rels.map(r => {
            const other = r.left_fact.fact_id === factId ? r.right_fact : r.left_fact;
            return `<div class="rel-card rel-card--${r.verdict}">
              <div class="card-header">
                ${verdictBadge(r.verdict)}
                <span class="badge">${esc(r.reason_code?.replace(/_/g,' '))}</span>
              </div>
              <div class="rel-fact-box mt-8">
                <div class="label">Other fact <span class="text-muted">${esc(other.document_id?.slice(-8))}</span></div>
                <div class="entity">${esc(other.entity_raw)}</div>
                <div class="metric">${esc(other.metric_raw)}</div>
                <div class="value">${esc(other.value_raw)}</div>
              </div>
              <div class="rel-explanation mt-8">${esc(r.explanation)}</div>
              ${renderEvidence(other.evidence, other.value_raw)}
              ${r.verdict === 'likely_conflict' ? `<div class="badge badge-likely_conflict mt-8">⚠ Human review required before confirming conflict</div>` : ''}
            </div>`;
          }).join('') + `</div>` : '<div class="empty-state"><div class="empty-icon">🔗</div><p>No relationships found for this fact</p></div>'}
        </div>`;
    } catch (e) {
      container.innerHTML = `<p class="text-red">Error loading fact: ${esc(e.message)}</p>`;
    }
  }

  load();
}

// ── Router ────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  const path = window.location.pathname;
  if (path === '/' || path === '') {
    initIndexPage();
  } else if (path.startsWith('/documents/')) {
    const docId = path.split('/documents/')[1];
    if (docId) initDocumentPage(docId);
  } else if (path.startsWith('/facts/')) {
    const factId = path.split('/facts/')[1];
    if (factId) initFactPage(factId);
  }
});
