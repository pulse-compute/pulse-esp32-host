from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools import package_release


ROOT = Path(__file__).resolve().parents[2]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ReleasePackagingTests(unittest.TestCase):
    def test_compact_index_replaces_generated_report_links(self) -> None:
        index_path = ROOT / "evidence/host-extension/index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        self.assertEqual(
            index["schema"],
            "pulse.esp32.host-extension-evidence-index.v1",
        )
        self.assertEqual(
            [item["pass"] for item in index["accepted_runs"]],
            ["HX1", "HX2", "HX3", "HX4", "HX4.5"],
        )
        for item in index["accepted_runs"]:
            self.assertEqual(item["status"], "PASS")
            self.assertEqual(item["target_runtime"], "HARDWARE_NOT_RUN")
            self.assertEqual(len(item["qualification_report_json_sha256"]), 64)
            self.assertEqual(
                len(item["qualification_report_markdown_sha256"]), 64
            )
        for path in ROOT.joinpath("docs").glob("HX*.md"):
            self.assertNotIn(
                "../reports/host-extension/",
                path.read_text(encoding="utf-8"),
            )

    def test_source_package_is_deterministic_lean_and_allowlisted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "first.zip"
            second = Path(temporary) / "second.zip"
            files = package_release.collect_source_files(ROOT)
            for output in (first, second):
                result = package_release.write_package(
                    output=output,
                    archive_root=package_release.SOURCE_ARCHIVE_ROOT,
                    files=files,
                    kind="SOURCE",
                    manifest_name="PACKAGE-MANIFEST.json",
                    maximum_bytes=package_release.SOURCE_PACKAGE_MAX_BYTES,
                )
                self.assertEqual(result["status"], "PASS")
            self.assertEqual(digest(first), digest(second))
            self.assertLessEqual(
                first.stat().st_size,
                package_release.SOURCE_PACKAGE_MAX_BYTES,
            )
            with zipfile.ZipFile(first) as archive:
                names = archive.namelist()
                self.assertIn(
                    "pulse-esp32-host-main/PACKAGE-MANIFEST.json", names
                )
                self.assertIn(
                    "pulse-esp32-host-main/tests/hardware-in-loop/"
                    "hx45-s3-aitrip-n8r2/fixtures/"
                    "synthetic-loopback-esp32s3.elf",
                    names,
                )
                for bundle in (
                    "relay-controller-r6.wdcb",
                    "relay-controller-r8.wdcb",
                ):
                    self.assertIn(
                        "pulse-esp32-host-main/examples/bundles/"
                        f"relay-controller/dist/{bundle}",
                        names,
                    )
                report_names = {
                    name.split("pulse-esp32-host-main/", 1)[1]
                    for name in names
                    if "/reports/" in name
                }
                self.assertEqual(
                    report_names,
                    {
                        "reports/.gitkeep",
                        "reports/README.md",
                        "reports/logs/.gitkeep",
                    },
                )
                self.assertFalse(any("/managed_components/" in name for name in names))
                self.assertFalse(any("/__pycache__/" in name for name in names))
                self.assertTrue(
                    all(info.date_time == package_release.FIXED_ZIP_TIME for info in archive.infolist())
                )
                executable = archive.getinfo(
                    "pulse-esp32-host-main/tools/check_deps.py"
                )
                regular = archive.getinfo(
                    "pulse-esp32-host-main/docs/PACKAGING_AND_EVIDENCE.md"
                )
                self.assertEqual(executable.external_attr >> 16, 0o100755)
                self.assertEqual(regular.external_attr >> 16, 0o100644)
                manifest = json.loads(
                    archive.read(
                        "pulse-esp32-host-main/PACKAGE-MANIFEST.json"
                    )
                )
                self.assertEqual(manifest["kind"], "SOURCE")
                self.assertEqual(manifest["file_count"], len(files))

    def test_unexpected_generated_artifact_fails_closed(self) -> None:
        package_release.validate_source_artifact(
            Path("tests/contract/native_extension_vectors/valid-esp32s3.elf")
        )
        with self.assertRaises(package_release.PackageError):
            package_release.validate_source_artifact(Path("firmware/accidental.elf"))
        with self.assertRaises(package_release.PackageError):
            package_release.validate_source_artifact(Path("docs/accidental.bin"))

    def test_hardware_package_requires_pass_and_keeps_build_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary) / "run"
            (run / "evaluation").mkdir(parents=True)
            (run / "build/CMakeFiles").mkdir(parents=True)
            (run / "build-report.json").write_text("{}\n", encoding="utf-8")
            (run / "serial.log").write_text(
                'PULSE_HX45_FINAL {"status":"PASS"}\n', encoding="utf-8"
            )
            (run / "evaluation/qualification-report.md").write_text(
                "# PASS\n", encoding="utf-8"
            )
            evaluation_path = run / "evaluation/qualification-report.json"
            evaluation_path.write_text(
                json.dumps(
                    {
                        "runtime_result": "NAMED_BOARD_OBSERVED",
                        "status": "PASS",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            build_object = run / "build/CMakeFiles/retained.o"
            build_object.write_bytes(b"retained build evidence")
            files = package_release.collect_hardware_evidence_files(run)
            self.assertIn(
                Path("build/CMakeFiles/retained.o"),
                [relative for _, relative in files],
            )
            evaluation_path.write_text(
                '{"runtime_result":"FAILED","status":"FAIL"}\n',
                encoding="utf-8",
            )
            with self.assertRaises(package_release.PackageError):
                package_release.collect_hardware_evidence_files(run)

    def test_make_and_docs_expose_split_packages(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        packaging = (ROOT / "docs/PACKAGING_AND_EVIDENCE.md").read_text(
            encoding="utf-8"
        )
        for token in (
            "package-source",
            "package-host-evidence",
            "package-hardware-evidence",
        ):
            self.assertIn(token, makefile)
            self.assertIn(token, packaging)
        self.assertIn("SOURCE_PACKAGE_MAX_BYTES", package_release.__dict__)


if __name__ == "__main__":
    unittest.main()
