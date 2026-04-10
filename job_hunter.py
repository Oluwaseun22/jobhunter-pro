"""
JobHunter Pro v2 — Main Scanner
Scans Reed + Indeed, evaluates jobs with AI, generates tailored CVs and reports.

Run modes:
  python3 job_hunter.py              # continuous mode, scans every N minutes
  python3 job_hunter.py --scan-once  # single scan and exit
"""

import os
import json
import time
import re
import schedule
import argparse
import datetime
import smtplib
import boto3
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

import requests
import anthropic
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib import colors

from evaluator import (
    load_profile,
    evaluate_job,
    keyword_prescore,
    generate_report,
    update_tracker,
    score_to_percent,
    calculate_weighted_score,
)

# ── Config ────────────────────────────────────────────────────────────────────

PROFILE = load_profile("profile.json")
LOG_FILE = "job_hunter_log.json"
OUTPUT_DIR = "tailored_cvs"
SETTINGS_FILE = "dashboard_settings.json"
MIN_KEYWORD_PRESCORE = 25  # Below this, don't even send to Claude


def get_secrets():
    """Load API keys from AWS Secrets Manager, fallback to environment."""
    try:
        client = boto3.client("secretsmanager", region_name="us-east-1")
        secret = client.get_secret_value(SecretId="jobhunter-pro/keys")
        return json.loads(secret["SecretString"])
    except Exception:
        # Local fallback for dev
        from dotenv import load_dotenv
        load_dotenv()
        return {
            "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY", ""),
            "REED_API_KEY":      os.getenv("REED_API_KEY", ""),
            "RAPIDAPI_KEY":      os.getenv("RAPIDAPI_KEY", ""),
            "EMAIL_FROM":        os.getenv("EMAIL_FROM", ""),
            "EMAIL_PASS":        os.getenv("EMAIL_PASS", ""),
            "EMAIL_TO":          os.getenv("EMAIL_TO", ""),
        }


SECRETS = get_secrets()


def get_config():
    """Load runtime config, merging profile defaults with dashboard settings."""
    config = {
        "MIN_MATCH_SCORE":   PROFILE["targets"]["min_match_score"],
        "SCAN_INTERVAL_MIN": PROFILE["targets"]["scan_interval_min"],
        "LOCATION":          "Scotland, UK",
        "OUTPUT_DIR":        OUTPUT_DIR,
    }
    if Path(SETTINGS_FILE).exists():
        try:
            s = json.load(open(SETTINGS_FILE))
            if "min_match_score"  in s: config["MIN_MATCH_SCORE"]   = s["min_match_score"]
            if "scan_interval"    in s: config["SCAN_INTERVAL_MIN"] = s["scan_interval"]
            if "job_titles"       in s and s["job_titles"]:
                PROFILE["targets"]["roles"] = s["job_titles"]
        except Exception:
            pass
    return config


# ── Scanners ──────────────────────────────────────────────────────────────────

def scan_reed(title, location="Scotland"):
    print(f"  [SCAN] Reed: {title} in {location}")
    key = SECRETS.get("REED_API_KEY", "")
    if not key:
        print("  [SKIP] No Reed API key.")
        return []
    try:
        r = requests.get(
            "https://www.reed.co.uk/api/1.0/search",
            auth=(key, ""),
            params={"keywords": title, "locationName": location, "resultsToTake": 10},
            timeout=30
        )
        jobs = r.json().get("results", [])
        return [{
            "id":          str(j["jobId"]),
            "title":       j["jobTitle"],
            "company":     j["employerName"],
            "location":    j.get("locationName", location),
            "salary":      f"£{j.get('minimumSalary', '')} - £{j.get('maximumSalary', '')}",
            "description": j.get("jobDescription", ""),
            "url":         j.get("jobUrl", ""),
            "posted":      j.get("date", ""),
            "source":      "reed",
        } for j in jobs]
    except Exception as e:
        print(f"  [ERROR] Reed: {e}")
        return []


def scan_jsearch(title, location="Scotland, UK"):
    """Search Indeed via JSearch RapidAPI — throttled to every 3rd hour."""
    print(f"  [SCAN] JSearch: {title} in {location}")
    key = SECRETS.get("RAPIDAPI_KEY", "")
    if not key:
        print("  [SKIP] No RapidAPI key.")
        return []
    try:
        r = requests.get(
            "https://jsearch.p.rapidapi.com/search",
            headers={
                "X-RapidAPI-Key":  key,
                "X-RapidAPI-Host": "jsearch.p.rapidapi.com"
            },
            params={
                "query":       f"{title} in {location}",
                "page":        "1",
                "num_results": "10",
                "date_posted": "week"
            },
            timeout=30
        )
        data = r.json().get("data", [])
        jobs = []
        for j in data:
            jobs.append({
                "id":          f"indeed_{j.get('job_id', '')}",
                "title":       j.get("job_title", ""),
                "company":     j.get("employer_name", ""),
                "location":    j.get("job_city", location),
                "salary":      (
                    f"£{j.get('job_min_salary', '')} - £{j.get('job_max_salary', '')}"
                    if j.get("job_min_salary") else "Not specified"
                ),
                "description": j.get("job_description", "")[:1500],
                "url":         j.get("job_apply_link", ""),
                "posted":      j.get("job_posted_at_datetime_utc", ""),
                "source":      "indeed",
            })
        print(f"  [SCAN] JSearch returned {len(jobs)} jobs")
        return jobs
    except Exception as e:
        print(f"  [ERROR] JSearch: {e}")
        return []


def scan_all():
    """Scan all platforms, deduplicate by title+company."""
    all_jobs = []
    roles = PROFILE["targets"]["roles"]
    call_indeed = int(time.time() / 3600) % 3 == 0  # Every 3rd hour

    for title in roles:
        all_jobs += scan_reed(title, "Scotland")
        if call_indeed:
            all_jobs += scan_jsearch(title, "Scotland, UK")
        time.sleep(0.5)

    seen = set()
    unique = []
    for j in all_jobs:
        key = f"{j['title'].lower().strip()}_{j['company'].lower().strip()}"
        if key not in seen:
            seen.add(key)
            unique.append(j)

    # Feature 3: Portal scanner — runs every 3rd scan to avoid hammering career pages
    if int(time.time() / 3600) % 3 == 0:
        portal_jobs = scan_portals(PROFILE)
        for j in portal_jobs:
            key = f"{j['title'].lower().strip()}_{j['company'].lower().strip()}"
            if key not in seen:
                seen.add(key)
                unique.append(j)
        if portal_jobs:
            print(f"[SCAN] +{len(portal_jobs)} portal jobs added.")

    print(f"[SCAN] Found {len(unique)} unique jobs.")
    return unique


# ── CV Tailoring ──────────────────────────────────────────────────────────────

TAILOR_PROMPT = """You are an expert UK CV writer. Tailor the candidate's CV for this specific job.
Return ONLY valid JSON, no markdown:
{
  "match_score": <0-100>,
  "matched_keywords": ["kw1", "kw2"],
  "summary": "<3 sentences, positive, ATS-optimised for this role>",
  "skills": ["<skill1>", "<skill2>"],
  "experience": [
    {
      "title": "<job title>",
      "company": "<company>",
      "dates": "<dates>",
      "bullets": ["<achievement bullet 1>", "<achievement bullet 2>"]
    }
  ],
  "projects": [
    {
      "name": "<project name>",
      "desc": "<description tailored to highlight relevance to this role>",
      "tech": "<tech stack>"
    }
  ]
}
Rules: Only write positive content suitable for a professional CV. Never mention gaps or weaknesses."""


def tailor_cv(job, profile):
    """Use Claude to tailor CV content for a specific job."""
    api_key = SECRETS.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("  [ERROR] No Anthropic API key.")
        return None

    client = anthropic.Anthropic(api_key=api_key)
    print(f"  [AI] Tailoring CV for: {job['title']} at {job['company']}")

    # Build master CV summary from profile
    master = {
        "name":       profile["personal"]["name"],
        "email":      profile["personal"]["email"],
        "phone":      profile["personal"]["phone"],
        "location":   profile["personal"]["location"],
        "linkedin":   profile["personal"]["linkedin"],
        "summary":    profile["summary"],
        "skills":     [s for cat in profile["skills"].values() for s in cat],
        "experience": profile["experience"],
        "education":  profile["education"],
        "projects":   profile["projects"],
    }

    user_msg = (
        f"JOB: {job['title']} at {job['company']}\n"
        f"SALARY: {job.get('salary', 'Not specified')}\n"
        f"DESCRIPTION:\n{job.get('description', '')[:2500]}\n\n"
        f"MASTER CV:\n{json.dumps(master, indent=2)}"
    )

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            system=TAILOR_PROMPT,
            messages=[{"role": "user", "content": user_msg}]
        )
        raw = re.sub(r"```json|```", "", response.content[0].text).strip()
        return json.loads(raw)
    except Exception as e:
        print(f"  [ERROR] Tailoring failed: {e}")
        return None


# ── PDF Generation ────────────────────────────────────────────────────────────

def generate_pdf(tailored, job, profile):
    """Generate a professional PDF CV tailored to the job."""
    Path(OUTPUT_DIR).mkdir(exist_ok=True)
    master = profile["personal"]

    safe_title   = re.sub(r"[^a-zA-Z0-9]", "_", job["title"])
    safe_company = re.sub(r"[^a-zA-Z0-9]", "_", job["company"])
    filename = f"{OUTPUT_DIR}/{safe_title}_{safe_company}.pdf"

    doc = SimpleDocTemplate(
        filename, pagesize=A4,
        rightMargin=0, leftMargin=0, topMargin=0, bottomMargin=18 * mm
    )

    CHARCOAL = colors.HexColor("#1a1a1a")
    WHITE    = colors.HexColor("#ffffff")
    ACCENT   = colors.HexColor("#444444")
    MIDGREY  = colors.HexColor("#888888")

    name_s    = ParagraphStyle("nm", fontSize=28, fontName="Helvetica-Bold",
                    textColor=WHITE, spaceAfter=4, leading=32)
    role_s    = ParagraphStyle("ro", fontSize=10, fontName="Helvetica",
                    textColor=colors.HexColor("#cccccc"), spaceAfter=6, leading=14)
    contact_s = ParagraphStyle("co", fontSize=8.5,
                    textColor=colors.HexColor("#bbbbbb"), spaceAfter=0, leading=13)
    section_s = ParagraphStyle("se", fontSize=8, fontName="Helvetica-Bold",
                    textColor=ACCENT, spaceBefore=14, spaceAfter=5,
                    leading=10, letterSpacing=2)
    body_s    = ParagraphStyle("bo", fontSize=9.5, spaceAfter=4,
                    leading=14, textColor=colors.HexColor("#222222"))
    bullet_s  = ParagraphStyle("bu", fontSize=9.5, spaceAfter=3,
                    leading=13, leftIndent=10, textColor=colors.HexColor("#222222"))
    bold_s    = ParagraphStyle("bh", fontSize=10, fontName="Helvetica-Bold",
                    textColor=CHARCOAL, spaceAfter=1, leading=13)
    italic_s  = ParagraphStyle("it", fontSize=8.5, fontName="Helvetica-Oblique",
                    textColor=MIDGREY, spaceAfter=5)
    skill_s   = ParagraphStyle("sk", fontSize=9.5,
                    textColor=colors.HexColor("#222222"), leading=15, spaceAfter=2)

    story = []

    # Dark header
    header_data = [
        [Paragraph(profile["personal"]["name"], name_s)],
        [Paragraph("Data &amp; IT Professional  |  MSc Information Technology  |  AWS Certified", role_s)],
        [Paragraph(
            f"{master['location']}  &nbsp;|&nbsp;  {master['email']}  "
            f"&nbsp;|&nbsp;  {master['phone']}  &nbsp;|&nbsp;  {master['linkedin']}",
            contact_s
        )],
    ]
    header_table = Table(header_data, colWidths=[210 * mm])
    header_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), CHARCOAL),
        ("LEFTPADDING",   (0, 0), (-1, -1), 18 * mm),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 18 * mm),
        ("TOPPADDING",    (0, 0), (0, 0),   10 * mm),
        ("BOTTOMPADDING", (0, 2), (0, 2),   10 * mm),
        ("TOPPADDING",    (0, 1), (0, 2),   1 * mm),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 6 * mm))

    def section(title):
        story.append(Paragraph(title, section_s))
        story.append(HRFlowable(
            width="90%", thickness=0.8,
            color=colors.HexColor("#cccccc"), spaceAfter=6
        ))

    def add(flowable):
        t = Table([[flowable]], colWidths=[174 * mm])
        t.setStyle(TableStyle([
            ("LEFTPADDING",  (0, 0), (-1, -1), 18 * mm),
            ("RIGHTPADDING", (0, 0), (-1, -1), 18 * mm),
            ("TOPPADDING",   (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 0),
        ]))
        story.append(t)

    # Summary
    section("PROFESSIONAL SUMMARY")
    add(Paragraph(tailored.get("summary", profile["summary"]), body_s))

    # Skills (two-column)
    section("CORE SKILLS")
    skills = tailored.get("skills", [s for cat in profile["skills"].values() for s in cat])
    mid = (len(skills) + 1) // 2
    left_text  = "<br/>".join([f"&#8226;  {s}" for s in skills[:mid]])
    right_text = "<br/>".join([f"&#8226;  {s}" for s in skills[mid:]])
    skill_row = Table(
        [[Paragraph(left_text, skill_s), Paragraph(right_text, skill_s)]],
        colWidths=[87 * mm, 87 * mm]
    )
    skill_row.setStyle(TableStyle([
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING",   (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 0),
    ]))
    add(skill_row)

    # Certifications
    section("CERTIFICATIONS")
    for cert in profile.get("certifications", []):
        add(Paragraph(f"&#8226;  {cert['name']} — {cert['issuer']}, {cert['date']}", body_s))

    # Experience
    section("PROFESSIONAL EXPERIENCE")
    for exp in tailored.get("experience", profile["experience"]):
        row = Table(
            [[Paragraph(f"{exp['title']}  —  {exp['company']}", bold_s),
              Paragraph(exp.get("dates", ""), italic_s)]],
            colWidths=[120 * mm, 54 * mm]
        )
        row.setStyle(TableStyle([
            ("VALIGN",       (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING",  (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING",   (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 0),
            ("ALIGN",        (1, 0), (1, 0),   "RIGHT"),
        ]))
        add(row)
        for b in exp.get("bullets", []):
            add(Paragraph(f"&#8226;  {b}", bullet_s))
        story.append(Spacer(1, 4))

    # Projects
    section("KEY PROJECTS")
    for p in tailored.get("projects", profile["projects"]):
        add(Paragraph(p["name"], bold_s))
        add(Paragraph(p.get("desc", p.get("description", "")), body_s))
        add(Paragraph(f"<i>Technologies: {p['tech']}</i>", italic_s))
        story.append(Spacer(1, 4))

    # Education
    section("EDUCATION")
    for edu in profile["education"]:
        row = Table(
            [[Paragraph(edu["degree"], bold_s),
              Paragraph(edu["dates"], italic_s)]],
            colWidths=[120 * mm, 54 * mm]
        )
        row.setStyle(TableStyle([
            ("VALIGN",       (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING",  (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING",   (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 0),
            ("ALIGN",        (1, 0), (1, 0),   "RIGHT"),
        ]))
        add(row)
        add(Paragraph(edu["school"], italic_s))

    doc.build(story)
    print(f"  [PDF] Generated: {filename}")
    return filename


# ── Email ─────────────────────────────────────────────────────────────────────

def send_alert(job, evaluation, pdf_path):
    """Send email alert with tailored CV attached."""
    email_from = SECRETS.get("EMAIL_FROM", "")
    email_pass = SECRETS.get("EMAIL_PASS", "")
    email_to   = SECRETS.get("EMAIL_TO", email_from)

    if not email_pass:
        print("  [SKIP] No email password configured.")
        return

    grade = evaluation.get("grade", "?")
    score = evaluation.get("overall", 0)
    rec   = evaluation.get("recommendation", "").upper()

    try:
        msg = MIMEMultipart()
        msg["From"]    = email_from
        msg["To"]      = email_to
        msg["Subject"] = (
            f"[{grade}] {job['title']} @ {job['company']} — "
            f"{score}/5 · {rec}"
        )

        body = (
            f"Hi Segun,\n\n"
            f"New job evaluated:\n\n"
            f"  Role:     {job['title']}\n"
            f"  Company:  {job['company']}\n"
            f"  Location: {job.get('location', 'N/A')}\n"
            f"  Salary:   {job.get('salary', 'N/A')}\n"
            f"  Grade:    {grade} ({score}/5)\n"
            f"  Action:   {rec}\n\n"
            f"  {evaluation.get('one_liner', '')}\n\n"
            f"  Apply: {job.get('url', 'N/A')}\n\n"
            f"Tailored CV attached.\n\n"
            f"— JobHunter Pro"
        )
        msg.attach(MIMEText(body, "plain"))

        if pdf_path and Path(pdf_path).exists():
            with open(pdf_path, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f"attachment; filename={Path(pdf_path).name}"
            )
            msg.attach(part)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(email_from, email_pass)
            s.sendmail(email_from, email_to, msg.as_string())

        print(f"  [EMAIL] Sent for {job['title']} @ {job['company']}")
    except Exception as e:
        print(f"  [ERROR] Email: {e}")


# ── Log ───────────────────────────────────────────────────────────────────────

def load_log():
    if Path(LOG_FILE).exists():
        with open(LOG_FILE) as f:
            return json.load(f)
    return {"seen": [], "applied": []}


def save_log(log):
    with open(LOG_FILE, "w") as f:
        json.dump(log, f, indent=2)


# ── Job Processor ─────────────────────────────────────────────────────────────

def process_job(job, log, config):
    """Full pipeline for a single job: prescore → evaluate → tailor → PDF → email → track."""

    # 1. Fast keyword prescore (no API call)
    prescore = keyword_prescore(job, PROFILE)
    if prescore == 0:
        print(f"  [BLOCK] {job['title']} @ {job['company']} — blocklisted")
        return
    if prescore < MIN_KEYWORD_PRESCORE:
        print(f"  [SKIP]  {job['title']} @ {job['company']} — prescore {prescore} below threshold")
        return

    print(f"  [PRE]   {job['title']} @ {job['company']} — prescore {prescore}")

    # 2. AI evaluation (scoring + gaps + recommendation)
    evaluation = evaluate_job(job, PROFILE)
    if not evaluation:
        return

    overall = evaluation.get("overall", 0)
    grade   = evaluation.get("grade", "?")
    rec     = evaluation.get("recommendation", "skip")

    print(f"  [EVAL]  Grade {grade} ({overall}/5) — {rec.upper()}")

    # 3. Generate evaluation report (always, even for skips)
    report_path = generate_report(job, evaluation, PROFILE)

    # 4. Update tracker
    update_tracker(job, evaluation, report_path, PROFILE)

    # Feature 1: Story bank — accumulate STAR+R bullets for B+ jobs
    generate_story_bullets(job, evaluation, PROFILE)

    # Feature 2: LinkedIn outreach — generate connection request for B+ jobs
    linkedin_msg = generate_linkedin_outreach(job, evaluation, PROFILE)
    if linkedin_msg:
        evaluation["linkedin_outreach"] = linkedin_msg
        print(f"  [LINKEDIN] Outreach message generated")

    # 5. If below threshold, stop here
    min_score = config["MIN_MATCH_SCORE"] / 20  # Convert 0-100 to 0-5
    if overall < min_score or rec == "skip":
        print(f"  [SKIP]  Below application threshold")
        log["seen"].append({
            "id":       job["id"],
            "title":    job["title"],
            "company":  job["company"],
            "score":    score_to_percent(overall),
            "grade":    grade,
            "url":      job.get("url", ""),
            "source":   job.get("source", ""),
            "location": job.get("location", ""),
            "salary":   job.get("salary", ""),
            "scanned":  datetime.datetime.now().isoformat(),
            "report":   report_path,
            "status":   "skipped",
        })
        save_log(log)
        return

    # 6. Tailor CV
    tailored = tailor_cv(job, PROFILE)
    if not tailored:
        return

    # 7. Generate PDF
    pdf_path = generate_pdf(tailored, job, PROFILE)

    # 8. Send email alert
    send_alert(job, evaluation, pdf_path)

    # 9. Save to log
    log["seen"].append({
        "id":               job["id"],
        "title":            job["title"],
        "company":          job["company"],
        "score":            score_to_percent(overall),
        "grade":            grade,
        "pdf":              pdf_path,
        "url":              job.get("url", ""),
        "source":           job.get("source", ""),
        "location":         job.get("location", ""),
        "salary":           job.get("salary", ""),
        "scanned":          datetime.datetime.now().isoformat(),
        "report":           report_path,
        "status":           "evaluated",
        "one_liner":        evaluation.get("one_liner", ""),
        "linkedin_outreach": evaluation.get("linkedin_outreach", ""),
        "category":         _classify_role(job["title"]),
    })
    save_log(log)


# ── Role Classification ───────────────────────────────────────────────────────

ROLE_CATEGORIES = {
    "data":    ["data analyst", "bi analyst", "business intelligence", "reporting analyst",
                "insights analyst", "analytics engineer", "data scientist", "data manager"],
    "cloud":   ["cloud", "data engineer", "aws", "devops", "infrastructure", "platform engineer"],
    "it":      ["it analyst", "it support", "service desk", "systems analyst", "it graduate",
                "it operations", "technical analyst", "helpdesk"],
    "business":["business analyst", "operations analyst", "process analyst", "digital analyst",
                "project analyst", "finance analyst", "cost analyst"],
    "ai":      ["ai engineer", "ml engineer", "machine learning", "artificial intelligence",
                "llm", "nlp", "trainee ai"],
}


def _classify_role(title):
    """Classify a job title into one of 5 categories for dashboard filtering."""
    t = title.lower()
    for category, keywords in ROLE_CATEGORIES.items():
        if any(kw in t for kw in keywords):
            return category
    return "other"


# ── Main Scan Loop ────────────────────────────────────────────────────────────

def run_scan():
    config = get_config()

    print(f"\n{'=' * 52}")
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Starting scan")
    print(f"  Threshold: {config['MIN_MATCH_SCORE']}% | Roles: {len(PROFILE['targets']['roles'])}")
    print(f"{'=' * 52}")

    log      = load_log()
    seen_ids = {j["id"] for j in log["seen"]}
    jobs     = scan_all()
    new_jobs = [j for j in jobs if j["id"] not in seen_ids]

    print(f"[SCAN] {len(new_jobs)} new jobs to process.")

    for job in new_jobs:
        process_job(job, log, config)
        time.sleep(2)

    print(f"[DONE] Scan complete. Next in {config['SCAN_INTERVAL_MIN']} min.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="JobHunter Pro v2")
    parser.add_argument("--scan-once", action="store_true", help="Run one scan and exit")
    args = parser.parse_args()

    if args.scan_once:
        run_scan()
    else:
        print("JobHunter Pro v2 — Monitoring Mode. Ctrl+C to stop.")
        run_scan()
        config = get_config()
        schedule.every(config["SCAN_INTERVAL_MIN"]).minutes.do(run_scan)
        while True:
            schedule.run_pending()
            time.sleep(30)
