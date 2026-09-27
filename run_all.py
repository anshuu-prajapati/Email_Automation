#!/usr/bin/env python3
"""
run_all.py — the whole pipeline in one command.

    find companies  →  people + emails  →  personal drafts  →  (you review)  →  send with resume.pdf
    company_finder.py   lead_finder.py      outreach.py draft                   outreach.py send

EXAMPLES
  # Find 10 new companies, their people and emails, write drafts, then STOP so you can review outbox.csv
  python run_all.py --location "Delhi NCR, India" --industry "AI, SaaS, fintech" --find 10

  # After reviewing outbox.csv: send the approved drafts
  python run_all.py --from send

  # Everything in one go (still shows the first email and asks you to type SEND)
  python run_all.py --location "Delhi NCR, India" --industry "AI, SaaS" --find 10 --test --send

  # Use a company list you already have instead of finding new ones
  python run_all.py --companies-csv tier2_ai_companies_delhi_ncr.csv --find 0

Every step caches its work, so if anything stops, fix it and run the same command again.
"""

import argparse
import csv
import os
import shlex
import subprocess
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

HERE = Path(__file__).resolve().parent
STEPS = ["find", "leads", "draft", "send"]


def banner(n, title):
    print(f"\n{'═' * 70}\n  STEP {n}/4 · {title}\n{'═' * 70}", flush=True)


def run(script, args, allow_fail=False):
    cmd = [sys.executable, str(HERE / script), *[str(a) for a in args]]
    print("$ python " + " ".join(shlex.quote(c) for c in cmd[1:]).replace(str(HERE) + os.sep, ""), flush=True)
    code = subprocess.run(cmd).returncode
    if code != 0 and not allow_fail:
        sys.exit(f"\n✗ Stopped: {script} exited with code {code}. Read the message above, fix it, "
                 "and run the same command again (finished work is cached, so it won't be redone or re-paid).")
    return code


def count_rows(path, test=lambda r: True):
    p = Path(path)
    if not p.exists():
        return 0
    with open(p, newline="", encoding="utf-8-sig") as f:
        return sum(1 for r in csv.DictReader(f) if test(r))


def preflight(args, start):
    """Check keys and files BEFORE spending any credits."""
    problems = []
    need = lambda k: os.getenv(k, "").strip()
    will = lambda step: STEPS.index(start) <= STEPS.index(step)

    if will("find") and args.find > 0 and not need("ANTHROPIC_API_KEY"):
        problems.append("ANTHROPIC_API_KEY is missing (needed to find companies).")
    if will("leads"):
        if not need("HUNTER_API_KEY"):
            problems.append("HUNTER_API_KEY is missing (needed for domains and emails).")
        if not need("SERPER_API_KEY"):
            problems.append("SERPER_API_KEY is missing (needed to find people).")
    if will("draft"):
        if not need("ANTHROPIC_API_KEY"):
            problems.append("ANTHROPIC_API_KEY is missing (needed to write the emails).")
        if not need("MY_NAME"):
            problems.append("MY_NAME is missing in .env (used in your signature).")
        if not Path("resume.pdf").exists():
            problems.append("resume.pdf is not in this folder.")
    if args.send or args.test or start == "send":
        if not (need("SMTP_USER") and need("SMTP_PASSWORD")):
            problems.append("SMTP_USER / SMTP_PASSWORD are missing (Gmail address + App Password).")
        if not Path("resume.pdf").exists() and "resume.pdf is not in this folder." not in problems:
            problems.append("resume.pdf is not in this folder.")
    if STEPS.index(start) <= STEPS.index("leads") and args.find == 0 and not Path(args.companies_csv).exists():
        problems.append(f"--find 0 was given but {args.companies_csv} doesn't exist.")
    for f in ("lead_finder.py", "company_finder.py", "outreach.py"):
        if not (HERE / f).exists():
            problems.append(f"{f} must be in the same folder as run_all.py.")
    problems = list(dict.fromkeys(p.replace(" (needed to find companies)", "").replace(" (needed to write the emails)", "")
                                  if p.startswith("ANTHROPIC") else p for p in problems))
    if problems:
        print("Can't start yet:\n  • " + "\n  • ".join(problems) +
              "\n\nSee .env.example and the README 'Setup' section.")
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description="Run the full outreach pipeline with one command.",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    g = ap.add_argument_group("step 1 · find companies (company_finder.py)")
    g.add_argument("--location", default="Delhi NCR, India")
    g.add_argument("--industry", default="", help='e.g. "AI, SaaS, fintech" (empty = any)')
    g.add_argument("--find", type=int, default=10, help="NEW companies to find this run (0 = skip this step)")
    g.add_argument("--tiers", default="2,3")
    g.add_argument("--min-size", type=int, default=100)
    g.add_argument("--max-size", type=int, default=10000)
    g.add_argument("--exclude", default="", help="comma list of CSVs whose companies to skip")
    g.add_argument("--companies-csv", default="companies_found.csv", help="company list used by step 2")

    g = ap.add_argument_group("step 2 · people + emails (lead_finder.py)")
    g.add_argument("--leads", default="leads.csv")
    g.add_argument("--roles", default="", help="e.g. recruiter,hr,founder,product,senior_mgmt")
    g.add_argument("--city", default=None, help='people-search city hint (default: first word of --location)')
    g.add_argument("--budget", type=float, default=None, help="max Hunter credits this month")
    g.add_argument("--max-companies", type=int, default=0)
    g.add_argument("--free-only", action="store_true")

    g = ap.add_argument_group("step 3-4 · write and send (outreach.py)")
    g.add_argument("--draft-limit", type=int, default=0, help="only write N new drafts")
    g.add_argument("--test", action="store_true", help="email 2 drafts to yourself before sending")
    g.add_argument("--send", action="store_true", help="send approved drafts at the end (asks you to type SEND)")
    g.add_argument("--max-send", type=int, default=0)
    g.add_argument("--now", action="store_true", help="allow sending outside weekday 9–18")
    g.add_argument("--yes", action="store_true", help="don't ask for SEND confirmation (unattended)")

    ap.add_argument("--from", dest="start", choices=STEPS, default="find",
                    help="start at this step (e.g. --from send after reviewing outbox.csv)")
    args = ap.parse_args()

    if load_dotenv:
        load_dotenv(HERE / ".env")
    preflight(args, args.start)
    start = STEPS.index(args.start)
    city = args.city if args.city is not None else args.location.split(",")[0].replace(" NCR", "").strip()

    # ── 1. companies ─────────────────────────────────────────────────────────
    if start <= 0:
        banner(1, "Find tier-2/3 companies + LinkedIn pages")
        if args.find > 0:
            a = ["--location", args.location, "--count", args.find, "--tiers", args.tiers,
                 "--min-size", args.min_size, "--max-size", args.max_size, "--output", args.companies_csv]
            if args.industry:
                a += ["--industry", args.industry]
            if args.exclude:
                a += ["--exclude", args.exclude]
            run("company_finder.py", a)
        else:
            print(f"Skipped (--find 0). Using {args.companies_csv}.")
        if count_rows(args.companies_csv) == 0:
            sys.exit(f"\n✗ No companies in {args.companies_csv}. Try a wider --industry or --location.")

    # ── 2. people + emails ───────────────────────────────────────────────────
    if start <= 1:
        banner(2, "Find senior people + their work emails")
        a = ["--input", args.companies_csv, "--output", args.leads]
        if city:
            a += ["--location", city]
        if args.roles:
            a += ["--roles", args.roles]
        if args.budget is not None:
            a += ["--budget", args.budget]
        if args.max_companies:
            a += ["--max-companies", args.max_companies]
        if args.free_only:
            a.append("--free-only")
        run("lead_finder.py", a)

    # ── 3. drafts ────────────────────────────────────────────────────────────
    if start <= 2:
        banner(3, "Write a personal email for each person")
        a = ["draft", "--leads", args.leads]
        if args.draft_limit:
            a += ["--limit", args.draft_limit]
        run("outreach.py", a)

    if args.test:
        print("\n── Sending 2 test emails to yourself ──")
        run("outreach.py", ["test"], allow_fail=True)

    # ── 4. send ──────────────────────────────────────────────────────────────
    sending = args.send or args.start == "send"
    if sending:
        banner(4, "Send approved emails with resume.pdf")
        a = ["send"]
        if args.max_send:
            a += ["--max", args.max_send]
        if args.now:
            a.append("--now")
        if args.yes:
            a.append("--yes")
        run("outreach.py", a, allow_fail=True)

    # ── summary ──────────────────────────────────────────────────────────────
    ok = lambda r: r.get("email_status") in ("valid", "accept_all")
    print(f"\n{'═' * 70}\n  SUMMARY\n{'═' * 70}")
    print(f"  Companies  {count_rows(args.companies_csv):>5}   ({args.companies_csv})")
    print(f"  People     {count_rows(args.leads):>5}   ({args.leads}), "
          f"{count_rows(args.leads, ok)} with a usable email")
    print(f"  Drafts     {count_rows('outbox.csv', lambda r: r.get('approved', '').lower() == 'yes' and r.get('status') != 'SENT'):>5}"
          f"   approved and waiting (outbox.csv)")
    print(f"  Sent       {count_rows('outbox.csv', lambda r: r.get('status') == 'SENT'):>5}   in total")
    if not sending:
        print("\nNext: open outbox.csv, edit or set approved=no where you like, save as CSV UTF-8, close Excel, then:\n"
              "  python run_all.py --from send")


if __name__ == "__main__":
    main()