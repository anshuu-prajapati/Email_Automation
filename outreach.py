#!/usr/bin/env python3
"""
outreach.py — Claude writes a short, personal email to each lead; you review; it sends with your resume.

    python outreach.py draft --leads leads.csv          # 1. Claude writes drafts → outbox.csv  (nothing is sent)
    python outreach.py test                              # 2. sends 2 drafts to YOURSELF so you can see them in an inbox
    python outreach.py send                              # 3. sends approved drafts (asks you to confirm first)

SAFETY BUILT IN
  • Nothing is ever sent by `draft`. You can edit or reject any draft in outbox.csv (approved = yes/no).
  • Only emails with status valid / accept_all are used by default.
  • Daily cap (20), random 1–2.5 min gaps, weekday business hours, max 2 people per company.
  • Every sent address is logged in outreach.db, so nobody is ever emailed twice.
  • Anyone listed in do_not_contact.txt (emails or @domains) is skipped forever.

SETUP (.env, same folder)
  ANTHROPIC_API_KEY=...
  SMTP_USER=you@gmail.com
  SMTP_PASSWORD=abcdefghijklmnop       # Gmail App Password (needs 2-Step Verification), NOT your normal password
  MY_NAME=Anshu Prajapati
  MY_TARGET_ROLE=Product Analyst       # what you're looking for
  MY_PHONE=+91 ...                     # optional
  MY_LINKEDIN=https://linkedin.com/in/...   # optional
  MY_PORTFOLIO=https://...             # optional
  MY_NOTE=Immediate joiner, open to Gurugram/Noida   # optional extra context for Claude
  # SMTP_HOST=smtp.gmail.com  SMTP_PORT=465          # defaults; change for Outlook/Zoho etc.
"""

import argparse
import base64
import csv
import hashlib
import json
import logging
import os
import random
import re
import smtplib
import sys
import time
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path

try:
    import anthropic
except ImportError:
    sys.exit("pip install anthropic")
try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None
try:
    from lead_finder import Store, Serper, write_csv, ascii_lower, CONFIG as LF_CONFIG
except ImportError:
    sys.exit("outreach.py needs lead_finder.py in the same folder.")


# ════════════════════════════════════════════════════════════════════════════
#  CONFIG
# ════════════════════════════════════════════════════════════════════════════

CONFIG = {
    "model": "claude-sonnet-5",
    "resume": "resume.pdf",
    "outbox": "outbox.csv",
    "db": "outreach.db",
    "do_not_contact": "do_not_contact.txt",
    "allowed_email_status": ["valid", "accept_all"],
    "daily_limit": 20,                  # sends per day. Keep it low: this is your personal inbox.
    "delay_seconds": (60, 150),         # random gap between sends
    "business_hours": (9, 18),          # local time, Mon–Fri only (override with --now)
    "max_per_company": 2,               # never email more than this many people at one company
    "words": (45, 120),                 # body length limits
    "research_company": True,           # 1 Serper search per company for a recent, relevant detail
}

# Phrases that make an email read as templated / AI-written. Drafts containing them are rewritten.
BANNED = [
    "hope this email finds you", "hope you are doing well", "hope you're doing well", "i am writing to",
    "i'm writing to", "i came across your profile", "to whom it may concern", "dear sir", "dear madam",
    "dear hiring manager", "please find attached", "kindly", "revert", "esteemed", "thrilled", "delve",
    "passionate about", "leverage", "synergy", "game-changer", "cutting-edge", "fast-paced", "in today's",
    "i would love the opportunity", "look forward to hearing from you", "i am confident that",
    "perfect fit", "dynamic", "testament", "—",
]

ASK_BY_ROLE = {
    "Recruiter / Hiring": "ask whether they're hiring for the target role, or who handles it",
    "HR": "ask whether there's an opening for the target role, or who the right person is",
    "Founder / Owner": "say in one line how the candidate could help this company, and ask for a 10-minute chat",
    "Product": "ask if they'd be open to a quick chat about the team, or to point the candidate to the right person",
    "Senior Management": "ask if they'd point the candidate to the right person for the target role",
}

OUTBOX_COLUMNS = ["approved", "status", "person_id", "to_name", "to_email", "email_status", "company_name",
                  "job_title", "contact_type", "subject", "body", "issues", "sent_at", "message_id", "error"]

log = logging.getLogger("outreach")


# ════════════════════════════════════════════════════════════════════════════
#  STATE
# ════════════════════════════════════════════════════════════════════════════

class State:
    def __init__(self, path):
        self.kv = Store(path)                                   # reuse cache table for briefs/research
        self.db = self.kv.db
        self.db.execute("""CREATE TABLE IF NOT EXISTS sent (
            email TEXT PRIMARY KEY, name TEXT, company TEXT, subject TEXT, sent_at TEXT, message_id TEXT)""")
        self.db.commit()

    def was_sent(self, email):
        return self.db.execute("SELECT 1 FROM sent WHERE email=?", (email.lower(),)).fetchone() is not None

    def sent_today(self):
        return self.db.execute("SELECT COUNT(*) FROM sent WHERE sent_at LIKE ?",
                               (datetime.now().strftime("%Y-%m-%d") + "%",)).fetchone()[0]

    def sent_to_company(self, company):
        return self.db.execute("SELECT COUNT(*) FROM sent WHERE lower(company)=?",
                               (company.lower(),)).fetchone()[0]

    def mark_sent(self, row, message_id):
        self.db.execute("INSERT OR REPLACE INTO sent VALUES (?,?,?,?,?,?)",
                        (row["to_email"].lower(), row["to_name"], row["company_name"], row["subject"],
                         datetime.now().isoformat(timespec="seconds"), message_id))
        self.db.commit()


def load_blocklist():
    p = Path(CONFIG["do_not_contact"])
    if not p.exists():
        return set()
    return {l.strip().lower() for l in p.read_text(encoding="utf-8").splitlines() if l.strip()
            and not l.startswith("#")}


def blocked(email, blocklist):
    email = email.lower()
    return email in blocklist or ("@" + email.split("@")[-1]) in blocklist


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


# ════════════════════════════════════════════════════════════════════════════
#  PROFILE + CLAUDE
# ════════════════════════════════════════════════════════════════════════════

def profile():
    p = {k: os.getenv(k, "").strip() for k in
         ("MY_NAME", "MY_TARGET_ROLE", "MY_PHONE", "MY_LINKEDIN", "MY_PORTFOLIO", "MY_NOTE")}
    if not p["MY_NAME"]:
        sys.exit("Set MY_NAME in .env (used in the signature and the From: name).")
    return p


def signature(p):
    extra = " | ".join(x for x in (p["MY_PHONE"], p["MY_LINKEDIN"], p["MY_PORTFOLIO"]) if x)
    return f"\n\nBest,\n{p['MY_NAME']}" + (f"\n{extra}" if extra else "")


class Writer:
    def __init__(self, state, model):
        self.state, self.model = state, model
        self.client = anthropic.Anthropic()

    def _json(self, content, max_tokens=1200):
        msg = self.client.messages.create(model=self.model, max_tokens=max_tokens,
                                          messages=[{"role": "user", "content": content}])
        text = "".join(b.text for b in msg.content if b.type == "text").strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
        return json.loads(text)

    def candidate_brief(self, resume_bytes, prof):
        """Read resume.pdf once (Claude reads the PDF directly), cache the facts."""
        k = Store.key("brief", hashlib.sha1(resume_bytes).hexdigest(), prof["MY_TARGET_ROLE"], prof["MY_NOTE"])
        hit = self.state.kv.get(k)
        if hit:
            return hit
        prompt = ("Read this resume and return JSON only: {\"headline\": str, \"years_experience\": str, "
                  "\"target_role\": str, \"top_skills\": [max 6], \"proof_points\": [3-5 short, concrete facts "
                  "WITH numbers where the resume has them], \"education\": str, \"location\": str}. "
                  "Use ONLY facts written in the resume. Never add, round up or embellish anything. "
                  f"The candidate says their target role is: {prof['MY_TARGET_ROLE'] or 'infer it from the resume'}.")
        brief = self._json([
            {"type": "document",
             "source": {"type": "base64", "media_type": "application/pdf",
                        "data": base64.standard_b64encode(resume_bytes).decode()}},
            {"type": "text", "text": prompt},
        ])
        self.state.kv.set(k, brief)
        return brief

    def write(self, lead, brief, prof, notes, siblings, feedback=None):
        first = first_name(lead["to_name"])
        ask = ASK_BY_ROLE.get(lead["contact_type"], ASK_BY_ROLE["Senior Management"])
        lo, hi = CONFIG["words"]
        prompt = f"""Write one short cold email from a job seeker to one person. It must read like a real person
typed it quickly: plain words, contractions, warm but not gushing, zero hype.

RECIPIENT: {lead['to_name']} ({first}), {lead['job_title']} at {lead['company_name']}
CANDIDATE (use ONLY these facts, never invent or inflate): {json.dumps(brief, ensure_ascii=False)}
TARGET ROLE: {prof['MY_TARGET_ROLE'] or brief.get('target_role', '')}
EXTRA CONTEXT FROM CANDIDATE: {prof['MY_NOTE'] or '-'}
COMPANY NOTES (search snippets; may be irrelevant or old. Use at most ONE detail, only if clearly about this
company, and never state anything not written here. If unsure, ignore them): {notes or '-'}

STRUCTURE
- Greeting exactly: "Hi {first},"
- {lo}-{hi} words in 2-4 short paragraphs. Plain text, no bullets, no emojis, no bold.
- Open with why THIS company or THIS person, not with "I". Keep it specific and brief.
- One concrete proof point from the candidate facts (a number if there is one).
- Then: {ask}.
- Mention the attached resume once, casually (e.g. "I've attached my resume").
- Close with one low-pressure line that makes it easy to say no.
- NO sign-off and NO name at the end (a signature is added automatically).
- Subject: 3-7 words, specific and human, not "Application for..." and no clickbait.
- Never use: {', '.join(b for b in BANNED if b != '—')}. Never use em dashes.
{('- Other emails to this company already open like this, so start differently: ' + ' / '.join(siblings)) if siblings else ''}
{('FIX THESE PROBLEMS FROM YOUR LAST DRAFT: ' + '; '.join(feedback)) if feedback else ''}

Return JSON only: {{"subject": "...", "body": "..."}}"""
        return self._json(prompt)


def first_name(full):
    tok = (full or "").strip().split()
    name = tok[0].strip(".,") if tok else ""
    return name.title() if name else "there"


def check(draft, lead):
    """Returns (subject, body, issues). Fixes small things itself."""
    subject = re.sub(r"\s+", " ", str(draft.get("subject", ""))).strip().strip('"')
    body = str(draft.get("body", "")).strip()
    body = re.sub(r"\n\s*(best|best regards|regards|thanks|thank you|cheers|warm regards|sincerely)[,!.]?[ \t]*(\n.*)?$",
                  "", body, flags=re.I | re.S).strip()           # drop a sign-off line Claude added anyway
    body = body.replace(" — ", ", ").replace("—", ", ")
    issues = []
    words = len(re.findall(r"\w+", body))
    lo, hi = CONFIG["words"]
    low = body.lower() + " " + subject.lower()
    if not subject:
        issues.append("missing subject")
    if not (lo <= words <= hi + 10):
        issues.append(f"body is {words} words (want {lo}-{hi})")
    if not body.lower().startswith(f"hi {first_name(lead['to_name']).lower()}"):
        issues.append(f'must start with "Hi {first_name(lead["to_name"])},"')
    if re.search(r"\[[^\]]+\]|\{[^}]+\}|<[^>]+>", body + subject):
        issues.append("contains a placeholder like [Name]")
    if ascii_lower(lead["company_name"]).split()[0] not in ascii_lower(body + subject):
        issues.append("company name not mentioned")
    comp_low = ascii_lower(lead["company_name"])
    bad = [b for b in BANNED if b not in comp_low and
           (b in low if not b[0].isalpha() else re.search(r"\b" + re.escape(b) + r"\b", low))]
    if bad:
        issues.append(f"uses banned phrases {bad}")
    if not re.search(r"\bresume\b|\bcv\b|résumé", low):
        issues.append("doesn't mention the attached resume")
    return subject, body, issues


# ════════════════════════════════════════════════════════════════════════════
#  COMMAND: draft
# ════════════════════════════════════════════════════════════════════════════

def cmd_draft(args):
    prof = profile()
    resume = Path(CONFIG["resume"])
    if not resume.exists():
        sys.exit(f"Can't find {resume}. Put your resume in this folder as {resume.name}.")
    if not os.getenv("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is required to write the messages.")

    state = State(CONFIG["db"])
    writer = Writer(state, args.model)
    serper = Serper(os.getenv("SERPER_API_KEY"), Store(LF_CONFIG["cache_db"]))
    blocklist = load_blocklist()
    outbox_path = Path(CONFIG["outbox"])
    outbox = read_csv(outbox_path) if outbox_path.exists() else []
    drafted = {r["to_email"].lower() for r in outbox}

    log.info("Reading %s …", resume.name)
    brief = writer.candidate_brief(resume.read_bytes(), prof)
    log.info("\nWhat Claude took from your resume (check it's right — messages only use these facts):")
    for k, v in brief.items():
        log.info("  %-17s %s", k + ":", "; ".join(v) if isinstance(v, list) else v)
    log.info("")

    leads = read_csv(args.leads)
    allowed = set(args.statuses or CONFIG["allowed_email_status"])
    per_company = {}
    for r in outbox:
        per_company[r["company_name"].lower()] = per_company.get(r["company_name"].lower(), 0) + 1

    todo, skipped = [], {"no email": 0, "email status": 0, "already sent/drafted": 0, "blocked": 0, "company cap": 0}
    rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    leads.sort(key=lambda r: (rank.get(r.get("priority"), 3), -float(r.get("relevance_score") or 0)))
    for r in leads:
        email = (r.get("email") or "").strip()
        comp = r.get("company_name", "")
        if not email:
            skipped["no email"] += 1
        elif r.get("email_status") not in allowed:
            skipped["email status"] += 1
        elif email.lower() in drafted or state.was_sent(email):
            skipped["already sent/drafted"] += 1
        elif blocked(email, blocklist):
            skipped["blocked"] += 1
        elif per_company.get(comp.lower(), 0) + state.sent_to_company(comp) >= CONFIG["max_per_company"]:
            skipped["company cap"] += 1
        else:
            per_company[comp.lower()] = per_company.get(comp.lower(), 0) + 1
            todo.append(r)
    if args.limit:
        todo = todo[:args.limit]
    log.info("Drafting %d emails (skipped: %s)\n", len(todo),
             ", ".join(f"{v} {k}" for k, v in skipped.items() if v) or "none")

    notes_cache = {}
    for i, r in enumerate(todo, 1):
        lead = {"to_name": r.get("person_name", ""), "to_email": r["email"].strip(),
                "company_name": r.get("company_name", ""), "job_title": r.get("job_title", ""),
                "contact_type": r.get("contact_type", "")}
        comp = lead["company_name"]
        if CONFIG["research_company"] and not args.no_research and comp not in notes_cache:
            items = serper.search(f'"{comp}" news') if serper.key else []
            notes_cache[comp] = " || ".join(f"{x.get('title', '')}: {x.get('snippet', '')[:160]}"
                                            for x in items[:3])
        siblings = [o["body"].split("\n", 2)[-1][:60] for o in outbox if o["company_name"] == comp]

        subject, body, issues, feedback = "", "", ["not written"], None
        for attempt in range(3):
            try:
                draft = writer.write(lead, brief, prof, notes_cache.get(comp, ""), siblings, feedback)
            except Exception as e:
                issues = [f"Claude error: {e}"]
                break
            subject, body, issues = check(draft, lead)
            if not issues:
                break
            feedback = issues
        row = {**lead, "person_id": r.get("person_id", ""), "email_status": r.get("email_status", ""),
               "subject": subject, "body": body, "issues": "; ".join(issues),
               "approved": "yes" if not issues else "no",
               "status": "DRAFT" if not issues else "NEEDS_REVIEW"}
        outbox.append(row)
        write_csv(outbox_path, OUTBOX_COLUMNS, outbox)
        log.info("[%d/%d] %s — %s (%s)  %s", i, len(todo), lead["to_name"], comp, lead["contact_type"],
                 "✓" if not issues else "⚠ " + row["issues"])
        if i <= args.show:
            log.info("      Subject: %s\n%s\n", subject, "\n".join("      " + l for l in body.splitlines()))

    log.info("\nDrafts saved to %s. Open it, edit any subject/body you like, set approved=no to skip one.", outbox_path)
    log.info("Then:  python outreach.py test   (see them in your own inbox)   →   python outreach.py send")


# ════════════════════════════════════════════════════════════════════════════
#  SENDING
# ════════════════════════════════════════════════════════════════════════════

class Mailer:
    def __init__(self):
        self.host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        self.port = int(os.getenv("SMTP_PORT", "465"))
        self.user = os.getenv("SMTP_USER", "")
        self.password = os.getenv("SMTP_PASSWORD", "").replace(" ", "")
        self.from_email = os.getenv("FROM_EMAIL", self.user)
        if not (self.user and self.password):
            sys.exit("Set SMTP_USER and SMTP_PASSWORD (a Gmail App Password) in .env.")
        self.conn = None

    def connect(self):
        try:
            if self.port == 465:
                self.conn = smtplib.SMTP_SSL(self.host, self.port, timeout=60)
            else:
                self.conn = smtplib.SMTP(self.host, self.port, timeout=60)
                self.conn.starttls()
            self.conn.login(self.user, self.password)
        except smtplib.SMTPAuthenticationError:
            sys.exit("Login failed. For Gmail: turn on 2-Step Verification, create an App Password "
                     "(Google Account → Security → App passwords) and put it in SMTP_PASSWORD.")

    def build(self, prof, to_name, to_email, subject, body, resume_bytes):
        msg = EmailMessage()
        msg["From"] = formataddr((prof["MY_NAME"], self.from_email))
        msg["To"] = formataddr((to_name, to_email))
        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain=self.from_email.split("@")[-1])
        msg.set_content(body + signature(prof))
        fname = re.sub(r"[^A-Za-z0-9]+", "_", prof["MY_NAME"]).strip("_") + "_Resume.pdf"
        msg.add_attachment(resume_bytes, maintype="application", subtype="pdf", filename=fname)
        return msg

    def send(self, msg):
        for attempt in range(2):
            try:
                if self.conn is None:
                    self.connect()
                self.conn.send_message(msg)
                return
            except smtplib.SMTPServerDisconnected:
                self.conn = None
                if attempt:
                    raise

    def close(self):
        if self.conn:
            try:
                self.conn.quit()
            except Exception:
                pass


def approved_rows(outbox, state, blocklist):
    for r in outbox:
        if (r.get("approved", "").strip().lower() in ("yes", "y", "1", "true")
                and r.get("status") not in ("SENT", "FAILED")
                and r.get("subject", "").strip() and r.get("body", "").strip()
                and not state.was_sent(r["to_email"]) and not blocked(r["to_email"], blocklist)):
            yield r


def cmd_test(args):
    prof, mailer = profile(), Mailer()
    to = args.to or mailer.user
    outbox = read_csv(CONFIG["outbox"])
    rows = [r for r in outbox if r.get("body")][:args.count]
    if not rows:
        sys.exit("No drafts yet. Run: python outreach.py draft --leads leads.csv")
    resume = Path(CONFIG["resume"]).read_bytes()
    for r in rows:
        msg = mailer.build(prof, prof["MY_NAME"], to, f"[TEST → {r['to_name']}] {r['subject']}", r["body"], resume)
        mailer.send(msg)
        log.info("Sent test of %s's email to %s", r["to_name"], to)
    mailer.close()
    log.info("Check your inbox (and spam folder). Nothing was marked as sent.")


def cmd_send(args):
    prof, state = profile(), State(CONFIG["db"])
    outbox_path = Path(CONFIG["outbox"])
    if not outbox_path.exists():
        sys.exit("No outbox.csv yet. Run: python outreach.py draft --leads leads.csv")
    outbox = read_csv(outbox_path)
    queue = list(approved_rows(outbox, state, load_blocklist()))
    left_today = CONFIG["daily_limit"] - state.sent_today()
    now = datetime.now()
    start, end = CONFIG["business_hours"]

    if not queue:
        sys.exit("Nothing to send: no approved, unsent drafts.")
    if left_today <= 0:
        sys.exit(f"Daily limit of {CONFIG['daily_limit']} reached. Run again tomorrow.")
    if not args.now and (now.weekday() >= 5 or not (start <= now.hour < end)):
        sys.exit(f"It's outside weekday {start}:00–{end}:00, when replies are far less likely. "
                 "Run again during work hours, or add --now.")

    batch = queue[:min(left_today, args.max or left_today)]
    lo, hi = CONFIG["delay_seconds"]
    log.info("Ready to send %d emails (%d approved in total, %d left in today's limit).",
             len(batch), len(queue), left_today)
    log.info("Estimated time: about %d minutes.\n", len(batch) * (lo + hi) // 2 // 60)
    first = batch[0]
    log.info("First one → %s <%s>\nSubject: %s\n\n%s%s\n[attached: %s]\n", first["to_name"], first["to_email"],
             first["subject"], first["body"], signature(prof), CONFIG["resume"])
    if not args.yes and input('Type SEND to start (anything else cancels): ').strip() != "SEND":
        sys.exit("Cancelled. Nothing was sent.")

    mailer, resume = Mailer(), Path(CONFIG["resume"]).read_bytes()
    sent = 0
    try:
        for i, r in enumerate(batch, 1):
            msg = mailer.build(prof, r["to_name"], r["to_email"], r["subject"], r["body"], resume)
            try:
                mailer.send(msg)
            except smtplib.SMTPRecipientsRefused as e:
                r.update(status="FAILED", error=f"address refused: {e}")
                log.warning("[%d/%d] ✗ %s refused the address", i, len(batch), r["to_email"])
            except smtplib.SMTPDataError as e:
                if "5.4.5" in str(e) or "quota" in str(e).lower():
                    log.error("Gmail says your daily sending quota is used up. Stopping.")
                    break
                r.update(status="FAILED", error=str(e)[:200])
                log.warning("[%d/%d] ✗ %s: %s", i, len(batch), r["to_email"], e)
            else:
                state.mark_sent(r, msg["Message-ID"])
                r.update(status="SENT", sent_at=datetime.now().isoformat(timespec="seconds"),
                         message_id=msg["Message-ID"], error="")
                sent += 1
                log.info("[%d/%d] ✓ %s <%s>  (%s)", i, len(batch), r["to_name"], r["to_email"], r["company_name"])
            write_csv(outbox_path, OUTBOX_COLUMNS, outbox)
            if i < len(batch):
                time.sleep(random.uniform(lo, hi))
    except KeyboardInterrupt:
        log.info("\nStopped. Everything sent so far is recorded; re-run to continue.")
    finally:
        mailer.close()
        write_csv(outbox_path, OUTBOX_COLUMNS, outbox)
    log.info("\nSent %d today. Replies come to %s. If someone says no, add their email to %s.",
             state.sent_today(), mailer.from_email, CONFIG["do_not_contact"])


# ════════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(description="Draft, test and send personal outreach emails with your resume.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draft", help="Claude writes drafts into outbox.csv (sends nothing)")
    d.add_argument("--leads", default="leads.csv")
    d.add_argument("--limit", type=int, default=0, help="only draft N emails")
    d.add_argument("--statuses", type=lambda s: s.split(","), help="email_status values to use, e.g. valid")
    d.add_argument("--show", type=int, default=3, help="print the first N drafts")
    d.add_argument("--no-research", action="store_true", help="skip the company news search")
    d.add_argument("--model", default=CONFIG["model"])
    t = sub.add_parser("test", help="send a few drafts to yourself")
    t.add_argument("--to", help="defaults to SMTP_USER")
    t.add_argument("--count", type=int, default=2)
    s = sub.add_parser("send", help="send approved drafts")
    s.add_argument("--max", type=int, default=0, help="send at most N this run")
    s.add_argument("--now", action="store_true", help="ignore the business-hours check")
    s.add_argument("--yes", action="store_true", help="skip the SEND confirmation")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for noisy in ("httpx", "httpcore", "anthropic", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    if load_dotenv:
        load_dotenv()
    {"draft": cmd_draft, "test": cmd_test, "send": cmd_send}[args.cmd](args)


if __name__ == "__main__":
    main()