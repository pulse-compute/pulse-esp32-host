from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools import build_idf_cell, check_idf_matrix, qualify_idf_matrix

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "firmware/idf-family-matrix.json"
IMAGE = check_idf_matrix.CANONICAL_LANE["container_image"]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evidence(path: Path, relative: str) -> dict[str, object]:
    return {"path": relative, "sha256": sha256(path), "size": path.stat().st_size}


class FakeMatrixBuilder:
    def __init__(
        self,
        *,
        results: dict[str, str] | None = None,
        corrupt_cell: str | None = None,
        different_source_cell: str | None = None,
        raise_cell: str | None = None,
    ) -> None:
        self.results = results or {
            "esp32s3-reference": "COMPILE_PROVEN",
            "esp32c3-compile": "INCOMPATIBLE",
            "esp32-compile": "INCOMPATIBLE",
            "esp32c6-compile": "COMPILE_PROVEN",
        }
        self.corrupt_cell = corrupt_cell
        self.different_source_cell = different_source_cell
        self.raise_cell = raise_cell
        self.calls: list[str] = []

    def __call__(self, **kwargs: object) -> dict[str, object]:
        cell = str(kwargs["cell_id"])
        if cell == self.raise_cell:
            raise RuntimeError("simulated builder crash")
        self.calls.append(cell)
        out = Path(kwargs["out_dir"])  # type: ignore[arg-type]
        matrix_path = Path(kwargs["matrix_path"])  # type: ignore[arg-type]
        out.mkdir(parents=True)
        matrix = check_idf_matrix.load_matrix(matrix_path)
        realization = matrix["realizations"][cell]
        result = self.results[cell]
        source = "b" * 64 if cell == self.different_source_cell else "a" * 64
        build_log = out / "build.log"
        build_log.write_text("region `dram0_0_seg` overflowed by 17664 bytes\n", encoding="utf-8")
        lock_path = matrix_path.parent / realization["dependency_lock"]
        inputs = {
            "source_tree_sha256": source,
            "dependency_lock": evidence(lock_path, realization["dependency_lock"]),
        }
        outputs: dict[str, object] = {"build_log": evidence(build_log, "build.log")}
        status = "PASS" if result == "COMPILE_PROVEN" else "FAIL"
        failure = None
        if result != "COMPILE_PROVEN":
            failure = {
                "stage": "build",
                "message": "build command exited with status 2: region `dram0_0_seg` overflowed by 17664 bytes",
            }
        if result == "COMPILE_PROVEN":
            sdkconfig = out / "sdkconfig"
            sdkconfig.write_text(f'CONFIG_IDF_TARGET="{realization["target"]}"\n', encoding="utf-8")
            size = out / "size.json"
            size.write_text('{"total_size": 1234}\n', encoding="utf-8")
            artifacts: dict[str, object] = {}
            for name, relative in build_idf_cell.EXPECTED_ARTIFACTS.items():
                path = out / "artifacts" / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"{cell}:{relative}\n", encoding="utf-8")
                artifacts[name] = evidence(path, f"artifacts/{relative}")
            outputs.update(
                {
                    "artifacts": artifacts,
                    "sdkconfig": evidence(sdkconfig, "sdkconfig"),
                    "size": evidence(size, "size.json"),
                    "resolved_lock": {
                        "path": realization["dependency_lock"],
                        "sha256": inputs["dependency_lock"]["sha256"],  # type: ignore[index]
                        "target": realization["target"],
                        "wamr_version": "2.4.0~1",
                        "wamr_component_hash": "hash",
                    },
                }
            )
        report: dict[str, object] = {
            "schema": build_idf_cell.REPORT_SCHEMA,
            "status": status,
            "result": result,
            "cell": cell,
            "lane": {"id": realization["lane"], **matrix["lanes"][realization["lane"]]},
            "realization": {"id": cell, "target": realization["target"]},
            "evidence": {"inputs": inputs, "outputs": outputs},
            "failure": failure,
        }
        report_path = out / "cell-report.json"
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if cell == self.corrupt_cell:
            build_log.write_text("corrupted after report\n", encoding="utf-8")
        return report


class IDFMatrixQualificationTests(unittest.TestCase):
    def qualify(
        self, temporary: Path, builder: FakeMatrixBuilder, *, family: bool = True
    ) -> tuple[dict[str, object], Path]:
        out = temporary / "matrix"
        report = qualify_idf_matrix.qualify_matrix(
            matrix_path=MATRIX,
            out_dir=out,
            observed_container_image=IMAGE,
            include_exploratory=family,
            timeout=10,
            cell_builder=builder,
        )
        return report, out

    def test_family_mapping_accepts_only_compile_proven_or_deterministic_incompatible(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            builder = FakeMatrixBuilder()
            report, out = self.qualify(Path(name), builder)
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(
                builder.calls,
                [
                    "esp32s3-reference",
                    "esp32s3-reference",
                    "esp32c3-compile",
                    "esp32-compile",
                    "esp32c6-compile",
                ],
            )
            self.assertEqual(report["result_counts"], {"BUILD_QUALIFIED": 1, "COMPILE_PROVEN": 1, "INCOMPATIBLE": 2})
            self.assertTrue(all(cell["evidence_complete"] for cell in report["cells"]))  # type: ignore[index]
            self.assertTrue((out / "matrix-report.json").is_file())
            self.assertTrue((out / "matrix-report.md").is_file())
            self.assertTrue(all(item["status"] == "NOT_ATTEMPTED_POLICY" for item in report["inventory"]["deferred"]))  # type: ignore[index]

    def test_reference_only_does_not_attempt_exploratory_cells(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            builder = FakeMatrixBuilder()
            report, _out = self.qualify(Path(name), builder, family=False)
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(builder.calls, ["esp32s3-reference", "esp32s3-reference"])
            self.assertEqual([item["id"] for item in report["cells"]], ["esp32s3-reference"])  # type: ignore[index]

    def test_infrastructure_failure_fails_but_later_cells_are_still_attempted(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            builder = FakeMatrixBuilder(
                results={
                    "esp32s3-reference": "COMPILE_PROVEN",
                    "esp32c3-compile": "INFRASTRUCTURE_FAILURE",
                    "esp32-compile": "INCOMPATIBLE",
                    "esp32c6-compile": "COMPILE_PROVEN",
                }
            )
            report, _out = self.qualify(Path(name), builder)
            self.assertEqual(report["status"], "FAIL")
            self.assertEqual(builder.calls[-3:], list(qualify_idf_matrix.EXPLORATORY_CELLS))
            self.assertTrue(any(item["gate"] == "esp32c3-compile" for item in report["failed_gates"]))  # type: ignore[index]

    def test_missing_evidence_source_drift_and_builder_crash_fail_closed(self) -> None:
        cases = (
            (FakeMatrixBuilder(corrupt_cell="esp32c6-compile"), "esp32c6-compile-evidence"),
            (FakeMatrixBuilder(different_source_cell="esp32c6-compile"), "source-reproducibility"),
            (FakeMatrixBuilder(raise_cell="esp32-compile"), "esp32-compile"),
        )
        for builder, gate in cases:
            with self.subTest(gate=gate), tempfile.TemporaryDirectory() as name:
                report, _out = self.qualify(Path(name), builder)
                self.assertEqual(report["status"], "FAIL")
                self.assertTrue(any(item["gate"] == gate for item in report["failed_gates"]))  # type: ignore[index]

    def test_wrong_image_stops_before_builds_and_dirty_output_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            temporary = Path(name)
            builder = FakeMatrixBuilder()
            report = qualify_idf_matrix.qualify_matrix(
                matrix_path=MATRIX,
                out_dir=temporary / "wrong-image",
                observed_container_image="espressif/idf:v5.4.4",
                include_exploratory=True,
                cell_builder=builder,
            )
            self.assertEqual(report["status"], "FAIL")
            self.assertEqual(builder.calls, [])
            self.assertEqual(report["failed_gates"][0]["gate"], "container-identity")  # type: ignore[index]

            dirty = temporary / "dirty"
            dirty.mkdir()
            prior = dirty / "prior.txt"
            prior.write_text("preserve\n", encoding="utf-8")
            with self.assertRaisesRegex(qualify_idf_matrix.MatrixQualificationError, "absent or empty"):
                qualify_idf_matrix.qualify_matrix(
                    matrix_path=MATRIX,
                    out_dir=dirty,
                    observed_container_image=IMAGE,
                    include_exploratory=True,
                    cell_builder=builder,
                )
            self.assertEqual(prior.read_text(encoding="utf-8"), "preserve\n")

    def test_evidence_paths_must_be_normalized_and_confined(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name) / "cell"
            root.mkdir()
            outside = root.parent / "outside.log"
            outside.write_text("outside\n", encoding="utf-8")
            escaped = {
                "path": "../outside.log",
                "sha256": sha256(outside),
                "size": outside.stat().st_size,
            }
            self.assertFalse(qualify_idf_matrix._file_matches(root, escaped))


if __name__ == "__main__":
    unittest.main()
