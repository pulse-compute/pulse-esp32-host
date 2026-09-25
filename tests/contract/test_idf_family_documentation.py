from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

from tools import check_idf_family_docs

ROOT = Path(__file__).resolve().parents[2]
DOCUMENT = ROOT / "docs/reference/IDF_FAMILY_MATRIX.md"


class IDFFamilyDocumentationTests(unittest.TestCase):
    def test_canonical_if7_document_matches_matrix_and_claim_contract(self) -> None:
        self.assertEqual(check_idf_family_docs.validate_static(), [])

    def test_status_or_configuration_drift_fails_closed(self) -> None:
        original = DOCUMENT.read_text(encoding="utf-8")
        cases = (
            (
                "The S3 reference firmware is reproducibly build-qualified under the pinned\n"
                "ESP-IDF lane. Additional family targets have explicit compile-probe results.",
                "The firmware builds on several chips.",
                "exact allowed IF7 status",
            ),
            (
                check_idf_family_docs.configuration_identity(
                    ROOT / "firmware/idf-family-matrix.json", "esp32c6-compile"
                ),
                "0" * 64,
                "configuration hash for esp32c6-compile",
            ),
        )
        for old, new, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as name:
                document = Path(name) / "IDF_FAMILY_MATRIX.md"
                document.write_text(original.replace(old, new), encoding="utf-8")
                errors = check_idf_family_docs.validate_static(document=document)
                self.assertTrue(any(expected in error for error in errors), errors)

    def test_optional_archive_without_evidence_root_is_cli_usage_error(self) -> None:
        with redirect_stderr(StringIO()):
            self.assertEqual(check_idf_family_docs.main(["--evidence-archive", "missing.zip"]), 2)


if __name__ == "__main__":
    unittest.main()
