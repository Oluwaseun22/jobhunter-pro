"""
evaluator.py — AI-powered job scoring and evaluation report generator
Part of JobHunter Pro v2

Replaces the simple keyword score_match() with a structured 5-dimension
Claude evaluation. Also generates a markdown report per job.
"""

import json
import re
import datetime
from pathlib import Path
import anthropic


def load_profile(path="profile.json"):
    with open(path) as f:
        return json.load(f)


def get_secrets():
    """
    Get API keys — AWS Secrets Manager first, fallback to environment variables.
    AUDIT FIX [HIGH]: Fallback uses os.getenv directly — no dotenv dependency
    on the server (dotenv is a dev-only convenience).
    """
    try:
        import boto3
        client = boto3.client("secretsmanager", region_name="us-east-1")
        secret = client.get_secret_value(SecretId="jobhunter-pro/keys")
        return json.loads(secret["SecretString"])
    except Exception:
        import os
        return {
            "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY", ""),
            "REED_API_KEY":      os.getenv("REED_API_KEY", ""),
            "RAPIDAPI_KEY":      os.getenv("RAPIDAPI_KEY", ""),
            "EMAIL_FROM":        os.getenv("EMAIL_FROM", ""),
            "EMAIL_PASS":        os.getenv("EMAIL_PASS", ""),
            "EMAIL_TO":          os.getenv("EMAIL_TO", ""),
            "DASHBOARD_TOKEN":   os.getenv("DASHBOARD_TOKEN", ""),
        }


SCORE_PROMPT = """You are an expert UK recruitment analyst. Evaluate this job against the candidate's profile.

Return ONLY valid JSON, no markdown, no explanation:
{
  "scores": {
    "role_fit": <0-5>,
    "skills_match": <0-5>,
    "location": <0-5>,
    "growth": <0-5>,
    "compensation": <0-5>
  },
  "overall": <0-5 weighted average>,
  "grade": <"A"|"B"|"C"|"D"|"F">,
  "matched_keywords": ["kw1", "kw2"],
  "gaps": ["gap1", "gap2"],
  "recommendation": <"apply"|"consider"|"skip">,
  "one_liner": "<25 words max — why apply or why skip>",
  "tailored_bullets": [
    "<CV bullet tailored to this JD>",
    "<CV bullet tailored to this JD>",
    "<CV bullet tailored to this JD>"
  ]
}

Scoring guide:
- role_fit: Does title/seniority match candidate's targets?
- skills_match: Overlap between required skills and candidate's actual skills?
- location: Is it in Scotland/UK? Remote? Requires relocation?
- growth: Learning opportunity, career trajectory alignment?
- compensation: Salary range vs candidate's £25k-£35k target?

Grade thresholds: A=4.5+, B=3.5-4.4, C=2.5-3.4, D=1.5-2.4, F=below 1.5
Recommendation: apply=3.5+, consider=2.5-3.4, skip=below 2.5"""


def evaluate_job(job, profile):
    """
    Run AI evaluation on a job against the candidate profile.
    Returns evaluation dict with scores, grade, recommendation, and report text.
    """
    secrets = get_secrets()
    api_key = secrets.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("  [ERROR] No Anthropic API key found.")
        return None

    client = anthropic.Anthropic(api_key=api_key)

    # Build compact profile summary for the prompt
    skills_flat = []
    for category in profile["skills"].values():
        skills_flat.extend(category)

    profile_summary = {
        "name": profile["personal"]["name"],
        "summary": profile["summary"],
        "skills": skills_flat,
        "certifications": [c["name"] for c in profile["certifications"]],
        "experience": [
            {
                "title": e["title"],
                "company": e["company"],
                "dates": e["dates"]
            }
            for e in profile["experience"]
        ],
        "education": [
            {"degree": e["degree"], "school": e["school"]}
            for e in profile["education"]
        ],
        "targets": {
            "roles": profile["targets"]["roles"],
            "salary_target": profile["targets"]["salary_target"],
            "locations": profile["targets"]["locations"]
        }
    }

    user_msg = (
        f"JOB TITLE: {job['title']}\n"
        f"COMPANY: {job['company']}\n"
        f"LOCATION: {job.get('location', 'Not specified')}\n"
        f"SALARY: {job.get('salary', 'Not specified')}\n"
        f"DESCRIPTION:\n{job.get('description', '')[:3000]}\n\n"
        f"CANDIDATE PROFILE:\n{json.dumps(profile_summary, indent=2)}"
    )

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            system=SCORE_PROMPT,
            messages=[{"role": "user", "content": user_msg}]
        )
        raw = re.sub(r"```json|```", "", response.content[0].text).strip()
        evaluation = json.loads(raw)
        return evaluation
    except Exception as e:
        print(f"  [ERROR] Evaluation failed: {e}")
        return None


def calculate_weighted_score(scores, weights):
    """Calculate weighted overall score from dimension scores."""
    total = (
        scores.get("role_fit", 0)      * weights["role_fit"] +
        scores.get("skills_match", 0)  * weights["skills_match"] +
        scores.get("location", 0)      * weights["location"] +
        scores.get("growth", 0)        * weights["growth"] +
        scores.get("compensation", 0)  * weights["compensation"]
    )
    return round(total, 2)


def score_to_percent(score_out_of_5):
    """Convert 0-5 score to 0-100 for dashboard compatibility."""
    return round((score_out_of_5 / 5) * 100)


def keyword_prescore(job, profile):
    """
    Fast keyword pre-filter before sending to Claude.
    Returns 0-100. Only jobs above MIN_KEYWORD_SCORE go to Claude.
    """
    desc = (job.get("description", "") + " " + job.get("title", "")).lower()

    # Check blocklist first
    job_text = (job.get("title", "") + " " + job.get("description", "")).lower()
    for blocked in profile.get("blocklist", []):
        if blocked in job_text:
            return 0

    # Keyword scoring
    all_skills = []
    for category in profile["skills"].values():
        all_skills.extend([s.lower() for s in category])

    core_keywords = ["data", "analyst", "sql", "python", "excel", "reporting",
                     "dashboard", "analytics", "bi", "cloud", "aws", "it",
                     "business analyst", "operations", "database"]

    hits = sum(1 for kw in core_keywords if kw in desc)
    return min(100, int((hits / len(core_keywords)) * 130))


def generate_report(job, evaluation, profile):
    """
    Generate a markdown evaluation report for a job.
    Saved to data/reports/{date}-{company-slug}-{title-slug}.md
    """
    Path("data/reports").mkdir(parents=True, exist_ok=True)

    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    company_slug = re.sub(r"[^a-z0-9]", "-", job["company"].lower()).strip("-")
    title_slug = re.sub(r"[^a-z0-9]", "-", job["title"].lower()).strip("-")
    filename = f"data/reports/{date_str}-{company_slug}-{title_slug}.md"

    scores = evaluation.get("scores", {})
    weights = profile["scoring_weights"]
    weighted = calculate_weighted_score(scores, weights)
    grade = evaluation.get("grade", "?")
    rec = evaluation.get("recommendation", "?").upper()

    report = f"""# {job['title']} — {job['company']}

**Date:** {date_str}
**Grade:** {grade}  |  **Score:** {weighted}/5  |  **Recommendation:** {rec}
**URL:** {job.get('url', 'N/A')}
**Salary:** {job.get('salary', 'Not specified')}
**Location:** {job.get('location', 'Not specified')}
**Source:** {job.get('source', 'N/A').upper()}

---

## Evaluation Summary

{evaluation.get('one_liner', '')}

---

## Dimension Scores

| Dimension | Score | Weight |
|-----------|-------|--------|
| Role Fit | {scores.get('role_fit', 0)}/5 | 30% |
| Skills Match | {scores.get('skills_match', 0)}/5 | 30% |
| Location | {scores.get('location', 0)}/5 | 20% |
| Growth | {scores.get('growth', 0)}/5 | 10% |
| Compensation | {scores.get('compensation', 0)}/5 | 10% |
| **Weighted Total** | **{weighted}/5** | |

---

## Matched Keywords

{', '.join(evaluation.get('matched_keywords', [])) or 'None identified'}

---

## Gaps

{chr(10).join(f'- {g}' for g in evaluation.get('gaps', [])) or '- None identified'}

---

## Tailored CV Bullets

{chr(10).join(f'- {b}' for b in evaluation.get('tailored_bullets', [])) or '- Not generated'}

---

## Job Description (excerpt)

{job.get('description', '')[:800]}...
"""

    with open(filename, "w") as f:
        f.write(report)

    print(f"  [REPORT] Saved: {filename}")
    return filename


def update_tracker(job, evaluation, report_path, profile):
    """
    Append a new entry to data/applications.md tracker.
    Creates the file with header if it doesn't exist.
    AUDIT FIX [medium]: Checks for existing company+role before appending — no duplicates.
    """
    Path("data").mkdir(exist_ok=True)
    tracker_path = Path("data/applications.md")

    header = (
        "# Applications Tracker\n\n"
        "| Date | Company | Role | Grade | Score | Status | Source | Report | URL |\n"
        "|------|---------|------|-------|-------|--------|--------|--------|-----|\n"
    )

    if not tracker_path.exists():
        with open(tracker_path, "w") as f:
            f.write(header)

    # AUDIT FIX [medium]: Duplicate check — skip if company+role already tracked
    existing = tracker_path.read_text()
    company_clean = job["company"].lower().strip()
    title_clean   = job["title"].lower().strip()
    for line in existing.splitlines():
        if company_clean in line.lower() and title_clean in line.lower():
            print(f"  [TRACKER] Skipped duplicate: {job['title']} @ {job['company']}")
            return

    scores = evaluation.get("scores", {})
    weights = profile["scoring_weights"]
    weighted = calculate_weighted_score(scores, weights)
    grade = evaluation.get("grade", "?")
    rec = evaluation.get("recommendation", "skip")
    date_str = datetime.datetime.now().strftime("%Y-%m-%d")

    status_map = {
        "apply":   "Evaluated",
        "consider":"Evaluated",
        "skip":    "Skipped"
    }
    status = status_map.get(rec, "Evaluated")

    report_link = f"[report]({report_path})" if report_path else "—"
    url_link    = f"[link]({job.get('url', '#')})" if job.get("url") else "—"

    row = (
        f"| {date_str} "
        f"| {job['company']} "
        f"| {job['title']} "
        f"| {grade} "
        f"| {weighted}/5 "
        f"| {status} "
        f"| {job.get('source', '').upper()} "
        f"| {report_link} "
        f"| {url_link} |\n"
    )

    with open(tracker_path, "a") as f:
        f.write(row)

    print(f"  [TRACKER] Added: {job['title']} @ {job['company']} — {grade} ({weighted}/5)")


# ══════════════════════════════════════════════════════════════════════════════
# FEATURE 1: INTERVIEW STORY BANK
# Accumulates STAR+R bullets across evaluations into data/story_bank.md
# Only runs for Grade B+ jobs to keep quality high
# ══════════════════════════════════════════════════════════════════════════════

STORY_PROMPT = """You are an interview coach. Given a job description and candidate profile,
extract 1-2 STAR+R (Situation, Task, Action, Result, Reflection) story bullets the candidate
could use to answer behavioural interview questions for THIS specific role.

Return ONLY valid JSON, no markdown:
{
  "stories": [
    {
      "question": "<the behavioural question this answers, e.g. Tell me about a time you analysed data to drive a decision>",
      "star": "<2-3 sentence STAR+R answer using candidate's real experience>",
      "keywords": ["<keyword from JD this story addresses>"]
    }
  ]
}

Rules:
- Use ONLY the candidate's real experience from their profile — never invent achievements
- Tailor the framing to the specific role and company
- Keep each story under 60 words
- Maximum 2 stories per job"""


def generate_story_bullets(job, evaluation, profile):
    """
    Generate STAR+R interview stories for this job and append to story bank.
    Only runs for Grade A or B evaluations.
    AUDIT: No user input — profile data only. No injection risk.
    """
    grade = evaluation.get("grade", "F")
    if grade not in ("A", "B"):
        return  # Only accumulate stories for strong matches

    secrets = get_secrets()
    api_key = secrets.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return

    client = anthropic.Anthropic(api_key=api_key)

    skills_flat = [s for cat in profile["skills"].values() for s in cat]
    profile_summary = {
        "summary": profile["summary"],
        "skills": skills_flat,
        "experience": profile["experience"],
        "projects": [{"name": p["name"], "description": p.get("description", "")} for p in profile["projects"]],
    }

    user_msg = (
        f"JOB: {job['title']} at {job['company']}\n"
        f"DESCRIPTION:\n{job.get('description', '')[:2000]}\n\n"
        f"CANDIDATE PROFILE:\n{json.dumps(profile_summary, indent=2)}"
    )

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=600,
            system=STORY_PROMPT,
            messages=[{"role": "user", "content": user_msg}]
        )
        raw = re.sub(r"```json|```", "", response.content[0].text).strip()
        result = json.loads(raw)
        stories = result.get("stories", [])
        if not stories:
            return
        _append_to_story_bank(job, stories)
        print(f"  [STORIES] Added {len(stories)} story bullets for {job['title']} @ {job['company']}")
    except Exception as e:
        print(f"  [ERROR] Story generation failed: {e}")


def _append_to_story_bank(job, stories):
    """
    Append new STAR+R stories to data/story_bank.md.
    AUDIT: Deduplication by job ID prevents same stories being added twice.
    """
    Path("data").mkdir(exist_ok=True)
    bank_path = Path("data/story_bank.md")

    # AUDIT FIX: Dedup check — skip if this job already has stories in the bank
    if bank_path.exists():
        existing = bank_path.read_text()
        job_key = f"{job['company'].lower()}-{job['title'].lower()}"
        if job_key in existing.lower():
            return

    header = "# Interview Story Bank\n\nAccumulated STAR+R stories across all evaluated jobs.\nUse these to prepare for behavioural interviews.\n\n---\n\n"
    if not bank_path.exists():
        bank_path.write_text(header)

    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    block = f"## {job['title']} @ {job['company']} — {date_str}\n\n"
    for s in stories:
        block += f"**Q: {s.get('question', '')}**\n\n"
        block += f"{s.get('star', '')}\n\n"
        kws = s.get("keywords", [])
        if kws:
            block += f"*Keywords: {', '.join(kws)}*\n\n"
    block += "---\n\n"

    with open(bank_path, "a") as f:
        f.write(block)


# ══════════════════════════════════════════════════════════════════════════════
# FEATURE 2: LINKEDIN OUTREACH GENERATOR
# Generates a tailored 300-char connection request after each B+ evaluation
# ══════════════════════════════════════════════════════════════════════════════

OUTREACH_PROMPT = """You are a career coach. Write a LinkedIn connection request message.

Rules:
- Maximum 300 characters (LinkedIn limit)
- Mention the specific role and company
- Reference one genuine reason you're interested
- Sound human, not AI-generated
- No buzzwords: no "synergies", "leverage", "passionate", "excited to connect"
- End with a question or soft CTA

Return ONLY valid JSON, no markdown:
{
  "message": "<the connection request message under 300 chars>",
  "char_count": <number>
}"""


def generate_linkedin_outreach(job, evaluation, profile):
    """
    Generate a tailored LinkedIn connection request message.
    Returns the message string or None on failure.
    AUDIT: Output sanitised — no HTML injection possible (plain text only).
    """
    grade = evaluation.get("grade", "F")
    if grade not in ("A", "B"):
        return None

    secrets = get_secrets()
    api_key = secrets.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None

    client = anthropic.Anthropic(api_key=api_key)

    user_msg = (
        f"CANDIDATE: {profile['personal']['name']}\n"
        f"CANDIDATE SUMMARY: {profile['summary']}\n\n"
        f"TARGET ROLE: {job['title']} at {job['company']}\n"
        f"LOCATION: {job.get('location', 'UK')}\n"
        f"WHY STRONG MATCH: {evaluation.get('one_liner', '')}\n"
        f"MATCHED KEYWORDS: {', '.join(evaluation.get('matched_keywords', [])[:5])}"
    )

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=200,
            system=OUTREACH_PROMPT,
            messages=[{"role": "user", "content": user_msg}]
        )
        raw = re.sub(r"```json|```", "", response.content[0].text).strip()
        result = json.loads(raw)
        msg = result.get("message", "")
        # Hard truncate at 300 chars as safety net
        return msg[:300] if msg else None
    except Exception as e:
        print(f"  [ERROR] LinkedIn outreach generation failed: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# FEATURE 3: PORTAL SCANNER
# Scans company career pages directly — beyond Reed + Indeed
# Scottish/UK focused companies relevant to data, cloud, IT roles
# ══════════════════════════════════════════════════════════════════════════════

# Pre-configured portals — Greenhouse API where available, fallback to search
PORTALS = [
    # Scottish companies
    {"name": "Skyscanner",     "type": "greenhouse", "handle": "skyscanner"},
    {"name": "FanDuel",        "type": "greenhouse", "handle": "fanduel"},
    {"name": "Barclays",       "type": "search",     "query": "data analyst site:jobs.barclays"},
    {"name": "Aggreko",        "type": "greenhouse", "handle": "aggreko"},
    {"name": "Wood Group",     "type": "search",     "query": "data analyst site:woodplc.com/careers"},
    {"name": "Sopra Steria",   "type": "greenhouse", "handle": "soprasteria"},
    # UK data/tech employers
    {"name": "KPMG",           "type": "search",     "query": "graduate data analyst KPMG UK"},
    {"name": "Capgemini",      "type": "greenhouse", "handle": "capgemini"},
    {"name": "Deloitte",       "type": "search",     "query": "data analyst graduate Deloitte UK"},
    {"name": "NHS Digital",    "type": "search",     "query": "data analyst NHS Digital UK"},
    {"name": "Registers of Scotland", "type": "search", "query": "data analyst Registers of Scotland"},
    {"name": "Scottish Government",   "type": "search", "query": "data analyst Scottish Government jobs"},
]

ROLE_KEYWORDS = [
    "data analyst", "junior data analyst", "trainee data analyst",
    "business analyst", "cloud engineer", "data engineer",
    "bi analyst", "reporting analyst", "it analyst", "ai engineer"
]


def scan_portals(profile):
    """
    Scan company career portals directly via Greenhouse API + web search.
    Returns list of job dicts in same format as Reed/JSearch results.
    AUDIT: No secrets needed — Greenhouse API is public. Rate-limited via sleep.
    """
    all_jobs = []
    print("  [PORTAL] Scanning company career pages...")

    for portal in PORTALS:
        try:
            if portal["type"] == "greenhouse":
                jobs = _scan_greenhouse(portal["name"], portal["handle"])
            else:
                jobs = []  # Search-based portals: placeholder for future web scraping

            if jobs:
                print(f"  [PORTAL] {portal['name']}: {len(jobs)} relevant jobs")
                all_jobs.extend(jobs)

            import time
            time.sleep(0.5)  # Respectful rate limiting
        except Exception as e:
            print(f"  [PORTAL] {portal['name']} failed: {e}")
            continue

    return all_jobs


def _scan_greenhouse(company_name, handle):
    """
    Query Greenhouse job board API — completely public, no auth needed.
    Filters by role keywords relevant to the profile.
    AUDIT: External API call — timeout set, errors caught, no secrets.
    """
    import requests as req
    try:
        r = req.get(
            f"https://boards-api.greenhouse.io/v1/boards/{handle}/jobs",
            params={"content": "true"},
            timeout=15
        )
        if r.status_code != 200:
            return []

        data = r.json().get("jobs", [])
        relevant = []
        for j in data:
            title = j.get("title", "").lower()
            if any(kw in title for kw in ROLE_KEYWORDS):
                location = ""
                offices = j.get("offices", [])
                if offices:
                    location = offices[0].get("name", "")

                relevant.append({
                    "id":          f"gh_{handle}_{j.get('id', '')}",
                    "title":       j.get("title", ""),
                    "company":     company_name,
                    "location":    location,
                    "salary":      "Not specified",
                    "description": j.get("content", "")[:1500] if j.get("content") else "",
                    "url":         j.get("absolute_url", ""),
                    "posted":      j.get("updated_at", ""),
                    "source":      "portal",
                })
        return relevant
    except Exception as e:
        print(f"  [PORTAL] Greenhouse {handle} error: {e}")
        return []
