from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path, PurePosixPath

from tools import reconcile_hp0_evidence


ROOT = Path(__file__).resolve().parents[2]
INDEX = ROOT / "evidence/hardware/index.json"


class HP0EvidenceReconciliationTests(unittest.TestCase):
    def test_index_freezes_exact_terminal_result_and_authorities(self) -> None:
        index = reconcile_hp0_evidence.load_index(INDEX)
        self.assertEqual(index["terminal_result"], "DUAL_ISA_PRESSURE_OBSERVED")
        self.assertEqual(
            index["dual_qualifier"]["hardware_result"],
            "DUAL_NAMED_BOARD_OBSERVED",
        )
        self.assertEqual(index["source_authority"]["library_version"], 17)
        self.assertEqual(index["source_authority"]["file_count"], 368)
        self.assertEqual(set(index["accepted_runs"]), {"esp32s3", "esp32c6"})
        for digest in (
            index["source_authority"]["sha256"],
            index["source_authority"]["source_tree_sha256"],
            index["handoff_authority"]["sha256"],
            index["input_evidence_archive"]["sha256"],
            index["dual_qualifier"]["qualification_report_json_sha256"],
        ):
            self.assertEqual(len(digest), 64)
            int(digest, 16)

    def test_hp0_document_supersedes_old_path_and_freezes_exclusions(self) -> None:
        document = (ROOT / "docs/HP0_EVIDENCE_RECONCILIATION.md").read_text(
            encoding="utf-8"
        )
        for token in (
            "DUAL_ISA_PRESSURE_OBSERVED",
            "old HX6/HX7 provider composition",
            "MQTT implementation",
            "GPIO or broad peripheral expansion",
            "RAX packaging",
            "host-firmware, bootloader, or partition-table OTA",
            "HP1 and HP2",
            "Native ELF remains trusted, scarce target refinement",
        ):
            self.assertIn(token, document)

    def test_verify_file_fails_closed_on_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "artifact.bin"
            path.write_bytes(b"accepted")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            reconcile_hp0_evidence.verify_file(path, digest=digest, size=8)
            path.write_bytes(b"tampered")
            with self.assertRaises(reconcile_hp0_evidence.ReconciliationError):
                reconcile_hp0_evidence.verify_file(path, digest=digest, size=8)

    def test_nested_workspace_copy_is_not_an_accepted_s3_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            reports = Path(temporary) / "reports"
            s3 = reports / "hardware/hx5b-aitrip-001"
            c6 = reports / "hardware/hx5b-xiao-c6-001"
            dual = reports / "host-extension/hx5b-dual-001"
            (s3 / "project/reports/hardware/hx5b-xiao-c6-001").mkdir(
                parents=True
            )
            c6.mkdir(parents=True)
            dual.mkdir(parents=True)
            (s3 / "serial.log").write_text("s3", encoding="utf-8")
            (s3 / "project/reports/hardware/hx5b-xiao-c6-001/serial.log").write_text(
                "duplicate", encoding="utf-8"
            )
            (c6 / "serial.log").write_text("c6", encoding="utf-8")
            (dual / "qualification-report.json").write_text("{}", encoding="utf-8")
            index = {
                "hp0": {
                    "excluded_input_paths": [
                        {"path": "hardware/hx5b-aitrip-001/project/reports"}
                    ]
                }
            }
            files = reconcile_hp0_evidence.collect_run_files(
                reports_root=reports,
                s3_run=s3,
                c6_run=c6,
                dual_run=dual,
                index=index,
            )
            logical = {path.as_posix() for _, path in files}
            self.assertIn(
                "hardware/esp32s3/hx5b-aitrip-001/serial.log", logical
            )
            self.assertIn(
                "hardware/esp32c6/hx5b-xiao-c6-001/serial.log", logical
            )
            self.assertFalse(any("project/reports" in path for path in logical))

    def test_manifested_package_is_deterministic_and_records_exclusion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = root / "serial.log"
            payload.write_text("retained serial\n", encoding="utf-8")
            reconciliation = {
                "schema": "pulse.esp32.hp0-evidence-reconciliation.v1",
                "status": "PASS",
                "terminal_result": "DUAL_ISA_PRESSURE_OBSERVED",
            }
            exclusion = [
                {
                    "path": "hardware/hx5b-aitrip-001/project/reports",
                    "reason": "duplicate",
                }
            ]
            outputs = []
            for name in ("first.zip", "second.zip"):
                output = root / name
                result = reconcile_hp0_evidence.write_evidence_package(
                    output=output,
                    files=[
                        (
                            payload,
                            PurePosixPath(
                                "hardware/esp32s3/hx5b-aitrip-001/serial.log"
                            ),
                        )
                    ],
                    reconciliation=reconciliation,
                    exclusions=exclusion,
                )
                self.assertEqual(result["status"], "PASS")
                outputs.append(output.read_bytes())
            self.assertEqual(outputs[0], outputs[1])
            with zipfile.ZipFile(root / "first.zip") as archive:
                manifest = json.loads(
                    archive.read(
                        f"{reconcile_hp0_evidence.ARCHIVE_ROOT}/EVIDENCE-MANIFEST.json"
                    )
                )
            self.assertEqual(manifest["terminal_result"], "DUAL_ISA_PRESSURE_OBSERVED")
            self.assertEqual(manifest["excluded_input_paths"], exclusion)

    def test_make_runner_and_docs_expose_hp0_without_firmware_changes(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        runner = (ROOT / "tools/run_contract_tests.py").read_text(encoding="utf-8")
        packaging = (ROOT / "docs/PACKAGING_AND_EVIDENCE.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("check-hp0", makefile)
        self.assertIn("hp0-evidence-reconcile", makefile)
        self.assertIn("test_hp0_evidence_reconciliation", runner)
        self.assertIn("HP0", packaging)


if __name__ == "__main__":
    unittest.main()
