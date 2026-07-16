from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"


class R35DependencyGateTests(unittest.TestCase):
    def test_r35_tooling_files_exist_and_are_executable(self) -> None:
        for rel in [
            "tools/check_deps.py",
            "tools/bootstrap_deps.sh",
            "tools/bootstrap_rust.sh",
            "tools/bootstrap_idf.sh",
            "tools/build_guest_wasm.sh",
            "tools/build_firmware.sh",
            "tools/check_r3_5.py",
            "tools/test_full.sh",
            "tools/test_full.py",
            "tools/wasm_inspect.py",
        ]:
            path = ROOT / rel
            self.assertTrue(path.exists(), rel)
            self.assertTrue(path.stat().st_mode & 0o111, f"{rel} should be executable")

    def test_makefile_exposes_r35_targets(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        for target in [
            "check-r3_5:",
            "check-r3.5:",
            "deps-check:",
            "deps-host:",
            "deps-rust:",
            "deps-idf:",
            "build-guest:",
            "build-firmware:",
            "check-full:",
        ]:
            self.assertIn(target, makefile)

    def test_dependency_check_json_schema(self) -> None:
        proc = subprocess.run([sys.executable, "-B", str(TOOLS / "check_deps.py")], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        report = json.loads(proc.stdout)
        self.assertEqual(report["schema"], "wdc.r3_5.dependency_report.v1")
        commands = report["commands"]
        for required in ["python3", "gcc", "make", "cmake", "ninja", "git", "cargo", "rustc", "idf.py"]:
            self.assertIn(required, commands)
            self.assertIn("present", commands[required])
        self.assertIn("rust", report)
        self.assertEqual(report["rust"]["target"], "wasm32-unknown-unknown")
        self.assertIn("esp_idf", report)

    def test_wasm_inspector_accepts_r2_fixture(self) -> None:
        fixture = ROOT / "firmware/components/wdc_runtime/test_vectors/wdc_static_hello_wasm.wasm"
        proc = subprocess.run(
            [
                sys.executable,
                "-B",
                str(TOOLS / "wasm_inspect.py"),
                str(fixture),
                "--json",
                "--require-import",
                "wdc:wdc_log",
                "--require-export",
                "wdc_module_init",
                "--require-export",
                "wdc_module_on_event",
                "--require-export",
                "wdc_module_health",
                "--require-export",
                "wdc_module_shutdown",
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout)
        summary = json.loads(proc.stdout)
        self.assertEqual(summary["schema"], "wdc.wasm_inspect.v1")
        self.assertTrue(any(i["module"] == "wdc" and i["name"] == "wdc_log" for i in summary["imports"]))
        exports = {item["name"] for item in summary["exports"]}
        self.assertIn("wdc_module_init", exports)

    def test_wasm_inspector_rejects_missing_lifecycle_export(self) -> None:
        fixture = ROOT / "firmware/components/wdc_runtime/test_vectors/wdc_static_missing_shutdown_wasm.wasm"
        proc = subprocess.run(
            [
                sys.executable,
                "-B",
                str(TOOLS / "wasm_inspect.py"),
                str(fixture),
                "--json",
                "--require-export",
                "wdc_module_shutdown",
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("MISSING: export wdc_module_shutdown", proc.stdout)

    def test_full_report_dry_run_writes_json_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp) / "reports"
            proc = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(TOOLS / "check_r3_5.py"),
                    "--skip-idf-build",
                    "--json-out",
                    str(report_dir / "r3_5_test_report.json"),
                    "--md-out",
                    str(report_dir / "r3_5_test_report.md"),
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout)
            json_path = report_dir / "r3_5_test_report.json"
            md_path = report_dir / "r3_5_test_report.md"
            self.assertTrue(json_path.exists())
            self.assertTrue(md_path.exists())
            report = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(report["schema"], "wdc.r3_5.full_verification_report.v1")
            names = {gate["name"] for gate in report["gates"]}
            self.assertIn("python_contract_tests", names)
            self.assertIn("hardware_flash_smoke", names)
            self.assertTrue(all(gate["status"] in {"PASS", "FAIL", "SKIPPED_ENV", "SKIPPED_NETWORK", "SKIPPED_NO_HARDWARE"} for gate in report["gates"]))


if __name__ == "__main__":
    unittest.main()
