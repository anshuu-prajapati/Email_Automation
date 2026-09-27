# Job Outreach Automation

This is one command that:

1. finds **tier-2 / tier-3 companies** (100–10,000 employees) and their LinkedIn pages
2. finds the **senior people** at each one (recruiters, HR, founders, product managers, senior managers)
3. gets their **work emails**
4. writes each person a **short, human, personal email**
5. sends it from your Gmail with **your resume attached**

```
run_all.py
 ├─ 1. company_finder.py   Claude agent → companies_found.csv   (name, LinkedIn URL, size, tier)
 ├─ 2. lead_finder.py      people + emails → leads.csv
 ├─ 3. outreach.py draft   Claude writes emails → outbox.csv    ← you review here
 └─ 4. outreach.py send    Gmail + resume.pdf, with safety limits
```

---

## 🎨 Using the Dashboard (Easiest Way!)

**No command line needed.** Use our beautiful Streamlit dashboard instead:

```bash
streamlit run streamlit_app.py
```

Or on Windows, just **double-click:**
```
run_dashboard.bat
```

✅ **What you get:**
- Web-based interface (opens in browser)
- Fill in API keys in sidebar
- Click buttons to run each step
- Watch live logs as they happen
- Preview CSVs before sending
- Upload resume from dashboard
- No terminal = no scary errors!

👉 **[Start with the Dashboard Guide →](README_DASHBOARD.md)**

Or use the **[Quick Start Guide →](DASHBOARD_QUICKSTART.md)** (3 steps, 5 minutes)

---

## Quick start (Command Line Alternative)

**1. Put these files in one folder:**

```
automation/
├── run_all.py
├── company_finder.py
├── lead_finder.py
├── outreach.py
├── requirements.txt
├── .env.example
├── README.md
└── resume.pdf          ← your resume, named exactly this
```

Keep the folder **outside OneDrive** if you can (e.g. `C:\projects\automation`). OneDrive locks files while it syncs.

**2. Open a terminal in the folder and install the packages:**

```bash
python -m venv venv
venv\Scripts\activate            # Windows   (Mac/Linux: source venv/bin/activate)
pip install -r requirements.txt
```

On Windows, if `python` isn't found, use `py` instead.

**Or use the Dashboard (recommended):**

After installing, just run:
```bash
streamlit run streamlit_app.py
```

No more command line! Everything in your browser. 🎉

**3. Get your keys:**

| Key | Where | Cost |
|---|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com → API keys | Pay-per-use |
| `HUNTER_API_KEY` | hunter.io → dashboard → API keys | Free: 50 credits/month |
| `SERPER_API_KEY` | serper.dev → dashboard | Free: 2,500 searches on signup |
| `SMTP_PASSWORD` | Gmail App Password (see below) | Free |

**Gmail App Password:**

- Google Account → Security → turn on **2-Step Verification**.
- Search **"App passwords"** and create one.
- Copy the 16-character code.

Your normal Gmail password will **not** work.

**4. Create `.env`:**

- Copy `.env.example` to a new file named `.env`.
- Fill in the keys and your details (`MY_NAME`, `MY_TARGET_ROLE`, and optionally phone / LinkedIn).
- On Windows, check that Notepad didn't save it as `.env.txt`.

**5. Run it:**

```bash
python run_all.py --location "Delhi NCR, India" --industry "AI, SaaS, fintech" --find 10
```

This finds 10 companies, their people and emails, and writes the drafts. It then **stops so you can review**.

- Open `outbox.csv` and edit anything you want.
- Set `approved` to `no` for any draft you don't want sent.
- Save it as **CSV UTF-8** and close Excel.

Then send:

```bash
python run_all.py --from send
```

It shows you the first email and waits for you to type `SEND`.

---

## The one command: `run_all.py`

**Common commands:**

```bash
# Find 10 new companies → people → emails → drafts, then stop for review
python run_all.py --location "Delhi NCR, India" --industry "AI, SaaS" --find 10

# Send the approved drafts (after reviewing outbox.csv)
python run_all.py --from send

# Everything in one go: sends 2 test emails to yourself first, then asks you to type SEND
python run_all.py --location "Delhi NCR, India" --industry "AI, SaaS" --find 10 --test --send

# Use a company list you already have (skip finding companies)
python run_all.py --companies-csv tier2_ai_companies_delhi_ncr.csv --find 0

# Only recruiters, HR and startup founders; spend at most 20 Hunter credits
python run_all.py --find 10 --roles recruiter,hr,founder --budget 20

# Find 20 more companies, skipping ones you already have
python run_all.py --find 20 --exclude tier2_ai_companies_delhi_ncr.csv

# Start again from a later step
python run_all.py --from leads      # redo people/emails for companies_found.csv
python run_all.py --from draft      # write drafts for any new leads
```

Before spending anything, `run_all.py` checks that your keys, `resume.pdf` and all the scripts are in place.

**If a step fails, fix the message and run the same command again.** Finished work is cached, so nothing is redone or paid for twice.

### Options

| Option | Default | What it does |
|---|---|---|
| **Step 1: companies** | | |
| `--location` | `Delhi NCR, India` | Where the companies are |
| `--industry` | any | e.g. `"AI, SaaS, fintech"` |
| `--find N` | `10` | New companies to find this run (`0` = skip, use `--companies-csv`) |
| `--tiers` | `2,3` | Company tiers to keep |
| `--min-size` / `--max-size` | `100` / `10000` | Employee range |
| `--exclude a.csv,b.csv` | — | Skip companies already in these files |
| `--companies-csv` | `companies_found.csv` | Company list used by step 2 |
| **Step 2: people + emails** | | |
| `--roles` | all | `recruiter,hr,founder,product,senior_mgmt` |
| `--city` | first word of `--location` | City hint for the people search |
| `--budget N` | `45` | Max Hunter credits this month |
| `--max-companies N` | all | Only the first N companies |
| `--free-only` | off | Never spend Hunter credits |
| `--leads` | `leads.csv` | Output file |
| **Steps 3–4: write + send** | | |
| `--draft-limit N` | all | Only write N new drafts |
| `--test` | off | Email 2 drafts to yourself first |
| `--send` | off | Send at the end (asks you to type SEND) |
| `--max-send N` | daily limit | Send at most N this run |
| `--now` | off | Allow sending outside weekday 9:00–18:00 |
| `--yes` | off | Skip the SEND confirmation (unattended) |
| **General** | | |
| `--from` | `find` | Start at `find`, `leads`, `draft` or `send` |

---

## What each step does

Each script also runs on its own. Use `python <script> --help` to see all its options.

### Step 1: `company_finder.py` (a Claude agent)

```bash
python company_finder.py --location "Delhi NCR, India" --industry "AI, SaaS" --count 30
```

Claude runs a tool loop and makes the judgement calls. Python checks every save.

| Tool | Source | Cost |
|---|---|---|
| `discover_companies` | Hunter Discover (HQ city, size bucket, industry, keywords) | Free |
| `google_search` | Serper, only for unclear companies | 1 search |
| `find_linkedin_page` | Serper `site:linkedin.com/company` | 1 search |
| `save_company` | Python checks: real LinkedIn URL, size in range, tier 2/3, not a duplicate | — |

- **What the tiers mean** is set in `TIER_GUIDE` at the top of the file. Household names like Flipkart or Paytm count as tier 1 and are skipped. Edit the text if your idea of "tier 2" is different.
- **Why each company was picked:** every row has a `reason` column so you can review Claude's choices.
- **Size buckets:** LinkedIn and Hunter group sizes into buckets, so a minimum of 100 includes the whole 51–200 bucket.
- **Resuming:** re-running adds to `companies_found.csv` and never adds a duplicate.

### Step 2: `lead_finder.py`

```bash
python lead_finder.py --input companies_found.csv --location Delhi
```

For each company it does this:

- **Domain:** finds the email domain (Hunter, free).
- **Real emails:** pulls up to 3 real emails of senior people, which also reveals the company's email format.
- **More people:** finds more people through public LinkedIn search results (Serper).
- **Filtering:** drops junior staff and ex-employees, and scores everyone left by role.
- **Emails for the rest:** builds them from the company's format and verifies them. If verification fails, it tries Hunter's Email Finder.

**Role groups** (edit `TARGET_ROLES` to change them):

| Group | Finds |
|---|---|
| `recruiter` | Recruiters, talent acquisition, hiring roles |
| `hr` | HR managers, HRBP, CHRO, people leads |
| `founder` | Founders, owners, CEO, MD (**startups ≤ 200 employees only**) |
| `product` | Product managers, Head / Director / VP of Product |
| `senior_mgmt` | Senior managers, directors, heads, VPs, CXOs |

**Dropped automatically:** intern, trainee, fresher, junior, HR Executive, Assistant Manager, Associate, ex-/former employees, "open to work". Edit `EXCLUDE_PATTERNS` to change this.

### Step 3–4: `outreach.py`

```bash
python outreach.py draft --leads leads.csv    # writes outbox.csv, sends nothing
python outreach.py test                       # 2 drafts to your own inbox
python outreach.py send                       # sends approved drafts after you type SEND
```

- **Your resume:** Claude reads `resume.pdf` once and prints the facts it found. Emails use **only** those facts, so it can't invent or inflate anything.
- **Each email:**
  - 45–120 words, plain text, starting with "Hi {first name},"
  - one specific reason for that company
  - one real proof point from your resume
  - a question that fits the person's role (recruiters and HR are asked about openings, founders are offered a 10-minute chat, managers are asked for the right person)
  - a casual mention of the attached resume
  - an easy "no worries if not" line
- **Humanised by checking:** drafts with templated phrases ("I hope this email finds you well", "passionate about", "please find attached", em dashes…) are rewritten automatically. Anything still failing is marked `NEEDS_REVIEW` with `approved=no`.
- **Signature** (name, phone, LinkedIn) is added by the script. The resume is attached as `Your_Name_Resume.pdf`.

**Safety limits** (change them in `CONFIG` in `outreach.py`):

| Limit | Default |
|---|---|
| Which emails | only `valid` / `accept_all` |
| Per day | 20 (Gmail allows 500, but a personal inbox doing cold email should stay low) |
| Gap between emails | random 1–2.5 minutes |
| When | Mon–Fri, 9:00–18:00 (override with `--now`) |
| Per company | max 2 people |
| Never twice | every sent address is logged in `outreach.db` |
| Opt-outs | anyone in `do_not_contact.txt` (one email or `@domain` per line) |

---

## Files it creates

| File | What's in it |
|---|---|
| `companies_found.csv` | Companies with LinkedIn URL, size, tier and reason |
| `leads.csv` | People, titles, emails, `email_status`, priority, and why an email is missing (`error`) |
| `leads_companies.csv` | Per-company summary: domain, people found, emails found |
| `outbox.csv` | Drafts: `approved`, `status` (DRAFT / NEEDS_REVIEW / SENT / FAILED), subject, body |
| `lead_finder_cache.db` | Cache of every API response, plus your monthly Hunter credit count |
| `outreach.db` | Resume facts, and a log of everyone emailed |
| `do_not_contact.txt` | You create this: emails or `@domains` never to contact |

### `email_status` in `leads.csv`

| Status | Meaning | Emailed by default? |
|---|---|---|
| `valid` | Confirmed by the mail server | ✅ |
| `accept_all` | Server accepts everything; a bounce is still possible | ✅ |
| `unknown` / `pattern_unverified` | Couldn't confirm | ❌ (allow with `outreach.py draft --statuses valid,accept_all,unknown`) |
| `unverified_guess` | A guess (only with `--guess-emails`) | ❌ |
| `not_found` | No email. The `error` column says why | ❌ |

---

## Costs and limits

| Service | Free allowance | Roughly what it covers |
|---|---|---|
| Hunter | 50 credits/month | About 10–15 companies with good emails |
| Serper | 2,500 searches (once) | 1–2 per company found, plus 1–2 per company for people and news |
| Claude API | Pay-per-use | Each script prints the tokens used. Start with `--find 5` to see the cost |
| Gmail | 500 emails/day | The script caps you at 20/day |

Hunter's credits are shared across your whole Hunter account. `lead_finder.py` reads your real balance at the start of every run and never plans to spend more than you have.

---

---

## Dashboard vs Command Line

Both ways work! Choose what's easiest for you:

| Feature | Dashboard | Command Line |
|---------|-----------|--------------|
| **Ease** | ✅ Easiest — web interface | ⏺️ Requires terminal |
| **Real-time logs** | ✅ In browser | ✅ In terminal |
| **Resume upload** | ✅ Click to upload | ⏺️ File in folder |
| **Configuration** | ✅ Fill forms in sidebar | ⏺️ Edit .env manually |
| **CSV preview** | ✅ See data in dashboard | ⏺️ Open in Excel |
| **Multi-step runs** | ✅ Click next tab | ⏺️ Run commands manually |

**For most users:** Use the dashboard! It's faster and more visual.

**For power users / scripting:** Command line is still fully supported.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `Can't start yet: ... missing` | Fill that value in `.env` (copied from `.env.example`) |
| `ModuleNotFoundError` | Activate the venv, then `pip install -r requirements.txt` |
| `PermissionError` / "is locked" | Close the CSV in Excel. Move the folder out of OneDrive |
| `domain=- (not_found)` | Add a `website` column to your company CSV |
| `people=0` for many companies | Use a different `--city`, fewer `--roles`, or check your Serper credits |
| Many `not_found` emails | Read the `error` column: format rejected, no Hunter record, or no credits left |
| "credits are used up" | Normal on the free plan. Run again after the monthly reset |
| Gmail `Login failed` | Use an App Password, not your normal password, and make sure 2-Step Verification is on |
| `outside weekday 9:00–18:00` | Run during work hours, or add `--now` |
| Test emails land in spam | Send fewer per day, and edit drafts to sound more like you |
| Tier looks wrong | Edit `TIER_GUIDE` in `company_finder.py` and check the `reason` column |

**Dashboard-specific issues:**

| Problem | Fix |
|---------|-----|
| `ModuleNotFoundError: streamlit` | Run `pip install streamlit` |
| Browser doesn't open | Manually go to `http://localhost:8501` |
| Can't find resume.pdf | Upload in dashboard's "Draft Emails" tab |
| Logs not updating | Refresh browser or wait for step to complete |
| "API Key missing" error | Go to sidebar → 🔑 API Keys → paste key → click Save |

For more detail on any step, add `-v` to `lead_finder.py`, or run that step's script on its own.

**Dashboard guides:**
- [Dashboard Quick Start](DASHBOARD_QUICKSTART.md) — 3-step setup
- [Dashboard Full Guide](README_DASHBOARD.md) — Complete user manual

---

## Responsible use

- **Keep it personal and small.** Send a few well-targeted emails a day, and read every draft before approving it. That works better and keeps your Gmail out of spam folders.
- **Only contact people about genuine job interest.** Use work emails only, and honour every "no" by adding it to `do_not_contact.txt`.
- **Data protection law applies.** In India that's the DPDP Act 2023; for EU contacts, GDPR. Keep only what you need, and the `email_source` column records where each email came from.
- **Don't scrape LinkedIn or automate actions on it.** These tools only read public search results and use licensed email-data APIs.

Keep `.env`, `resume.pdf` and the `.db` files private. If you use Git, add them to `.gitignore`.