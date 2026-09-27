#!/usr/bin/env python3
"""
Streamlit Dashboard for Job Outreach Automation
Run: streamlit run streamlit_app.py
"""

import os
import sys
import json
import subprocess
import threading
import time
from pathlib import Path
from datetime import datetime

import streamlit as st

try:
    from dotenv import load_dotenv, set_key
except ImportError:
    st.error("Please install python-dotenv: pip install python-dotenv")
    sys.exit(1)

# ════════════════════════════════════════════════════════════════════════════
#  CONFIG & PATHS
# ════════════════════════════════════════════════════════════════════════════

HERE = Path(__file__).resolve().parent
ENV_FILE = HERE / ".env"
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)

st.set_page_config(
    page_title="Job Outreach Automation",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ════════════════════════════════════════════════════════════════════════════
#  UTILITY FUNCTIONS
# ════════════════════════════════════════════════════════════════════════════

def save_env_var(key, value):
    """Safely save env var to .env file."""
    if not ENV_FILE.exists():
        ENV_FILE.write_text("")
    set_key(str(ENV_FILE), key, value)
    os.environ[key] = value


def get_env(key, default=""):
    """Get env var safely."""
    return os.getenv(key, default).strip()


def count_csv_rows(path):
    """Count rows in CSV file."""
    import csv
    p = Path(path)
    if not p.exists():
        return 0
    try:
        with open(p, newline="", encoding="utf-8-sig") as f:
            return sum(1 for _ in csv.DictReader(f))
    except Exception:
        return 0


def read_csv_preview(path, limit=5):
    """Read first N rows of CSV."""
    import csv
    p = Path(path)
    if not p.exists():
        return None
    try:
        with open(p, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            return [next(reader) for _ in range(limit) if reader]
    except Exception:
        return None


def run_command(cmd, output_placeholder):
    """Run Python command and stream output to placeholder."""
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        output_text = []
        for line in process.stdout:
            line = line.rstrip()
            output_text.append(line)
            output_placeholder.text_area(
                "Live Output",
                value="\n".join(output_text[-100:]),  # Show last 100 lines
                height=400,
                disabled=True
            )
            time.sleep(0.01)  # Small delay for UI update

        returncode = process.wait()
        return returncode, "\n".join(output_text)
    except Exception as e:
        error_msg = f"Error running command: {str(e)}"
        output_placeholder.error(error_msg)
        return 1, error_msg


# ════════════════════════════════════════════════════════════════════════════
#  SIDEBAR - CONFIGURATION
# ════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("## ⚙️ Configuration")

    with st.expander("🔑 API Keys", expanded=False):
        st.info("Keys are saved to `.env` and NOT stored elsewhere.")

        hunter_key = st.text_input(
            "Hunter API Key",
            value=get_env("HUNTER_API_KEY"),
            type="password",
            key="hunter_input"
        )
        if hunter_key and st.button("Save Hunter Key", key="save_hunter"):
            save_env_var("HUNTER_API_KEY", hunter_key)
            st.success("✅ Hunter key saved")

        serper_key = st.text_input(
            "Serper API Key",
            value=get_env("SERPER_API_KEY"),
            type="password",
            key="serper_input"
        )
        if serper_key and st.button("Save Serper Key", key="save_serper"):
            save_env_var("SERPER_API_KEY", serper_key)
            st.success("✅ Serper key saved")

        anthropic_key = st.text_input(
            "Anthropic API Key",
            value=get_env("ANTHROPIC_API_KEY"),
            type="password",
            key="anthropic_input"
        )
        if anthropic_key and st.button("Save Anthropic Key", key="save_anthropic"):
            save_env_var("ANTHROPIC_API_KEY", anthropic_key)
            st.success("✅ Anthropic key saved")

    with st.expander("👤 Personal Details", expanded=True):
        name = st.text_input(
            "Your Name",
            value=get_env("MY_NAME"),
            key="name_input"
        )
        if name and st.button("Save Name", key="save_name"):
            save_env_var("MY_NAME", name)
            st.success("✅ Name saved")

        target_role = st.text_input(
            "Target Role (e.g., Product Manager)",
            value=get_env("MY_TARGET_ROLE"),
            key="role_input"
        )
        if target_role and st.button("Save Role", key="save_role"):
            save_env_var("MY_TARGET_ROLE", target_role)
            st.success("✅ Role saved")

        phone = st.text_input(
            "Phone (optional)",
            value=get_env("MY_PHONE"),
            key="phone_input"
        )
        if phone and st.button("Save Phone", key="save_phone"):
            save_env_var("MY_PHONE", phone)
            st.success("✅ Phone saved")

        linkedin = st.text_input(
            "LinkedIn URL (optional)",
            value=get_env("MY_LINKEDIN"),
            key="linkedin_input"
        )
        if linkedin and st.button("Save LinkedIn", key="save_linkedin"):
            save_env_var("MY_LINKEDIN", linkedin)
            st.success("✅ LinkedIn saved")

    with st.expander("📧 Email Settings", expanded=False):
        smtp_user = st.text_input(
            "Gmail Address (SMTP User)",
            value=get_env("SMTP_USER"),
            key="smtp_user_input"
        )
        if smtp_user and st.button("Save Email", key="save_smtp_user"):
            save_env_var("SMTP_USER", smtp_user)
            st.success("✅ Email saved")

        smtp_pass = st.text_input(
            "Gmail App Password (NOT your normal password)",
            value=get_env("SMTP_PASSWORD"),
            type="password",
            key="smtp_pass_input"
        )
        if smtp_pass and st.button("Save App Password", key="save_smtp_pass"):
            save_env_var("SMTP_PASSWORD", smtp_pass)
            st.success("✅ App Password saved")

        st.caption("📝 Need an App Password? [Follow Google's guide](https://support.google.com/accounts/answer/185833)")

    st.divider()

    # Status check
    st.markdown("### ✓ Status Check")
    checks = {
        "Hunter Key": bool(get_env("HUNTER_API_KEY")),
        "Serper Key": bool(get_env("SERPER_API_KEY")),
        "Anthropic Key": bool(get_env("ANTHROPIC_API_KEY")),
        "My Name": bool(get_env("MY_NAME")),
        "Target Role": bool(get_env("MY_TARGET_ROLE")),
        "Gmail Address": bool(get_env("SMTP_USER")),
        "App Password": bool(get_env("SMTP_PASSWORD")),
    }

    for check, status in checks.items():
        icon = "✅" if status else "❌"
        st.write(f"{icon} {check}")

    all_set = all(checks.values())
    if all_set:
        st.success("🎉 All configured! Ready to run.")
    else:
        st.warning("⚠️ Fill in the missing fields to proceed.")

# ════════════════════════════════════════════════════════════════════════════
#  MAIN DASHBOARD
# ════════════════════════════════════════════════════════════════════════════

st.markdown("# 🚀 Job Outreach Automation Dashboard")
st.markdown("Find companies → Discover leads → Write emails → Send with resume")

# Tabs for each step
tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["📊 Dashboard", "🏢 Find Companies", "👥 Find Leads", "✉️ Draft Emails", "📤 Send Emails"]
)

# ──────────────────────────────────────────────────────────────────────────────
#  TAB 1: DASHBOARD
# ──────────────────────────────────────────────────────────────────────────────

with tab1:
    st.markdown("## Progress Summary")

    col1, col2, col3, col4 = st.columns(4)

    companies_count = count_csv_rows(HERE / "companies_found.csv")
    leads_count = count_csv_rows(HERE / "leads.csv")

    import csv
    drafts_count = 0
    drafts_sent = 0
    outbox_path = HERE / "outbox.csv"
    if outbox_path.exists():
        with open(outbox_path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if row.get("approved", "").lower() == "yes" and row.get("status") != "SENT":
                    drafts_count += 1
                if row.get("status") == "SENT":
                    drafts_sent += 1

    with col1:
        st.metric("Companies Found", companies_count)
    with col2:
        st.metric("Leads Discovered", leads_count)
    with col3:
        st.metric("Drafts Ready", drafts_count)
    with col4:
        st.metric("Emails Sent", drafts_sent)

    st.divider()

    # Show latest files
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### Latest Companies")
        companies_preview = read_csv_preview(HERE / "companies_found.csv", limit=3)
        if companies_preview:
            st.dataframe(companies_preview, use_container_width=True)
        else:
            st.info("No companies found yet. Go to 'Find Companies' to start.")

    with col2:
        st.markdown("### Latest Leads")
        leads_preview = read_csv_preview(HERE / "leads.csv", limit=3)
        if leads_preview:
            st.dataframe(leads_preview, use_container_width=True)
        else:
            st.info("No leads found yet. Discover some leads first.")

# ──────────────────────────────────────────────────────────────────────────────
#  TAB 2: FIND COMPANIES
# ──────────────────────────────────────────────────────────────────────────────

with tab2:
    st.markdown("## Step 1: Find Companies")
    st.markdown("Claude AI searches for tier-2/3 companies matching your criteria.")

    col1, col2 = st.columns(2)

    with col1:
        location = st.text_input(
            "Location",
            value="Delhi NCR, India",
            help='e.g., "Delhi NCR, India" or "Bengaluru"'
        )
        industry = st.text_input(
            "Industry",
            value="AI, SaaS, fintech",
            help='e.g., "AI, SaaS, fintech" (leave blank for any)'
        )
        find_count = st.number_input(
            "Number of Companies to Find",
            value=10,
            min_value=1,
            max_value=50
        )

    with col2:
        tiers = st.multiselect(
            "Company Tiers",
            ["2", "3"],
            default=["2", "3"],
            help="Tier 2: well-known in industry | Tier 3: smaller/regional"
        )
        min_size = st.number_input("Min Company Size", value=100, min_value=1)
        max_size = st.number_input("Max Company Size", value=10000, min_value=100)

    st.divider()

    if st.button("🔍 Find Companies", key="btn_find_companies", use_container_width=True):
        if not get_env("ANTHROPIC_API_KEY"):
            st.error("❌ Missing ANTHROPIC_API_KEY. Add it in Configuration → API Keys.")
        else:
            st.info("⏳ Searching for companies... (this may take 2-5 minutes)")
            output_placeholder = st.empty()

            cmd = [
                sys.executable,
                str(HERE / "company_finder.py"),
                "--location", location,
                "--industry", industry,
                "--count", str(find_count),
                "--tiers", ",".join(tiers),
                "--min-size", str(min_size),
                "--max-size", str(max_size),
            ]

            returncode, output = run_command(cmd, output_placeholder)

            if returncode == 0:
                new_count = count_csv_rows(HERE / "companies_found.csv")
                st.success(f"✅ Found! {new_count} companies total in companies_found.csv")
            else:
                st.error(f"❌ Error: {output[-500:]}")

# ──────────────────────────────────────────────────────────────────────────────
#  TAB 3: FIND LEADS
# ──────────────────────────────────────────────────────────────────────────────

with tab3:
    st.markdown("## Step 2: Find Leads")
    st.markdown("Discover senior people and their work emails at each company.")

    companies_count = count_csv_rows(HERE / "companies_found.csv")
    if companies_count == 0:
        st.warning("⚠️ No companies found. Complete Step 1 first.")
    else:
        st.success(f"✅ {companies_count} companies ready to process")

    col1, col2 = st.columns(2)

    with col1:
        roles = st.multiselect(
            "Target Roles",
            ["recruiter", "hr", "founder", "product", "senior_mgmt"],
            default=["recruiter", "hr"],
            help="Leave blank for all roles"
        )
        city = st.text_input(
            "City Hint (for searches)",
            value="Delhi",
            help="e.g., 'Delhi' to bias search results"
        )

    with col2:
        budget = st.number_input(
            "Hunter Budget (credits)",
            value=45,
            min_value=0,
            max_value=200,
            help="Free tier: 50 credits/month"
        )
        free_only = st.checkbox(
            "Free Sources Only",
            value=False,
            help="Don't spend Hunter credits"
        )

    st.divider()

    if st.button("👥 Find Leads", key="btn_find_leads", use_container_width=True):
        if not get_env("HUNTER_API_KEY"):
            st.error("❌ Missing HUNTER_API_KEY. Add it in Configuration → API Keys.")
        elif not get_env("SERPER_API_KEY"):
            st.error("❌ Missing SERPER_API_KEY. Add it in Configuration → API Keys.")
        else:
            st.info("⏳ Finding leads... (this may take 5-15 minutes depending on number of companies)")
            output_placeholder = st.empty()

            cmd = [
                sys.executable,
                str(HERE / "lead_finder.py"),
                "--input", str(HERE / "companies_found.csv"),
                "--location", city,
                "--budget", str(budget),
            ]

            if roles:
                cmd.extend(["--roles", ",".join(roles)])
            if free_only:
                cmd.append("--free-only")

            returncode, output = run_command(cmd, output_placeholder)

            if returncode == 0:
                leads_count = count_csv_rows(HERE / "leads.csv")
                st.success(f"✅ Found! {leads_count} leads total in leads.csv")
            else:
                st.error(f"❌ Error: {output[-500:]}")

# ──────────────────────────────────────────────────────────────────────────────
#  TAB 4: DRAFT EMAILS
# ──────────────────────────────────────────────────────────────────────────────

with tab4:
    st.markdown("## Step 3: Draft Emails")
    st.markdown("Claude writes personalized emails for each lead. YOU review before sending.")

    leads_count = count_csv_rows(HERE / "leads.csv")
    if leads_count == 0:
        st.warning("⚠️ No leads found. Complete Step 2 first.")
    else:
        st.success(f"✅ {leads_count} leads ready")

    # Resume upload
    st.markdown("### 📄 Your Resume")
    resume_path = HERE / "resume.pdf"
    if resume_path.exists():
        st.success(f"✅ Found: {resume_path.name}")
    else:
        st.warning("⚠️ resume.pdf not found in this folder. Upload it to proceed.")
        uploaded_file = st.file_uploader("Upload resume.pdf", type=["pdf"], key="resume_upload")
        if uploaded_file:
            resume_path.write_bytes(uploaded_file.getvalue())
            st.success("✅ Resume saved!")

    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        draft_limit = st.number_input(
            "Max Drafts to Write",
            value=0,
            min_value=0,
            help="0 = write for all leads"
        )

    if st.button("✉️ Write Drafts", key="btn_draft", use_container_width=True):
        if not get_env("ANTHROPIC_API_KEY"):
            st.error("❌ Missing ANTHROPIC_API_KEY.")
        elif not resume_path.exists():
            st.error("❌ resume.pdf not found. Upload it above.")
        else:
            st.info("⏳ Writing drafts... (1-2 minutes)")
            output_placeholder = st.empty()

            cmd = [
                sys.executable,
                str(HERE / "outreach.py"),
                "draft",
                "--leads", str(HERE / "leads.csv"),
            ]

            if draft_limit > 0:
                cmd.extend(["--limit", str(draft_limit)])

            returncode, output = run_command(cmd, output_placeholder)

            if returncode == 0:
                st.success("✅ Drafts written to outbox.csv")
                st.info("📋 Next: Review outbox.csv, edit drafts, set approved=yes/no, then come back and Send.")
            else:
                st.error(f"❌ Error: {output[-500:]}")

    st.divider()

    # Show current drafts
    st.markdown("### Current Drafts")
    outbox_preview = read_csv_preview(HERE / "outbox.csv", limit=5)
    if outbox_preview:
        st.dataframe(outbox_preview, use_container_width=True)
        st.caption(f"Showing first 5 of {count_csv_rows(HERE / 'outbox.csv')} drafts. "
                   "Open outbox.csv to edit and review all.")
    else:
        st.info("No drafts yet. Click 'Write Drafts' above to create them.")

# ──────────────────────────────────────────────────────────────────────────────
#  TAB 5: SEND EMAILS
# ──────────────────────────────────────────────────────────────────────────────

with tab5:
    st.markdown("## Step 4: Send Emails")
    st.markdown("Send approved drafts from your Gmail with resume.pdf attached.")

    import csv
    approved_count = 0
    outbox_path = HERE / "outbox.csv"
    if outbox_path.exists():
        with open(outbox_path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if row.get("approved", "").lower() == "yes" and row.get("status") != "SENT":
                    approved_count += 1

    if approved_count == 0:
        st.warning("⚠️ No approved drafts. Review and set approved=yes in outbox.csv first.")
    else:
        st.success(f"✅ {approved_count} drafts approved and ready to send")

    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        max_send = st.number_input(
            "Max to Send Today",
            value=5,
            min_value=1,
            max_value=20,
            help="Default: 20/day limit"
        )
    with col2:
        now = st.checkbox("Send Now", value=False, help="Allow sending outside 9-18, Mon-Fri")

    st.divider()

    send_mode = st.radio(
        "Send Mode",
        ["One by One (with confirmation)", "Bulk (send all at once)"],
        help="Choose how to send: review each email or send all approved at once"
    )

    st.divider()

    if st.button("📤 Send Approved Emails", key="btn_send", use_container_width=True):
        if not get_env("SMTP_USER"):
            st.error("❌ Missing Gmail address (SMTP_USER).")
        elif not get_env("SMTP_PASSWORD"):
            st.error("❌ Missing Gmail App Password (SMTP_PASSWORD).")
        elif not (HERE / "resume.pdf").exists():
            st.error("❌ resume.pdf not found.")
        else:
            st.info("⏳ Sending emails... (check dashboard for live output)")
            output_placeholder = st.empty()

            cmd = [
                sys.executable,
                str(HERE / "outreach.py"),
                "send",
                "--max", str(max_send),
            ]

            if now:
                cmd.append("--now")
            cmd.append("--yes")
            if "Bulk" in send_mode:
                cmd.append("--bulk")

            returncode, output = run_command(cmd, output_placeholder)

            if returncode == 0:
                sent_count = count_csv_rows(HERE / "outbox.csv", lambda r: r.get("status") == "SENT")
                st.success(f"✅ Done! {sent_count} emails sent in total")
            else:
                st.warning(f"⚠️ Process completed (check output above for details)")

# ════════════════════════════════════════════════════════════════════════════
#  FOOTER
# ════════════════════════════════════════════════════════════════════════════

st.divider()
st.markdown("""
---
**📖 Help & Documentation**
- [README](../README.md) — Full usage guide
- [.env.example](../.env.example) — Configuration template

**⚖️ Responsible Use**
- Send a few targeted emails per day
- Review every draft before approval
- Honor every "no" by adding to do_not_contact.txt
- Follow GDPR / data protection laws in your region

**🔒 Privacy**
- Your API keys are stored only in `.env` (not uploaded, not logged)
- Everything runs locally on your machine
- Resume is read by Claude, not stored
""")
