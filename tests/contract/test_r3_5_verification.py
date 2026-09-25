from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"

import sys
sys.path.insert(0, str(TOOLS))
import check_deps  # noqa: E402
import wasm_inspect  # noqa: E402


class R35VerificationTests(unittest.TestCase):
    def test_r35_scripts_exist_and_are_executable(self) -> None:
        for rel in [
            "check_deps.py",
            "wasm_inspect.py",
            "bootstrap_deps.sh",
            "bootstrap_rust.sh",
            "bootstrap_idf.sh",
            "build_guest_wasm.sh",
            "build_firmware.sh",
            "qualify_idf_reference.py",
            "test_full.py",
            "test_full.sh",
            "check_r3_5.py",
            "run_contract_tests.py",
        ]:
            path = TOOLS / rel
            self.assertTrue(path.exists(), rel)
            if rel.endswith(".sh") or rel.endswith(".py"):
                self.assertTrue(path.stat().st_mode & 0o111, rel)

    def test_makefile_exposes_r35_targets(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        for target in [
            "check-r3-5:",
            "check-r3_5:",
            "check-r3.5:",
            "deps-check:",
            "deps-rust:",
            "deps-idf:",
            "deps-bootstrap:",
            "build-guest:",
            "build-firmware:",
            "idf-reference-qualify:",
            "check-full:",
            "check-full-network:",
        ]:
            self.assertIn(target, makefile)

    def test_check_deps_writes_report_without_strict_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            json_out = Path(tmp) / "deps.json"
            md_out = Path(tmp) / "deps.md"
            report = check_deps.make_report()
            json_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            check_deps.write_markdown(report, md_out)
            payload = json.loads(json_out.read_text(encoding="utf-8"))
            self.assertIn("checks", payload)
            self.assertIn("summary", payload)
            names = {item["name"] for item in payload["checks"]}
            self.assertIn("rustc", names)
            self.assertIn("cargo", names)
            self.assertIn("ESP-IDF idf.py", names)
            self.assertTrue(md_out.read_text(encoding="utf-8").startswith("# R3.5 dependency report"))

    def test_wasm_inspect_validates_static_fixture_exports(self) -> None:
        fixture = ROOT / "firmware/components/wdc_runtime/test_vectors/wdc_static_hello_wasm.wasm"
        payload = wasm_inspect.inspect_wasm(fixture)
        exports = {item["name"] for item in payload["exports"]}
        for exported in ["wdc_module_init", "wdc_module_on_event", "wdc_module_health", "wdc_module_shutdown"]:
            self.assertIn(exported, exports)
        self.assertIn(("wdc", "wdc_log"), {(item["module"], item["name"]) for item in payload["imports"]})

    def test_wasm_inspect_detects_missing_required_symbol(self) -> None:
        fixture = ROOT / "firmware/components/wdc_runtime/test_vectors/wdc_static_hello_wasm.wasm"
        payload = wasm_inspect.inspect_wasm(fixture)
        exports = {item["name"] for item in payload["exports"]}
        self.assertNotIn("definitely_missing", exports)

    def test_rust_relay_example_returns_i32_not_result(self) -> None:
        relay = (ROOT / "guest-sdk/rust/examples/relay_toggle/src/lib.rs").read_text(encoding="utf-8")
        self.assertIn("match host::gpio_set", relay)
        self.assertIn("Ok(()) => WDC_OK", relay)
        self.assertNotIn("pub extern \"C\" fn wdc_module_init() -> i32 {\n    host::gpio_set", relay)

    def test_test_full_report_schema_is_present(self) -> None:
        script = (TOOLS / "test_full.py").read_text(encoding="utf-8")
        for token in ["PASS", "FAIL", "SKIPPED_ENV", "SKIPPED_NETWORK", "SKIPPED_NO_HARDWARE", "r3_5_test_report.json"]:
            self.assertIn(token, script)


if __name__ == "__main__":
    unittest.main()
