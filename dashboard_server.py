"""
JobHunter Pro - Dashboard Server
Run: python3 dashboard_server.py
Then open: http://localhost:5000
"""

import json, os, subprocess
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

LOG_FILE    = "job_hunter_log.json"
CV_DIR      = "tailored_cvs"

def load_data():
    if Path(LOG_FILE).exists():
        with open(LOG_FILE) as f:
            return json.load(f)
    return {"seen": [], "applied": []}

def get_stats(data):
    jobs = data.get("seen", [])
    applied = data.get("applied", [])
    scores = [j.get("score", 0) for j in jobs if j.get("score")]
    avg = round(sum(scores) / len(scores)) if scores else 0
    return {
        "total": len(jobs),
        "applied": len(applied),
        "avg_score": avg,
        "cvs": len(list(Path(CV_DIR).glob("*.pdf"))) if Path(CV_DIR).exists() else 0,
    }

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>JobHunter Pro — Segun's Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Fraunces:ital,wght@0,300;0,700;0,900;1,300&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --ink:#0f0f0f;--paper:#f7f5f0;--warm:#ede9e0;
  --accent:#1a1a1a;--red:#c0392b;--green:#1a5c38;
  --mono:'DM Mono',monospace;--serif:'Fraunces',serif;
  --border:#d4cfc4;
}
body{background:var(--paper);color:var(--ink);font-family:var(--mono);min-height:100vh}

/* Grain overlay */
body::before{content:'';position:fixed;inset:0;opacity:.025;
  background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
  pointer-events:none;z-index:999}

header{
  background:var(--ink);color:var(--paper);
  padding:28px 40px;
  display:flex;align-items:center;justify-content:space-between;
  border-bottom:3px solid var(--ink);
}
.logo{display:flex;align-items:baseline;gap:14px}
.logo h1{font-family:var(--serif);font-size:28px;font-weight:900;letter-spacing:-1px}
.logo span{font-size:11px;opacity:.5;letter-spacing:2px;text-transform:uppercase}
.live{display:flex;align-items:center;gap:8px;font-size:11px;letter-spacing:1px;text-transform:uppercase}
.dot{width:7px;height:7px;border-radius:50%;background:#4ade80;animation:pulse 2s infinite;box-shadow:0 0 8px #4ade80}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}

.main{max-width:1100px;margin:0 auto;padding:40px}

/* Stats */
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--border);border:1px solid var(--border);margin-bottom:40px}
.stat{background:var(--paper);padding:28px 24px}
.stat-n{font-family:var(--serif);font-size:48px;font-weight:900;line-height:1;margin-bottom:6px}
.stat-l{font-size:10px;letter-spacing:2px;text-transform:uppercase;opacity:.5}
.stat.green .stat-n{color:var(--green)}
.stat.red .stat-n{color:var(--red)}

/* Toolbar */
.toolbar{display:flex;align-items:center;justify-content:space-between;margin-bottom:20px}
.toolbar h2{font-family:var(--serif);font-size:22px;font-weight:700;font-style:italic}
.controls{display:flex;gap:10px;align-items:center}
.btn{font-family:var(--mono);font-size:11px;letter-spacing:1px;text-transform:uppercase;
  padding:8px 16px;border:1px solid var(--ink);background:transparent;cursor:pointer;
  transition:all .15s}
.btn:hover,.btn.active{background:var(--ink);color:var(--paper)}
.btn.scan{background:var(--ink);color:var(--paper)}
.btn.scan:hover{background:#333}

/* Job table */
.job-table{border:1px solid var(--border);background:var(--paper)}
.job-header{
  display:grid;grid-template-columns:2fr 1.2fr 0.8fr 0.7fr 0.8fr 0.6fr;
  padding:12px 20px;background:var(--warm);border-bottom:1px solid var(--border);
  font-size:9px;letter-spacing:2px;text-transform:uppercase;opacity:.6;gap:12px
}
.job-row{
  display:grid;grid-template-columns:2fr 1.2fr 0.8fr 0.7fr 0.8fr 0.6fr;
  padding:18px 20px;border-bottom:1px solid var(--border);
  align-items:center;gap:12px;transition:background .1s;cursor:pointer
}
.job-row:hover{background:var(--warm)}
.job-row:last-child{border-bottom:none}
.job-title{font-weight:500;font-size:13px;margin-bottom:3px}
.job-company{font-size:10px;opacity:.5;letter-spacing:.5px}
.job-loc{font-size:11px;opacity:.6}
.score-bar{display:flex;align-items:center;gap:8px}
.score-num{font-family:var(--serif);font-size:16px;font-weight:700;min-width:32px}
.score-track{flex:1;height:3px;background:var(--border);border-radius:2px}
.score-fill{height:100%;border-radius:2px;background:var(--ink)}
.score-fill.high{background:var(--green)}
.score-fill.med{background:#b7791f}
.tag{font-size:9px;letter-spacing:1px;text-transform:uppercase;
  padding:3px 8px;border:1px solid var(--border);display:inline-block}
.tag.new{border-color:var(--green);color:var(--green)}
.tag.applied{border-color:var(--ink);background:var(--ink);color:var(--paper)}
.job-actions{display:flex;gap:6px}
.action-btn{font-family:var(--mono);font-size:9px;letter-spacing:1px;text-transform:uppercase;
  padding:5px 10px;border:1px solid var(--border);background:transparent;cursor:pointer;
  text-decoration:none;color:var(--ink);transition:all .15s}
.action-btn:hover{background:var(--ink);color:var(--paper);border-color:var(--ink)}

.empty{padding:80px;text-align:center;opacity:.4}
.empty-icon{font-size:40px;margin-bottom:16px}
.empty p{font-size:13px;line-height:1.8}

/* Scan progress */
.scan-bar{
  background:var(--ink);color:var(--paper);
  padding:12px 20px;font-size:11px;letter-spacing:1px;
  display:none;align-items:center;gap:12px;margin-bottom:20px
}
.scan-bar.show{display:flex}
.spin{animation:spin 1s linear infinite;display:inline-block}
@keyframes spin{to{transform:rotate(360deg)}}

/* Footer */
footer{text-align:center;padding:40px;font-size:10px;opacity:.3;letter-spacing:1px;text-transform:uppercase}

/* Modal */
.modal-bg{display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:100;align-items:center;justify-content:center}
.modal-bg.open{display:flex}
.modal{background:var(--paper);border:1px solid var(--border);max-width:560px;width:90%;max-height:80vh;overflow-y:auto}
.modal-header{padding:24px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:start}
.modal-title{font-family:var(--serif);font-size:20px;font-weight:700}
.modal-close{background:none;border:none;font-size:20px;cursor:pointer;opacity:.4;font-family:var(--mono)}
.modal-body{padding:24px}
.modal-field{margin-bottom:16px}
.modal-label{font-size:9px;letter-spacing:2px;text-transform:uppercase;opacity:.5;margin-bottom:6px}
.modal-value{font-size:13px;line-height:1.6}
.modal-actions{padding:24px;border-top:1px solid var(--border);display:flex;gap:10px}
</style>
</head>
<body>

<header>
  <div class="logo">
    <h1>JobHunter Pro</h1>
    <span>Segun's Dashboard · Scotland</span>
  </div>
  <div class="live">
    <div class="dot"></div>
    System Active
  </div>
</header>

<div class="main">

  <div class="stats" id="stats">
    <div class="stat">
      <div class="stat-n" id="s-total">—</div>
      <div class="stat-l">Jobs Found</div>
    </div>
    <div class="stat green">
      <div class="stat-n" id="s-cvs">—</div>
      <div class="stat-l">CVs Generated</div>
    </div>
    <div class="stat">
      <div class="stat-n" id="s-avg">—</div>
      <div class="stat-l">Avg Match %</div>
    </div>
    <div class="stat red">
      <div class="stat-n" id="s-applied">—</div>
      <div class="stat-l">Applied</div>
    </div>
  </div>

  <div class="toolbar">
    <h2>Live Job Feed</h2>
    <div class="controls">
      <button class="btn active" onclick="filterJobs('all',this)">All</button>
      <button class="btn" onclick="filterJobs('high',this)">High Match</button>
      <button class="btn" onclick="filterJobs('new',this)">Recent</button>
      <button class="btn scan" onclick="triggerScan()">↻ Scan Now</button>
    </div>
  </div>

  <div class="scan-bar" id="scanBar">
    <span class="spin">⟳</span>
    <span id="scanMsg">Scanning Reed for new jobs in Scotland...</span>
  </div>

  <div class="job-table">
    <div class="job-header">
      <div>Role</div>
      <div>Company</div>
      <div>Location</div>
      <div>Match</div>
      <div>Status</div>
      <div>Actions</div>
    </div>
    <div id="jobList">
      <div class="empty">
        <div class="empty-icon">◎</div>
        <p>Loading jobs...</p>
      </div>
    </div>
  </div>

</div>

<footer>JobHunter Pro · Running locally on your Mac · Auto-scans every 20 min</footer>

<!-- Job detail modal -->
<div class="modal-bg" id="modal">
  <div class="modal">
    <div class="modal-header">
      <div>
        <div class="modal-title" id="m-title">—</div>
        <div style="font-size:11px;opacity:.5;margin-top:4px" id="m-company">—</div>
      </div>
      <button class="modal-close" onclick="closeModal()">✕</button>
    </div>
    <div class="modal-body">
      <div class="modal-field">
        <div class="modal-label">Match Score</div>
        <div class="modal-value" id="m-score">—</div>
      </div>
      <div class="modal-field">
        <div class="modal-label">Location</div>
        <div class="modal-value" id="m-loc">—</div>
      </div>
      <div class="modal-field">
        <div class="modal-label">Scanned</div>
        <div class="modal-value" id="m-date">—</div>
      </div>
      <div class="modal-field">
        <div class="modal-label">CV Generated</div>
        <div class="modal-value" id="m-pdf">—</div>
      </div>
    </div>
    <div class="modal-actions">
      <a class="action-btn" id="m-apply" href="#" target="_blank">Apply Now →</a>
      <button class="action-btn" onclick="closeModal()">Close</button>
    </div>
  </div>
</div>

<script>
let allJobs = [];
let currentFilter = 'all';

async function loadData() {
  try {
    const r = await fetch('/api/jobs');
    const data = await r.json();
    allJobs = data.jobs || [];
    renderStats(data.stats);
    renderJobs(allJobs);
  } catch(e) {
    document.getElementById('jobList').innerHTML = `
      <div class="empty">
        <div class="empty-icon">⚠</div>
        <p>Could not load data.<br>Make sure job_hunter.py has run at least once.</p>
      </div>`;
  }
}

function renderStats(s) {
  document.getElementById('s-total').textContent   = s.total   || 0;
  document.getElementById('s-cvs').textContent     = s.cvs     || 0;
  document.getElementById('s-avg').textContent     = (s.avg_score || 0) + '%';
  document.getElementById('s-applied').textContent = s.applied || 0;
}

function renderJobs(jobs) {
  const list = document.getElementById('jobList');
  if (!jobs.length) {
    list.innerHTML = `<div class="empty"><div class="empty-icon">◎</div><p>No jobs found yet.<br>Click "Scan Now" to start.</p></div>`;
    return;
  }
  list.innerHTML = jobs.map((j,i) => {
    const score = j.score || 0;
    const cls = score >= 80 ? 'high' : score >= 60 ? 'med' : '';
    const pct = Math.min(100, score);
    const date = j.scanned ? new Date(j.scanned).toLocaleDateString('en-GB',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}) : '—';
    const isApplied = (j.applied === true);
    return `
    <div class="job-row" onclick="showModal(${i})">
      <div>
        <div class="job-title">${j.title}</div>
        <div class="job-company">${date}</div>
      </div>
      <div class="job-company" style="font-size:12px;opacity:.8">${j.company}</div>
      <div class="job-loc">${j.location || 'Scotland'}</div>
      <div class="score-bar">
        <span class="score-num">${score}%</span>
        <div class="score-track"><div class="score-fill ${cls}" style="width:${pct}%"></div></div>
      </div>
      <div><span class="tag ${isApplied ? 'applied' : 'new'}">${isApplied ? 'Applied' : 'New'}</span></div>
      <div class="job-actions" onclick="event.stopPropagation()">
        <a class="action-btn" href="${j.url || '#'}" target="_blank">Apply</a>
        ${j.pdf ? `<a class="action-btn" href="/cv/${encodeURIComponent(j.pdf.split('/').pop())}" target="_blank">CV</a>` : ''}
      </div>
    </div>`;
  }).join('');
}

function filterJobs(type, btn) {
  currentFilter = type;
  document.querySelectorAll('.controls .btn:not(.scan)').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  let filtered = allJobs;
  if (type === 'high')   filtered = allJobs.filter(j => (j.score||0) >= 75);
  if (type === 'new')    filtered = allJobs.filter(j => !j.applied);
  renderJobs(filtered);
}

function showModal(i) {
  const j = allJobs[i];
  document.getElementById('m-title').textContent   = j.title;
  document.getElementById('m-company').textContent = j.company;
  document.getElementById('m-score').textContent   = (j.score || '—') + '%';
  document.getElementById('m-loc').textContent     = j.location || 'Scotland';
  document.getElementById('m-date').textContent    = j.scanned ? new Date(j.scanned).toLocaleString('en-GB') : '—';
  document.getElementById('m-pdf').textContent     = j.pdf ? j.pdf.split('/').pop() : 'Not generated';
  const applyBtn = document.getElementById('m-apply');
  applyBtn.href = j.url || '#';
  applyBtn.style.opacity = j.url ? '1' : '.3';
  document.getElementById('modal').classList.add('open');
}

function closeModal() {
  document.getElementById('modal').classList.remove('open');
}

async function triggerScan() {
  const bar = document.getElementById('scanBar');
  const msg = document.getElementById('scanMsg');
  bar.classList.add('show');
  msg.textContent = 'Scanning Reed for new jobs in Scotland...';
  try {
    await fetch('/api/scan', {method:'POST'});
    msg.textContent = 'Scan complete! Reloading jobs...';
    setTimeout(async () => {
      await loadData();
      bar.classList.remove('show');
    }, 2000);
  } catch(e) {
    msg.textContent = 'Scan triggered — check Terminal for progress.';
    setTimeout(() => bar.classList.remove('show'), 3000);
  }
}

// Auto-refresh every 60s
loadData();
setInterval(loadData, 60000);
</script>
</body>
</html>"""

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress default logs

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == '/' or parsed.path == '/index.html':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode())

        elif parsed.path == '/api/jobs':
            data = load_data()
            stats = get_stats(data)
            # Add location field if missing
            for j in data.get("seen", []):
                if "location" not in j:
                    j["location"] = "Scotland"
            payload = json.dumps({"jobs": data.get("seen", []), "stats": stats})
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(payload.encode())

        elif parsed.path.startswith('/cv/'):
            filename = parsed.path.replace('/cv/', '')
            filepath = Path(CV_DIR) / filename
            if filepath.exists() and filepath.suffix == '.pdf':
                self.send_response(200)
                self.send_header('Content-Type', 'application/pdf')
                self.send_header('Content-Disposition', f'inline; filename="{filename}"')
                self.end_headers()
                with open(filepath, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == '/api/scan':
            # Trigger scan in background
            import threading
            def run():
                os.system('python3 job_hunter.py --scan-once')
            threading.Thread(target=run, daemon=True).start()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status":"scanning"}')
        else:
            self.send_response(404)
            self.end_headers()

if __name__ == '__main__':
    PORT = 3000
    print(f"""
+==========================================+
|     JobHunter Pro - Dashboard            |
|                                          |
|  Open in browser:                        |
|  http://localhost:{PORT}                    |
|                                          |
|  Press Ctrl+C to stop.                   |
+==========================================+
""")
    server = HTTPServer(('localhost', PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
