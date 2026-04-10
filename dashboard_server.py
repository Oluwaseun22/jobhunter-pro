"""
JobHunter Pro v2 — Dashboard Server
Run: python3 dashboard_server.py
Open: http://0.0.0.0:4000
"""

import json
import os
import subprocess
import threading
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

LOG_FILE      = "job_hunter_log.json"
CV_DIR        = "tailored_cvs"
SETTINGS_FILE = "dashboard_settings.json"
REPORTS_DIR   = "data/reports"
TRACKER_FILE  = "data/applications.md"


def get_dashboard_token():
    """
    Load dashboard access token.
    AUDIT FIX [6.D]: Checked on every request to prevent open access.
    Set DASHBOARD_TOKEN in AWS Secrets Manager under jobhunter-pro/keys,
    or as an environment variable for local dev.
    """
    # Try Secrets Manager first
    try:
        import boto3
        client = boto3.client("secretsmanager", region_name="us-east-1")
        secret = client.get_secret_value(SecretId="jobhunter-pro/keys")
        secrets = json.loads(secret["SecretString"])
        token = secrets.get("DASHBOARD_TOKEN", "")
        if token:
            return token
    except Exception:
        pass
    # Fallback to environment variable
    return os.getenv("DASHBOARD_TOKEN", "")


DASHBOARD_TOKEN = get_dashboard_token()


def load_data():
    if Path(LOG_FILE).exists():
        with open(LOG_FILE) as f:
            return json.load(f)
    return {"seen": [], "applied": []}


def save_data(data):
    with open(LOG_FILE, "w") as f:
        json.dump(data, f, indent=2)


def load_settings():
    defaults = {
        "email_alerts":    True,
        "auto_scan":       True,
        "scan_interval":   20,
        "min_match_score": 50,
        "job_titles": [
            "Data Analyst", "Junior Data Analyst", "Graduate Data Analyst",
            "IT Analyst", "IT Support Analyst", "Business Analyst",
            "Junior Business Analyst", "Operations Analyst",
            "Data Analyst Trainee", "IT Graduate"
        ]
    }
    if Path(SETTINGS_FILE).exists():
        with open(SETTINGS_FILE) as f:
            defaults.update(json.load(f))
    return defaults


def save_settings(s):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(s, f, indent=2)


def get_stats(data):
    jobs    = data.get("seen", [])
    applied = [j for j in jobs if j.get("applied") or j.get("status") == "applied"]
    scores  = [j.get("score", 0) for j in jobs if j.get("score")]
    avg     = round(sum(scores) / len(scores)) if scores else 0
    graded  = [j for j in jobs if j.get("grade") in ("A", "B")]
    cvs     = len(list(Path(CV_DIR).glob("*.pdf"))) if Path(CV_DIR).exists() else 0
    return {
        "total":    len(jobs),
        "applied":  len(applied),
        "avg_score": avg,
        "cvs":      cvs,
        "strong":   len(graded),
    }


def load_tracker():
    if not Path(TRACKER_FILE).exists():
        return ""
    with open(TRACKER_FILE) as f:
        return f.read()


def load_report(filename):
    path = Path(REPORTS_DIR) / filename
    if path.exists() and path.suffix == ".md":
        with open(path) as f:
            return f.read()
    return None


HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>JobHunter Pro v2</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Fraunces:ital,wght@0,300;0,700;0,900&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --ink:#0f0f0f;--paper:#f7f5f0;--warm:#ede9e0;--border:#d4cfc4;
  --green:#1a5c38;--red:#c0392b;--orange:#b7791f;--blue:#1e3a8a;--purple:#5b21b6;
  --mono:'DM Mono',monospace;--serif:'Fraunces',serif
}
body{background:var(--paper);color:var(--ink);font-family:var(--mono);min-height:100vh}

/* Header */
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

/* Layout */
.main{max-width:1200px;margin:0 auto;padding:32px}

/* Notification */
.notif{background:var(--ink);color:#f7f5f0;padding:10px 20px;font-size:11px;
  display:none;align-items:center;justify-content:space-between;margin-bottom:20px;border-radius:4px}
.notif.show{display:flex}

/* Stats */
.stats{display:grid;grid-template-columns:repeat(5,1fr);gap:1px;background:var(--border);
  border:1px solid var(--border);margin-bottom:28px}
.stat{background:var(--paper);padding:20px}
.stat-n{font-family:var(--serif);font-size:38px;font-weight:900;line-height:1;margin-bottom:4px}
.stat-l{font-size:10px;letter-spacing:2px;text-transform:uppercase;opacity:.5}
.stat.g .stat-n{color:var(--green)}.stat.r .stat-n{color:var(--red)}.stat.p .stat-n{color:var(--purple)}

/* Tabs */
.tabs{display:flex;gap:0;border-bottom:2px solid var(--border);margin-bottom:24px}
.tab{font-family:var(--mono);font-size:11px;letter-spacing:1px;text-transform:uppercase;
  padding:10px 18px;border:none;background:transparent;cursor:pointer;opacity:.5;
  border-bottom:2px solid transparent;margin-bottom:-2px;transition:all .15s}
.tab.active{opacity:1;border-bottom-color:var(--ink)}
.tab:hover{opacity:.8}
.tabpanel{display:none}.tabpanel.active{display:block}

/* Settings panel */
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
.tog::after{content:'';position:absolute;width:16px;height:16px;background:white;border-radius:50%;
  top:3px;left:3px;transition:transform .3s;box-shadow:0 1px 3px rgba(0,0,0,.3)}
.tog.on::after{transform:translateX(18px)}
.tags-wrap{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.tpill{font-size:10px;padding:4px 10px;border:1px solid var(--border);background:var(--paper);display:flex;align-items:center;gap:6px}
.tremove{opacity:.4;cursor:pointer;font-size:12px}.tremove:hover{opacity:1;color:var(--red)}

/* Controls */
.ctrl{display:flex;align-items:center;justify-content:space-between;margin-bottom:18px;flex-wrap:wrap;gap:12px}
.ctrl h2{font-family:var(--serif);font-size:20px;font-weight:700;font-style:italic}
.btns{display:flex;gap:7px;flex-wrap:wrap}
.btn{font-family:var(--mono);font-size:11px;letter-spacing:1px;text-transform:uppercase;
  padding:7px 13px;border:1px solid var(--ink);background:transparent;cursor:pointer;transition:all .15s}
.btn:hover,.btn.active{background:var(--ink);color:var(--paper)}
.btn.pri{background:var(--ink);color:var(--paper)}.btn.pri:hover{background:#333}

/* Scanning bars */
.sbar{background:var(--ink);color:#f7f5f0;padding:10px 18px;font-size:11px;
  display:none;align-items:center;gap:10px;margin-bottom:14px}
.sbar.show{display:flex}
.spin{animation:spin 1s linear infinite;display:inline-block}
@keyframes spin{to{transform:rotate(360deg)}}
.rbar{background:var(--ink);color:#f7f5f0;padding:14px 18px;margin-bottom:14px;display:none}
.rbar.show{display:block}
.rpb{height:3px;background:rgba(255,255,255,.2);margin-top:8px;border-radius:2px}
.rpf{height:100%;background:#4ade80;border-radius:2px;transition:width .5s;width:0%}
.rpt{font-size:10px;opacity:.6;margin-top:5px}

/* Grade badge */
.grade{display:inline-flex;align-items:center;justify-content:center;
  width:26px;height:26px;font-family:var(--serif);font-size:14px;font-weight:900;border-radius:4px}
.grade.A{background:#d1fae5;color:var(--green)}.grade.B{background:#dbeafe;color:var(--blue)}
.grade.C{background:#fef3c7;color:var(--orange)}.grade.D,.grade.F{background:#fee2e2;color:var(--red)}
.grade.blank{background:var(--warm);color:var(--border)}

/* Job table */
.jtable{border:1px solid var(--border);background:var(--paper)}
.jh{display:grid;grid-template-columns:2fr 1.2fr 0.5fr 0.5fr 0.7fr 0.7fr 1.1fr;
  padding:10px 18px;background:var(--warm);border-bottom:1px solid var(--border);
  font-size:9px;letter-spacing:2px;text-transform:uppercase;opacity:.6;gap:10px}
.jr{display:grid;grid-template-columns:2fr 1.2fr 0.5fr 0.5fr 0.7fr 0.7fr 1.1fr;
  padding:14px 18px;border-bottom:1px solid var(--border);align-items:center;gap:10px;transition:background .1s}
.jr:hover{background:var(--warm)}.jr.applied{opacity:.55}.jr.hidden{display:none}
.jtitle{font-weight:500;font-size:13px;margin-bottom:2px;cursor:pointer}.jtitle:hover{text-decoration:underline}
.jmeta{font-size:10px;opacity:.5}.jco{font-size:12px;opacity:.8}
.sb{display:flex;align-items:center;gap:6px}
.sn{font-family:var(--serif);font-size:13px;font-weight:700;min-width:28px}
.st{flex:1;height:3px;background:var(--border);border-radius:2px}
.sf{height:100%;border-radius:2px;background:var(--ink)}.sf.h{background:var(--green)}.sf.m{background:var(--orange)}
.tag{font-size:9px;letter-spacing:1px;text-transform:uppercase;padding:3px 7px;border:1px solid var(--border);display:inline-block}
.tag.new{border-color:var(--green);color:var(--green)}.tag.applied{border-color:var(--ink);background:var(--ink);color:#f7f5f0}
.tag.skipped{border-color:var(--border);color:var(--border)}
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

/* Tracker tab */
.tracker-wrap{background:var(--paper);border:1px solid var(--border);padding:0}
.tracker-content{font-size:11px;line-height:1.8;padding:24px;overflow-x:auto;white-space:pre-wrap;font-family:var(--mono)}

/* Report viewer */
.report-list{border:1px solid var(--border)}
.report-item{display:flex;align-items:center;justify-content:space-between;
  padding:12px 18px;border-bottom:1px solid var(--border);cursor:pointer;transition:background .1s}
.report-item:hover{background:var(--warm)}
.report-item:last-child{border-bottom:none}
.ri-title{font-size:12px;font-weight:500}
.ri-meta{font-size:10px;opacity:.5;margin-top:2px}
.report-content{display:none;background:var(--warm);border:1px solid var(--border);
  padding:24px;margin-top:12px;font-size:12px;line-height:1.8;white-space:pre-wrap;font-family:var(--mono)}
.report-content.open{display:block}

/* Modal */
.mbg{display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:100;align-items:center;justify-content:center}
.mbg.open{display:flex}
.modal{background:var(--paper);border:1px solid var(--border);max-width:600px;width:90%;max-height:88vh;overflow-y:auto}
.mh{padding:18px 22px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:start}
.mt{font-family:var(--serif);font-size:17px;font-weight:700}
.mc{background:none;border:none;font-size:17px;cursor:pointer;opacity:.4}
.mb{padding:22px}
.mf{margin-bottom:14px}
.ml{font-size:9px;letter-spacing:2px;text-transform:uppercase;opacity:.5;margin-bottom:4px}
.mv{font-size:13px;line-height:1.6}
.ni{width:100%;background:var(--warm);border:1px solid var(--border);padding:10px;
  font-family:var(--mono);font-size:12px;color:var(--ink);outline:none;resize:vertical;min-height:80px}
.ma{padding:18px 22px;border-top:1px solid var(--border);display:flex;gap:7px;flex-wrap:wrap}
.one-liner{font-size:12px;font-style:italic;opacity:.7;line-height:1.6;padding:10px;
  background:var(--warm);border-left:3px solid var(--border);margin-bottom:8px}

footer{text-align:center;padding:28px;font-size:10px;opacity:.3;letter-spacing:1px;text-transform:uppercase}

@media(max-width:900px){
  header{padding:14px 16px}.logo h1{font-size:18px}.main{padding:16px}
  .stats{grid-template-columns:repeat(3,1fr)}.stat{padding:14px}.stat-n{font-size:28px}
  .jh{display:none}.jr{grid-template-columns:1fr;gap:6px;padding:14px 16px}
  .ctrl{flex-direction:column;align-items:flex-start}.btns{flex-wrap:wrap}
  .sg{grid-template-columns:1fr}
}
@media(max-width:480px){
  .stats{grid-template-columns:repeat(2,1fr)}.stat-n{font-size:24px}
}
</style>
</head>
<body>
<header>
  <div class="logo">
    <h1>JobHunter Pro<span>v2 · Scotland</span></h1>
  </div>
  <div class="hright">
    <div class="live"><div class="dot"></div>Live</div>
    <button class="sbtn" onclick="toggleSettings()">⚙ Settings</button>
  </div>
</header>

<div class="main">
  <div class="notif" id="notif">
    <span id="notif-text"></span>
    <button onclick="document.getElementById('notif').classList.remove('show')"
      style="background:none;border:none;color:#f7f5f0;cursor:pointer;font-size:16px">✕</button>
  </div>

  <!-- Stats -->
  <div class="stats">
    <div class="stat"><div class="stat-n" id="s1">—</div><div class="stat-l">Jobs Found</div></div>
    <div class="stat g"><div class="stat-n" id="s2">—</div><div class="stat-l">CVs Generated</div></div>
    <div class="stat p"><div class="stat-n" id="s5">—</div><div class="stat-l">Grade A/B</div></div>
    <div class="stat"><div class="stat-n" id="s3">—</div><div class="stat-l">Avg Score</div></div>
    <div class="stat r"><div class="stat-n" id="s4">—</div><div class="stat-l">Applied</div></div>
  </div>

  <!-- Settings -->
  <div class="settings-panel" id="sp">
    <div class="sg">
      <div>
        <span class="sl">Toggles</span>
        <div class="tr">
          <div><div class="tl">Email Alerts</div><div class="ts">Send CV to your inbox</div></div>
          <div class="tog" id="te" onclick="this.classList.toggle('on');settings.email_alerts=this.classList.contains('on')"></div>
        </div>
        <div class="tr">
          <div><div class="tl">Auto Scan</div><div class="ts">Scan automatically</div></div>
          <div class="tog" id="ta" onclick="this.classList.toggle('on');settings.auto_scan=this.classList.contains('on')"></div>
        </div>
      </div>
      <div>
        <span class="sl">Thresholds</span>
        <div style="margin-bottom:14px">
          <div class="sl">Min Match Score (0-100)</div>
          <input class="si" type="number" id="sc" min="0" max="100" value="50">
        </div>
        <div>
          <div class="sl">Scan Interval (minutes)</div>
          <input class="si" type="number" id="si2" min="5" max="120" value="20">
        </div>
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
    <button class="btn pri" onclick="saveSettings()" style="margin-top:18px;width:100%">
      💾 Save Settings
    </button>
  </div>

  <!-- Tabs -->
  <div class="tabs">
    <button class="tab active" onclick="switchTab('jobs',this)">Job Feed</button>
    <button class="tab" onclick="switchTab('tracker',this)">Tracker</button>
    <button class="tab" onclick="switchTab('reports',this)">Reports</button>
  </div>

  <!-- Tab: Jobs -->
  <div class="tabpanel active" id="tab-jobs">
    <div class="ctrl">
      <h2>Live Job Feed</h2>
      <div class="btns">
        <button class="btn active" onclick="filter('all',this)">All</button>
        <button class="btn" onclick="filter('ab',this)">Grade A/B</button>
        <button class="btn" onclick="filter('applied',this)">Applied</button>
        <button class="btn" onclick="filter('reed',this)">Reed</button>
        <button class="btn" onclick="filter('indeed',this)">Indeed</button>
        <button class="btn pri" onclick="scan()">↻ Scan Now</button>
      </div>
    </div>
    <div class="sbar" id="sb"><span class="spin">⟳</span><span id="sm">Scanning...</span></div>
    <div class="rbar" id="rb">
      <div style="font-size:11px;letter-spacing:1px">✨ RE-TAILORING CV...</div>
      <div class="rpb"><div class="rpf" id="rf"></div></div>
      <div class="rpt" id="rt">Starting...</div>
    </div>
    <div class="jtable">
      <div class="jh">
        <div>Role</div><div>Company</div><div>Grade</div>
        <div>Source</div><div>Score</div><div>Status</div><div>Actions</div>
      </div>
      <div id="jl"><div class="empty">Loading...</div></div>
    </div>
  </div>

  <!-- Tab: Tracker -->
  <div class="tabpanel" id="tab-tracker">
    <div class="ctrl">
      <h2>Application Tracker</h2>
      <div class="btns">
        <button class="btn pri" onclick="loadTracker()">↻ Refresh</button>
      </div>
    </div>
    <div class="tracker-wrap">
      <div class="tracker-content" id="tracker-content">Loading tracker...</div>
    </div>
  </div>

  <!-- Tab: Reports -->
  <div class="tabpanel" id="tab-reports">
    <div class="ctrl">
      <h2>Evaluation Reports</h2>
      <div class="btns">
        <button class="btn pri" onclick="loadReports()">↻ Refresh</button>
      </div>
    </div>
    <div class="report-list" id="report-list">
      <div class="empty">Loading reports...</div>
    </div>
    <div class="report-content" id="report-content"></div>
  </div>
</div>

<!-- Modal -->
<div class="mbg" id="modal">
  <div class="modal">
    <div class="mh">
      <div>
        <div class="mt" id="mt">—</div>
        <div style="font-size:11px;opacity:.5;margin-top:3px" id="mc2">—</div>
      </div>
      <button class="mc" onclick="closeModal()">✕</button>
    </div>
    <div class="mb">
      <div class="one-liner" id="m-oneliner" style="display:none"></div>
      <div style="display:flex;gap:14px;margin-bottom:14px;flex-wrap:wrap">
        <div class="mf" style="flex:1">
          <div class="ml">Grade</div>
          <div class="mv" id="m-grade">—</div>
        </div>
        <div class="mf" style="flex:1">
          <div class="ml">Score</div>
          <div class="mv" id="ms">—</div>
        </div>
        <div class="mf" style="flex:1">
          <div class="ml">Source</div>
          <div class="mv" id="msrc">—</div>
        </div>
      </div>
      <div style="display:flex;gap:14px;margin-bottom:14px;flex-wrap:wrap">
        <div class="mf" style="flex:1">
          <div class="ml">Location</div>
          <div class="mv" id="m-loc">—</div>
        </div>
        <div class="mf" style="flex:1">
          <div class="ml">Salary</div>
          <div class="mv" id="m-sal">—</div>
        </div>
        <div class="mf" style="flex:1">
          <div class="ml">Scanned</div>
          <div class="mv" id="md">—</div>
        </div>
      </div>
      <div class="mf">
        <div class="ml">Notes</div>
        <textarea class="ni" id="mn" placeholder="Add notes..."></textarea>
      </div>
    </div>
    <div class="ma">
      <a class="ab ap" id="ma" href="#" target="_blank">✓ Apply</a>
      <button class="ab" id="mcv" onclick="openCV()">📄 CV</button>
      <button class="ab rt" onclick="retailor()">✨ Re-tailor</button>
      <button class="ab" onclick="markApplied()">✅ Applied</button>
      <button class="ab" onclick="viewReport()">📋 Report</button>
      <button class="ab hd" onclick="hideJob()">✕ Hide</button>
      <button class="ab" onclick="saveNotes()">💾 Notes</button>
      <button class="ab" onclick="closeModal()">Close</button>
    </div>
  </div>
</div>

<footer>JobHunter Pro v2 · 0.0.0.0:4000 · github.com/Oluwaseun22/jobhunter-pro</footer>

<script>
let jobs = [], settings = {}, cur = -1;

const TOKEN = new URLSearchParams(window.location.search).get('token') || '';
function apiFetch(url, opts) {
  opts = opts || {};
  opts.headers = Object.assign({'X-Dashboard-Token': TOKEN}, opts.headers || {});
  return fetch(url, opts);
}

// ── Load ──────────────────────────────────────────────────────
async function load() {
  try {
    const [jr, sr] = await Promise.all([apiFetch('/api/jobs'), apiFetch('/api/settings')]);
    const jd = await jr.json();
    settings = await sr.json();
    jobs = jd.jobs || [];
    document.getElementById('s1').textContent = jd.stats.total    || 0;
    document.getElementById('s2').textContent = jd.stats.cvs      || 0;
    document.getElementById('s3').textContent = (jd.stats.avg_score || 0) + '%';
    document.getElementById('s4').textContent = jd.stats.applied  || 0;
    document.getElementById('s5').textContent = jd.stats.strong   || 0;
    renderJobs(jobs);
    applySettings();
  } catch(e) {
    document.getElementById('jl').innerHTML =
      '<div class="empty">Could not load data. Run a scan first.</div>';
  }
}

// ── Render jobs ───────────────────────────────────────────────
function renderJobs(list) {
  const el = document.getElementById('jl');
  const visible = list.filter(j => !j.hidden);
  if (!visible.length) {
    el.innerHTML = '<div class="empty">No jobs match filter.</div>';
    return;
  }
  el.innerHTML = visible.map((j, i) => {
    const idx   = jobs.indexOf(j);
    const sc    = j.score || 0;
    const cls   = sc >= 80 ? 'h' : sc >= 60 ? 'm' : '';
    const src   = j.source || 'reed';
    const grade = j.grade || '';
    const dt    = j.scanned
      ? new Date(j.scanned).toLocaleDateString('en-GB', {day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'})
      : '—';
    const status = j.applied ? 'applied' : (j.status || 'new');
    return `<div class="jr ${j.applied ? 'applied' : ''}" id="r${idx}">
      <div>
        <div class="jtitle" onclick="showModal(${idx})">${j.title}</div>
        <div class="jmeta">${dt}${j.notes ? ' · 📝' : ''}</div>
      </div>
      <div class="jco">${j.company}</div>
      <div><span class="grade ${grade || 'blank'}">${grade || '·'}</span></div>
      <div><span class="tag ${src}">${src}</span></div>
      <div class="sb">
        <span class="sn">${sc}%</span>
        <div class="st"><div class="sf ${cls}" style="width:${Math.min(100,sc)}%"></div></div>
      </div>
      <div><span class="tag ${status}">${status}</span></div>
      <div class="ja" onclick="event.stopPropagation()">
        <a class="ab ap" href="${j.url || '#'}" target="_blank" onclick="qApply(${idx})">Apply</a>
        ${j.pdf ? `<a class="ab" href="/cv/${encodeURIComponent(j.pdf.split('/').pop())}" target="_blank">CV</a>` : ''}
        <button class="ab rt" onclick="qRetailor(${idx})">✨</button>
        <button class="ab hd" onclick="qHide(${idx})">✕</button>
      </div>
    </div>`;
  }).join('');
}

// ── Filters ───────────────────────────────────────────────────
function filter(t, btn) {
  document.querySelectorAll('.btns .btn:not(.pri)').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  let f = jobs.filter(j => !j.hidden);
  if (t === 'ab')      f = f.filter(j => j.grade === 'A' || j.grade === 'B');
  if (t === 'applied') f = f.filter(j => j.applied || j.status === 'applied');
  if (t === 'reed')    f = f.filter(j => j.source === 'reed');
  if (t === 'indeed')  f = f.filter(j => j.source === 'indeed');
  renderJobs(f);
}

// ── Modal ─────────────────────────────────────────────────────
function showModal(i) {
  cur = i;
  const j = jobs[i];
  document.getElementById('mt').textContent      = j.title;
  document.getElementById('mc2').textContent     = `${j.company} · ${j.location || 'Scotland'}`;
  document.getElementById('m-grade').textContent = j.grade || '—';
  document.getElementById('ms').textContent      = (j.score || '—') + '%';
  document.getElementById('msrc').textContent    = (j.source || 'reed').toUpperCase();
  document.getElementById('md').textContent      = j.scanned ? new Date(j.scanned).toLocaleString('en-GB') : '—';
  document.getElementById('m-loc').textContent   = j.location || '—';
  document.getElementById('m-sal').textContent   = j.salary || '—';
  document.getElementById('mn').value            = j.notes || '';
  document.getElementById('ma').href             = j.url || '#';
  document.getElementById('mcv').dataset.pdf     = j.pdf || '';

  const ol = document.getElementById('m-oneliner');
  if (j.one_liner) { ol.textContent = j.one_liner; ol.style.display = 'block'; }
  else { ol.style.display = 'none'; }

  document.getElementById('modal').classList.add('open');
}
function closeModal() { document.getElementById('modal').classList.remove('open'); }
function openCV() {
  const p = document.getElementById('mcv').dataset.pdf;
  if (p) window.open('/cv/' + encodeURIComponent(p.split('/').pop()), '_blank');
}

// ── Actions ───────────────────────────────────────────────────
async function upd(i, d) {
  await apiFetch('/api/update-job', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({index: i, ...d})
  });
}
async function saveNotes()    { if (cur < 0) return; const n = document.getElementById('mn').value; await upd(cur, {notes: n}); jobs[cur].notes = n; notify('📝 Notes saved'); renderJobs(jobs.filter(j => !j.hidden)); }
async function markApplied()  { if (cur < 0) return; await upd(cur, {applied: true, status: 'applied'}); jobs[cur].applied = true; notify('✅ Applied!'); closeModal(); load(); }
async function qApply(i)      { await upd(i, {applied: true, status: 'applied'}); jobs[i].applied = true; }
async function qHide(i)       { await upd(i, {hidden: true}); document.getElementById('r' + i)?.classList.add('hidden'); notify('Hidden'); }
async function hideJob()      { if (cur < 0) return; await qHide(cur); closeModal(); }

function viewReport() {
  if (cur < 0) return;
  const j = jobs[cur];
  if (!j.report) { notify('No report for this job'); return; }
  closeModal();
  switchTab('reports', document.querySelectorAll('.tab')[2]);
  setTimeout(() => loadReports(j.report), 200);
}

// ── Re-tailor ─────────────────────────────────────────────────
const rsteps = [
  {p:15, t:'Reading job description...'},
  {p:35, t:'Matching your skills...'},
  {p:55, t:'Rewriting CV summary...'},
  {p:75, t:'Optimising keywords...'},
  {p:90, t:'Generating PDF...'},
  {p:100,t:'Done!'}
];
async function retailor() {
  if (cur < 0) return; closeModal();
  const rb = document.getElementById('rb'), rf = document.getElementById('rf'), rt = document.getElementById('rt');
  rb.classList.add('show'); let s = 0;
  const iv = setInterval(() => { if (s >= rsteps.length) { clearInterval(iv); return; } rf.style.width = rsteps[s].p + '%'; rt.textContent = rsteps[s].t; s++; }, 700);
  try {
    await apiFetch('/api/retailor', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({index: cur})});
    clearInterval(iv); rf.style.width = '100%'; rt.textContent = 'CV re-tailored!';
    setTimeout(() => { rb.classList.remove('show'); load(); }, 2000);
    notify('✨ CV re-tailored!');
  } catch(e) { clearInterval(iv); rb.classList.remove('show'); notify('Re-tailor failed'); }
}
async function qRetailor(i) { cur = i; await retailor(); }

// ── Scan ──────────────────────────────────────────────────────
async function scan() {
  const sb = document.getElementById('sb'), sm = document.getElementById('sm');
  sb.classList.add('show'); sm.textContent = 'Scanning Reed + Indeed for new jobs...';
  try {
    await apiFetch('/api/scan', {method: 'POST'});
    sm.textContent = 'Scan running... refreshing in 60s';
    setTimeout(async () => { await load(); sb.classList.remove('show'); }, 60000);
  } catch(e) { sb.classList.remove('show'); }
}

// ── Tabs ──────────────────────────────────────────────────────
function switchTab(name, btn) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tabpanel').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('tab-' + name).classList.add('active');
  if (name === 'tracker') loadTracker();
  if (name === 'reports') loadReports();
}

async function loadTracker() {
  try {
    const r = await apiFetch('/api/tracker');
    const d = await r.json();
    document.getElementById('tracker-content').textContent = d.content || 'No applications tracked yet.';
  } catch(e) { document.getElementById('tracker-content').textContent = 'Could not load tracker.'; }
}

async function loadReports(highlightReport) {
  try {
    const r  = await apiFetch('/api/reports');
    const d  = await r.json();
    const el = document.getElementById('report-list');
    if (!d.reports || !d.reports.length) {
      el.innerHTML = '<div class="empty">No evaluation reports yet.</div>';
      return;
    }
    el.innerHTML = d.reports.map(rep => `
      <div class="report-item" onclick="toggleReport('${rep.filename}', this)">
        <div>
          <div class="ri-title">${rep.filename.replace('.md','').replace(/-/g,' ')}</div>
          <div class="ri-meta">${rep.filename.split('-').slice(0,3).join('-')}</div>
        </div>
        <span style="opacity:.4;font-size:11px">▼</span>
      </div>
    `).join('');

    if (highlightReport) {
      const fname = highlightReport.split('/').pop();
      const items = document.querySelectorAll('.report-item');
      for (const item of items) {
        if (item.querySelector('.ri-title').textContent.includes(fname.replace('.md', ''))) {
          item.click();
          item.scrollIntoView({behavior: 'smooth'});
          break;
        }
      }
    }
  } catch(e) {
    document.getElementById('report-list').innerHTML = '<div class="empty">Could not load reports.</div>';
  }
}

async function toggleReport(filename, el) {
  const content = document.getElementById('report-content');
  if (content.classList.contains('open') && content.dataset.current === filename) {
    content.classList.remove('open');
    return;
  }
  try {
    const r = await apiFetch('/api/report/' + encodeURIComponent(filename));
    const d = await r.json();
    content.textContent = d.content || 'Empty report.';
    content.dataset.current = filename;
    content.classList.add('open');
    content.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  } catch(e) { notify('Could not load report'); }
}

// ── Settings ──────────────────────────────────────────────────
function toggleSettings() { document.getElementById('sp').classList.toggle('open'); }
function applySettings() {
  document.getElementById('te').classList.toggle('on', settings.email_alerts !== false);
  document.getElementById('ta').classList.toggle('on', settings.auto_scan !== false);
  document.getElementById('sc').value  = settings.min_match_score || 50;
  document.getElementById('si2').value = settings.scan_interval   || 20;
  renderTitles(settings.job_titles || []);
}
function renderTitles(t) {
  document.getElementById('tt').innerHTML = t.map((x,i) =>
    `<div class="tpill">${x}<span class="tremove" onclick="rmTitle(${i})">✕</span></div>`
  ).join('');
}
function rmTitle(i)  { settings.job_titles.splice(i, 1); renderTitles(settings.job_titles); }
function addTitle()  {
  const v = document.getElementById('ni').value.trim();
  if (!v) return;
  if (!settings.job_titles) settings.job_titles = [];
  settings.job_titles.push(v);
  renderTitles(settings.job_titles);
  document.getElementById('ni').value = '';
}
async function saveSettings() {
  settings.min_match_score = parseInt(document.getElementById('sc').value);
  settings.scan_interval   = parseInt(document.getElementById('si2').value);
  await apiFetch('/api/settings', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(settings)
  });
  notify('💾 Settings saved!');
  toggleSettings();
}

function notify(m) {
  const n = document.getElementById('notif');
  document.getElementById('notif-text').textContent = m;
  n.classList.add('show');
  setTimeout(() => n.classList.remove('show'), 3000);
}

load();
setInterval(load, 60000);
</script>
</body>
</html>"""


LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>JobHunter Pro — Login</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0f0f0f;color:#f7f5f0;font-family:'Courier New',monospace;
  min-height:100vh;display:flex;align-items:center;justify-content:center}
.box{border:1px solid #333;padding:48px;max-width:360px;width:90%;text-align:center}
h1{font-size:20px;font-weight:900;margin-bottom:6px;letter-spacing:1px}
p{font-size:11px;opacity:.4;letter-spacing:2px;text-transform:uppercase;margin-bottom:32px}
input{width:100%;background:#1a1a1a;border:1px solid #333;color:#f7f5f0;
  padding:12px 16px;font-family:inherit;font-size:14px;outline:none;margin-bottom:12px;
  letter-spacing:2px;text-align:center}
input:focus{border-color:#f7f5f0}
button{width:100%;background:#f7f5f0;color:#0f0f0f;border:none;padding:12px;
  font-family:inherit;font-size:12px;letter-spacing:2px;text-transform:uppercase;cursor:pointer}
button:hover{background:#ccc}
.err{color:#c0392b;font-size:11px;margin-top:10px;display:none}
</style>
</head>
<body>
<div class="box">
  <h1>JobHunter Pro</h1>
  <p>__TOKEN_HINT__</p>
  <input type="password" id="tk" placeholder="Enter token" autocomplete="off">
  <button onclick="login()">Access Dashboard</button>
  <div class="err" id="err">Invalid token</div>
</div>
<script>
function login() {
  const t = document.getElementById('tk').value.trim();
  if (!t) return;
  // Reload with token as query param — Handler validates it
  window.location.href = '/?token=' + encodeURIComponent(t);
}
document.getElementById('tk').addEventListener('keydown', e => {
  if (e.key === 'Enter') login();
});
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, f, *a): pass

    def add_security_headers(self):
        # AUDIT FIX [6.7]: HTTP security headers on every response
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "geolocation=(), microphone=(), camera=()")

    def is_authorised(self):
        # AUDIT FIX [6.D]: Token auth — skip if no token configured (local dev without token)
        if not DASHBOARD_TOKEN:
            return True
        auth = self.headers.get("X-Dashboard-Token", "")
        query = urlparse(self.path).query
        token_in_query = any(
            p.startswith("token=") and p[6:] == DASHBOARD_TOKEN
            for p in query.split("&")
        )
        return auth == DASHBOARD_TOKEN or token_in_query

    def send_json(self, data, status=200):
        payload = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.add_security_headers()
        self.end_headers()
        self.wfile.write(payload)

    def send_unauth(self):
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.add_security_headers()
        self.end_headers()
        self.wfile.write(b'{"error":"Unauthorised"}')

    def get_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def do_GET(self):
        path = urlparse(self.path).path

        # Root page: serve login gate if token required and not provided
        if path in ("/", ""):
            if DASHBOARD_TOKEN and not self.is_authorised():
                # Serve a minimal login page
                login_html = LOGIN_HTML.replace("__TOKEN_HINT__",
                    "Enter your dashboard token to continue.")
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.add_security_headers()
                self.end_headers()
                self.wfile.write(login_html.encode())
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.add_security_headers()
            self.end_headers()
            self.wfile.write(HTML.encode())
            return

        # All other routes require auth
        if not self.is_authorised():
            self.send_unauth()
            return

        if path == "/api/jobs":
            d = load_data()
            self.send_json({"jobs": d.get("seen", []), "stats": get_stats(d)})

        elif path == "/api/settings":
            self.send_json(load_settings())

        elif path == "/api/tracker":
            self.send_json({"content": load_tracker()})

        elif path == "/api/reports":
            reports_dir = Path(REPORTS_DIR)
            if reports_dir.exists():
                files = sorted(
                    [{"filename": f.name} for f in reports_dir.glob("*.md")],
                    key=lambda x: x["filename"], reverse=True
                )
            else:
                files = []
            self.send_json({"reports": files})

        elif path.startswith("/api/report/"):
            # AUDIT FIX [6.B]: Strip to filename only — prevents directory traversal
            raw_name = path.replace("/api/report/", "")
            filename = Path(raw_name).name  # e.g. "../../.env" → ".env", then rejected below
            if not filename.endswith(".md") or "/" in filename or "\\" in filename:
                self.send_json({"error": "Not found"}, 404)
                return
            content = load_report(filename)
            if content:
                self.send_json({"content": content})
            else:
                self.send_json({"error": "Not found"}, 404)

        elif path.startswith("/cv/"):
            # AUDIT FIX [6.A]: Strip to filename only — prevents directory traversal
            raw_name = path.replace("/cv/", "")
            safe_name = Path(raw_name).name  # "../../.env" → ".env", then rejected below
            fp = Path(CV_DIR) / safe_name
            # Must be inside CV_DIR, must be a .pdf, no path separators in name
            if (
                fp.suffix == ".pdf"
                and fp.parent.resolve() == Path(CV_DIR).resolve()
                and "/" not in safe_name
                and "\\" not in safe_name
                and fp.exists()
            ):
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.end_headers()
                with open(fp, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.end_headers()

        else:
            # AUDIT FIX [10.1]: Proper 404 response instead of bare header
            self.send_json({"error": "Not found"}, 404)
        path = urlparse(self.path).path

        # AUDIT FIX [6.D]: All POST routes require auth
        if not self.is_authorised():
            self.send_unauth()
            return

        body = self.get_body()

        if path == "/api/scan":
            # AUDIT FIX [6.C]: subprocess.run with arg list — no shell=True
            threading.Thread(
                target=lambda: subprocess.run(
                    ["python3", "job_hunter.py", "--scan-once"],
                    check=False
                ),
                daemon=True
            ).start()
            self.send_json({"status": "scanning"})

        elif path == "/api/update-job":
            d    = load_data()
            jobs = d.get("seen", [])
            i    = body.get("index", -1)
            if 0 <= i < len(jobs):
                for k in ["applied", "hidden", "notes", "status"]:
                    if k in body:
                        jobs[i][k] = body[k]
                save_data(d)
            self.send_json({"status": "ok"})

        elif path == "/api/retailor":
            d    = load_data()
            jobs = d.get("seen", [])
            i    = body.get("index", -1)
            if 0 <= i < len(jobs):
                import tempfile
                import subprocess
                job = jobs[i]
                tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
                json.dump(job, tmp)
                tmp.close()

                # AUDIT FIX [6.C]: Use subprocess.run() with arg list — no shell=True,
                # no f-string interpolation of job data into a shell command.
                # Temp file path passed as argument, not interpolated into code string.
                script = (
                    "import sys, json; "
                    "from job_hunter import tailor_cv, generate_pdf, PROFILE; "
                    "j = json.load(open(sys.argv[1])); "
                    "t = tailor_cv(j, PROFILE); "
                    "generate_pdf(t, j, PROFILE) if t else None"
                )

                def go(t=tmp.name):
                    try:
                        subprocess.run(
                            ["python3", "-c", script, t],
                            timeout=120,
                            check=False
                        )
                    except Exception as e:
                        print(f"  [ERROR] Retailor subprocess: {e}")
                    finally:
                        # AUDIT FIX [medium]: Always clean up temp file
                        try:
                            os.unlink(t)
                        except OSError:
                            pass

                threading.Thread(target=go, daemon=True).start()
            self.send_json({"status": "ok"})

        elif path == "/api/settings":
            save_settings(body)
            self.send_json({"status": "saved"})

        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    PORT = 4000
    print(f"""
+==========================================+
|   JobHunter Pro v2 — Dashboard           |
|   Open: http://0.0.0.0:{PORT}             |
|   Press Ctrl+C to stop                   |
+==========================================+
""")
    try:
        HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
