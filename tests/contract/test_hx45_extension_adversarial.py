from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMMON_WASM = (
    ROOT
    / "firmware/components/wdc_runtime/test_vectors/wdc_hx4_event_effect_wasm.wasm"
)
EXPECTED_COMMON_WASM_SHA256 = (
    "ef8b21a4b7a423923c09f5e38fc626ff7d1cda856c4935db7f191695a333e5c4"
)
EXPECTED_CASES = {
    "unknown-event-identity": -6,
    "unknown-operation-identity": -6,
    "event-queue-full": -4,
    "oversized-event-frame": -6,
    "oversized-effect-frame": -4,
    "expired-deadline": -11,
    "completion-after-timeout": -8,
    "duplicate-completion": -7,
    "completion-after-quiescence": -8,
    "wasm-trap-during-event": -15,
    "extension-fault-during-operation": -16,
}


def adversarial_compile_command(compiler: str, executable: Path) -> list[str]:
    return [
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
        "-Ifirmware/components/wdc_runtime/include",
        "-Ifirmware/components/wdc_events/include",
        "-Ifirmware/components/wdc_abi/include",
        "-Ifirmware/components/wdc_diag/include",
        "tests/contract/hx45_adversarial_smoke.c",
        "firmware/components/wdc_extension/wdc_extension_bridge.c",
        "firmware/components/wdc_extension/wdc_extension_host_services.c",
        "firmware/components/wdc_extension/wdc_extension_lifecycle.c",
        "firmware/components/wdc_runtime/wdc_runtime.c",
        "firmware/components/wdc_runtime/wdc_static_wasm.c",
        "firmware/components/wdc_events/wdc_event_queue.c",
        "firmware/components/wdc_events/wdc_event_encode.c",
        "firmware/components/wdc_abi/wdc_cbor.c",
        "firmware/components/wdc_abi/wdc_host_call.c",
        "-o",
        str(executable),
    ]


class HX45ExtensionAdversarialTests(unittest.TestCase):
    def test_native_adversarial_corpus_executes_all_deferred_cases(self) -> None:
        compiler = shutil.which("cc")
        self.assertIsNotNone(compiler, "host C compiler is required for HX4.5 smoke")
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "hx45-adversarial-smoke"
            build = subprocess.run(
                adversarial_compile_command(compiler, executable),
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
        self.assertEqual(report["failures"], 0)
        self.assertEqual(report["case_count"], len(EXPECTED_CASES))
        self.assertEqual(report["queue_capacity"], 16)
        observed = {item["name"]: item for item in report["cases"]}
        self.assertEqual(set(observed), set(EXPECTED_CASES))
        for name, expected in EXPECTED_CASES.items():
            self.assertEqual(observed[name]["status"], "PASS", name)
            self.assertEqual(observed[name]["observed"], expected, name)
            self.assertEqual(observed[name]["expected"], expected, name)

    def test_exact_common_wasm_propagates_rejections_and_real_trap_executes(self) -> None:
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node.js is required for HX4.5 real-Wasm smoke")
        run = subprocess.run(
            [node, "tests/contract/hx45_wasm_adversarial_smoke.mjs"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(run.returncode, 0, run.stdout)
        report = json.loads(run.stdout)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["common_wasm_sha256"], EXPECTED_COMMON_WASM_SHA256)
        self.assertEqual(report["common_wasm_bytes"], 306)
        self.assertTrue(report["target_neutral"])
        self.assertEqual(
            [item["host_status"] for item in report["status_propagations"]],
            [-6, -4, -11, -16, -9],
        )
        self.assertTrue(
            all(
                item["host_status"] == item["guest_status"] and item["calls"] == 1
                for item in report["status_propagations"]
            )
        )
        self.assertTrue(report["event_trap"]["observed"])
        self.assertEqual(report["event_trap"]["error_name"], "RuntimeError")

    def test_common_wasm_identity_is_unchanged_by_the_adversarial_seal(self) -> None:
        self.assertEqual(len(COMMON_WASM.read_bytes()), 306)
        self.assertEqual(
            hashlib.sha256(COMMON_WASM.read_bytes()).hexdigest(),
            EXPECTED_COMMON_WASM_SHA256,
        )

    def test_effect_slot_distinguishes_pending_timeout_and_cancellation(self) -> None:
        services = (
            ROOT / "firmware/components/wdc_extension/wdc_extension_host_services.c"
        ).read_text(encoding="utf-8")
        bridge = (
            ROOT / "firmware/components/wdc_extension/wdc_extension_bridge.c"
        ).read_text(encoding="utf-8")
        header = (
            ROOT / "firmware/components/wdc_extension/include/wdc_extension.h"
        ).read_text(encoding="utf-8")
        self.assertIn("WDC_EXTENSION_ERR_NOT_READY = -18", header)
        self.assertIn("result = WDC_EXTENSION_ERR_NOT_READY", services)
        self.assertIn("WDC_EFFECT_SLOT_TIMED_OUT", services)
        self.assertIn("status != WDC_EXTENSION_ERR_NOT_READY", bridge)
        self.assertIn("wdc_extension_services_release_effect", bridge)

    def test_expired_deadline_is_not_misclassified_as_bad_encoding(self) -> None:
        lifecycle = (
            ROOT / "firmware/components/wdc_extension/wdc_extension_lifecycle.c"
        ).read_text(encoding="utf-8")
        bridge = (
            ROOT / "firmware/components/wdc_extension/wdc_extension_bridge.c"
        ).read_text(encoding="utf-8")
        self.assertIn("return WDC_EXTENSION_ERR_TIMEOUT;", lifecycle)
        self.assertIn(
            "status == WDC_EXTENSION_ERR_TIMEOUT ? WDC_ERR_TIMEOUT : WDC_ERR_IO",
            bridge,
        )

    def test_corpus_uses_existing_queue_runtime_abi_and_registry_only(self) -> None:
        smoke = (ROOT / "tests/contract/hx45_adversarial_smoke.c").read_text(
            encoding="utf-8"
        )
        for token in (
            "pulse_host_emit_event_v1",
            "wdc_events_post",
            "wdc_extension_bridge_process_next",
            "wdc_runtime_get_report",
            "wdc_host_call_dispatch",
            "wdc_extension_registry_quiesce",
            "wdc_extension_registry_requires_reset",
        ):
            self.assertIn(token, smoke)
        self.assertNotIn("wasm_runtime_", smoke)
        self.assertNotRegex(smoke, r"\b(?:malloc|calloc|realloc|free)\s*\(")

    def test_make_runner_qualifier_and_docs_expose_hx45(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        runner = (ROOT / "tools/run_contract_tests.py").read_text(encoding="utf-8")
        self.assertIn("check-hx4-5", makefile)
        self.assertIn("tests.contract.test_hx45_extension_adversarial", makefile)
        self.assertIn("tests.contract.test_hx45_extension_adversarial", runner)
        self.assertIn("qualify_extension_adversarial.py", makefile)
        self.assertTrue(
            (ROOT / "docs/HX4_5_EXTENSION_ADVERSARIAL.md").is_file()
        )


if __name__ == "__main__":
    unittest.main()
