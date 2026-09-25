from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools import build_native_extension

ROOT = Path(__file__).resolve().parents[2]


class HX3ExtensionLifecycleTests(unittest.TestCase):
    def test_required_lifecycle_cases_execute_in_native_host_smoke(self) -> None:
        compiler = shutil.which("cc")
        self.assertIsNotNone(compiler, "host C compiler is required for HX3 lifecycle smoke")
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "hx3-lifecycle-smoke"
            command = [
                compiler,
                "-std=c11",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-DPULSE_EXTENSION_HOST_TEST",
                "-Inative-sdk/c/include",
                "-Ifirmware/components/wdc_extension/include",
                "-Ifirmware/components/wdc_extension",
                "-Ifirmware/components/wdc_elf/include",
                "tests/contract/hx3_lifecycle_smoke.c",
                "firmware/components/wdc_extension/wdc_extension_lifecycle.c",
                "-o",
                str(executable),
            ]
            build = subprocess.run(
                command,
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(build.returncode, 0, build.stdout)
            run = subprocess.run(
                [str(executable)],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(run.returncode, 0, run.stdout)
            report = json.loads(run.stdout)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["case_count"], 12)
        self.assertTrue(all(item["status"] == "PASS" for item in report["cases"]))
        self.assertEqual(report["reverse_unwind"], {"init": True, "start": True})
        self.assertEqual(report["repeated_cycles"], 32)
        self.assertEqual(report["repeated_cycle_retained_bytes"], 0)
        names = {item["name"] for item in report["cases"]}
        self.assertTrue(
            {
                "happy-lifecycle",
                "init-failure-reverse-unwind",
                "start-failure-before-task",
                "start-failure-after-partial-task",
                "unhealthy-probation",
                "duplicate-start",
                "invoke-before-start",
                "invoke-after-quiesce",
                "quiescence-timeout-reset",
                "duplicate-deinit",
                "expired-quiesce-deadline",
                "repeated-lifecycle-cycles",
            }.issubset(names)
        )
        self.assertEqual(report["simulated_reset_count"], 3)

    def test_host_owns_exact_state_machine_and_reset_latch(self) -> None:
        header = (ROOT / "firmware/components/wdc_extension/include/wdc_extension.h").read_text(
            encoding="utf-8"
        )
        source = (ROOT / "firmware/components/wdc_extension/wdc_extension_lifecycle.c").read_text(
            encoding="utf-8"
        )
        for state in (
            "WDC_EXTENSION_INITIALIZING",
            "WDC_EXTENSION_INITIALIZED",
            "WDC_EXTENSION_STARTING",
            "WDC_EXTENSION_STARTED",
            "WDC_EXTENSION_QUIESCING",
            "WDC_EXTENSION_QUIESCED",
            "WDC_EXTENSION_DEINITIALIZED",
            "WDC_EXTENSION_RESET_REQUIRED",
        ):
            self.assertIn(state, header)
        for api in (
            "wdc_extension_registry_initialize",
            "wdc_extension_registry_start",
            "wdc_extension_candidate_invoke",
            "wdc_extension_candidate_health",
            "wdc_extension_registry_quiesce",
            "wdc_extension_registry_deinitialize",
            "wdc_extension_registry_unload_clean",
            "wdc_extension_registry_requires_reset",
        ):
            self.assertIn(api, header)
        self.assertIn("WDC_EXTENSION_FAILURE_QUIESCE_MS 1000u", source)
        self.assertIn("candidate->start_entered = 1u", source)
        self.assertIn("candidate->reset_required = 1u", source)
        self.assertIn("quiesce_deadline_valid", source)
        self.assertNotIn("vTaskDelete", source)
        self.assertNotIn("xTaskCreate", source)

    def test_partial_failures_unwind_in_reverse_and_never_force_delete(self) -> None:
        source = (ROOT / "firmware/components/wdc_extension/wdc_extension_lifecycle.c").read_text(
            encoding="utf-8"
        )
        self.assertGreaterEqual(source.count("while (index != 0u)"), 3)
        self.assertIn("deinitialize_reverse", source)
        self.assertIn("unwind_after_start", source)
        self.assertIn("quiesce_candidate(candidate, &request)", source)
        self.assertIn("WDC_EXTENSION_ERR_RESET_REQUIRED", source)
        self.assertNotRegex(source, r"\b(?:free|malloc|calloc|realloc)\s*\(")

    def test_synthetic_extension_owns_one_static_task_and_queue(self) -> None:
        source = (ROOT / "native-extensions/synthetic-loopback/extension.c").read_text(
            encoding="utf-8"
        )
        start = source.split("static int32_t synthetic_start", 1)[1].split(
            "static int32_t synthetic_invoke", 1
        )[0]
        init = source.split("static int32_t synthetic_init", 1)[1].split(
            "static int32_t synthetic_start", 1
        )[0]
        self.assertIn("xQueueGenericCreateStatic", start)
        self.assertIn("xTaskCreateStatic", start)
        self.assertNotIn("xQueueGenericCreateStatic", init)
        self.assertNotIn("xTaskCreateStatic", init)
        self.assertIn("s_quiesce_requested = 1u", source)
        self.assertIn("vTaskDelete(0)", source)
        self.assertIn("vTaskSetThreadLocalStoragePointerAndDelCallback", start)
        self.assertIn("synthetic_task_deleted", source)
        self.assertNotIn("s_task_exited = 1u;\n    s_task = 0;\n    vTaskDelete(0)", source)
        self.assertIn("vQueueDelete(s_queue)", source)
        self.assertIn("pulse_host_report_health_v1", source)
        self.assertIn("PULSE_SYNTHETIC_TASK_STACK_BYTES 4096u", source)
        self.assertIn("PULSE_SYNTHETIC_QUEUE_DEPTH 4u", source)
        for token in ("malloc(", "calloc(", "realloc(", "free("):
            self.assertNotIn(token, source)
        self.assertNotRegex(source, r"\b(?:gpio|wifi|mqtt|http|ble|lora|rax|nvs)_")

    def test_direct_import_table_is_exact_and_platform_private(self) -> None:
        platform_source = (
            ROOT / "firmware/components/wdc_extension/wdc_extension_platform_espidf.c"
        ).read_text(encoding="utf-8")
        synthetic = (ROOT / "native-extensions/synthetic-loopback/extension.c").read_text(
            encoding="utf-8"
        )
        for name in build_native_extension.SYNTHETIC_ALLOWED_IMPORTS:
            self.assertIn(f'"{name}"', platform_source)
            self.assertRegex(synthetic, rf"\b{name}\s*\(")
        self.assertIn("sizeof(StaticTask_t)", platform_source)
        self.assertIn("sizeof(StaticQueue_t)", platform_source)
        self.assertIn("sizeof(StackType_t) == 1u", platform_source)
        self.assertNotIn("freertos", (ROOT / "native-sdk/c/include/pulse_extension.h").read_text())

    def test_host_services_are_caller_bounded_and_only_hx4_services_open(self) -> None:
        source = (
            ROOT / "firmware/components/wdc_extension/wdc_extension_host_services.c"
        ).read_text(encoding="utf-8")
        self.assertIn("__builtin_return_address(0)", source)
        self.assertIn("candidate->memory.executable_address", source)
        self.assertIn("candidate->memory.writable_address", source)
        self.assertIn("wdc_extension_record_service_health", source)
        self.assertIn("wdc_extension_record_service_fault", source)
        for function in ("pulse_host_emit_event_v1", "pulse_host_complete_effect_v1"):
            body = source.split(f"int32_t {function}", 1)[1].split("}", 1)[0]
            self.assertNotIn("PULSE_EXT_ERR_UNSUPPORTED", body)
        log_body = source.split("int32_t pulse_host_log_v1", 1)[1].split("}", 1)[0]
        self.assertIn("PULSE_EXT_ERR_UNSUPPORTED", log_body)

    def test_inspector_enforces_declared_writable_backing(self) -> None:
        source = (ROOT / "tools/inspect_native_extension.py").read_text(encoding="utf-8")
        builder = (ROOT / "tools/build_native_extension.py").read_text(encoding="utf-8")
        self.assertIn("allocated writable ELF sections exceed declared", source)
        self.assertIn('"resource_footprint"', source)
        self.assertIn("SYNTHETIC_ALLOWED_IMPORTS", builder)
        self.assertIn('"-Wl,--allow-shlib-undefined"', builder)
        self.assertNotIn('"-Wl,--no-undefined"', builder)

    def test_hx2_pre_execution_boundary_remains_call_free(self) -> None:
        source = (ROOT / "firmware/components/wdc_extension/wdc_extension.c").read_text(
            encoding="utf-8"
        )
        stage_one = source.split("int32_t wdc_extension_inspect", 1)[1].split(
            "static int memory_contains", 1
        )[0]
        self.assertNotIn("wdc_elf_", stage_one)
        for lifecycle in ("init_fn", "start_fn", "invoke_fn", "health_fn", "quiesce_fn", "deinit_fn"):
            self.assertIsNone(re.search(rf"->{lifecycle}\s*\(", stage_one))

    def test_firmware_links_lifecycle_platform_and_service_units(self) -> None:
        cmake = (ROOT / "firmware/components/wdc_extension/CMakeLists.txt").read_text(
            encoding="utf-8"
        )
        for source in (
            "wdc_extension_lifecycle.c",
            "wdc_extension_host_services.c",
            "wdc_extension_platform_espidf.c",
        ):
            self.assertIn(source, cmake)
        self.assertIn("REQUIRES esp_timer freertos wdc_elf", cmake)

    def test_make_runner_qualifier_and_docs_expose_hx3(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        runner = (ROOT / "tools/run_contract_tests.py").read_text(encoding="utf-8")
        qualifier = (ROOT / "tools/qualify_extension_runtime.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("check-hx3", makefile)
        self.assertIn("host-extension-runtime-qualify", makefile)
        self.assertIn("tests.contract.test_hx3_extension_lifecycle", runner)
        self.assertIn("BUILD_ONLY_PROVEN", qualifier)
        self.assertIn("HARDWARE_NOT_RUN", qualifier)
        self.assertTrue((ROOT / "docs/HX3_EXTENSION_LIFECYCLE.md").is_file())


if __name__ == "__main__":
    unittest.main()
