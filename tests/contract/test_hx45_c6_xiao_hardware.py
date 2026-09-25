from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools import build_hx45_c6_xiao, evaluate_hx45_c6_xiao


ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "tests/hardware-in-loop/hx45-c6-seeed-xiao-4m"


def file_evidence(path: Path, root: Path) -> dict[str, object]:
    return {
        "path": str(path.relative_to(root)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size,
    }


def board_marker() -> dict[str, object]:
    return {
        "board": "Seeed Studio XIAO ESP32C6",
        "target": "esp32c6",
        "chip_model": 13,
        "chip_revision": 1,
        "cores": 1,
        "flash_bytes": 4 * 1024 * 1024,
        "psram_bytes": 0,
        "elf_sha256": build_hx45_c6_xiao.EXPECTED_NATIVE_ELF_SHA256,
        "common_wasm_sha256": build_hx45_c6_xiao.EXPECTED_COMMON_WASM_SHA256,
    }


def case_marker(name: str, observed: int) -> str:
    return "PULSE_HX45_CASE " + json.dumps(
        {
            "name": name,
            "observed": observed,
            "expected": observed,
            "status": "PASS",
        }
    )


def heap_marker(cycle: int, stage: str, active: bool = False) -> str:
    return "PULSE_HX45_HEAP " + json.dumps(
        {
            "cycle": cycle,
            "stage": stage,
            "internal_free": 90000 if active else 100000,
            "internal_minimum": 90000,
            "internal_largest": 80000,
            "psram_free": 0,
            "psram_minimum": 0,
            "psram_largest": 0,
        }
    )


def passing_serial() -> str:
    lines = ["PULSE_HX45_BOARD " + json.dumps(board_marker())]
    for name in ("board-is-esp32c6", "board-flash-is-4mb", "board-has-no-psram"):
        lines.append(case_marker(name, 1))
    lines.append(
        'PULSE_HX45_BEGIN {"status":"RUNNING","warmup_cycles":1,'
        '"measured_cycles":5}'
    )
    for cycle in range(6):
        for stage in (
            "before",
            "after-extension-start",
            "after-wamr-load",
            "after-roundtrip",
            "after-clean-unload",
        ):
            lines.append(heap_marker(cycle, stage, stage == "after-wamr-load"))
        lines.append(
            "PULSE_HX45_MAIN_STACK "
            + json.dumps(
                {
                    "cycle": cycle,
                    "stage": "after-roundtrip",
                    "headroom_bytes": 5000 if cycle == 0 else 4096,
                }
            )
        )
        lines.append(
            "PULSE_HX45_CYCLE "
            + json.dumps(
                {
                    "cycle": cycle,
                    "measured": cycle != 0,
                    "status": "PASS",
                    "internal_before": 100000,
                    "internal_after": 100000,
                    "psram_before": 0,
                    "psram_after": 0,
                    "stack_headroom_bytes": 3072 if cycle == 0 else 2048,
                    "main_stack_headroom_bytes": 5000 if cycle == 0 else 4096,
                    "queue_high_water": 1 if cycle == 0 else 2,
                    "completion_latency_ms": 1,
                }
            )
        )

    required_cases = {
        "event-effect-roundtrip": (6, 0),
        "extension-stack-measured": (6, 1),
        "extension-queue-measured": (6, 1),
        "main-stack-headroom": (6, 1),
        "internal-free-headroom": (8, 1),
        "internal-largest-headroom": (8, 1),
        "internal-heap-recovered": (5, 1),
        "unknown-event-rejected-on-target": (1, -6),
        "extension-unload": (6, 0),
        "real-wasm-event-trap": (1, -15),
        "trap-main-stack-headroom": (1, 1),
        "expired-quiesce-requires-timeout": (1, -16),
        "expired-quiesce-latches-reset": (1, 1),
        "reset-main-stack-headroom": (1, 1),
        "reset-breadcrumb-recorded": (1, 1),
    }
    for name, (count, observed) in required_cases.items():
        lines.extend(case_marker(name, observed) for _ in range(count))

    lines.extend(
        [
            heap_marker(900, "before-real-wasm-trap"),
            'PULSE_HX45_MAIN_STACK {"cycle":900,"stage":"after-real-wasm-trap",'
            '"headroom_bytes":4500}',
            heap_marker(900, "during-real-wasm-trap", True),
            heap_marker(900, "after-real-wasm-trap"),
            'PULSE_HX45_TRAP {"status":"PASS","observed":-15,'
            '"expected":-15,"runtime_outcome":7}',
            heap_marker(1000, "reset-required", True),
            'PULSE_HX45_MAIN_STACK {"cycle":1000,"stage":"reset-required",'
            '"headroom_bytes":4300}',
            'PULSE_HX45_RESET_ARMED {"status":"PASS","phase":1,'
            '"fault_code":1213739780,"fault_status":-5,"reset_required":1}',
            "PULSE_HX45_BOARD " + json.dumps(board_marker()),
        ]
    )
    for name in ("board-is-esp32c6", "board-flash-is-4mb", "board-has-no-psram"):
        lines.append(case_marker(name, 1))
    lines.extend(
        [
            'PULSE_HX45_RESET_OBSERVED {"status":"PASS","reset_reason":3,'
            '"software_reset":true,"breadcrumb_valid":true,"reset_required":1,'
            '"fault_code":1213739780,"fault_status":-5}',
            'PULSE_HX45_FINAL {"status":"PASS","board":'
            '"Seeed Studio XIAO ESP32C6","measured_cycles":5,'
            '"minimum_internal_free":90000,"minimum_internal_largest":80000,'
            '"minimum_psram_free":0,"minimum_psram_largest":0,'
            '"minimum_stack_headroom":2048,"minimum_main_stack_headroom":4096,'
            '"maximum_queue_high_water":2,'
            '"target_runtime":"NAMED_BOARD_OBSERVED"}',
        ]
    )
    return "\n".join(lines) + "\n"


def write_build_report(root: Path) -> Path:
    native = root / "native-extension/synthetic-loopback-esp32c6.elf"
    native.parent.mkdir(parents=True)
    native.write_bytes(build_hx45_c6_xiao.DEFAULT_SEALED_NATIVE_ELF.read_bytes())
    common = root / "inputs/wdc_hx4_event_effect_wasm.wasm"
    common.parent.mkdir()
    common.write_bytes(build_hx45_c6_xiao.COMMON_WASM.read_bytes())

    evidence_paths = {
        "sdkconfig": root / "sdkconfig",
        "dependency_lock": root / "project/dependencies.lock",
        "build_log": root / "build.log",
        "application_elf": root / "build/pulse_hx45_c6_xiao_4m.elf",
        "application_binary": root / "build/pulse_hx45_c6_xiao_4m.bin",
        "application_map": root / "build/pulse_hx45_c6_xiao_4m.map",
        "bootloader_binary": root / "build/bootloader/bootloader.bin",
        "partition_table_binary": root / "build/partition_table/partition-table.bin",
        "flasher_args": root / "build/flasher_args.json",
        "flash_args": root / "build/flash_args",
    }
    for name, path in evidence_paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((name + "\n").encode())
    evidence_paths["dependency_lock"].write_bytes(build_hx45_c6_xiao.LOCK.read_bytes())

    harness_paths = {
        name: root / "project" / name
        for name in build_hx45_c6_xiao.HARNESS_SOURCE_PATHS
    }
    for name, path in harness_paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(("harness:" + name + "\n").encode())
    generated = root / "project/main/hx45_extension_blob.c"
    generated.write_text("generated sealed extension blob\n", encoding="utf-8")

    report = {
        "schema": build_hx45_c6_xiao.REPORT_SCHEMA,
        "status": "PASS",
        "board": {
            "manufacturer": "Seeed Studio",
            "model": "XIAO ESP32C6",
            "board_marking": "XIAO ESP32C6",
            "target": "esp32c6",
            "flash_bytes": 4 * 1024 * 1024,
            "psram_bytes": 0,
        },
        "claim_boundary": {
            "build": "BUILD_PROVEN",
            "runtime": "HARDWARE_NOT_RUN",
            "canonical_compile_realization_unchanged": True,
        },
        "sealed_sources": {
            "firmware": evaluate_hx45_c6_xiao.EXPECTED_FIRMWARE_SOURCE,
            "native_sdk": evaluate_hx45_c6_xiao.EXPECTED_NATIVE_SDK_SOURCE,
        },
        "native_extension": {"elf": file_evidence(native, root)},
        "common_wasm": file_evidence(common, root),
        "harness_sources": {
            name: file_evidence(path, root) for name, path in harness_paths.items()
        },
        "generated_sources": {"extension_blob": file_evidence(generated, root)},
        "firmware": {
            "status": "PASS",
            "result": "BUILD_PROVEN",
            "size": {"diram_remain": 200000, "iram_remain": 0},
            "headroom_gate": {
                "status": "PASS",
                "minimum_diram_remain_bytes": 160 * 1024,
                "observed_diram_remain_bytes": 200000,
                "application_partition_bytes": 2 * 1024 * 1024,
                "application_binary_bytes": evidence_paths[
                    "application_binary"
                ].stat().st_size,
            },
            "environment": {
                "status": "PASS",
                "version": "v5.4.4",
                "source_commit": "296b6eab9445fd720e71aecab961e2d3fbca9944",
                "platform": "darwin/arm64",
                "canonical_platform": "linux/amd64",
                "platform_scope": "NAMED_BOARD_HIL_BUILD",
            },
            "sdkconfig": file_evidence(evidence_paths["sdkconfig"], root),
            "dependency_lock": file_evidence(
                evidence_paths["dependency_lock"], root
            ),
            "build_log": file_evidence(evidence_paths["build_log"], root),
            "artifacts": {
                name: file_evidence(path, root)
                for name, path in evidence_paths.items()
                if name not in {"sdkconfig", "dependency_lock", "build_log"}
            },
        },
    }
    path = root / "build-report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


class HX45C6XiaoHardwareTests(unittest.TestCase):
    def test_harness_is_exactly_4mb_no_psram_and_usb_serial_jtag(self) -> None:
        defaults = (HARNESS / "sdkconfig.defaults").read_text(encoding="utf-8")
        main = (HARNESS / "main/hx45_c6_xiao_main.c").read_text(encoding="utf-8")
        cmake = (HARNESS / "main/CMakeLists.txt").read_text(encoding="utf-8")
        self.assertIn("CONFIG_ESPTOOLPY_FLASHSIZE_4MB=y", defaults)
        self.assertIn("CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG=y", defaults)
        self.assertIn("# CONFIG_ELF_LOADER_LOAD_PSRAM is not set", defaults)
        self.assertIn("# CONFIG_ESP_SYSTEM_PMP_IDRAM_SPLIT is not set", defaults)
        self.assertNotIn("CONFIG_SPIRAM=y", defaults)
        self.assertNotIn("esp_psram", cmake)
        self.assertNotIn("esp_psram", main)
        self.assertNotIn("MALLOC_CAP_SPIRAM", main)
        self.assertIn("CHIP_ESP32C6", main)
        self.assertIn("board-has-no-psram", main)
        self.assertIn("wdc_extension_profile_esp32c6", main)
        self.assertIn("factory,    app,  factory, 0x10000, 2M", (HARNESS / "partitions.csv").read_text())
        self.assertFalse((HARNESS / "main/hx45_extension_blob.c").exists())

    def test_sealed_c6_fixture_and_prepare_only_report(self) -> None:
        fixture = build_hx45_c6_xiao.DEFAULT_SEALED_NATIVE_ELF
        self.assertEqual(
            hashlib.sha256(fixture.read_bytes()).hexdigest(),
            build_hx45_c6_xiao.EXPECTED_NATIVE_ELF_SHA256,
        )
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "run"
            report = build_hx45_c6_xiao.qualify_build(
                out_dir=output,
                sealed_native_elf=fixture,
                prepare_only=True,
                idf_path=None,
                idf_py=None,
                timeout=1,
            )
            self.assertEqual(report["status"], "PREPARED")
            self.assertEqual(report["board"]["model"], "XIAO ESP32C6")
            self.assertEqual(report["board"]["flash_bytes"], 4 * 1024 * 1024)
            self.assertEqual(report["board"]["psram_bytes"], 0)
            self.assertTrue((output / "project/main/hx45_extension_blob.c").is_file())

    def test_sdkconfig_validator_rejects_psram(self) -> None:
        required = {
            "CONFIG_IDF_TARGET": '"esp32c6"',
            "CONFIG_IDF_TARGET_ESP32C6": "y",
            "CONFIG_PARTITION_TABLE_CUSTOM": "y",
            "CONFIG_PARTITION_TABLE_CUSTOM_FILENAME": '"partitions.csv"',
            "CONFIG_ESPTOOLPY_FLASHSIZE_4MB": "y",
            "CONFIG_ELF_LOADER": "y",
            "CONFIG_FREERTOS_SUPPORT_STATIC_ALLOCATION": "y",
            "CONFIG_FREERTOS_TLSP_DELETION_CALLBACKS": "y",
            "CONFIG_FREERTOS_THREAD_LOCAL_STORAGE_POINTERS": "1",
            "CONFIG_FREERTOS_CHECK_STACKOVERFLOW_CANARY": "y",
            "CONFIG_ESP_MAIN_TASK_STACK_SIZE": "16384",
            "CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG": "y",
        }
        with tempfile.TemporaryDirectory() as temporary:
            sdkconfig = Path(temporary) / "sdkconfig"
            sdkconfig.write_text(
                "\n".join(f"{key}={value}" for key, value in required.items()) + "\n",
                encoding="utf-8",
            )
            build_hx45_c6_xiao.validate_sdkconfig(sdkconfig)
            sdkconfig.write_text(
                sdkconfig.read_text(encoding="utf-8") + "CONFIG_SPIRAM=y\n",
                encoding="utf-8",
            )
            with self.assertRaises(build_hx45_c6_xiao.HardwareBuildError):
                build_hx45_c6_xiao.validate_sdkconfig(sdkconfig)

    def test_c6_loader_allocation_restores_executable_intent(self) -> None:
        compiler = shutil.which("cc")
        self.assertIsNotNone(
            compiler,
            "host C compiler is required for the C6 allocator smoke test",
        )
        component = ROOT / "firmware/components/wdc_elf"
        cmake = (component / "CMakeLists.txt").read_text(encoding="utf-8")
        allocator = (component / "wdc_elf_c6_allocator.c").read_text(
            encoding="utf-8"
        )
        self.assertIn("CONFIG_IDF_TARGET_ESP32C6", cmake)
        self.assertIn("-Wl,--wrap=esp_elf_malloc", cmake)
        self.assertIn("MALLOC_CAP_EXEC", allocator)
        self.assertIn("MALLOC_CAP_CACHE_ALIGNED", allocator)
        self.assertNotIn("MALLOC_CAP_8BIT | MALLOC_CAP_EXEC", allocator)

        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "hx45-c6-elf-allocator-smoke"
            build = subprocess.run(
                [
                    compiler,
                    "-std=c11",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    f"-I{ROOT / 'tests/contract/fakes'}",
                    str(
                        ROOT
                        / "tests/contract/hx45_c6_elf_allocator_smoke.c"
                    ),
                    str(component / "wdc_elf_c6_allocator.c"),
                    "-o",
                    str(executable),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(build.returncode, 0, build.stdout)
            run = subprocess.run(
                [str(executable)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(run.returncode, 0, run.stdout)

    def test_sdkconfig_validator_rejects_fixed_pmp_split(self) -> None:
        required = {
            "CONFIG_IDF_TARGET": '"esp32c6"',
            "CONFIG_IDF_TARGET_ESP32C6": "y",
            "CONFIG_PARTITION_TABLE_CUSTOM": "y",
            "CONFIG_PARTITION_TABLE_CUSTOM_FILENAME": '"partitions.csv"',
            "CONFIG_ESPTOOLPY_FLASHSIZE_4MB": "y",
            "CONFIG_ELF_LOADER": "y",
            "CONFIG_FREERTOS_SUPPORT_STATIC_ALLOCATION": "y",
            "CONFIG_FREERTOS_TLSP_DELETION_CALLBACKS": "y",
            "CONFIG_FREERTOS_THREAD_LOCAL_STORAGE_POINTERS": "1",
            "CONFIG_FREERTOS_CHECK_STACKOVERFLOW_CANARY": "y",
            "CONFIG_ESP_MAIN_TASK_STACK_SIZE": "16384",
            "CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG": "y",
            "CONFIG_ESP_SYSTEM_PMP_IDRAM_SPLIT": "y",
        }
        with tempfile.TemporaryDirectory() as temporary:
            sdkconfig = Path(temporary) / "sdkconfig"
            sdkconfig.write_text(
                "\n".join(f"{key}={value}" for key, value in required.items())
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(build_hx45_c6_xiao.HardwareBuildError):
                build_hx45_c6_xiao.validate_sdkconfig(sdkconfig)

    def test_evaluator_accepts_complete_named_board_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            serial = root / "serial.log"
            serial.write_text(passing_serial(), encoding="utf-8")
            report = evaluate_hx45_c6_xiao.evaluate(
                serial_log=serial,
                build_report_path=write_build_report(root),
                board_marking="XIAO ESP32C6",
            )
            self.assertEqual(report["status"], "PASS", report["failures"])
            self.assertEqual(report["runtime_result"], "NAMED_BOARD_OBSERVED")
            self.assertEqual(len(report["observations"]["measured_clean_cycles"]), 5)

            serial.write_text(passing_serial() + "Guru Meditation Error\n", encoding="utf-8")
            report = evaluate_hx45_c6_xiao.evaluate(
                serial_log=serial,
                build_report_path=root / "build-report.json",
                board_marking="XIAO ESP32C6",
            )
            self.assertEqual(report["status"], "FAIL")
            self.assertTrue(report["observations"]["fatal_serial_signatures"])

    def test_evaluator_rejects_wrong_board_attestation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            serial = root / "serial.log"
            serial.write_text(passing_serial(), encoding="utf-8")
            report = evaluate_hx45_c6_xiao.evaluate(
                serial_log=serial,
                build_report_path=write_build_report(root),
                board_marking="generic ESP32-C6",
            )
            self.assertEqual(report["status"], "FAIL")
            self.assertTrue(any("board marking" in item for item in report["failures"]))

    def test_make_runner_docs_and_packaging_expose_xiao_lane(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        runner = (ROOT / "tools/run_contract_tests.py").read_text(encoding="utf-8")
        packager = (ROOT / "tools/package_release.py").read_text(encoding="utf-8")
        for token in (
            "check-hx45-c6-xiao",
            "hx45-c6-xiao-build",
            "hx45-c6-xiao-evaluate",
            "HX_XIAO_SEALED_ELF",
            "HX_XIAO_IDF_PATH",
            "HX_XIAO_IDF_PY",
        ):
            self.assertIn(token, makefile)
        self.assertIn("tests.contract.test_hx45_c6_xiao_hardware", runner)
        self.assertIn("hx45-c6-seeed-xiao-4m/fixtures/", packager)
        self.assertTrue((ROOT / "docs/HX4_5_C6_XIAO_HARDWARE.md").is_file())


if __name__ == "__main__":
    unittest.main()
