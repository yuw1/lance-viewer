// Lance Viewer - tab rendering
// Deps: tools.js. Includes index/version-diff/storage/timeline views.

// ---------- Tab rendering ----------

function renderTree(data) {
  const root = data.tree;
  const container = $('view');
  container.innerHTML =
    `<div class="tree-table-wrap">` +
    `<table class="tree-table">` +
    `<thead><tr><th>${t('colName')}</th><th class="tree-col-size">${t('colSize')}</th><th class="tree-col-mtime">${t('colMtime')}</th></tr></thead>` +
    `<tbody id="treeTbody"></tbody>` +
    `</table></div>`;
  const tb = $('treeTbody');

  // Flat rendering: all rows live in one tbody; dir rows record their direct child rows in
  // childRows, and expand/collapse toggles display on those rows. All rows share one column width.
  function walk(items, depth, relPath, childRows) {
    childRows = childRows || [];
    for (const it of items) {
      const fullRel = relPath ? relPath + '/' + it.name : it.name;
      const tr = document.createElement('tr');
      tr.className = 'tree-tr';
      tr.dataset.depth = depth;

      if (it.type === 'dir') {
        tr.innerHTML =
          `<td class="tree-name" style="padding-left:${8 + depth * 18}px">` +
            `<span class="tree-arrow">${icon('chevron-down', 14)}</span>` +
            `<span class="tree-dir">${icon('folder', 14)} ${esc(it.name)}/</span>` +
            `<span class="tree-size">${t('itemCount', {n: it.children.length})}</span>` +
          `</td>` +
          `<td class="tree-col-size"></td>` +
          `<td class="tree-col-mtime">${esc(it.mtime || '')}</td>`;
        tb.appendChild(tr);
        childRows.push(tr); // record direct child row under the parent dir

        tr._childRows = [];
        walk(it.children, depth + 1, fullRel, tr._childRows);

        tr.addEventListener('click', e => {
          e.stopPropagation();
          toggleDir(tr);
        });
        const arrow = tr.querySelector('.tree-arrow');
        arrow.addEventListener('click', e => {
          e.stopPropagation();
          toggleDir(tr);
        });
      } else {
        const isManifest = it.name.endsWith('.manifest');
        const isTxn = it.name.endsWith('.txn');
        const isLance = it.name.endsWith('.lance') || it.name.endsWith('.idx');
        const isJson = it.name.endsWith('.json');
        const isArrow = it.name.endsWith('.arrow');
        const kind = isManifest ? 'manifest' : isTxn ? 'txn' : isLance ? 'datafile' : isJson ? 'json' : isArrow ? 'arrow' : null;
        const label = indexFileLabel(it.name);
        tr.className = 'tree-tr'
          + (isManifest ? ' manifest-file' : isTxn ? ' txn-file' : isLance ? ' lance-file' : isJson ? ' json-file' : isArrow ? ' arrow-file' : '');
        tr.innerHTML =
          `<td class="tree-name" style="padding-left:${8 + depth * 18}px">` +
            `<span class="tree-arrow">&nbsp;</span>` +
            `<span class="tree-file ${it.size < 1024 ? 'small' : ''}">${icon('file', 14)} ${esc(it.name)}</span>` +
            (label ? `<span class="file-tag">${esc(label)}</span>` : '') +
          `</td>` +
          `<td class="tree-col-size">${fmtSize(it.size)}</td>` +
          `<td class="tree-col-mtime">${esc(it.mtime || '')}</td>`;
        if (kind) {
          tr.title = kind === 'datafile' ? t('openDatafile') :
            kind === 'manifest' ? t('openManifest') :
            kind === 'txn' ? t('openTxn') :
            kind === 'arrow' ? t('openArrow') : t('openJson');
          tr.addEventListener('click', e => {
            e.stopPropagation();
            openFile(fullRel, kind);
          });
        }
        tb.appendChild(tr);
        childRows.push(tr); // record direct child row under the parent dir
      }
    }
  }

  walk(root, 0, '');
}

function collectDescendants(dirTr) {
  const rows = [];
  (function rec(tr) {
    if (tr._childRows) {
      for (const c of tr._childRows) {
        rows.push(c);
        rec(c);
      }
    }
  })(dirTr);
  return rows;
}

function toggleDir(tr) {
  const open = tr._open !== false;
  // A dir row with no _childRows is not a dir; bail out.
  if (!tr._childRows) return;
  const descendants = collectDescendants(tr);
  if (open) {
    // Collapse: hide all descendant rows, arrow points right
    for (const r of descendants) r.style.display = 'none';
    tr.querySelector('.tree-arrow').innerHTML = icon('chevron-right', 14);
    tr.querySelector('.tree-arrow').style.color = 'var(--muted)';
    tr._open = false;
  } else {
    // Expand: show only direct child rows (nested dirs keep their own state), arrow points down
    for (const r of tr._childRows) r.style.display = '';
    tr.querySelector('.tree-arrow').innerHTML = icon('chevron-down', 14);
    tr.querySelector('.tree-arrow').style.color = 'var(--accent)';
    tr._open = true;
  }
}

function renderSchema(data) {
  const f = data.fields;
  let html = '<div class="table-wrap"><table><thead><tr>' +
    '<th>#</th><th>' + t('colField') + '</th><th>' + t('colType') + '</th><th>' + t('nullable') + '</th></tr></thead><tbody>';
  f.forEach((c, i) => {
    html += `<tr>
      <td class="num">${i}</td>
      <td style="font-weight:600">${esc(c.name)}</td>
      <td class="mono" style="color:var(--violet)">${esc(c.type)}</td>
      <td class="${c.nullable ? 'nullable-yes' : 'nullable-no'}">${c.nullable ? ti('yesNullable') : ti('noNullable')}</td>
    </tr>`;
  });
  html += '</tbody></table></div>';
  $('view').innerHTML = html;
}

// ---------- Index overview ----------

function idxTypeBadge(type) {
  const color = {
    'IVF_HNSW_FLAT': 'var(--violet)', 'IVF_PQ': 'var(--violet)', 'IVF_SQ': 'var(--violet)',
    'HNSW': 'var(--violet)', 'FLAT': 'var(--violet)',
    'BTree': 'var(--green)', 'Inverted': 'var(--amber)', 'FTSP': 'var(--amber)',
    'BloomFilter': 'var(--red)', 'ZoneMap': 'var(--accent)',
  }[type] || 'var(--muted)';
  return `<span class="layout-badge" style="border-color:${color};color:${color}">${esc(type)}</span>`;
}

function idxFoldLabel(v) {
  // Description of a folded object
  if (v && typeof v === 'object' && v.__folded__) {
    if (v.num_centroids !== undefined) return t('idxCentroids', {n: v.num_centroids, dim: v.dim});
    if (v.num_items !== undefined) return t('itemCount', {n: v.num_items});
    return t('idxKeys', {n: v.num_keys !== undefined ? v.num_keys : ''});
  }
  return null;
}

function idxParamsHtml(params) {
  if (!params || typeof params !== 'object') return '';
  const items = Object.entries(params).filter(([k, v]) =>
    v !== null && v !== undefined && v !== false);
  return items.map(([k, v]) =>
    `<span class="layout-badge" style="background:#1d222c;border-color:var(--border);color:var(--muted)">${esc(k)}=${esc(typeof v === 'object' ? JSON.stringify(v) : v)}</span>`).join(' ');
}

function idxDetailRows(idx) {
  const st = idx.stats;
  if (!st) return '';
  let rows = [];
  rows.push([t('idxRows'), st.num_indexed_rows ?? '—']);
  rows.push([t('unidxRows'), st.num_unindexed_rows ?? '—']);
  rows.push([t('idxIndexedFrag'), st.num_indexed_fragments ?? '—']);
  rows.push([t('idxUnindexedFrag'), st.num_unindexed_fragments ?? '—']);
  rows.push([t('idxSegments'), st.num_segments ?? '—']);
  if (st.updated_at_timestamp_ms) {
    rows.push([t('idxUpdated'), new Date(st.updated_at_timestamp_ms).toLocaleString()]);
  }
  const html = '<div class="table-wrap mf-table"><table><thead><tr><th>' + t('colMetric') + '</th><th>' + t('colValue') + '</th></tr></thead><tbody>' +
    rows.map(([k, v]) => `<tr><td class="mono" style="color:var(--muted)">${esc(k)}</td><td class="num">${esc(v)}</td></tr>`).join('') +
    '</tbody></table></div>';
  return html;
}

function idxTypeSpecificHtml(idx) {
  const st = idx.stats;
  if (!st) return '';
  const type = idx.type;
  let html = '';
  const indexData = (st.indices || [])[0] || {};

  if (type === 'Inverted' || type === 'FTSP') {
    html += `<div class="mf-section-title">${ti('invDetail')}</div>`;
    html += '<div class="table-wrap mf-table"><table><thead><tr>' +
      '<th>' + t('tokenCount') + '</th><th>' + t('docCount') + '</th></tr></thead><tbody>' +
      `<tr><td class="num">${indexData.num_tokens ?? '—'}</td><td class="num">${indexData.num_docs ?? '—'}</td></tr>` +
      '</tbody></table></div>';
    if (indexData.params) {
      html += `<div class="mf-section-title">${ti('tokenParams')}</div>`;
      html += `<div style="margin-bottom:4px">${idxParamsHtml(indexData.params)}</div>`;
    }
  } else if (type === 'BTree') {
    html += `<div class="mf-section-title">${ti('btreeDetail')}</div>`;
    html += '<div class="table-wrap mf-table"><table><thead><tr>' +
      '<th>min</th><th>max</th><th>' + t('colPages') + '</th></tr></thead><tbody>' +
      `<tr><td class="num">${esc(indexData.min ?? '—')}</td><td class="num">${esc(indexData.max ?? '—')}</td><td class="num">${esc(indexData.num_pages ?? '—')}</td></tr>` +
      '</tbody></table></div>';
  } else if (type === 'IVF_HNSW_FLAT' || type === 'HNSW' || type === 'IVF_PQ' || type === 'IVF_SQ' || type === 'FLAT') {
    html += `<div class="mf-section-title">${ti('vecDetail')}</div>`;
    const sub = indexData.sub_index || {};
    const subParams = sub.params || {};
    const params = [
      ['metric', indexData.metric_type ?? '—'],
      [t('vecDim'), sub.dim ?? '—'],
      [t('numPartitions'), indexData.num_partitions ?? '—'],
      ['HNSW M', subParams.m],
      ['ef_construction', subParams.ef_construction],
      ['max_level', subParams.max_level],
      ['entry_point', sub.entry_point],
      [t('idxFileVersion'), indexData.index_file_version ?? '—'],
    ];
    html += '<div class="table-wrap mf-table"><table><thead><tr><th>' + t('colMetric') + '</th><th>' + t('colValue') + '</th></tr></thead><tbody>' +
      params.map(([k, v]) => `<tr><td class="mono" style="color:var(--muted)">${esc(k)}</td><td class="num">${esc(v ?? '—')}</td></tr>`).join('') +
      '</tbody></table></div>';
    const centroids = idxFoldLabel(indexData.centroids);
    if (centroids) html += `<div class="mf-section-title">${ti('vecCentroids')}</div><div style="color:var(--muted);font-size:12px">${centroids}</div>`;
  } else if (type === 'BloomFilter') {
    html += `<div class="mf-section-title">${ti('bfDetail')}</div><div style="color:var(--muted);font-size:12px">${t('bfDesc')}</div>`;
  }
  return html;
}

function renderIndex(data) {
  const idxs = data.indices;
  const totalIndexed = idxs.reduce((s, i) => s + (i.stats?.num_indexed_rows || 0), 0);

  let html = `<div class="stats">
    <div class="stat"><b>${idxs.length}</b><span>${t('idxCount')}</span></div>
    <div class="stat"><b>${totalIndexed}</b><span>${t('idxIndexedRows')}</span></div>
  </div>`;

  if (idxs.length === 0) {
    html += '<div class="empty">' + t('idxNone') + '</div>';
    $('view').innerHTML = html;
    return;
  }

  // Overview table
  html += '<div class="mf-section-title">' + ti('idxOverview') + '</div>';
  html += '<div class="table-wrap"><table><thead><tr>' +
    '<th>' + t('colName2') + '</th><th>' + t('colType2') + '</th><th>' + t('colField2') + '</th><th>' + t('idxRows') + '</th><th>' + t('unidxRows') + '</th></tr></thead><tbody>';
  idxs.forEach(i => {
    html += `<tr>
      <td style="font-weight:600">${esc(i.name)}</td>
      <td>${idxTypeBadge(i.type)}</td>
      <td class="mono">${i.fields.map(esc).join(', ')}</td>
      <td class="num">${i.stats?.num_indexed_rows ?? '—'}</td>
      <td class="num">${i.stats?.num_unindexed_rows ?? '—'}</td>
    </tr>`;
  });
  html += '</tbody></table></div>';

  // Per-index details
  idxs.forEach(i => {
    html += `<div class="mf-section-title" style="margin-top:20px">${icon('scan-search', 14)} ${esc(i.name)}</div>`;
    html += `<div style="margin-bottom:6px">${idxTypeBadge(i.type)} ${i.fields.map(f => `<span class="mono" style="color:var(--accent)">${esc(f)}</span>`).join(' ')}</div>`;
    html += idxDetailRows(i);
    html += idxTypeSpecificHtml(i);
  });

  $('view').innerHTML = html;
}

// ---------- Version diff ----------

let diffFrom = null, diffTo = null;

async function loadVersionDiffUI() {
  showError(null); showLoading(true);
  $('view').innerHTML = '';
  try {
    const data = await fetchAPI('version_diff', {});
    showLoading(false);
    if (data.error) { showError(data.error); return; }
    if (!data.diff) { $('view').innerHTML = '<div class="empty">' + t('noVersions') + '</div>'; return; }
    // Initialize selection
    diffFrom = diffFrom ?? data.diff.from.version;
    diffTo = diffTo ?? data.diff.to.version;
    // Render dropdowns + diff
    const params = diffFrom !== data.diff.from.version || diffTo !== data.diff.to.version
      ? { from: diffFrom, to: diffTo } : {};
    const d2 = params.from || params.to ? await fetchAPI('version_diff', params) : data;
    if (d2.error) { showError(d2.error); return; }
    renderVersionDiff(d2);
  } catch (e) {
    showLoading(false); showError(t('requestFailed', {err: e}));
  }
}

async function runDiff() {
  showLoading(true);
  try {
    const data = await fetchAPI('version_diff', { from: diffFrom, to: diffTo });
    showLoading(false);
    if (data.error) { showError(data.error); return; }
    renderVersionDiff(data);
  } catch (e) { showLoading(false); showError(t('requestFailed', {err: e})); }
}

function deltaSpan(val, suffix='') {
  if (val === 0 || val === null || val === undefined) return `<span class="delta-zero">0</span>`;
  const cls = val > 0 ? 'delta-up' : 'delta-down';
  const sign = val > 0 ? '+' : '';
  return `<span class="${cls}">${sign}${val}${suffix}</span>`;
}

function fmtSizeB(b) {
  if (b === 0) return '0';
  if (b < 1024) return b + ' B';
  if (b < 1048576) return (b/1024).toFixed(1) + ' KB';
  return (b/1048576).toFixed(1) + ' MB';
}

function renderVersionDiff(data) {
  const d = data.diff;
  const vers = data.versions;
  const opts = v => `<option value="${v}" ${v===diffFrom?'selected':''}>v${v}</option>`;
  const opts2 = v => `<option value="${v}" ${v===diffTo?'selected':''}>v${v}</option>`;

  let html = `<div class="vs-selector">
    <span style="color:var(--muted)">${t('compare')}</span>
    <select id="diffFrom" onchange="diffFrom=parseInt(this.value);runDiff()">${vers.map(opts).join('')}</select>
    <span style="color:var(--muted)">→</span>
    <select id="diffTo" onchange="diffTo=parseInt(this.value);runDiff()">${vers.map(opts2).join('')}</select>
  </div>`;

  // Delta cards
  html += `<div class="stats">
    <div class="stat"><b>${deltaSpan(d.delta.rows)}</b><span>${t('diffRows', {from: d.from.version, to: d.to.version})}</span></div>
    <div class="stat"><b>${deltaSpan(d.delta.data_files)}</b><span>${t('diffDataFiles')}</span></div>
    <div class="stat"><b>${deltaSpan(d.delta.fragments)}</b><span>${t('diffFragments')}</span></div>
    <div class="stat"><b>${deltaSpan(d.delta.deletion_files)}</b><span>${t('diffTombstones')}</span></div>
    <div class="stat"><b>${deltaSpan(fmtSizeB(d.delta.size_bytes),'')}</b><span>${t('diffSize')}</span></div>
  </div>`;

  // Schema diff
  html += '<div class="mf-section-title">' + ti('schemaDiff') + '</div>';
  if (!d.schema.added.length && !d.schema.removed.length && !d.schema.type_changed.length) {
    html += '<div class="empty" style="padding:12px">' + t('schemaNoChange') + '</div>';
  } else {
    html += '<div class="table-wrap mf-table"><table><thead><tr><th>' + t('colChange') + '</th><th>' + t('colField2') + '</th></tr></thead><tbody>';
    d.schema.added.forEach(n => html += `<tr><td class="delta-up">${t('added')}</td><td class="mono">${esc(n)}</td></tr>`);
    d.schema.removed.forEach(n => html += `<tr><td class="delta-down">${t('removed')}</td><td class="mono">${esc(n)}</td></tr>`);
    d.schema.type_changed.forEach(tch => html += `<tr><td class="delta-zero">${t('typeChanged')}</td><td class="mono">${esc(tch.name)}: ${esc(tch.from)} → ${esc(tch.to)}</td></tr>`);
    html += '</tbody></table></div>';
  }

  // Index diff
  html += '<div class="mf-section-title">' + ti('indexDiff') + '</div>';
  if (!d.indices.added.length && !d.indices.removed.length) {
    html += '<div class="empty" style="padding:12px">' + t('indexNoChange') + '</div>';
  } else {
    html += '<div class="table-wrap mf-table"><table><thead><tr><th>' + t('colChange') + '</th><th>' + t('colIndex') + '</th><th>' + t('colType2') + '</th><th>' + t('colField2') + '</th></tr></thead><tbody>';
    d.indices.added.forEach(i => html += `<tr><td class="delta-up">${t('added')}</td><td style="font-weight:600">${esc(i[0])}</td><td>${idxTypeBadge(i[1])}</td><td class="mono">${(i[2]||[]).map(esc).join(', ')}</td></tr>`);
    d.indices.removed.forEach(i => html += `<tr><td class="delta-down">${t('removed')}</td><td style="font-weight:600">${esc(i[0])}</td><td>${idxTypeBadge(i[1])}</td><td class="mono">${(i[2]||[]).map(esc).join(', ')}</td></tr>`);
    html += '</tbody></table></div>';
  }

  // Version timeline
  html += '<div class="mf-section-title">' + ti('verTimeline', {from: d.from.version, to: d.to.version}) + '</div>';
  html += '<div class="table-wrap mf-table"><table><thead><tr>' +
    '<th>' + t('colVersion2') + '</th><th>' + t('colTime') + '</th><th>' + t('colRows') + '</th><th>' + t('diffDataFiles') + '</th><th>' + t('diffFragments') + '</th><th>' + t('diffTombstones') + '</th><th>' + t('diffSize') + '</th></tr></thead><tbody>';
  data.timeline.forEach(tt => {
    const isBoundary = tt.version === d.from.version || tt.version === d.to.version;
    html += `<tr${isBoundary ? ' style="background:#1d222c"' : ''}>
      <td><span class="mono" style="color:var(--violet);font-weight:600">v${tt.version}</span></td>
      <td class="ts">${tt.timestamp}</td>
      <td class="num">${tt.rows}</td>
      <td class="num">${tt.data_files}</td>
      <td class="num">${tt.fragments}</td>
      <td>${tt.deletion_files > 0
        ? `<span class="del-badge">${t('tombstoneCount', {n: tt.deletion_files, m: tt.deletion_rows ?? 0})}</span>`
        : '<span style="color:var(--muted)">' + t('noTombstone') + '</span>'}</td>
      <td class="num">${fmtSizeB(tt.size_bytes)}</td>
    </tr>`;
  });
  html += '</tbody></table></div>';

  $('view').innerHTML = html;
}

// ---------- Storage / compression analysis ----------

function compBadge(comps) {
  if (!comps || comps.length === 0) return '<span style="color:var(--muted)">' + t('notCompressed') + '</span>';
  return comps.map(c =>
    `<span class="layout-badge" style="border-color:var(--green);color:var(--green)">${esc(c)}</span>`).join(' ');
}

function pctBar(size, total) {
  const pct = total > 0 ? (size / total * 100) : 0;
  const w = Math.max(1, Math.round(pct));
  return `<div style="display:flex;align-items:center;gap:8px">
    <div style="flex:1;height:10px;background:#20242e;border-radius:5px;overflow:hidden;min-width:80px">
      <div style="width:${w}%;height:100%;background:var(--accent);border-radius:5px"></div>
    </div>
    <span class="num">${pct.toFixed(1)}%</span>
  </div>`;
}

function renderStorage(data) {
  const total = data.total_size;
  let html = `<div class="stats">
    <div class="stat"><b>${fmtSizeB(total)}</b><span>${t('totalSize')}</span></div>
    <div class="stat"><b>${data.data_files.length}</b><span>${t('dataFileCount')}</span></div>
  </div>`;

  // Type breakdown
  html += '<div class="mf-section-title">' + ti('storageTypes') + '</div>';
  html += '<div class="table-wrap"><table><thead><tr>' +
    '<th>' + t('colType3') + '</th><th>' + t('colCount') + '</th><th>' + t('colSize') + '</th><th>' + t('colPct') + '</th></tr></thead><tbody>';
  data.file_types.forEach(tt => {
    html += `<tr>
      <td style="font-weight:600">${esc(tt.label)}</td>
      <td class="num">${tt.count}</td>
      <td class="num">${fmtSizeB(tt.size)}</td>
      <td>${pctBar(tt.size, total)}</td>
    </tr>`;
  });
  html += '</tbody></table></div>';

  // Per-column storage of data files
  html += '<div class="mf-section-title" style="margin-top:20px">' + ti('colLevelStorage') + '</div>';
  const analysed = data.data_files_analyzed != null ? data.data_files_analyzed : data.data_files.length;
  const fileTotal = data.data_files_total != null ? data.data_files_total : analysed;
  if (fileTotal > analysed) {
    html += `<div class="section-note">${t('storageTopN', {n: analysed, total: fileTotal})}</div>`;
  }
  data.data_files.forEach(df => {
    const fileLabel = df.file.split('/').pop();
    html += `<div class="mf-section-title" style="margin-top:14px;font-size:12px">${icon('file-text', 14)} ${esc(fileLabel)} <span style="color:var(--muted)">${fmtSizeB(df.size)}</span></div>`;
    if (df.error) { html += `<div class="error">${icon('circle-alert', 14)} ${esc(df.error)}</div>`; return; }
    html += '<div class="table-wrap mf-table"><table><thead><tr>' +
      '<th>' + t('colField') + '</th><th>' + t('colStorage') + '</th><th>' + t('colPct') + '</th><th>' + t('colCompress') + '</th><th>' + t('colPages') + '</th></tr></thead><tbody>';
    df.columns.forEach(c => {
      html += `<tr>
        <td style="font-weight:600">${esc(c.name)}</td>
        <td class="num">${fmtSizeB(c.buffer_size)}</td>
        <td>${pctBar(c.buffer_size, df.size)}</td>
        <td>${compBadge(c.compression)}</td>
        <td class="num">${c.pages}</td>
      </tr>`;
    });
    html += '</tbody></table></div>';
  });

  // Top files
  html += '<div class="mf-section-title" style="margin-top:20px">' + ti('topFiles') + '</div>';
  html += '<div class="table-wrap mf-table"><table><thead><tr>' +
    '<th>' + t('colFile') + '</th><th>' + t('colSize') + '</th><th>' + t('colPct') + '</th></tr></thead><tbody>';
  data.top_files.forEach(f => {
    html += `<tr>
      <td class="mono" style="color:var(--violet)">${esc(f.path)}</td>
      <td class="num">${fmtSizeB(f.size)}</td>
      <td>${pctBar(f.size, total)}</td>
    </tr>`;
  });
  html += '</tbody></table></div>';

  $('view').innerHTML = html;
}

// ---------- Health / diagnostics ----------

function renderHealth(data) {
  const issues = data.issues || [];
  const issueIcon = { error: 'circle-alert', warn: 'circle-alert', info: 'lightbulb' };
  const issuesHtml = issues.length
    ? '<div class="issues">' + issues.map(issue => {
        const severity = ['error', 'warn', 'info'].includes(issue.severity) ? issue.severity : 'info';
        return `<div class="issue issue-${severity}">${icon(issueIcon[severity], 14)}
          <span>${esc(t('issue_' + issue.code, issue.params || {}))}</span></div>`;
      }).join('') + '</div>'
    : `<div class="health-ok">${icon('check', 14)} ${t('healthOk')}</div>`;

  const format = data.format || {};
  const frag = data.fragment_stats || {};

  let html = `<div class="mf-section-title">${ti('healthDiagnosis')}</div>` + issuesHtml;
  html += `<div class="stats">
    <div class="stat"><b>${data.rows}</b><span>${t('totalRows')}</span></div>
    <div class="stat"><b>${data.fragments}</b><span>${t('healthFragments')}</span></div>
    <div class="stat"><b>${data.versions}</b><span>${t('versions')}</span></div>
    <div class="stat"><b>${data.data_files}</b><span>${t('healthDataFiles')}</span></div>
    <div class="stat"><b>${fmtSizeB(data.size_bytes)}</b><span>${t('healthSize')}</span></div>
    <div class="stat"><b>${data.deleted_rows}</b><span>${t('healthDeletedRows')}</span></div>
  </div>`;
  html += `<div class="health-format">${t('healthFormat')}:
    <span class="mono">${esc(format.data_storage_version || '?')}</span></div>`;

  html += `<div class="mf-section-title">${t('healthFragmentSizes')}</div>
    <div class="stats">
      <div class="stat"><b>${frag.min ?? 0}</b><span>${t('healthMin')}</span></div>
      <div class="stat"><b>${frag.median ?? 0}</b><span>${t('healthMedian')}</span></div>
      <div class="stat"><b>${frag.max ?? 0}</b><span>${t('healthMax')}</span></div>
    </div>`;

  html += `<div class="mf-section-title">${t('healthCoverage')}</div>
    <div class="table-wrap mf-table"><table><thead><tr>
      <th>${t('colField')}</th><th>${t('colType')}</th><th>${t('colIndex')}</th>
    </tr></thead><tbody>`;
  (data.coverage || []).forEach(column => {
    const types = column.index_types || [];
    html += `<tr>
      <td style="font-weight:600">${esc(column.field)}</td>
      <td class="mono" style="color:var(--violet)">${esc(column.type)}</td>
      <td>${types.length
        ? types.map(type => `<span class="layout-badge">${esc(type)}</span>`).join(' ')
        : '<span style="color:var(--muted)">' + t('healthNoIndex') + '</span>'}</td>
    </tr>`;
  });
  html += '</tbody></table></div>';

  $('view').innerHTML = html;
}

// ---------- Transaction timeline ----------

function txnBadge(op) {
  const cls = {
    'append': 'txn-append', 'delete': 'txn-delete', 'overwrite': 'txn-overwrite',
    'create_index': 'txn-create_index', 'rewrite': 'txn-rewrite', 'update': 'txn-update',
  }[op] || '';
  return `<span class="txn-op ${cls}">${esc(op)}</span>`;
}

function opLabel(op) {
  const m = {
    'append': t('op_append'), 'delete': t('op_delete'), 'overwrite': t('op_overwrite'),
    'create_index': t('op_create_index'), 'rewrite': t('op_rewrite'), 'merge': t('op_merge'),
    'project': t('op_project'), 'restore': t('op_restore'), 'update': t('op_update'),
    'update_config': t('op_update_config'), 'data_replacement': t('op_data_replacement'),
    'clone': t('op_clone'), 'reserve_fragments': t('op_reserve_fragments'), 'data_overlay': t('op_data_overlay'),
  };
  return m[op] || op || t('op_unknown');
}

// Timeline paging: the backend decodes the newest chunk only. Older chunks are fetched on demand
// and prepended, so "load earlier" never re-reads what is already on screen (and a dataset with
// thousands of versions does not turn one tab click into thousands of object reads).
let timelineRows = null;
let timelineHasMore = false;
let timelineTotal = 0;
let timelineHasSnapshot = false;
const TIMELINE_CHUNK = 200;

function renderTimeline(data) {
  // Fresh load (tab switch, dataset switch): replace the accumulated window.
  timelineRows = data.transactions || [];
  timelineHasMore = !!data.has_more;
  timelineTotal = data.total != null ? data.total : timelineRows.length;
  timelineHasSnapshot = !!data.has_snapshot;
  drawTimeline();
}

async function loadEarlierTransactions() {
  if (!timelineRows) return;
  showLoading(true);
  try {
    const data = await fetchAPI('transactions',
      { limit: TIMELINE_CHUNK, offset: timelineRows.length });
    showLoading(false);
    if (data.error) { showError(data.error); return; }
    timelineRows = (data.transactions || []).concat(timelineRows);
    timelineHasMore = !!data.has_more;
    timelineTotal = data.total != null ? data.total : timelineRows.length;
    drawTimeline();
  } catch (e) {
    showLoading(false);
    showError(t('requestFailed', {err: e}));
  }
}

function drawTimeline() {
  const txns = timelineRows || [];
  const snap = timelineHasSnapshot;

  // Counters are computed from the loaded window rather than taken from the server: the server's
  // op_stats covers only the chunk it returned, which would drift after prepending an older chunk.
  const stats = {};
  for (const tx of txns) {
    if (tx.operation) stats[tx.operation] = (stats[tx.operation] || 0) + 1;
  }

  let statHtml = '';
  const statEntries = Object.entries(stats);
  if (statEntries.length) {
    statHtml = '<div class="stats">' + statEntries.map(([op, n]) =>
      `<div class="stat"><b>${n}</b><span>${txnBadge(op)} ${esc(opLabel(op))}</span></div>`).join('') +
      '</div>';
  }

  if (txns.length === 0) {
    $('view').innerHTML = statHtml + '<div class="empty">' + t('noTxns') + '</div>';
    return;
  }

  const windowBar = `<div class="timeline-window">
    <span>${t('timelineWindow', {n: txns.length, total: timelineTotal})}</span>
    ${timelineHasMore
      ? `<button class="btn-mini" onclick="loadEarlierTransactions()">${t('loadEarlier')}</button>`
      : ''}
  </div>`;

  // Timeline
  let html = statHtml + windowBar;
  html += '<div class="mf-section-title">' + ti('txnTimeline', {n: txns.length}) + '</div>';
  html += '<div class="table-wrap"><table><thead><tr>' +
    '<th>' + t('colVersion2') + '</th><th>' + t('colOp') + '</th><th>' + t('colTime') + '</th>' +
    (snap ? '<th>' + t('colRows') + '</th><th>' + t('diffDataFiles') + '</th><th>' + t('diffFragments') + '</th><th>' + t('diffTombstones') + '</th><th>' + t('diffSize') + '</th>' : '') +
    '<th>' + t('colReadVersion') + '</th></tr></thead><tbody>';
  txns.forEach(tx => {
    if (tx.error) {
      html += `<tr><td class="num">${esc(tx.file)}</td><td colspan="6"><div class="error">${icon('circle-alert', 14)} ${esc(tx.error)}</div></td></tr>`;
      return;
    }
    const s = tx.snapshot;
    html += `<tr>
      <td><span class="mono" style="color:var(--violet);font-weight:600">v${tx.version ?? '?'}</span></td>
      <td>${txnBadge(tx.operation)} <span style="color:var(--muted);font-size:12px">${esc(opLabel(tx.operation))}</span></td>
      <td class="ts">${esc(s?.timestamp || tx.mtime || '—')}</td>
      ${snap ? `
      <td class="num">${s ? s.rows : '—'}</td>
      <td class="num">${s ? s.data_files : '—'}</td>
      <td class="num">${s ? s.fragments : '—'}</td>
      <td>${s && s.deletion_files > 0
        ? `<span class="del-badge">${t('tombstoneCount', {n: s.deletion_files, m: s.deletion_rows})}</span>`
        : '<span style="color:var(--muted)">' + t('noTombstone') + '</span>'}</td>
      <td class="num">${s ? fmtSizeB(s.size_bytes) : '—'}</td>
      ` : ''}
      <td class="num">${tx.read_version ?? '—'}</td>
    </tr>`;
  });
  html += '</tbody></table></div>';

  $('view').innerHTML = html;
}

// ---------- Branch / version / tag view ----------

// Snapshot version the current data view reads: None = latest; otherwise a concrete version number
let curSnapshotVersion = null;
// refs cache (branches/tags/versions of the current dataset), used when switching branches
let refsCache = null;
// Currently selected branch name ('main' or an actual branch)
let curBranch = 'main';
// Data preview pagination: rows per page and current page (0-based)
// Page size is user-selectable; 20 is the default. Wide tables are why 500 is not offered:
// every extra row is another full row of cells to build and paint.
const DATA_PAGE_SIZES = [20, 50, 100, 200];
let dataPageSize = 20;
// Version dropdown cap: only the newest N versions are rendered as <option>s (see renderRefsBar).
const MAX_VERSIONS = 100;
let dataPage = 0;
// null = read every column (the default). An array = an explicit projection, so only those
// columns are read off storage. Kept across pages and versions until the user clears it.
let dataColumns = null;
// Row filter for the Data tab: a Lance SQL predicate evaluated server-side. Empty = no filter.
let dataFilter = '';

// Toggle one column in the projection. The chip row doubles as the picker, so there is no
// separate column dialog: every schema field is already on screen with its type.
function toggleDataColumn(name) {
  const all = window.__schemaNames || [];
  // Without the schema list there is nothing to subtract from, and starting from an empty set
  // would turn "hide this column" into "show only this column". The chips are not on screen
  // before the schema arrives, so this is a guard, not a path the user can reach.
  if (!all.length) return;
  // Starting from the full set on the first click keeps the visible selection honest: the table
  // currently shows every column, so "everything except this one" is what the user means.
  const cur = dataColumns ? dataColumns.slice() : all.slice();
  const i = cur.indexOf(name);
  if (i === -1) cur.push(name); else cur.splice(i, 1);
  // Turning the last column off falls back to all columns: an empty projection renders an empty
  // table (to_table(columns=[]) returns zero columns) with no obvious way out.
  dataColumns = cur.length && cur.length !== all.length ? cur : null;
  // No page reset here: a projection changes neither the row count nor the row order, so the
  // current offset stays valid and is not worth losing the user's place for.
  reloadDataTab();
}

// Chip click: resolve the index back to the name here, in JS, so the onclick only ever carries a
// number. Keeps arbitrary column names out of the markup entirely.
function toggleDataColumnAt(i) {
  const all = window.__schemaNames || [];
  if (i >= 0 && i < all.length) toggleDataColumn(all[i]);
}

function selectAllDataColumns() {
  dataColumns = null;
  reloadDataTab();
}

function applyDataFilter() {
  const input = $('dataFilter');
  if (!input) return;
  dataFilter = (input.value || '').trim();
  dataPage = 0;   // a different row set means the old offset is meaningless
  reloadDataTab();
}

function clearDataFilter() {
  dataFilter = '';
  dataPage = 0;
  reloadDataTab();
}


// Accept a refs payload returned alongside the dataset response (one dataset open, not two),
// and normalise the selected branch/snapshot against it.
function applyRefs(refs) {
  if (!refs || refs.error) { refsCache = null; return false; }
  refsCache = refs;
  // If the currently selected branch no longer exists, fall back to main
  const branchNames = ['main'].concat((refs.branches || []).map(b => b.name));
  if (branchNames.indexOf(curBranch) === -1) curBranch = 'main';
  // If the current snapshot version is no longer in the version list, fall back to latest
  const vers = (refs.versions || []).map(v => v.version);
  let invalidated = false;
  if (curSnapshotVersion != null && vers.indexOf(curSnapshotVersion) === -1) {
    curSnapshotVersion = null;
    invalidated = true;
  }
  // True means the caller asked for a snapshot that no longer exists and should retry at latest.
  return invalidated;
}

// Render the branch/version bar HTML, injected at the top of #view; curSnapshotVersion drives selection
function renderRefsBar() {
  const refs = refsCache;
  if (!refs) return '';
  const branches = (refs.branches || []).map(b => b.name);
  const allBranches = ['main'].concat(branches);
  const versions = refs.versions || [];
  const tagByVer = refs.tag_by_version || {};

  // Latest version each branch points to (shown in the branch dropdown): main = max version, others use their ref version
  let branchVer = {};
  (refs.branches || []).forEach(b => { if (b.version != null) branchVer[b.name] = b.version; });
  if (versions.length) branchVer['main'] = versions[versions.length - 1].version;

  const branchOpts = allBranches.map(b =>
    `<option value="${esc(b)}" ${b === curBranch ? 'selected' : ''}>` +
      `${icon('git-branch', 13)} ${esc(b)}` + (branchVer[b] != null ? ` (v${branchVer[b]})` : '') +
    `</option>`).join('');

  // Version dropdown: newest MAX_VERSIONS entries only. A long-lived dataset accumulates thousands
  // of versions, and one <option> each makes the refs bar itself the slow part of the page. The
  // selected version stays visible even when it falls outside the window; the jump box reaches the
  // rest by number.
  const verLabel = v => {
    const tags = tagByVer[v.version] || [];
    return tags.length
      ? `${icon('tag', 13)} ${esc(tags.join(', '))} (v${v.version})`
      : `v${v.version}` + (v.timestamp ? ` · ${v.timestamp.slice(0, 10)}` : '');
  };
  let shownVersions = versions.slice(-MAX_VERSIONS);
  if (curSnapshotVersion != null && !shownVersions.some(v => v.version === curSnapshotVersion)) {
    shownVersions = [{version: curSnapshotVersion, timestamp: null}].concat(shownVersions);
  }
  const verOpts = shownVersions.map(v =>
    `<option value="${v.version}" ${v.version === curSnapshotVersion ? 'selected' : ''}>${verLabel(v)}</option>`
  ).join('');

  const trimmed = versions.length > MAX_VERSIONS;
  // The note names the window size, not the option count: a pinned out-of-window selection adds one
  // extra option without making the window any bigger.
  const versionNote = trimmed
    ? `<span class="refs-note">${t('versionsTrimmed', {n: MAX_VERSIONS, total: versions.length})}</span>`
    : '';
  const jumpBox = trimmed
    ? `<input id="refVersionJump" class="refs-jump" type="number" min="1" placeholder="${t('versionJumpPlaceholder')}">
       <button class="btn-mini" onclick="jumpToRefVersion()">${t('versionJumpGo')}</button>`
    : '';

  return `<div class="refs-bar">
    <span class="refs-label">${ti('branchLabel')}</span>
    <select id="refBranch" onchange="onRefBranchChange()">${branchOpts}</select>
    <span class="refs-label">${ti('versionLabel')}</span>
    <select id="refVersion" onchange="onRefVersionChange()">${verOpts}</select>
    ${versionNote}${jumpBox}
    ${curSnapshotVersion != null ? `<span class="refs-snapshot">${t('snapshotViewing', {ver: curSnapshotVersion})}</span>` : ''}
  </div>`;
}

function onRefBranchChange() {
  const sel = $('refBranch');
  curBranch = sel.value;
  // Branch switch -> jump to that branch's current version
  if (curBranch === 'main') {
    const vers = (refsCache?.versions || []);
    curSnapshotVersion = vers.length ? vers[vers.length - 1].version : null;
  } else {
    const b = (refsCache?.branches || []).find(x => x.name === curBranch);
    curSnapshotVersion = (b && b.version != null) ? b.version : null;
  }
  dataPage = 0;
  reloadDataTab();
}

function onRefVersionChange() {
  const sel = $('refVersion');
  const v = parseInt(sel.value, 10);
  curSnapshotVersion = isNaN(v) ? null : v;
  dataPage = 0;
  reloadDataTab();
}

// Jump box for the version bar: versions older than the rendered window are still reachable by
// number. Unknown numbers are rejected here rather than sent to the server as a confusing error.
function jumpToRefVersion() {
  const el = $('refVersionJump');
  if (!el) return;
  const v = parseInt(el.value, 10);
  if (!el.value || isNaN(v) || v < 1) return;
  const known = (refsCache?.versions || []).some(x => x.version === v);
  if (!known) {
    showError(t('versionNotFound', {v}));
    return;
  }
  curSnapshotVersion = v;
  dataPage = 0;
  reloadDataTab();
}

// Data preview paging: offset = page * dataPageSize
function setDataPage(page) {
  const count = window.__dataCount != null ? window.__dataCount : 0;
  const maxPage = Math.max(0, Math.ceil(count / dataPageSize) - 1);
  dataPage = Math.max(0, Math.min(page, maxPage));
  reloadDataTab();
}

// Changing the page size keeps the row the user is looking at: convert the first visible row's
// index into the new page size instead of jumping back to page 1 and losing their place.
function setPageSize(n) {
  n = parseInt(n, 10);
  if (DATA_PAGE_SIZES.indexOf(n) === -1 || n === dataPageSize) return;
  const firstRow = dataPage * dataPageSize;
  dataPageSize = n;
  dataPage = Math.floor(firstRow / n);
  reloadDataTab();
}

// Jump box: clamp instead of ignoring, so a typo of 0 or 9999 lands on a real page.
function jumpToDataPage(inputId) {
  const el = $(inputId);
  if (!el) return;
  const total = Math.max(1, Math.ceil((window.__dataCount || 0) / dataPageSize));
  const n = parseInt(el.value, 10);
  el.value = '';
  setDataPage(isNaN(n) ? dataPage : Math.max(1, Math.min(n, total)) - 1);
}

// Reload the data tab (per current curSnapshotVersion + current page)
async function reloadDataTab() {
  showLoading(true);
  try {
    const params = { limit: dataPageSize, offset: dataPage * dataPageSize };
    if (curSnapshotVersion != null) params.version = curSnapshotVersion;
    if (dataColumns) params.cols = dataColumns;
    if (dataFilter) params.filter = dataFilter;
    const data = await fetchAPI('dataset', params);
    showLoading(false);
    if (data.error) { showError(data.error); return; }
    renderData(data);
  } catch (e) {
    showLoading(false); showError(t('requestFailed', {err: e}));
  }
}

function renderData(data) {
  // Branch/version/tag bar (top)
  const refsBar = renderRefsBar();
  // The server echoes the filter it applied, so the input always shows what the rows reflect.
  if (data.filter !== undefined) dataFilter = data.filter || '';
  const filterBar = `<div class="filter-bar">
    <input id="dataFilter" class="filter-input" value="${esc(dataFilter)}"
      placeholder="${t('filterPlaceholder')}"
      onkeydown="if(event.key==='Enter')applyDataFilter()">
    <button class="btn-mini" onclick="applyDataFilter()">${t('filterApply')}</button>
    <button class="btn-mini btn-plain" onclick="clearDataFilter()">${t('filterClear')}</button>
    ${dataFilter ? `<span class="filter-note">${t('filterScope', {expr: esc(dataFilter)})}</span>` : ''}
  </div>`;
  // Top stats
  const stats = `
    <div class="stats">
      <div class="stat"><b>${data.count}</b><span>${t('totalRows')}</span></div>
      <div class="stat"><b>${data.shown}</b><span>${t('shown')}</span></div>
      <div class="stat"><b>${data.versions}</b><span>${t('versions')}</span></div>
      <div class="stat"><b>${data.schema.length}</b><span>${t('cols')}</span></div>
    </div>`;
  // Schema chips double as the column picker (option A): every field is already listed with its
  // type, so a click on a chip toggles that column instead of a second row of controls.
  const allNames = data.schema.map(f => f.name);
  window.__schemaNames = allNames;
  // A version switch can change the schema; drop names that no longer exist so the projection
  // never asks for a column this snapshot does not have (the server rejects unknown names).
  if (dataColumns) {
    const kept = dataColumns.filter(c => allNames.indexOf(c) !== -1);
    dataColumns = kept.length && kept.length !== allNames.length ? kept : null;
  }
  const picked = dataColumns ? dataColumns : allNames;
  const chips = data.schema.map((f, i) => {
    const on = picked.indexOf(f.name) !== -1;
    // Pass the schema index, never the name: a column name is arbitrary text from the dataset and
    // has no business being parsed as JavaScript inside an onclick attribute.
    return `<span class="chip col-chip${on ? ' on' : ''} mono" onclick="toggleDataColumnAt(${i})"
      title="${on ? t('colsHide') : t('colsShow')}">
      ${esc(f.name)} <span style="color:var(--violet)">${esc(f.type)}</span></span>`;
  }).join('');
  const pickerBar = `<div class="col-picker">${chips}</div>`;
  const pickInfo = dataColumns
    ? `<span class="col-count">${t('colsShown', { n: picked.length, total: allNames.length })}</span>
       <button class="btn-mini" onclick="selectAllDataColumns()">${t('colsAll')}</button>`
    : `<span class="col-count">${t('colsShown', { n: allNames.length, total: allNames.length })}</span>`;
  // Table
  const cols = data.columns;
  const names = Object.keys(cols);
  const n = data.shown;
  // refsBar only matters when there are branches/tags/multiple versions; show it when present (even on empty tables so you can switch versions)
  const bar = refsBar ? `<div class="refs-bar-wrap">${refsBar}</div>` : '';
  let html = bar + filterBar + stats + `<div style="margin-bottom:14px"><div class="col-picker-head">${pickInfo}</div>${pickerBar}</div><div class="table-wrap data-wrap"><table><thead><tr>`;
  html += names.map(c => `<th>${esc(c)}</th>`).join('');
  html += '</tr></thead><tbody>';
  for (let r = 0; r < n; r++) {
    html += '<tr>';
    for (const c of names) {
      const v = cols[c][r];
      const ts = data.display.find(d => d.name === c)?.timestamp;
      let cell;
      if (ts && typeof v === 'number') {
        const dt = new Date(v > 1e12 ? v : v * 1000);
        cell = `<span class="ts" title="${dt.toISOString()}">${dt.toLocaleString()}</span>`;
      } else if (Array.isArray(v)) {
        cell = `<span class="vec" title="${t('clickExpand')}" onclick="toggleVec(this, ${JSON.stringify(v)}, ${v.length})">${sparkline(v)}<span class="vec-label">${t('vecExpand', {dims: v.length})}</span></span>`;
      } else if (typeof v === 'string') {
        const looksNum = /^-?[\d.]+$/.test(v);
        const badge = c.toLowerCase().includes('category') ? badgeFor(v) : '';
        cell = badge || (looksNum
          ? `<span class="num">${v}</span>`
          : `<span class="trunc" title="${esc(v)}">${esc(v.length>90? v.slice(0,90)+'…': v)}</span>`);
      } else if (typeof v === 'number') {
        cell = `<span class="num">${v}</span>`;
      } else {
        cell = v == null ? '<span style="color:#5a6070">null</span>' : esc(String(v));
      }
      html += `<td>${cell}</td>`;
    }
    html += '</tr>';
  }
  html += '</tbody></table></div>';
  // Pagination bar
  const totalPages = Math.max(1, Math.ceil(data.count / dataPageSize));
  const cur = dataPage + 1;
  window.__dataCount = data.count;
  // The bar stays visible even on a single page: that is where the page-size control lives, and a
  // table that fits in one page can still be switched to a denser one.
  const pagination = renderPagination(cur, totalPages, data.count);
  html += pagination;
  // Empty tables still show the bar (branch/version) and schema chips, otherwise you can't switch back to a version with data
  const emptyLabel = dataFilter && data.count === 0 ? t('filterNoRows') : t('emptyDataset');
  $('view').innerHTML = n ? html : bar + filterBar + stats + `<div style="margin-bottom:14px"><div class="col-picker-head">${pickInfo}</div>${pickerBar}</div><div class="empty">${emptyLabel}</div>`;
}

// Page numbers to draw: first and last always visible, current +/-2, gaps collapsed to an ellipsis.
// A full 250-button row is unreadable and reflow-heavy; this keeps five or so around the cursor.
function pageWindow(cur, total) {
  const win = new Set([1, total]);
  for (let p = cur - 2; p <= cur + 2; p++) if (p >= 1 && p <= total) win.add(p);
  const pages = [...win].sort((a, b) => a - b);
  const out = [];
  let prev = 0;
  for (const p of pages) {
    if (prev && p - prev > 1) out.push(null); // null renders as the ellipsis
    out.push(p);
    prev = p;
  }
  return out;
}

// Data preview pagination bar: page size, first/prev, numbered window, next/last, jump box.
function renderPagination(cur, totalPages, totalRows) {
  const disablePrev = cur <= 1 ? 'disabled' : '';
  const disableNext = cur >= totalPages ? 'disabled' : '';
  const sizes = DATA_PAGE_SIZES.map(n =>
    `<option value="${n}"${n === dataPageSize ? ' selected' : ''}>${n}</option>`).join('');
  const nums = pageWindow(cur, totalPages).map(p => p === null
    ? `<span class="pager-gap">…</span>`
    : (p === cur
      ? `<span class="pager-btn cur">${p}</span>`
      : `<button class="pager-btn" onclick="setDataPage(${p - 1})">${p}</button>`)).join('');
  return `<div class="pagination">
    <span class="pagination-info">${t('pageInfo', {total: totalRows, cur, pages: totalPages})}</span>
    <label class="pager-size">${t('pageSize')}
      <select onchange="setPageSize(this.value)">${sizes}</select>
    </label>
    <button class="btn-mini" onclick="setDataPage(0)" ${disablePrev}>${t('firstPage')}</button>
    <button class="btn-mini" onclick="setDataPage(${cur - 2})" ${disablePrev}>${t('prev')}</button>
    <span class="pager-nums">${nums}</span>
    <button class="btn-mini" onclick="setDataPage(${cur})" ${disableNext}>${t('next')}</button>
    <button class="btn-mini" onclick="setDataPage(${totalPages - 1})" ${disableNext}>${t('lastPage')}</button>
    <label class="pager-jump">${t('jumpTo')}
      <input type="text" inputmode="numeric" id="pagerJump" value=""
             onkeydown="if(event.key==='Enter')jumpToDataPage('pagerJump')">
      ${t('pageUnit')}
    </label>
    <button class="btn-mini" onclick="jumpToDataPage('pagerJump')">${t('jump')}</button>
  </div>`;
}

// Vector column expand/collapse: show real values or the folded label.
// On expand we also show generic vector stats (norm/sparsity/min/max/mean/pos-ratio/normalized)
// and a larger sparkline, computed client-side — no dependency on any specific embedding model.
toggleVec = (el, values, dims) => {
  const open = el.classList.toggle('expanded');
  if (open) {
    const st = vecStats(values);
    const nums = values.map(x => Number.isInteger(x) ? x : +x.toFixed(4)).join(', ');
    const statsRow = `
      <div class="vec-stats">
        <span>${t('vecNorm')} <b>${st.norm.toFixed(4)}</b></span>
        <span>${t('vecSparsity')} <b>${(st.sparsity*100).toFixed(1)}%</b></span>
        <span>${t('vecMin')} <b>${st.min.toFixed(4)}</b></span>
        <span>${t('vecMax')} <b>${st.max.toFixed(4)}</b></span>
        <span>${t('vecMean')} <b>${st.mean.toFixed(4)}</b></span>
        <span>${t('vecPosRatio')} <b>${(st.positiveRatio*100).toFixed(1)}%</b></span>
        <span class="${st.normalized ? 'norm-ok' : ''}">${st.normalized ? t('vecNormed') : t('vecNotNormed')}</span>
      </div>`;
    el.innerHTML = `${sparkline(values, 120, 30)}
      <span class="vec-label">${t('vecDims', {dims})}</span>
      <div class="vec-nums">${nums}</div>${statsRow}`;
  } else {
    el.innerHTML = `${sparkline(values)}<span class="vec-label">${t('vecExpand', {dims})}</span>`;
  }
};

// Generic vector statistics (works for any embedding dimension/model).
function vecStats(v) {
  if (!v || !v.length) return { n: 0, min: 0, max: 0, mean: 0, norm: 0, sparsity: 0, positiveRatio: 0, normalized: false };
  let sum = 0, sumSq = 0, min = Infinity, max = -Infinity, nz = 0, pos = 0;
  const n = v.length;
  for (let i = 0; i < n; i++) {
    const x = v[i];
    sum += x; sumSq += x * x;
    if (x < min) min = x;
    if (x > max) max = x;
    if (x !== 0) nz++;
    if (x > 0) pos++;
  }
  const norm = Math.sqrt(sumSq);
  return {
    n, min, max,
    mean: sum / n,
    norm,
    sparsity: n ? 1 - nz / n : 0,
    positiveRatio: n ? pos / n : 0,
    normalized: Math.abs(norm - 1) < 1e-4,
  };
}

// Minimal inline SVG sparkline (zero dependencies). Draws a zero-line and the value polyline.
function sparkline(v, w = 44, h = 14) {
  const n = v ? v.length : 0;
  if (!n) return '';
  let min = Infinity, max = -Infinity;
  for (const x of v) { if (x < min) min = x; if (x > max) max = x; }
  const span = (max - min) || 1;
  const pts = v.map((x, i) => {
    const px = (i / (n - 1)) * w;
    const py = (h - 1) - ((x - min) / span) * (h - 2);
    return `${px.toFixed(1)},${py.toFixed(1)}`;
  }).join(' ');
  const zeroY = (h - 1) - ((-min) / span) * (h - 2);
  return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">` +
    `<line x1="0" y1="${zeroY.toFixed(1)}" x2="${w}" y2="${zeroY.toFixed(1)}" class="spark-zero"/>` +
    `<polyline points="${pts}" class="spark-line"/></svg>`;
}

function badgeFor(cat) {
  if (!cat) return '';
  const m = {fact:'b-fact', preference:'b-preference', other:'b-other'}[cat.toLowerCase()];
  return `<span class="badge ${m||'b-other'}">${esc(cat)}</span>`;
}

// Index file type identification (for file-tree tags)
function indexFileLabel(name) {
  if (name === 'index.idx') return t('labelIdxMain');
  if (name === 'auxiliary.idx') return t('labelIdxAux');
  if (/^part_.*_tokens\.lance$/.test(name)) return t('labelTokenDict');
  if (/^part_.*_invert\.lance$/.test(name)) return t('labelInvertList');
  if (/^part_.*_docs\.lance$/.test(name)) return t('labelDocMap');
  if (name === 'metadata.lance') return t('labelIdxMeta');
  if (name === 'page_lookup.lance') return t('labelPageLookup');
  if (name === 'page_data.lance') return t('labelPageData');
  return '';
}

// Index file field-name explanations
function indexFieldExplain(name) {
  if (name === '__vector_id') return t('field_vector_id');
  if (name === '__neighbors') return t('field_neighbors');
  if (name === '_distance') return t('field_distance');
  if (name === '_rowid') return t('field_rowid');
  if (name === 'flat') return t('field_flat');
  if (name === 'item') return t('field_item');
  if (name === 'token') return t('field_token');
  if (name === 'doc_id') return t('field_doc_id');
  if (name === 'term_frequency') return t('field_term_frequency');
  return '';
}

// Index file overview: infer index type from file path + schema and explain it
function indexExplainBlock(file, schema) {
  if (!file) return '';
  const base = file.split('/').pop();
  const cols = (schema || []).map(c => c.name);
  let title, desc;

  // Inverted / FTS index files
  if (/part_.*(invert|tokens|docs)\.lance$/.test(base)) {
    if (base.includes('tokens')) {
      title = ti('idxTitle_tokens');
      desc = t('idxDesc_tokens');
    } else if (base.includes('invert')) {
      title = ti('idxTitle_invert');
      desc = t('idxDesc_invert');
    } else {
      title = ti('idxTitle_docs');
      desc = t('idxDesc_docs');
    }
  }
  // BTree index
  else if (/page_(data|lookup)\.lance$/.test(base)) {
    title = ti('idxTitle_btree');
    desc = t('idxDesc_btree');
  }
  // Vector index
  else if (base === 'index.idx') {
    title = ti('idxTitle_index');
    desc = t('idxDesc_index');
  } else if (base === 'auxiliary.idx') {
    title = ti('idxTitle_aux');
    desc = t('idxDesc_aux');
  }
  // Metadata
  else if (base === 'metadata.lance') {
    title = ti('idxTitle_meta');
    desc = t('idxDesc_meta');
  }

  if (!title) return '';
  return `<div class="mf-section-title" style="color:var(--amber)">${icon('lightbulb', 14)} ${t('explainTitle', {title})}</div>
    <div class="index-explain">${desc}</div>`;
}
