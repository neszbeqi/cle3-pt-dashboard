// CLE3 PT Dashboard — app.js

const S = {
  associates: [], summary: {}, floors: [],
  actions: [], barriers: [],
  notifications: [], unreadCount: 0,
  shift: 'night', floor: 'all',
  activeTab: 'floor',
  selectedBadge: null,
  refreshTimer: null,
  fetchTimer: null,
};

// ── Helpers ───────────────────────────────────────────────────────────────────
const esc  = s => s == null ? '' : String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
const fmt  = (n,d=1) => n == null ? '–' : Number(n).toFixed(d) + '%';
const fmtH = h => h == null ? '–' : Number(h).toFixed(2) + 'h';
function ptCls(pt) {
  if (pt == null) return 'unknown';
  if (pt >= 88)   return 'good';
  if (pt >= 84)   return 'watch';
  return 'below';
}
function show(id) { const e = document.getElementById(id); if(e) e.classList.remove('hidden'); }
function hide(id) { const e = document.getElementById(id); if(e) e.classList.add('hidden'); }
function setStatus(msg) { const e = document.getElementById('status-msg'); if(e) e.textContent = msg; }

async function api(path, opts={}) {
  try {
    const r = await fetch(path, opts);
    if (!r.ok) throw new Error(r.status);
    return await r.json();
  } catch(e) { console.error('API', path, e); return null; }
}
const apiPost = (path, body) => api(path, {
  method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)
});

// ── Load data ─────────────────────────────────────────────────────────────────
async function loadData() {
  setStatus('Refreshing…');
  const r = await api(`/api/data?shift=${S.shift}&floor=${S.floor}`);
  if (!r) { setStatus('Error loading data'); return; }
  if (!r.ok) {
    const msg = r.msg || 'Fetching data - check back shortly.';
    setStatus(msg);
    const loadEl = document.getElementById('floor-loading');
    if (loadEl) loadEl.textContent = r.error
      ? 'FCLM error: ' + r.error + '  (retrying...)'
      : 'Loading FCLM data... (a browser window may open for login)';
    S.associates = [];
    show('floor-loading');
    hide('floor-table-wrap');
    // Retry every 10s until data arrives
    if (!S.fetchTimer) {
      S.fetchTimer = setInterval(() => { if (S.associates.length === 0) loadData(); }, 10000);
    }
  } else {
    // Data loaded - clear fast-retry timer
    if (S.fetchTimer) { clearInterval(S.fetchTimer); S.fetchTimer = null; }
    S.associates = r.associates || [];
    S.summary    = r.summary || {};
    S.floors     = r.floors || [];
    hide('floor-loading');
    show('floor-table-wrap');
    setStatus('Updated ' + new Date(r.updated).toLocaleTimeString() + ' - ' + S.associates.length + ' AAs - ' + r.shift + ' shift');
  }
  // Load actions for this shift
  const acts = await api(`/api/actions?shift=${S.shift}`);
  S.actions = acts || [];
  renderAll();
}

// ── SSE ───────────────────────────────────────────────────────────────────────
function initSSE() {
  const es = new EventSource('/api/events');
  es.onmessage = e => {
    try {
      const d = JSON.parse(e.data);
      if (d.type === 'flags') {
        const p = d.payload;
        const msg = `⚑ ${p.count} flagged: ${(p.below||[]).slice(0,3).join(', ')}`;
        addNotif(msg);
        showToast(msg, 'warn');
      }
    } catch {}
  };
  es.onerror = () => setTimeout(initSSE, 5000);
}

function addNotif(msg) {
  S.notifications.unshift({ msg, ts: new Date().toISOString() });
  S.unreadCount++;
  const badge = document.getElementById('notif-badge');
  if (badge) { badge.textContent = S.unreadCount; badge.classList.remove('hidden'); }
}

let _toastWrap = null;
function showToast(msg, level='info') {
  if (!_toastWrap) {
    _toastWrap = document.createElement('div');
    _toastWrap.style.cssText = 'position:fixed;bottom:20px;right:20px;z-index:999;display:flex;flex-direction:column;gap:8px';
    document.body.appendChild(_toastWrap);
  }
  const colors = {
    warn:    ['#7c2d12','#fed7aa','#9a3412'],
    success: ['#14532d','#bbf7d0','#166534'],
    info:    ['#1e2235','#e2e8f0','#252a40'],
  };
  const [bg,fg,bd] = colors[level] || colors.info;
  const d = document.createElement('div');
  d.style.cssText = `padding:10px 16px;border-radius:8px;font-size:13px;font-weight:600;
    opacity:0;transition:opacity .3s;background:${bg};color:${fg};border:1px solid ${bd}`;
  d.textContent = msg;
  _toastWrap.appendChild(d);
  requestAnimationFrame(() => d.style.opacity = '1');
  setTimeout(() => { d.style.opacity='0'; setTimeout(()=>d.remove(),350); }, 3500);
}

// ── Summary bar ───────────────────────────────────────────────────────────────
function renderSummary() {
  const aas   = S.associates;
  const valid = aas.filter(a => a.pt_pct != null);
  const avg   = valid.length ? valid.reduce((s,a)=>s+a.pt_pct,0)/valid.length : null;
  const below = aas.filter(a => a.status === 'below').length;
  const watch = aas.filter(a => a.status === 'watch').length;
  const good  = aas.filter(a => a.status === 'good').length;
  const set   = (id,v) => { const e=document.getElementById(id); if(e) e.textContent=v; };
  set('s-avg',   avg != null ? avg.toFixed(1)+'%' : '–');
  set('s-below', below);
  set('s-watch', watch);
  set('s-good',  good);
  set('s-count', aas.length);
}

// ── Floor view ────────────────────────────────────────────────────────────────
function renderFloor() {
  const tbody = document.getElementById('aa-tbody');
  if (!tbody) return;
  // Sort by station (numeric sort of leading digits), then name
  const sorted = [...S.associates].sort((a,b) => {
    const sa = a.station || '', sb = b.station || '';
    if (sa && sb) return sa.localeCompare(sb, undefined, {numeric:true});
    if (sa) return -1;
    if (sb) return 1;
    return (a.name||'').localeCompare(b.name||'');
  });
  if (!sorted.length) {
    tbody.innerHTML = `<tr><td colspan="10" class="empty-msg">No associates on ${S.floor === 'all' ? 'any floor' : 'Floor '+S.floor} for this shift.</td></tr>`;
    return;
  }
  tbody.innerHTML = sorted.map(a => aaRow(a)).join('');
}

function aaRow(a) {
  const pt    = a.pt_pct;
  const cls   = ptCls(pt);
  const bar   = pt != null ? Math.min(100, Math.max(0,pt)) : 0;
  const proj  = a.projection;
  const idleM = a.inferred != null ? Math.round(a.inferred * 60) : null;
  const hasAct= S.actions.some(x => x.badge === a.badge);
  const rowCls= a.status === 'below' ? 'row-below' : a.status === 'watch' ? 'row-watch' : '';
  return `<tr class="${rowCls}" onclick="openDrawer('${esc(a.badge)}')">
    <td><span class="text-muted" style="font-size:12px">${esc(a.station||'–')}</span></td>
    <td><div class="aa-name">${esc(a.name)}</div></td>
    <td><a class="login-link" href="/timecard/${esc(a.badge)}?shift=${S.shift}" target="_blank" onclick="event.stopPropagation()">${esc(a.badge)}</a></td>
    <td><span style="font-size:12px;color:var(--muted2)">${esc(a.manager||'–')}</span></td>
    <td><span class="pt-num ${cls}">${fmt(pt)}</span></td>
    <td><div class="pt-bar-wrap">
      <div class="pt-bar"><div class="pt-bar-fill ${cls}" style="width:${bar}%"></div></div>
      <span class="pt-trend">${proj != null ? 'Proj: '+fmt(proj) : ''}</span>
    </div></td>
    <td><span style="font-size:12px;color:${idleM>30?'var(--red)':idleM>15?'var(--amber)':'var(--muted2)'}">${idleM != null ? idleM+'m' : '–'}</span></td>
    <td><span class="pt-num ${ptCls(proj)}" style="font-size:13px">${fmt(proj)}</span></td>
    <td><span class="status-chip chip-${cls}">${cls === 'good' ? '✓ On Target' : cls === 'watch' ? '⚠ Watch' : cls === 'below' ? '✗ Below' : '–'}</span></td>
    <td onclick="event.stopPropagation()">
      ${hasAct
        ? `<span class="status-chip chip-watch" style="font-size:9px">Action taken</span>`
        : `<button class="act-btn primary" onclick="openActionModal('${esc(a.badge)}','${esc(a.name)}','${esc(a.manager||'')}')">+ Action</button>`}
    </td>
  </tr>`;
}

// ── Flagged tab ───────────────────────────────────────────────────────────────
function renderFlagged() {
  const tbody = document.getElementById('flagged-tbody');
  if (!tbody) return;
  // Flagged = below OR watch, and no action taken yet this shift
  const flagged = S.associates
    .filter(a => a.flagged && !S.actions.some(x => x.badge === a.badge))
    .sort((a,b) => (a.pt_pct||100) - (b.pt_pct||100));
  if (!flagged.length) {
    tbody.innerHTML = '<tr><td colspan="8" class="empty-msg">No flagged associates — great shift!</td></tr>';
    return;
  }
  tbody.innerHTML = flagged.map(a => `
    <tr class="${a.status==='below'?'row-below':'row-watch'}" onclick="openDrawer('${esc(a.badge)}')">
      <td>${esc(a.station||'–')}</td>
      <td><div class="aa-name">${esc(a.name)}</div></td>
      <td><a class="login-link" href="/timecard/${esc(a.badge)}?shift=${S.shift}" target="_blank" onclick="event.stopPropagation()">${esc(a.badge)}</a></td>
      <td>${esc(a.manager||'–')}</td>
      <td><span class="pt-num ${ptCls(a.pt_pct)}">${fmt(a.pt_pct)}</span></td>
      <td><span class="pt-num ${ptCls(a.projection)}" style="font-size:13px">${fmt(a.projection)}</span></td>
      <td>${a.consecutive_low >= 2 ? `<span class="status-chip chip-below">${a.consecutive_low} shifts</span>` : '–'}</td>
      <td onclick="event.stopPropagation()">
        <button class="act-btn primary" onclick="openActionModal('${esc(a.badge)}','${esc(a.name)}','${esc(a.manager||'')}')">+ Action</button>
      </td>
    </tr>`).join('');
}

// ── Actions tab ───────────────────────────────────────────────────────────────
function renderActions() {
  const tbody = document.getElementById('actions-tbody');
  if (!tbody) return;
  if (!S.actions.length) {
    tbody.innerHTML = '<tr><td colspan="8" class="empty-msg">No actions logged this shift yet.</td></tr>';
    return;
  }
  tbody.innerHTML = S.actions.map(act => {
    const aa  = S.associates.find(a => a.badge === act.badge) || {};
    const pt  = aa.pt_pct;
    const recovered = pt != null && pt >= 88;
    return `<tr onclick="openDrawer('${esc(act.badge)}')">
      <td><div class="aa-name">${esc(act.name||aa.name||act.badge)}</div></td>
      <td><a class="login-link" href="/timecard/${esc(act.badge)}?shift=${S.shift}" target="_blank" onclick="event.stopPropagation()">${esc(act.badge)}</a></td>
      <td><span class="pt-num ${ptCls(pt)}">${fmt(pt)}</span></td>
      <td><span class="pt-num ${ptCls(aa.projection)}" style="font-size:13px">${fmt(aa.projection)}</span></td>
      <td><span class="status-chip chip-watch">${esc(act.action_type)}</span></td>
      <td style="font-size:11px;color:var(--muted2)">${esc(act.am_name||'–')}</td>
      <td style="font-size:11px;color:var(--muted)">${act.ts ? new Date(act.ts).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}) : '–'}</td>
      <td>${recovered
        ? '<span class="status-chip chip-good">✓ Recovered</span>'
        : '<span class="status-chip chip-below">Still low</span>'}</td>
    </tr>`;
  }).join('');
}

// ── Patterns tab ──────────────────────────────────────────────────────────────
async function renderPatterns() {
  // Consecutive low shifts
  const patternEl = document.getElementById('patterns-list');
  if (patternEl) {
    const repeat = S.associates
      .filter(a => a.consecutive_low >= 2)
      .sort((a,b) => b.consecutive_low - a.consecutive_low);
    patternEl.innerHTML = repeat.length === 0
      ? '<div class="empty-msg">No repeat patterns detected.</div>'
      : repeat.map(a => `
        <div class="pattern-row" onclick="openDrawer('${esc(a.badge)}')">
          <div class="pattern-name">${esc(a.name)}</div>
          <div class="pattern-sub">${a.consecutive_low} consecutive shifts below 88% · ${esc(a.manager||'')}</div>
        </div>`).join('');
  }
  // Barriers
  const barrierEl = document.getElementById('barrier-list');
  if (barrierEl) {
    const r = await api('/api/barriers');
    const barriers = Array.isArray(r) ? r : [];
    barrierEl.innerHTML = barriers.length === 0
      ? '<div class="empty-msg">No barriers logged recently.</div>'
      : barriers.map(b => `
        <div class="barrier-row">
          <div class="barrier-type">${esc(b.barrier)}</div>
          <div class="barrier-sub">${b.cnt ? b.cnt+' occurrences' : ''} ${esc(b.names||b.note||'')}</div>
        </div>`).join('');
  }
}

// ── Drawer ────────────────────────────────────────────────────────────────────
async function openDrawer(badge) {
  S.selectedBadge = badge;
  const a = S.associates.find(x => x.badge === badge) || {};
  document.getElementById('d-name').textContent = a.name || badge;
  document.getElementById('d-sub').textContent  = `${a.badge||''} · ${a.station||'No station'} · ${a.manager||''}`;
  const overlay = document.getElementById('drawer-overlay');
  const drawer  = document.getElementById('drawer');
  if (overlay) overlay.classList.remove('hidden');
  if (drawer)  { drawer.classList.remove('hidden'); requestAnimationFrame(()=>drawer.classList.add('open')); }
  await renderDrawerBody(badge, a);
}
function closeDrawer() {
  const drawer  = document.getElementById('drawer');
  const overlay = document.getElementById('drawer-overlay');
  if (drawer)  { drawer.classList.remove('open'); setTimeout(()=>drawer.classList.add('hidden'),260); }
  if (overlay) overlay.classList.add('hidden');
  S.selectedBadge = null;
}

async function renderDrawerBody(badge, a) {
  const body = document.getElementById('drawer-body');
  if (!body) return;
  body.innerHTML = '<div class="loading-msg">Loading…</div>';

  const [histRes, barrRes] = await Promise.all([
    api(`/api/history/${encodeURIComponent(badge)}`),
    api(`/api/barriers?badge=${encodeURIComponent(badge)}`),
  ]);
  const history  = histRes || [];
  const barriers = Array.isArray(barrRes) ? barrRes : [];
  const actions  = S.actions.filter(x => x.badge === badge);
  const pt  = a.pt_pct;
  const proj= a.projection;

  let html = '';

  // Current PT + projection
  html += `<div class="d-section">
    <div class="d-sec-title">Current Shift</div>
    <div class="metric-row"><span class="metric-lbl">PT%</span><span class="metric-val pt-num ${ptCls(pt)}">${fmt(pt)}</span></div>
    <div class="metric-row"><span class="metric-lbl">Idle Time</span><span class="metric-val">${a.inferred!=null?Math.round(a.inferred*60)+'m':'–'}</span></div>
    <div class="metric-row"><span class="metric-lbl">Total Time</span><span class="metric-val">${fmtH(a.total)}</span></div>
    <div class="metric-row"><span class="metric-lbl">Projected EOD</span><span class="metric-val pt-num ${ptCls(proj)}">${fmt(proj)}</span></div>
    <div class="metric-row"><span class="metric-lbl">Station</span><span class="metric-val">${esc(a.station||'–')}</span></div>
    <div class="metric-row"><span class="metric-lbl">Floor</span><span class="metric-val">${a.floor||'–'}</span></div>
  </div>`;

  // Consecutive pattern
  if (a.consecutive_low >= 2) {
    html += `<div class="d-section" style="border-color:#7f1d1d">
      <div class="d-sec-title">Pattern Detected</div>
      <div style="color:var(--red);font-weight:600">${a.consecutive_low} consecutive shifts below 88%</div>
    </div>`;
  }

  // Recent shift history
  if (history.length) {
    html += `<div class="d-section"><div class="d-sec-title">Recent Shift History</div>
      ${history.map(h=>`<div class="metric-row">
        <span class="metric-lbl">${esc(h.date)} ${esc(h.shift)}</span>
        <span class="metric-val pt-num ${ptCls(h.pt_pct)}">${fmt(h.pt_pct)}</span>
      </div>`).join('')}
    </div>`;
  }

  // Actions taken
  if (actions.length) {
    html += `<div class="d-section"><div class="d-sec-title">Actions Taken This Shift</div>
      ${actions.map(act=>`<div class="metric-row">
        <span class="metric-lbl">${new Date(act.ts).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}</span>
        <span class="metric-val">${esc(act.action_type)}</span>
      </div>`).join('')}
    </div>`;
  }

  // Barriers
  if (barriers.length) {
    html += `<div class="d-section"><div class="d-sec-title">Barriers Logged</div>
      ${barriers.map(b=>`<div class="metric-row">
        <span class="metric-lbl">${esc(b.date)}</span>
        <span class="metric-val">${esc(b.barrier)}</span>
      </div>`).join('')}
    </div>`;
  }

  // Action buttons
  html += `<div class="action-row-btns">
    <a class="act-btn primary" href="/timecard/${esc(badge)}?shift=${S.shift}" target="_blank">Open Timecard</a>
    <button class="act-btn" onclick="openActionModal('${esc(badge)}','${esc(a.name||badge)}','${esc(a.manager||'')}'); closeDrawer()">+ Log Action</button>
    <button class="act-btn" onclick="openBarrierModal('${esc(badge)}','${esc(a.name||badge)}'); closeDrawer()">+ Log Barrier</button>
  </div>`;

  body.innerHTML = html;
}

// ── Modals ────────────────────────────────────────────────────────────────────
function openModal(title, bodyHTML) {
  document.getElementById('modal-title').textContent = title;
  document.getElementById('modal-body').innerHTML = bodyHTML;
  show('modal-overlay');
}
function closeModal() {
  hide('modal-overlay');
  document.getElementById('modal-body').innerHTML = '';
}

function openActionModal(badge, name, manager) {
  openModal(`Log Action — ${name}`, `
    <label>Action Type
      <select id="act-type" style="width:100%;margin-top:4px;padding:8px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:6px">
        <option value="Cycle Time Audit">Cycle Time Audit</option>
        <option value="Stow Pro SWACE Audit">Stow Pro SWACE Audit</option>
        <option value="Verbal Coaching">Verbal Coaching</option>
        <option value="Document Coaching">Document Coaching</option>
        <option value="First Warning">First Warning</option>
        <option value="STU">STU</option>
      </select>
    </label>
    <label style="margin-top:12px;display:block">Your Name (AM)
      <input id="act-am" type="text" placeholder="Your name" style="width:100%;margin-top:4px;padding:8px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:6px">
    </label>
    <label style="margin-top:12px;display:block">Note (optional)
      <textarea id="act-note" rows="3" placeholder="What did you observe? What did you discuss?" style="width:100%;margin-top:4px;padding:8px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:6px;resize:vertical"></textarea>
    </label>
    <div class="modal-footer" style="padding:12px 0 0">
      <button class="act-btn" onclick="closeModal()">Cancel</button>
      <button class="act-btn primary" onclick="submitAction('${esc(badge)}','${esc(name)}','${esc(manager)}')">Save</button>
    </div>`);
}
async function submitAction(badge, name, manager) {
  const type  = document.getElementById('act-type')?.value;
  const am    = document.getElementById('act-am')?.value || '';
  const note  = document.getElementById('act-note')?.value || '';
  const r = await apiPost('/api/action', {
    badge, name, manager, action_type: type, note, am_name: am,
    shift: S.shift,
  });
  if (r?.ok) {
    closeModal();
    showToast(`Action logged: ${type}`, 'success');
    loadData();
  } else {
    showToast('Failed to save action', 'warn');
  }
}

function openBarrierModal(badge, name) {
  openModal(`Log Barrier — ${name}`, `
    <label>Barrier Type
      <select id="bar-type" style="width:100%;margin-top:4px;padding:8px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:6px">
        <option>Equipment Issue</option>
        <option>System/Scan Issue</option>
        <option>Path/Bin Issue</option>
        <option>Staffing</option>
        <option>Training Gap</option>
        <option>Other</option>
      </select>
    </label>
    <label style="margin-top:12px;display:block">Note
      <textarea id="bar-note" rows="3" placeholder="Describe the barrier…" style="width:100%;margin-top:4px;padding:8px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:6px;resize:vertical"></textarea>
    </label>
    <div class="modal-footer" style="padding:12px 0 0">
      <button class="act-btn" onclick="closeModal()">Cancel</button>
      <button class="act-btn primary" onclick="submitBarrier('${esc(badge)}','${esc(name)}')">Save</button>
    </div>`);
}
async function submitBarrier(badge, name) {
  const barrier = document.getElementById('bar-type')?.value;
  const note    = document.getElementById('bar-note')?.value || '';
  const r = await apiPost('/api/barrier', { badge, name, barrier, note, shift: S.shift });
  if (r?.ok) {
    closeModal();
    showToast('Barrier logged', 'success');
    if (S.activeTab === 'patterns') renderPatterns();
  } else {
    showToast('Failed to save barrier', 'warn');
  }
}

// ── Tab switching ─────────────────────────────────────────────────────────────
function switchTab(tab) {
  S.activeTab = tab;
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  document.querySelectorAll('.tab-pane').forEach(p => {
    p.classList.toggle('hidden', p.id !== 'tab-' + tab);
  });
  if (tab === 'floor')    renderFloor();
  else if (tab === 'flagged')  renderFlagged();
  else if (tab === 'actions')  renderActions();
  else if (tab === 'patterns') renderPatterns();
}

// ── Render all ────────────────────────────────────────────────────────────────
function renderAll() {
  renderSummary();
  if (S.activeTab === 'floor')    renderFloor();
  else if (S.activeTab === 'flagged')  renderFlagged();
  else if (S.activeTab === 'actions')  renderActions();
  else if (S.activeTab === 'patterns') renderPatterns();
  // Update tab badges
  const below = S.associates.filter(a => a.flagged && !S.actions.some(x=>x.badge===a.badge)).length;
  const actTab = document.querySelector('[data-tab="flagged"]');
  if (actTab) actTab.textContent = `Flagged${below ? ' ('+below+')' : ''}`;
  const actionsTab = document.querySelector('[data-tab="actions"]');
  if (actionsTab) actionsTab.textContent = `Actions Taken${S.actions.length ? ' ('+S.actions.length+')' : ''}`;
}

// ── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Auto-detect shift
  const h = new Date().getHours();
  S.shift = (h >= 18 || h < 6) ? 'night' : 'day';
  document.querySelectorAll('.shift-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.shift === S.shift);
    b.addEventListener('click', () => {
      S.shift = b.dataset.shift;
      document.querySelectorAll('.shift-btn').forEach(x => x.classList.toggle('active', x.dataset.shift === S.shift));
      apiPost('/api/set-shift', { shift: S.shift });
      loadData();
    });
  });

  // Floor selector
  const floorSel = document.getElementById('floor-select');
  if (floorSel) floorSel.addEventListener('change', e => {
    S.floor = e.target.value;
    loadData();
  });

  // Tabs
  document.querySelectorAll('.tab-btn').forEach(b =>
    b.addEventListener('click', () => switchTab(b.dataset.tab))
  );

  // Refresh button
  document.getElementById('refresh-btn')?.addEventListener('click', loadData);

  // Notifications
  document.getElementById('notif-btn')?.addEventListener('click', () => {
    const panel = document.getElementById('notif-panel');
    if (!panel) return;
    if (!panel.classList.contains('hidden')) { panel.classList.add('hidden'); return; }
    const list = document.getElementById('notif-list');
    if (list) {
      list.innerHTML = S.notifications.length === 0
        ? '<div class="empty-msg" style="padding:12px">No alerts</div>'
        : S.notifications.slice(0,20).map(n =>
            `<div class="notif-item"><div class="ni-msg">${esc(n.msg)}</div><div class="ni-time">${new Date(n.ts).toLocaleTimeString()}</div></div>`
          ).join('');
    }
    S.unreadCount = 0;
    const badge = document.getElementById('notif-badge');
    if (badge) badge.classList.add('hidden');
    panel.classList.remove('hidden');
  });
  document.getElementById('clear-notifs')?.addEventListener('click', () => {
    S.notifications = []; S.unreadCount = 0;
    document.getElementById('notif-badge')?.classList.add('hidden');
    document.getElementById('notif-list').innerHTML = '<div class="empty-msg" style="padding:12px">No alerts</div>';
  });

  // Drawer / modal close
  document.getElementById('drawer-close')?.addEventListener('click', closeDrawer);
  document.getElementById('drawer-overlay')?.addEventListener('click', closeDrawer);
  document.getElementById('modal-close')?.addEventListener('click', closeModal);
  document.getElementById('modal-overlay')?.addEventListener('click', e => {
    if (e.target === document.getElementById('modal-overlay')) closeModal();
  });

  // Barrier floor-level button
  document.getElementById('log-barrier-floor-btn')?.addEventListener('click', () =>
    openBarrierModal('', 'Floor-wide')
  );

  // Keyboard ESC
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') { closeModal(); closeDrawer(); }
  });

  // Auto-refresh every 3 min
  S.refreshTimer = setInterval(loadData, 3 * 60 * 1000);

  initSSE();
  loadData();
});
