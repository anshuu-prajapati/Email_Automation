#!/usr/bin/env python3
"""
company_finder.py — a Claude agent that finds tier-2 / tier-3 companies
(100–10,000 employees) and their LinkedIn company pages.

Its output CSV plugs straight into lead_finder.py:

    python company_finder.py --location "Delhi NCR" --industry "AI, SaaS, fintech" --count 30
    python lead_finder.py   --input companies_found.csv

HOW IT WORKS
  Claude runs a tool loop. It decides what to search, judges each company's tier,
  and only saves companies that pass hard checks done in Python:
    discover_companies   Hunter Discover: companies by city + headcount + industry   (FREE)
    google_search        Serper Google search, to check a company it's unsure about  (free quota)
    find_linkedin_page   Serper: site:linkedin.com/company "<name>"                 (free quota)
    save_company         validates the LinkedIn URL, size bucket, tier, duplicates → writes CSV

SETUP
  Same folder and .env as lead_finder.py (it reuses its cache + HTTP helpers).
  Needs ANTHROPIC_API_KEY (required here), HUNTER_API_KEY, SERPER_API_KEY.
"""

import argparse
import csv
import json
import logging
import os
import re
import sys
from datetime import datetime
from difflib import get_close_matches
from pathlib import Path

try:
    import anthropic
except ImportError:
    sys.exit("Install the Claude SDK first:  pip install anthropic")
try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

try:
    from lead_finder import (Store, Serper, http, OutOfCredits, norm, domain_from_url,
                             linkedin_company_slug, CONFIG as LF_CONFIG)
except ImportError:
    sys.exit("company_finder.py needs lead_finder.py in the same folder.")


# ════════════════════════════════════════════════════════════════════════════
#  CONFIG
# ════════════════════════════════════════════════════════════════════════════

CFG = {
    "model": "claude-sonnet-5",       # --model claude-haiku-4-5-20251001 is cheaper but judges tiers less well
    "max_turns": 40,                  # hard stop for the agent loop
    "max_google_searches": 120,       # Serper calls per run (google_search + find_linkedin_page)
    "max_discover_calls": 30,         # Hunter Discover calls per run (free, but be polite)
}

# Hunter / LinkedIn size buckets
ALL_BUCKETS = ["1-10", "11-50", "51-200", "201-500", "501-1000", "1001-5000", "5001-10000", "10001+"]

# Edit these to change what "tier 2" and "tier 3" mean for you.
TIER_GUIDE = """\
Tier 1 — SKIP: globally famous brands and India's best-known giants. Big Tech / FAANG, large MNCs,
         household-name unicorns and large listed companies (e.g. Google, Microsoft, Amazon, Flipkart,
         Paytm, Infosys, Reliance).
Tier 2 — KEEP: well known inside their industry but not household names. Established product or tech
         companies, funded scale-ups (roughly Series B or later), recognised mid-size brands and
         respected employers.
Tier 3 — KEEP: smaller established companies. Regional or niche players, growing startups with real
         traction, solid services / consulting firms: genuine operating businesses that are lesser known.
Skip anything defunct, acquired and merged away, a shell / directory listing, a staffing agency's
fake page, or a company you cannot identify with reasonable confidence."""

OUTPUT_COLUMNS = ["company_id", "company_name", "linkedin_url", "website", "company_size", "industry",
                  "headquarters", "tier", "reason", "source", "found_at"]

log = logging.getLogger("company_finder")
INDUSTRIES_URL = "https://hunter.io/files/industries.json"


# ════════════════════════════════════════════════════════════════════════════
#  TOOLS (Python side) — Claude calls these; Python enforces the rules
# ════════════════════════════════════════════════════════════════════════════

class Toolbox:
    def __init__(self, args, store, buckets, out_path):
        self.args, self.store, self.buckets, self.out_path = args, store, buckets, out_path
        self.hunter_key = os.getenv("HUNTER_API_KEY")
        self.serper = Serper(os.getenv("SERPER_API_KEY"), store)
        self.google_calls = self.discover_calls = 0
        self.domain_bucket = {}            # domain -> size bucket learned from Discover
        self.saved_rows, self.new_count = [], 0
        self.seen_slugs, self.seen_domains, self.seen_names = set(), set(), set()
        self.next_id = 1
        self._industries = None
        self._load_existing()
        self._load_excludes()

    # ── bookkeeping ──────────────────────────────────────────────────────────
    def _remember(self, name, slug, domain):
        if slug:
            self.seen_slugs.add(slug)
        if domain:
            self.seen_domains.add(domain)
        if name:
            self.seen_names.add(norm(name))

    def _is_dup(self, name, slug, domain):
        return (slug and slug in self.seen_slugs) or (domain and domain in self.seen_domains) \
            or (norm(name) in self.seen_names)

    def _read_csv(self, path):
        with open(path, newline="", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))

    def _load_existing(self):
        """Resume: companies already in the output file count as done."""
        if not self.out_path.exists():
            return
        for r in self._read_csv(self.out_path):
            self.saved_rows.append(r)
            self._remember(r.get("company_name"), linkedin_company_slug(r.get("linkedin_url", "")),
                           domain_from_url(r.get("website", "")))
            m = re.match(r"C(\d+)$", r.get("company_id", ""))
            if m:
                self.next_id = max(self.next_id, int(m.group(1)) + 1)
        log.info("Resuming: %d companies already in %s", len(self.saved_rows), self.out_path.name)

    def _load_excludes(self):
        for path in self.args.exclude or []:
            if not Path(path).exists():
                log.warning("Exclude file not found: %s", path)
                continue
            n = 0
            for r in self._read_csv(path):
                lower = {re.sub(r"[^a-z]", "", k.lower()): v for k, v in r.items() if k}
                name = lower.get("companyname") or lower.get("company") or lower.get("name") or ""
                link = lower.get("linkedinurl") or lower.get("linkedin") or ""
                site = lower.get("website") or lower.get("domain") or ""
                self._remember(name, linkedin_company_slug(link), domain_from_url(site))
                n += 1
            log.info("Excluding %d companies from %s", n, path)

    def industries(self):
        if self._industries is None:
            k = Store.key("hunter_industries")
            self._industries = self.store.get(k)
            if not self._industries:
                try:
                    import requests
                    self._industries = requests.get(INDUSTRIES_URL, timeout=30).json()
                    self.store.set(k, self._industries)
                except Exception:
                    self._industries = []
        return self._industries

    def _map_industries(self, wanted):
        valid = self.industries()
        lower = {v.lower(): v for v in valid}
        mapped, unknown = [], []
        for w in wanted or []:
            if w.lower() in lower:
                mapped.append(lower[w.lower()])
                continue
            wl = w.lower()
            contains = sorted((v for v in lower if re.search(r"\b" + re.escape(wl) + r"\b", v)), key=len)[:3]
            close = get_close_matches(wl, list(lower), n=2, cutoff=0.75)
            picks = [lower[v] for v in (contains or close)]
            if picks:
                mapped.extend(picks)
            else:
                unknown.append(w)
        return sorted(set(mapped)), unknown

    # ── tool: discover_companies ─────────────────────────────────────────────
    def discover_companies(self, headcount, cities=None, country="IN", industries=None,
                           keywords=None, query=None):
        if not self.hunter_key:
            return "ERROR: HUNTER_API_KEY is not set, so Discover is unavailable. Use google_search instead."
        if headcount not in self.buckets:
            return f"ERROR: headcount must be ONE of {self.buckets}."
        if self.discover_calls >= CFG["max_discover_calls"]:
            return "ERROR: Discover call limit reached for this run. Work with the companies you already have."
        body = {"headcount": [headcount]}
        notes = []
        if cities:
            body["headquarters_location"] = {"include": [{"city": c, "country": country} for c in cities]}
        elif country:
            body["headquarters_location"] = {"include": [{"country": country}]}
        if industries:
            mapped, unknown = self._map_industries(industries)
            if mapped:
                body["industry"] = {"include": mapped}
                notes.append(f"industries used: {mapped}")
            if unknown:
                notes.append(f"no Hunter industry matched {unknown}; try keywords instead")
        if keywords:
            body["keywords"] = {"include": keywords, "match": "any"}
        if query:
            body["query"] = query

        k = Store.key("hunter_discover", body)
        res = self.store.get(k)
        if res is None:
            self.discover_calls += 1
            try:
                res = http("POST", "https://api.hunter.io/v2/discover",
                           params={"api_key": self.hunter_key}, json_body=body)
            except OutOfCredits:
                return "ERROR: Hunter usage limit reached. Use google_search to find companies instead."
            if not res or "_error" in res:
                return f"ERROR from Hunter: {json.dumps(res)[:300]}"
            self.store.set(k, res)

        rows, skipped = [], 0
        for c in res.get("data") or []:
            d = (c.get("domain") or "").lower()
            name = c.get("organization") or d
            if not d or self._is_dup(name, "", d):
                skipped += 1
                continue
            self.domain_bucket[d] = headcount
            rows.append(f"{name} | {d}")
        head = (f"{len(rows)} companies with {headcount} employees"
                f"{' (' + '; '.join(notes) + ')' if notes else ''}; {skipped} skipped as duplicates/excluded.\n"
                "Format: organization | domain. The free plan returns one page per filter combination, "
                "so vary the city, industry, keywords or bucket to get more.")
        return head + ("\n" + "\n".join(rows) if rows else "\n(no new companies — change the filters)")

    # ── tool: google_search ──────────────────────────────────────────────────
    def _serper(self, q):
        if not self.serper.key:
            return None, "ERROR: SERPER_API_KEY is not set."
        if self.google_calls >= CFG["max_google_searches"]:
            return None, "ERROR: Google search limit reached for this run. Save what you have verified and stop."
        self.google_calls += 1
        return self.serper.search(q), None

    def google_search(self, query):
        items, err = self._serper(query)
        if err:
            return err
        if not items:
            return "No results."
        return "\n".join(f"- {i.get('title', '')} | {i.get('link', '')} | {i.get('snippet', '')[:220]}"
                         for i in items[:10])

    # ── tool: find_linkedin_page ─────────────────────────────────────────────
    def find_linkedin_page(self, company_name, domain=""):
        items, err = self._serper(f'site:linkedin.com/company "{company_name}"')
        if err:
            return err
        cands, seen = [], set()
        base = (domain or "").split(".")[0].lower()
        for i in items or []:
            slug = linkedin_company_slug(i.get("link", ""))
            if not slug or slug in seen or slug.startswith(("jobs", "showcase")):
                continue
            seen.add(slug)
            text = f"{i.get('title', '')} {i.get('snippet', '')}".lower()
            hint = []
            if domain and domain.lower() in text:
                hint.append("DOMAIN MATCH")
            if base and base in slug:
                hint.append("slug matches domain")
            cands.append(f"- https://www.linkedin.com/company/{slug}/ | {i.get('title', '')} | "
                         f"{i.get('snippet', '')[:220]}{'  [' + ', '.join(hint) + ']' if hint else ''}")
        if not cands:
            return "No LinkedIn company page found. Try a shorter or alternate name, or skip this company."
        return "Candidates (pick only one that is clearly the same company, or none):\n" + "\n".join(cands[:6])

    # ── tool: save_company ───────────────────────────────────────────────────
    def save_company(self, company_name, linkedin_url, tier, size_bucket, domain="", industry="",
                     hq_city="", reason=""):
        slug = linkedin_company_slug(linkedin_url)
        domain = domain_from_url(domain) if domain else ""
        if not slug:
            return "REJECTED: linkedin_url must be a linkedin.com/company/<slug> URL taken from find_linkedin_page."
        if tier not in self.args.tiers:
            return f"REJECTED: only tiers {self.args.tiers} are wanted."
        known = self.domain_bucket.get(domain)
        if known and size_bucket != known:
            size_bucket = known                                     # trust the filter that found it
        if size_bucket not in self.buckets:
            return f"REJECTED: size {size_bucket} is outside the wanted range {self.buckets}."
        if self._is_dup(company_name, slug, domain):
            return "REJECTED: duplicate or excluded company. Move on to the next one."

        row = {
            "company_id": f"C{self.next_id:04d}", "company_name": company_name.strip(),
            "linkedin_url": f"https://www.linkedin.com/company/{slug}/", "website": domain,
            "company_size": f"{size_bucket} employees", "industry": industry, "headquarters": hq_city,
            "tier": tier, "reason": reason[:300],
            "source": "hunter_discover" if known else "google", "found_at": datetime.now().isoformat(timespec="seconds"),
        }
        self.next_id += 1
        self.saved_rows.append(row)
        self.new_count += 1
        self._remember(company_name, slug, domain)
        self._write()
        log.info("   ✅ [%d/%d] %s (tier %s, %s) → %s", self.new_count, self.args.count, company_name,
                 tier, size_bucket, row["linkedin_url"])
        if self.new_count >= self.args.count:
            return f"Saved. TARGET REACHED ({self.new_count}/{self.args.count}). Stop now and write a 2-line summary."
        return f"Saved ({self.new_count}/{self.args.count})."

    def _write(self):
        tmp = self.out_path.with_name(self.out_path.name + ".tmp")
        with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
            w.writeheader()
            w.writerows(self.saved_rows)
        try:
            tmp.replace(self.out_path)
        except PermissionError:
            alt = self.out_path.with_name(f"{self.out_path.stem}_unlocked{self.out_path.suffix}")
            tmp.replace(alt)
            log.warning("   ⚠  %s is open in Excel — saved to %s", self.out_path.name, alt.name)

    # ── dispatcher ───────────────────────────────────────────────────────────
    def run(self, name, args):
        fn = {"discover_companies": self.discover_companies, "google_search": self.google_search,
              "find_linkedin_page": self.find_linkedin_page, "save_company": self.save_company}.get(name)
        if not fn:
            return f"ERROR: unknown tool {name}", True
        try:
            out = fn(**args)
        except TypeError as e:
            return f"ERROR: bad arguments ({e})", True
        except Exception as e:
            return f"ERROR: {type(e).__name__}: {e}", True
        return out, out.startswith(("ERROR", "REJECTED"))


def tool_schemas(buckets, tiers):
    return [
        {
            "name": "discover_companies",
            "description": ("Free company database search (Hunter Discover). Returns up to 100 companies "
                            "(organization | domain) headquartered in the given cities that match ONE headcount "
                            "bucket. Call once per bucket/city/industry combination: results are not paginated, "
                            "so vary the filters to get more companies."),
            "input_schema": {
                "type": "object",
                "properties": {
                    "headcount": {"type": "string", "enum": buckets},
                    "cities": {"type": "array", "items": {"type": "string"},
                               "description": "HQ cities, e.g. ['New Delhi','Gurugram','Noida']"},
                    "country": {"type": "string", "description": "ISO code, default IN"},
                    "industries": {"type": "array", "items": {"type": "string"},
                                   "description": "LinkedIn-style industry names, e.g. 'Software Development', "
                                                  "'Financial Services', 'IT Services and IT Consulting'"},
                    "keywords": {"type": "array", "items": {"type": "string"},
                                 "description": "free-text keywords such as 'artificial intelligence', 'saas'"},
                    "query": {"type": "string", "description": "optional natural-language description"},
                },
                "required": ["headcount"],
            },
        },
        {
            "name": "google_search",
            "description": "Google search (costs one Serper credit). Use sparingly: only to check a company you "
                           "can't place in a tier, or to find companies Discover missed.",
            "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        },
        {
            "name": "find_linkedin_page",
            "description": "Finds candidate LinkedIn company pages for a company (costs one Serper credit). "
                           "Pass the domain too so matches can be flagged.",
            "input_schema": {"type": "object",
                             "properties": {"company_name": {"type": "string"}, "domain": {"type": "string"}},
                             "required": ["company_name"]},
        },
        {
            "name": "save_company",
            "description": "Save one verified company. The linkedin_url MUST come from find_linkedin_page. "
                           "Never build or guess a LinkedIn URL.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "company_name": {"type": "string"},
                    "linkedin_url": {"type": "string"},
                    "tier": {"type": "integer", "enum": tiers},
                    "size_bucket": {"type": "string", "enum": buckets},
                    "domain": {"type": "string"},
                    "industry": {"type": "string"},
                    "hq_city": {"type": "string"},
                    "reason": {"type": "string", "description": "one short sentence on why this tier"},
                },
                "required": ["company_name", "linkedin_url", "tier", "size_bucket", "reason"],
            },
        },
    ]


# ════════════════════════════════════════════════════════════════════════════
#  AGENT LOOP
# ════════════════════════════════════════════════════════════════════════════

def build_prompts(args, buckets):
    system = f"""You are a company-research agent building a target list for B2B / job outreach.

GOAL: save {args.count} NEW companies that are tier {' or '.join(map(str, args.tiers))},
have {args.min_size:,}–{args.max_size:,} employees (size buckets: {', '.join(buckets)}),
are located in / around: {args.location}{f', in industries: {args.industry}' if args.industry else ''}.
Each saved company needs its real LinkedIn company page.

TIERS
{TIER_GUIDE}

METHOD
1. Call discover_companies with ONE headcount bucket at a time and the relevant HQ cities
   (for Delhi NCR use cities like New Delhi, Delhi, Gurugram, Gurgaon, Noida, Faridabad, Ghaziabad).
   Add industries or keywords that fit the brief. Spread across buckets so the list isn't all one size.
2. From each result list, pick the companies that fit the brief. Judge the tier from what you know.
   If you truly can't tell what a company is, do ONE google_search; if still unclear, skip it.
3. Call find_linkedin_page with the name and domain. Only accept a candidate that is clearly the same
   company (a DOMAIN MATCH or slug match helps). If none fits, skip the company. NEVER invent a URL.
4. Call save_company. If it is REJECTED, read why and move on.
5. Stop as soon as a save says TARGET REACHED, or when you run out of good candidates.

RULES: be economical with google_search and find_linkedin_page (they cost credits).
You may call several tools in one turn. Keep your text short: one line on what you are doing."""
    user = (f"Find {args.count} tier-{'/'.join(map(str, args.tiers))} companies around {args.location}"
            f"{f' in {args.industry}' if args.industry else ''} with {args.min_size}–{args.max_size} employees. Start.")
    return system, user


def run_agent(args, tools: Toolbox, buckets):
    client = anthropic.Anthropic()
    system, user = build_prompts(args, buckets)
    schemas = tool_schemas(buckets, args.tiers)
    messages = [{"role": "user", "content": user}]
    usage = {"in": 0, "out": 0}

    for turn in range(1, CFG["max_turns"] + 1):
        try:
            resp = client.messages.create(model=args.model, max_tokens=4096, system=system,
                                          tools=schemas, messages=messages)
        except anthropic.APIError as e:
            log.error("Claude API error: %s", e)
            break
        usage["in"] += resp.usage.input_tokens
        usage["out"] += resp.usage.output_tokens
        messages.append({"role": "assistant", "content": resp.content})

        for b in resp.content:
            if b.type == "text" and b.text.strip():
                log.info("🤖 %s", b.text.strip().splitlines()[0][:160])

        if resp.stop_reason != "tool_use":
            break

        results = []
        for b in resp.content:
            if b.type != "tool_use":
                continue
            brief = ", ".join(f"{k}={v}" for k, v in b.input.items() if k != "reason")[:120]
            log.info("   🔧 %s(%s)", b.name, brief)
            out, is_err = tools.run(b.name, b.input)
            if is_err:
                log.info("      ↳ %s", out[:140])
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": out, "is_error": is_err})
        messages.append({"role": "user", "content": results})

        if tools.new_count >= args.count:
            break
    else:
        log.info("Stopped at the %d-turn limit.", CFG["max_turns"])
    return usage


# ════════════════════════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════════════════════════

def buckets_for(min_size, max_size):
    out = []
    for b in ALL_BUCKETS:
        lo, hi = (int(b[:-1]), 10 ** 9) if b.endswith("+") else map(int, b.split("-"))
        if hi >= min_size and lo <= max_size:
            out.append(b)
    return out


def main():
    ap = argparse.ArgumentParser(description="Claude agent: find tier-2/3 companies and their LinkedIn pages.")
    ap.add_argument("--location", default="Delhi NCR, India", help='e.g. "Delhi NCR, India" or "Bengaluru"')
    ap.add_argument("--industry", default="", help='free text, e.g. "AI, SaaS, fintech" (empty = any)')
    ap.add_argument("--count", type=int, default=30, help="how many NEW companies to add this run")
    ap.add_argument("--tiers", default="2,3", type=lambda s: sorted({int(x) for x in s.split(",") if x.strip()}))
    ap.add_argument("--min-size", type=int, default=100)
    ap.add_argument("--max-size", type=int, default=10000)
    ap.add_argument("--output", default="companies_found.csv")
    ap.add_argument("--exclude", type=lambda s: [x.strip() for x in s.split(",") if x.strip()],
                    help="CSV files of companies to skip, e.g. tier2_ai_companies_delhi_ncr.csv")
    ap.add_argument("--model", default=CFG["model"])
    ap.add_argument("--max-turns", type=int, default=CFG["max_turns"])
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for noisy in ("httpx", "httpcore", "anthropic", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    if load_dotenv:
        load_dotenv()
    if not os.getenv("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is required: this script is a Claude agent.")
    for k in ("HUNTER_API_KEY", "SERPER_API_KEY"):
        if not os.getenv(k):
            log.warning("⚠  %s not set — the agent will have fewer tools.", k)
    if not set(args.tiers) <= {2, 3}:
        sys.exit("--tiers accepts 2 and/or 3.")
    CFG["max_turns"] = args.max_turns

    buckets = buckets_for(args.min_size, args.max_size)
    if args.min_size > 51 and "51-200" in buckets:
        log.info("ℹ  LinkedIn groups sizes in buckets, so %d+ includes the whole 51-200 bucket.", args.min_size)

    store = Store(LF_CONFIG["cache_db"])
    out_path = Path(args.output)
    tools = Toolbox(args, store, buckets, out_path)
    log.info("Target: %d new tier-%s companies | %s | %s | sizes %s | model %s\n",
             args.count, "/".join(map(str, args.tiers)), args.location, args.industry or "any industry",
             ", ".join(buckets), args.model)

    try:
        usage = run_agent(args, tools, buckets)
    except KeyboardInterrupt:
        usage = None
        log.info("\nStopped — everything saved so far is in the CSV. Re-run to continue.")

    log.info("\nDone: %d new companies (%d total) → %s", tools.new_count, len(tools.saved_rows), out_path)
    log.info("Used: %d Google searches, %d Discover calls%s", tools.google_calls, tools.discover_calls,
             f", Claude tokens in/out {usage['in']:,}/{usage['out']:,}" if usage else "")
    if tools.new_count:
        log.info("\nNext step:\n  python lead_finder.py --input %s", out_path)


if __name__ == "__main__":
    main()