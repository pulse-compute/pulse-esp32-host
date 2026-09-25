from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import build_idf_cell, check_idf_matrix, verify_idf_environment

ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = ROOT / "firmware" / "idf-family-matrix.json"
CHECKER = ROOT / "tools" / "check_idf_matrix.py"


class IDFFamilyMatrixContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.matrix = check_idf_matrix.load_matrix(MATRIX_PATH)

    def run_checker_text(self, text: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temp_dir:
            firmware = Path(temp_dir) / "firmware"
            firmware.mkdir()
            shutil.copy2(ROOT / "firmware/sdkconfig.defaults", firmware / "sdkconfig.defaults")
            shutil.copy2(ROOT / "firmware/partitions.csv", firmware / "partitions.csv")
            shutil.copytree(ROOT / "firmware/realizations", firmware / "realizations")
            shutil.copytree(ROOT / "firmware/partitions", firmware / "partitions")
            path = firmware / "idf-family-matrix.json"
            path.write_text(text, encoding="utf-8")
            return subprocess.run(
                [sys.executable, "-B", str(CHECKER), "--matrix", str(path)],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )

    def run_checker(self, matrix: dict[str, object]) -> subprocess.CompletedProcess[str]:
        return self.run_checker_text(json.dumps(matrix, indent=2) + "\n")

    def test_canonical_matrix_passes_cli_validation(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-B", str(CHECKER), "--matrix", str(MATRIX_PATH)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout)
        report = json.loads(proc.stdout)
        self.assertEqual(report["schema"], "pulse.esp32.idf-family-matrix.v1")
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["inventory_count"], 10)
        self.assertEqual(report["resolved_realization_count"], 4)

    def test_all_canonical_target_locks_pass_fail_closed_validation(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-B", str(CHECKER), "--check-locks"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout)
        report = json.loads(proc.stdout)
        self.assertEqual(report["lock_count"], 4)
        self.assertEqual(
            {lock["target"] for lock in report["locks"].values()},
            {"esp32", "esp32s3", "esp32c3", "esp32c6"},
        )
        self.assertEqual(
            {lock["wamr_component_hash"] for lock in report["locks"].values()},
            {"04f25aad2896b5e906397a061d35cce560609bebd3913a4be7e365ecbf2dd9d6"},
        )

    def test_tampered_target_and_component_hash_fail_lock_validation(self) -> None:
        mutations = {
            "target": ("target: esp32c3", "target: esp32c6", "lock.target must be 'esp32c3'"),
            "component_hash": (
                "04f25aad2896b5e906397a061d35cce560609bebd3913a4be7e365ecbf2dd9d6",
                "14f25aad2896b5e906397a061d35cce560609bebd3913a4be7e365ecbf2dd9d6",
                "component_hash does not match",
            ),
        }
        for label, (old, new, expected_error) in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp_dir:
                firmware = Path(temp_dir) / "firmware"
                shutil.copytree(ROOT / "firmware", firmware)
                lock = firmware / "locks/idf-5.4.4/esp32c3/dependencies.lock"
                lock.write_text(lock.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
                proc = subprocess.run(
                    [sys.executable, "-B", str(CHECKER), "--matrix", str(firmware / "idf-family-matrix.json"), "--check-locks"],
                    cwd=ROOT,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn(expected_error, proc.stdout)

    def test_all_attempted_realizations_resolve_exact_configuration(self) -> None:
        s3 = check_idf_matrix.resolve_realization(self.matrix, "esp32s3-reference", MATRIX_PATH)
        self.assertEqual(
            s3["config"],
            {**check_idf_matrix.COMMON_CONFIG, **check_idf_matrix.S3_OVERLAY_CONFIG},
        )
        self.assertEqual(s3["partitions"], "partitions.csv")
        self.assertEqual(len(s3["partition_rows"]), 8)

        for realization_id in ["esp32-compile", "esp32c3-compile", "esp32c6-compile"]:
            with self.subTest(realization_id=realization_id):
                resolved = check_idf_matrix.resolve_realization(self.matrix, realization_id, MATRIX_PATH)
                self.assertEqual(
                    resolved["config"],
                    {
                        **check_idf_matrix.COMMON_CONFIG,
                        **check_idf_matrix.COMPILE_OVERLAY_CONFIGS[realization_id],
                    },
                )
                self.assertEqual(resolved["partition_rows"], s3["partition_rows"])

        esp32 = check_idf_matrix.resolve_realization(self.matrix, "esp32-compile", MATRIX_PATH)
        self.assertEqual(esp32["config"]["CONFIG_SPIRAM"], "n")
        for realization_id in ("esp32c3-compile", "esp32c6-compile"):
            resolved = check_idf_matrix.resolve_realization(self.matrix, realization_id, MATRIX_PATH)
            self.assertNotIn("CONFIG_SPIRAM", resolved["config"])
            self.assertNotIn("CONFIG_SPIRAM_USE_MALLOC", resolved["config"])

    def test_common_defaults_are_target_neutral_and_reproducible(self) -> None:
        common = check_idf_matrix.parse_sdkconfig_defaults(ROOT / "firmware/sdkconfig.defaults")
        self.assertEqual(common, check_idf_matrix.COMMON_CONFIG)
        for key in common:
            self.assertNotEqual(key, "CONFIG_IDF_TARGET")
            self.assertFalse(key.startswith("CONFIG_PARTITION_TABLE_"), key)
            self.assertFalse(key.startswith("CONFIG_ESPTOOLPY_FLASHSIZE"), key)
            self.assertFalse(key.startswith("CONFIG_SPIRAM"), key)

    def test_project_and_shell_identity_are_family_derived(self) -> None:
        cmake = (ROOT / "firmware/CMakeLists.txt").read_text(encoding="utf-8")
        self.assertIn("project(wdc_esp32_host)", cmake)
        self.assertNotIn("wdc_esp32s3_shell", cmake)

        shell_config = (ROOT / "firmware/main/shell_config.h").read_text(encoding="utf-8")
        self.assertIn("WDC_SHELL_TARGET CONFIG_IDF_TARGET", shell_config)
        self.assertIn('"wdc-" WDC_SHELL_TARGET "-shell"', shell_config)
        self.assertNotIn("wdc-esp32s3-shell", shell_config)
        self.assertNotIn("__DATE__", shell_config)
        self.assertNotIn("__TIME__", shell_config)

    def test_shell_identity_expands_for_host_and_idf_target(self) -> None:
        if shutil.which("gcc") is None:
            self.skipTest("gcc not available")

        for target, expected in [(None, "wdc-host-shell"), ("esp32c3", "wdc-esp32c3-shell")]:
            with self.subTest(target=target or "host"), tempfile.TemporaryDirectory() as temp_dir:
                temp = Path(temp_dir)
                if target is not None:
                    (temp / "sdkconfig.h").write_text(
                        f'#define CONFIG_IDF_TARGET "{target}"\n', encoding="utf-8"
                    )
                source = temp / "shell_identity.c"
                source.write_text(
                    "#include <string.h>\n"
                    '#include "shell_config.h"\n'
                    "int main(void) {\n"
                    f'    return strcmp(WDC_SHELL_NAME, "{expected}") != 0 || '
                    'strcmp(WDC_SHELL_BUILD_ID, "0.1.0-r9-R9") != 0;\n'
                    "}\n",
                    encoding="utf-8",
                )
                binary = temp / "shell_identity"
                command = [
                    "gcc",
                    "-std=c11",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-I",
                    str(ROOT / "firmware/main"),
                    "-I",
                    str(temp),
                ]
                if target is not None:
                    command.append("-DESP_PLATFORM")
                command.extend([str(source), "-o", str(binary)])
                compiled = subprocess.run(
                    command,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
                self.assertEqual(compiled.returncode, 0, compiled.stdout)
                executed = subprocess.run(
                    [str(binary)],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
                self.assertEqual(executed.returncode, 0, executed.stdout)

    def test_lane_and_inventory_are_exact(self) -> None:
        self.assertEqual(self.matrix["lanes"], {"idf-5.4.4": check_idf_matrix.CANONICAL_LANE})
        self.assertEqual(set(self.matrix["realizations"]), set(check_idf_matrix.EXPECTED_REALIZATIONS))
        self.assertEqual(
            {entry["id"] for entry in self.matrix["deferred"]}, set(check_idf_matrix.EXPECTED_DEFERRED)
        )
        self.assertEqual(
            {entry["id"] for entry in self.matrix["excluded"]}, set(check_idf_matrix.EXPECTED_EXCLUDED)
        )

    def test_lane_environment_verifier_rejects_version_and_commit_drift(self) -> None:
        lane = self.matrix["lanes"][check_idf_matrix.CANONICAL_LANE_ID]
        with tempfile.TemporaryDirectory() as temp_dir:
            idf_path = Path(temp_dir) / "idf"
            idf_py = idf_path / "tools/idf.py"
            idf_py.parent.mkdir(parents=True)
            idf_py.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

            def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
                if command[-1] == "--version":
                    return subprocess.CompletedProcess(command, 0, "ESP-IDF v5.4.4\n", "")
                return subprocess.CompletedProcess(command, 0, lane["source_commit"] + "\n", "")

            report = verify_idf_environment.verify_idf_environment(
                MATRIX_PATH,
                idf_path=idf_path,
                idf_py=idf_py,
                runner=runner,
                observed_platform="linux/amd64",
            )
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["canonical_platform"], "linux/amd64")

            with self.assertRaisesRegex(
                verify_idf_environment.IDFEnvironmentError,
                "host platform .* is not accepted",
            ):
                verify_idf_environment.verify_idf_environment(
                    MATRIX_PATH,
                    idf_path=idf_path,
                    idf_py=idf_py,
                    runner=runner,
                    observed_platform="darwin/arm64",
                )

            hardware_report = verify_idf_environment.verify_idf_environment(
                MATRIX_PATH,
                idf_path=idf_path,
                idf_py=idf_py,
                runner=runner,
                observed_platform="darwin/arm64",
                allowed_platforms=(
                    "linux/amd64",
                    "darwin/amd64",
                    "darwin/arm64",
                ),
            )
            self.assertEqual(hardware_report["platform"], "darwin/arm64")
            self.assertEqual(hardware_report["canonical_platform"], "linux/amd64")

            def wrong_version(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                if command[-1] == "--version":
                    return subprocess.CompletedProcess(command, 0, "ESP-IDF v5.4.5\n", "")
                return runner(command, **kwargs)

            with self.assertRaisesRegex(verify_idf_environment.IDFEnvironmentError, "does not match lane"):
                verify_idf_environment.verify_idf_environment(
                    MATRIX_PATH,
                    idf_path=idf_path,
                    idf_py=idf_py,
                    runner=wrong_version,
                    observed_platform="linux/amd64",
                )

            def wrong_commit(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
                if command[-1] == "--version":
                    return subprocess.CompletedProcess(command, 0, "ESP-IDF v5.4.4\n", "")
                return subprocess.CompletedProcess(command, 0, "0" * 40 + "\n", "")

            with self.assertRaisesRegex(verify_idf_environment.IDFEnvironmentError, "commit .* does not match"):
                verify_idf_environment.verify_idf_environment(
                    MATRIX_PATH,
                    idf_path=idf_path,
                    idf_py=idf_py,
                    runner=wrong_commit,
                    observed_platform="linux/amd64",
                )

    def test_lock_resolution_is_isolated_and_update_is_explicit_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            firmware = Path(temp_dir) / "firmware"
            shutil.copytree(ROOT / "firmware", firmware)
            matrix_path = firmware / "idf-family-matrix.json"
            selected_lock = firmware / "locks/idf-5.4.4/esp32c3/dependencies.lock"
            canonical = selected_lock.read_bytes()
            selected_lock.write_bytes(canonical + b"\n")

            environment = {
                "idf_py": "/pinned/idf/tools/idf.py",
                "idf_path": "/pinned/idf",
            }

            def configure(_command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                cwd = Path(str(kwargs["cwd"]))
                target = dict(kwargs["env"])["IDF_TARGET"]  # type: ignore[arg-type]
                source = ROOT / f"firmware/locks/idf-5.4.4/{target}/dependencies.lock"
                (cwd / "dependencies.lock").write_bytes(source.read_bytes())
                return subprocess.CompletedProcess(_command, 0, "configured\n", "")

            with mock.patch.object(
                build_idf_cell.verify_idf_environment,
                "verify_idf_environment",
                return_value=environment,
            ), mock.patch.object(build_idf_cell.subprocess, "run", side_effect=configure):
                with self.assertRaisesRegex(build_idf_cell.CellLockError, "would mutate"):
                    build_idf_cell.configure_lock(
                        matrix_path=matrix_path,
                        cell_id="esp32c3-compile",
                        update_lock=False,
                    )
                self.assertEqual(selected_lock.read_bytes(), canonical + b"\n")

                updated = build_idf_cell.configure_lock(
                    matrix_path=matrix_path,
                    cell_id="esp32c3-compile",
                    update_lock=True,
                )
                self.assertTrue(updated["changed"])
                self.assertEqual(selected_lock.read_bytes(), canonical)

                repeated = build_idf_cell.configure_lock(
                    matrix_path=matrix_path,
                    cell_id="esp32c3-compile",
                    update_lock=True,
                )
                self.assertFalse(repeated["changed"])

    def test_if3_scripts_remove_moving_idf_and_source_tree_builds(self) -> None:
        bootstrap = (ROOT / "tools/bootstrap_idf.sh").read_text(encoding="utf-8")
        self.assertNotIn("release/v5.4", bootstrap)
        self.assertIn("verify_idf_environment.py", bootstrap)
        self.assertIn("esp32\", \"esp32s3\", \"esp32c3\", \"esp32c6", bootstrap)
        legacy_build = (ROOT / "tools/build_firmware.sh").read_text(encoding="utf-8")
        self.assertNotIn("idf.py set-target", legacy_build)
        self.assertNotIn("idf.py build", legacy_build)
        self.assertIn("build_idf_cell.py", legacy_build)
        self.assertIn('--out-dir "$OUT_DIR"', legacy_build)
        self.assertNotIn("exit 78", legacy_build)

    def test_wamr_manifest_uses_an_exact_version(self) -> None:
        manifest = (ROOT / "firmware/components/wdc_runtime/idf_component.yml").read_text(encoding="utf-8")
        self.assertIn('version: "2.4.0~1"', manifest)
        self.assertNotIn('"^2.4.0~1"', manifest)
        self.assertEqual(self.matrix["lanes"]["idf-5.4.4"]["wamr_version"], "2.4.0~1")

    def test_adr_freezes_required_boundaries(self) -> None:
        adr = (ROOT / "docs/adr/0009-idf-family-build-matrix.md").read_text(encoding="utf-8")
        for required in [
            "Lane and realization are separate axes",
            "locks are stored per lane and target",
            "isolated temporary project copies",
            "ESP32-S3 is the only required/reference realization",
            "Build mapping is not runtime qualification",
            "Pulse host capability ABIs",
            "ESP32 provider",
        ]:
            self.assertIn(required, adr)

    def test_unknown_fields_fail_closed(self) -> None:
        matrix = copy.deepcopy(self.matrix)
        matrix["surprise"] = True
        proc = self.run_checker(matrix)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("unknown fields: surprise", proc.stdout)

    def test_duplicate_realization_id_in_json_fails_closed(self) -> None:
        raw = MATRIX_PATH.read_text(encoding="utf-8")
        start = raw.index('    "esp32-compile": {')
        end = raw.index('    "esp32c3-compile": {')
        duplicate_block = raw[start:end]
        proc = self.run_checker_text(raw[:end] + duplicate_block + raw[end:])
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("duplicate key 'esp32-compile'", proc.stdout)

    def test_missing_lane_reference_fails_closed(self) -> None:
        matrix = copy.deepcopy(self.matrix)
        matrix["realizations"]["esp32-compile"]["lane"] = "idf-missing"
        proc = self.run_checker(matrix)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("references missing lane 'idf-missing'", proc.stdout)

    def test_all_firmware_paths_reject_escape(self) -> None:
        mutations = {
            "defaults": lambda entry: entry.__setitem__("defaults", ["sdkconfig.defaults", "../escape.defaults"]),
            "partitions": lambda entry: entry.__setitem__("partitions", "../partitions.csv"),
            "dependency_lock": lambda entry: entry.__setitem__("dependency_lock", "../dependencies.lock"),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                matrix = copy.deepcopy(self.matrix)
                mutate(matrix["realizations"]["esp32-compile"])
                proc = self.run_checker(matrix)
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn("normalized relative path inside firmware", proc.stdout)

    def test_unsupported_intent_and_result_vocabularies_fail_closed(self) -> None:
        matrix = copy.deepcopy(self.matrix)
        matrix["realizations"]["esp32-compile"]["intent"] = "optional"
        proc = self.run_checker(matrix)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("unsupported intent 'optional'", proc.stdout)
        with self.assertRaisesRegex(check_idf_matrix.MatrixContractError, "unsupported build result"):
            check_idf_matrix.validate_result_name("SKIPPED_ENV")
        self.assertEqual(
            check_idf_matrix.validate_result_name("COMPILE_PROVEN"),
            "COMPILE_PROVEN",
        )

    def test_missing_reason_fails_closed(self) -> None:
        matrix = copy.deepcopy(self.matrix)
        del matrix["excluded"][0]["reason"]
        proc = self.run_checker(matrix)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("missing fields: reason", proc.stdout)

    def test_required_cell_needs_two_reproducibility_runs(self) -> None:
        matrix = copy.deepcopy(self.matrix)
        matrix["realizations"]["esp32s3-reference"]["reproducibility_runs"] = 1
        proc = self.run_checker(matrix)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("requires at least two reproducibility runs", proc.stdout)

    def test_missing_inventory_row_fails_closed(self) -> None:
        matrix = copy.deepcopy(self.matrix)
        del matrix["realizations"]["esp32c6-compile"]
        proc = self.run_checker(matrix)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("missing inventory IDs: esp32c6-compile", proc.stdout)


if __name__ == "__main__":
    unittest.main()
