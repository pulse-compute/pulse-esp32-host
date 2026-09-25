from __future__ import annotations

import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FW = ROOT / "firmware"
RT = FW / "components/wdc_runtime"


class R2RuntimeTests(unittest.TestCase):
    def test_r2_runtime_files_exist(self) -> None:
        required = [
            "firmware/components/wdc_runtime/include/wdc_runtime.h",
            "firmware/components/wdc_runtime/include/wdc_static_wasm.h",
            "firmware/components/wdc_runtime/wdc_runtime.c",
            "firmware/components/wdc_runtime/wdc_static_wasm.c",
            "firmware/components/wdc_runtime/CMakeLists.txt",
            "firmware/components/wdc_runtime/idf_component.yml",
            "firmware/components/wdc_runtime/test_vectors/wdc_static_hello_wasm.wasm",
            "firmware/components/wdc_runtime/test_vectors/wdc_static_missing_shutdown_wasm.wasm",
            "firmware/components/wdc_runtime/test_vectors/wdc_static_init_fail_wasm.wasm",
            "firmware/components/wdc_runtime/test_vectors/wdc_static_health_fail_wasm.wasm",
            "firmware/components/wdc_runtime/test_vectors/wdc_static_init_trap_wasm.wasm",
        ]
        for rel in required:
            self.assertTrue((ROOT / rel).exists(), rel)

    def test_r2_wamr_component_dependency_is_declared(self) -> None:
        manifest = (RT / "idf_component.yml").read_text(encoding="utf-8")
        self.assertIn("espressif/wasm-micro-runtime", manifest)
        self.assertIn('version: "2.4.0~1"', manifest)
        self.assertNotIn('"^2.4.0~1"', manifest)

        cmake = (RT / "CMakeLists.txt").read_text(encoding="utf-8")
        self.assertIn("wdc_runtime.c", cmake)
        self.assertIn("wdc_static_wasm.c", cmake)
        self.assertIn("wasm-micro-runtime", cmake)

    def test_r2_runtime_source_has_wamr_lifecycle_calls(self) -> None:
        text = (RT / "wdc_runtime.c").read_text(encoding="utf-8")
        for token in [
            "wasm_runtime_init",
            "wasm_runtime_register_natives",
            "wasm_runtime_load",
            "wasm_runtime_instantiate",
            "wasm_runtime_create_exec_env",
            "wasm_runtime_lookup_function",
            "wasm_runtime_call_wasm",
            "wasm_runtime_destroy_exec_env",
            "wasm_runtime_deinstantiate",
            "wasm_runtime_unload",
            "wasm_runtime_destroy",
        ]:
            self.assertIn(token, text)

    def test_static_hello_wasm_has_magic_and_required_exports(self) -> None:
        data = (RT / "test_vectors/wdc_static_hello_wasm.wasm").read_bytes()
        self.assertEqual(data[:8], b"\x00asm\x01\x00\x00\x00")
        for exported in [
            b"wdc_module_init",
            b"wdc_module_on_event",
            b"wdc_module_health",
            b"wdc_module_shutdown",
        ]:
            self.assertIn(exported, data)
        self.assertIn(b"wdc.r2.host_meta", data)
        self.assertIn(b"r2 hello from static wasm", data)

    def test_current_shell_config_and_main_are_runtime_mode(self) -> None:
        config = (FW / "main/shell_config.h").read_text(encoding="utf-8")
        self.assertIn('WDC_SHELL_VERSION     "0.1.0-r9"', config)
        self.assertIn('WDC_SHELL_BUILD_STAGE "R9"', config)
        self.assertRegex(config, r"#define\s+WDC_NO_BUNDLE_MODE\s+0")
        self.assertRegex(config, r"#define\s+WDC_R4_STATIC_RUNTIME_SMOKE\s+0")

        main = (FW / "main/shell_main.c").read_text(encoding="utf-8")
        self.assertIn("wdc_shell_run_r5_runtime_smoke", main)
        self.assertIn("wdc_runtime_dispatch_event", main)
        self.assertIn("wdc_static_hello_wasm", main)
        self.assertIn("R5 static WASM lifecycle/event smoke", main)

    def test_runtime_host_stub_compiles_and_distinguishes_exit_gate_outcomes(self) -> None:
        if shutil.which("gcc") is None:
            self.skipTest("gcc not available")

        program = textwrap.dedent(
            r'''
            #include <assert.h>
            #include <string.h>
            #include "wdc_abi.h"
            #include "wdc_diag.h"
            #include "wdc_runtime.h"
            #include "wdc_static_wasm.h"

            static void run_ok(void) {
                WdcRuntimeReport report;
                memset(&report, 0, sizeof(report));
                WdcRuntimeConfig cfg = wdc_runtime_default_config();
                int32_t status = wdc_runtime_run_static_smoke(&cfg, wdc_static_hello_wasm, wdc_static_hello_wasm_len, &report);
                assert(status == WDC_OK);
                assert(report.backend == WDC_RUNTIME_BACKEND_HOST_STUB);
                assert(report.runtime_initialized);
                assert(report.module_loaded);
                assert(report.module_instantiated);
                assert(report.exports_resolved);
                assert(report.init_called);
                assert(report.health_called);
                assert(report.shutdown_called);
                assert(report.outcome == WDC_RUNTIME_OUTCOME_OK);
            }

            static void run_missing_export(void) {
                WdcRuntimeReport report;
                memset(&report, 0, sizeof(report));
                int32_t status = wdc_runtime_run_static_smoke(NULL, wdc_static_missing_shutdown_wasm, wdc_static_missing_shutdown_wasm_len, &report);
                assert(status == WDC_ERR_NOT_AVAILABLE);
                assert(report.outcome == WDC_RUNTIME_OUTCOME_EXPORT_MISSING);
                assert(!report.shutdown_called);
            }

            static void run_init_fail(void) {
                WdcRuntimeReport report;
                memset(&report, 0, sizeof(report));
                int32_t status = wdc_runtime_run_static_smoke(NULL, wdc_static_init_fail_wasm, wdc_static_init_fail_wasm_len, &report);
                assert(status == WDC_ERR_CONTRACT_VIOLATION);
                assert(report.outcome == WDC_RUNTIME_OUTCOME_GUEST_NON_OK_STATUS);
                assert(report.init_called);
                assert(!report.health_called);
            }

            static void run_health_fail(void) {
                WdcRuntimeReport report;
                memset(&report, 0, sizeof(report));
                int32_t status = wdc_runtime_run_static_smoke(NULL, wdc_static_health_fail_wasm, wdc_static_health_fail_wasm_len, &report);
                assert(status == WDC_ERR_CONTRACT_VIOLATION);
                assert(report.outcome == WDC_RUNTIME_OUTCOME_GUEST_NON_OK_STATUS);
                assert(report.init_called);
                assert(report.health_called);
                assert(!report.shutdown_called);
            }

            static void run_trap(void) {
                WdcRuntimeReport report;
                memset(&report, 0, sizeof(report));
                int32_t status = wdc_runtime_run_static_smoke(NULL, wdc_static_init_trap_wasm, wdc_static_init_trap_wasm_len, &report);
                assert(status == WDC_ERR_CONTRACT_VIOLATION);
                assert(report.outcome == WDC_RUNTIME_OUTCOME_GUEST_TRAPPED);
                assert(report.init_called);
                assert(!report.health_called);
            }

            static void run_invalid_payload(void) {
                static const unsigned char bad[] = {0, 1, 2, 3, 4};
                WdcRuntimeReport report;
                WdcRuntime runtime;
                memset(&report, 0, sizeof(report));
                assert(wdc_runtime_init(&runtime, NULL) == WDC_OK);
                assert(wdc_runtime_load_static(&runtime, bad, sizeof(bad)) == WDC_ERR_BAD_ENCODING);
                wdc_runtime_copy_report(&runtime, &report);
                assert(report.outcome == WDC_RUNTIME_OUTCOME_INVALID_PAYLOAD);
                wdc_runtime_teardown(&runtime);
            }

            int main(void) {
                assert(wdc_diag_init() == WDC_OK);
                run_ok();
                run_missing_export();
                run_init_fail();
                run_health_fail();
                run_trap();
                run_invalid_payload();
                return 0;
            }
            '''
        )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            test_c = tmp_path / "r2_runtime_smoke.c"
            test_c.write_text(program, encoding="utf-8")
            exe = tmp_path / "r2_runtime_smoke"
            include_args = [
                "-I", str(FW / "components/wdc_abi/include"),
                "-I", str(FW / "components/wdc_diag/include"),
                "-I", str(FW / "components/wdc_events/include"),
                "-I", str(FW / "components/wdc_runtime/include"),
            ]
            sources = [
                FW / "components/wdc_abi/wdc_errors.c",
                FW / "components/wdc_diag/wdc_diag.c",
                FW / "components/wdc_events/wdc_event_queue.c",
                FW / "components/wdc_events/wdc_event_encode.c",
                FW / "components/wdc_abi/wdc_cbor.c",
                FW / "components/wdc_runtime/wdc_runtime.c",
                FW / "components/wdc_runtime/wdc_static_wasm.c",
                test_c,
            ]
            subprocess.run(
                ["gcc", "-std=c11", "-Wall", "-Wextra", "-Werror", *include_args, *map(str, sources), "-o", str(exe)],
                check=True,
            )
            subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    unittest.main()
