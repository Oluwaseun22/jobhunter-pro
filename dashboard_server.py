"""
JobHunter Pro - Dashboard Server
Run: python3 dashboard_server.py
Open: http://0.0.0.0:4000
"""
import json, os, threading
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

LOG_FILE      = "job_hunter_log.json"
CV_DIR        = "tailored_cvs"
SETTINGS_FILE = "dashboard_settings.json"

def load_data():
    if Path(LOG_FILE).exists():
        with open(LOG_FILE) as f: return json.load(f)
    return {"seen": [], "applied": []}

def save_data(data):
    with open(LOG_FILE, "w") as f: json.dump(data, f, indent=2)

def load_settings():
    d = {"email_alerts":True,"auto_scan":True,"scan_interval":20,"min_match_score":40,
         "job_titles":["Data Analyst","Junior Data Analyst","Graduate Data Analyst",
                       "IT Analyst","IT Support Analyst","Business Analyst",
                       "Junior Business Analyst","Operations Analyst","Data Analyst Trainee","IT Graduate"]}
    if Path(SETTINGS_FILE).exists():
        with open(SETTINGS_FILE) as f: d.update(json.load(f))
    return d

def save_settings(s):
    with open(SETTINGS_FILE,"w") as f: json.dump(s,f,indent=2)

def get_stats(data):
    jobs = data.get("seen",[])
    applied = [j for j in jobs if j.get("applied")]
    scores = [j.get("score",0) for j in jobs if j.get("score")]
    avg = round(sum(scores)/len(scores)) if scores else 0
    return {"total":len(jobs),"applied":len(applied),"avg_score":avg,
            "cvs":len(list(Path(CV_DIR).glob("*.pdf"))) if Path(CV_DIR).exists() else 0}

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>JobHunter Pro</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Fraunces:ital,wght@0,300;0,700;0,900&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--ink:#0f0f0f;--paper:#f7f5f0;--warm:#ede9e0;--border:#d4cfc4;
  --green:#1a5c38;--red:#c0392b;--orange:#b7791f;--blue:#1e3a8a;
  --mono:'DM Mono',monospace;--serif:'Fraunces',serif}
body{background:var(--paper);color:var(--ink);font-family:var(--mono);min-height:100vh}
header{background:var(--ink);color:#f7f5f0;padding:20px 40px;display:flex;align-items:center;justify-content:space-between}
.logo h1{font-family:var(--serif);font-size:24px;font-weight:900}
.logo span{font-size:10px;opacity:.5;letter-spacing:2px;text-transform:uppercase;margin-left:12px}
.hright{display:flex;align-items:center;gap:14px}
.live{display:flex;align-items:center;gap:8px;font-size:11px;letter-spacing:1px;text-transform:uppercase}
.dot{width:7px;height:7px;border-radius:50%;background:#4ade80;animation:pulse 2s infinite;box-shadow:0 0 8px #4ade80}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.sbtn{background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.2);color:#f7f5f0;
  padding:6px 14px;font-family:var(--mono);font-size:11px;letter-spacing:1px;cursor:pointer}
.sbtn:hover{background:rgba(255,255,255,.2)}
.main{max-width:1200px;margin:0 auto;padding:32px}
.notif{background:var(--ink);color:#f7f5f0;padding:10px 20px;font-size:11px;
  display:none;align-items:center;justify-content:space-between;margin-bottom:20px;border-radius:4px}
.notif.show{display:flex}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--border);
  border:1px solid var(--border);margin-bottom:28px}
.stat{background:var(--paper);padding:22px}
.stat-n{font-family:var(--serif);font-size:42px;font-weight:900;line-height:1;margin-bottom:4px}
.stat-l{font-size:10px;letter-spacing:2px;text-transform:uppercase;opacity:.5}
.stat.g .stat-n{color:var(--green)}.stat.r .stat-n{color:var(--red)}
.settings-panel{display:none;background:var(--warm);border:1px solid var(--border);padding:24px;margin-bottom:24px}
.settings-panel.open{display:block}
.sg{display:grid;grid-template-columns:repeat(3,1fr);gap:24px}
.sl{font-size:9px;letter-spacing:2px;text-transform:uppercase;opacity:.6;margin-bottom:8px;display:block}
.si{width:100%;background:var(--paper);border:1px solid var(--border);padding:8px 12px;
  font-family:var(--mono);font-size:12px;color:var(--ink);outline:none}
.tr{display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border)}
.tr:last-child{border-bottom:none}
.tl{font-size:12px}.ts{font-size:10px;opacity:.5;margin-top:2px}
.tog{width:40px;height:22px;background:var(--border);border-radius:100px;position:relative;cursor:pointer;transition:background .3s;flex-shrink:0}
.tog.on{background:var(--ink)}
.tog::after{content:'';position:absolute;width:16px;height:16px;background:white;border-radius:50%;top:3px;left:3px;transition:transform .3s;box-shadow:0 1px 3px rgba(0,0,0,.3)}
.tog.on::after{transform:translateX(18px)}
.tags-wrap{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.tpill{font-size:10px;padding:4px 10px;border:1px solid var(--border);background:var(--paper);display:flex;align-items:center;gap:6px}
.tremove{opacity:.4;cursor:pointer;font-size:12px}.tremove:hover{opacity:1;color:var(--red)}
.ctrl{display:flex;align-items:center;justify-content:space-between;margin-bottom:18px;flex-wrap:wrap;gap:12px}
.ctrl h2{font-family:var(--serif);font-size:20px;font-weight:700;font-style:italic}
.btns{display:flex;gap:7px;flex-wrap:wrap}
.btn{font-family:var(--mono);font-size:11px;letter-spacing:1px;text-transform:uppercase;
  padding:7px 13px;border:1px solid var(--ink);background:transparent;cursor:pointer;transition:all .15s}
.btn:hover,.btn.active{background:var(--ink);color:var(--paper)}
.btn.pri{background:var(--ink);color:var(--paper)}.btn.pri:hover{background:#333}
.sbar{background:var(--ink);color:#f7f5f0;padding:10px 18px;font-size:11px;display:none;align-items:center;gap:10px;margin-bottom:14px}
.sbar.show{display:flex}
.spin{animation:spin 1s linear infinite;display:inline-block}
@keyframes spin{to{transform:rotate(360deg)}}
.rbar{background:var(--ink);color:#f7f5f0;padding:14px 18px;margin-bottom:14px;display:none}
.rbar.show{display:block}
.rpb{height:3px;background:rgba(255,255,255,.2);margin-top:8px;border-radius:2px}
.rpf{height:100%;background:#4ade80;border-radius:2px;transition:width .5s;width:0%}
.rpt{font-size:10px;opacity:.6;margin-top:5px}
.jtable{border:1px solid var(--border);background:var(--paper)}
.jh{display:grid;grid-template-columns:2fr 1.2fr 0.6fr 0.7fr 0.7fr 1.1fr;
  padding:10px 18px;background:var(--warm);border-bottom:1px solid var(--border);
  font-size:9px;letter-spacing:2px;text-transform:uppercase;opacity:.6;gap:10px}
.jr{display:grid;grid-template-columns:2fr 1.2fr 0.6fr 0.7fr 0.7fr 1.1fr;
  padding:14px 18px;border-bottom:1px solid var(--border);align-items:center;gap:10px;transition:background .1s}
.jr:hover{background:var(--warm)}.jr.applied{opacity:.55}.jr.hidden{display:none}
.jtitle{font-weight:500;font-size:13px;margin-bottom:2px;cursor:pointer}.jtitle:hover{text-decoration:underline}
.jmeta{font-size:10px;opacity:.5}.jco{font-size:12px;opacity:.8}
.sb{display:flex;align-items:center;gap:6px}
.sn{font-family:var(--serif);font-size:14px;font-weight:700;min-width:32px}
.st{flex:1;height:3px;background:var(--border);border-radius:2px}
.sf{height:100%;border-radius:2px;background:var(--ink)}.sf.h{background:var(--green)}.sf.m{background:var(--orange)}
.tag{font-size:9px;letter-spacing:1px;text-transform:uppercase;padding:3px 7px;border:1px solid var(--border);display:inline-block}
.tag.new{border-color:var(--green);color:var(--green)}.tag.applied{border-color:var(--ink);background:var(--ink);color:#f7f5f0}
.tag.indeed{border-color:var(--blue);color:var(--blue)}.tag.reed{border-color:var(--orange);color:var(--orange)}
.ja{display:flex;gap:4px;flex-wrap:wrap}
.ab{font-family:var(--mono);font-size:9px;letter-spacing:.5px;text-transform:uppercase;
  padding:5px 7px;border:1px solid var(--border);background:transparent;cursor:pointer;
  text-decoration:none;color:var(--ink);transition:all .15s;white-space:nowrap}
.ab:hover{background:var(--ink);color:#f7f5f0;border-color:var(--ink)}
.ab.ap:hover{background:var(--green);border-color:var(--green);color:white}
.ab.rt:hover{background:var(--blue);border-color:var(--blue);color:white}
.ab.hd:hover{background:var(--red);border-color:var(--red);color:white}
.empty{padding:60px;text-align:center;opacity:.4}
.mbg{display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:100;align-items:center;justify-content:center}
.mbg.open{display:flex}
.modal{background:var(--paper);border:1px solid var(--border);max-width:580px;width:90%;max-height:85vh;overflow-y:auto}
.mh{padding:18px 22px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:start}
.mt{font-family:var(--serif);font-size:17px;font-weight:700}
.mc{background:none;border:none;font-size:17px;cursor:pointer;opacity:.4}
.mb{padding:22px}
.mf{margin-bottom:12px}
.ml{font-size:9px;letter-spacing:2px;text-transform:uppercase;opacity:.5;margin-bottom:4px}
.mv{font-size:13px;line-height:1.6}
.ni{width:100%;background:var(--warm);border:1px solid var(--border);padding:10px;
  font-family:var(--mono);font-size:12px;color:var(--ink);outline:none;resize:vertical;min-height:80px}
.ma{padding:18px 22px;border-top:1px solid var(--border);display:flex;gap:7px;flex-wrap:wrap}
footer{text-align:center;padding:28px;font-size:10px;opacity:.3;letter-spacing:1px;text-transform:uppercase}

@media (max-width: 768px) {
  header{padding:14px 16px}
  .logo h1{font-size:18px}
  .main{padding:16px}
  .stats{grid-template-columns:repeat(2,1fr)}
  .stat{padding:14px}
  .stat-n{font-size:32px}
  .jh{display:none}
  .jr{grid-template-columns:1fr;gap:6px;padding:14px 16px}
  .jr > div:nth-child(3){display:none}
  .sn{font-size:12px}
  .score-track{display:none}
  .ja{flex-wrap:wrap}
  .ab{font-size:9px;padding:5px 7px}
  .ctrl{flex-direction:column;align-items:flex-start;gap:10px}
  .btns{flex-wrap:wrap}
  .btn{font-size:10px;padding:6px 10px}
  .sg{grid-template-columns:1fr}
  .settings-panel{padding:16px}
  .modal{width:95%;margin:10px}
  .ma{flex-wrap:wrap}
}
@media (max-width: 480px) {
  .stats{grid-template-columns:repeat(2,1fr)}
  .stat-n{font-size:28px}
  .logo h1{font-size:16px}
}
</style>
</head>
<body>
<header>
  <div class="logo">
    <h1>JobHunter Pro<span>Segun's Dashboard · Scotland</span></h1>
  </div>
  <div class="hright">
    <div class="live"><div class="dot"></div>System Active</div>
    <button class="sbtn" onclick="toggleSettings()">⚙ Settings</button>
  </div>
</header>
<div class="main">
  <div class="notif" id="notif"><span id="notif-text"></span><button onclick="document.getElementById('notif').classList.remove('show')" style="background:none;border:none;color:#f7f5f0;cursor:pointer;font-size:16px">✕</button></div>
  <div class="stats">
    <div class="stat"><div class="stat-n" id="s1">—</div><div class="stat-l">Jobs Found</div></div>
    <div class="stat g"><div class="stat-n" id="s2">—</div><div class="stat-l">CVs Generated</div></div>
    <div class="stat"><div class="stat-n" id="s3">—</div><div class="stat-l">Avg Match %</div></div>
    <div class="stat r"><div class="stat-n" id="s4">—</div><div class="stat-l">Applied</div></div>
  </div>
  <div class="settings-panel" id="sp">
    <div class="sg">
      <div>
        <span class="sl">Toggles</span>
        <div class="tr"><div><div class="tl">Email Alerts</div><div class="ts">Send CV to your inbox</div></div><div class="tog" id="te" onclick="this.classList.toggle('on');settings.email_alerts=this.classList.contains('on')"></div></div>
        <div class="tr"><div><div class="tl">Auto Scan</div><div class="ts">Scan automatically</div></div><div class="tog" id="ta" onclick="this.classList.toggle('on');settings.auto_scan=this.classList.contains('on')"></div></div>
        <div class="tr"><div><div class="tl">Browser Notifications</div><div class="ts">Alert on new jobs</div></div><div class="tog" id="tn" onclick="toggleNotif(this)"></div></div>
      </div>
      <div>
        <span class="sl">Thresholds</span>
        <div style="margin-bottom:14px"><div class="sl">Min Match Score</div><input class="si" type="number" id="sc" min="0" max="100" value="40"></div>
        <div><div class="sl">Scan Interval (minutes)</div><input class="si" type="number" id="si" min="5" max="60" value="20"></div>
      </div>
      <div>
        <span class="sl">Job Titles</span>
        <div class="tags-wrap" id="tt"></div>
        <div style="display:flex;gap:6px;margin-top:10px">
          <input class="si" id="ni" placeholder="Add job title..." style="flex:1">
          <button class="btn pri" onclick="addTitle()" style="padding:7px 11px">+</button>
        </div>
      </div>
    </div>
    <button class="btn pri" onclick="saveSettings()" style="margin-top:18px;width:100%">💾 Save Settings</button>
  </div>
  <div class="ctrl">
    <h2>Live Job Feed</h2>
    <div class="btns">
      <button class="btn active" onclick="filter('all',this)">All</button>
      <button class="btn" onclick="filter('high',this)">High Match</button>
      <button class="btn" onclick="filter('applied',this)">Applied</button>
      <button class="btn" onclick="filter('reed',this)">Reed</button>
      <button class="btn" onclick="filter('indeed',this)">Indeed</button>
      <button class="btn pri" onclick="scan()">↻ Scan Now</button>
    </div>
  </div>
  <div class="sbar" id="sb"><span class="spin">⟳</span><span id="sm">Scanning Reed + Indeed...</span></div>
  <div class="rbar" id="rb"><div style="font-size:11px;letter-spacing:1px">✨ RE-TAILORING CV...</div><div class="rpb"><div class="rpf" id="rf"></div></div><div class="rpt" id="rt">Starting...</div></div>
  <div class="jtable">
    <div class="jh"><div>Role</div><div>Company</div><div>Source</div><div>Match</div><div>Status</div><div>Actions</div></div>
    <div id="jl"><div class="empty">Loading...</div></div>
  </div>
</div>
<footer>JobHunter Pro · 0.0.0.0:4000 · Auto-scans every 20 min · github.com/Oluwaseun22/jobhunter-pro</footer>
<div class="mbg" id="modal">
  <div class="modal">
    <div class="mh"><div><div class="mt" id="mt">—</div><div style="font-size:11px;opacity:.5;margin-top:3px" id="mc2">—</div></div><button class="mc" onclick="closeModal()">✕</button></div>
    <div class="mb">
      <div class="mf"><div class="ml">Match Score</div><div class="mv" id="ms">—</div></div>
      <div class="mf"><div class="ml">Source</div><div class="mv" id="msrc">—</div></div>
      <div class="mf"><div class="ml">Scanned</div><div class="mv" id="md">—</div></div>
      <div class="mf"><div class="ml">CV File</div><div class="mv" id="mpdf">—</div></div>
      <div class="mf"><div class="ml">Notes</div><textarea class="ni" id="mn" placeholder="Add notes..."></textarea></div>
    </div>
    <div class="ma">
      <a class="ab ap" id="ma" href="#" target="_blank">✓ Apply</a>
      <button class="ab" id="mcv" onclick="openCV()">📄 CV</button>
      <button class="ab rt" onclick="retailor()">✨ Re-tailor</button>
      <button class="ab" onclick="markApplied()">✅ Applied</button>
      <button class="ab hd" onclick="hideJob()">🗑 Hide</button>
      <button class="ab" onclick="saveNotes()">💾 Notes</button>
      <button class="ab" onclick="closeModal()">Close</button>
    </div>
  </div>
</div>
<script>
let jobs=[], settings={}, cur=-1, notifOn=false;

async function load() {
  try {
    const [jr, sr] = await Promise.all([fetch('/api/jobs'), fetch('/api/settings')]);
    const jd = await jr.json(); settings = await sr.json();
    jobs = jd.jobs || [];
    document.getElementById('s1').textContent = jd.stats.total || 0;
    document.getElementById('s2').textContent = jd.stats.cvs   || 0;
    document.getElementById('s3').textContent = (jd.stats.avg_score||0)+'%';
    document.getElementById('s4').textContent = jd.stats.applied || 0;
    renderJobs(jobs); applySettings();
  } catch(e) { document.getElementById('jl').innerHTML='<div class="empty">Could not load data. Make sure job_hunter.py has run at least once.</div>'; }
}

function renderJobs(list) {
  const el = document.getElementById('jl');
  if (!list.length) { el.innerHTML='<div class="empty">No jobs match filter. Click Scan Now.</div>'; return; }
  el.innerHTML = list.map((j,i)=>{
    const sc=j.score||0, cls=sc>=80?'h':sc>=60?'m':'', src=j.source||'reed';
    const dt=j.scanned?new Date(j.scanned).toLocaleDateString('en-GB',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}):'—';
    return `<div class="jr ${j.applied?'applied':''} ${j.hidden?'hidden':''}" id="r${i}">
      <div><div class="jtitle" onclick="showModal(${i})">${j.title}</div><div class="jmeta">${dt}${j.notes?' · 📝':''}</div></div>
      <div class="jco">${j.company}</div>
      <div><span class="tag ${src}">${src}</span></div>
      <div class="sb"><span class="sn">${sc}%</span><div class="st"><div class="sf ${cls}" style="width:${Math.min(100,sc)}%"></div></div></div>
      <div><span class="tag ${j.applied?'applied':'new'}">${j.applied?'Applied':'New'}</span></div>
      <div class="ja" onclick="event.stopPropagation()">
        <a class="ab ap" href="${j.url||'#'}" target="_blank" onclick="qApply(${i})">Apply</a>
        ${j.pdf?`<a class="ab" href="/cv/${encodeURIComponent(j.pdf.split('/').pop())}" target="_blank">CV</a>`:''}
        <button class="ab rt" onclick="qRetailor(${i})">✨</button>
        <button class="ab hd" onclick="qHide(${i})">✕</button>
      </div>
    </div>`;
  }).join('');
}

function filter(t, btn) {
  document.querySelectorAll('.btns .btn:not(.pri)').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  let f = jobs.filter(j=>!j.hidden);
  if(t==='high') f=f.filter(j=>(j.score||0)>=75);
  if(t==='applied') f=f.filter(j=>j.applied);
  if(t==='reed') f=f.filter(j=>j.source==='reed');
  if(t==='indeed') f=f.filter(j=>j.source==='indeed');
  renderJobs(f);
}

function showModal(i) {
  cur=i; const j=jobs[i];
  document.getElementById('mt').textContent   = j.title;
  document.getElementById('mc2').textContent  = `${j.company} · ${j.location||'Scotland'}`;
  document.getElementById('ms').textContent   = (j.score||'—')+'%';
  document.getElementById('msrc').textContent = (j.source||'reed').toUpperCase();
  document.getElementById('md').textContent   = j.scanned?new Date(j.scanned).toLocaleString('en-GB'):'—';
  document.getElementById('mpdf').textContent = j.pdf?j.pdf.split('/').pop():'Not generated';
  document.getElementById('mn').value         = j.notes||'';
  document.getElementById('ma').href          = j.url||'#';
  document.getElementById('mcv').dataset.pdf  = j.pdf||'';
  document.getElementById('modal').classList.add('open');
}
function closeModal(){document.getElementById('modal').classList.remove('open')}
function openCV(){const p=document.getElementById('mcv').dataset.pdf;if(p)window.open('/cv/'+encodeURIComponent(p.split('/').pop()),'_blank')}

async function upd(i,d){await fetch('/api/update-job',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({index:i,...d})})}
async function saveNotes(){if(cur<0)return;const n=document.getElementById('mn').value;await upd(cur,{notes:n});jobs[cur].notes=n;notify('📝 Notes saved');renderJobs(jobs.filter(j=>!j.hidden))}
async function markApplied(){if(cur<0)return;await upd(cur,{applied:true});jobs[cur].applied=true;notify('✅ Marked Applied!');closeModal();load()}
async function qApply(i){await upd(i,{applied:true});jobs[i].applied=true}
async function qHide(i){await upd(i,{hidden:true});document.getElementById('r'+i).classList.add('hidden');notify('🗑 Hidden')}
async function hideJob(){if(cur<0)return;await qHide(cur);closeModal()}

const rsteps=[{p:15,t:'Reading job description...'},{p:35,t:'Matching skills...'},{p:55,t:'Rewriting summary...'},{p:75,t:'Optimising skills...'},{p:90,t:'Generating PDF...'},{p:100,t:'Done!'}];
async function retailor(){
  if(cur<0)return; closeModal();
  const rb=document.getElementById('rb'),rf=document.getElementById('rf'),rt=document.getElementById('rt');
  rb.classList.add('show'); let s=0;
  const iv=setInterval(()=>{if(s>=rsteps.length){clearInterval(iv);return}rf.style.width=rsteps[s].p+'%';rt.textContent=rsteps[s].t;s++},700);
  try{
    await fetch('/api/retailor',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({index:cur})});
    clearInterval(iv);rf.style.width='100%';rt.textContent='CV re-tailored!';
    setTimeout(()=>{rb.classList.remove('show');load()},2000);
    notify('✨ CV re-tailored!');
  }catch(e){clearInterval(iv);rb.classList.remove('show');notify('❌ Re-tailor failed')}
}
async function qRetailor(i){cur=i;await retailor()}

async function scan(){
  const sb=document.getElementById('sb'),sm=document.getElementById('sm');
  sb.classList.add('show');sm.textContent='Scanning Reed + Indeed for new jobs...';
  try{await fetch('/api/scan',{method:'POST'});sm.textContent='Scan running... refreshing in 60s';setTimeout(async()=>{await load();sb.classList.remove('show')},60000)}
  catch(e){sb.classList.remove('show')}
}

function toggleSettings(){document.getElementById('sp').classList.toggle('open')}
function applySettings(){
  document.getElementById('te').classList.toggle('on',settings.email_alerts!==false);
  document.getElementById('ta').classList.toggle('on',settings.auto_scan!==false);
  document.getElementById('sc').value=settings.min_match_score||40;
  document.getElementById('si').value=settings.scan_interval||20;
  renderTitles(settings.job_titles||[]);
}
function renderTitles(t){document.getElementById('tt').innerHTML=t.map((x,i)=>`<div class="tpill">${x}<span class="tremove" onclick="rmTitle(${i})">✕</span></div>`).join('')}
function rmTitle(i){settings.job_titles.splice(i,1);renderTitles(settings.job_titles)}
function addTitle(){const v=document.getElementById('ni').value.trim();if(!v)return;if(!settings.job_titles)settings.job_titles=[];settings.job_titles.push(v);renderTitles(settings.job_titles);document.getElementById('ni').value=''}
function toggleNotif(el){el.classList.toggle('on');if(el.classList.contains('on')){Notification.requestPermission().then(p=>{notifOn=p==='granted';if(!notifOn)el.classList.remove('on')})}else{notifOn=false}}
async function saveSettings(){
  settings.min_match_score=parseInt(document.getElementById('sc').value);
  settings.scan_interval=parseInt(document.getElementById('si').value);
  await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(settings)});
  notify('💾 Settings saved!');toggleSettings();
}
function notify(m){const n=document.getElementById('notif');document.getElementById('notif-text').textContent=m;n.classList.add('show');setTimeout(()=>n.classList.remove('show'),3000)}
load();setInterval(load,60000);
</script>
</body>
</html>"""

class H(BaseHTTPRequestHandler):
    def log_message(self,f,*a):pass
    def sj(self,d,s=200):
        p=json.dumps(d).encode()
        self.send_response(s);self.send_header('Content-Type','application/json')
        self.send_header('Access-Control-Allow-Origin','*');self.end_headers();self.wfile.write(p)
    def gb(self):
        l=int(self.headers.get('Content-Length',0))
        return json.loads(self.rfile.read(l)) if l else {}
    def do_GET(self):
        p=urlparse(self.path).path
        if p in('/',''):
            self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(HTML.encode())
        elif p=='/api/jobs':
            d=load_data();self.sj({"jobs":d.get("seen",[]),"stats":get_stats(d)})
        elif p=='/api/settings':
            self.sj(load_settings())
        elif p.startswith('/cv/'):
            fp=Path(CV_DIR)/p.replace('/cv/','')
            if fp.exists() and fp.suffix=='.pdf':
                self.send_response(200);self.send_header('Content-Type','application/pdf');self.end_headers()
                with open(fp,'rb') as f:self.wfile.write(f.read())
            else:self.send_response(404);self.end_headers()
        else:self.send_response(404);self.end_headers()
    def do_POST(self):
        p=urlparse(self.path).path;b=self.gb()
        if p=='/api/scan':
            threading.Thread(target=lambda:os.system('python3 job_hunter.py --scan-once'),daemon=True).start()
            self.sj({"status":"scanning"})
        elif p=='/api/update-job':
            d=load_data();jobs=d.get("seen",[]);i=b.get("index",-1)
            if 0<=i<len(jobs):
                for k in['applied','hidden','notes']:
                    if k in b:jobs[i][k]=b[k]
                save_data(d)
            self.sj({"status":"ok"})
        elif p=='/api/retailor':
            d=load_data();jobs=d.get("seen",[]);i=b.get("index",-1)
            if 0<=i<len(jobs):
                import tempfile;j=jobs[i]
                tmp=tempfile.NamedTemporaryFile(mode='w',suffix='.json',delete=False)
                json.dump(j,tmp);tmp.close()
                def go(t=tmp.name):
                    os.system(f"python3 -c \"from job_hunter import tailor_cv,generate_pdf;import json;j=json.load(open('{t}'));t2=tailor_cv(j);generate_pdf(t2,j) if t2 else None\"")
                    os.unlink(t)
                threading.Thread(target=go,daemon=True).start()
            self.sj({"status":"ok"})
        elif p=='/api/settings':
            save_settings(b)
            try:
                import re;c=open('job_hunter.py',encoding='utf-8').read()
                c=re.sub(r'"MIN_MATCH_SCORE":\s*\d+',f'"MIN_MATCH_SCORE":   {b.get("min_match_score",40)}',c)
                c=re.sub(r'"SCAN_INTERVAL_MIN":\s*\d+',f'"SCAN_INTERVAL_MIN": {b.get("scan_interval",20)}',c)
                open('job_hunter.py','w',encoding='utf-8').write(c)
            except:pass
            self.sj({"status":"saved"})
        else:self.send_response(404);self.end_headers()

if __name__=='__main__':
    PORT=4000
    print(f"""
+==========================================+
|   JobHunter Pro - Dashboard v2           |
|   Open: http://0.0.0.0:{PORT}             |
|   Press Ctrl+C to stop                   |
+==========================================+
""")
    try:HTTPServer(('0.0.0.0',PORT),H).serve_forever()
    except KeyboardInterrupt:print("\nStopped.")
