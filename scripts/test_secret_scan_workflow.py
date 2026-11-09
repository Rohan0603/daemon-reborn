"""Regression tests for the license-free, integrity-verified CI scanner."""

import unittest
from pathlib import Path

WORKFLOW = (
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / "secret-scan.yml"
)


class SecretScanWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_uses_pinned_license_free_cli_with_checksum_verification(self) -> None:
        self.assertNotIn("gitleaks/gitleaks-action", self.workflow)
        self.assertIn("GITLEAKS_VERSION: 8.30.1", self.workflow)
        self.assertIn("gitleaks_${GITLEAKS_VERSION}_checksums.txt", self.workflow)
        self.assertIn("sha256sum --check --strict", self.workflow)

    def test_scanner_is_redacted_and_real_cli_regression_runs(self) -> None:
        self.assertIn("--redact", self.workflow)
        self.assertIn("--no-banner", self.workflow)
        self.assertIn("scripts/test_gitleaks_cli.py", self.workflow)

    def test_workflow_has_read_only_contents_permission(self) -> None:
        self.assertIn("permissions:", self.workflow)
        self.assertIn("contents: read", self.workflow)


if __name__ == "__main__":
    unittest.main()
