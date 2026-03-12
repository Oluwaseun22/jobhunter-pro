# JobHunter Pro 🎯
### Segun's Automated Job Application System — Built in One Night

> **Built:** 12 March 2026, 1am–5am  
> **Author:** Oluwasegun Toriola  
> **Location:** Paisley, Scotland  
> **Stack:** Python · Claude API · Reed API · ReportLab · HTML/CSS/JS

---

## What This Does

An end-to-end automated job hunting system that:

1. **Scans** Reed.co.uk every 20 minutes for new Data/IT jobs in Scotland
2. **Scores** each job against your CV using keyword matching
3. **Tailors** your CV using Claude AI for every matching job
4. **Generates** a professional PDF CV tailored to each specific role
5. **Emails** you the tailored CV with the apply link within minutes of the job being posted
6. **Displays** everything in a live web dashboard at `localhost:8080`

---

## Project Structure

```
JobHunterPro/
├── job_hunter.py          # Main scanner + AI tailoring + PDF generator
├── dashboard_server.py    # Local web dashboard (localhost:8080)
├── .env                   # API keys (never commit this)
├── job_hunter_log.json    # Log of all jobs found (auto-generated)
└── tailored_cvs/          # All generated PDF CVs (auto-generated)
    ├── IT_Desktop_Analyst_University_of_the_West_of_Scotland.pdf
    ├── Data_Analyst_Trainee_ITOL_Recruit.pdf
    └── ... (one per job)
```

---

## Setup

### 1. Prerequisites

- Python 3.11+
- MacOS / Linux
- A Reed.co.uk API key (free at reed.co.uk/developers)
- An Anthropic API key (console.anthropic.com — ~$0.01 per CV)
- A Gmail App Password (myaccount.google.com/security)

### 2. Install Dependencies

```bash
pip3 install requests anthropic reportlab python-dotenv schedule
```

### 3. Create `.env` File

```bash
nano ~/JobHunterPro/.env
```

```
ANTHROPIC_API_KEY=sk-ant-your-key-here
REED_API_KEY=your-reed-key-here
EMAIL_FROM=your@gmail.com
EMAIL_PASS=your-16-char-app-password
EMAIL_TO=your@gmail.com
```

### 4. Update Your Master CV

Edit the `MASTER_CV` dictionary in `job_hunter.py` with your real details — name, skills, experience, education, projects.

### 5. Run

**Terminal 1 — Job Scanner:**
```bash
cd ~/JobHunterPro
python3 job_hunter.py
```

**Terminal 2 — Dashboard:**
```bash
cd ~/JobHunterPro
python3 dashboard_server.py
```

Then open your browser: `http://localhost:8080`

---

## How It Works

### Job Scanning
```
Reed API → scan_all_platforms() → 57 jobs found
         → deduplicate by job ID
         → filter against seen jobs in log
         → process new jobs only
```

### Match Scoring
A fast keyword-based pre-filter scores each job 0–100 against your CV keywords. Only jobs above the `MIN_MATCH_SCORE` threshold (default: 35%) get sent to Claude for deep tailoring.

### AI CV Tailoring
```
Job description + Master CV → Claude API (claude-sonnet-4)
                            → Returns JSON: {match_score, keywords, summary, skills, experience, projects}
                            → generate_pdf() builds professional PDF
                            → send_alert() emails you with PDF attached
```

### Dashboard
A lightweight Python HTTP server reads `job_hunter_log.json` and serves a single-page dashboard. No frameworks, no dependencies — pure HTML/CSS/JS served locally.

---

## Configuration

In `job_hunter.py`, edit the `CONFIG` dict:

| Key | Default | Description |
|-----|---------|-------------|
| `MIN_MATCH_SCORE` | 35 | Minimum keyword score to send to Claude |
| `SCAN_INTERVAL_MIN` | 20 | How often to scan (minutes) |
| `LOCATION` | Scotland, UK | Job search location |
| `OUTPUT_DIR` | tailored_cvs | Where PDFs are saved |

Edit `JOB_TITLES` list to change which roles are searched.

---

## Issues & Failures (Build Log)

This system was built in a single session. Here's an honest account of everything that went wrong:

### Issue 1 — Reed API key not loading from .env
**Problem:** Script ran but showed `[SKIP] No Reed API key` even though `.env` had the key.  
**Cause:** `load_dotenv()` wasn't being called before `os.getenv()` in the CONFIG dict.  
**Fix:** Added `from dotenv import load_dotenv` and `load_dotenv()` at the very top of the file.

### Issue 2 — PDF generation failing: UnicodeEncodeError bullet point
**Problem:** `fpdf2` library crashed on `•` bullet character.  
```
UnicodeEncodeError: 'latin-1' codec can't encode character '\u2022'
```
**Cause:** `fpdf2` Helvetica font only supports latin-1 encoding. Bullet `•` is Unicode.  
**Fix:** Replaced all `•` with `-` using Python unicode replacement.

### Issue 3 — PDF generation failing: em dash character
**Problem:** Same issue with `—` em dash character (U+2014).  
**Fix:** Replaced all em dashes with regular hyphens `-`.

### Issue 4 — PDF generation failing: "Not enough horizontal space"
**Problem:** `fpdf2` multi_cell crashed with layout error.  
**Cause:** Margins were set incorrectly causing zero usable width.  
**Fix:** Switched from `fpdf2` to `reportlab` library entirely — much more robust Unicode support and layout control.

### Issue 5 — Script entry point broken after multiple edits
**Problem:** After many `sed` and Python patch commands, the `if __name__ == "__main__":` block got deleted, so `python3 job_hunter.py --scan-once` ran silently and did nothing.  
**Cause:** Cumulative edits corrupted the file structure.  
**Fix:** Rewrote the entire script from scratch as a clean file.

### Issue 6 — File creation failing on Mac
**Problem:** `cat > file.py << 'EOF'` heredoc commands were failing silently on zsh.  
**Cause:** zsh handles heredocs slightly differently to bash. Special characters in the heredoc body (backslashes, regex patterns) were being interpreted.  
**Fix:** Used `python3 -c "open(...).write(...)"` for patches, and direct `cat` with careful escaping for full file writes.

### Issue 7 — Chrome blocking localhost:5000
**Problem:** Dashboard server ran fine but Chrome showed "Access Denied" / HTTP 403.  
**Cause:** Chrome has security restrictions on certain localhost ports.  
**Fix:** Changed port from 5000 to 8080.

### Issue 8 — PDF design too plain
**Problem:** Initial PDF CVs were functional but visually basic — single column skills, no visual hierarchy.  
**Fix:** Rewrote `generate_pdf()` using ReportLab Tables for two-column skills layout, bold charcoal header block, section dividers with HRFlowable, and proper typography hierarchy.

### Issue 9 — HRFlowable unexpected keyword argument
**Problem:** 
```
TypeError: HRFlowable.__init__() got an unexpected keyword argument 'leftIndent'
```
**Cause:** ReportLab's `HRFlowable` doesn't support `leftIndent`.  
**Fix:** Removed the `leftIndent` argument.

### Issue 10 — AI writing negative things in CV summaries
**Problem:** Claude was being too honest — writing things like *"lacking specific AI/LLM expertise required for this senior role"* inside the actual CV.  
**Cause:** The tailor prompt didn't explicitly say to only write positive content suitable for a CV.  
**Fix:** Raised `MIN_MATCH_SCORE` to 35% to filter out clearly unsuitable roles before they reach Claude.

---

## Results (First Night)

- **57 jobs** found on first scan
- **22 CVs** generated automatically
- **£0.00** infrastructure cost (runs locally)
- **~£0.25** in Claude API costs for 22 tailored CVs
- **Top match:** Data Analyst Trainee @ ITOL Recruit — 92%
- **Priority application:** IT Desktop Analyst @ University of the West of Scotland — 78% — interviews week of 30 March 2026

---

## Limitations & Known Issues

- **Reed only** — Indeed scanning requires RapidAPI key (paid). LinkedIn scraping violates ToS.
- **One CV on Reed profile** — Reed only allows one saved CV, so auto-applying with role-specific CVs requires manual upload per application.
- **Mac must be on** — System only runs while your MacBook is open. Future improvement: deploy to AWS EC2 free tier for 24/7 monitoring.
- **Match scoring is basic** — The keyword pre-filter is simple and scores many jobs low. Claude's real scoring is much more accurate.
- **Email alerts require Gmail App Password** — Some Google Workspace/university accounts block this.

---

## Future Improvements

- [ ] Deploy scanner to AWS EC2 free tier for 24/7 monitoring
- [ ] Add LinkedIn job scanning
- [ ] Add S1Jobs.com (Scottish jobs board) scanning  
- [ ] Improve keyword scoring with TF-IDF or semantic matching
- [ ] Add "Mark as Applied" button on dashboard
- [ ] Auto-generate cover letters per job
- [ ] Add Slack/WhatsApp notifications instead of email
- [ ] Store CVs in S3 and serve from dashboard

---

## Cost Breakdown

| Item | Cost |
|------|------|
| Reed API | Free |
| Anthropic Claude API | ~£0.01 per CV tailored |
| ReportLab | Free |
| Dashboard server | Free (local) |
| **Total for 22 CVs** | **~£0.22** |

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Job scanning | Reed.co.uk REST API |
| AI tailoring | Claude claude-sonnet-4 via Anthropic API |
| PDF generation | ReportLab |
| Email alerts | Python smtplib + Gmail SMTP |
| Dashboard | Pure HTML/CSS/JS + Python HTTPServer |
| Scheduling | Python `schedule` library |
| Config | python-dotenv |

---

*Built in one session, 12 March 2026. Paisley, Scotland.*
