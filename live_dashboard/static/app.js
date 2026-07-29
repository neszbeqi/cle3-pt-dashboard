// CLE3 Live Dashboard — app.js

const API = '';
let state = {
  associates: [], ams: [], eti: [], andons: [],
  newHires: [], expiringFeedbacks: [], barrierPatterns: [],
  notifications: [], unreadCount: 0,
  currentShift: 'night', selectedAssociate: null,
  drawerOpen: false, activeTab: 'floor',
  refreshInterval: null, lastRefresh: null,
};

function fmt(n,d=1){if(n==null||isNaN(n))return'–';return Number(n).toFixed(d)+'%';}
function fmtDelta(n){if(n==null||isNaN(n))return'';const s=n>=0?'+':'';return s+Number(n).toFixed(1)+'%';}
function ptClass(pt){if(pt==null)return'pt-unknown';if(pt<75)return'pt-red';if(pt<80)return'pt-orange';if(pt<84)return'pt-yellow';return'pt-green';}
function trendArrow(d){if(d==null)return'';if(d>1)return'<span class="arrow up">▲</span>';if(d<-1)return'<span class="arrow down">▼</span>';return'<span class="arrow flat">►</span>';}
function chipHtml(l,c){return`<span class="chip ${c}">${l}</span>`;}
function escHtml(s){if(!s)return'';return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
function timeAgo(ts){if(!ts)return'';const d=Math.floor((Date.now()-new Date(ts).getTime())/1000);if(d<60)return d+'s ago';if(d<3600)return Math.floor(d/60)+'m ago';return Math.floor(d/3600)+'h ago';}

async function apiFetch(path,opts={}){
  try{const r=await fetch(API+path,opts);if(!r.ok)throw new Error(r.status);return await r.json();}
  catch(e){console.error('API',path,e);return null;}
}
async function apiPost(path,body){
  return apiFetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
}

async function loadAll(){
  setStatus('Refreshing…');
  const[assocs,eti,andons,expiring,patterns]=await Promise.all([
    apiFetch('/api/associates'),apiFetch('/api/eti'),apiFetch('/api/andons'),
    apiFetch('/api/expiring-feedbacks'),apiFetch('/api/barrier-patterns'),
  ]);
  if(assocs){state.associates=assocs.associates||[];state.ams=assocs.ams||[];state.newHires=assocs.new_hires||[];}
  if(eti)state.eti=eti.data||[];
  if(andons)state.andons=andons.andons||[];
  if(expiring)state.expiringFeedbacks=expiring.feedbacks||[];
  if(patterns)state.barrierPatterns=patterns.patterns||[];
  state.lastRefresh=new Date();
  setStatus('Updated: '+state.lastRefresh.toLocaleTimeString());
  renderAll();
}
function setStatus(msg){const e=document.getElementById('status-text');if(e)e.textContent=msg;}

function initSSE(){
  const es=new EventSource('/api/events');
  es.onmessage=(e)=>{
    const d=JSON.parse(e.data);
    if(d.type==='notification'){state.notifications.unshift(d);state.unreadCount++;updateBell();showToast(d.message,d.level||'info');}
    else if(d.type==='refresh')loadAll();
  };
  es.onerror=()=>setTimeout(initSSE,5000);
}

function updateBell(){
  const b=document.getElementById('notif-badge');if(!b)return;
  if(state.unreadCount>0){b.textContent=state.unreadCount;b.style.display='inline-block';}
  else b.style.display='none';
}
function toggleNotifPanel(){
  state.unreadCount=0;updateBell();
  const p=document.getElementById('notif-panel');if(!p)return;
  if(p.classList.contains('open')){p.classList.remove('open');return;}
  p.innerHTML=state.notifications.length===0?'<div class="notif-empty">No notifications</div>':
    state.notifications.slice(0,20).map(n=>`<div class="notif-item ${n.level||'info'}"><span class="notif-msg">${escHtml(n.message)}</span><span class="notif-time">${timeAgo(n.ts)}</span></div>`).join('');
  p.classList.add('open');
}

function showToast(msg,level='info'){
  const w=document.getElementById('toast-wrap');if(!w)return;
  const d=document.createElement('div');d.className=`toast toast-${level}`;d.textContent=msg;
  w.appendChild(d);setTimeout(()=>d.classList.add('show'),50);
  setTimeout(()=>{d.classList.remove('show');setTimeout(()=>d.remove(),400);},4000);
}

function renderExpiryBanner(){
  const b=document.getElementById('expiry-banner');if(!b)return;
  if(!state.expiringFeedbacks.length){b.style.display='none';return;}
  b.style.display='flex';
  b.innerHTML=`<span class="banner-icon">⚠</span><span><strong>${state.expiringFeedbacks.length} feedback(s) expiring within 7 days:</strong> `+
    state.expiringFeedbacks.map(f=>`${escHtml(f.associate_name)} (${escHtml(f.type)} — ${escHtml(f.expires_on)})`).join(', ')+
    `</span><button class="banner-close" onclick="document.getElementById('expiry-banner').style.display='none'">✕</button>`;
}

function renderFloor(){
  const el=document.getElementById('floor-content');if(!el)return;
  if(!state.ams.length){el.innerHTML='<div class="empty-state">No data yet — loading…</div>';return;}
  const sorted=[...state.ams].sort((a,b)=>(a.avg_pt||100)-(b.avg_pt||100));
  el.innerHTML=sorted.map(am=>renderAMBlock(am)).join('');
}
function renderAMBlock(am){
  const assocs=state.associates.filter(a=>a.manager===am.name);
  const avg=am.avg_pt!=null?am.avg_pt.toFixed(1):'–';
  return`<div class="am-block">
    <div class="am-header ${am.avg_pt!=null?ptClass(am.avg_pt):''}">
      <span class="am-name">${escHtml(am.name)}</span>
      <span class="am-pt">${avg}%</span>
      <span class="am-count">${assocs.length} associates</span>
    </div>
    <div class="assoc-list">
      ${assocs.sort((a,b)=>(a.pt_pct||100)-(b.pt_pct||100)).map(a=>renderAssocRow(a)).join('')}
    </div>
  </div>`;
}
function renderAssocRow(a){
  const pt=a.pt_pct,cls=ptClass(pt),bar=pt!=null?Math.min(100,Math.max(0,pt)):0;
  const isNew=state.newHires.some(n=>n.employee_id===a.employee_id);
  const flags=a.flags||[];
  let chips='';
  if(isNew)chips+=chipHtml('NEW','chip-new');
  if(a.handoff_note)chips+=chipHtml('📋','chip-handoff');
  flags.forEach(f=>{
    if(f==='low_pt')chips+=chipHtml('LOW PT','chip-red');
    else if(f==='idle_gaps')chips+=chipHtml('IDLE','chip-orange');
    else if(f==='black_bar')chips+=chipHtml('BLACK BAR','chip-black');
    else if(f==='pattern')chips+=chipHtml('PATTERN','chip-purple');
    else chips+=chipHtml(f,'chip-default');
  });
  return`<div class="assoc-row${flags.length?' has-flags':''}" onclick="openDrawer('${escHtml(a.employee_id)}')">
    <div class="assoc-main"><span class="assoc-name">${escHtml(a.name)}</span><span class="assoc-id">${escHtml(a.employee_id)}</span></div>
    <div class="assoc-pt-wrap"><div class="pt-bar-bg"><div class="pt-bar ${cls}" style="width:${bar}%"></div></div>
    <span class="assoc-pt ${cls}">${fmt(pt)}</span>${trendArrow(a.projected_delta)}</div>
    <div class="assoc-chips">${chips}</div>
  </div>`;
}

async function openDrawer(employeeId){
  const assoc=state.associates.find(a=>a.employee_id===employeeId);if(!assoc)return;
  state.selectedAssociate=assoc;state.drawerOpen=true;
  document.getElementById('drawer').classList.add('open');
  document.getElementById('drawer-overlay').classList.add('open');
  await renderDrawer(assoc);
}
function closeDrawer(){
  state.drawerOpen=false;state.selectedAssociate=null;
  document.getElementById('drawer').classList.remove('open');
  document.getElementById('drawer-overlay').classList.remove('open');
}
async function renderDrawer(assoc){
  const drawer=document.getElementById('drawer-body');if(!drawer)return;
  drawer.innerHTML='<div class="drawer-loading">Loading…</div>';
  const[detail,feedback,barriers,actions]=await Promise.all([
    apiFetch(`/api/associate/${encodeURIComponent(assoc.employee_id)}`),
    apiFetch(`/api/feedback/${encodeURIComponent(assoc.employee_id)}`),
    apiFetch(`/api/barriers/${encodeURIComponent(assoc.employee_id)}`),
    apiFetch(`/api/actions/${encodeURIComponent(assoc.employee_id)}`),
  ]);
  const d=detail||assoc;
  const feedbacks=feedback?.feedbacks||[];
  const barrierList=barriers?.barriers||[];
  const actionList=actions?.actions||[];
  const flags=d.flags||[];
  const momentum=d.momentum||[];
  const patterns=d.patterns||[];
  const andons=state.andons.filter(an=>an.employee_id===assoc.employee_id);
  const isNew=state.newHires.some(n=>n.employee_id===assoc.employee_id);
  let nextAction='';
  if(flags.length){const r=await apiFetch(`/api/next-action/${encodeURIComponent(assoc.employee_id)}`);nextAction=r?.action||'';}

  drawer.innerHTML=`
  <div class="drawer-header">
    <div><div class="drawer-name">${escHtml(d.name)} ${isNew?chipHtml('NEW HIRE','chip-new'):''}</div>
    <div class="drawer-sub">${escHtml(d.employee_id)} · ${escHtml(d.manager)}</div></div>
    <div class="drawer-pt-big ${ptClass(d.pt_pct)}">${fmt(d.pt_pct)}</div>
  </div>
  ${nextAction?`<div class="next-action-box"><span class="na-label">NEXT ACTION</span>${escHtml(nextAction)}</div>`:''}
  <div class="drawer-section"><div class="section-title">Projection</div>
    <div class="projection-row">
      <span>Current: <strong>${fmt(d.pt_pct)}</strong></span>
      <span>Projected EOD: <strong class="${ptClass(d.projected_pt)}">${fmt(d.projected_pt)}</strong></span>
      <span class="delta">${fmtDelta(d.projected_delta)}</span>
    </div>
  </div>
  ${momentum.length?`<div class="drawer-section"><div class="section-title">Momentum (2h windows)</div>
    <div class="momentum-list">${momentum.map(m=>`<div class="momentum-item"><span>${escHtml(m.window)}</span><span class="${ptClass(m.pt)}">${fmt(m.pt)}</span></div>`).join('')}</div></div>`:''}
  ${flags.length?`<div class="drawer-section"><div class="section-title">Active Flags</div>
    <div class="flags-list">${flags.map(f=>`<div class="flag-item">${escHtml(f)}</div>`).join('')}</div></div>`:''}
  ${patterns.length?`<div class="drawer-section"><div class="section-title">Detected Patterns</div>
    ${patterns.map(p=>`<div class="pattern-item"><span class="pattern-label">${escHtml(p.label||p)}</span><span class="pattern-desc">${escHtml(p.description||'')}</span></div>`).join('')}</div>`:''}
  ${andons.length?`<div class="drawer-section"><div class="section-title">Active Andons</div>
    ${andons.map(an=>`<div class="andon-item ${an.severity||''}">${escHtml(an.description)} <span class="andon-time">${timeAgo(an.ts)}</span></div>`).join('')}</div>`:''}
  <div class="drawer-section"><div class="section-title">Feedback History</div>
    ${feedbacks.length===0?'<div class="empty-small">No feedback on record</div>':
      feedbacks.map(f=>`<div class="feedback-item"><span class="fb-type">${escHtml(f.type)}</span><span class="fb-date">${escHtml(f.date)}</span><span class="fb-expires">Expires: ${escHtml(f.expires_on)}</span><span class="fb-note">${escHtml(f.note||'')}</span></div>`).join('')}
  </div>
  ${barrierList.length?`<div class="drawer-section"><div class="section-title">Barriers Logged</div>
    ${barrierList.map(b=>`<div class="barrier-item"><span class="b-type">${escHtml(b.type)}</span><span class="b-desc">${escHtml(b.description)}</span><span class="b-time">${escHtml(b.logged_at)}</span></div>`).join('')}</div>`:''}
  ${actionList.length?`<div class="drawer-section"><div class="section-title">AM Actions</div>
    ${actionList.map(a=>`<div class="action-item"><span class="a-type">${escHtml(a.type)}</span><span class="a-note">${escHtml(a.note)}</span><span class="a-time">${escHtml(a.logged_at)}</span></div>`).join('')}</div>`:''}
  ${d.handoff_note?`<div class="drawer-section"><div class="section-title">Handoff Note</div><div class="handoff-note-box">${escHtml(d.handoff_note)}</div></div>`:''}
  <div class="drawer-actions">
    <button class="btn btn-blue" onclick="openFeedbackModal('${escHtml(assoc.employee_id)}')">Log Feedback</button>
    <button class="btn btn-teal" onclick="openSTUModal('${escHtml(assoc.employee_id)}')">STU</button>
    <button class="btn btn-orange" onclick="openBarrierModal('${escHtml(assoc.employee_id)}')">Log Barrier</button>
    <button class="btn btn-purple" onclick="openCoachingPacket('${escHtml(assoc.employee_id)}')">Coaching Packet</button>
    <a class="btn btn-gray" href="https://atoz.amazon.work/engage/conversation-hub?f=NrBEHkDkH0AUCUCiBZAkgZUaANAb1AG4CGANgK4CmoAXKAC4BOloAvgLrZgDCUAaovHQBBACqooceOAAiAVS4icwfMXJLVaqLkKSs8hUs1qJIAcSEmsLPasOgh0obEXs2bIA" target="_blank">Engage</a>
    <a class="btn btn-gray" href="https://adapt-iad.amazon.com/#/employee-dashboard/${escHtml(assoc.employee_id)}" target="_blank">Adapt</a>
  </div>`;
}

function renderRankings(){
  const el=document.getElementById('rankings-content');if(!el)return;
  const sorted=[...state.associates].sort((a,b)=>(b.pt_pct||0)-(a.pt_pct||0));
  const top5=sorted.slice(0,5);
  const bottom5=sorted.slice(-5).reverse();
  const amActions=state.ams.map(am=>({name:am.name,actions:am.action_count||0,avg_pt:am.avg_pt})).sort((a,b)=>b.actions-a.actions);
  el.innerHTML=`
  <div class="rankings-grid">
    <div class="rank-card"><div class="rank-title">🏆 Top Performers</div>
      ${top5.map((a,i)=>`<div class="rank-row"><span class="rank-num">#${i+1}</span><span class="rank-name">${escHtml(a.name)}</span><span class="rank-pt ${ptClass(a.pt_pct)}">${fmt(a.pt_pct)}</span></div>`).join('')}
    </div>
    <div class="rank-card"><div class="rank-title">⚠ Needs Attention</div>
      ${bottom5.map((a,i)=>`<div class="rank-row"><span class="rank-num">${i+1}</span><span class="rank-name">${escHtml(a.name)}</span><span class="rank-pt ${ptClass(a.pt_pct)}">${fmt(a.pt_pct)}</span><button class="mini-btn" onclick="openDrawer('${escHtml(a.employee_id)}')">View</button></div>`).join('')}
    </div>
    <div class="rank-card"><div class="rank-title">📋 AM Accountability</div>
      ${amActions.map(am=>`<div class="rank-row"><span class="rank-name">${escHtml(am.name)}</span><span class="rank-pt ${ptClass(am.avg_pt)}">${fmt(am.avg_pt)} avg</span><span class="rank-actions">${am.actions} actions</span></div>`).join('')}
    </div>
    <div class="rank-card" id="would-be-card"><div class="rank-title">💡 Would-Be PT</div><div class="would-be-loading">Loading…</div></div>
  </div>
  <div class="pattern-watch-section"><div class="rank-title">🔍 Pattern Watch</div><div id="pattern-watch-list"></div></div>`;
  loadWouldBe();renderPatternWatch();
}
async function loadWouldBe(){
  const r=await apiFetch('/api/would-be-pt');
  const card=document.getElementById('would-be-card');if(!card)return;
  if(!r){card.querySelector('.would-be-loading').textContent='Failed to load';return;}
  const list=r.scenarios||[];
  card.innerHTML=`<div class="rank-title">💡 Would-Be PT</div>`+(list.length===0?'<div class="empty-small">No scenarios</div>':
    list.map(s=>`<div class="rank-row"><span class="rank-name">${escHtml(s.description)}</span><span class="rank-pt ${ptClass(s.projected_pt)}">${fmt(s.projected_pt)}</span></div>`).join(''));
}
function renderPatternWatch(){
  const el=document.getElementById('pattern-watch-list');if(!el)return;
  const pw=state.associates.filter(a=>a.patterns&&a.patterns.length).map(a=>({name:a.name,id:a.employee_id,patterns:a.patterns}));
  if(!pw.length){el.innerHTML='<div class="empty-small">No patterns detected</div>';return;}
  el.innerHTML=pw.map(a=>`<div class="pw-row" onclick="openDrawer('${escHtml(a.id)}')"><span class="pw-name">${escHtml(a.name)}</span>${a.patterns.map(p=>`<span class="chip chip-purple">${escHtml(p.label||p)}</span>`).join('')}</div>`).join('');
}

function renderETI(){
  const el=document.getElementById('eti-content');if(!el)return;
  if(!state.eti.length){el.innerHTML='<div class="empty-state">ETI/TPH data not available. Check Vantage connection.</div>';return;}
  const avgEti=state.eti.reduce((s,r)=>s+(r.eti||0),0)/state.eti.length;
  const avgTph=state.eti.reduce((s,r)=>s+(r.tph||0),0)/state.eti.length;
  const low=state.eti.filter(r=>r.eti<80);
  let sug='';
  if(avgEti<75)sug='⚠ Floor-wide ETI low — check for system slowdowns or mislabeled bins.';
  else if(low.length>state.eti.length*0.3)sug='⚠ 30%+ of associates below 80% ETI — consider path reassignment.';
  else sug='✓ ETI/TPH within normal range.';
  el.innerHTML=`
  <div class="eti-summary">
    <div class="eti-card"><div class="eti-label">Avg ETI</div><div class="eti-val">${avgEti.toFixed(1)}%</div></div>
    <div class="eti-card"><div class="eti-label">Avg TPH</div><div class="eti-val">${avgTph.toFixed(0)}</div></div>
    <div class="eti-card"><div class="eti-label">Below 80% ETI</div><div class="eti-val ${low.length>0?'text-orange':''}">${low.length}</div></div>
  </div>
  <div class="suggestion-box">${sug}</div>
  <div class="eti-table-wrap"><table class="eti-table">
    <thead><tr><th>Name</th><th>ID</th><th>ETI%</th><th>TPH</th></tr></thead>
    <tbody>${[...state.eti].sort((a,b)=>(a.eti||0)-(b.eti||0)).map(r=>`<tr class="${r.eti<80?'row-warn':''}"><td>${escHtml(r.name)}</td><td>${escHtml(r.employee_id)}</td><td class="${r.eti<80?'text-orange':'text-green'}">${r.eti!=null?r.eti.toFixed(1)+'%':'–'}</td><td>${r.tph!=null?r.tph.toFixed(0):'–'}</td></tr>`).join('')}</tbody>
  </table></div>`;
}

function openFeedbackModal(employeeId){
  const assoc=state.associates.find(a=>a.employee_id===employeeId);if(!assoc)return;
  document.getElementById('modal-title').textContent=`Log Feedback — ${assoc.name}`;
  document.getElementById('modal-body').innerHTML=`
  <form id="feedback-form">
    <input type="hidden" name="employee_id" value="${escHtml(employeeId)}">
    <label>Type<select name="type"><option>Doc Coaching</option><option>First Warning</option><option>Second Warning</option><option>Final Warning</option></select></label>
    <label>Date<input type="date" name="date" value="${new Date().toISOString().slice(0,10)}" required></label>
    <label>Note<textarea name="note" rows="3" placeholder="Context, what was discussed…"></textarea></label>
    <div class="modal-actions"><button type="submit" class="btn btn-blue">Save</button><button type="button" class="btn btn-gray" onclick="closeModal()">Cancel</button></div>
  </form>`;
  document.getElementById('feedback-form').onsubmit=async(e)=>{
    e.preventDefault();const fd=new FormData(e.target);const payload=Object.fromEntries(fd);
    const r=await apiPost('/api/feedback',payload);
    if(r?.ok){closeModal();showToast('Feedback saved','success');loadAll();}else showToast('Failed to save','error');
  };
  openModal();
}

async function openSTUModal(employeeId){
  const assoc=state.associates.find(a=>a.employee_id===employeeId);if(!assoc)return;
  document.getElementById('modal-title').textContent=`STU — ${assoc.name}`;
  document.getElementById('modal-body').innerHTML='<div class="loading">Loading template…</div>';
  openModal();
  const r=await apiFetch(`/api/stu-template/${encodeURIComponent(employeeId)}`);
  const tmpl=r?.template||`Situation: \nTask: \nUrgency: `;
  document.getElementById('modal-body').innerHTML=`
  <textarea id="stu-text" rows="10" style="width:100%;font-family:monospace">${escHtml(tmpl)}</textarea>
  <div class="modal-actions"><button class="btn btn-blue" onclick="copySTU()">Copy</button><button class="btn btn-gray" onclick="closeModal()">Close</button></div>`;
}
function copySTU(){
  const el=document.getElementById('stu-text');if(!el)return;
  navigator.clipboard.writeText(el.value).then(()=>showToast('Copied','success'));
}

function openBarrierModal(employeeId){
  const assoc=state.associates.find(a=>a.employee_id===employeeId);if(!assoc)return;
  document.getElementById('modal-title').textContent=`Log Barrier — ${assoc.name}`;
  document.getElementById('modal-body').innerHTML=`
  <form id="barrier-form">
    <input type="hidden" name="employee_id" value="${escHtml(employeeId)}">
    <label>Barrier Type<select name="type"><option>Equipment</option><option>System Down</option><option>Path Issue</option><option>Staffing</option><option>Training Gap</option><option>Other</option></select></label>
    <label>Description<textarea name="description" rows="3" required placeholder="What happened?"></textarea></label>
    <label>Action Taken<input type="text" name="action_taken" placeholder="What did you do?"></label>
    <div class="modal-actions"><button type="submit" class="btn btn-orange">Save</button><button type="button" class="btn btn-gray" onclick="closeModal()">Cancel</button></div>
  </form>`;
  document.getElementById('barrier-form').onsubmit=async(e)=>{
    e.preventDefault();const fd=new FormData(e.target);const payload=Object.fromEntries(fd);
    const r=await apiPost('/api/barrier',payload);
    if(r?.ok){closeModal();showToast('Barrier logged','success');loadAll();}else showToast('Failed to save','error');
  };
  openModal();
}

function openNewHireModal(){
  document.getElementById('modal-title').textContent='Add New Hire';
  document.getElementById('modal-body').innerHTML=`
  <form id="newhire-form">
    <label>Employee ID<input type="text" name="employee_id" required placeholder="A12345678"></label>
    <label>Start Date<input type="date" name="start_date" value="${new Date().toISOString().slice(0,10)}" required></label>
    <label>Note<input type="text" name="note" placeholder="Path, trainer, etc."></label>
    <div class="modal-actions"><button type="submit" class="btn btn-blue">Add</button><button type="button" class="btn btn-gray" onclick="closeModal()">Cancel</button></div>
  </form>`;
  document.getElementById('newhire-form').onsubmit=async(e)=>{
    e.preventDefault();const fd=new FormData(e.target);const payload=Object.fromEntries(fd);
    const r=await apiPost('/api/new-hire',payload);
    if(r?.ok){closeModal();showToast('New hire added','success');loadAll();}else showToast('Failed to save','error');
  };
  openModal();
}

async function openHandoffModal(){
  document.getElementById('modal-title').textContent='Shift Handoff';
  document.getElementById('modal-body').innerHTML='<div class="loading">Loading…</div>';
  openModal();
  const r=await apiFetch('/api/handoff-summary');
  const summary=r?.summary||'';
  document.getElementById('modal-body').innerHTML=`
  <p class="handoff-intro">Review and edit the handoff note for the incoming AM.</p>
  <textarea id="handoff-text" rows="12" style="width:100%">${escHtml(summary)}</textarea>
  <div class="modal-actions">
    <button class="btn btn-blue" onclick="saveHandoff()">Save Handoff</button>
    <button class="btn btn-teal" onclick="copyHandoff()">Copy</button>
    <button class="btn btn-gray" onclick="closeModal()">Cancel</button>
  </div>`;
}
async function saveHandoff(){
  const text=document.getElementById('handoff-text')?.value;if(!text)return;
  const r=await apiPost('/api/handoff',{note:text});
  if(r?.ok){closeModal();showToast('Handoff saved','success');}else showToast('Failed to save','error');
}
function copyHandoff(){
  const el=document.getElementById('handoff-text');if(!el)return;
  navigator.clipboard.writeText(el.value).then(()=>showToast('Copied','success'));
}

async function openCoachingPacket(employeeId){
  const assoc=state.associates.find(a=>a.employee_id===employeeId);if(!assoc)return;
  document.getElementById('modal-title').textContent=`Coaching Packet — ${assoc.name}`;
  document.getElementById('modal-body').innerHTML='<div class="loading">Generating…</div>';
  openModal();
  const[detail,feedback,barriers]=await Promise.all([
    apiFetch(`/api/associate/${encodeURIComponent(employeeId)}`),
    apiFetch(`/api/feedback/${encodeURIComponent(employeeId)}`),
    apiFetch(`/api/barriers/${encodeURIComponent(employeeId)}`),
  ]);
  const d=detail||assoc;
  const feedbacks=feedback?.feedbacks||[];
  const barrierList=barriers?.barriers||[];
  const packet=`COACHING PREP PACKET
Generated: ${new Date().toLocaleString()}
==============================
ASSOCIATE: ${d.name}
ID: ${d.employee_id}
Manager: ${d.manager}
Current PT: ${d.pt_pct!=null?d.pt_pct.toFixed(1)+'%':'–'}
Projected EOD: ${d.projected_pt!=null?d.projected_pt.toFixed(1)+'%':'–'}

FLAGS: ${(d.flags||[]).join(', ')||'None'}
PATTERNS: ${(d.patterns||[]).map(p=>p.label||p).join(', ')||'None'}

FEEDBACK HISTORY:
${feedbacks.length===0?'No feedback on record':feedbacks.map(f=>`  ${f.date} — ${f.type}${f.note?': '+f.note:''} (expires ${f.expires_on})`).join('\n')}

BARRIERS LOGGED:
${barrierList.length===0?'None':barrierList.map(b=>`  ${b.logged_at} — ${b.type}: ${b.description}`).join('\n')}

NOTES:
${d.handoff_note||''}`;
  document.getElementById('modal-body').innerHTML=`
  <pre id="packet-text" class="packet-pre">${escHtml(packet)}</pre>
  <div class="modal-actions">
    <button class="btn btn-blue" onclick="copyPacket()">Copy</button>
    <button class="btn btn-teal" onclick="printPacket()">Print</button>
    <button class="btn btn-gray" onclick="closeModal()">Close</button>
  </div>`;
}
function copyPacket(){
  const el=document.getElementById('packet-text');if(!el)return;
  navigator.clipboard.writeText(el.textContent).then(()=>showToast('Copied','success'));
}
function printPacket(){
  const el=document.getElementById('packet-text');if(!el)return;
  const w=window.open('','_blank');
  w.document.write(`<pre style="font-family:monospace;font-size:12px;padding:20px">${el.innerHTML}</pre>`);
  w.document.close();w.print();
}

function openBarrierPatterns(){
  document.getElementById('modal-title').textContent='Systemic Barrier Patterns';
  const patterns=state.barrierPatterns;
  document.getElementById('modal-body').innerHTML=patterns.length===0
    ?'<div class="empty-state">No systemic patterns detected.</div>'
    :patterns.map(p=>`<div class="barrier-pattern-item"><div class="bp-type">${escHtml(p.type)}</div><div class="bp-count">${p.count} occurrences</div><div class="bp-associates">${escHtml((p.associates||[]).join(', '))}</div></div>`).join('');
  openModal();
}

function openModal(){document.getElementById('modal-overlay').classList.add('open');document.getElementById('modal-box').classList.add('open');}
function closeModal(){document.getElementById('modal-overlay').classList.remove('open');document.getElementById('modal-box').classList.remove('open');}

function setShift(shift){
  state.currentShift=shift;
  document.querySelectorAll('.shift-btn').forEach(b=>b.classList.toggle('active',b.dataset.shift===shift));
  apiFetch(`/api/set-shift?shift=${shift}`).then(()=>loadAll());
}

function switchTab(tab){
  state.activeTab=tab;
  document.querySelectorAll('.tab-btn').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));
  document.querySelectorAll('.tab-pane').forEach(p=>p.style.display=p.id===tab+'-pane'?'block':'none');
  if(tab==='floor')renderFloor();
  else if(tab==='rankings')renderRankings();
  else if(tab==='eti')renderETI();
}

function renderAll(){
  renderExpiryBanner();
  if(state.activeTab==='floor')renderFloor();
  else if(state.activeTab==='rankings')renderRankings();
  else if(state.activeTab==='eti')renderETI();
  if(state.drawerOpen&&state.selectedAssociate){
    const fresh=state.associates.find(a=>a.employee_id===state.selectedAssociate.employee_id);
    if(fresh)renderDrawer(fresh);
  }
}

function startAutoRefresh(){
  if(state.refreshInterval)clearInterval(state.refreshInterval);
  state.refreshInterval=setInterval(loadAll,3*60*1000);
}

function handleSearch(e){
  const q=e.target.value.trim().toLowerCase();
  document.querySelectorAll('.assoc-row').forEach(row=>{
    row.style.display=row.textContent.toLowerCase().includes(q)?'':'none';
  });
}

document.addEventListener('DOMContentLoaded',()=>{
  document.querySelectorAll('.shift-btn').forEach(b=>b.addEventListener('click',()=>setShift(b.dataset.shift)));
  document.querySelectorAll('.tab-btn').forEach(b=>b.addEventListener('click',()=>switchTab(b.dataset.tab)));
  const bell=document.getElementById('bell-btn');if(bell)bell.addEventListener('click',toggleNotifPanel);
  const overlay=document.getElementById('drawer-overlay');if(overlay)overlay.addEventListener('click',closeDrawer);
  const mOverlay=document.getElementById('modal-overlay');if(mOverlay)mOverlay.addEventListener('click',closeModal);
  const search=document.getElementById('search-input');if(search)search.addEventListener('input',handleSearch);
  const nhBtn=document.getElementById('new-hire-btn');if(nhBtn)nhBtn.addEventListener('click',openNewHireModal);
  const hoBtn=document.getElementById('handoff-btn');if(hoBtn)hoBtn.addEventListener('click',openHandoffModal);
  const bpBtn=document.getElementById('barrier-patterns-btn');if(bpBtn)bpBtn.addEventListener('click',openBarrierPatterns);
  const refBtn=document.getElementById('refresh-btn');if(refBtn)refBtn.addEventListener('click',loadAll);
  const h=new Date().getHours();
  state.currentShift=(h>=18||h<6)?'night':'day';
  document.querySelectorAll('.shift-btn').forEach(b=>b.classList.toggle('active',b.dataset.shift===state.currentShift));
  initSSE();
  loadAll();
  startAutoRefresh();
});
