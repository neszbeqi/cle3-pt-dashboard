// CLE3 PT Dashboard — app.js  (2026-08-07)

const S = {
  associates: [],   // all associates, unfiltered
  actions:    [],
  departed:   [],   // flagged AAs who clocked out mid-shift
  shift:      'night',
  floor:      'all',
  activeTab:  'floor',
  loading:    false,
  countdown:  180,
  countdownTm: null,
};

// ── Helpers ───────────────────────────────────────────────────────────────────
const esc = s => s == null ? '' : String(s)
  .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
const fmt  = (n,d=1) => n == null ? '–' : Number(n).toFixed(d) + '%';
const fmtH = h => h == null ? '–' : Number(h).toFixed(2) + 'h';

// Client-side 4-tier status (CSS classes: good/watch/low/below/unknown)
function ptSt(pt) {
  if (pt == null) return 'unknown';
  if (pt >= 88)   return 'good';
  if (pt >= 85)   return 'watch';
  if (pt >= 80)   return 'low';
  return 'below';
}

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

// ── Toast ─────────────────────────────────────────────────────────────────────
let _toastTm = null;
function toast(msg, crit=false) {
  const el = document.getElementById('toast');
  if (!el) return;
  el.textContent = msg;
  el.className = crit ? 'toast toast-crit' : 'toast';
  clearTimeout(_toastTm);
  _toastTm = setTimeout(() => el.classList.add('hidden'), 3500);
}

// ── Header ────────────────────────────────────────────────────────────────────
function updateHeader(shift, date, updatedAt) {
  const sb = document.getElementById('shift-badge');
  if (sb) sb.textContent = shift === 'night' ? 'Night Shift' : 'Day Shift';
  const db = document.getElementById('date-badge');
  if (db && date) db.textContent = date;
  if (updatedAt) {
    const lu = document.getElementById('last-updated');
    if (lu) lu.textContent = 'Updated ' +
      new Date(updatedAt).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});
  }
}

function updateAlertStrip(aas) {
  const el = document.getElementById('alert-strip');
  if (!el) return;
  const below = aas.filter(a => a.status === 'below').length;
  const watch = aas.filter(a => a.status === 'watch').length;
  const total = aas.length;
  if (total === 0) { el.innerHTML = ''; return; }
  const parts = [];
  if (below > 0) parts.push(`<span class="alert-c">▼ ${below} below target</span>`);
  if (watch > 0) parts.push(`<span class="alert-w">⚠ ${watch} watch</span>`);
  if (!below && !watch) parts.push(`<span class="alert-ok">✓ All ${total} AAs on target</span>`);
  el.innerHTML = parts.join('');
}

// ── Countdown ─────────────────────────────────────────────────────────────────
function startCountdown() {
  S.countdown = 180;
  clearInterval(S.countdownTm);
  S.countdownTm = setInterval(() => {
    S.countdown--;
    const el = document.getElementById('countdown');
    if (el) el.textContent = 'Refresh in ' + S.countdown + 's';
    if (S.countdown <= 0) { clearInterval(S.countdownTm); loadData(); }
  }, 1000);
}

// ── Load data ─────────────────────────────────────────────────────────────────
async function loadData() {
  if (S.loading) return;
  S.loading = true;
  clearInterval(S.countdownTm);

  const btn = document.getElementById('refresh-btn');
  if (btn) { btn.disabled = true; btn.textContent = '⟳ Loading…'; }

  const [dataRes, actsRes] = await Promise.all([
    api(`/api/data?shift=${S.shift}&floor=all`),
    api(`/api/actions?shift=${S.shift}`)
  ]);
  // departed is embedded in the data response

  S.loading = false;
  if (btn) { btn.disabled = false; btn.textContent = '⟳ PT Data'; }

  if (!dataRes) {
    showSpinner('Server not responding — retrying…');
    startCountdown();
    return;
  }
  if (!dataRes.ok) {
    const msg = dataRes.msg || 'Fetching FCLM data…';
    showSpinner(msg);
    updateAlertStrip([]);
    updateBadges();
    setLoginNeeded(dataRes.need_login || false);
    startCountdown();
    return;
  }
  setLoginNeeded(false);

  S.associates = dataRes.associates || [];
  S.actions    = Array.isArray(actsRes) ? actsRes : [];
  S.departed   = dataRes.departed  || [];
  updateHeader(dataRes.shift, dataRes.date, dataRes.updated);
  updateAlertStrip(S.associates);
  updateBadges();
  renderActiveTab();
  startCountdown();
}

function showSpinner(msg) {
  const el = document.getElementById('floor-content');
  if (el) el.innerHTML =
    `<div class="spinner-wrap"><div class="spinner"></div><div id="floor-msg">${esc(msg)}</div></div>`;
}

function updateBadges() {
  const flagged = S.associates.filter(a => a.flagged).length;
  const bf = document.getElementById('badge-flagged');
  if (bf) { bf.textContent = flagged; bf.classList.toggle('hidden', !flagged); }
  const ba = document.getElementById('badge-actions');
  if (ba) { ba.textContent = S.actions.length; ba.classList.toggle('hidden', !S.actions.length); }
  const bd = document.getElementById('badge-departed');
  if (bd) { bd.textContent = S.departed.length; bd.classList.toggle('hidden', !S.departed.length); }
  const bb = document.getElementById('badge-breaks');
  const bkViolations = S.associates.filter(a => a.break_data && a.break_data.any_violation).length;
  if (bb) { bb.textContent = bkViolations; bb.classList.toggle('hidden', !bkViolations); }
}

// ── Floor view ────────────────────────────────────────────────────────────────
function renderFloor() {
  const el = document.getElementById('floor-content');
  if (!el) return;

  // Client-side floor filter
  const filtered = S.floor === 'all'
    ? S.associates
    : S.associates.filter(a => String(a.floor) === String(S.floor));

  if (!filtered.length) {
    el.innerHTML = S.associates.length === 0
      ? `<div class="spinner-wrap"><div class="spinner"></div><div>Loading FCLM data…</div></div>`
      : '<div class="empty-state">No associates on this floor.</div>';
    return;
  }

  // Group by floor
  const byFloor = {};
  for (const a of filtered) {
    const f = a.floor || 0;
    if (!byFloor[f]) byFloor[f] = [];
    byFloor[f].push(a);
  }
  const floors = Object.keys(byFloor).sort((a,b) => Number(a)-Number(b));
  el.innerHTML = floors.map(f => floorSection(Number(f), byFloor[f])).join('');
}

function floorSection(floorNum, aas) {
  const pts   = aas.map(a => a.pt_pct).filter(p => p != null);
  const avg   = pts.length ? pts.reduce((s,v)=>s+v,0)/pts.length : null;
  const below = aas.filter(a => a.status === 'below').length;
  const watch = aas.filter(a => a.status === 'watch').length;
  const good  = aas.filter(a => a.status === 'good').length;
  const st    = ptSt(avg);
  const gap   = avg != null ? avg - 88 : null;
  const barW  = avg != null ? Math.min(100, Math.max(0, avg)) : 0;
  const barCls = avg == null ? 'bar-unknown'
               : avg >= 88 ? 'bar-good' : avg >= 85 ? 'bar-watch' : avg >= 80 ? 'bar-low' : 'bar-below';
  const pills = [
    below > 0 && `<span style="color:var(--below);font-weight:700;font-size:11px">${below} below</span>`,
    watch > 0 && `<span style="color:var(--watch);font-weight:700;font-size:11px">${watch} watch</span>`,
    good  > 0 && `<span style="color:var(--good);font-size:11px">${good} on target</span>`,
  ].filter(Boolean);

  const sorted = [...aas].sort((a,b) => (a.pt_pct ?? 100) - (b.pt_pct ?? 100));

  return `<div class="floor-section">
    <div class="floor-hdr">
      <div class="floor-title">
        <span class="floor-name">Floor ${floorNum || '?'}</span>
        <span class="floor-meta">${aas.length} AAs</span>
      </div>
      <div class="floor-pt-info">
        <span class="floor-avg pt-${st}">${avg != null ? avg.toFixed(1)+'%' : '–'}</span>
        ${gap != null ? `<span class="floor-gap ${gap>=0?'gap-pos':'gap-neg'}">${gap>=0?'+':''}${gap.toFixed(1)}%</span>` : ''}
      </div>
      <div class="floor-bar-wrap">
        <div class="floor-bar ${barCls}" style="width:${barW}%"></div>
        <div class="bar-target-tick"></div>
      </div>
      <div style="display:flex;gap:8px;font-size:11px">${pills.join('')}</div>
    </div>
    <div class="table-wrap">
      <table class="aa-table">
        <thead><tr>
          <th>Station</th><th>Name</th><th>Badge</th>
          <th>PT%</th><th>Bar</th><th>To Recover</th><th>Idle</th><th>Status</th><th></th>
        </tr></thead>
        <tbody>${sorted.map(aaRow).join('')}</tbody>
      </table>
    </div>
  </div>`;
}

function aaRow(a) {
  const st    = ptSt(a.pt_pct);
  const projSt= ptSt(a.projection);
  const bar   = a.pt_pct != null ? Math.min(100, Math.max(0, a.pt_pct)) : 0;
  const idleM = a.inferred != null ? Math.round(a.inferred * 60) : null;
  const hasAct= S.actions.some(x => x.badge === a.badge);
  const repeat= (a.consecutive_low||0) >= 2;
  const idleColor = idleM > 30 ? 'var(--below)' : idleM > 15 ? 'var(--low)' : 'var(--txt-2)';

  return `<tr class="aa-row st-${st}">
    <td class="col-stn">${esc(a.station||'–')}</td>
    <td class="col-name">${esc(a.name)}${repeat?`<span class="repeat-flag" title="${a.consecutive_low} shifts below target">${a.consecutive_low}</span>`:''}</td>
    <td><a class="tc-link" href="/timecard/${esc(a.badge)}" target="_blank">${esc(a.badge)}</a></td>
    <td><span class="pt-num pt-${st}">${fmt(a.pt_pct)}</span></td>
    <td><div class="pt-wrap"><div class="pt-bg"><div class="pt-fill fill-${st}" style="width:${bar}%"></div></div></div></td>
    <td>${(()=>{
      const r = a.projection;
      if (r == null) return '<span style="color:var(--txt-2)">–</span>';
      if (r === 0)   return '<span style="color:var(--good);font-size:12px">✓ On Track</span>';
      if (r > 10)    return '<span style="color:var(--below);font-size:12px">Far off</span>';
      return '<span style="color:var(--watch);font-size:12px;font-weight:600">' + r.toFixed(1) + 'h to recover</span>';
    })()}</td>
    <td style="color:${idleColor}">${idleM != null ? idleM+'m' : '–'}</td>
    <td>${stChip(st)}</td>
    <td>${hasAct
      ? `<span class="act-tag">Actioned</span>`
      : `<button class="log-btn" onclick="openModal('${esc(a.badge)}','${esc(a.name)}','${esc(a.manager||'')}','${st}')">+ Action</button>`
    }</td>
  </tr>`;
}

function stChip(st) {
  if (st === 'good')    return `<span class="tta-ok">✓ On Target</span>`;
  if (st === 'watch')   return `<span class="tta-urgent">● Watch</span>`;
  if (st === 'low')     return `<span class="tta-urgent">⚠ Low</span>`;
  if (st === 'below')   return `<span class="tta-critical">✗ Below</span>`;
  return `<span class="tta-none">–</span>`;
}

// ── Flagged tab ───────────────────────────────────────────────────────────────
function renderFlagged() {
  const el = document.getElementById('flagged-content');
  if (!el) return;
  const flagged = [...S.associates]
    .filter(a => a.flagged)
    .sort((a,b) => (a.pt_pct??100) - (b.pt_pct??100));
  if (!flagged.length) {
    el.innerHTML = '<div class="empty-state">No flagged associates — great shift!</div>';
    return;
  }
  el.innerHTML = `<div class="flagged-list">${flagged.map(flagCard).join('')}</div>`;
}

function flagCard(a) {
  const st     = ptSt(a.pt_pct);
  const projSt = ptSt(a.projection);
  const hasAct = S.actions.some(x => x.badge === a.badge);
  const urgency = st === 'below' ? 'CRITICAL' : st === 'low' ? 'LOW' : 'WATCH';
  return `<div class="flag-card st-${st}">
    <div class="flag-card-top">
      <div class="flag-left">
        <span class="flag-urgency" style="color:${st==='below'?'var(--below)':st==='low'?'var(--low)':'var(--watch)'}">${urgency}</span>
        <span class="flag-name">${esc(a.name)}</span>
        <span class="flag-loc">${esc(a.station||'No station')} · ${esc(a.manager||'–')}</span>
      </div>
      <div class="flag-pt-block">
        <span class="flag-pt pt-${st}">${fmt(a.pt_pct)}</span>
        <span class="flag-pt-lbl">PT%</span>
      </div>
    </div>
    ${a.projection != null ? `<div class="flag-tta">Projected EOD: <span class="pt-${projSt} pt-num">${fmt(a.projection)}</span></div>` : ''}
    ${(a.consecutive_low||0) >= 2 ? `<div class="flag-lastact" style="color:var(--below);font-weight:600">${a.consecutive_low} consecutive shifts below target</div>` : ''}
    ${hasAct ? `<div class="flag-lastact">✓ Action logged this shift</div>` : ''}
    <div class="flag-btns">
      <a href="/timecard/${esc(a.badge)}" target="_blank">Open Timecard ↗</a>
      <button onclick="openModal('${esc(a.badge)}','${esc(a.name)}','${esc(a.manager||'')}','${st}')">+ Log Action</button>
    </div>
  </div>`;
}

// ── Shift Report tab ──────────────────────────────────────────────────────────
async function renderReport() {
  const el = document.getElementById('report-content');
  if (!el) return;
  el.innerHTML = '<div class="spinner-wrap"><div class="spinner"></div></div>';

  const r = await api(`/api/report?shift=${S.shift}`);
  if (!r || !r.ok) {
    el.innerHTML = `<div class="empty-state">${esc(r?.msg || 'No report data yet — wait for FCLM data to load.')}</div>`;
    return;
  }

  const ov  = r.overall_pt;
  const st  = ptSt(ov);
  const gap = ov != null ? ov - 88 : null;

  let html = `<div class="report-cards">
    <div class="rcard rcard-${ov>=88?'good':ov>=85?'watch':'below'}">
      <div class="rcard-val pt-${st}">${ov != null ? ov.toFixed(1)+'%' : '–'}</div>
      <div class="rcard-lbl">Overall PT%</div>
      ${gap != null ? `<div class="rcard-sub ${gap>=0?'pt-good':'pt-below'}">${gap>=0?'+':''}${gap.toFixed(1)}% vs 88%</div>` : ''}
    </div>
    <div class="rcard"><div class="rcard-val">${r.aa_count}</div><div class="rcard-lbl">Total AAs</div></div>
    <div class="rcard ${r.flagged_count>0?'rcard-warn':'rcard-good'}">
      <div class="rcard-val">${r.flagged_count}</div><div class="rcard-lbl">Flagged</div>
    </div>
    <div class="rcard ${r.below_count>0?'rcard-below':'rcard-good'}">
      <div class="rcard-val">${r.below_count}</div><div class="rcard-lbl">Below Target</div>
    </div>
    <div class="rcard">
      <div class="rcard-val">${r.intervention_count}</div><div class="rcard-lbl">Actions Logged</div>
    </div>
  </div>`;

  // Floor breakdown — server returns a dict keyed by floor number
  const fsum = r.floor_summary || {};
  const fkeys = Object.keys(fsum).filter(f => Number(f) > 0).sort((a,b) => Number(a)-Number(b));
  if (fkeys.length) {
    html += `<div class="report-sec"><div class="sec-title">Floor Breakdown</div>
      ${fkeys.map(f => {
        const v   = fsum[f];
        const fst = ptSt(v.avg_pt);
        const bw  = v.avg_pt != null ? Math.min(100, v.avg_pt) : 0;
        const bc  = v.avg_pt >= 88 ? 'bar-good' : v.avg_pt >= 85 ? 'bar-watch' : v.avg_pt >= 80 ? 'bar-low' : 'bar-below';
        return `<div class="report-fl-row">
          <span class="rfl-label">Floor ${f}</span>
          <div class="rfl-bar-wrap"><div class="rfl-bar ${bc}" style="width:${bw}%"></div><div class="rfl-tick"></div></div>
          <span class="rfl-val pt-${fst}">${v.avg_pt != null ? v.avg_pt.toFixed(1)+'%' : '–'}</span>
          <span class="rfl-count">${v.count} AAs</span>
        </div>`;
      }).join('')}
    </div>`;
  }

  // Zone issues
  if (r.zone_issues && r.zone_issues.length) {
    html += `<div class="report-sec"><div class="sec-title">Station Group Issues</div>
      ${r.zone_issues.map(z => `<div class="zone-issue">
        <span class="zone-lbl">Stns ${esc(z.zone)} &nbsp;<span style='font-weight:400;color:var(--txt-2)'>Floor ${z.floor}</span></span>
        <span class="zone-detail">${z.flagged} of ${z.total} AAs flagged · avg ${z.avg_pt != null ? z.avg_pt.toFixed(1)+'%' : '–'}</span>
      </div>`).join('')}
    </div>`;
  } else {
    html += `<div class="report-sec"><div class="sec-title">Station Group Issues</div><div class="no-issues">No station group issues detected.</div></div>`;
  }

  // Within-shift trend
  if (r.trend && r.trend.length > 1) {
    html += `<div class="report-sec"><div class="sec-title">Shift PT% Trend</div>${trendSVG(r.trend)}</div>`;
  }

  el.innerHTML = html;
}

function trendSVG(trend) {
  const W=560, H=120, pad={t:10,r:10,b:24,l:40};
  const pts = trend.filter(t => t.avg_pt != null);
  if (pts.length < 2) return '<div class="no-data">Not enough data points yet.</div>';
  const xs = pts.map((_,i) => pad.l + i*(W-pad.l-pad.r)/(pts.length-1));
  const toY = v => pad.t + (H-pad.t-pad.b)*(1-(v-60)/(100-60));
  const tgtY = toY(88);
  const path = pts.map((p,i) => (i===0?'M':'L')+xs[i].toFixed(1)+','+toY(p.avg_pt).toFixed(1)).join(' ');
  const dots = pts.map((p,i) => `<circle cx="${xs[i].toFixed(1)}" cy="${toY(p.avg_pt).toFixed(1)}" r="3" class="dot-${ptSt(p.avg_pt)}"/>`).join('');
  const skip = Math.ceil(pts.length/7);
  const labels = pts.filter((_,i)=>i%skip===0).map(p => {
    const i=pts.indexOf(p);
    const lbl = p.ts ? p.ts.slice(11,16) : '';
    return `<text x="${xs[i].toFixed(1)}" y="${H-4}" text-anchor="middle" class="chart-lbl">${esc(lbl)}</text>`;
  }).join('');
  return `<svg class="trend-svg" viewBox="0 0 ${W} ${H}">
    <line x1="${pad.l}" y1="${tgtY.toFixed(1)}" x2="${W-pad.r}" y2="${tgtY.toFixed(1)}" class="tg-line" stroke-dasharray="4,4"/>
    <text x="${pad.l-3}" y="${tgtY.toFixed(1)}" class="tg-lbl" text-anchor="end" dominant-baseline="middle">88%</text>
    <path d="${path}" fill="none" class="trend-path"/>
    ${dots}${labels}
  </svg>`;
}

// ── Actions tab ───────────────────────────────────────────────────────────────
function renderActions() {
  const el = document.getElementById('actions-content');
  if (!el) return;
  if (!S.actions.length) {
    el.innerHTML = '<div class="empty-state">No actions logged this shift yet.</div>';
    return;
  }
  el.innerHTML = `<table class="act-log">
    <thead><tr><th>Time</th><th>Name</th><th>Badge</th><th>Action</th><th>AM</th><th>PT%</th><th>Notes</th></tr></thead>
    <tbody>${S.actions.map(act => {
      const aa = S.associates.find(a => a.badge === act.badge) || {};
      const ts = act.ts ? new Date(act.ts).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}) : '–';
      return `<tr>
        <td style="color:var(--txt-2);font-size:12px">${ts}</td>
        <td class="col-name">${esc(act.name||aa.name||act.badge)}</td>
        <td><a class="tc-link" href="/timecard/${esc(act.badge)}" target="_blank">${esc(act.badge)}</a></td>
        <td><span class="act-tag">${esc(act.action_type)}</span></td>
        <td style="font-size:12px;color:var(--txt-2)">${esc(act.am_name||'–')}</td>
        <td><span class="pt-num pt-${ptSt(aa.pt_pct)}">${fmt(aa.pt_pct)}</span></td>
        <td style="font-size:12px;color:var(--txt-2)">${esc(act.note||'–')}</td>
      </tr>`;
    }).join('')}</tbody>
  </table>`;
}

// ── Departed tab ──────────────────────────────────────────────────────────────
function renderDeparted() {
  const el = document.getElementById('departed-content');
  if (!el) return;
  const list = [...S.departed].sort((a,b) => (b.gone_min||0) - (a.gone_min||0));
  if (!list.length) {
    el.innerHTML = '<div class="empty-state">No departed associates this shift — everyone is still clocked in.</div>';
    return;
  }
  el.innerHTML = `<div style="margin-bottom:12px;font-size:12px;color:var(--txt-2)">
    AAs who were below the PT threshold and are no longer clocked in at a station.
    After 60 minutes away they are likely not returning this shift.
  </div>
  <div class="dep-list">${list.map(depCard).join('')}</div>`;
}

function depCard(a) {
  const goneMin  = a.gone_min || 0;
  const likely   = a.likely_gone;
  const st       = ptSt(a.pt_pct);
  const goneStr  = goneMin < 60
    ? goneMin + 'm ago'
    : Math.floor(goneMin/60) + 'h ' + (goneMin%60) + 'm ago';
  const statusCls  = likely ? 'dep-likely' : (goneMin >= 30 ? 'dep-watch' : 'dep-may');
  const statusText = likely ? '⚠ Likely not returning' : (goneMin >= 30 ? 'Watch — 30+ min out' : 'May still return');
  const cardCls    = likely ? 'dep-likely' : (goneMin >= 30 ? 'dep-watch' : '');
  const fcUrl      = 'https://fclm-portal.amazon.com/employee/timeDetails?warehouseId=CLE3&employeeId=' + encodeURIComponent(a.badge||'');

  return '<div class="dep-card ' + cardCls + '">' +
    '<div class="dep-info">' +
      '<span class="dep-name">' + esc(a.name) + '</span>' +
      '<span class="dep-loc">Station ' + esc(a.station||'–') + ' · Floor ' + esc(a.floor||'?') + ' · ' + esc(a.manager||'–') + '</span>' +
      '<span class="dep-pt pt-' + st + '">Last PT: ' + fmt(a.pt_pct) +
        ((a.consecutive_low||0)>=2 ? ' · ' + a.consecutive_low + ' shifts below' : '') + '</span>' +
    '</div>' +
    '<div class="dep-time">' +
      '<span class="dep-gone-lbl">Left ' + goneStr + '</span>' +
      '<span class="dep-status ' + statusCls + '">' + statusText + '</span>' +
    '</div>' +
    '<div class="dep-btns">' +
      '<a href="' + fcUrl + '" target="_blank">Timecard ↗</a>' +
    '</div>' +
  '</div>';
}


function switchTab(tab) {
  S.activeTab = tab;
  document.querySelectorAll('.tab-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.tab === tab));
  document.querySelectorAll('.tab-pane').forEach(p =>
    p.classList.toggle('hidden', p.id !== 'tab-'+tab));
  renderActiveTab();
}

function renderActiveTab() {
  if      (S.activeTab === 'floor')    renderFloor();
  else if (S.activeTab === 'flagged')  renderFlagged();
  else if (S.activeTab === 'report')   renderReport();
  else if (S.activeTab === 'actions')  renderActions();
  else if (S.activeTab === 'departed') renderDeparted();
  else if (S.activeTab === 'breaks')   renderBreaks();
}


// ── Breaks tab ────────────────────────────────────────────────────────────────
function renderBreaks() {
  const el = document.getElementById('breaks-content');
  if (!el) return;

  const aas = S.associates.filter(a => a.break_data);
  if (!aas.length) {
    el.innerHTML = '<div class="empty-state">Break compliance data not yet loaded — it arrives with the next timecard refresh (~3 min).</div>';
    return;
  }

  const violations = aas.filter(a => a.break_data.any_violation);
  const clean      = aas.filter(a => !a.break_data.any_violation);

  let html = `<div class="brk-header">
    <span class="brk-summary">${violations.length} violation${violations.length !== 1 ? 's' : ''} of ${aas.length} tracked</span>
    <span class="brk-legend">
      <span class="brk-pill brk-flag">⚠ Flagged (&gt;7 min gap)</span>
      <span class="brk-pill brk-ok">✓ On time</span>
    </span>
  </div>`;

  if (violations.length) {
    html += '<div class="brk-section-lbl">Break violations</div>';
    html += '<div class="brk-list">' + violations.map(brkCard).join('') + '</div>';
  }
  if (clean.length) {
    html += `<details class="brk-clean-wrap"><summary class="brk-section-lbl brk-clean-lbl">
      ✓ On time (${clean.length})</summary>
      <div class="brk-list">${clean.map(brkCard).join('')}</div>
    </details>`;
  }

  el.innerHTML = html;
}

function brkCard(a) {
  const bd       = a.break_data || {};
  const st       = ptSt(a.pt_pct);
  const fcUrl    = 'https://fclm-portal.amazon.com/employee/timeDetails?warehouseId=CLE3&employeeId=' + encodeURIComponent(a.badge||'');
  const hasViol  = bd.any_violation;
  const cardCls  = hasViol ? 'brk-card brk-card-viol' : 'brk-card';

  // Shift start row
  let rows = '';
  if (bd.shift_start_gap != null) {
    const flag = bd.shift_start_flagged;
    rows += `<tr>
      <td class="brk-event">Shift start</td>
      <td class="brk-time">–</td>
      <td class="brk-time">–</td>
      <td class="brk-dur">–</td>
      <td class="brk-gap ${flag ? 'brk-gap-flag' : 'brk-gap-ok'}">–</td>
      <td class="brk-gap ${flag ? 'brk-gap-flag' : 'brk-gap-ok'}">${bd.shift_start_gap}m ${flag ? '⚠' : '✓'}</td>
    </tr>`;
  }

  // Break rows
  for (const b of (bd.breaks || [])) {
    const preCls  = b.pre_flagged  ? 'brk-gap-flag' : 'brk-gap-ok';
    const postCls = b.post_flagged ? 'brk-gap-flag' : 'brk-gap-ok';
    const preVal  = b.pre_gap_min  != null ? b.pre_gap_min + 'm ' + (b.pre_flagged  ? '⚠' : '✓') : '–';
    const postVal = b.post_gap_min != null ? b.post_gap_min + 'm ' + (b.post_flagged ? '⚠' : '✓') : '–';
    rows += `<tr>
      <td class="brk-event">Break ${b.break_num}</td>
      <td class="brk-time">${esc(b.break_start)}</td>
      <td class="brk-time">${esc(b.break_end)}</td>
      <td class="brk-dur">${b.break_dur_min}m</td>
      <td class="brk-gap ${preCls}">${preVal}</td>
      <td class="brk-gap ${postCls}">${postVal}</td>
    </tr>`;
  }

  return `<div class="${cardCls}">
    <div class="brk-card-hdr">
      <div class="brk-name-wrap">
        <span class="brk-name">${esc(a.name)}</span>
        <span class="brk-meta">Station ${esc(a.station||'–')} · Floor ${esc(a.floor||'?')} · PT: <span class="pt-num pt-${st}">${fmt(a.pt_pct)}</span></span>
      </div>
      <a href="${fcUrl}" target="_blank" class="brk-tc-link">Timecard ↗</a>
    </div>
    <table class="brk-table">
      <thead><tr>
        <th>Event</th><th>Left</th><th>Returned</th><th>Duration</th>
        <th>Pre-gap (last stow → left)</th><th>Post-gap (returned → first stow)</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </div>`;
}

// ── Modal ─────────────────────────────────────────────────────────────────────
let _mBadge = '', _mName = '', _mMgr = '';
function openModal(badge, name, manager, st) {
  _mBadge = badge; _mName = name; _mMgr = manager;
  document.getElementById('modal-title').textContent = 'Log Action — ' + name;
  document.getElementById('f-badge').value = badge;
  document.getElementById('f-name').value  = name;
  document.getElementById('f-type').value  = '';
  document.getElementById('f-note').value  = '';
  const ti = document.getElementById('modal-tta-info');
  if (ti) ti.innerHTML = (st && st !== 'good' && st !== 'unknown')
    ? `<div class="modal-tta-msg st-${st}">Status: ${st.toUpperCase()} — take action if not already done</div>` : '';
  document.getElementById('modal').classList.remove('hidden');
}

function closeModal() {
  document.getElementById('modal').classList.add('hidden');
}

async function submitAction(event) {
  event.preventDefault();
  const badge = document.getElementById('f-badge').value;
  const name  = document.getElementById('f-name').value;
  const type  = document.getElementById('f-type').value;
  const note  = document.getElementById('f-note').value;
  const am    = document.getElementById('f-am').value;
  if (!type) { toast('Please select an action type', true); return; }
  const r = await apiPost('/api/action', {
    badge, name, manager: _mMgr, action_type: type, note, am_name: am, shift: S.shift
  });
  if (r?.ok) {
    closeModal();
    toast('Action logged: ' + type);
    await loadData();
  } else {
    toast('Failed to save — server error', true);
  }
}

// ── Button handlers (called from HTML) ────────────────────────────────────────
function setLoginNeeded(needed) {
  const el = document.getElementById('login-banner');
  if (el) el.classList.toggle('hidden', !needed);
}

async function manualRefresh() {
  clearInterval(S.countdownTm);
  await apiPost('/api/refresh', {shift: S.shift});
  await loadData();
}

async function reloadStations() {
  const btn = document.getElementById('refresh-scc-btn');
  if (btn) { btn.disabled = true; btn.textContent = '⇄ Loading…'; }
  await apiPost('/api/refresh-scc', {});
  toast('Station reload started — data updates in ~2 min');
  if (btn) { btn.disabled = false; btn.textContent = '⇄ Stations'; }
  setTimeout(loadData, 5000);
}

// ── SSE ───────────────────────────────────────────────────────────────────────
function initSSE() {
  const es = new EventSource('/api/events');
  es.onmessage = e => {
    try {
      const d = JSON.parse(e.data);
      if (d.type === 'flags') {
        const p = d.payload;
        const names = (p.below||[]).slice(0,3).join(', ');
        toast(`${p.count} flagged${names ? ': '+names : ''}`, p.critical > 0);
        loadData();
      }
    } catch {}
  };
  es.onerror = () => setTimeout(initSSE, 5000);
}

// ── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Date badge
  const db = document.getElementById('date-badge');
  if (db) db.textContent = new Date().toLocaleDateString([],{weekday:'short',month:'short',day:'numeric'});

  // Auto-detect shift
  const h = new Date().getHours();
  S.shift = (h >= 18 || h < 6) ? 'night' : 'day';
  document.querySelectorAll('.sh-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.shift === S.shift);
    b.addEventListener('click', () => {
      S.shift = b.dataset.shift;
      document.querySelectorAll('.sh-btn').forEach(x =>
        x.classList.toggle('active', x.dataset.shift === S.shift));
      apiPost('/api/set-shift', {shift: S.shift});
      loadData();
    });
  });

  // Floor filter (client-side, no re-fetch)
  document.querySelectorAll('.fl-btn').forEach(b => {
    b.addEventListener('click', () => {
      S.floor = b.dataset.floor;
      document.querySelectorAll('.fl-btn').forEach(x =>
        x.classList.toggle('active', x.dataset.floor === S.floor));
      renderFloor();
    });
  });

  // Tabs
  document.querySelectorAll('.tab-btn').forEach(b =>
    b.addEventListener('click', () => switchTab(b.dataset.tab)));

  // Modal backdrop + ESC
  document.getElementById('modal')?.addEventListener('click', e => {
    if (e.target.id === 'modal') closeModal();
  });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

  initSSE();
  loadData();
});
