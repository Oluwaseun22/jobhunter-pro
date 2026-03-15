from dotenv import load_dotenv
load_dotenv()

import os, json, time, re, schedule, argparse, datetime, smtplib
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import anthropic
import requests
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib import colors

CONFIG = {
    "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY", ""),
    "REED_API_KEY":      os.getenv("REED_API_KEY", ""),
    "EMAIL_FROM":        os.getenv("EMAIL_FROM", "seguntoriola25@gmail.com"),
    "EMAIL_PASS":        os.getenv("EMAIL_PASS", ""),
    "EMAIL_TO":          os.getenv("EMAIL_TO", "seguntoriola25@gmail.com"),
    "SCAN_INTERVAL_MIN": 20,
    "MIN_MATCH_SCORE":   50,
    "LOCATION":          "Scotland, UK",
    "LOG_FILE":          "job_hunter_log.json",
    "OUTPUT_DIR":        "tailored_cvs",
}

JOB_TITLES = [
    "Data Analyst",
    "Junior Data Analyst",
    "Graduate Data Analyst",
    "IT Analyst",
    "IT Support Analyst",
    "Business Analyst",
    "Junior Business Analyst",
    "Operations Analyst",
    "Data Analyst Trainee",
    "IT Graduate",
]

MASTER_CV = {
    "name":    "Oluwasegun Toriola",
    "email":   "seguntoriola25@gmail.com",
    "phone":   "+44 07943 004361",
    "location":"Paisley, Scotland",
    "linkedin":"linkedin.com/in/oluwasegun",
    "summary": "Data and IT professional with MSc Information Technology (University of the West of Scotland, 2026) and hands-on experience in data analysis, cloud infrastructure, and operational management. Skilled in SQL, Power BI, Python, and AWS.",
    "skills": ["SQL","Power BI","Python","AWS EC2 S3 IAM VPC","Firebase Firestore","Git","Microsoft Excel","HTML CSS JavaScript","Operations management","Stakeholder communication"],
    "experience": [{"title":"Data and Operations Specialist","company":"O.S Toriola Steel Construction Company","dates":"Nov 2022 - Present","bullets":["Managed and analysed operational data to support business decisions","Built Excel dashboards tracking KPIs across construction projects","Streamlined data reporting processes reducing manual effort by 30%","Coordinated between departments to ensure accurate data flow"]}],
    "education": [{"degree":"MSc Information Technology","school":"University of the West of Scotland Paisley","dates":"2024 - Jun 2026"},{"degree":"HND Mechanical Engineering","school":"Lagos State Polytechnic","dates":"2014 - 2018"}],
    "projects": [{"name":"ENGMart Cloud Retail Platform","desc":"Full-stack e-commerce platform with Firebase Firestore real-time order syncing, EmailJS notifications, and AWS deployment.","tech":"HTML JS Firebase AWS EmailJS"}],
}

def scan_reed(title, location="Scotland"):
    print(f"  [SCAN] Searching Reed: {title} in {location}")
    key = CONFIG["REED_API_KEY"]
    if not key:
        print("  [SKIP] No Reed API key found.")
        return []
    try:
        r = requests.get("https://www.reed.co.uk/api/1.0/search", auth=(key,""),
            params={"keywords":title,"locationName":location,"resultsToTake":10}, timeout=30)
        jobs = r.json().get("results",[])
        return [{"id":str(j["jobId"]),"title":j["jobTitle"],"company":j["employerName"],
            "location":j.get("locationName",location),
            "salary":f"£{j.get('minimumSalary','')} - £{j.get('maximumSalary','')}",
            "description":j.get("jobDescription",""),"url":j.get("jobUrl",""),
            "posted":j.get("date",""),"source":"reed"} for j in jobs]
    except Exception as e:
        print(f"  [ERROR] Reed: {e}")
        return []



def scan_indeed_via_jsearch(title, location="Scotland, UK"):
    """Search Indeed jobs via JSearch RapidAPI - free tier 100 calls/day"""
    print(f"  [SCAN] Searching Indeed/JSearch: {title} in {location}")
    key = os.getenv("RAPIDAPI_KEY", "")
    if not key:
        print("  [SKIP] No RapidAPI key found.")
        return []
    try:
        r = requests.get(
            "https://jsearch.p.rapidapi.com/search",
            headers={"X-RapidAPI-Key": key, "X-RapidAPI-Host": "jsearch.p.rapidapi.com"},
            params={"query": f"{title} in {location}", "page": "1", "num_results": "10", "date_posted": "week"},
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
                "salary":      f"£{j.get('job_min_salary','')} - £{j.get('job_max_salary','')}" if j.get("job_min_salary") else "Not specified",
                "description": j.get("job_description", "")[:1000],
                "url":         j.get("job_apply_link", ""),
                "posted":      j.get("job_posted_at_datetime_utc", ""),
                "source":      "indeed",
            })
        print(f"  [SCAN] Indeed returned {len(jobs)} jobs")
        return jobs
    except Exception as e:
        print(f"  [ERROR] JSearch: {e}")
        return []

def scan_all_platforms():
    all_jobs = []
    for title in JOB_TITLES:
        all_jobs += scan_reed(title, "Scotland")
        # Only call Indeed every 3rd scan to preserve free API quota
        import time as _t
        if int(_t.time() / 3600) % 3 == 0:
            all_jobs += scan_indeed_via_jsearch(title, "Scotland, UK")
        time.sleep(0.5)
    seen = set()
    unique = []
    for j in all_jobs:
        # Deduplicate by title + company (catches same job from multiple sources)
        key = f"{j['title'].lower().strip()}_{j['company'].lower().strip()}"
        if key not in seen:
            seen.add(key)
            unique.append(j)
    print(f"[SCAN] Found {len(unique)} unique jobs.")
    return unique

BLOCKLIST = [
    "social worker", "recruitment consultant", "sales executive",
    "transport planner", "phd", "biosciences", "nuclear", "accounts graduate",
    "audit associate", "procurement", "sport operations", "school executive",
    "student success", "ethical hacker", "cyber security", "cybersecurity",
    "software developer", "web developer", "coding", "demonstrator",
    "settlements analyst", "kyc", "aml", "investment management"
]

def score_match(job):
    desc = (job.get("description","") + " " + job.get("title","")).lower()
    keywords = ["sql","power bi","python","aws","data","analyst","analytics","excel","dashboard","reporting","cloud","operations","it","business analyst","bi","database"]
    hits = sum(1 for kw in keywords if kw in desc)
    return min(100, int((hits / len(keywords)) * 120))

TAILOR_PROMPT = 'You are an expert UK CV writer. Return ONLY valid JSON no markdown: {"match_score":85,"matched_keywords":["kw1"],"summary":"3 sentences","skills":["skill1"],"experience":[{"title":"","company":"","dates":"","bullets":["b1"]}],"projects":[{"name":"","desc":"","tech":""}]}'

def tailor_cv(job):
    client = anthropic.Anthropic(api_key=CONFIG["ANTHROPIC_API_KEY"])
    print(f"  [AI] Tailoring CV for: {job['title']} at {job['company']}")
    user_msg = f"JOB: {job['title']} at {job['company']}\nDESCRIPTION: {job.get('description','')[:2000]}\nMASTER CV: {json.dumps(MASTER_CV)}"
    try:
        response = client.messages.create(model="claude-sonnet-4-20250514", max_tokens=1800,
            system=TAILOR_PROMPT, messages=[{"role":"user","content":user_msg}])
        raw = re.sub(r"```json|```","",response.content[0].text).strip()
        return json.loads(raw)
    except Exception as e:
        print(f"  [ERROR] Tailoring failed: {e}")
        return None

def generate_pdf(tailored, job, master=MASTER_CV):
    from reportlab.platypus import Table, TableStyle, HRFlowable
    from reportlab.lib.units import mm

    Path(CONFIG["OUTPUT_DIR"]).mkdir(exist_ok=True)
    filename = f"{CONFIG['OUTPUT_DIR']}/{re.sub(r'[^a-zA-Z0-9]','_',job['title'])}_{re.sub(r'[^a-zA-Z0-9]','_',job['company'])}.pdf"

    doc = SimpleDocTemplate(filename, pagesize=A4,
        rightMargin=0, leftMargin=0, topMargin=0, bottomMargin=18*mm)

    CHARCOAL = colors.HexColor("#1a1a1a")
    WHITE    = colors.HexColor("#ffffff")
    ACCENT   = colors.HexColor("#444444")
    LIGHT    = colors.HexColor("#f5f5f5")
    MIDGREY  = colors.HexColor("#888888")

    # Styles
    name_s    = ParagraphStyle("nm", fontSize=28, fontName="Helvetica-Bold",
                    textColor=WHITE, spaceAfter=4, leading=32)
    role_s    = ParagraphStyle("ro", fontSize=10, fontName="Helvetica",
                    textColor=colors.HexColor("#cccccc"), spaceAfter=6, leading=14)
    contact_s = ParagraphStyle("co", fontSize=8.5, textColor=colors.HexColor("#bbbbbb"),
                    spaceAfter=0, leading=13)
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
    skill_s   = ParagraphStyle("sk", fontSize=9.5, textColor=colors.HexColor("#222222"),
                    leading=15, spaceAfter=2)

    story = []

    # ── Dark header band ──────────────────────────────────────
    header_content = [
        [Paragraph(master["name"], name_s)],
        [Paragraph("Data &amp; IT Professional  |  MSc Information Technology", role_s)],
        [Paragraph(
            f"{master['location']}  &nbsp;&nbsp;|&nbsp;&nbsp;  {master['email']}  &nbsp;&nbsp;|&nbsp;&nbsp;  {master['phone']}  &nbsp;&nbsp;|&nbsp;&nbsp;  {master['linkedin']}",
            contact_s)],
    ]
    header_table = Table(header_content, colWidths=[210*mm])
    header_table.setStyle(TableStyle([
        ("BACKGROUND",   (0,0), (-1,-1), CHARCOAL),
        ("LEFTPADDING",  (0,0), (-1,-1), 18*mm),
        ("RIGHTPADDING", (0,0), (-1,-1), 18*mm),
        ("TOPPADDING",   (0,0), (0,0),   10*mm),
        ("BOTTOMPADDING",(0,2), (0,2),   10*mm),
        ("TOPPADDING",   (0,1), (0,2),   1*mm),
        ("VALIGN",       (0,0), (-1,-1), "TOP"),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 6*mm))

    # ── Helper: section title ─────────────────────────────────
    def section(title):
        story.append(Paragraph(title, section_s))
        story.append(HRFlowable(width="90%", thickness=0.8,
            color=colors.HexColor("#cccccc"), spaceAfter=6))

    # ── Wrap remaining content with side margins ──────────────
    def add(flowable):
        t = Table([[flowable]], colWidths=[174*mm])
        t.setStyle(TableStyle([
            ("LEFTPADDING",  (0,0), (-1,-1), 18*mm),
            ("RIGHTPADDING", (0,0), (-1,-1), 18*mm),
            ("TOPPADDING",   (0,0), (-1,-1), 0),
            ("BOTTOMPADDING",(0,0), (-1,-1), 0),
        ]))
        story.append(t)

    # ── Summary ───────────────────────────────────────────────
    section("PROFESSIONAL SUMMARY")
    add(Paragraph(tailored.get("summary", master["summary"]), body_s))

    # ── Skills two-column ─────────────────────────────────────
    section("CORE SKILLS")
    skills = tailored.get("skills", master["skills"])
    mid = (len(skills) + 1) // 2
    left_text  = "<br/>".join([f"&#8226;  {s}" for s in skills[:mid]])
    right_text = "<br/>".join([f"&#8226;  {s}" for s in skills[mid:]])
    skill_row = Table(
        [[Paragraph(left_text, skill_s), Paragraph(right_text, skill_s)]],
        colWidths=[87*mm, 87*mm]
    )
    skill_row.setStyle(TableStyle([
        ("VALIGN",       (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING",  (0,0), (-1,-1), 0),
        ("RIGHTPADDING", (0,0), (-1,-1), 0),
        ("TOPPADDING",   (0,0), (-1,-1), 0),
        ("BOTTOMPADDING",(0,0), (-1,-1), 0),
    ]))
    add(skill_row)

    # ── Experience ────────────────────────────────────────────
    section("PROFESSIONAL EXPERIENCE")
    for exp in tailored.get("experience", master["experience"]):
        row = Table(
            [[Paragraph(f"{exp['title']}  —  {exp['company']}", bold_s),
              Paragraph(exp.get("dates",""), italic_s)]],
            colWidths=[120*mm, 54*mm]
        )
        row.setStyle(TableStyle([
            ("VALIGN",       (0,0), (-1,-1), "TOP"),
            ("LEFTPADDING",  (0,0), (-1,-1), 0),
            ("RIGHTPADDING", (0,0), (-1,-1), 0),
            ("TOPPADDING",   (0,0), (-1,-1), 0),
            ("BOTTOMPADDING",(0,0), (-1,-1), 0),
            ("ALIGN",        (1,0), (1,0),   "RIGHT"),
        ]))
        add(row)
        for b in exp.get("bullets", []):
            add(Paragraph(f"&#8226;  {b}", bullet_s))
        story.append(Spacer(1, 4))

    # ── Projects ──────────────────────────────────────────────
    section("KEY PROJECTS")
    for p in tailored.get("projects", master["projects"]):
        add(Paragraph(p["name"], bold_s))
        add(Paragraph(p["desc"], body_s))
        add(Paragraph(f"<i>Technologies: {p['tech']}</i>", italic_s))
        story.append(Spacer(1, 4))

    # ── Education ─────────────────────────────────────────────
    section("EDUCATION")
    for edu in master["education"]:
        row = Table(
            [[Paragraph(edu["degree"], bold_s),
              Paragraph(edu["dates"], italic_s)]],
            colWidths=[120*mm, 54*mm]
        )
        row.setStyle(TableStyle([
            ("VALIGN",       (0,0), (-1,-1), "TOP"),
            ("LEFTPADDING",  (0,0), (-1,-1), 0),
            ("RIGHTPADDING", (0,0), (-1,-1), 0),
            ("TOPPADDING",   (0,0), (-1,-1), 0),
            ("BOTTOMPADDING",(0,0), (-1,-1), 0),
            ("ALIGN",        (1,0), (1,0),   "RIGHT"),
        ]))
        add(row)
        add(Paragraph(edu["school"], italic_s))

    doc.build(story)
    print(f"  [PDF] Generated: {filename}")
    return filename


def generate_pdf_OLD(tailored, job, master=MASTER_CV):
    Path(CONFIG["OUTPUT_DIR"]).mkdir(exist_ok=True)
    filename = f"{CONFIG['OUTPUT_DIR']}/{re.sub(r'[^a-zA-Z0-9]','_',job['title'])}_{re.sub(r'[^a-zA-Z0-9]','_',job['company'])}.pdf"
    doc = SimpleDocTemplate(filename, pagesize=A4, rightMargin=20*mm, leftMargin=20*mm, topMargin=20*mm, bottomMargin=20*mm)
    name_s    = ParagraphStyle("n",  fontSize=20, fontName="Helvetica-Bold", spaceAfter=4)
    contact_s = ParagraphStyle("c",  fontSize=9,  textColor=colors.grey, spaceAfter=12)
    section_s = ParagraphStyle("se", fontSize=11, fontName="Helvetica-Bold", textColor=colors.HexColor("#3333aa"), spaceBefore=10, spaceAfter=6)
    body_s    = ParagraphStyle("b",  fontSize=10, spaceAfter=4, leading=14)
    bullet_s  = ParagraphStyle("bu", fontSize=10, spaceAfter=3, leading=13, leftIndent=10)
    italic_s  = ParagraphStyle("i",  fontSize=9,  fontName="Helvetica-Oblique", textColor=colors.grey, spaceAfter=4)
    bold_s    = ParagraphStyle("bo", fontSize=10, fontName="Helvetica-Bold", spaceAfter=2)
    story = []
    story.append(Paragraph(master["name"], name_s))
    story.append(Paragraph(f"{master['location']} | {master['email']} | {master['phone']} | {master['linkedin']}", contact_s))
    story.append(Paragraph("PROFESSIONAL SUMMARY", section_s))
    story.append(Paragraph(tailored.get("summary", master["summary"]), body_s))
    story.append(Paragraph("CORE SKILLS", section_s))
    story.append(Paragraph(" | ".join(tailored.get("skills", master["skills"])), body_s))
    story.append(Paragraph("PROFESSIONAL EXPERIENCE", section_s))
    for exp in tailored.get("experience", master["experience"]):
        story.append(Paragraph(f"{exp['title']} - {exp['company']}", bold_s))
        story.append(Paragraph(exp.get("dates",""), italic_s))
        for b in exp.get("bullets",[]):
            story.append(Paragraph(f"- {b}", bullet_s))
        story.append(Spacer(1,4))
    story.append(Paragraph("KEY PROJECTS", section_s))
    for p in tailored.get("projects", master["projects"]):
        story.append(Paragraph(p["name"], bold_s))
        story.append(Paragraph(p["desc"], body_s))
        story.append(Paragraph(f"Tech: {p['tech']}", italic_s))
        story.append(Spacer(1,4))
    story.append(Paragraph("EDUCATION", section_s))
    for edu in master["education"]:
        story.append(Paragraph(f"{edu['degree']} - {edu['school']} | {edu['dates']}", body_s))
    doc.build(story)
    print(f"  [PDF] Generated: {filename}")
    return filename

def send_alert(job, tailored, pdf_path):
    if not CONFIG["EMAIL_PASS"]:
        print("  [SKIP] No email password configured.")
        return
    try:
        msg = MIMEMultipart()
        msg["From"] = CONFIG["EMAIL_FROM"]
        msg["To"]   = CONFIG["EMAIL_TO"]
        msg["Subject"] = f"New Job: {job['title']} at {job['company']} - {tailored.get('match_score','?')}% match"
        msg.attach(MIMEText(f"Hi Segun,\n\n{job['title']} at {job['company']}\nLocation: {job['location']}\nMatch: {tailored.get('match_score','?')}%\nApply: {job.get('url','')}\n\nCV attached.\n\nJobHunter Pro", "plain"))
        with open(pdf_path,"rb") as f:
            part = MIMEBase("application","octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f"attachment; filename={Path(pdf_path).name}")
        msg.attach(part)
        with smtplib.SMTP_SSL("smtp.gmail.com",465) as s:
            s.login(CONFIG["EMAIL_FROM"], CONFIG["EMAIL_PASS"])
            s.sendmail(CONFIG["EMAIL_FROM"], CONFIG["EMAIL_TO"], msg.as_string())
        print(f"  [EMAIL] Sent for {job['title']}")
    except Exception as e:
        print(f"  [ERROR] Email: {e}")

def load_log():
    if Path(CONFIG["LOG_FILE"]).exists():
        with open(CONFIG["LOG_FILE"]) as f: return json.load(f)
    return {"seen":[],"applied":[]}

def save_log(log):
    with open(CONFIG["LOG_FILE"],"w") as f: json.dump(log,f,indent=2)

def process_job(job, log):
    # Block irrelevant job categories
    job_text = (job.get("title","") + " " + job.get("description","")).lower()
    if any(b in job_text for b in BLOCKLIST):
        print(f"  [BLOCK] {job['title']} @ {job['company']} - irrelevant category")
        return
    score = score_match(job)
    print(f"  [MATCH] {job['title']} @ {job['company']} -> {score}%")
    if score < CONFIG["MIN_MATCH_SCORE"]:
        print(f"  [SKIP]  Below threshold")
        return
    tailored = tailor_cv(job)
    if not tailored: return
    print(f"  [AI]   Score: {tailored.get('match_score','?')}% | Keywords: {tailored.get('matched_keywords',[])}")
    pdf_path = generate_pdf(tailored, job)
    send_alert(job, tailored, pdf_path)
    log["seen"].append({"id":job["id"],"title":job["title"],"company":job["company"],
        "score":tailored.get("match_score",score),"pdf":pdf_path,
        "url":job.get("url",""),"scanned":datetime.datetime.now().isoformat()})
    save_log(log)

def run_scan():
    # Reload settings from dashboard on every scan
    if Path("dashboard_settings.json").exists():
        try:
            s = json.load(open("dashboard_settings.json"))
            if "min_match_score" in s:
                CONFIG["MIN_MATCH_SCORE"] = s["min_match_score"]
            if "scan_interval" in s:
                CONFIG["SCAN_INTERVAL_MIN"] = s["scan_interval"]
            if "job_titles" in s and s["job_titles"]:
                global JOB_TITLES
                JOB_TITLES = s["job_titles"]
        except: pass

    print(f"\n{'='*50}\n[{datetime.datetime.now().strftime('%H:%M:%S')}] Starting scan...\n{'='*50}")
    log = load_log()
    seen_ids = {j["id"] for j in log["seen"]}
    jobs = scan_all_platforms()
    new_jobs = [j for j in jobs if j["id"] not in seen_ids]
    print(f"[SCAN] {len(new_jobs)} new jobs to process.")
    for job in new_jobs:
        process_job(job, log)
        time.sleep(2)
    print(f"[DONE] Scan complete. Next scan in {CONFIG['SCAN_INTERVAL_MIN']} minutes.\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scan-once", action="store_true")
    args = parser.parse_args()
    if args.scan_once:
        run_scan()
    else:
        print("JobHunter Pro - Monitoring Mode. Ctrl+C to stop.")
        run_scan()
        schedule.every(CONFIG["SCAN_INTERVAL_MIN"]).minutes.do(run_scan)
        while True:
            schedule.run_pending()
            time.sleep(30)
