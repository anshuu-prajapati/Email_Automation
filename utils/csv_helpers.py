"""
CSV file handling utilities.
"""

import csv
from pathlib import Path


def count_rows(filepath, filter_fn=None):
    """Count rows in CSV file, optionally filtering."""
    p = Path(filepath)
    if not p.exists():
        return 0
    try:
        with open(p, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if filter_fn:
                return sum(1 for row in reader if filter_fn(row))
            else:
                return sum(1 for _ in reader)
    except Exception as e:
        print(f"Error counting rows in {filepath}: {e}")
        return 0


def read_preview(filepath, limit=5):
    """Read first N rows of CSV file."""
    p = Path(filepath)
    if not p.exists():
        return None
    try:
        with open(p, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            return [next(reader) for _ in range(limit) if reader]
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return None


def read_all(filepath):
    """Read all rows from CSV file."""
    p = Path(filepath)
    if not p.exists():
        return []
    try:
        with open(p, newline="", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return []


def get_summary_stats():
    """Get counts of companies, leads, drafts, sent."""
    HERE = Path(__file__).parent.parent

    companies = count_rows(HERE / "companies_found.csv")
    leads = count_rows(HERE / "leads.csv")

    drafts_ready = count_rows(
        HERE / "outbox.csv",
        filter_fn=lambda r: r.get("approved", "").lower() == "yes" and r.get("status") != "SENT"
    )

    sent = count_rows(
        HERE / "outbox.csv",
        filter_fn=lambda r: r.get("status") == "SENT"
    )

    return {
        "companies": companies,
        "leads": leads,
        "drafts_ready": drafts_ready,
        "sent": sent,
    }
