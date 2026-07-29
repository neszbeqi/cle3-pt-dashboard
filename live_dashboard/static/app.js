// CLE3 Live Dashboard — app.js  (rewritten to match server.py + index.html)

// ── State ─────────────────────────────────────────────────────────────────────
const S = {
  associates: [], wouldBe: null, expiring: [],
  barrierPatterns: [], notifications: [], unreadCount: 0,
  eti: null, andons: [],
  currentShift: 'night', activeTab: 'floor',
  currentView: 'all', amFilter: '',
  selectedLogin: null, refreshTimer: null,
};

// ── Helpers ───────────────────────────────────────────────────────────────────
const esc = s => s == null ? '' : String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
const fmt  = (n,d=1) => n == null ? '–' : Number(n).toFixed(d) + '%';
const fmtD = n => n == null ? '' : (n >= 0 ? '+' : '') + Number(n).toFixed(1) + '%';
function ptCls(pt) {
  if (pt == null) return '';
  return pt >= 84 ? 'good' : pt >= 80 ? 'warn' : 'bad';
}
function severityCls(s) {
  return s === 'critical' ? 'critical' : s === 'high' ? 'high' : 'medium';
}
function setStatus(msg) {
  const el = document.getElementById('status-msg');
  if (el) el.textContent = msg;
}
function show(id)  { document.getElementById(id)?.classList.remove('hidden'); }
function hide(id)  { document.getElementById(id)?.classList.add('hidden'); }
function tog(id,v) { document.getElementById(id)?.classList.toggle('hidden', !v); }

// ── API ───────────────────────────────────────────────────────────────────────
async function api(path, opts={}) {
  try {
    const r = await fetch(path, opts);
    if (!r.ok) throw new Error(r.status);
    return await r.json();
  } catch(e) { console.error('API', path, e); return null; }
}
const apiPost = (path, body) => api(path, {
  method: 'POST',
  headers: {'Content-Type':'application/json'},
  body: JSON.stringify(body),
});

// ── Load data ─────────────────────────────────────────────────────────────────
async function loadAll() {
  setStatus('Refreshing…');
  const r = await api(`/api/associates?shift=${S.currentShift}`);
  if (r) {
    if (r.ok) {
      S.associates = r.data || [];
      S.wouldBe    = r.would_be;
      S.expiring   = r.expiring || [];
      hide('floor-loading');
    } else {
      S.associates = [];
      show('floor-loading');
      document.getElementById('floor-loading').textContent = r.message || 'Loading…';
    }
  }
  // Fetch barrier patterns in background
  api('/api/barriers/all').then(d => { if (d) S.barrierPatterns = d; });
  S.lastRefresh = new Date();
  setStatus('Updated: ' + S.lastRefresh.toLocaleTimeString());
  renderAll();
}

// ── SSE ───────────────────────────────────────────────────────────────────────
function initSSE() {
  const es = new EventSource('/api/events');
  es.onmessage = e => {
    try {
      const d = JSON.parse(e.data);
      if (d.type === 'flag') {
        const msg = `⚑ ${d.payload?.name || d.payload?.login}: ${d.payload?.flag}`;
        S.notifications.unshift({ msg, ts: new Date().toISOString(), level: 'crit' });
        S.unreadCount++;
        updateBell();
        showToast(msg, 'warn');
      } else if (d.type === 'refresh') {
        loadAll();
      }
    } catch {}
  };
  es.onerror = () => setTimeout(initSSE, 5000);
}

// ── Bell ──────────────────────────────────────────────────────────────────────
function updateBell() {
  const badge = document.getElementById('notif-badge');
  if (!badge) return;
  if (S.unreadCount > 0) {
    badge.textContent = S.unreadCount;
    badge.classList.remove('hidden');
  } else {
    badge.classList.add('hidden');
  }
}
function toggleNotifPanel() {
  const panel = document.getElementById('notif-panel');
  if (!panel) return;
  if (!panel.classList.contains('hidden')) { panel.classList.add('hidden'); return; }
  const list = document.getElementById('notif-list');
  if (list) {
    list.innerHTML = S.notifications.length === 0
      ? '<div class="empty-msg">No alerts</div>'
      : S.notifications.slice(0,30).map(n =>
          `<div class="notif-item"><div class="ni-flag">${esc(n.msg)}</div><div class="ni-time">${new Date(n.ts).toLocaleTimeString()}</div></div>`
        ).join('');
  }
  S.unreadCount = 0;
  updateBell();
  panel.classList.remove('hidden');
}

// ── Toast ─────────────────────────────────────────────────────────────────────
let _toastWrap = null;
function showToast(msg, level='info') {
  if (!_toastWrap) {
    _toastWrap = document.createElement('div');
    _toastWrap.style.cssText = 'position:fixed;bottom:20px;right:20px;z-index:999;display:flex;flex-direction:column;gap:8px';
    document.body.appendChild(_toastWrap);
  }
  const d = document.createElement('div');
  d.style.cssText = `padding:10px 16px;border-radius:8px;font-size:13px;font-weight:600;opacity:0;transition:opacity .3s;
    background:${level==='warn'?'#7c2d12':level==='success'?'#14532d':'#1e2130'};
    color:${level==='warn'?'#fed7aa':level==='success'?'#bbf7d0':'#e2e8f0'};
    border:1px solid ${level==='warn'?'#9a3412':level==='success'?'#166534':'#2d3148'}`;
  d.textContent = msg;
  _toastWrap.appendChild(d);
  requestAnimationFrame(() => { d.style.opacity = '1'; });
  setTimeout(() => { d.style.opacity = '0'; setTimeout(() => d.remove(), 350); }, 3500);
}

// ── Expiry banner ─────────────────────────────────────────────────────────────
function renderExpiryBanner() {
  const el = document.getElementById('expiry-banner');
  if (!el) return;
  if (!S.expiring.length) { el.classList.add('hidden'); return; }
  el.classList.remove('hidden');
  el.innerHTML = `<strong>⚠ ${S.expiring.length} feedback(s) expiring within 7 days:</strong>&nbsp;` +
    S.expiring.map(f => `${esc(f.name)} (${esc(f.label)} — ${f.days_remaining}d)`).join(', ') +
    `&nbsp;<button onclick="document.getElementById('expiry-banner').classList.add('hidden')" style="margin-left:auto;background:none;border:none;color:#fed7aa;cursor:pointer;font-size:14px">✕</button>`;
}

// ── Summary cards ─────────────────────────────────────────────────────────────
function renderSummary() {
  const valid = S.associates.filter(a => a.pt != null);
  const avg   = valid.length ? valid.reduce((s,a) => s+a.pt, 0)/valid.length : null;
  const flagged = S.associates.filter(a => a.flags?.length).length;
  const el = id => document.getElementById(id);
  if (el('s-avg'))     el('s-avg').textContent     = avg != null ? avg.toFixed(1)+'%' : '–';
  if (el('s-flagged')) el('s-flagged').textContent = flagged;
  if (el('s-count'))   el('s-count').textContent   = S.associates.length;
  if (el('s-expiring'))el('s-expiring').textContent= S.expiring.length;
  if (el('s-wouldbe')) {
    const wb = S.wouldBe;
    el('s-wouldbe').textContent = wb ? wb.would_be.toFixed(1)+'%' : '–';
  }
}

// ── AM filter dropdown ────────────────────────────────────────────────────────
function populateAMFilter() {
  const sel = document.getElementById('am-filter');
  if (!sel) return;
  const ams = [...new Set(S.associates.map(a => a.manager).filter(Boolean))].sort();
  const cur = sel.value;
  sel.innerHTML = '<option value="">All Managers</option>' +
    ams.map(m => `<option value="${esc(m)}" ${m===cur?'selected':''}>${esc(m)}</option>`).join('');
}

// ── Floor view ────────────────────────────────────────────────────────────────
function renderFloor() {
  const container = document.getElementById('am-cards');
  if (!container) return;

  let rows = [...S.associates];
  // Apply view filter
  if (S.currentView === 'flagged') rows = rows.filter(a => a.flags?.length);
  else if (S.currentView === 'newhires') rows = rows.filter(a => a.new_hire);
  // Apply AM filter
  if (S.amFilter) rows = rows.filter(a => a.manager === S.amFilter);

  // Group by manager
  const map = {};
  for (const a of rows) {
    const m = a.manager || 'Unknown';
    if (!map[m]) map[m] = [];
    map[m].push(a);
  }
  // Sort AMs by avg PT ascending (worst first)
  const groups = Object.entries(map).map(([name, aas]) => {
    const v = aas.filter(a => a.pt != null);
    const avg = v.length ? v.reduce((s,a) => s+a.pt, 0)/v.length : null;
    return {name, aas, avg};
  }).sort((a,b) => (a.avg ?? 100) - (b.avg ?? 100));

  if (!groups.length) {
    container.innerHTML = '<div class="empty-msg">No associates match current filter.</div>';
    return;
  }
  container.innerHTML = groups.map((g,gi) => renderAMCard(g, gi)).join('');
}

function renderAMCard({name, aas, avg}, gi) {
  const cls = ptCls(avg);
  const flagCount = aas.filter(a => a.flags?.length).length;
  // Sort AAs: flagged first, then worst PT
  const sorted = [...aas].sort((a,b) => {
    const fa = a.flags?.length || 0, fb = b.flags?.length || 0;
    if (fa !== fb) return fb - fa;
    return (a.pt ?? 100) - (b.pt ?? 100);
  });
  return `
  <div class="am-card" id="amc-${gi}">
    <div class="am-header" onclick="toggleAMCard(${gi})">
      <span class="am-name">${esc(name)}</span>
      <div class="am-stats">
        <span>${sorted.length} AAs</span>
        ${flagCount ? `<span class="text-red">${flagCount} flagged</span>` : ''}
      </div>
      <span class="am-pt ${cls}">${avg != null ? avg.toFixed(1)+'%' : '–'}</span>
      <span class="am-chevron">▼</span>
    </div>
    <div class="am-body" id="amb-${gi}">
      ${sorted.map((a,i) => renderAARow(a, i+1)).join('')}
    </div>
  </div>`;
}
function toggleAMCard(gi) {
  const card = document.getElementById('amc-'+gi);
  const body = document.getElementById('amb-'+gi);
  if (!card || !body) return;
  card.classList.toggle('collapsed');
  body.style.display = card.classList.contains('collapsed') ? 'none' : '';
}

function renderAARow(a, rank) {
  const pt      = a.pt;
  const cls     = ptCls(pt);
  const barPct  = pt != null ? Math.min(100, Math.max(0, pt)) : 0;
  const flags   = a.flags || [];
  const proj    = a.projection;
  const trend   = proj ? (proj.trending - (pt||0)) : null;
  const trendTxt= trend != null ? (trend > 0.5 ? '▲' : trend < -0.5 ? '▼' : '►') : '';
  const trendCls= trend != null ? (trend > 0.5 ? 'trend-up' : trend < -0.5 ? 'trend-down' : '') : '';
  return `
  <div class="aa-row ${flags.length ? 'flagged-row' : ''}" onclick="openDrawer('${esc(a.login||a.id)}')">
    <span class="aa-num">${rank}</span>
    <div class="aa-info">
      <div class="aa-name">${esc(a.name)}${a.new_hire ? '<span class="new-hire-chip">NEW</span>' : ''}</div>
      <div class="aa-badge">${esc(a.id||a.login)}</div>
    </div>
    <span class="aa-pt-num ${cls}">${fmt(pt)}</span>
    <div class="pt-bar-wrap">
      <div class="pt-bar"><div class="pt-bar-fill ${cls}" style="width:${barPct}%"></div></div>
      <span class="pt-trend ${trendCls}">${proj ? 'Proj: '+fmt(proj.trending) : ''} ${trendTxt}</span>
    </div>
    <div class="flags-wrap">
      ${flags.map(f => `<span class="flag-chip ${severityCls(f.severity)}">${esc(f.label)}</span>`).join('')}
      ${a.handoff_note ? '<span class="flag-chip medium">📋</span>' : ''}
    </div>
  </div>`;
}

// ── Drawer ────────────────────────────────────────────────────────────────────
async function openDrawer(login) {
  S.selectedLogin = login;
  const a = S.associates.find(x => (x.login||x.id) === login) || {};
  // Set header immediately
  const dname = document.getElementById('d-name');
  const dsub  = document.getElementById('d-sub');
  if (dname) dname.textContent = a.name || login;
  if (dsub)  dsub.textContent  = `${esc(a.id||a.login||'')} · ${esc(a.manager||'')}`;
  // Show drawer
  const overlay = document.getElementById('drawer-overlay');
  const drawer  = document.getElementById('drawer');
  if (overlay) overlay.classList.remove('hidden');
  if (drawer)  { drawer.classList.remove('hidden'); requestAnimationFrame(() => drawer.classList.add('open')); }
  // Load body
  const body = document.getElementById('drawer-body');
  if (body) body.innerHTML = '<div class="loading-msg">Loading…</div>';
  await renderDrawerBody(login, a);
}
function closeDrawer() {
  const drawer  = document.getElementById('drawer');
  const overlay = document.getElementById('drawer-overlay');
  if (drawer)  { drawer.classList.remove('open'); setTimeout(() => drawer.classList.add('hidden'), 260); }
  if (overlay) overlay.classList.add('hidden');
  S.selectedLogin = null;
}

async function renderDrawerBody(login, a) {
  const body = document.getElementById('drawer-body');
  if (!body) return;

  const [fbRes, barRes, trendRes, pattRes] = await Promise.all([
    api(`/api/feedback/${encodeURIComponent(login)}`),
    api(`/api/barriers/${encodeURIComponent(login)}`),
    api(`/api/trend/${encodeURIComponent(login)}?shift=${S.currentShift}`),
    api(`/api/patterns/${encodeURIComponent(login)}`),
  ]);

  const feedbacks  = fbRes?.records || [];
  const nextAction = fbRes?.next_action;
  const barriers   = Array.isArray(barRes) ? barRes : [];
  const trendPts   = trendRes?.points || [];
  const pattern    = pattRes || a.pattern || {};
  const flags      = a.flags || [];
  const proj       = a.projection;
  const andons     = S.andons.filter(x => x.login === login);
  const pt         = a.pt;

  let html = '';

  // Next action
  if (nextAction) {
    html += `<div class="d-section">
      <div class="d-section-title">Next Action</div>
      <div class="next-action-badge" style="background:${esc(nextAction.color||'#f59e0b')}22;border:1px solid ${esc(nextAction.color||'#f59e0b')}">
        <span style="color:${esc(nextAction.color||'#f59e0b')};font-size:14px">●</span>
        <span>${esc(nextAction.label)}</span>
      </div>
      <div class="na-reason">${esc(nextAction.reason)}</div>
      ${nextAction.days_remaining != null ? `<div class="expiry-pill ${nextAction.days_remaining<=7?'crit':nextAction.days_remaining<=14?'warn':''}">${nextAction.days_remaining}d remaining</div>` : ''}
    </div>`;
  }

  // PT / projection
  if (proj) {
    html += `<div class="d-section">
      <div class="d-section-title">Projection</div>
      <div class="metric-row"><span class="metric-label">Current PT</span><span class="metric-val ${ptCls(pt)}">${fmt(pt)}</span></div>
      <div class="metric-row"><span class="metric-label">Trending (same pace)</span><span class="metric-val ${ptCls(proj.trending)}">${fmt(proj.trending)}</span></div>
      <div class="metric-row"><span class="metric-label">Best case</span><span class="metric-val ${ptCls(proj.best_case)}">${fmt(proj.best_case)}</span></div>
      <div class="metric-row"><span class="metric-label">Can hit 88%?</span><span class="metric-val ${proj.can_hit_88?'text-green':'text-red'}">${proj.can_hit_88?'Yes':'No'}</span></div>
      <div class="metric-row"><span class="metric-label">Elapsed / Remaining</span><span class="metric-val">${proj.elapsed_hrs}h / ${proj.remaining_hrs}h</span></div>
    </div>`;
  }

  // Flags
  if (flags.length) {
    html += `<div class="d-section">
      <div class="d-section-title">Active Flags</div>
      <div class="flags-wrap" style="flex-wrap:wrap;gap:6px;padding:4px 0">
        ${flags.map(f => `<span class="flag-chip ${severityCls(f.severity)}">${esc(f.label)}</span>`).join('')}
      </div>
    </div>`;
  }

  // Pattern
  if (pattern.consecutive_low >= 2) {
    html += `<div class="d-section">
      <div class="d-section-title">Trend Pattern</div>
      <div class="pattern-badge">${esc(pattern.streak_label)}</div>
      ${pattern.history?.slice(0,5).map(h => `<div class="metric-row">
        <span class="metric-label">${esc(h.date)} ${esc(h.shift)}</span>
        <span class="metric-val ${ptCls(h.pt)}">${fmt(h.pt)}</span>
      </div>`).join('') || ''}
    </div>`;
  }

  // Momentum (trend chart from DB snapshots)
  if (trendPts.length >= 2) {
    const max = Math.max(...trendPts.map(p=>p.pt||0)) || 100;
    html += `<div class="d-section">
      <div class="d-section-title">Shift Momentum</div>
      <div class="momentum-bars">
        ${trendPts.slice(-8).map(p => {
          const h = Math.round((p.pt||0)/max*60);
          const c = ptCls(p.pt);
          return `<div class="momentum-bar-wrap">
            <div class="momentum-pct ${c}">${fmt(p.pt,0)}</div>
            <div class="momentum-bar ${c}" style="height:${h}px;background:var(--${c==='good'?'green':c==='warn'?'orange':'red'})"></div>
            <div class="momentum-lbl">${new Date(p.ts).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}</div>
          </div>`;
        }).join('')}
      </div>
    </div>`;
  }

  // Andons
  if (andons.length) {
    html += `<div class="d-section"><div class="d-section-title">Active Andons</div>
      ${andons.map(an => `<div class="andon-item"><div class="andon-top"><span>${esc(an.description||an.type||'Andon')}</span><span class="andon-dwell">${esc(an.dwell||'')}</span></div></div>`).join('')}
    </div>`;
  }

  // Feedback history
  html += `<div class="d-section"><div class="d-section-title">Feedback History</div>
    ${feedbacks.length === 0
      ? '<div class="empty-msg">No feedback on record</div>'
      : feedbacks.map(f => `<div class="metric-row">
          <span class="metric-label">${esc(f.date)}</span>
          <span class="metric-val">${esc(LABELS[f.type]||f.type)}</span>
          <span style="font-size:10px;color:var(--muted)">${esc(f.notes||'')}</span>
        </div>`).join('')}
  </div>`;

  // Barriers
  if (barriers.length) {
    html += `<div class="d-section"><div class="d-section-title">Barriers</div>
      ${barriers.slice(0,5).map(b => `<div class="metric-row">
        <span class="metric-label">${esc(b.date)}</span>
        <span class="metric-val">${esc(b.barrier)}</span>
      </div>`).join('')}
    </div>`;
  }

  // Handoff note
  if (a.handoff_note) {
    html += `<div class="d-section"><div class="d-section-title">Handoff Note</div>
      <div style="font-size:12px;color:var(--text);line-height:1.5">${esc(a.handoff_note.note)}</div>
      <div style="font-size:10px;color:var(--muted);margin-top:4px">from ${esc(a.handoff_note.am_name)}</div>
    </div>`;
  }

  // New hire info
  if (a.new_hire) {
    html += `<div class="d-section"><div class="d-section-title">New Hire</div>
      <div class="metric-row"><span class="metric-label">Start Date</span><span class="metric-val">${esc(a.new_hire.start_date)}</span></div>
      <div class="metric-row"><span class="metric-label">Day #</span><span class="metric-val">${a.new_hire.day}</span></div>
      ${a.new_hire.notes ? `<div style="font-size:11px;color:var(--muted2);margin-top:4px">${esc(a.new_hire.notes)}</div>` : ''}
    </div>`;
  }

  // Action buttons
  html += `<div class="action-row">
    <button class="pri-btn" onclick="openFeedbackModal('${esc(login)}')">Log Feedback</button>
    <button class="sec-action-btn" onclick="openSTUModal('${esc(login)}')">STU</button>
    <button class="sec-action-btn warn-btn" onclick="openBarrierModal('${esc(login)}')">Log Barrier</button>
    <button class="sec-action-btn" onclick="openCoachingPrep('${esc(login)}')">Coaching Packet</button>
    <a class="sec-action-btn" href="https://atoz.amazon.work/engage/conversation-hub?f=NrBEHkDkH0AUCUCiBZAkgZUaANAb1AG4CGANgK4CmoAXKAC4BOloAvgLrZgDCUAaovHQBBACqooceOAAiAVS4icwfMXJLVaqLkKSs8hUs1qJIAcSEmsLPasOgh0obEXs2bIA" target="_blank">Engage</a>
    <a class="sec-action-btn" href="https://adapt-iad.amazon.com/#/employee-dashboard/${esc(login)}" target="_blank">Adapt</a>
  </div>`;

  body.innerHTML = html;
}

// Feedback labels (client-side)
const LABELS = {
  document_coaching:'Document Coaching', first_warning:'First Warning',
  second_warning:'Second Warning', final_warning:'Final Warning',
  separation:'Separation', stu:'STU Only',
};

// ── Rankings tab ──────────────────────────────────────────────────────────────
async function renderRankings() {
  const el = document.getElementById('rankings-content');
  if (!el) return;
  el.innerHTML = '<div class="loading-msg">Loading rankings…</div>';
  const r = await api(`/api/rankings?shift=${S.currentShift}`);
  if (!r) { el.innerHTML = '<div class="empty-msg">Failed to load.</div>'; return; }

  const managers = r.managers || [];
  const top      = r.top_performers || [];
  const flagged  = r.most_flagged || [];
  const patterns = r.patterns || [];
  const wb       = r.would_be;

  el.innerHTML = `
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:20px">
    <div class="rank-section">
      <div class="rank-title">AM Accountability</div>
      ${managers.map(m => `<div class="rank-row">
        <div style="flex:1">
          <div class="rank-name">${esc(m.name)}</div>
          <div class="rank-sub">${m.aa_count} AAs · ${m.actions_7d} actions (7d)</div>
        </div>
        <span class="rank-pt ${ptCls(m.pt)}">${m.pt != null ? m.pt.toFixed(1)+'%' : '–'}</span>
        ${m.actions_7d === 0 ? '<span class="am-no-action">No actions</span>' : ''}
      </div>`).join('')}
    </div>
    <div class="rank-section">
      <div class="rank-title">🏆 Top Performers</div>
      ${top.slice(0,8).map((a,i) => `<div class="rank-row">
        <span class="rank-pos">${i+1}</span>
        <div style="flex:1"><div class="rank-name">${esc(a.name)}</div><div class="rank-sub">${esc(a.manager||'')}</div></div>
        <span class="rank-pt ${ptCls(a.pt)}">${fmt(a.pt)}</span>
      </div>`).join('')}
    </div>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
    <div class="rank-section">
      <div class="rank-title">⚠ Most Flagged</div>
      ${flagged.slice(0,8).map(a => `<div class="rank-row" onclick="openDrawer('${esc(a.login||a.id)}')" style="cursor:pointer">
        <div style="flex:1"><div class="rank-name">${esc(a.name)}</div>
        <div class="flags-wrap">${(a.flags||[]).map(f=>`<span class="flag-chip ${severityCls(f.severity)}">${esc(f.label)}</span>`).join('')}</div></div>
        <span class="rank-pt ${ptCls(a.pt)}">${fmt(a.pt)}</span>
      </div>`).join('') || '<div class="empty-msg">No flagged associates</div>'}
    </div>
    <div class="rank-section">
      <div class="rank-title">🔍 Pattern Watch</div>
      ${patterns.length === 0 ? '<div class="empty-msg">No repeat patterns</div>' :
        patterns.map(p => `<div class="rank-row" onclick="openDrawer('${esc(p.login)}')" style="cursor:pointer">
          <div style="flex:1"><div class="rank-name">${esc(p.name)}</div>
          <div class="rank-sub">${esc(p.consecutive)} consecutive shifts &lt;88%</div></div>
        </div>`).join('')}
      ${wb ? `<div style="margin-top:12px;padding:10px;background:var(--card2);border-radius:6px;border:1px solid var(--border)">
        <div style="font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.6px">Would-Be PT</div>
        <div style="display:flex;gap:16px;margin-top:6px">
          <span>Now: <strong class="${ptCls(wb.current)}">${fmt(wb.current)}</strong></span>
          <span>If fixed: <strong class="${ptCls(wb.would_be)}">${fmt(wb.would_be)}</strong></span>
          <span class="${wb.delta>0?'text-green':'text-red'}">${fmtD(wb.delta)}</span>
        </div>
      </div>` : ''}
    </div>
  </div>`;
}

// ── ETI/TPH tab ───────────────────────────────────────────────────────────────
async function fetchETI() {
  const el = document.getElementById('eti-content');
  if (!el) return;
  el.innerHTML = '<div class="loading-msg">Fetching ETI/TPH (browser window will open)…</div>';
  const r = await api(`/api/eti?shift=${S.currentShift}`);
  if (!r || !r.ok) {
    el.innerHTML = '<div class="loading-msg">ETI/TPH fetch started — check back in ~30 seconds, then click Fetch again.</div>';
    return;
  }
  renderETI(r);
}
function renderETI(r) {
  const el = document.getElementById('eti-content');
  if (!el) return;
  const rows = r.rows || r.data || [];
  if (!rows.length) { el.innerHTML = '<div class="empty-msg">No ETI/TPH data returned.</div>'; return; }
  const avg_eti = rows.reduce((s,x) => s+(x.eti||0), 0)/rows.length;
  const avg_tph = rows.reduce((s,x) => s+(x.tph||0), 0)/rows.length;
  const low = rows.filter(x => x.eti < 80);
  let suggestion = '';
  if (avg_eti < 75) suggestion = 'Floor-wide ETI critically low — check system/path issues.';
  else if (low.length > rows.length*0.3) suggestion = `${low.length} associates below 80% ETI — review path assignments.`;
  else suggestion = 'ETI/TPH within normal range.';
  el.innerHTML = `
  <div class="eti-grid">
    <div class="eti-card"><div class="eti-label">Avg ETI</div><div class="eti-val">${avg_eti.toFixed(1)}%</div></div>
    <div class="eti-card"><div class="eti-label">Avg TPH</div><div class="eti-val">${avg_tph.toFixed(0)}</div></div>
    <div class="eti-card"><div class="eti-label">Below 80%</div><div class="eti-val ${low.length>0?'text-orange':''}">${low.length}</div></div>
  </div>
  <div class="actions-box" style="margin-bottom:16px">
    <div class="actions-title">Suggested Action</div>
    <div class="action-item">${esc(suggestion)}</div>
  </div>
  <table style="width:100%;border-collapse:collapse;font-size:12px">
    <thead><tr style="color:var(--muted);font-size:10px;text-transform:uppercase">
      <th style="padding:6px 8px;text-align:left;border-bottom:1px solid var(--border)">Name</th>
      <th style="padding:6px 8px;text-align:right;border-bottom:1px solid var(--border)">ETI%</th>
      <th style="padding:6px 8px;text-align:right;border-bottom:1px solid var(--border)">TPH</th>
    </tr></thead>
    <tbody>
      ${[...rows].sort((a,b)=>(a.eti||0)-(b.eti||0)).map(row => `
        <tr style="${row.eti<80?'background:#1a0f0f':''};border-bottom:1px solid var(--border)">
          <td style="padding:7px 8px">${esc(row.name)}</td>
          <td style="padding:7px 8px;text-align:right;font-weight:600" class="${row.eti<80?'text-red':row.eti<88?'text-orange':'text-green'}">${row.eti!=null?row.eti.toFixed(1)+'%':'–'}</td>
          <td style="padding:7px 8px;text-align:right">${row.tph!=null?row.tph.toFixed(0):'–'}</td>
        </tr>`).join('')}
    </tbody>
  </table>`;
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

function openFeedbackModal(login) {
  const a = S.associates.find(x => (x.login||x.id)===login) || {};
  openModal(`Log Feedback — ${a.name||login}`, `
    <form id="fb-form">
      <label>Type<select name="type" style="width:100%;margin-top:4px;padding:8px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:6px">
        <option value="document_coaching">Document Coaching</option>
        <option value="first_warning">First Warning</option>
        <option value="second_warning">Second Warning</option>
        <option value="final_warning">Final Warning</option>
      </select></label>
      <label style="margin-top:12px;display:block">Date
        <input type="date" name="date" value="${new Date().toISOString().slice(0,10)}" style="width:100%;margin-top:4px;padding:8px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:6px">
      </label>
      <label style="margin-top:12px;display:block">Notes (optional)
        <textarea name="notes" rows="3" placeholder="Context, what was discussed…" style="width:100%;margin-top:4px;padding:8px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:6px;resize:vertical"></textarea>
      </label>
    </form>
    <div class="modal-footer">
      <button class="sec-action-btn" onclick="closeModal()">Cancel</button>
      <button class="pri-btn" onclick="submitFeedback('${esc(login)}','${esc(a.name||login)}')">Save</button>
    </div>`);
}
async function submitFeedback(login, name) {
  const form = document.getElementById('fb-form');
  if (!form) return;
  const fd = new FormData(form);
  const r = await apiPost('/api/feedback', {
    login, name, type: fd.get('type'),
    date: fd.get('date'), notes: fd.get('notes'), has_pending: false,
  });
  if (r?.ok) { closeModal(); showToast('Feedback saved', 'success'); loadAll(); }
  else showToast('Failed to save feedback', 'warn');
}

async function openSTUModal(login) {
  const a = S.associates.find(x => (x.login||x.id)===login) || {};
  openModal(`STU — ${a.name||login}`, '<div class="loading-msg">Loading template…</div>');
  const r = await api(`/api/stu-template/${encodeURIComponent(login)}?shift=${S.currentShift}`);
  const tmpl = r?.template || 'Situation:\nTask:\nUrgency:';
  document.getElementById('modal-body').innerHTML = `
    <textarea id="stu-txt" rows="8" style="width:100%;padding:10px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:6px;font-size:13px;line-height:1.6;resize:vertical">${esc(tmpl)}</textarea>
    <div class="modal-footer">
      <button class="sec-action-btn" onclick="closeModal()">Close</button>
      <button class="pri-btn" onclick="navigator.clipboard.writeText(document.getElementById('stu-txt').value).then(()=>showToast('Copied','success'))">Copy</button>
    </div>`;
}

function openBarrierModal(login) {
  const a = S.associates.find(x => (x.login||x.id)===login) || {};
  openModal(`Log Barrier — ${a.name||login}`, `
    <form id="bar-form">
      <label>Barrier Type<select name="barrier" style="width:100%;margin-top:4px;padding:8px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:6px">
        <option>Equipment Issue</option><option>System Down</option><option>Path Issue</option>
        <option>Staffing Gap</option><option>Training Gap</option><option>Other</option>
      </select></label>
      <label style="margin-top:12px;display:block">Description
        <textarea name="flag_type" rows="3" required placeholder="What happened?" style="width:100%;margin-top:4px;padding:8px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:6px;resize:vertical"></textarea>
      </label>
    </form>
    <div class="modal-footer">
      <button class="sec-action-btn" onclick="closeModal()">Cancel</button>
      <button class="pri-btn" onclick="submitBarrier('${esc(login)}','${esc(a.name||login)}')">Save</button>
    </div>`);
}
async function submitBarrier(login, name) {
  const form = document.getElementById('bar-form');
  if (!form) return;
  const fd = new FormData(form);
  const r = await apiPost('/api/barriers', {
    login, name, barrier: fd.get('barrier'), flag_type: fd.get('flag_type'),
  });
  if (r?.ok) { closeModal(); showToast('Barrier logged', 'success'); }
  else showToast('Failed to save barrier', 'warn');
}

async function openHandoffModal() {
  openModal('Shift Handoff Note', '<div class="loading-msg">Loading…</div>');
  const r = await api(`/api/handoff?shift=${S.currentShift}`);
  const existing = Array.isArray(r) && r.length ? r[0].note : '';
  document.getElementById('modal-body').innerHTML = `
    <p style="font-size:12px;color:var(--muted2);margin-bottom:8px">Write a note for the incoming AM. It will appear in drawer views for all associates.</p>
    <textarea id="ho-txt" rows="10" style="width:100%;padding:10px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:6px;font-size:13px;line-height:1.6;resize:vertical">${esc(existing)}</textarea>
    <div class="modal-footer">
      <button class="sec-action-btn" onclick="navigator.clipboard.writeText(document.getElementById('ho-txt').value).then(()=>showToast('Copied','success'))">Copy</button>
      <button class="sec-action-btn" onclick="closeModal()">Cancel</button>
      <button class="pri-btn" onclick="submitHandoff()">Save</button>
    </div>`;
}
async function submitHandoff() {
  const txt = document.getElementById('ho-txt')?.value;
  if (!txt) return;
  const r = await apiPost('/api/handoff', { note: txt });
  if (r?.ok) { closeModal(); showToast('Handoff saved', 'success'); }
  else showToast('Failed to save', 'warn');
}

async function openCoachingPrep(login) {
  const a = S.associates.find(x => (x.login||x.id)===login) || {};
  openModal(`Coaching Packet — ${a.name||login}`, '<div class="loading-msg">Generating…</div>');
  const r = await api(`/api/coaching-prep/${encodeURIComponent(login)}?shift=${S.currentShift}`);
  if (!r) { document.getElementById('modal-body').innerHTML = '<div class="empty-msg">Failed to load.</div>'; return; }
  const packet = `COACHING PREP PACKET
Generated: ${new Date().toLocaleString()}
==============================
ASSOCIATE: ${r.name}   ID: ${r.badge}
Manager: ${r.manager}
Current PT: ${r.current_pt != null ? r.current_pt.toFixed(1)+'%' : '–'}
Projected (trending): ${r.projection?.trending != null ? r.projection.trending.toFixed(1)+'%' : '–'}
Can hit 88%: ${r.projection?.can_hit_88 != null ? (r.projection.can_hit_88 ? 'Yes' : 'No') : '–'}

FLAGS: ${(r.flags||[]).map(f=>f.label).join(', ') || 'None'}
PATTERN: ${r.pattern?.streak_label || 'None'}
NEXT ACTION: ${r.next_action?.label || '–'}

FEEDBACK HISTORY:
${r.feedback_history?.length === 0 ? 'No feedback on record' :
  (r.feedback_history||[]).map(f=>`  ${f.date} — ${LABELS[f.type]||f.type}${f.notes?': '+f.notes:''}`).join('\n')}

BARRIERS (recent):
${r.barriers?.length === 0 ? 'None' :
  (r.barriers||[]).map(b=>`  ${b.date} — ${b.barrier}: ${b.flag_type}`).join('\n')}

STU TEMPLATE:
"${r.stu_template || ''}"`;
  document.getElementById('modal-body').innerHTML = `
    <pre id="prep-txt" style="white-space:pre-wrap;font-family:monospace;font-size:11px;background:var(--bg);padding:14px;border-radius:6px;border:1px solid var(--border);max-height:400px;overflow-y:auto">${esc(packet)}</pre>
    <div class="modal-footer">
      <button class="sec-action-btn" onclick="closeModal()">Close</button>
      <button class="sec-action-btn" onclick="(()=>{const w=window.open('','_blank');w.document.write('<pre style=\\'font-family:monospace;padding:20px\\'>'+document.getElementById('prep-txt').innerHTML+'</pre>');w.print()})()">Print</button>
      <button class="pri-btn" onclick="navigator.clipboard.writeText(document.getElementById('prep-txt').textContent).then(()=>showToast('Copied','success'))">Copy</button>
    </div>`;
}

function openBarrierPatterns() {
  const patterns = S.barrierPatterns;
  openModal('Systemic Barrier Patterns',
    patterns.length === 0
      ? '<div class="empty-msg">No systemic patterns detected yet.</div>'
      : patterns.map(p => `<div style="padding:10px;background:var(--card2);border-radius:6px;margin-bottom:8px;border:1px solid var(--border)">
          <div style="font-weight:600;color:var(--text)">${esc(p.barrier)}</div>
          <div style="font-size:11px;color:var(--muted);margin-top:3px">${p.cnt} occurrences · ${esc(p.associates||'')}</div>
        </div>`).join('') +
      `<div class="modal-footer"><button class="sec-action-btn" onclick="closeModal()">Close</button></div>`);
}

// ── Tab switching ─────────────────────────────────────────────────────────────
function switchTab(tab) {
  S.activeTab = tab;
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  document.querySelectorAll('.tab-pane').forEach(p => {
    const isActive = p.id === 'tab-' + tab;
    p.classList.toggle('active', isActive);
    p.classList.toggle('hidden', !isActive);
  });
  if (tab === 'rankings') renderRankings();
  else if (tab === 'floor') renderFloor();
}

// ── Shift toggle ──────────────────────────────────────────────────────────────
function setShift(shift) {
  S.currentShift = shift;
  document.querySelectorAll('.shift-btn').forEach(b => b.classList.toggle('active', b.dataset.shift === shift));
  loadAll();
}

// ── View filter buttons ───────────────────────────────────────────────────────
function setView(view) {
  S.currentView = view;
  document.querySelectorAll('.view-btn').forEach(b => b.classList.toggle('active', b.dataset.view === view));
  renderFloor();
}

// ── Render all ────────────────────────────────────────────────────────────────
function renderAll() {
  renderExpiryBanner();
  renderSummary();
  populateAMFilter();
  if (S.activeTab === 'floor') renderFloor();
  else if (S.activeTab === 'rankings') renderRankings();
  // Refresh drawer if open
  if (S.selectedLogin) {
    const fresh = S.associates.find(a => (a.login||a.id) === S.selectedLogin);
    if (fresh) renderDrawerBody(S.selectedLogin, fresh);
  }
}

// ── Auto-refresh ──────────────────────────────────────────────────────────────
function startAutoRefresh() {
  if (S.refreshTimer) clearInterval(S.refreshTimer);
  S.refreshTimer = setInterval(loadAll, 3 * 60 * 1000);
}

// ── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Detect shift from current time
  const h = new Date().getHours();
  S.currentShift = (h >= 18 || h < 6) ? 'night' : 'day';
  document.querySelectorAll('.shift-btn').forEach(b => b.classList.toggle('active', b.dataset.shift === S.currentShift));

  // Shift buttons
  document.querySelectorAll('.shift-btn').forEach(b => b.addEventListener('click', () => setShift(b.dataset.shift)));
  // Tab buttons
  document.querySelectorAll('.tab-btn').forEach(b => b.addEventListener('click', () => switchTab(b.dataset.tab)));
  // View filter buttons
  document.querySelectorAll('.view-btn').forEach(b => b.addEventListener('click', () => setView(b.dataset.view)));
  // AM filter dropdown
  const amf = document.getElementById('am-filter');
  if (amf) amf.addEventListener('change', e => { S.amFilter = e.target.value; renderFloor(); });
  // Bell / notifications
  const notifBtn = document.getElementById('notif-btn');
  if (notifBtn) notifBtn.addEventListener('click', toggleNotifPanel);
  const clearNotifs = document.getElementById('clear-notifs');
  if (clearNotifs) clearNotifs.addEventListener('click', () => {
    S.notifications = []; S.unreadCount = 0; updateBell();
    document.getElementById('notif-list').innerHTML = '<div class="empty-msg">No alerts</div>';
  });
  // Drawer close
  const drawerClose = document.getElementById('drawer-close');
  if (drawerClose) drawerClose.addEventListener('click', closeDrawer);
  const drawerOverlay = document.getElementById('drawer-overlay');
  if (drawerOverlay) drawerOverlay.addEventListener('click', closeDrawer);
  // Modal close
  const modalClose = document.getElementById('modal-close');
  if (modalClose) modalClose.addEventListener('click', closeModal);
  const modalOverlay = document.getElementById('modal-overlay');
  if (modalOverlay) modalOverlay.addEventListener('click', e => { if (e.target === modalOverlay) closeModal(); });
  // Toolbar buttons
  const refreshBtn = document.getElementById('refresh-btn');
  if (refreshBtn) refreshBtn.addEventListener('click', loadAll);
  const handoffBtn = document.getElementById('handoff-btn');
  if (handoffBtn) handoffBtn.addEventListener('click', openHandoffModal);
  const barriersBtn = document.getElementById('barriers-btn');
  if (barriersBtn) barriersBtn.addEventListener('click', openBarrierPatterns);
  const fetchEtiBtn = document.getElementById('fetch-eti-btn');
  if (fetchEtiBtn) fetchEtiBtn.addEventListener('click', fetchETI);

  // Keyboard shortcuts
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') { closeModal(); closeDrawer(); }
  });

  initSSE();
  loadAll();
  startAutoRefresh();
});
