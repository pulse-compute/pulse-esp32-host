from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools import qualify_host_kernel


ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "specs/PULSE-ESP32-006-host-kernel-resource-authority.json"
EXPECTED_CASES = {
    "fixed-priority-and-reserve-authority",
    "isr-fixed-capture-notification",
    "priority-preemption-under-application-pressure",
    "terminal-completion-exactly-once",
    "per-class-capacity-reservation",
    "c6-portable-admission",
    "admission-denials-fail-closed",
    "s3-psram-explicit-nonportable",
    "synthetic-pressure-no-retention",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class HP1HostKernelResourceAuthorityTests(unittest.TestCase):
    def test_control_kernel_executes_exact_synthetic_seal(self) -> None:
        compiler = shutil.which("cc")
        self.assertIsNotNone(compiler, "host C compiler is required for HP1")
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "hp1-control-kernel-smoke"
            build = subprocess.run(
                qualify_host_kernel._compile_command(compiler, executable),
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
            smoke = json.loads(run.stdout)
        qualify_host_kernel._validate_smoke(smoke)
        self.assertEqual(
            {item["name"] for item in smoke["cases"]}, EXPECTED_CASES
        )
        self.assertEqual(smoke["pressure"]["accepted"], 320)
        self.assertEqual(smoke["pressure"]["terminal"], 320)
        self.assertEqual(smoke["pressure"]["retained"], 0)

    def test_model_freezes_priority_queue_and_reserve_authority(self) -> None:
        model = qualify_host_kernel._load_model()
        priorities = model["priority_classes"]
        self.assertEqual(
            [(item["class"], item["freertos_priority"]) for item in priorities],
            [
                ("SAFETY_RECOVERY", 13),
                ("ADMINISTRATION", 11),
                ("NETWORK", 9),
                ("CAPABILITY", 7),
                ("APPLICATION", 5),
            ],
        )
        self.assertTrue(model["queue_contract"]["application_cannot_select_class_or_priority"])
        self.assertEqual(
            model["queue_contract"]["overflow_terminal_disposition"],
            "REJECTED_OVERFLOW",
        )
        c6 = model["profiles"]["c6_minimum"]
        self.assertFalse(c6["psram_supported"])
        self.assertEqual(c6["fixed_control_reserve_bytes"], 98304)
        self.assertEqual(c6["exclusive_update_working_bytes"], 65536)
        self.assertEqual(c6["largest_block_floor_bytes"], 32768)
        self.assertEqual(c6["maximum_application_internal_bytes"], 131072)

    def test_isr_path_is_fixed_notification_only(self) -> None:
        core = (
            ROOT / "firmware/components/wdc_control/wdc_control.c"
        ).read_text(encoding="utf-8")
        platform = (
            ROOT / "firmware/components/wdc_control/wdc_control_platform_espidf.c"
        ).read_text(encoding="utf-8")
        isr = core.split("wdc_control_capture_isr(", 1)[1].split(
            "int32_t wdc_control_take_isr_capture", 1
        )[0]
        adapter = platform.split("wdc_control_platform_capture_from_isr(", 1)[1].split(
            "int32_t wdc_control_platform_heap_snapshot", 1
        )[0]
        self.assertIn("__atomic_store_n", isr)
        self.assertIn("recovery_required", isr)
        self.assertNotIn("memcpy", isr)
        self.assertIn("vTaskNotifyGiveFromISR", adapter)
        for forbidden in (
            "malloc",
            "calloc",
            "realloc",
            "printf",
            "ESP_LOG",
            "wdc_runtime",
            "wdc_extension",
            "wdc_host_call",
        ):
            self.assertNotIn(forbidden, isr)
            self.assertNotIn(forbidden, adapter)

    def test_application_request_has_no_priority_or_allocation_escape(self) -> None:
        header = (
            ROOT / "firmware/components/wdc_control/include/wdc_control.h"
        ).read_text(encoding="utf-8")
        implementation = (
            ROOT / "firmware/components/wdc_control/wdc_control.c"
        ).read_text(encoding="utf-8")
        work_request = header.split("typedef struct WdcControlWorkRequest", 1)[1].split(
            "} WdcControlWorkRequest;", 1
        )[0]
        self.assertNotIn("priority", work_request.lower())
        self.assertNotIn("alloc", work_request.lower())
        self.assertIn("wdc_control_priority_class_for_source", implementation)
        self.assertIn("requested_task_priority != 0u", implementation)
        self.assertIn("requests_unbounded_allocation", implementation)
        for forbidden in ("malloc(", "calloc(", "realloc(", "free("):
            self.assertNotIn(forbidden, implementation)

    def test_admission_checks_all_three_phases_and_largest_block(self) -> None:
        source = (
            ROOT / "firmware/components/wdc_control/wdc_control.c"
        ).read_text(encoding="utf-8")
        admission = source.split("static int admission_arithmetic", 1)[1]
        for token in (
            "normal_required_bytes",
            "transition_required_bytes",
            "exclusive_update_required_bytes",
            "required_internal_free_bytes",
            "required_largest_block_bytes",
            "update_largest_allocation_bytes",
            "largest_block_floor_bytes",
            "checked_add",
        ):
            self.assertIn(token, admission)
        model = json.loads(MODEL.read_text(encoding="utf-8"))
        evidence = model["sizing_evidence"]
        self.assertEqual(evidence["c6_hx5b_minimum_internal_free_bytes"], 255032)
        self.assertEqual(
            evidence["c6_hx5b_minimum_internal_largest_block_bytes"], 221184
        )
        self.assertEqual(evidence["c6_psram_bytes"], 0)

    def test_qualifier_is_manifested_and_does_not_claim_hardware(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "hp1"
            report = qualify_host_kernel.qualify(output)
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["pass"], "HP1")
            self.assertEqual(report["phase"], "HOST_KERNEL_RESOURCE_AUTHORITY")
            self.assertEqual(report["aggregate"], "HOST_RESOURCE_AUTHORITY_PROVEN")
            self.assertEqual(
                report["claim_boundary"]["hardware_execution_this_pass"],
                "NOT_RUN",
            )
            self.assertEqual(
                report["claim_boundary"]["retained_hp0_evidence_use"],
                "SIZING_INPUT_ONLY",
            )
            for artifact in report["evidence"].values():
                path = output / artifact["path"]
                self.assertTrue(path.is_file())
                self.assertEqual(digest(path), artifact["sha256"])
            self.assertTrue((output / "qualification-report.json").is_file())
            self.assertTrue((output / "qualification-report.md").is_file())

    def test_hp1_preserves_hx5b_and_public_extension_identities(self) -> None:
        model = json.loads(MODEL.read_text(encoding="utf-8"))
        authority = model["authority"]
        self.assertEqual(
            digest(ROOT / "native-sdk/c/include/pulse_extension.h"),
            authority["native_extension_abi_sha256"],
        )
        self.assertEqual(
            digest(
                ROOT
                / "firmware/components/wdc_runtime/test_vectors/"
                "wdc_hx4_event_effect_wasm.wasm"
            ),
            authority["common_wasm_sha256"],
        )
        self.assertEqual(
            digest(ROOT / "specs/PULSE-ESP32-005b-extension-pressure-seal.json"),
            authority["hx5b_pressure_model_sha256"],
        )
        main = (ROOT / "firmware/main/app_main.c").read_text(encoding="utf-8")
        cmake = (ROOT / "firmware/main/CMakeLists.txt").read_text(encoding="utf-8")
        self.assertIn("wdc_control_link_anchor", main)
        self.assertIn("wdc_control", cmake)

    def test_make_runner_and_docs_expose_hp1_scope(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        runner = (ROOT / "tools/run_contract_tests.py").read_text(encoding="utf-8")
        docs = (ROOT / "docs/HP1_HOST_KERNEL_RESOURCE_AUTHORITY.md").read_text(
            encoding="utf-8"
        )
        normalized_docs = " ".join(docs.split())
        self.assertIn("check-hp1", makefile)
        self.assertIn("host-kernel-qualify", makefile)
        self.assertIn("tests.contract.test_hp1_host_kernel_resource_authority", runner)
        self.assertIn("No application-facing record contains an RTOS priority", normalized_docs)
        self.assertIn("does not make a new physical result", normalized_docs)
        for forbidden in ("MQTT implementation", "RAX packaging"):
            self.assertNotIn(forbidden, docs)


if __name__ == "__main__":
    unittest.main()
