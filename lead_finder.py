#!/usr/bin/env python3
"""
lead_finder.py — company CSV  ->  senior people at each company  ->  work emails  ->  leads CSV

FREE-TIER STACK
  Hunter.io   domain lookup (free) + domain search / email finder / verifier (50 credits/month free)
  Serper.dev  Google "X-ray" search of public LinkedIn profiles (2,500 free searches on signup)
  Claude      OPTIONAL — only called for edge cases the rules can't settle (tiny, pay-per-use)

SETUP
  pip install requests anthropic python-dotenv
  Create a .env file next to this script:
      HUNTER_API_KEY=xxxx
      SERPER_API_KEY=xxxx
      ANTHROPIC_API_KEY=xxxx      # optional

RUN
  python lead_finder.py --input tier2_ai_companies_delhi_ncr.csv
  python lead_finder.py --input companies.csv --max-companies 5 --budget 20
  python lead_finder.py --input companies.csv --roles hr,recruiter,founder
  python lead_finder.py --input companies.csv --free-only        # spend 0 Hunter credits

Every API response is cached in lead_finder_cache.db, so re-running (after a crash,
Ctrl+C, or next month) never pays twice for the same lookup.
"""

import argparse
import csv
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import time
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlparse

import requests

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None
try:
    import anthropic
except ImportError:
    anthropic = None


# ════════════════════════════════════════════════════════════════════════════
#  CONFIG — edit this section to change who you're looking for
# ════════════════════════════════════════════════════════════════════════════

CONFIG = {
    "max_people_per_company": 5,      # keep only the top N people per company
    "hunter_search_limit": 3,         # emails pulled per company via Domain Search (~1 credit each, free plan max 10)
    "serper_results": 10,             # Google results per X-ray query
    "serper_region": "in",            # Google country (in = India)
    "location_hint": "",              # e.g. "Delhi" to bias X-ray search; "" = anywhere
    "startup_max_employees": 200,     # at or below this, a company counts as a startup
    "verify_pattern_emails": True,    # spend 0.5 credit to verify emails built from a pattern
    "min_score": 60,                  # drop people scoring below this
    "claude_model": "claude-haiku-4-5-20251001",
    "cache_db": "lead_finder_cache.db",
    "request_timeout": 30,
}

# Order matters: the first group whose pattern matches a title wins.
TARGET_ROLES = {
    "recruiter": {
        "label": "Recruiter / Hiring",
        "department": "Talent Acquisition",
        "patterns": [r"recruit", r"talent acquisition", r"\bta (lead|manager|partner|head)\b",
                     r"\bhiring\b", r"\bsourcer\b", r"campus (hiring|relations)"],
        "search_terms": ["recruiter", "talent acquisition"],
        "hunter_department": "hr",
        "score": 95,
    },
    "hr": {
        "label": "HR",
        "department": "HR",
        "patterns": [r"\bhr\b", r"human resource", r"\bhrbp\b", r"\bchro\b", r"head of people",
                     r"people (ops|operations|partner|team|function|lead|and culture|& culture)"],
        "search_terms": ["HR manager", "HR business partner"],
        "hunter_department": "hr",
        "score": 90,
    },
    "founder": {
        "label": "Founder / Owner",
        "department": "Leadership",
        "patterns": [r"founder", r"\bowner\b", r"\bceo\b", r"chief executive", r"managing director",
                     r"\bproprietor\b"],
        "search_terms": ["founder", "CEO"],
        "hunter_department": "executive",
        "score": 95,
        "startup_only": True,          # only kept when the company is a startup
    },
    "product": {
        "label": "Product",
        "department": "Product",
        "patterns": [r"product manager", r"product (lead|head|owner|director)", r"head of product",
                     r"\bcpo\b", r"chief product", r"(vp|vice president|director|head),? (of )?product", r"group product"],
        "search_terms": ["product manager"],
        "hunter_department": "product",
        "score": 85,
    },
    "senior_mgmt": {
        "label": "Senior Management",
        "department": "Management",
        "patterns": [r"senior manager", r"\bsr\.? manager", r"\bdirector\b", r"\bhead\b", r"\bvp\b",
                     r"vice president", r"general manager", r"\bcto\b", r"\bcoo\b", r"\bcxo\b",
                     r"engineering manager", r"\bchief\b"],
        "search_terms": ["senior manager", "director"],
        "hunter_department": "management",
        "score": 75,
    },
}

# Titles matching any of these are dropped (junior roles, ex-employees, job seekers).
EXCLUDE_PATTERNS = [
    r"\bintern(ship)?\b", r"\btrainee\b", r"\bstudent\b", r"\bfresher\b", r"\bjunior\b", r"\bjr\.?\b",
    r"\bassociate\b(?!.*\b(director|vp|vice president)\b)",      # keeps "Associate Director"
    r"\bassistant\b(?!.*\b(director|vice president)\b)",         # drops "Assistant Manager"
    r"\bexecutive\b(?!.*\b(director|officer|vp)\b)",             # drops "HR Executive", keeps "Chief Executive Officer"
    r"\bex[- ]", r"\bformer(ly)?\b", r"aspiring", r"seeking", r"open to work", r"looking for",
]

OUTPUT_COLUMNS = [
    "person_id", "company_id", "company_name", "company_domain", "person_linkedin_url", "person_name",
    "job_title", "department", "seniority", "profile_summary", "location",
    "email", "email_status", "email_confidence", "email_source",
    "relevance_score", "contact_type", "priority", "recommended_action",
    "connection_message", "connection_status", "connection_sent_at",
    "followup_message", "followup_status", "followup_sent_at",
    "response_status", "response", "referral_status", "last_action", "next_action", "error",
]

COMPANY_COLUMNS = ["company_id", "company_name", "linkedin_url", "domain", "domain_source",
                   "is_startup", "people_found", "emails_found", "error"]

log = logging.getLogger("lead_finder")


# ════════════════════════════════════════════════════════════════════════════
#  STORAGE — response cache + monthly credit ledger (SQLite)
# ════════════════════════════════════════════════════════════════════════════

class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS cache (k TEXT PRIMARY KEY, v TEXT, ts REAL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS credits (month TEXT PRIMARY KEY, used REAL)")
        self.db.commit()

    @staticmethod
    def key(*parts):
        return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()

    def get(self, k):
        row = self.db.execute("SELECT v FROM cache WHERE k=?", (k,)).fetchone()
        return json.loads(row[0]) if row else None

    def set(self, k, v):
        self.db.execute("INSERT OR REPLACE INTO cache VALUES (?,?,?)", (k, json.dumps(v), time.time()))
        self.db.commit()

    def credits_used(self):
        row = self.db.execute("SELECT used FROM credits WHERE month=?", (_month(),)).fetchone()
        return row[0] if row else 0.0

    def add_credits(self, n):
        self.db.execute("INSERT INTO credits VALUES (?,?) ON CONFLICT(month) DO UPDATE SET used=used+?",
                        (_month(), n, n))
        self.db.commit()


def _month():
    return datetime.now().strftime("%Y-%m")


class Budget:
    """Tracks Hunter credits this script is allowed to spend this month."""

    def __init__(self, store, limit, free_only):
        self.store, self.limit, self.free_only, self.exhausted = store, limit, free_only, False
        self.remote_left, self.run_spent = None, 0.0   # real balance reported by Hunter at start

    def left(self):
        if self.free_only or self.exhausted:
            return 0.0
        local = self.limit - self.store.credits_used()
        if self.remote_left is not None:
            local = min(local, self.remote_left - self.run_spent)
        return max(0.0, local)

    def can(self, n):
        return self.left() >= n

    def spend(self, n):
        if n > 0:
            self.store.add_credits(n)
            self.run_spent += n


# ════════════════════════════════════════════════════════════════════════════
#  HTTP + PROVIDERS
# ════════════════════════════════════════════════════════════════════════════

SESSION = requests.Session()


class OutOfCredits(Exception):
    pass


def http(method, url, *, params=None, json_body=None, headers=None, retries=3):
    last = ""
    for attempt in range(retries):
        try:
            r = SESSION.request(method, url, params=params, json=json_body, headers=headers,
                                timeout=CONFIG["request_timeout"])
        except requests.RequestException as e:
            last = str(e)
            time.sleep(2 ** attempt)
            continue
        if r.status_code in (200, 201):
            return r.json()
        if r.status_code == 202:                       # Hunter verifier still working
            time.sleep(3)
            continue
        if r.status_code == 429 and "hunter.io" in url:  # Hunter: monthly usage limit reached
            raise OutOfCredits(r.text[:200])
        if r.status_code == 451:                       # person opted out — respect it
            return {"_claimed": True}
        if r.status_code in (403, 429) or r.status_code >= 500:
            last = f"{r.status_code} {r.text[:200]}"
            time.sleep(2 ** attempt * 2)
            continue
        return {"_error": r.status_code, "_body": r.text[:300]}
    return {"_error": "retries_exhausted", "_body": last}


class Hunter:
    BASE = "https://api.hunter.io/v2"

    def __init__(self, key, store, budget):
        self.key, self.store, self.budget = key, store, budget

    def _get(self, path, params, cost_check=0.0):
        """Cached GET. Returns (data, from_cache) or (None, False)."""
        if not self.key:
            return None, False
        k = Store.key("hunter", path, params)
        hit = self.store.get(k)
        if hit is not None:
            return hit, True
        if cost_check and not self.budget.can(cost_check):
            return None, False
        try:
            res = http("GET", f"{self.BASE}/{path}", params={**params, "api_key": self.key})
        except OutOfCredits:
            log.warning("Hunter says your monthly credits are used up. Continuing with free sources only.")
            self.budget.exhausted = True
            return None, False
        if res is None or "_error" in res:
            log.debug("Hunter %s error: %s", path, res)
            return None, False
        self.store.set(k, res)
        return res, False

    def account(self):
        if not self.key:
            return None
        res = http("GET", f"{self.BASE}/account", params={"api_key": self.key})
        return (res or {}).get("data")

    def domain_finder(self, company):                                 # FREE
        res, _ = self._get("domain-finder", {"company": company, "limit": 5})
        return (res or {}).get("data") or []

    def domain_search(self, domain, departments, limit):              # ~1 credit per email returned
        params = {"domain": domain, "type": "personal", "seniority": "senior,executive",
                  "department": ",".join(sorted(departments)), "limit": limit}
        res, cached = self._get("domain-search", params, cost_check=limit)
        data = (res or {}).get("data")
        if data and not cached:
            self.budget.spend(len(data.get("emails") or []))
        return data

    def email_finder(self, domain, first, last, linkedin_handle=""):  # 1 credit if found
        params = {"domain": domain}
        if first and last:
            params.update(first_name=first, last_name=last)
        elif linkedin_handle:
            params["linkedin_handle"] = linkedin_handle
        else:
            return None
        res, cached = self._get("email-finder", params, cost_check=1)
        data = (res or {}).get("data")
        if data and data.get("email") and not cached:
            self.budget.spend(1)
        return data

    def verify(self, email):                                          # 0.5 credit
        res, cached = self._get("email-verifier", {"email": email}, cost_check=0.5)
        data = (res or {}).get("data")
        if data and not cached:
            self.budget.spend(0.5)
        return data


class Serper:
    URL = "https://google.serper.dev/search"

    def __init__(self, key, store):
        self.key, self.store = key, store

    def search(self, query):
        if not self.key:
            return []
        body = {"q": query, "num": CONFIG["serper_results"], "gl": CONFIG["serper_region"]}
        k = Store.key("serper", body)
        hit = self.store.get(k)
        if hit is None:
            hit = http("POST", self.URL, json_body=body,
                       headers={"X-API-KEY": self.key, "Content-Type": "application/json"})
            if not hit or "_error" in hit:
                log.debug("Serper error: %s", hit)
                return []
            self.store.set(k, hit)
        return hit.get("organic") or []


class Claude:
    """Only used when rules can't decide. Everything works without it."""

    SYSTEM = ("You are a precise data-cleaning helper for a B2B lead list. "
              "Reply with valid JSON only: no prose, no code fences. Never invent facts; use null when unsure.")

    def __init__(self, store):
        self.store = store
        self.client = None
        if anthropic and os.getenv("ANTHROPIC_API_KEY"):
            self.client = anthropic.Anthropic()

    def ask(self, task, payload):
        if not self.client:
            return None
        k = Store.key("claude", CONFIG["claude_model"], task, payload)
        hit = self.store.get(k)
        if hit is not None:
            return hit
        try:
            msg = self.client.messages.create(
                model=CONFIG["claude_model"], max_tokens=1500, system=self.SYSTEM,
                messages=[{"role": "user",
                           "content": f"{task}\n\nINPUT:\n{json.dumps(payload, ensure_ascii=False)}"}],
            )
            text = "".join(b.text for b in msg.content if b.type == "text").strip()
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
            out = json.loads(text)
        except Exception as e:
            log.warning("Claude call skipped (%s)", e)
            return None
        self.store.set(k, out)
        return out

    def classify_titles(self, titles, allowed):
        cats = {k: TARGET_ROLES[k]["label"] for k in allowed}
        task = ("Map each job title to one category key from CATEGORIES, or \"none\" if the person is junior, "
                "an individual contributor below manager level, not currently in the role, or fits no category. "
                f"CATEGORIES: {json.dumps(cats)}. Return an object {{title: key_or_none}}.")
        res = self.ask(task, titles)
        if isinstance(res, list):                    # e.g. [{"title": ..., "category": ...}]
            out = {}
            for item in res:
                if isinstance(item, dict):
                    t = item.get("title")
                    v = item.get("category") or item.get("key") or item.get("value")
                    if t:
                        out[t] = v
            return out
        return res if isinstance(res, dict) else {}

    def pick_domain(self, company, linkedin_slug, candidates):
        task = ("Pick the official corporate email domain for this company from the candidates. "
                "Return {\"domain\": \"<one of the candidates>\"} or {\"domain\": null} if none clearly fits.")
        res = self.ask(task, {"company": company, "linkedin_slug": linkedin_slug, "candidates": candidates})
        if isinstance(res, str):
            return res
        return res.get("domain") if isinstance(res, dict) else None

    def is_startup(self, company, industry):
        task = (f"Is this company a startup with roughly {CONFIG['startup_max_employees']} employees or fewer? "
                "Return {\"startup\": true|false|null}. Use null if you do not know the company.")
        res = self.ask(task, {"company": company, "industry": industry})
        if isinstance(res, bool):
            return res
        val = res.get("startup") if isinstance(res, dict) else None
        return val if isinstance(val, bool) else None

    def parse_profiles(self, company, items):
        task = (f"These are Google results for LinkedIn profiles, searched for people at \"{company}\". "
                "For each, extract the person's name and CURRENT job title, and whether they currently work at "
                "that company. Return a list of {\"i\": int, \"name\": str|null, \"title\": str|null, "
                "\"works_there_now\": bool}.")
        res = self.ask(task, items)
        if isinstance(res, dict):                    # e.g. {"results": [...]}
            res = next((v for v in res.values() if isinstance(v, list)), [])
        return [x for x in res if isinstance(x, dict)] if isinstance(res, list) else []


# ════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ════════════════════════════════════════════════════════════════════════════

def norm(s):
    return re.sub(r"[^a-z0-9]", "", ascii_lower(s))


def ascii_lower(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def similarity(a, b):
    a, b = norm(a), norm(b)
    return SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def domain_from_url(u):
    u = (u or "").strip()
    if not u:
        return ""
    if "://" not in u:
        u = "http://" + u
    host = urlparse(u).netloc.lower().split(":")[0]
    host = host[4:] if host.startswith("www.") else host
    return "" if (not host or "linkedin.com" in host or "." not in host) else host


def linkedin_company_slug(url):
    m = re.search(r"linkedin\.com/company/([^/?#]+)", url or "", re.I)
    return m.group(1).lower() if m else ""


def clean_profile_url(url):
    m = re.search(r"linkedin\.com/in/([^/?#]+)", url or "", re.I)
    return f"https://www.linkedin.com/in/{m.group(1)}/" if m else ""


def parse_size(raw):
    """'501-1,000 employees' -> 1000, '10,001+' -> 10001, '' -> None"""
    nums = [int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", raw or "")]
    return max(nums) if nums else None


def clean_name(raw):
    s = re.sub(r"\(.*?\)", "", raw or "")
    s = s.split(",")[0]
    s = re.sub(r"^(dr|mr|mrs|ms|ca|er|adv)\.?\s+", "", s.strip(), flags=re.I)
    s = "".join(ch for ch in s if ch.isalpha() or ch in " .'-")
    return re.sub(r"\s+", " ", s).strip()


def split_name(name):
    tokens = [t.strip(".") for t in name.split() if t.strip(".")]
    if not tokens:
        return "", ""
    return tokens[0], (tokens[-1] if len(tokens) > 1 else "")


def email_from_pattern(pattern, first, last, domain):
    f, l = re.sub(r"[^a-z]", "", ascii_lower(first)), re.sub(r"[^a-z]", "", ascii_lower(last))
    if not f or (("{last}" in pattern or "{l}" in pattern) and not l):
        return ""
    local = (pattern.replace("{first}", f).replace("{last}", l)
             .replace("{f}", f[:1]).replace("{l}", l[:1]))
    return "" if "{" in local else f"{local}@{domain}"


def seniority_of(title):
    t = title.lower()
    if re.search(r"founder|owner|\bceo\b|chief|\bc[a-z]o\b|\bvp\b|vice president|\bhead\b|director|president", t):
        return "executive"
    if re.search(r"senior|\bsr\b|\blead\b|principal|manager|\bstaff\b", t):
        return "senior"
    return "mid"


def tidy_title(title, company, role_key):
    t = re.sub(r"\s*(?:\bat\b|@)\s*" + re.escape(company) + r"\b.*$", "", title or "", flags=re.I).strip()
    parts = [x.strip() for x in re.split(r"\s*[|•·]\s*", t) if x.strip()]
    if len(parts) > 1 and role_key in TARGET_ROLES:
        pats = TARGET_ROLES[role_key]["patterns"]
        parts = [x for x in parts if any(re.search(pt, x.lower()) for pt in pats)] or parts
    return parts[0] if parts else (title or "")


def rule_classify(title, allowed):
    t = (title or "").lower()
    if not t:
        return None, "no_title"
    if any(re.search(p, t) for p in EXCLUDE_PATTERNS):
        return None, "excluded"
    for key, role in TARGET_ROLES.items():
        if key in allowed and any(re.search(p, t) for p in role["patterns"]):
            return key, "rule"
    return None, "unmatched"


def parse_serp_item(item, company_name):
    url = clean_profile_url(item.get("link", ""))
    if not url:
        return None
    title, snippet = item.get("title", ""), item.get("snippet", "")
    head = re.split(r"\s*[|｜]\s*LinkedIn", title)[0].replace("...", "").replace("…", "")
    parts = [p.strip() for p in re.split(r"\s+[-–—]\s+", head) if p.strip()]
    name = clean_name(parts[0]) if parts else ""
    job = parts[1] if len(parts) > 1 else ""
    seen_company = parts[2] if len(parts) > 2 else ""
    if job and similarity(job, company_name) >= 0.85:           # "Name - Company | LinkedIn"
        seen_company, job = job, ""
    text = ascii_lower(f"{title} {snippet}")
    cn = ascii_lower(company_name)
    mentions = similarity(seen_company, company_name) >= 0.8 or norm(company_name) in norm(text)
    former = re.search(r"\b(ex|former|formerly|previously)\b[\s\-@]*" + re.escape(cn), text)
    return {"linkedin_url": url, "name": name, "title": job, "current": bool(mentions and not former),
            "snippet": snippet[:300], "needs_llm": not name or not job}


# ════════════════════════════════════════════════════════════════════════════
#  PIPELINE
# ════════════════════════════════════════════════════════════════════════════

COLUMN_ALIASES = {
    "name": ["companyname", "company", "name", "organization", "organisation"],
    "linkedin": ["linkedinurl", "linkedin", "companylinkedin", "linkedinpage", "linkedincompanyurl"],
    "website": ["website", "domain", "url", "companywebsite", "site"],
    "size": ["companysize", "size", "employees", "headcount", "employeecount"],
    "industry": ["industry", "industrysector", "sector"],
    "id": ["companyid", "id"],
}


def load_companies(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        sys.exit(f"{path} is empty.")
    by_norm = {norm(h): h for h in rows[0].keys()}
    col = {field: next((by_norm[a] for a in aliases if a in by_norm), None)
           for field, aliases in COLUMN_ALIASES.items()}
    if not col["name"]:
        sys.exit(f"Couldn't find a company-name column in {path}. Headers: {list(rows[0].keys())}")

    companies, seen = [], set()
    for row in rows:
        get = lambda f: (row.get(col[f]) or "").strip() if col[f] else ""
        name = get("name")
        if not name:
            continue
        slug = linkedin_company_slug(get("linkedin"))
        dedupe = slug or norm(name)
        if dedupe in seen:
            continue
        seen.add(dedupe)
        companies.append({
            "company_id": get("id") or f"C{len(companies) + 1:04d}",
            "name": name, "linkedin_url": get("linkedin"), "slug": slug,
            "website": get("website"), "size_raw": get("size"), "industry": get("industry"),
        })
    return companies


class App:
    def __init__(self, args):
        self.args = args
        self.store = Store(CONFIG["cache_db"])
        self.budget = Budget(self.store, args.budget, args.free_only)
        self.hunter = Hunter(os.getenv("HUNTER_API_KEY"), self.store, self.budget)
        self.serper = Serper(os.getenv("SERPER_API_KEY"), self.store)
        self.claude = Claude(self.store)
        self.roles = [r for r in TARGET_ROLES if r in args.roles] if args.roles else list(TARGET_ROLES)

    # ── Stage 2: domain ──────────────────────────────────────────────────────
    def resolve_domain(self, c):
        d = domain_from_url(c["website"])
        if d:
            return d, "input"
        cands = [x for x in self.hunter.domain_finder(c["name"]) if x.get("domain")]
        if not cands:
            return "", "not_found"
        best = max(cands, key=lambda x: similarity(c["name"], x.get("company_name", "")))
        if len(cands) == 1 or similarity(c["name"], best.get("company_name", "")) >= 0.85:
            return best["domain"], "hunter"
        picked = self.claude.pick_domain(c["name"], c["slug"], [x["domain"] for x in cands])
        if picked in {x["domain"] for x in cands}:
            return picked, "claude"
        return best["domain"], "hunter_low_confidence"

    def startup_status(self, c):
        size = parse_size(c["size_raw"])
        if size is not None:
            return size <= CONFIG["startup_max_employees"]
        if "founder" not in self.roles:
            return None
        return self.claude.is_startup(c["name"], c["industry"])

    # ── Stage 3: people ──────────────────────────────────────────────────────
    def xray_query(self, c, roles):
        terms = [t for r in roles for t in TARGET_ROLES[r]["search_terms"]]
        loc = f' "{CONFIG["location_hint"]}"' if CONFIG["location_hint"] else ""
        return f'site:linkedin.com/in "{c["name"]}" ({" OR ".join(f"{chr(34)}{t}{chr(34)}" for t in terms)}){loc}'

    def discover(self, c, domain, roles):
        people, pattern = {}, None

        def add(p):
            k = p.get("linkedin_url") or norm(p.get("name", ""))
            if not k:
                return
            for e in people.values():                     # merge same person from 2 sources
                if norm(e.get("name", "")) and norm(e.get("name", "")) == norm(p.get("name", "")):
                    for f, v in p.items():
                        if v and not e.get(f):
                            e[f] = v
                    return
            people[k] = p

        # A) Hunter Domain Search — real emails + the company's email pattern
        depts = {TARGET_ROLES[r]["hunter_department"] for r in roles}
        data = self.hunter.domain_search(domain, depts, CONFIG["hunter_search_limit"])  # cache first, then budget
        if data:
            pattern = data.get("pattern")
            for e in data.get("emails") or []:
                name = " ".join(x for x in [e.get("first_name"), e.get("last_name")] if x)
                add({"name": name, "title": e.get("position") or "",
                     "linkedin_url": clean_profile_url(e.get("linkedin") or ""),
                     "email": e.get("value", ""),
                     "email_status": (e.get("verification") or {}).get("status") or "unknown",
                     "email_confidence": e.get("confidence", ""), "email_source": "hunter_domain_search",
                     "snippet": "", "source": "hunter"})

        # B) Serper X-ray — public LinkedIn profiles (free)
        parsed = [p for p in (parse_serp_item(it, c["name"]) for it in self.serper.search(self.xray_query(c, roles)))
                  if p]
        unclear = [p for p in parsed if p["needs_llm"]]
        if unclear:
            fixes = self.claude.parse_profiles(c["name"], [{"i": i, "result": p["snippet"], "url": p["linkedin_url"]}
                                                           for i, p in enumerate(unclear)])
            for fx in fixes:
                i = fx.get("i")
                if isinstance(i, int) and 0 <= i < len(unclear):
                    unclear[i]["name"] = clean_name(fx.get("name") or unclear[i]["name"])
                    unclear[i]["title"] = fx.get("title") or unclear[i]["title"]
                    unclear[i]["current"] = bool(fx.get("works_there_now"))
        for p in parsed:
            if p["current"] and p["name"]:
                add({**p, "email": "", "source": "serper"})
        return list(people.values()), pattern

    # ── Stage 4: classify + score ────────────────────────────────────────────
    def score(self, people, roles, is_startup):
        unmatched = []
        for p in people:
            p["role"], p["why"] = rule_classify(p["title"], roles)
            if p["why"] == "unmatched":
                unmatched.append(p["title"])
        if unmatched:
            llm = self.claude.classify_titles(sorted(set(unmatched)), roles)
            for p in people:
                if p["why"] == "unmatched" and llm.get(p["title"]) in roles:
                    p["role"], p["why"] = llm[p["title"]], "claude"

        kept = []
        for p in people:
            if not p["role"]:
                continue
            role = TARGET_ROLES[p["role"]]
            if role.get("startup_only") and is_startup is False:
                continue
            p["seniority"] = seniority_of(p["title"])
            s = role["score"] + {"executive": 5, "senior": 0, "mid": -25}[p["seniority"]]
            if role.get("startup_only") and is_startup is None:
                s -= 15                                   # unknown company size -> less sure
            p["relevance_score"] = max(0, min(100, s))
            if p["relevance_score"] >= CONFIG["min_score"]:
                kept.append(p)
        kept.sort(key=lambda p: (-p["relevance_score"], not p.get("email")))
        return kept[:CONFIG["max_people_per_company"]]

    # ── Stages 5–6: email + verify ───────────────────────────────────────────
    def find_email(self, p, domain, pattern):
        """Fills p['email'] and writes WHY into p['email_note'] (-> 'error' column)."""
        if p.get("email"):
            return
        notes = []
        first, last = split_name(p["name"])
        if not first:
            notes.append("name unreadable")
        elif not pattern:
            notes.append("company email format unknown")
        else:
            e = email_from_pattern(pattern, first, last, domain)
            if not e:
                notes.append(f"format {pattern} needs a last name")
            else:
                p.update(email=e, email_status="pattern_unverified", email_confidence=50,
                         email_source="hunter_pattern")
                if not CONFIG["verify_pattern_emails"]:
                    return
                if not self.budget.can(0.5):
                    p["email_note"] = "not verified: no credits left"
                    return
                v = self.hunter.verify(e)
                if not v:
                    p["email_note"] = "verification failed, try again later"
                    return
                p.update(email_status=v.get("status", "unknown"), email_confidence=v.get("score", ""))
                if v.get("status") != "invalid":
                    return
                notes.append(f"{e} rejected by mail server")
                p.update(email="", email_status="", email_confidence="", email_source="")

        handle = (re.search(r"/in/([^/]+)/", p.get("linkedin_url", "")) or [None, ""])[1]
        if not self.budget.can(1):
            notes.append("Email Finder skipped: no credits left")
        else:
            r = self.hunter.email_finder(domain, first, last, handle)
            if r and r.get("email"):
                p.update(email=r["email"], email_status=(r.get("verification") or {}).get("status") or "unknown",
                         email_confidence=r.get("score", ""), email_source="hunter_finder", email_note="")
                return
            notes.append("Hunter has no record of this person")

        if self.args.guess_emails and first and last:
            p.update(email=email_from_pattern("{first}.{last}", first, last, domain),
                     email_status="unverified_guess", email_confidence=15, email_source="guess",
                     email_note="; ".join(notes))
            return
        p.update(email="", email_status="not_found", email_confidence="", email_source="",
                 email_note="; ".join(notes))

    # ── One company end-to-end ───────────────────────────────────────────────
    def process(self, c):
        domain, dsrc = self.resolve_domain(c)
        c.update(domain=domain, domain_source=dsrc)
        if not domain:
            c["error"] = "domain_not_found"
            return []
        is_startup = self.startup_status(c)
        c["is_startup"] = "" if is_startup is None else is_startup
        roles = [r for r in self.roles if not (TARGET_ROLES[r].get("startup_only") and is_startup is False)]
        if not roles:
            return []
        people, pattern = self.discover(c, domain, roles)
        people = self.score(people, roles, is_startup)
        for p in people:
            self.find_email(p, domain, pattern)
        c["people_found"] = len(people)
        c["emails_found"] = sum(1 for p in people if p.get("email"))
        return people


def to_row(pid, c, p):
    role = TARGET_ROLES[p["role"]]
    good = p.get("email_status") in ("valid", "accept_all")
    s = p["relevance_score"]
    return {
        "person_id": f"P{pid:05d}", "company_id": c["company_id"], "company_name": c["name"],
        "company_domain": c.get("domain", ""), "person_linkedin_url": p.get("linkedin_url", ""),
        "person_name": p.get("name", ""), "job_title": tidy_title(p.get("title", ""), c["name"], p["role"]), "department": role["department"],
        "seniority": p.get("seniority", ""), "profile_summary": p.get("snippet", ""), "location": "",
        "email": p.get("email", ""), "email_status": p.get("email_status", ""),
        "email_confidence": p.get("email_confidence", ""), "email_source": p.get("email_source", ""),
        "relevance_score": s, "contact_type": role["label"],
        "priority": "HIGH" if s >= 90 else "MEDIUM" if s >= 75 else "LOW",
        "recommended_action": ("SEND_EMAIL" if good else "VERIFY_THEN_EMAIL" if p.get("email")
                               else "LINKEDIN_CONNECT"),
        "connection_status": "NEW", "response_status": "NOT_CONTACTED", "referral_status": "NOT_REQUESTED",
        "error": p.get("email_note", ""),
    }


_fallbacks = {}   # locked file name -> the one side file used for this run


def write_csv(path, columns, rows):
    """Write atomically. If Windows/Excel/OneDrive has the file locked, retry,
    then save to a side file instead of crashing."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    for attempt in range(5):
        try:
            tmp.replace(path)
            return path
        except PermissionError:
            time.sleep(1 + attempt)                  # OneDrive locks usually clear in a few seconds
    first_time = path.name not in _fallbacks
    fallback = _fallbacks.setdefault(
        path.name, path.with_name(f"{path.stem}_{datetime.now():%Y%m%d_%H%M%S}{path.suffix}"))
    tmp.replace(fallback)
    if first_time:
        log.warning("   ⚠  %s is locked (open in Excel?). Saved to %s instead — close it and it'll be used again.",
                    path.name, fallback.name)
    return fallback


def main():
    ap = argparse.ArgumentParser(description="Find senior people + work emails for a list of companies.")
    ap.add_argument("--input", required=True, help="CSV with company name (+ LinkedIn URL / website optional)")
    ap.add_argument("--output", default="leads.csv")
    ap.add_argument("--budget", type=float, default=45, help="max Hunter credits to spend this month (free plan = 50)")
    ap.add_argument("--max-companies", type=int, default=0, help="only process the first N companies (0 = all)")
    ap.add_argument("--roles", type=lambda s: [x.strip() for x in s.split(",") if x.strip()],
                    help=f"comma list from: {','.join(TARGET_ROLES)}")
    ap.add_argument("--location", default=None, help='bias X-ray search, e.g. "Delhi"')
    ap.add_argument("--free-only", action="store_true", help="never spend Hunter credits")
    ap.add_argument("--guess-emails", action="store_true",
                    help="as a last resort write first.last@domain, clearly marked unverified_guess")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(message)s")
    for noisy in ("httpx", "httpcore", "anthropic", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    if load_dotenv:
        load_dotenv()
    if args.location is not None:
        CONFIG["location_hint"] = args.location
    if args.roles and (bad := [r for r in args.roles if r not in TARGET_ROLES]):
        sys.exit(f"Unknown role group(s): {bad}. Choose from {list(TARGET_ROLES)}")

    for k, why in [("HUNTER_API_KEY", "domains + emails"), ("SERPER_API_KEY", "LinkedIn X-ray search")]:
        if not os.getenv(k):
            log.warning("⚠  %s not set — %s will be skipped.", k, why)
    if not os.getenv("ANTHROPIC_API_KEY"):
        log.info("ℹ  ANTHROPIC_API_KEY not set — running rules-only (that's fine).")

    app = App(args)
    if (acct := app.hunter.account()):
        reqs = acct.get("requests", {}) if isinstance(acct, dict) else {}
        remaining = (reqs.get("credits") or {}).get("remaining") if isinstance(reqs, dict) else None
        if isinstance(remaining, (int, float)):
            app.budget.remote_left = float(remaining)
            log.info("Hunter account: %.1f credits remaining this month", remaining)
    log.info("Budget this month: %.1f credits left of %.0f  |  roles: %s\n",
             app.budget.left(), args.budget, ", ".join(app.roles))

    companies = load_companies(args.input)
    if args.max_companies:
        companies = companies[:args.max_companies]
    out_path = Path(args.output)
    comp_path = out_path.with_name(out_path.stem + "_companies.csv")
    rows, pid = [], 0
    saved_leads, saved_comp = out_path, comp_path

    try:
        for i, c in enumerate(companies, 1):
            log.info("[%d/%d] %s", i, len(companies), c["name"])
            try:
                people = app.process(c)
            except Exception as e:                       # one bad company never kills the run
                log.error("   ✗ %s: %s", type(e).__name__, e, exc_info=args.verbose)
                c["error"] = str(e)[:200]
                people = []
            for p in people:
                pid += 1
                rows.append(to_row(pid, c, p))
            log.info("   domain=%s (%s)  people=%s  emails=%s  credits_left=%.1f",
                     c.get("domain") or "-", c.get("domain_source", ""), c.get("people_found", 0),
                     c.get("emails_found", 0), app.budget.left())
            saved_leads = write_csv(out_path, OUTPUT_COLUMNS, rows)     # save after every company
            saved_comp = write_csv(comp_path, COMPANY_COLUMNS,
                      [{**x, "company_name": x["name"]} for x in companies[:i]])
    except KeyboardInterrupt:
        log.info("\nStopped — progress saved. Re-run the same command to continue (cached calls are free).")

    emails = sum(1 for r in rows if r["email"])
    log.info("\nDone: %d people, %d with email → %s  (company summary → %s)", len(rows), emails, saved_leads, saved_comp)


if __name__ == "__main__":
    main()