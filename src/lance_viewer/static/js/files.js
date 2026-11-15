// Lance Viewer - file viewers (manifest/txn/json/arrow/datafile)
// Deps: tools.js. renderDatafile uses indexExplainBlock from render.js.

// ---------- Manifest viewer ----------

async function openFile(file, kind) {
  const api = kind === 'manifest' ? 'manifest' : kind === 'txn' ? 'txn' : kind === 'json' ? 'json' : kind === 'arrow' ? 'arrow' : 'datafile';
  $('mfFile').textContent = file;
  $('mfBody').innerHTML = '<div class="loading"><span class="spinner"></span>' + t('decoding') + '</div>';
  $('mfSummary').innerHTML = '';
  $('manifestModal').style.display = 'flex';
  try {
    const r = await fetchAPI(api, { file });
    if (r.error) {
      $('mfBody').innerHTML = `<div class="error">${icon('circle-alert', 14)} ${esc(r.error)}</div>`;
      return;
    }
    if (kind === 'manifest') renderManifest(r);
    else if (kind === 'txn') renderTxn(r);
    else if (kind === 'json') renderJsonFile(r);
    else if (kind === 'arrow') renderArrowFile(r);
    else renderDatafile(r);
  } catch (e) {
    $('mfBody').innerHTML = `<div class="error">${icon('circle-alert', 14)} ${esc(t('requestFailed', {err: e}))}</div>`;
  }
}

function closeManifest() { $('manifestModal').style.display = 'none'; }

document.addEventListener('keydown', e => { if (e.key === 'Escape') closeManifest(); });
$('manifestModal')?.addEventListener('click', e => {
  if (e.target.id === 'manifestModal') closeManifest();
});

function renderManifest(data) {
  const s = data.summary;
  const schemaChips = s.schema_cols.map(c =>
    `<span class="chip mono" style="background:#20242e;border:1px solid var(--border);padding:3px 8px;border-radius:5px;font-size:11px;margin:2px">${esc(c.name)} <span style="color:var(--violet)">${esc(c.logical_type||'?')}</span> <span style="color:var(--amber);font-size:10px">${esc(c.encoding||'')}</span></span>`
  ).join('');

  const fragInfo = s.fragments.map((f,i) =>
    `frag${i}: id=${f.id??'—'} rows=${f.physical_rows} files=${f.files.length}`
  ).join(' · ');

  $('mfSummary').innerHTML = `
    <span class="stat-inline"><b>v${s.version}</b></span>
    <span class="stat-inline">fragments: <b>${s.fragments.length}</b></span>
    <span class="stat-inline">max_fragment_id: <b>${s.max_fragment_id??'—'}</b></span>
    <span class="stat-inline">reader_flags: <b>${s.reader_feature_flags??'—'}</b></span>
    <span class="stat-inline">writer_flags: <b>${s.writer_feature_flags??'—'}</b></span>
    <div style="margin-top:8px">${schemaChips}</div>
    <div style="margin-top:6px;font-size:11px;color:var(--muted)">${fragInfo}</div>
  `;

  // Full JSON tree
  const full = { manifest_pos: data.full.manifest_pos, magic: data.full.magic, ...data.full.data };
  const tablesHtml = renderManifestTables(full);
  $('mfBody').innerHTML =
    `<div id="mfTables">${tablesHtml}</div>` +
    '<div class="mf-section-title">' + ti('fullJsonProto') + '</div>' +
    '<div class="json-tree" id="jsonTree"></div>';
  renderJsonTree(full, $('jsonTree'));
}

// ---------- Transaction (txn) rendering ----------

function renderTxn(data) {
  const s = data.summary;
  const d = data.full.data;

  const opBadge = s.operation
    ? `<span class="txn-op txn-${esc(s.operation)}">${esc(s.operation_label || s.operation)}</span>`
    : `<span class="txn-op">${t('unknownOp')}</span>`;

  $('mfSummary').innerHTML = `
    ${opBadge}
    <span class="stat-inline">read_version: <b>${s.read_version ?? '—'}</b></span>
    <span class="stat-inline">fragments: <b>${s.fragments}</b></span>
    <span class="stat-inline">rows: <b>${s.physical_rows ?? '—'}</b></span>
    <span class="stat-inline">data_files: <b>${s.data_files}</b></span>
    <div style="margin-top:6px;font-size:11px;color:var(--muted)">uuid: <span class="mono">${esc(s.uuid ?? '—')}</span></div>
  `;

  // Structured tables (append has fragments; other ops may have different shapes)
  let tablesHtml = renderTxnTables(d);
  // Full JSON tree
  $('mfBody').innerHTML =
    `<div id="mfTables">${tablesHtml}</div>` +
    '<div class="mf-section-title">' + ti('fullJsonProto') + '</div>' +
    '<div class="json-tree" id="jsonTree"></div>';
  renderJsonTree(d, $('jsonTree'));
}

function renderJsonFile(data) {
  const d = data.data;
  const file = data.file;

  // Explanation block: latest_version_hint.json is a lightweight file in Lance's versions dir pointing to the latest version
  let explain = '';
  if (file.endsWith('latest_version_hint.json')) {
    explain = `<div class="mf-section-title" style="color:var(--amber)">${ti('hintLatestVersionTitle')}</div>
      <div class="index-explain">${t('hintLatestVersionDesc')}</div>`;
  }

  // Summary: expand top-level key-values
  let summary = '';
  if (d && typeof d === 'object' && !Array.isArray(d)) {
    const items = Object.entries(d).map(([k, v]) => {
      const val = typeof v === 'object' ? JSON.stringify(v) : String(v);
      return `<span class="stat-inline"><b>${esc(k)}</b>: <span class="mono">${esc(val)}</span></span>`;
    }).join('');
    if (items) summary = `<div>${items}</div>`;
  }

  $('mfSummary').innerHTML = summary;
  $('mfBody').innerHTML =
    `${explain}` +
    '<div class="mf-section-title">' + t('jsonContent') + '</div>' +
    '<div class="json-tree" id="jsonTree"></div>';
  renderJsonTree(d, $('jsonTree'));
}

function renderArrowFile(data) {
  const d = data;

  // Summary
  $('mfSummary').innerHTML = `
    <span class="stat-inline"><b>${t('rowsDeleted', {n: d.total_rows})}</b></span>
    <span class="stat-inline">batch: <b>${d.num_batches}</b></span>
    <span class="stat-inline">${t('col')}: <b>${d.schema.length}</b></span>
  `;

  // Explanation block
  const explain = `<div class="mf-section-title" style="color:var(--red)">${ti('deletionTitle')}</div>
    <div class="index-explain">${t('deletionDesc')}</div>`;

  // Schema chips
  const chips = d.schema.map(c =>
    `<span class="chip mono" style="display:inline-block;background:#20242e;border:1px solid var(--border);padding:4px 10px;border-radius:6px;font-size:12px;margin:2px">
      ${esc(c.name)} <span style="color:var(--violet)">${esc(c.type)}</span></span>`).join('');

  // Data table
  const cols = d.schema.map(c => c.name);
  let html = explain;
  if (d.schema.length) html += `<div style="margin-bottom:12px">${chips}</div>`;
  html += '<div class="mf-section-title">' + ti('deletedRowsTitle') + '</div>';
  if (d.total_rows === 0) {
    html += '<div class="empty">' + t('deletionEmpty') + '</div>';
  } else {
    html += '<div class="table-wrap mf-table"><table><thead><tr>' +
      cols.map(c => `<th>${esc(c)}</th>`).join('') +
      '</tr></thead><tbody>';
    d.rows.forEach((row, i) => {
      html += '<tr>';
      for (const c of cols) {
        const v = row[c];
        html += `<td>${v == null ? '<span style="color:#5a6070">null</span>' : (typeof v === 'number' ? `<span class="num">${v}</span>` : esc(String(v)))}</td>`;
      }
      html += '</tr>';
    });
    html += '</tbody></table></div>';
  }

  $('mfBody').innerHTML = html;
}

function renderTxnTables(d) {
  let html = '';
  // Append -> fragments table
  if (d.append && d.append.fragments) {
    const frags = d.append.fragments;
    html += `<div class="mf-section-title">${ti('appendFrags', {n: frags.length})}</div>`;
    html += '<div class="table-wrap mf-table"><table><thead><tr>' +
      '<th>#</th><th>physical_rows</th><th>' + t('colDataFiles') + '</th></tr></thead><tbody>';
    frags.forEach((f, i) => {
      const files = f.files || [];
      const filesStr = files.map(x => {
        const p = (x.path||'').split('/').pop();
        return `<div class="mono" style="font-size:11px">${esc(p)} <span style="color:var(--muted)">${x.file_size_bytes??''} B · v${x.file_major_version??'?'}.${x.file_minor_version??'?'}</span></div>`;
      }).join('');
      html += `<tr>
        <td class="num">${i}</td>
        <td class="num">${f.physical_rows ?? '—'}</td>
        <td>${filesStr || '—'}</td>
      </tr>`;
    });
    html += '</tbody></table></div>';
  }
  // Delete -> deletion predicate / position
  if (d.delete) {
    const del = d.delete;
    html += `<div class="mf-section-title">${ti('deleteOp')}</div>`;
    html += '<div class="table-wrap mf-table"><table><thead><tr>' +
      '<th>predicate</th><th>fragment_ids</th><th>use_delete_file</th></tr></thead><tbody><tr>' +
      `<td class="mono">${esc(del.predicate ?? '—')}</td>` +
      `<td class="mono">${del.fragment_ids ? del.fragment_ids.join(', ') : '—'}</td>` +
      `<td>${del.use_delete_file !== undefined ? del.use_delete_file : '—'}</td>` +
      '</tr></tbody></table></div>';
  }
  // Overwrite -> new table structure
  if (d.overwrite) {
    const ov = d.overwrite;
    html += `<div class="mf-section-title">${ti('overwriteOp')}</div>`;
    html += '<div class="table-wrap mf-table"><table><thead><tr>' +
      '<th>schema_fields</th><th>fragments</th></tr></thead><tbody><tr>' +
      `<td class="num">${ov.schema && ov.schema.fields ? ov.schema.fields.length : '—'}</td>` +
      `<td class="num">${ov.fragments ? ov.fragments.length : '—'}</td>` +
      '</tr></tbody></table></div>';
  }
  return html;
}

// ---------- Data file (.lance) rendering ----------

function renderDatafile(data) {
  const dat = data.data;
  const f = dat.footer;
  const compLabel = c => c && c.length ? c.join(' + ') : '<span style="color:var(--muted)">' + t('noCompression') + '</span>';

  $('mfSummary').innerHTML = `
    <span class="stat-inline"><b>v${f.major_version}.${f.minor_version}</b></span>
    <span class="stat-inline">${t('col')}: <b>${f.columns}</b></span>
    <span class="stat-inline">global buffers: <b>${f.global_buffers}</b></span>
    <span class="stat-inline">file: <b>${fmtSize(f.file_size)}</b></span>
    <div style="margin-top:6px;font-size:11px;color:var(--muted)">
      cm0_off=${f.column0_offset} · cmo_off=${f.cmo_table_offset} · gbo_off=${f.gbo_table_offset}
    </div>
  `;

  // Index-file explanation (if it is an index file), then Footer info
  let html = indexExplainBlock(data.file, dat.schema);
  html += `<div class="mf-section-title">${ti('footerTitle')}</div>`;
  html += `<div class="table-wrap mf-table"><table><thead><tr>` +
    `<th>${t('colFieldOffset')}</th><th>${t('colOffValue')}</th></tr></thead><tbody>` +
    `<tr><td>Column 0 metadata offset</td><td class="num">${f.column0_offset}</td></tr>` +
    `<tr><td>CMO table offset</td><td class="num">${f.cmo_table_offset}</td></tr>` +
    `<tr><td>GBO table offset</td><td class="num">${f.gbo_table_offset}</td></tr>` +
    `<tr><td>Global buffers</td><td class="num">${f.global_buffers}</td></tr>` +
    `<tr><td>Columns</td><td class="num">${f.columns}</td></tr>` +
    `<tr><td>Version</td><td class="num">${f.major_version}.${f.minor_version}</td></tr>` +
    `<tr><td>Magic</td><td class="mono" style="color:var(--violet)">LANC</td></tr>` +
    `</tbody></table></div>`;

  // Column schema (decoded from the global-buffer FileDescriptor)
  if (dat.schema && dat.schema.length) {
    html += `<div class="mf-section-title">${ti('colSchemaTitle', {n: dat.schema.length})}</div>`;
    html += '<div class="table-wrap mf-table"><table><thead><tr>' +
      '<th>' + t('colName3') + '</th><th>' + t('colType') + '</th><th>parent</th><th>' + t('colExplain') + '</th></tr></thead><tbody>';
    dat.schema.forEach(c => {
      html += `<tr>
        <td class="mono" style="color:var(--accent);font-weight:600">${esc(c.name)}</td>
        <td class="mono" style="color:var(--violet)">${esc(c.logical_type||'')}</td>
        <td class="num">${c.parent_id ?? '—'}</td>
        <td style="color:var(--muted);font-size:12px">${indexFieldExplain(c.name)}</td>
      </tr>`;
    });
    html += '</tbody></table></div>';
  }

  // Per-column page overview table
  html += `<div class="mf-section-title">${ti('colPagesTitle', {n: dat.columns.length})}</div>`;
  html += '<div class="table-wrap mf-table"><table><thead><tr>' +
    '<th>' + t('col') + '</th><th>' + t('colPage') + '</th><th>' + t('colRows') + '</th><th>' + t('colBuffers') + '</th><th>' + t('colLayout') + '</th><th>' + t('colEncodingDetail') + '</th><th>' + t('colCompression') + '</th></tr></thead><tbody>';
  dat.columns.forEach(c => {
    c.pages.forEach(p => {
      html += `<tr>
        <td style="font-weight:600">col${c.index}</td>
        <td class="num">${p.index}</td>
        <td class="num">${p.length}</td>
        <td class="num">${p.num_buffers}</td>
        <td><span class="layout-badge">${esc(p.layout)}</span></td>
        <td class="mono" style="font-size:11px;color:var(--muted)">${esc(p.encoding||'')}</td>
        <td>${compLabel(p.compression)}</td>
      </tr>`;
    });
  });
  html += '</tbody></table></div>';

  // Global buffers
  if (dat.global_buffers && dat.global_buffers.length) {
    html += `<div class="mf-section-title">${ti('globalBuffers', {n: dat.global_buffers.length})}</div>`;
    html += '<div class="table-wrap mf-table"><table><thead><tr>' +
      '<th>#</th><th>offset</th><th>size</th></tr></thead><tbody>';
    dat.global_buffers.forEach(g => {
      html += `<tr><td class="num">${g.index}</td><td class="num">${g.offset}</td><td class="num">${fmtSize(g.size)}</td></tr>`;
    });
    html += '</tbody></table></div>';
  }

  $('mfBody').innerHTML =
    `<div id="mfTables">${html}</div>` +
    '<div class="mf-section-title">' + t('fullJson') + '</div>' +
    '<div class="json-tree" id="jsonTree"></div>';
  renderJsonTree(dat, $('jsonTree'));
}

// ---------- Manifest structured tables ----------

function renderManifestTables(full) {
  const d = full || {};
  let html = '';

  // Field table
  const fields = d.fields || [];
  html += `<div class="mf-section-title">${ti('schemaFieldsTitle', {n: fields.length})}</div>`;
  html += '<div class="table-wrap mf-table"><table><thead><tr>' +
    '<th>' + t('colId') + '</th><th>' + t('colName3') + '</th><th>' + t('colParentId') + '</th><th>' + t('colLogicalType') + '</th><th>' + t('colEncoding') + '</th><th>' + t('colNullable') + '</th></tr></thead><tbody>';
  fields.forEach((f, i) => {
    html += `<tr>
      <td class="num">${f.id ?? i}</td>
      <td style="font-weight:600">${esc(f.name||'')}</td>
      <td class="num">${f.parent_id ?? '—'}</td>
      <td class="mono" style="color:var(--violet)">${esc(f.logical_type||'')}</td>
      <td class="mono" style="color:var(--amber)">${esc(f.encoding||'')}</td>
      <td class="${f.nullable ? 'nullable-yes' : 'nullable-no'}">${f.nullable ? icon('check', 13) : icon('x', 13)}</td>
    </tr>`;
  });
  html += '</tbody></table></div>';

  // Fragment table
  const frags = d.fragments || [];
  html += `<div class="mf-section-title">${ti('fragsTitle', {n: frags.length})}</div>`;
  html += '<div class="table-wrap mf-table"><table><thead><tr>' +
    '<th>#</th><th>id</th><th>physical_rows</th><th>' + t('colDataFiles') + '</th><th>' + t('colDeletionFile') + '</th></tr></thead><tbody>';
  frags.forEach((f, i) => {
    const files = f.files || [];
    const filesStr = files.map(x => {
      const p = (x.path||'').split('/').pop();
      return `<span class="mono" style="font-size:11px">${esc(p)}</span>`;
    }).join('<br>');
    const del = f.deletion_file;
    const delStr = del
      ? `<span class="del-badge">${t('tombstoneDel', {n: del.num_deleted_rows ?? '?'})}</span> <span class="mono" style="font-size:10px;color:var(--muted)">id=${del.id??'—'}</span>`
      : '<span style="color:var(--muted)">' + t('noTombstone') + '</span>';
    html += `<tr>
      <td class="num">${i}</td>
      <td class="num">${f.id ?? 0}</td>
      <td class="num">${f.physical_rows ?? '—'}</td>
      <td>${filesStr || '—'}</td>
      <td>${delStr}</td>
    </tr>`;
  });
  html += '</tbody></table></div>';

  // Index table (if index_section exists)
  const idxSection = d.index_section;
  if (idxSection && (idxSection.indices || idxSection.indices_map)) {
    const indices = idxSection.indices || [];
    html += `<div class="mf-section-title">${ti('indicesTitle', {n: indices.length})}</div>`;
    html += '<div class="table-wrap mf-table"><table><thead><tr>' +
      '<th>name</th><th>type</th><th>dataset_version</th></tr></thead><tbody>';
    indices.forEach((idx, i) => {
      html += `<tr>
        <td style="font-weight:600">${esc(idx.name||('#'+i))}</td>
        <td class="mono" style="color:var(--violet)">${esc(idx.index_type||'')}</td>
        <td class="num">${idx.dataset_version ?? '—'}</td>
      </tr>`;
    });
    html += '</tbody></table></div>';
  }

  return html;
}

// A collection larger than this is rendered in chunks on demand. A manifest can list thousands of
// fragments; building every node eagerly (even collapsed) made the viewer the slow part of the page.
const JSON_CHUNK = 200;

function renderJsonTree(obj, container) {
  container.innerHTML = '';

  // Builds the next chunk of a collection's children, leaving a "show more" control behind while
  // items remain. Nested collections build theirs lazily the first time they are expanded.
  function chunkBuilder(keys, val, depth, children) {
    let built = 0;
    return function buildChunk() {
      const end = Math.min(built + JSON_CHUNK, keys.length);
      for (let i = built; i < end; i++) buildNode(keys[i], val[keys[i]], depth, children);
      built = end;
      if (built >= keys.length) return;
      const more = document.createElement('div');
      more.className = 'json-more';
      const btn = document.createElement('button');
      btn.className = 'btn-mini';
      btn.textContent = t('jsonShowMore', {n: Math.min(JSON_CHUNK, keys.length - built), total: keys.length});
      btn.addEventListener('click', () => { more.remove(); buildChunk(); });
      more.appendChild(btn);
      children.appendChild(more);
    };
  }

  function buildNode(key, val, depth, parent) {
    const target = parent || container;
    const row = document.createElement('div');
    row.className = 'row';
    const isObj = val && typeof val === 'object' && !Array.isArray(val);
    const isArr = Array.isArray(val);
    const isColl = isObj || isArr;
    const isEmptyColl = isColl && Object.keys(val).length === 0;
    const keyHtml = key != null ? `<span class="json-key">"${esc(key)}"</span>: ` : '';

    if (isColl && !isEmptyColl) {
      const toggle = document.createElement('span');
      toggle.className = 'json-toggle';
      toggle.innerHTML = icon('chevron-right', 12);
      row.innerHTML = keyHtml + `<span style="color:var(--muted)">${isArr ? 'Array' : 'Object'} <span class="json-num">${isArr ? val.length : Object.keys(val).length}</span></span>`;
      row.prepend(toggle);
      const children = document.createElement('div');
      children.className = 'json-children';
      children.style.display = 'none';
      const keys = Object.keys(val);
      const buildChunk = chunkBuilder(keys, val, depth + 1, children);
      let builtOnce = false;
      const expand = () => {
        if (builtOnce) return;
        builtOnce = true;
        buildChunk();
      };
      toggle.addEventListener('click', () => {
        const open = children.style.display !== 'none';
        if (!open) expand();
        children.style.display = open ? 'none' : 'block';
        toggle.innerHTML = open ? icon('chevron-right', 12) : icon('chevron-down', 12);
      });
      target.appendChild(row);
      target.appendChild(children);
      if (depth === 0) {
        expand();
        children.style.display = 'block';
        toggle.innerHTML = icon('chevron-down', 12);
      }
    } else if (isArr && val.length === 0) {
      row.innerHTML = keyHtml + '<span style="color:var(--muted)">[]</span>';
      target.appendChild(row);
    } else if (isObj && Object.keys(val).length === 0) {
      row.innerHTML = keyHtml + '<span style="color:var(--muted)">{}</span>';
      target.appendChild(row);
    } else {
      let valHtml;
      if (typeof val === 'string') valHtml = `<span class="json-str">"${esc(val)}"</span>`;
      else if (typeof val === 'number') valHtml = `<span class="json-num">${val}</span>`;
      else if (typeof val === 'boolean') valHtml = `<span class="json-bool">${val}</span>`;
      else if (val === null) valHtml = '<span class="json-null">null</span>';
      else if (isArr) valHtml = `<span style="color:var(--muted)">[...]</span>`;
      else valHtml = `<span style="color:var(--muted)">{...}</span>`;
      row.innerHTML = keyHtml + valHtml;
      target.appendChild(row);
    }
  }
  buildNode(null, obj, 0);
}

// Single escaping helper for the whole frontend: delegates to escHtml so the rules (including the
// single quote, which matters inside inline handlers and single-quoted attributes) live in one place.
function esc(s) {
  return escHtml(s);
}
