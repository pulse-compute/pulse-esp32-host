from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.contract import test_hx45_c6_xiao_hardware as c6_fixture
from tools import (
    build_hx45_c6_xiao,
    build_hx45_s3_aitrip,
    evaluate_hx45_c6_xiao,
    qualify_extension_pressure,
)


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_WORKLOADS = {
    "queue-saturation-recovery",
    "deadline-late-completion-storm",
    "duplicate-completion-recovery-storm",
    "bounded-latency-distribution",
    "repeated-wasm-trap-recovery",
    "repeated-native-fault-reset-cycles",
    "pressure-reservation-released",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pressure_serial() -> str:
    result: list[str] = []
    pressure_inserted = False
    for line in c6_fixture.passing_serial().splitlines():
        if line.startswith("PULSE_HX45_CYCLE "):
            marker = json.loads(line.split(" ", 1)[1])
            marker.update(
                {"load_ms": 2, "start_ms": 1, "quiesce_ms": 1, "deinit_ms": 0}
            )
            if marker["cycle"] == 1 and not pressure_inserted:
                for name in (
                    "hx5b-queue-saturation",
                    "hx5b-queue-drain-recovery",
                    "hx5b-pressure-roundtrip",
                ):
                    result.append(c6_fixture.case_marker(name, 1))
                result.append(
                    "PULSE_HX45_PRESSURE "
                    + json.dumps(
                        {
                            "status": "PASS",
                            "campaign": "HX5b",
                            "queue_rounds": 8,
                            "accepted_events": 128,
                            "rejected_events": 8,
                            "recovered_rounds": 8,
                            "queue_high_water": 16,
                            "end_pending": 0,
                            "latency_sample_count": 128,
                            "latency_minimum_ms": 0,
                            "latency_p50_ms": 1,
                            "latency_p95_ms": 2,
                            "latency_maximum_ms": 3,
                        }
                    )
                )
                pressure_inserted = True
            line = "PULSE_HX45_CYCLE " + json.dumps(marker)
        result.append(line)
    return "\n".join(result) + "\n"


class HX5bExtensionPressureTests(unittest.TestCase):
    def test_native_pressure_executes_exact_bounded_storms(self) -> None:
        compiler = shutil.which("cc")
        self.assertIsNotNone(compiler, "host C compiler is required for HX5b")
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "hx5b-pressure-smoke"
            build = subprocess.run(
                qualify_extension_pressure._pressure_compile_command(
                    compiler, executable
                ),
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
        qualify_extension_pressure._validate_native(report)
        self.assertEqual(report["queue"]["rounds"], 64)
        self.assertEqual(report["queue"]["high_water"], 16)
        self.assertEqual(report["completions"]["late"], 128)
        self.assertEqual(report["completions"]["duplicates"], 128)
        self.assertEqual(report["native_faults"]["simulated_resets"], 64)
        self.assertEqual(report["memory_pressure"]["retained_bytes"], 0)

    def test_real_wasm_traps_recover_repeatedly_under_reservation(self) -> None:
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node.js is required for HX5b real Wasm")
        run = subprocess.run(
            [node, "tests/contract/hx5b_wasm_pressure_smoke.mjs"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(run.returncode, 0, run.stdout)
        report = json.loads(run.stdout)
        qualify_extension_pressure._validate_wasm(report)
        self.assertEqual(report["traps"], 64)
        self.assertEqual(report["successful_recoveries"], 64)

    def test_unified_report_reexecutes_hx5a_and_never_fakes_hardware(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "hx5b"
            report = qualify_extension_pressure.qualify(out)
            self.assertEqual(report["schema"], "pulse.esp32.host-extension-report.v1")
            self.assertEqual(report["pass"], "HX5b")
            self.assertEqual(report["phase"], "PRESSURE_HOST_SEALED")
            self.assertEqual(report["aggregate"], "HOST_PRESSURE_PROVEN")
            self.assertEqual(report["baseline"]["executed_case_count"], 56)
            self.assertEqual(report["coverage"]["workload_count"], 7)
            self.assertEqual(report["coverage"]["bounded_operation_count"], 1664)
            self.assertEqual(report["coverage"]["retained_bytes"], 0)
            self.assertEqual(report["hardware"]["execution_this_pass"], "NOT_RUN")
            self.assertEqual(report["hardware"]["results"], {})
            self.assertFalse(any(out.rglob("serial.log")))
            for artifact in report["evidence"].values():
                path = out / artifact["path"]
                self.assertTrue(path.is_file())
                self.assertEqual(digest(path), artifact["sha256"])
            self.assertTrue((out / "qualification-report.md").is_file())

    def test_pressure_build_mode_is_opt_in_for_both_named_boards(self) -> None:
        for builder, fixture in (
            (build_hx45_s3_aitrip, build_hx45_s3_aitrip.DEFAULT_SEALED_NATIVE_ELF),
            (build_hx45_c6_xiao, build_hx45_c6_xiao.DEFAULT_SEALED_NATIVE_ELF),
        ):
            with self.subTest(target=builder.__name__), tempfile.TemporaryDirectory() as temporary:
                report = builder.qualify_build(
                    out_dir=Path(temporary) / "run",
                    sealed_native_elf=fixture,
                    prepare_only=True,
                    idf_path=None,
                    idf_py=None,
                    timeout=1,
                    hx5b_pressure=True,
                )
                self.assertEqual(report["status"], "PREPARED")
                self.assertEqual(report["campaign"], "HX5b")
                self.assertEqual(
                    report["pressure_contract"],
                    {
                        "status": "BUILD_CONFIGURED",
                        "queue_rounds": 8,
                        "accepted_events": 128,
                        "queue_capacity": 16,
                        "effect_timeout_ms": 1000,
                        "runtime": "HARDWARE_NOT_RUN",
                    },
                )

    def test_c6_pressure_evaluator_requires_complete_ordered_target_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build_path = c6_fixture.write_build_report(root)
            build = json.loads(build_path.read_text(encoding="utf-8"))
            build["campaign"] = "HX5b"
            build["pressure_contract"] = {
                "status": "BUILD_CONFIGURED",
                "queue_rounds": 8,
                "accepted_events": 128,
                "queue_capacity": 16,
                "effect_timeout_ms": 1000,
                "runtime": "HARDWARE_NOT_RUN",
            }
            build_path.write_text(json.dumps(build), encoding="utf-8")
            serial = root / "serial.log"
            serial.write_text(pressure_serial(), encoding="utf-8")
            report = evaluate_hx45_c6_xiao.evaluate(
                serial_log=serial,
                build_report_path=build_path,
                board_marking="XIAO ESP32C6",
                require_hx5b_pressure=True,
            )
            self.assertEqual(report["status"], "PASS", report["failures"])
            self.assertEqual(report["pressure_seal"]["status"], "PASS")
            self.assertEqual(
                report["pressure_seal"]["marker"]["latency_sample_count"], 128
            )
            evaluation_path = root / "hx5b-evaluation.json"
            evaluation_path.write_text(json.dumps(report), encoding="utf-8")
            ingested = qualify_extension_pressure._load_hardware_evaluation(
                evaluation_path, "esp32c6"
            )
            self.assertEqual(ingested["runtime_result"], "NAMED_BOARD_OBSERVED")
            serial.write_text(pressure_serial() + "tampered\n", encoding="utf-8")
            with self.assertRaises(qualify_extension_pressure.QualificationError):
                qualify_extension_pressure._load_hardware_evaluation(
                    evaluation_path, "esp32c6"
                )

            serial.write_text(
                pressure_serial().replace(
                    '"recovered_rounds": 8', '"recovered_rounds": 7', 1
                ),
                encoding="utf-8",
            )
            failed = evaluate_hx45_c6_xiao.evaluate(
                serial_log=serial,
                build_report_path=build_path,
                board_marking="XIAO ESP32C6",
                require_hx5b_pressure=True,
            )
            self.assertEqual(failed["status"], "FAIL")
            self.assertEqual(failed["pressure_seal"]["status"], "FAIL")

    def test_pressure_marker_uses_uint32_portable_format_macros(self) -> None:
        sources = (
            ROOT
            / "tests/hardware-in-loop/hx45-s3-aitrip-n8r2/main/hx45_s3_aitrip_main.c",
            ROOT
            / "tests/hardware-in-loop/hx45-c6-seeed-xiao-4m/main/hx45_c6_xiao_main.c",
        )
        for source in sources:
            with self.subTest(source=source):
                text = source.read_text(encoding="utf-8")
                start = text.index('printf("PULSE_HX45_PRESSURE ')
                end = text.index("    fflush(stdout);", start)
                marker = text[start:end]
                self.assertIn("#include <inttypes.h>", text)
                self.assertEqual(marker.count("PRIu32"), 11)
                self.assertNotIn('\\":%u', marker)
                self.assertIn("(uint32_t)HX5B_QUEUE_ROUNDS", marker)
                self.assertIn("(uint32_t)wdc_events_pending()", marker)

    def test_model_make_runner_and_docs_freeze_scope(self) -> None:
        model = json.loads(
            (ROOT / "specs/PULSE-ESP32-005b-extension-pressure-seal.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(model["pass"], "HX5b")
        self.assertEqual(
            {item["id"] for item in model["required_workloads"]}, EXPECTED_WORKLOADS
        )
        self.assertEqual(
            {item["target"] for item in model["hardware_campaigns"]},
            {"esp32s3", "esp32c6"},
        )
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        runner = (ROOT / "tools/run_contract_tests.py").read_text(encoding="utf-8")
        docs = (ROOT / "docs/HX5B_EXTENSION_PRESSURE_SEAL.md").read_text(
            encoding="utf-8"
        )
        for token in (
            "check-hx5b",
            "host-extension-pressure-qualify",
            "hx5b-s3-aitrip-build",
            "hx5b-c6-xiao-build",
        ):
            self.assertIn(token, makefile)
        self.assertIn("tests.contract.test_hx5b_extension_pressure", runner)
        self.assertIn("No new host capability", docs)
        self.assertIn("HARDWARE_NOT_RUN", docs)
        self.assertIn("HX6", docs)


if __name__ == "__main__":
    unittest.main()
