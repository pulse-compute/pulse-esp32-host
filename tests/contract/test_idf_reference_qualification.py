from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools import build_idf_cell, check_idf_matrix, qualify_idf_reference

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "firmware/idf-family-matrix.json"
IMAGE = check_idf_matrix.CANONICAL_LANE["container_image"]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FakeCellBuilder:
    def __init__(
        self,
        *,
        artifact_mismatch: bool = False,
        sdkconfig_mismatch: bool = False,
        lock_mismatch: bool = False,
        failure_result: str | None = None,
    ) -> None:
        self.calls = 0
        self.artifact_mismatch = artifact_mismatch
        self.sdkconfig_mismatch = sdkconfig_mismatch
        self.lock_mismatch = lock_mismatch
        self.failure_result = failure_result

    def __call__(self, **kwargs: object) -> dict[str, object]:
        self.calls += 1
        out_dir = Path(kwargs["out_dir"])  # type: ignore[arg-type]
        matrix_path = Path(kwargs["matrix_path"])  # type: ignore[arg-type]
        out_dir.mkdir()
        matrix = check_idf_matrix.load_matrix(matrix_path)
        realization = matrix["realizations"]["esp32s3-reference"]
        lock_path = matrix_path.parent / realization["dependency_lock"]
        lock_bytes = lock_path.read_bytes()
        lock_sha = sha256(lock_bytes)
        source_inputs = {
            "matrix": {"path": matrix_path.name, "sha256": sha256(matrix_path.read_bytes())},
            "source_tree_sha256": "source-tree",
            "source_files": [],
            "defaults": [],
            "partitions": {"path": realization["partitions"], "sha256": "partition"},
            "dependency_lock": {
                "path": realization["dependency_lock"],
                "sha256": lock_sha,
                "size": len(lock_bytes),
            },
        }
        sdkconfig = b'CONFIG_IDF_TARGET="esp32s3"\n'
        if self.sdkconfig_mismatch and self.calls == 2:
            sdkconfig += b"CONFIG_TEST_DIFFERENCE=y\n"
        (out_dir / "sdkconfig").write_bytes(sdkconfig)
        (out_dir / "build.log").write_text("normalized build\n", encoding="utf-8")
        (out_dir / "size.json").write_text('{"total_size": 1234}\n', encoding="utf-8")

        artifact_evidence: dict[str, object] = {}
        for name, relative in build_idf_cell.EXPECTED_ARTIFACTS.items():
            data = f"esp32s3:{relative}\n".encode("utf-8")
            if self.artifact_mismatch and self.calls == 2 and name == "application_binary":
                data += b"different\n"
            path = out_dir / "artifacts" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            artifact_evidence[name] = {
                "path": f"artifacts/{relative}",
                "sha256": sha256(data),
                "size": len(data),
            }

        status = "FAIL" if self.failure_result else "PASS"
        result = self.failure_result or "COMPILE_PROVEN"
        report: dict[str, object] = {
            "schema": build_idf_cell.REPORT_SCHEMA,
            "status": status,
            "result": result,
            "cell": "esp32s3-reference",
            "lane": {"id": "idf-5.4.4", **matrix["lanes"]["idf-5.4.4"]},
            "realization": {"id": "esp32s3-reference", "target": "esp32s3"},
            "evidence": {
                "inputs": source_inputs,
                "outputs": {
                    "artifacts": artifact_evidence,
                    "sdkconfig": {
                        "path": "sdkconfig",
                        "sha256": sha256(sdkconfig),
                        "size": len(sdkconfig),
                    },
                    "resolved_lock": {
                        "path": realization["dependency_lock"],
                        "sha256": "different-lock" if self.lock_mismatch and self.calls == 2 else lock_sha,
                        "target": "esp32s3",
                        "wamr_version": "2.4.0~1",
                        "wamr_component_hash": "component-hash",
                    },
                },
            },
            "failure": (
                {"stage": "build", "message": "simulated cell failure"}
                if self.failure_result
                else None
            ),
        }
        (out_dir / "cell-report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return report


class IDFReferenceQualificationTests(unittest.TestCase):
    def qualify(self, temporary: Path, builder: FakeCellBuilder) -> tuple[dict[str, object], Path]:
        output = temporary / "qualification"
        report = qualify_idf_reference.qualify_reference(
            matrix_path=MATRIX,
            out_dir=output,
            observed_container_image=IMAGE,
            timeout=10,
            cell_builder=builder,
        )
        return report, output

    def test_two_identical_builds_are_build_qualified(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            temporary = Path(temporary_name)
            builder = FakeCellBuilder()
            report, output = self.qualify(temporary, builder)
            self.assertEqual(builder.calls, 2)
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["result"], "BUILD_QUALIFIED")
            self.assertEqual(len(report["runs"]), 2)  # type: ignore[arg-type]
            comparisons = report["comparisons"]  # type: ignore[assignment]
            self.assertTrue(comparisons["inputs_identical"])
            self.assertTrue(comparisons["sdkconfig_identical"])
            self.assertTrue(comparisons["dependency_lock_identical"])
            self.assertTrue(all(item["identical"] for item in comparisons["artifacts"].values()))
            self.assertTrue((output / "qualification-report.json").is_file())
            self.assertTrue((output / "qualification-report.md").is_file())
            self.assertNotIn(str(temporary), (output / "qualification-report.json").read_text())
            deferred = report["deferred_hardware"]  # type: ignore[assignment]
            self.assertTrue(deferred)
            self.assertTrue(all(item["status"] == "DEFERRED_NO_HARDWARE_IF4" for item in deferred))

    def test_artifact_difference_fails_reproducibility(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            report, _output = self.qualify(
                Path(temporary_name), FakeCellBuilder(artifact_mismatch=True)
            )
            self.assertEqual(report["status"], "FAIL")
            self.assertEqual(report["result"], "UNCLASSIFIED_FAILURE")
            self.assertEqual(report["failed_gates"][0]["gate"], "artifact-reproducibility")  # type: ignore[index]
            comparison = report["comparisons"]["artifacts"]["application_binary"]  # type: ignore[index]
            self.assertFalse(comparison["identical"])

    def test_sdkconfig_and_lock_differences_fail_closed(self) -> None:
        cases = (
            (FakeCellBuilder(sdkconfig_mismatch=True), "configuration-reproducibility"),
            (FakeCellBuilder(lock_mismatch=True), "dependency-reproducibility"),
        )
        for index, (builder, expected_gate) in enumerate(cases):
            with self.subTest(gate=expected_gate), tempfile.TemporaryDirectory() as temporary_name:
                output = Path(temporary_name) / str(index)
                report = qualify_idf_reference.qualify_reference(
                    matrix_path=MATRIX,
                    out_dir=output,
                    observed_container_image=IMAGE,
                    timeout=10,
                    cell_builder=builder,
                )
                self.assertEqual(report["status"], "FAIL")
                self.assertEqual(report["failed_gates"][0]["gate"], expected_gate)  # type: ignore[index]

    def test_cell_failure_classification_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            builder = FakeCellBuilder(failure_result="INFRASTRUCTURE_FAILURE")
            report, _output = self.qualify(Path(temporary_name), builder)
            self.assertEqual(builder.calls, 1)
            self.assertEqual(report["status"], "FAIL")
            self.assertEqual(report["result"], "INFRASTRUCTURE_FAILURE")
            self.assertEqual(report["failed_gates"][0]["gate"], "run-a")  # type: ignore[index]

    def test_container_identity_is_required_before_builds(self) -> None:
        for observed in (None, "espressif/idf:v5.4.4"):
            with self.subTest(observed=observed), tempfile.TemporaryDirectory() as temporary_name:
                builder = FakeCellBuilder()
                report = qualify_idf_reference.qualify_reference(
                    matrix_path=MATRIX,
                    out_dir=Path(temporary_name) / "output",
                    observed_container_image=observed,
                    timeout=10,
                    cell_builder=builder,
                )
                self.assertEqual(builder.calls, 0)
                self.assertEqual(report["status"], "FAIL")
                self.assertEqual(report["result"], "INFRASTRUCTURE_FAILURE")
                self.assertEqual(report["failed_gates"][0]["gate"], "container-identity")  # type: ignore[index]

    def test_dirty_output_directory_is_preserved_and_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            output = Path(temporary_name) / "output"
            output.mkdir()
            evidence = output / "prior-report.json"
            evidence.write_text("preserve\n", encoding="utf-8")
            with self.assertRaisesRegex(
                qualify_idf_reference.ReferenceQualificationError, "absent or empty"
            ):
                qualify_idf_reference.qualify_reference(
                    matrix_path=MATRIX,
                    out_dir=output,
                    observed_container_image=IMAGE,
                    timeout=10,
                    cell_builder=FakeCellBuilder(),
                )
            self.assertEqual(evidence.read_text(encoding="utf-8"), "preserve\n")

    def test_pinned_idf_integration_repairs_remain_mechanical(self) -> None:
        caps_cmake = (ROOT / "firmware/components/wdc_caps/CMakeLists.txt").read_text(
            encoding="utf-8"
        )
        runtime = (ROOT / "firmware/components/wdc_runtime/wdc_runtime.c").read_text(
            encoding="utf-8"
        )
        self.assertIn("PRIV_REQUIRES esp_timer", caps_cmake)
        for export in (
            "WDC_EXPORT_INIT",
            "WDC_EXPORT_ON_EVENT",
            "WDC_EXPORT_HEALTH",
            "WDC_EXPORT_SHUTDOWN",
        ):
            self.assertIn(f"wasm_runtime_lookup_function(module_inst, {export})", runtime)
        self.assertNotIn("wasm_runtime_lookup_function(module_inst, WDC_EXPORT_INIT, NULL)", runtime)


if __name__ == "__main__":
    unittest.main()
