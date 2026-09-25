from __future__ import annotations

import ast
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import build_hx45_s3_aitrip, evaluate_hx45_s3_aitrip


ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "tests/hardware-in-loop/hx45-s3-aitrip-n8r2"


def file_evidence(path: Path, root: Path) -> dict[str, object]:
    return {
        "path": str(path.relative_to(root)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size,
    }


def board_marker(native_digest: str) -> dict[str, object]:
    return {
        "board": "AITRIP ESP32-S3-DevKitC-1 N8R2",
        "target": "esp32s3",
        "chip_model": 9,
        "chip_revision": 1,
        "cores": 2,
        "flash_bytes": 8 * 1024 * 1024,
        "psram_bytes": 2 * 1024 * 1024,
        "elf_sha256": native_digest,
        "common_wasm_sha256": build_hx45_s3_aitrip.EXPECTED_COMMON_WASM_SHA256,
    }


def passing_serial(native_digest: str) -> str:
    lines = [
        f"PULSE_HX45_BOARD {json.dumps(board_marker(native_digest))}",
        'PULSE_HX45_BEGIN {"status":"RUNNING","warmup_cycles":1,"measured_cycles":5}',
    ]
    for cycle in range(0, 6):
        for stage in (
            "before",
            "after-extension-start",
            "after-wamr-load",
            "after-roundtrip",
            "after-clean-unload",
        ):
            lines.append(
                "PULSE_HX45_HEAP "
                + json.dumps(
                    {
                        "cycle": cycle,
                        "stage": stage,
                        "internal_free": 90000 if stage == "after-wamr-load" else 100000,
                        "internal_minimum": 90000,
                        "internal_largest": 80000,
                        "psram_free": 1800000 if stage == "after-wamr-load" else 1900000,
                        "psram_minimum": 1800000,
                        "psram_largest": 1700000,
                    }
                )
            )
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
                    "psram_before": 1900000,
                    "psram_after": 1900000,
                    "stack_headroom_bytes": 3072 if cycle == 0 else 2048,
                    "main_stack_headroom_bytes": 5000 if cycle == 0 else 4096,
                    "queue_high_water": 1 if cycle == 0 else 2,
                    "completion_latency_ms": 1,
                }
            )
        )
    required_case_specs = {
        "event-effect-roundtrip": (6, 0),
        "extension-stack-measured": (6, 1),
        "extension-queue-measured": (6, 1),
        "main-stack-headroom": (6, 1),
        "internal-free-headroom": (8, 1),
        "internal-largest-headroom": (8, 1),
        "psram-free-headroom": (8, 1),
        "psram-largest-headroom": (8, 1),
        "internal-heap-recovered": (5, 1),
        "psram-heap-recovered": (5, 1),
        "unknown-event-rejected-on-target": (1, -6),
        "extension-unload": (6, 0),
        "real-wasm-event-trap": (1, -15),
        "trap-main-stack-headroom": (1, 1),
        "expired-quiesce-requires-timeout": (1, -16),
        "expired-quiesce-latches-reset": (1, 1),
        "reset-main-stack-headroom": (1, 1),
        "reset-breadcrumb-recorded": (1, 1),
    }
    for name, (count, observed) in required_case_specs.items():
        for _ in range(count):
            lines.append(
                "PULSE_HX45_CASE "
                + json.dumps(
                    {
                        "name": name,
                        "observed": observed,
                        "expected": observed,
                        "status": "PASS",
                    }
                )
            )
    lines.extend(
        [
            'PULSE_HX45_HEAP {"cycle":900,"stage":"before-real-wasm-trap","internal_free":100000,"internal_minimum":90000,"internal_largest":80000,"psram_free":1900000,"psram_minimum":1800000,"psram_largest":1700000}',
            'PULSE_HX45_MAIN_STACK {"cycle":900,"stage":"after-real-wasm-trap","headroom_bytes":4500}',
            'PULSE_HX45_HEAP {"cycle":900,"stage":"during-real-wasm-trap","internal_free":90000,"internal_minimum":90000,"internal_largest":80000,"psram_free":1800000,"psram_minimum":1800000,"psram_largest":1700000}',
            'PULSE_HX45_HEAP {"cycle":900,"stage":"after-real-wasm-trap","internal_free":100000,"internal_minimum":90000,"internal_largest":80000,"psram_free":1900000,"psram_minimum":1800000,"psram_largest":1700000}',
            'PULSE_HX45_TRAP {"status":"PASS","observed":-15,"expected":-15,"runtime_outcome":7}',
            'PULSE_HX45_HEAP {"cycle":1000,"stage":"reset-required","internal_free":95000,"internal_minimum":90000,"internal_largest":80000,"psram_free":1850000,"psram_minimum":1800000,"psram_largest":1700000}',
            'PULSE_HX45_MAIN_STACK {"cycle":1000,"stage":"reset-required","headroom_bytes":4300}',
            'PULSE_HX45_RESET_ARMED {"status":"PASS","phase":1,"fault_code":1213739780,"fault_status":-5,"reset_required":1}',
            f"PULSE_HX45_BOARD {json.dumps(board_marker(native_digest))}",
            'PULSE_HX45_RESET_OBSERVED {"status":"PASS","reset_reason":3,"software_reset":true,"breadcrumb_valid":true,"reset_required":1,"fault_code":1213739780,"fault_status":-5}',
            'PULSE_HX45_FINAL {"status":"PASS","board":"AITRIP ESP32-S3-DevKitC-1 N8R2","measured_cycles":5,"minimum_internal_free":90000,"minimum_internal_largest":80000,"minimum_psram_free":1800000,"minimum_psram_largest":1700000,"minimum_stack_headroom":2048,"minimum_main_stack_headroom":4096,"maximum_queue_high_water":2,"target_runtime":"NAMED_BOARD_OBSERVED"}',
        ]
    )
    return "\n".join(lines) + "\n"


class HX45S3AitripHardwareTests(unittest.TestCase):
    def test_local_python_tools_remain_compatible_with_python39(self) -> None:
        for path in sorted((ROOT / "tools").glob("*.py")):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path), feature_version=9)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if not isinstance(node.func, ast.Name) or node.func.id != "zip":
                    continue
                self.assertNotIn(
                    "strict",
                    {keyword.arg for keyword in node.keywords},
                    f"{path.relative_to(ROOT)} uses zip(strict=), which requires Python 3.10",
                )

    def test_harness_is_isolated_and_exactly_n8r2(self) -> None:
        defaults = (HARNESS / "sdkconfig.defaults").read_text(encoding="utf-8")
        partitions = (HARNESS / "partitions.csv").read_text(encoding="utf-8")
        top_cmake = (HARNESS / "CMakeLists.txt").read_text(encoding="utf-8")
        self.assertIn("CONFIG_ESPTOOLPY_FLASHSIZE_8MB=y", defaults)
        self.assertIn("CONFIG_SPIRAM_MODE_QUAD=y", defaults)
        self.assertIn("CONFIG_SPIRAM_SPEED_40M=y", defaults)
        self.assertIn("CONFIG_SPIRAM_MALLOC_ALWAYSINTERNAL=4096", defaults)
        self.assertIn("CONFIG_SPIRAM_MALLOC_RESERVE_INTERNAL=32768", defaults)
        self.assertIn("CONFIG_ELF_LOADER_LOAD_PSRAM=y", defaults)
        self.assertIn("CONFIG_ESP_MAIN_TASK_STACK_SIZE=16384", defaults)
        self.assertIn("CONFIG_FREERTOS_CHECK_STACKOVERFLOW_CANARY=y", defaults)
        self.assertIn("factory,    app,  factory, 0x10000, 2M", partitions)
        self.assertNotIn("ota_0", partitions)
        self.assertIn("EXTRA_COMPONENT_DIRS", top_cmake)
        self.assertFalse((HARNESS / "main/hx45_extension_blob.c").exists())

    def test_builder_stages_time_normalized_sealed_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "run"
            output.mkdir()
            elf = root / "extension.elf"
            elf.write_bytes(b"sealed fixture")
            project, staged_repository = build_hx45_s3_aitrip.stage_project(
                output, elf
            )
            self.assertTrue(
                (staged_repository / "firmware/components/wdc_runtime").is_dir()
            )
            self.assertTrue(
                (staged_repository / "native-sdk/c/include").is_dir()
            )
            for tree in (project, staged_repository):
                for path in (tree, *tree.rglob("*")):
                    self.assertEqual(
                        int(path.stat().st_mtime),
                        build_hx45_s3_aitrip.NORMALIZED_BUILD_INPUT_MTIME,
                    )

    def test_psram_text_mapping_preserves_callable_instruction_addresses(self) -> None:
        source = (
            ROOT / "firmware/components/wdc_elf/wdc_elf.c"
        ).read_text(encoding="utf-8")
        self.assertIn('#include "private/elf_platform.h"', source)
        self.assertIn("CONFIG_ELF_LOADER_CACHE_OFFSET", source)
        self.assertGreaterEqual(source.count("elf_remap_text"), 2)

    def test_psram_elf_writable_state_remains_internal(self) -> None:
        compiler = shutil.which("cc")
        self.assertIsNotNone(
            compiler,
            "host C compiler is required for the HX4.5 allocator smoke test",
        )
        component = ROOT / "firmware/components/wdc_elf"
        cmake = (component / "CMakeLists.txt").read_text(encoding="utf-8")
        allocator = (component / "wdc_elf_allocator.c").read_text(
            encoding="utf-8"
        )
        adapter = (component / "wdc_elf.c").read_text(encoding="utf-8")
        self.assertGreaterEqual(cmake.count("CONFIG_ELF_LOADER_LOAD_PSRAM"), 2)
        self.assertIn("-Wl,--wrap=esp_elf_malloc", cmake)
        self.assertIn("-Wl,--wrap=esp_elf_free", cmake)
        self.assertIn("-u __wrap_esp_elf_malloc", cmake)
        self.assertIn("-u __wrap_esp_elf_free", cmake)
        self.assertIn("PRIV_REQUIRES elf_loader heap", cmake)
        self.assertIn("MALLOC_CAP_SPIRAM", allocator)
        self.assertIn("MALLOC_CAP_INTERNAL", allocator)
        self.assertIn("wdc_elf_allocator_prepare", allocator)
        self.assertIn("s_pending.residue", allocator)
        self.assertLess(
            adapter.index("wdc_elf_allocator_prepare"),
            adapter.index("esp_elf_relocate"),
        )
        self.assertGreater(
            adapter.index("wdc_elf_allocator_finish"),
            adapter.index("esp_elf_relocate"),
        )
        self.assertNotIn("CONFIG_FREERTOS_TASK_CREATE_ALLOW_EXT_MEM", cmake)
        self.assertNotIn("CONFIG_FREERTOS_TASK_CREATE_ALLOW_EXT_MEM", allocator)

        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "hx45-elf-allocator-smoke"
            build = subprocess.run(
                [
                    compiler,
                    "-std=c11",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    f"-I{ROOT / 'tests/contract/fakes'}",
                    f"-I{component}",
                    str(ROOT / "tests/contract/hx45_elf_allocator_smoke.c"),
                    str(component / "wdc_elf_allocator.c"),
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
                [
                    str(executable),
                    str(
                        HARNESS
                        / "fixtures/synthetic-loopback-esp32s3.elf"
                    ),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(run.returncode, 0, run.stdout)

    def test_psram_native_text_keeps_wamr_linear_memory_internal(self) -> None:
        compiler = shutil.which("cc")
        self.assertIsNotNone(
            compiler,
            "host C compiler is required for the HX4.5 WAMR allocator smoke test",
        )
        component = ROOT / "firmware/components/wdc_runtime"
        cmake = (component / "CMakeLists.txt").read_text(encoding="utf-8")
        allocator = (component / "wdc_runtime_allocator.c").read_text(
            encoding="utf-8"
        )
        self.assertIn("CONFIG_ELF_LOADER_LOAD_PSRAM", cmake)
        self.assertIn("-Wl,--wrap=os_mmap", cmake)
        self.assertIn("-u __wrap_os_mmap", cmake)
        self.assertIn("MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT", allocator)
        self.assertIn("MMAP_PROT_EXEC", allocator)
        self.assertIn("__real_os_mmap", allocator)
        self.assertIn("heap_caps_malloc(size + overhead", allocator)

        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "hx45-wamr-allocator-smoke"
            build = subprocess.run(
                [
                    compiler,
                    "-std=c11",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    f"-I{ROOT / 'tests/contract/fakes'}",
                    str(ROOT / "tests/contract/hx45_wamr_allocator_smoke.c"),
                    str(component / "wdc_runtime_allocator.c"),
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

    def test_wamr_receives_a_writable_module_buffer_for_its_full_lifetime(self) -> None:
        compiler = shutil.which("cc")
        self.assertIsNotNone(
            compiler,
            "host C compiler is required for the HX4.5 WAMR buffer smoke test",
        )
        component = ROOT / "firmware/components/wdc_runtime"
        runtime = (component / "wdc_runtime.c").read_text(encoding="utf-8")
        buffer_source = (component / "wdc_runtime_buffer.c").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("wasm_runtime_load((uint8_t *)wasm_bytes", runtime)
        self.assertIn("wdc_runtime_buffer_copy(wasm_bytes, wasm_len)", runtime)
        self.assertIn("wasm_runtime_load(writable_wasm", runtime)
        self.assertIn("runtime->backend_wasm_buffer = writable_wasm", runtime)
        self.assertLess(
            runtime.index("wasm_runtime_unload"),
            runtime.index("wdc_runtime_buffer_release((uint8_t *)runtime->backend_wasm_buffer"),
        )
        self.assertIn("MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT", buffer_source)

        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "hx45-wamr-module-buffer-smoke"
            build = subprocess.run(
                [
                    compiler,
                    "-std=c11",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    f"-I{ROOT / 'tests/contract/fakes'}",
                    f"-I{component}",
                    str(ROOT / "tests/contract/hx45_wamr_module_buffer_smoke.c"),
                    str(component / "wdc_runtime_buffer.c"),
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

    def test_wamr_control_flow_runs_on_an_esp_pthread(self) -> None:
        harness_source = (
            HARNESS / "main/hx45_s3_aitrip_main.c"
        ).read_text(encoding="utf-8")
        firmware_entry = (ROOT / "firmware/main/app_main.c").read_text(
            encoding="utf-8"
        )
        harness_cmake = (HARNESS / "main/CMakeLists.txt").read_text(
            encoding="utf-8"
        )
        firmware_cmake = (ROOT / "firmware/main/CMakeLists.txt").read_text(
            encoding="utf-8"
        )
        for source, worker, stack in (
            (harness_source, "hx45_driver_pthread", "16384"),
            (firmware_entry, "wdc_app_pthread", "16u * 1024u"),
        ):
            self.assertIn("#include <pthread.h>", source)
            self.assertIn(worker, source)
            self.assertIn("pthread_attr_setstacksize", source)
            self.assertIn("pthread_create", source)
            self.assertIn("pthread_join", source)
            self.assertIn(stack, source)
        self.assertIn("pthread", harness_cmake)
        self.assertIn("pthread", firmware_cmake)

    def test_harness_executes_target_runtime_measurement_and_reset_boundary(self) -> None:
        source = (HARNESS / "main/hx45_s3_aitrip_main.c").read_text(
            encoding="utf-8"
        )
        for token in (
            "wdc_extension_inspect",
            "wdc_extension_load_descriptor",
            "wdc_extension_registry_start",
            "wdc_hx4_event_effect_wasm",
            "wdc_extension_bridge_process_next",
            "wdc_extension_registry_unload_clean",
            "heap_caps_get_free_size",
            "esp_flash_get_physical_size",
            "task_stack_high_water_bytes",
            "PULSE_HX45_MAIN_STACK",
            "HX45_INTERNAL_FREE_MIN_BYTES",
            "queue_high_water",
            "RTC_NOINIT_ATTR",
            "esp_restart",
            "PULSE_HX45_FINAL",
        ):
            self.assertIn(token, source)
        for forbidden in ("wdc_hal", "gpio_set_level", "esp_wifi", "mqtt"):
            self.assertNotIn(forbidden, source)

    def test_generated_blob_is_deterministic_and_flash_resident(self) -> None:
        sealed_fixture = build_hx45_s3_aitrip.DEFAULT_SEALED_NATIVE_ELF
        self.assertTrue(sealed_fixture.is_file())
        self.assertEqual(
            hashlib.sha256(sealed_fixture.read_bytes()).hexdigest(),
            build_hx45_s3_aitrip.EXPECTED_NATIVE_ELF_SHA256,
        )
        data = b"sealed-elf-fixture"
        digest = hashlib.sha256(data).hexdigest()
        first = build_hx45_s3_aitrip.render_blob_source(data, digest)
        second = build_hx45_s3_aitrip.render_blob_source(data, digest)
        self.assertEqual(first, second)
        self.assertIn("const uint8_t pulse_hx45_extension_elf[]", first)
        self.assertNotIn("DRAM_ATTR", first)
        self.assertIn(digest, first)
        self.assertIn(build_hx45_s3_aitrip.EXPECTED_COMMON_WASM_SHA256, first)
        with self.assertRaises(build_hx45_s3_aitrip.HardwareBuildError):
            build_hx45_s3_aitrip.render_blob_source(data, "0" * 64)

    def test_builder_seals_sources_and_generated_configuration(self) -> None:
        self.assertEqual(
            build_hx45_s3_aitrip.EXPECTED_FIRMWARE_SOURCE,
            evaluate_hx45_s3_aitrip.EXPECTED_FIRMWARE_SOURCE,
        )
        self.assertEqual(
            build_hx45_s3_aitrip.validate_sealed_sources(),
            {
                "firmware": build_hx45_s3_aitrip.EXPECTED_HP55_FIRMWARE_SOURCE,
                "native_sdk": build_hx45_s3_aitrip.EXPECTED_NATIVE_SDK_SOURCE,
                "historical_campaign_firmware":
                    build_hx45_s3_aitrip.EXPECTED_FIRMWARE_SOURCE,
                "current_successor": "HP5.5",
            },
        )
        required = {
            "CONFIG_IDF_TARGET": '"esp32s3"',
            "CONFIG_IDF_TARGET_ESP32S3": "y",
            "CONFIG_PARTITION_TABLE_CUSTOM": "y",
            "CONFIG_PARTITION_TABLE_CUSTOM_FILENAME": '"partitions.csv"',
            "CONFIG_ESPTOOLPY_FLASHSIZE_8MB": "y",
            "CONFIG_SPIRAM": "y",
            "CONFIG_SPIRAM_MODE_QUAD": "y",
            "CONFIG_SPIRAM_SPEED_40M": "y",
            "CONFIG_SPIRAM_USE_MALLOC": "y",
            "CONFIG_SPIRAM_MALLOC_ALWAYSINTERNAL": "4096",
            "CONFIG_SPIRAM_MALLOC_RESERVE_INTERNAL": "32768",
            "CONFIG_ELF_LOADER": "y",
            "CONFIG_ELF_LOADER_LOAD_PSRAM": "y",
            "CONFIG_ELF_LOADER_CACHE_OFFSET": "y",
            "CONFIG_FREERTOS_SUPPORT_STATIC_ALLOCATION": "y",
            "CONFIG_FREERTOS_TLSP_DELETION_CALLBACKS": "y",
            "CONFIG_FREERTOS_THREAD_LOCAL_STORAGE_POINTERS": "1",
            "CONFIG_FREERTOS_CHECK_STACKOVERFLOW_CANARY": "y",
            "CONFIG_ESP_MAIN_TASK_STACK_SIZE": "16384",
        }
        with tempfile.TemporaryDirectory() as temporary:
            sdkconfig = Path(temporary) / "sdkconfig"
            sdkconfig.write_text(
                "\n".join(f"{key}={value}" for key, value in required.items())
                + "\n",
                encoding="utf-8",
            )
            build_hx45_s3_aitrip.validate_sdkconfig(sdkconfig)
            sdkconfig.write_text(
                sdkconfig.read_text(encoding="utf-8")
                + "CONFIG_ELF_LOADER_LIBC_SYMBOLS=y\n",
                encoding="utf-8",
            )
            with self.assertRaises(build_hx45_s3_aitrip.HardwareBuildError):
                build_hx45_s3_aitrip.validate_sdkconfig(sdkconfig)

    def test_serial_evaluator_accepts_only_complete_named_board_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            serial = root / "serial.log"
            build = root / "build-report.json"
            native_path = root / "native-extension/synthetic-loopback-esp32s3.elf"
            native_path.parent.mkdir()
            native_path.write_bytes(b"synthetic exact native fixture")
            native_digest = hashlib.sha256(native_path.read_bytes()).hexdigest()
            evidence_paths = {
                "sdkconfig": root / "sdkconfig",
                "dependency_lock": root / "project/dependencies.lock",
                "build_log": root / "build.log",
                "application_elf": root / "build/pulse_hx45_s3_aitrip_n8r2.elf",
                "application_binary": root / "build/pulse_hx45_s3_aitrip_n8r2.bin",
                "application_map": root / "build/pulse_hx45_s3_aitrip_n8r2.map",
                "bootloader_binary": root / "build/bootloader/bootloader.bin",
                "partition_table_binary": root / "build/partition_table/partition-table.bin",
                "flasher_args": root / "build/flasher_args.json",
                "flash_args": root / "build/flash_args",
            }
            harness_paths = {
                name: root / "project" / name
                for name in build_hx45_s3_aitrip.HARNESS_SOURCE_PATHS
            }
            for name, path in evidence_paths.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((name + "\n").encode())
            evidence_paths["dependency_lock"].write_bytes(
                (
                    ROOT
                    / "firmware/locks/host-extension/idf-5.4.4/esp32s3/dependencies.lock"
                ).read_bytes()
            )
            for name, path in harness_paths.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(("harness:" + name + "\n").encode())
            common_path = root / "inputs/wdc_hx4_event_effect_wasm.wasm"
            common_path.parent.mkdir()
            common_path.write_bytes(
                (
                    ROOT
                    / "firmware/components/wdc_runtime/test_vectors/wdc_hx4_event_effect_wasm.wasm"
                ).read_bytes()
            )
            generated_blob = root / "project/main/hx45_extension_blob.c"
            generated_blob.write_text("generated sealed extension blob\n", encoding="utf-8")
            serial.write_text(passing_serial(native_digest), encoding="utf-8")
            build.write_text(
                json.dumps(
                    {
                        "schema": "pulse.esp32.hx45-s3-aitrip-build.v1",
                        "status": "PASS",
                        "board": {
                            "manufacturer": "AITRIP",
                            "model": "ESP32-S3-DevKitC-1 N8R2",
                            "module": "ESP32-S3-WROOM-1-N8R2",
                            "target": "esp32s3",
                            "flash_bytes": 8 * 1024 * 1024,
                            "psram_bytes": 2 * 1024 * 1024,
                            "psram_mode": "quad",
                        },
                        "claim_boundary": {
                            "build": "BUILD_PROVEN",
                            "runtime": "HARDWARE_NOT_RUN",
                            "canonical_16mb_reference_unchanged": True,
                        },
                        "sealed_sources": {
                            "firmware": evaluate_hx45_s3_aitrip.EXPECTED_FIRMWARE_SOURCE,
                            "native_sdk": evaluate_hx45_s3_aitrip.EXPECTED_NATIVE_SDK_SOURCE,
                        },
                        "native_extension": {
                            "elf": file_evidence(native_path, root)
                        },
                        "common_wasm": file_evidence(common_path, root),
                        "harness_sources": {
                            name: file_evidence(path, root)
                            for name, path in harness_paths.items()
                        },
                        "generated_sources": {
                            "extension_blob": file_evidence(generated_blob, root)
                        },
                        "firmware": {
                            "status": "PASS",
                            "result": "BUILD_PROVEN",
                            "size": {"diram_remain": 4096, "iram_remain": 16},
                            "headroom_gate": {
                                "status": "PASS",
                                "minimum_diram_remain_bytes": 1024,
                                "observed_diram_remain_bytes": 4096,
                                "minimum_iram_remain_bytes": 1,
                                "observed_iram_remain_bytes": 16,
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
                ),
                encoding="utf-8",
            )
            with mock.patch.object(
                evaluate_hx45_s3_aitrip,
                "EXPECTED_NATIVE_ELF_SHA256",
                native_digest,
            ):
                report = evaluate_hx45_s3_aitrip.evaluate(
                    serial_log=serial,
                    build_report_path=build,
                    module_marking="ESP32-S3-WROOM-1 N8R2",
                )
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["runtime_result"], "NAMED_BOARD_OBSERVED")
            self.assertEqual(len(report["observations"]["measured_clean_cycles"]), 5)

            serial.write_text(
                passing_serial(native_digest) + "Guru Meditation Error\n",
                encoding="utf-8",
            )
            with mock.patch.object(
                evaluate_hx45_s3_aitrip,
                "EXPECTED_NATIVE_ELF_SHA256",
                native_digest,
            ):
                report = evaluate_hx45_s3_aitrip.evaluate(
                    serial_log=serial,
                    build_report_path=build,
                    module_marking="ESP32-S3-WROOM-1-N8R2",
                )
            self.assertEqual(report["status"], "FAIL")
            self.assertTrue(report["observations"]["fatal_serial_signatures"])

    def test_make_runner_and_docs_expose_named_board_lane(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        runner = (ROOT / "tools/run_contract_tests.py").read_text(encoding="utf-8")
        self.assertIn("check-hx45-s3-aitrip", makefile)
        self.assertIn("hx45-s3-aitrip-build", makefile)
        self.assertIn("hx45-s3-aitrip-evaluate", makefile)
        self.assertIn("HX_AITRIP_SEALED_ELF", makefile)
        self.assertIn("HX_AITRIP_IDF_PATH", makefile)
        self.assertIn("HX_AITRIP_IDF_PY", makefile)
        self.assertIn("--sealed-native-elf", makefile)
        self.assertIn("--idf-path", makefile)
        self.assertIn("--idf-py", makefile)
        self.assertIn("tests.contract.test_hx45_s3_aitrip_hardware", makefile)
        self.assertIn("tests.contract.test_hx45_s3_aitrip_hardware", runner)
        self.assertTrue((ROOT / "docs/HX4_5_S3_AITRIP_HARDWARE.md").is_file())


if __name__ == "__main__":
    unittest.main()
