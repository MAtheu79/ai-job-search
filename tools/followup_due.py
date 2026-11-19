#!/usr/bin/env python3
"""Work out which open applications need a follow-up, from job_search_tracker.csv.

Read-only. Prints JSON: one entry per open application with the last activity
date, days elapsed, follow-ups already sent, and the recommended next action.

  python tools/followup_due.py [--tracker PATH] [--applications DIR] [--today YYYY-MM-DD] [--all]

Activity dates come from the tracker `date` column, any YYYY-MM-DD dates in the
`notes` column, and stage dates in documents/applications/<company>_<role>/outcome.md.
Follow-ups are counted from notes entries such as "2026-11-02 follow-up sent";
thank-you notes from "thank-you sent". /followup writes those notes.
"""

import argparse
import csv
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TRACKER = ROOT / "job_search_tracker.csv"
DEFAULT_APPLICATIONS = ROOT / "documents" / "applications"

FINAL_STATUSES = {
    "hired", "rejected", "no response", "withdrawn", "offer declined",
    "interview only", "closed", "declined",
}
DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
FOLLOWUP_RE = re.compile(r"follow[- ]?up sent|followed up", re.IGNORECASE)
THANKYOU_RE = re.compile(r"thank[- ]?you( note| email)? sent", re.IGNORECASE)

# Cadence (calendar days since last activity).
APPLIED_FIRST_NUDGE = 7
APPLIED_SECOND_NUDGE = 10   # days after the first follow-up
APPLIED_GIVE_UP = 30        # days since applying, with 2 follow-ups and no reply
INTERVIEW_CHECK_IN = 7
INTERVIEW_SECOND_CHECK_IN = 14


def normalize_status(value):
    return re.sub(r"[_\s]+", " ", (value or "").strip().lower())


def parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")


def outcome_dates(applications_dir, company, role):
    path = Path(applications_dir) / f"{slug(company)}_{slug(role)}" / "outcome.md"
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return []
    return [d for d in (parse_date(m) for m in DATE_RE.findall(text)) if d]


def recommend(status, days, followups, thank_you_sent, days_since_applied):
    """Return (action, due) for an open application."""
    if status in ("interview", "interviewing") or status.startswith("interview"):
        if days <= 1 and not thank_you_sent:
            return "send_thank_you", True
        if followups == 0 and days >= INTERVIEW_CHECK_IN:
            return "interview_check_in", True
        if followups == 1 and days >= INTERVIEW_SECOND_CHECK_IN:
            return "interview_second_check_in", True
        if followups >= 2 and days >= INTERVIEW_SECOND_CHECK_IN:
            return "consider_outcome", True
        return "wait", False
    if status == "offer":
        return "respond_to_offer", True
    # applied (and any unknown open status)
    if followups == 0:
        return ("first_follow_up", True) if days >= APPLIED_FIRST_NUDGE else ("wait", False)
    if followups == 1:
        return ("final_follow_up", True) if days >= APPLIED_SECOND_NUDGE else ("wait", False)
    if days_since_applied is not None and days_since_applied >= APPLIED_GIVE_UP:
        return "consider_outcome", True
    return "wait", False


def analyse(rows, today, applications_dir):
    results = []
    for row in rows:
        status = normalize_status(row.get("status"))
        if status in FINAL_STATUSES:
            continue
        applied = parse_date((row.get("date") or "").strip())
        notes = row.get("notes") or ""
        dates = [d for d in (parse_date(m) for m in DATE_RE.findall(notes)) if d]
        dates += outcome_dates(applications_dir, row.get("company"), row.get("role"))
        if applied:
            dates.append(applied)
        dates = [d for d in dates if d <= today]
        if not dates:
            results.append({
                "company": row.get("company", ""), "role": row.get("role", ""),
                "status": status, "action": "missing_date", "due": True,
                "last_activity": None, "days_since_activity": None,
                "followups_sent": 0, "contact_person": row.get("contact_person", ""),
            })
            continue
        last = max(dates)
        days = (today - last).days
        followups = len(FOLLOWUP_RE.findall(notes))
        thank_you = bool(THANKYOU_RE.search(notes))
        since_applied = (today - applied).days if applied else None
        action, due = recommend(status, days, followups, thank_you, since_applied)
        results.append({
            "company": row.get("company", ""),
            "role": row.get("role", ""),
            "status": status,
            "applied": applied.isoformat() if applied else None,
            "last_activity": last.isoformat(),
            "days_since_activity": days,
            "followups_sent": followups,
            "contact_person": row.get("contact_person", ""),
            "action": action,
            "due": due,
        })
    results.sort(key=lambda r: (not r["due"], -(r["days_since_activity"] or 0)))
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description="List applications that need a follow-up.")
    parser.add_argument("--tracker", type=Path, default=DEFAULT_TRACKER)
    parser.add_argument("--applications", type=Path, default=DEFAULT_APPLICATIONS)
    parser.add_argument("--today", help="override today's date (YYYY-MM-DD)")
    parser.add_argument("--all", action="store_true", help="include applications not yet due")
    args = parser.parse_args(argv)

    today = parse_date(args.today) if args.today else date.today()
    if today is None:
        print("Error: --today must be YYYY-MM-DD", file=sys.stderr)
        return 1
    try:
        with open(args.tracker, newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
    except FileNotFoundError:
        rows = []

    results = analyse(rows, today, args.applications)
    if not args.all:
        results = [r for r in results if r["due"]]
    print(json.dumps({"today": today.isoformat(), "applications": results}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
