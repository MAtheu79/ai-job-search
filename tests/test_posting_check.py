"""Tests for tools/posting_check.py (closed-posting signals and repost detection)."""

import csv
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from tools import posting_check as pc

LONG_BODY = " ".join(["We are looking for a data scientist to join our team."] * 10)


class ClosedSignalTests(unittest.TestCase):
    today = date(2026, 11, 19)

    def test_open_posting(self):
        result = pc.check_closed(LONG_BODY + "\nDeadline: 2026-12-01", self.today)
        self.assertEqual(result["verdict"], "open")
        self.assertEqual(result["days_to_deadline"], 12)

    def test_english_closed_phrase(self):
        result = pc.check_closed(LONG_BODY + "\nNo longer accepting applications", self.today)
        self.assertEqual(result["verdict"], "closed")

    def test_danish_closed_phrase_with_special_letters(self):
        result = pc.check_closed(LONG_BODY + "\nAnnoncen er udløbet.", self.today)
        self.assertEqual(result["verdict"], "closed")

    def test_spanish_closed_phrase_with_accents(self):
        result = pc.check_closed(LONG_BODY + "\nLa oferta ya no está disponible", self.today)
        self.assertEqual(result["verdict"], "closed")

    def test_past_deadline_day_first_format(self):
        result = pc.check_closed(LONG_BODY + "\nAnsøgningsfrist: 01.11.2026", self.today)
        self.assertEqual(result["verdict"], "closed")
        self.assertTrue(result["deadline_passed"])

    def test_dates_without_deadline_cue_are_ignored(self):
        result = pc.check_closed(LONG_BODY + "\nPublished 2020-01-01", self.today)
        self.assertEqual(result["verdict"], "open")
        self.assertEqual(result["deadlines"], [])

    def test_short_page_is_unclear(self):
        self.assertEqual(pc.check_closed("Sign in to continue", self.today)["verdict"], "unclear")


class NormalizationTests(unittest.TestCase):
    def test_company_suffixes_dropped(self):
        self.assertEqual(pc.normalize_company("Acme A/S"), pc.normalize_company("ACME"))
        self.assertEqual(pc.normalize_company("Ørsted GmbH"), "orsted")

    def test_gender_tags_ignored(self):
        self.assertEqual(pc.title_similarity("Data Scientist (m/f/d)", "Data Scientist"), 1.0)

    def test_seniority_variants_are_similar(self):
        self.assertGreaterEqual(pc.title_similarity("Senior Data Scientist", "Data Scientist"), 0.8)

    def test_different_roles_are_not_similar(self):
        self.assertLess(pc.title_similarity("Data Scientist", "Office Manager"), 0.5)


class RepostTests(unittest.TestCase):
    seen = {
        "https://jobs.example/1": {
            "title": "Data Scientist", "company": "Acme A/S",
            "url": "https://jobs.example/1", "first_seen": "2026-08-01", "status": "expired",
        },
        "https://jobs.example/9": {
            "title": "Office Manager", "company": "Acme A/S",
            "url": "https://jobs.example/9", "first_seen": "2026-09-01", "status": "new",
        },
    }

    def test_new_job(self):
        result = pc.check_repost("Other Co", "Data Scientist", "", self.seen, [])
        self.assertEqual(result["verdict"], "new")
        self.assertEqual(result["matches"], [])

    def test_same_url_is_seen_before(self):
        result = pc.check_repost("Acme", "Data Scientist", "https://jobs.example/1", self.seen, [])
        self.assertEqual(result["verdict"], "seen_before")

    def test_different_url_is_likely_repost(self):
        result = pc.check_repost("ACME", "Data Scientist (m/f/d)", "https://jobs.example/2", self.seen, [])
        self.assertEqual(result["verdict"], "likely_repost")
        self.assertEqual(result["first_seen"], "2026-08-01")
        self.assertEqual(len(result["matches"]), 1)

    def test_tracker_match_wins(self):
        tracker = [{"company": "Acme", "role": "Data Scientist", "date": "2026-08-05", "status": "rejected"}]
        result = pc.check_repost("Acme", "Data Scientist", "https://jobs.example/2", self.seen, tracker)
        self.assertEqual(result["verdict"], "already_applied")


class CliTests(unittest.TestCase):
    def test_missing_state_files_are_empty_not_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = pc.main([
                "repost", "--company", "Acme", "--title", "Data Scientist",
                "--seen", str(Path(tmp) / "missing.json"),
                "--tracker", str(Path(tmp) / "missing.csv"),
            ])
        self.assertEqual(code, 0)

    def test_loaders_read_real_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            seen_path = Path(tmp) / "seen.json"
            seen_path.write_text(json.dumps({"seen": self.__class__.seen_fixture()}), encoding="utf-8")
            tracker_path = Path(tmp) / "tracker.csv"
            with open(tracker_path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["date", "company", "role", "status"])
                writer.writeheader()
                writer.writerow({"date": "2026-01-01", "company": "Acme", "role": "Analyst", "status": "applied"})
            self.assertEqual(len(pc.load_seen(seen_path)), 1)
            self.assertEqual(pc.load_tracker(tracker_path)[0]["role"], "Analyst")

    @staticmethod
    def seen_fixture():
        return {"k": {"title": "X", "company": "Y", "first_seen": "2026-01-01"}}


if __name__ == "__main__":
    unittest.main()
