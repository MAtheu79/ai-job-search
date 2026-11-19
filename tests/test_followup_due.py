"""Tests for tools/followup_due.py (follow-up cadence over the tracker)."""

import tempfile
import unittest
from datetime import date
from pathlib import Path

from tools import followup_due as fd

TODAY = date(2026, 11, 19)
NO_APPS = Path("/nonexistent-applications-dir")


def row(**kw):
    base = {"date": "", "company": "Acme", "role": "Data Scientist", "status": "applied",
            "notes": "", "contact_person": ""}
    base.update(kw)
    return base


def one(**kw):
    results = fd.analyse([row(**kw)], TODAY, NO_APPS)
    return results[0] if results else None


class AppliedCadenceTests(unittest.TestCase):
    def test_recent_application_waits(self):
        self.assertEqual(one(date="2026-11-15")["action"], "wait")

    def test_first_follow_up_after_a_week(self):
        r = one(date="2026-11-10")
        self.assertEqual(r["action"], "first_follow_up")
        self.assertTrue(r["due"])

    def test_note_date_resets_the_clock(self):
        r = one(date="2026-10-01", notes="2026-11-15 follow-up sent to recruiter")
        self.assertEqual(r["followups_sent"], 1)
        self.assertEqual(r["action"], "wait")

    def test_final_follow_up(self):
        r = one(date="2026-10-20", notes="2026-11-05 follow-up sent")
        self.assertEqual(r["action"], "final_follow_up")

    def test_consider_outcome_after_two_follow_ups(self):
        r = one(date="2026-10-01", notes="2026-10-08 follow-up sent; 2026-10-20 followed up")
        self.assertEqual(r["action"], "consider_outcome")


class InterviewCadenceTests(unittest.TestCase):
    def test_thank_you_right_after_interview(self):
        r = one(date="2026-10-01", status="interview", notes="2026-11-18 phone screen")
        self.assertEqual(r["action"], "send_thank_you")

    def test_no_thank_you_twice(self):
        r = one(date="2026-10-01", status="interview", notes="2026-11-18 screen; thank-you sent")
        self.assertEqual(r["action"], "wait")

    def test_check_in_after_a_week(self):
        r = one(date="2026-10-01", status="interview", notes="2026-11-10 technical round")
        self.assertEqual(r["action"], "interview_check_in")

    def test_outcome_md_stage_dates_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "acme_data_scientist"
            folder.mkdir()
            (folder / "outcome.md").write_text("- [x] Phone screen (2026-11-18)\n", encoding="utf-8")
            r = fd.analyse([row(date="2026-10-01", status="interview")], TODAY, Path(tmp))[0]
        self.assertEqual(r["last_activity"], "2026-11-18")


class FilteringTests(unittest.TestCase):
    def test_final_statuses_skipped(self):
        for status in ("rejected", "hired", "no_response", "Offer declined", "withdrawn"):
            self.assertIsNone(one(date="2026-01-01", status=status), status)

    def test_missing_date_is_flagged(self):
        self.assertEqual(one()["action"], "missing_date")

    def test_future_dates_ignored(self):
        r = one(date="2026-11-01", notes="interview booked for 2026-12-03")
        self.assertEqual(r["last_activity"], "2026-11-01")

    def test_missing_tracker_is_empty(self):
        self.assertEqual(fd.main(["--tracker", "/nonexistent.csv", "--today", "2026-11-19"]), 0)


if __name__ == "__main__":
    unittest.main()
