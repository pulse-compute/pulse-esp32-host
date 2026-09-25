from __future__ import annotations

import hashlib
import json
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools import build_native_extension, gen_r2_wasm


ROOT = Path(__file__).resolve().parents[2]
WASM = (
    ROOT
    / "firmware/components/wdc_runtime/test_vectors/wdc_hx4_event_effect_wasm.wasm"
)


class HX4ExtensionEventEffectTests(unittest.TestCase):
    def test_native_host_smoke_executes_complete_bounded_round_trip(self) -> None:
        compiler = shutil.which("cc")
        self.assertIsNotNone(compiler, "host C compiler is required for HX4 smoke")
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "hx4-roundtrip-smoke"
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
                "-Ifirmware/components/wdc_runtime/include",
                "-Ifirmware/components/wdc_events/include",
                "-Ifirmware/components/wdc_abi/include",
                "-Ifirmware/components/wdc_diag/include",
                "tests/contract/hx4_roundtrip_smoke.c",
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
        self.assertEqual(report["handler_calls"], 1)
        self.assertEqual(report["invoke_calls"], 1)
        self.assertEqual((report["queue_before"], report["queue_after"]), (1, 0))
        self.assertEqual(report["event_id"], 1)
        self.assertEqual(report["causation_id"], 42)
        self.assertEqual(report["operation_id"], build_native_extension.SYNTHETIC_OPERATION_ID)
        self.assertEqual(report["correlation_id"], 1)
        self.assertEqual(report["deadline_ms"], 2000)
        self.assertEqual(report["effect_payload_len"], 8)
        self.assertEqual(report["completion_payload_len"], 8)
        self.assertEqual(report["encoding"], "cbor")
        self.assertEqual(report["duplicate_completion_status"], -7)

    def test_common_wasm_executes_real_handler_in_node(self) -> None:
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node.js is required for the real Wasm smoke")
        run = subprocess.run(
            [node, "tests/contract/hx4_wasm_smoke.mjs"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(run.returncode, 0, run.stdout)
        report = json.loads(run.stdout)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["wasm_bytes"], len(WASM.read_bytes()))
        self.assertEqual(report["wasm_sha256"], hashlib.sha256(WASM.read_bytes()).hexdigest())
        self.assertTrue(report["target_neutral"])
        self.assertEqual(
            report["imports"],
            [{"module": "wdc", "name": "wdc_host_call", "kind": "function"}],
        )
        self.assertEqual(report["calls"][0]["opcode"], 0x0801)
        self.assertEqual(report["calls"][0]["operation_id"], 0x4543484F)
        self.assertEqual(report["calls"][0]["payload"], "hx4-echo")
        self.assertTrue(all(value == 0 for value in report["lifecycle"].values()))

    def test_wasm_fixture_is_deterministic_and_has_no_target_selector(self) -> None:
        committed = WASM.read_bytes()
        self.assertEqual(committed, gen_r2_wasm.make_hx4_event_effect_module())
        text = committed.decode("latin1")
        for prohibited in ("esp32s3", "esp32c6", "xtensa", "riscv", "IDF_TARGET"):
            self.assertNotIn(prohibited, text)
        self.assertIn(b"event=test:tick", committed)
        self.assertIn(b"effect=test:echo", committed)

    def test_bridge_reuses_only_existing_event_runtime_and_abi_paths(self) -> None:
        bridge = (
            ROOT / "firmware/components/wdc_extension/wdc_extension_bridge.c"
        ).read_text(encoding="utf-8")
        extension = (
            ROOT / "native-extensions/synthetic-loopback/extension.c"
        ).read_text(encoding="utf-8")
        self.assertIn("wdc_events_next(&bridge->current_event)", bridge)
        self.assertIn("wdc_runtime_dispatch_event", bridge)
        self.assertIn("wdc_host_call_set_effect_hook", bridge)
        self.assertIn("resolve_operation", bridge)
        self.assertIn("registry->sealed", bridge)
        self.assertNotIn("wasm_runtime_", bridge)
        self.assertNotIn("wdc_runtime", extension)
        self.assertNotIn("wasm", extension.lower())

    def test_event_and_completion_services_are_bounded_and_caller_owned(self) -> None:
        services = (
            ROOT / "firmware/components/wdc_extension/wdc_extension_host_services.c"
        ).read_text(encoding="utf-8")
        header = (
            ROOT / "firmware/components/wdc_extension/include/wdc_extension.h"
        ).read_text(encoding="utf-8")
        for token in (
            "__builtin_return_address(0)",
            "candidate->memory.executable_address",
            "candidate->memory.writable_address",
            "candidate->inspection.metadata.max_event_payload_bytes",
            "candidate->inspection.metadata.max_effect_completion_bytes",
            "wdc_events_post(&queued)",
            "WDC_EFFECT_SLOT_ACTIVE",
            "WDC_EFFECT_SLOT_COMPLETED",
            "last_correlation_id",
        ):
            self.assertIn(token, services)
        self.assertIn("WDC_EXTENSION_EFFECT_PAYLOAD_MAX 256u", header)
        self.assertNotRegex(services, r"\b(?:malloc|calloc|realloc|free)\s*\(")

    def test_extension_copies_effect_into_its_static_queue_before_return(self) -> None:
        source = (
            ROOT / "native-extensions/synthetic-loopback/extension.c"
        ).read_text(encoding="utf-8")
        invoke = source.split("static int32_t synthetic_invoke", 1)[1].split(
            "static int32_t synthetic_health", 1
        )[0]
        task = source.split("static void synthetic_task", 1)[1].split(
            "static int32_t synthetic_init", 1
        )[0]
        self.assertLess(invoke.index("item.payload[index]"), invoke.index("xQueueGenericSend"))
        self.assertIn("PULSE_SYNTHETIC_WORK_TICK", task)
        self.assertIn("pulse_host_emit_event_v1", task)
        self.assertIn("PULSE_SYNTHETIC_WORK_ECHO", task)
        self.assertIn("pulse_host_complete_effect_v1", task)
        self.assertIn('"pulse-hx4"', source)
        self.assertNotRegex(source, r"\b(?:malloc|calloc|realloc|free)\s*\(")

    def test_effect_authorization_preserves_fail_closed_dispatch(self) -> None:
        dispatcher = (
            ROOT / "firmware/components/wdc_abi/wdc_host_call.c"
        ).read_text(encoding="utf-8")
        caps = (ROOT / "firmware/components/wdc_caps/wdc_caps.c").read_text(
            encoding="utf-8"
        )
        safety = (ROOT / "firmware/components/wdc_safety/wdc_safety.c").read_text(
            encoding="utf-8"
        )
        self.assertIn("s_authorizer == NULL", dispatcher)
        self.assertIn("WDC_ERR_CAPABILITY_DENIED", dispatcher)
        self.assertNotIn("WDC_OP_EFFECT_INVOKE", dispatcher.split("opcode_safe_without_authorizer", 1)[1].split("}", 1)[0])
        self.assertIn("case WDC_OP_EFFECT_INVOKE:", caps)
        self.assertIn("case WDC_OP_EFFECT_INVOKE:", safety)

    def test_synthetic_metadata_digest_uses_declared_static_memory(self) -> None:
        metadata = build_native_extension._synthetic_metadata("esp32s3")  # noqa: SLF001
        values = struct.unpack(
            "<8sHHIHHIHHHH16sIIHHI4I4I8I32s32s", metadata
        )
        self.assertEqual(values[27], 3072)
        source = (
            ROOT / "native-extensions/synthetic-loopback/extension.c"
        ).read_text(encoding="utf-8")
        self.assertIn("PULSE_SYNTHETIC_STATIC_MEMORY_BYTES 3072u", source)
        builder = (ROOT / "tools/build_native_extension.py").read_text(encoding="utf-8")
        self.assertIn("generated metadata digest does not match", builder)

    def test_make_runner_qualifier_and_docs_expose_hx4(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        runner = (ROOT / "tools/run_contract_tests.py").read_text(encoding="utf-8")
        self.assertIn("check-hx4", makefile)
        self.assertIn("tests.contract.test_hx4_extension_event_effect", makefile)
        self.assertIn("tests.contract.test_hx4_extension_event_effect", runner)
        self.assertIn("qualify_extension_roundtrip.py", makefile)
        self.assertTrue((ROOT / "docs/HX4_EXTENSION_EVENT_EFFECT.md").is_file())


if __name__ == "__main__":
    unittest.main()
