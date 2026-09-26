# Lead Finder

Give it a CSV of companies. It finds the senior people who work there — recruiters, HR, founders, product managers, senior managers — and gets their work emails. Everything is saved to a CSV that's ready for outreach.

It is one Python file (`lead_finder.py`) and runs on free tiers. An optional Claude agent (`company_finder.py`) can build the company list for you first.

---

## How it works

```
companies.csv
     │
  1. Find domain ─────── Hunter Domain Finder (free)
     │
  2. Real emails ─────── Hunter Domain Search (~1 credit per email) → also learns the email format
     │
  3. Find people ─────── Google search of public LinkedIn profiles via Serper (free)
     │
  4. Filter & score ──── keep only your target roles, drop junior / ex-employees
     │
  5. Build emails ────── apply the company's email format, or Hunter Email Finder (1 credit)
     │
  6. Verify ──────────── Hunter Email Verifier (0.5 credit)
     │
  leads.csv  +  leads_companies.csv
```

Claude is optional. It is only called when the rules can't decide something:

- a job title the rules don't recognise
- a company with more than one possible domain
- a search result that is hard to read
- whether a company is a startup (when the CSV has no size column)

All of its answers are cached.

---

## Step 0 (optional): find companies with the Claude agent — `company_finder.py`

Don't have a company list yet? `company_finder.py` is a Claude agent. It finds **tier-2 / tier-3 companies with 100–10,000 employees** and their **LinkedIn company pages**. It writes a CSV that `lead_finder.py` reads directly.

```bash
python company_finder.py --location "Delhi NCR, India" --industry "AI, SaaS, fintech" --count 30
python lead_finder.py   --input companies_found.csv
```

**What it needs:**

- `lead_finder.py` in the same folder (it shares the cache and helper code)
- `ANTHROPIC_API_KEY` (**required** for this script)
- `HUNTER_API_KEY` and `SERPER_API_KEY`

**How the agent works:** Claude chooses the searches and judges each company's tier. Python checks every save before anything is written.

| Tool the agent uses | Source | Cost |
|---|---|---|
| `discover_companies` | Hunter Discover (by HQ city, size bucket, industry, keywords) | Free |
| `google_search` | Serper, only to check an unclear company | 1 Serper search |
| `find_linkedin_page` | Serper `site:linkedin.com/company` | 1 Serper search |
| `save_company` | Python checks: real LinkedIn URL, size in range, tier 2/3, not a duplicate | — |

**What Python checks:**

- Claude can't save a made-up LinkedIn URL: it must be a real `linkedin.com/company/...` link found by the search.
- It can't save a company outside your size range, or a duplicate.
- It can't save a company that's already in your `--exclude` files.

### Options

| Option | Default | What it does |
|---|---|---|
| `--location` | `Delhi NCR, India` | Where the companies should be |
| `--industry` | any | Free text, e.g. `"AI, SaaS, fintech"` |
| `--count` | `30` | New companies to add this run |
| `--tiers` | `2,3` | `2`, `3` or `2,3` |
| `--min-size` / `--max-size` | `100` / `10000` | Employee range |
| `--exclude a.csv,b.csv` | none | Skip companies already in these files |
| `--output` | `companies_found.csv` | Output file |
| `--model` | `claude-sonnet-5` | `claude-haiku-4-5-20251001` is cheaper but judges tiers less well |
| `--max-turns` | `40` | Hard stop for the agent loop |

**Example:** 50 new companies, skipping ones you already have:

```bash
python company_finder.py --count 50 --industry "SaaS, fintech" --exclude tier2_ai_companies_delhi_ncr.csv
```

### Good to know

- **Tiers are Claude's judgement.** Edit `TIER_GUIDE` at the top of `company_finder.py` to change what tier 2 and tier 3 mean for you. Every saved row has a `reason` column so you can review the choice.
- **Size buckets.** LinkedIn and Hunter group sizes into buckets (51-200, 201-500 …). A minimum of 100 therefore includes the whole 51-200 bucket.
- **Resuming.** Re-running appends to `companies_found.csv` and skips companies already in it. The file is saved after every company, so Ctrl+C is safe.
- **Getting more results.** Hunter Discover's free plan returns one page (up to 100 companies) per filter combination. The agent varies city, size bucket and industry to find more.
- **Cost.** The Claude API is pay-per-use. The script prints the tokens used at the end, and a 30-company run is usually a small cost.
- **Output columns:** `company_id, company_name, linkedin_url, website, company_size, industry, headquarters, tier, reason, source, found_at`.

---

## Step 3: send personal emails with your resume — `outreach.py`

After `lead_finder.py` has found emails, `outreach.py` has Claude write a short, personal email to each person. You review the drafts, then it sends them from your Gmail with `resume.pdf` attached.

```bash
python outreach.py draft --leads leads.csv    # writes drafts to outbox.csv, sends NOTHING
python outreach.py test                       # sends 2 drafts to yourself to check how they look
python outreach.py send                       # sends approved drafts after you type SEND
```

### Setup

**1. Put `resume.pdf` in the project folder.**

**2. Create a Gmail App Password.** Your normal Gmail password will not work.

- Turn on 2-Step Verification: Google Account → Security.
- Search "App passwords" and create one.
- Copy the 16-character code.

**3. Add these lines to `.env`:**

```
SMTP_USER=you@gmail.com
SMTP_PASSWORD=abcdefghijklmnop
MY_NAME=Your Name
MY_TARGET_ROLE=Product Analyst
MY_PHONE=+91 ...
MY_LINKEDIN=https://linkedin.com/in/...
MY_NOTE=Immediate joiner, open to Gurugram/Noida
```

`MY_PHONE`, `MY_LINKEDIN` and `MY_NOTE` are optional. Using Outlook or Zoho instead of Gmail? Also set `SMTP_HOST` and `SMTP_PORT`.

### How the drafts are written

- **Claude reads your resume once** and prints the facts it found. Check them: messages only use those facts, so Claude can't invent or inflate your experience.
- **Each email is short:** 45–120 words, plain text, starting with "Hi {first name},".
- **Each email includes:**
  - one specific reason for writing to that company
  - one real proof point from your resume
  - a question that fits the person's role (recruiters and HR are asked about openings, founders are offered a 10-minute chat, managers are asked for the right person)
  - a casual mention of the attached resume
  - an easy "no worries if not" line
- **Company news:** one Google search per company can add a recent detail. Claude uses it only if it's clearly about that company.
- **Humanised by checking:** drafts using templated phrases ("I hope this email finds you well", "passionate about", "please find attached", em dashes…) are rewritten automatically, up to twice. Anything still failing is marked `NEEDS_REVIEW` with `approved=no`.
- **Your signature** (name, phone, LinkedIn) is added by the script, so it's always the same and always correct.
- **Attachment name:** the resume is attached as `Your_Name_Resume.pdf`.

### Reviewing drafts

Open `outbox.csv` and review it:

- Edit any `subject` or `body` you like.
- Set `approved` to `no` for anything you don't want sent.
- Save it as **CSV UTF-8**, then close Excel before running `send`.

### Built-in limits

| Limit | Default | Why |
|---|---|---|
| Email status | only `valid` / `accept_all` | Bounces hurt your inbox reputation |
| Per day | 20 | Gmail allows 500/day, but cold email from a personal inbox should stay low |
| Gap between sends | random 1–2.5 min | Avoids looking like a bulk sender |
| Send window | Mon–Fri, 9:00–18:00 | Better reply rates (use `--now` to override) |
| Per company | max 2 people | Don't flood one company |
| Never twice | every sent address is logged in `outreach.db` | Re-running is always safe |
| Do-not-contact | `do_not_contact.txt` (one email or `@domain` per line) | Anyone who says no is never emailed again |

You can change these in `CONFIG` at the top of `outreach.py`.

**Options:**

- `draft`: `--limit N`, `--statuses valid`, `--no-research`, `--show N`
- `test`: `--to other@email.com`, `--count N`
- `send`: `--max N`, `--now`, `--yes`

Replies arrive in your normal Gmail inbox. The script doesn't read replies or send follow-ups.

---

## Requirements

- Python 3.9 or newer
- Free accounts:
  - **Hunter** (hunter.io): domains and emails, 50 credits/month free
  - **Serper** (serper.dev): LinkedIn search, 2,500 free searches on signup, no card needed
  - **Claude API** (console.anthropic.com): *optional*, pay-per-use, very small cost

---

## Setup

**1. Put the files in one folder**

```
lead-finder/
├── lead_finder.py
├── README.md
├── your_companies.csv
└── .env
```

**2. Install the packages**

```bash
pip install requests anthropic python-dotenv
```

On Windows, if `python` / `pip` aren't recognised, use `py` and `py -m pip` instead.

**3. Create a `.env` file with your keys**

```
HUNTER_API_KEY=your_hunter_key
SERPER_API_KEY=your_serper_key
ANTHROPIC_API_KEY=your_claude_key
```

The last line is optional. On Windows, make sure Notepad didn't save the file as `.env.txt`. Choose "All files" when saving.

Never share or commit `.env`. If you use Git, add `.env`, `lead_finder_cache.db`, `outreach.db` and `resume.pdf` to `.gitignore`.

---

## Input CSV

The script detects columns automatically. Only a company name is required:

| Column (any of these names) | Required | Used for |
|---|---|---|
| `Company Name`, `company_name`, `company`, `name` | ✅ | searching |
| `LinkedIn URL`, `linkedin_url`, `linkedin` | optional | removing duplicate companies |
| `website`, `domain`, `url` | optional | skips the domain lookup (more accurate) |
| `company_size`, `size`, `employees` | optional | startup check for founders |
| `industry`, `sector` | optional | startup check |
| `company_id`, `id` | optional | otherwise `C0001`, `C0002`… are assigned |

Tip: adding a `website` column gives more reliable results than relying on the domain lookup.

---

## Usage

**Test run first.** This spends zero Hunter credits:

```bash
python lead_finder.py --input your_companies.csv --max-companies 2 --free-only -v
```

**Real run:**

```bash
python lead_finder.py --input your_companies.csv --max-companies 5 --location Delhi
```

**More examples:**

```bash
# only recruiters, HR and startup founders
python lead_finder.py --input your_companies.csv --roles recruiter,hr,founder

# cap spending at 20 credits and name the output
python lead_finder.py --input your_companies.csv --budget 20 --output delhi_leads.csv
```

### Options

| Option | Default | What it does |
|---|---|---|
| `--input` | — | Company CSV (required) |
| `--output` | `leads.csv` | Output file name |
| `--max-companies N` | all | Process only the first N companies |
| `--roles a,b` | all groups | Which role groups to target (see below) |
| `--location "Delhi"` | none | Bias the LinkedIn search toward a city |
| `--budget N` | `45` | Max Hunter credits to spend this month |
| `--free-only` | off | Never spend Hunter credits |
| `--guess-emails` | off | Last resort: writes `first.last@domain`, marked `unverified_guess` |
| `-v` | off | Detailed logs |

---

## Choosing who to find

There are five role groups, defined in `TARGET_ROLES` at the top of `lead_finder.py`:

| Group | Finds | Notes |
|---|---|---|
| `recruiter` | Recruiters, Talent Acquisition, hiring roles | |
| `hr` | HR managers, HRBP, CHRO, People team leads | |
| `founder` | Founders, owners, CEO, MD | **Startups only** (≤ 200 employees) |
| `product` | Product managers, Head/Director/VP of Product | |
| `senior_mgmt` | Senior managers, directors, heads, VPs, CXOs | |

Titles matching `EXCLUDE_PATTERNS` are dropped. By default that covers:

- intern, trainee, student, fresher
- junior, HR Executive, Assistant Manager, Associate
- ex- / former employees
- "open to work"

**To change who you find:**

- Add a new job-title keyword to a group's `patterns` list, for example `r"people partner"`.
- Add words to `search_terms` so the Google search looks for them too.
- Change `score` to rank a group higher or lower.
- Edit `EXCLUDE_PATTERNS` to allow or block more titles.
- Change `startup_max_employees` in `CONFIG` to redefine "startup".

Other settings in `CONFIG`:

| Setting | Default | Meaning |
|---|---|---|
| `max_people_per_company` | `5` | Keep the top N people per company |
| `hunter_search_limit` | `3` | Emails pulled per company from Hunter (≈ credits) |
| `min_score` | `60` | Drop people scoring below this |
| `verify_pattern_emails` | `True` | Verify emails built from the company format |

---

## Output

### `leads.csv`

This file has the same columns as `people.csv`, plus a few new ones:

| Column | Meaning |
|---|---|
| `company_domain` | e.g. `zomato.com` |
| `email` | the work email (may be empty) |
| `email_status` | see the table below |
| `email_confidence` | 0–100, from Hunter |
| `email_source` | `hunter_domain_search`, `hunter_pattern`, `hunter_finder` or `guess` |

The existing columns are filled like this:

- `contact_type`, `department`, `seniority` and `relevance_score` come from the role match.
- `priority` is `HIGH` (≥90), `MEDIUM` (≥75) or `LOW`.
- `recommended_action` is `SEND_EMAIL`, `VERIFY_THEN_EMAIL` or `LINKEDIN_CONNECT`.
- The outreach columns start as `NEW` / `NOT_CONTACTED` / `NOT_REQUESTED`.

### `email_status` values

| Status | Safe to email? |
|---|---|
| `valid` | ✅ Yes |
| `accept_all` | ⚠️ Probably. The server accepts every address, so a bounce is still possible |
| `pattern_unverified` | ⚠️ Built from the company format but not checked. Verify it first |
| `unknown` | ⚠️ Verification failed. Verify it first |
| `unverified_guess` | ❌ Don't send without verifying |
| `not_found` | — No email. Use LinkedIn instead |

### `leads_companies.csv`

One row per company, with these columns:

- `domain` and `domain_source` (where the domain came from)
- `is_startup`
- `people_found` and `emails_found`
- any `error`

---

## Credits and caching

- **The free plan is small.** Hunter's free plan is 50 credits/month, which is about 10–15 companies with good emails.
- **What costs credits:**
  - Domain Search: ~1 credit per email returned
  - Email Finder: 1 credit, only charged when an email is found
  - Email Verifier: 0.5 credit
- **What's free:** Domain Finder and Serper searches (until the 2,500 signup searches are used).
- **Caching:** every API response is saved in `lead_finder_cache.db`. Re-running never pays twice for the same lookup.
- **Stopping and resuming:** press **Ctrl+C** at any time. Output is saved after every company, and re-running the same command picks up where you left off.
- **Budget tracking:** the budget is tracked per calendar month in the cache database. Hunter's credits are shared across your whole Hunter account, so leave a few spare if you also use Hunter's website.
- **Starting fresh:** delete `lead_finder_cache.db` to clear the cache. This also resets the local credit count; Hunter's real count doesn't change.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError` | Run `pip install requests anthropic python-dotenv` (Windows: `py -m pip ...`) |
| `HUNTER_API_KEY not set` | `.env` is missing, in the wrong folder, or saved as `.env.txt` |
| `domain=- (not_found)` | Add a `website` column with the company's site |
| `hunter_low_confidence` domain | Check it in `leads_companies.csv`, or add the website to your CSV |
| `people=0` for many companies | Remove `--location`, use fewer `--roles`, or check your Serper credits |
| "credits are used up" | Normal on the free plan. The run continues with free sources |
| Wrong person / ex-employee in results | "Currently works there" is a best guess from search results. Check `profile_summary` |
| Founders showing up at big companies | Add a `company_size` column, or set `ANTHROPIC_API_KEY` so Claude can judge company size |

---

## Responsible use

- Collect only work contact details, and only for genuine professional outreach.
- Keep the `email_source` column. It records where each email came from.
- Honour opt-outs and unsubscribe requests quickly.
- In India, the DPDP Act 2023 applies. For EU contacts, GDPR applies.
- Don't scrape LinkedIn directly or automate actions on it. It breaks LinkedIn's Terms of Service and can get your account restricted. This tool only reads public Google search results and uses licensed email-data APIs.
- Send cold email in small, personal batches. Mass-sending unverified emails damages your sender reputation.