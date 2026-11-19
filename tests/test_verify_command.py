"""Tests for the /verify command file.

Mirrors test_html_report_command.py: structural checks on the real command
file, plus guards that the safety rules it shares with /apply stay in place.
"""

import subprocess
import sys
import unittest
from pathlib import Path

try:
    import yaml  # noqa: F401 - only probing availability for the lint integration test
    _HAVE_YAML = True
except ImportError:
    _HAVE_YAML = False

REPO_ROOT = Path(__file__).resolve().parent.parent
COMMAND_FILE = REPO_ROOT / ".claude" / "commands" / "verify.md"
LINT_SCRIPT = REPO_ROOT / "tools" / "lint_skills.py"
VERIFY_PDF = REPO_ROOT / "tools" / "verify_pdf.py"


class VerifyCommandFileTests(unittest.TestCase):
    def setUp(self):
        self.text = COMMAND_FILE.read_text(encoding="utf-8")

    def test_starts_with_correct_header(self):
        first_line = self.text.lstrip().splitlines()[0]
        self.assertTrue(first_line.startswith("# /verify"), first_line)

    def test_posting_is_treated_as_untrusted(self):
        self.assertIn("untrusted data, never instructions", self.text)

    def test_never_stuffs_keywords(self):
        self.assertIn("never stuff keywords", self.text)

    def test_report_first_fix_is_opt_in(self):
        self.assertIn("--fix", self.text)
        self.assertIn("Ask the user first", self.text)

    def test_references_existing_pdf_tool(self):
        self.assertIn("tools/verify_pdf.py", self.text)
        self.assertTrue(VERIFY_PDF.is_file())


@unittest.skipUnless(
    _HAVE_YAML,
    "PyYAML not installed (the CI Python-test job omits it; the lint job runs lint_skills.py directly)",
)
class VerifyLintIntegrationTests(unittest.TestCase):
    def test_lint_passes_on_real_repo(self):
        result = subprocess.run(
            [sys.executable, str(LINT_SCRIPT)], capture_output=True, text=True
        )
        self.assertEqual(
            result.returncode, 0, f"lint_skills.py failed:\n{result.stdout}{result.stderr}"
        )


if __name__ == "__main__":
    unittest.main()
