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

// ── Evidence panel ────────────────────────────────────────
function renderEvidence(evidence) {
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
    textHtml = `<div class="evidence-quote">${esc(evidence.text || '')}</div>`;
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

// ── Index page logic ──────────────────────────────────────
function initIndexPage() {
  const uploadZone = document.getElementById('upload-zone');
  const fileInput = document.getElementById('file-input');
  const uploadBtn = document.getElementById('upload-btn');
  const selectedFile = document.getElementById('selected-file');
  const uploadStatus = document.getElementById('upload-status');
  const docsGrid = document.getElementById('docs-grid');
  const factsSection = document.getElementById('facts-section');
  const relsSection = document.getElementById('rels-section');

  let currentFiles = [];  // multi-file: array of File objects
  let activePolls = new Set();

  // Drag & drop (support multiple files)
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
      selectedFile.textContent = files.length === 1
        ? `Selected: ${files[0].name} (${(files[0].size / 1024 / 1024).toFixed(2)} MB)`
        : `Selected: ${files.length} files (${files.map(f => f.name).join(', ')})`;
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
    if (selectedFile) selectedFile.textContent = '';
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
            if (typeof loadFacts === 'function') loadFacts();
            if (typeof loadRelationships === 'function') loadRelationships();
          } catch (err) {
            toast(err.message || 'Failed to delete', 'error');
          }
        });
      });

      // Load stats for each doc
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

  // Facts tab
  let factsPage = 1;
  let factsFilters = {};
  async function loadFacts() {
    if (!factsSection) return;
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

  // Relationships tab
  async function loadRelationships() {
    const grid = document.getElementById('rels-grid');
    if (!grid) return;
    grid.innerHTML = '<div class="spinner" style="margin:40px auto;display:block"></div>';
    try {
      const verdictFilter = document.getElementById('verdict-filter')?.value || '';
      const res = await API.relationships({ limit: 50, ...(verdictFilter ? { verdict: verdictFilter } : {}) });
      if (!res.items.length) {
        grid.innerHTML = '<div class="empty-state"><div class="empty-icon">🔗</div><p>No relationships yet. Upload multiple documents.</p></div>';
        return;
      }
      grid.innerHTML = res.items.map(r => `
        <div class="rel-card rel-card--${r.verdict}">
          <div class="card-header">
            ${verdictBadge(r.verdict)}
            <div class="flex items-center gap-8">
              <span class="badge" style="font-size:.68rem">
                ${esc(r.reason_code?.replace(/_/g,' '))}
              </span>
              ${reviewBadge(r.review_state)}
            </div>
          </div>
          <div class="rel-facts">
            <div class="rel-fact-box">
              <div class="label">Source A <span class="text-muted">${esc(r.left_fact?.document_id?.slice(-8) || '')}</span></div>
              <div class="entity">${esc(r.left_fact?.entity_raw || '—')}</div>
              <div class="metric">${esc(r.left_fact?.metric_raw || '—')}</div>
              <div class="value">${esc(r.left_fact?.value_raw || '—')}</div>
              <div class="text-muted" style="font-size:.72rem">${esc(r.left_fact?.period_raw || '')}</div>
            </div>
            <div class="rel-connector">${r.verdict === 'corroborates' ? '≈' : r.verdict === 'reconciles' ? '⟺' : r.verdict === 'likely_conflict' ? '⚡' : '?'}</div>
            <div class="rel-fact-box">
              <div class="label">Source B <span class="text-muted">${esc(r.right_fact?.document_id?.slice(-8) || '')}</span></div>
              <div class="entity">${esc(r.right_fact?.entity_raw || '—')}</div>
              <div class="metric">${esc(r.right_fact?.metric_raw || '—')}</div>
              <div class="value">${esc(r.right_fact?.value_raw || '—')}</div>
              <div class="text-muted" style="font-size:.72rem">${esc(r.right_fact?.period_raw || '')}</div>
            </div>
          </div>
          <div class="rel-explanation">${esc(r.explanation)}</div>
          ${r.verdict === 'likely_conflict' ? `
            <div class="rel-actions">
              <button class="btn btn-sm btn-success" onclick="reviewRel('${r.relationship_id}', 'human_verified', this)">✓ Verify Evidence</button>
              <button class="btn btn-sm btn-danger" onclick="reviewRel('${r.relationship_id}', 'rejected', this)">✗ Reject</button>
            </div>` : ''}
        </div>`).join('');
    } catch (e) {
      grid.innerHTML = `<p class="text-red">${esc(e.message)}</p>`;
    }
  }

  window.reviewRel = async (id, state, btn) => {
    btn.disabled = true;
    try {
      await API.reviewRelationship(id, state, null);
      toast(`Relationship marked as ${state}`, 'success');
      loadRelationships();
    } catch (e) { toast(e.message, 'error'); btn.disabled = false; }
  };

  // Rejected candidates
  async function loadRejected() {
    const tbody = document.getElementById('rejected-tbody');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center"><span class="spinner"></span></td></tr>';
    try {
      const rows = await API.rejectedCandidates({});
      if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:20px;color:var(--text-muted)">No rejected candidates</td></tr>';
        return;
      }
      tbody.innerHTML = rows.map(r => `
        <tr>
          <td class="text-secondary" style="font-size:.78rem">${esc(r.entity_raw)}</td>
          <td class="text-secondary" style="font-size:.78rem">${esc(r.metric_raw)}</td>
          <td class="fact-value">${esc(r.value_raw)}</td>
          <td><span class="badge badge-rejected">${esc(r.rejection_reason?.replace(/_/g,' '))}</span></td>
          <td class="text-muted" style="font-size:.72rem">${esc(r.extraction_method)}</td>
        </tr>`).join('');
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="5" class="text-red">${esc(e.message)}</td></tr>`;
    }
  }

  // Tabs
  const tabBtns = document.querySelectorAll('.tab');
  const tabPanels = document.querySelectorAll('.tab-panel');
  tabBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      tabBtns.forEach(b => b.classList.remove('active'));
      tabPanels.forEach(p => p.classList.add('hidden'));
      btn.classList.add('active');
      const target = document.getElementById(btn.dataset.tab);
      if (target) target.classList.remove('hidden');
      if (btn.dataset.tab === 'facts-panel') loadFacts();
      if (btn.dataset.tab === 'rels-panel') loadRelationships();
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
  document.getElementById('verdict-filter')?.addEventListener('change', loadRelationships);

  // Init
  loadDocuments();
  loadFacts();
  loadRelationships();
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

  // Load facts for this document
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

        ${renderEvidence(fact.evidence)}

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
              ${renderEvidence(other.evidence)}
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
