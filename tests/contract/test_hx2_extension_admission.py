from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools import inspect_native_extension


ROOT = Path(__file__).resolve().parents[2]
VECTORS = ROOT / "tests" / "contract" / "native_extension_vectors"
MANIFEST = json.loads((VECTORS / "vectors.json").read_text(encoding="utf-8"))


class HX2ExtensionAdmissionTests(unittest.TestCase):
    def test_public_abi_is_single_fixed_width_authority(self) -> None:
        header = (ROOT / "native-sdk/c/include/pulse_extension.h").read_text(encoding="utf-8")
        self.assertIn("pulse_extension_metadata_v1", header)
        self.assertIn("pulse_extension_descriptor_v1", header)
        self.assertIn("pulse_extension_entry_v1", header)
        for token in [
            "sizeof(pulse_extension_metadata_v1) == 192u",
            "sizeof(pulse_extension_descriptor_v1) == 160u",
            "offsetof(pulse_extension_descriptor_v1, init_fn) == 104u",
            "offsetof(pulse_extension_descriptor_v1, deinit_fn) == 124u",
            "sizeof(void *) == 4u",
        ]:
            self.assertIn(token, header)
        for prohibited in ["size_t ", "long ", "bool ", "...", "char *name"]:
            self.assertNotIn(prohibited, header)

    def test_valid_dual_isa_vectors_pass_strict_admission(self) -> None:
        for vector in MANIFEST["valid"]:
            report = inspect_native_extension.inspect_elf(
                VECTORS / vector["file"],
                vector["expected_target"],
                require_extension=True,
            )
            self.assertEqual(report["status"], "PASS", report["validation_errors"])
            self.assertEqual(report["metadata"]["record_size"], 192)
            self.assertEqual(report["metadata"]["descriptor_size"], 160)
            self.assertEqual(report["entry_export"]["name"], "pulse_extension_entry_v1")
            self.assertEqual(report["imports"], [])

    def test_pre_execution_negative_corpus_rejects_without_lifecycle_calls(self) -> None:
        lifecycle_calls = 0
        observed_names: set[str] = set()
        for vector in MANIFEST["pre_execution_rejections"]:
            observed_names.add(vector["name"])
            try:
                report = inspect_native_extension.inspect_elf(
                    VECTORS / vector["file"],
                    vector["expected_target"],
                    require_extension=True,
                )
                errors = report["validation_errors"]
                self.assertEqual(report["status"], "FAIL", vector["name"])
            except inspect_native_extension.ElfInspectionError as exc:
                errors = [str(exc)]
            self.assertIn(vector["expected_error"], " | ".join(errors), vector["name"])
        self.assertEqual(lifecycle_calls, 0)
        for required in {
            "wrong-machine",
            "wrong-target-id",
            "unknown-metadata-version",
            "truncated-metadata",
            "metadata-outside-bounds",
            "duplicate-event-id",
            "duplicate-operation-id",
            "incompatible-abi-major",
            "unsupported-required-abi-minor",
            "wrong-descriptor-size-metadata",
            "nonzero-metadata-reserved",
            "unexpected-import",
            "unresolved-import",
            "budget-above-profile",
            "artifact-hash-mismatch",
        }:
            self.assertIn(required, observed_names)

    def test_descriptor_negative_corpus_rejects_before_lifecycle(self) -> None:
        metadata_report = inspect_native_extension.inspect_elf(
            VECTORS / MANIFEST["descriptor_metadata_file"],
            "esp32s3",
            require_extension=True,
        )
        metadata = metadata_report["metadata"]
        ranges = {
            "executable_ranges": ((0x1000, 0x100),),
            "readable_ranges": ((0x2000, 0x100),),
            "descriptor_address": 0x2000,
        }
        valid = (VECTORS / MANIFEST["valid_descriptor"]).read_bytes()
        self.assertEqual(
            inspect_native_extension.validate_descriptor_bytes(valid, metadata, **ranges), []
        )
        lifecycle_calls = 0
        for vector in MANIFEST["descriptor_rejections"]:
            errors = inspect_native_extension.validate_descriptor_bytes(
                (VECTORS / vector["file"]).read_bytes(), metadata, **ranges
            )
            self.assertIn(vector["expected_error"], " | ".join(errors), vector["name"])
        self.assertEqual(lifecycle_calls, 0)

    def test_registry_rejects_duplicate_extension_identity(self) -> None:
        vector = MANIFEST["registry_rejections"][0]
        descriptors = [(VECTORS / item).read_bytes() for item in vector["files"]]
        errors = inspect_native_extension.validate_registry_catalog(descriptors)
        self.assertIn(vector["expected_error"], errors)

    def test_host_stage_one_has_no_loader_or_extension_call_surface(self) -> None:
        source = (ROOT / "firmware/components/wdc_extension/wdc_extension.c").read_text(
            encoding="utf-8"
        )
        stage_one = source.split("int32_t wdc_extension_inspect", 1)[1].split(
            "static int memory_contains", 1
        )[0]
        self.assertNotIn("wdc_elf_", stage_one)
        self.assertNotRegex(stage_one, r"pulse_extension_entry_v1\s*\(")
        for lifecycle in ("init_fn", "start_fn", "invoke_fn", "health_fn", "quiesce_fn", "deinit_fn"):
            self.assertIsNone(re.search(rf"->{lifecycle}\s*\(", source))
        stage_two = source.split("int32_t wdc_extension_load_descriptor", 1)[1]
        self.assertLess(stage_two.index("sha256_bytes"), stage_two.index("wdc_elf_load_inspected"))
        self.assertLess(stage_two.index("wdc_elf_load_inspected"), stage_two.index("entry()"))
        self.assertLess(stage_two.index("entry()"), stage_two.index("normalize_descriptor"))
        normalizer = source.split("static int32_t normalize_descriptor", 1)[1].split(
            "#ifdef PULSE_EXTENSION_HOST_TEST", 1
        )[0]
        self.assertLess(normalizer.index("readable_contains"), normalizer.index("memcpy"))
        self.assertLess(normalizer.index("memcpy"), normalizer.index("descriptor_valid"))
        self.assertIn("descriptor_storage", stage_two)
        self.assertIn("descriptor_storage", (ROOT / "firmware/components/wdc_extension/include/wdc_extension.h").read_text(encoding="utf-8"))
        adapter = (ROOT / "firmware/components/wdc_elf/wdc_elf.c").read_text(encoding="utf-8")
        self.assertIn("wdc_elf_load_inspected_with_symbols", adapter)
        self.assertIn("wdc_elf_resolve_exact", adapter)
        self.assertIn("s_resolved_symbol_count = 0u", adapter)
        self.assertIn("inspection->imports", stage_two)

    def test_synthetic_extension_is_scope_compressed_and_fail_closed(self) -> None:
        source = (ROOT / "native-extensions/synthetic-loopback/extension.c").read_text(
            encoding="utf-8"
        )
        self.assertIn(".start_fn = synthetic_start", source)
        self.assertNotRegex(source, r"#include\s*[<\"](?:freertos|driver|esp_|lwip|nvs)")
        self.assertNotRegex(source, r"\b(?:gpio|wifi|mqtt|http|ble|lora|rax|nvs)_")
        for token in ["malloc(", "calloc(", "realloc(", "free("]:
            self.assertNotIn(token, source)

    def test_bounded_sha256_matches_standard_vectors(self) -> None:
        compiler = shutil.which("cc")
        self.assertIsNotNone(compiler, "host C compiler is required for the HX2 digest smoke test")
        component = ROOT / "firmware/components/wdc_extension"
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "hx2-sha256-smoke"
            build = subprocess.run(
                [
                    compiler,
                    "-std=c11",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    f"-I{component}",
                    str(ROOT / "tests/contract/hx2_sha256_smoke.c"),
                    str(component / "wdc_extension_sha256.c"),
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

    def test_loader_bounded_unaligned_descriptor_is_normalized_before_validation(self) -> None:
        compiler = shutil.which("cc")
        self.assertIsNotNone(compiler, "host C compiler is required for the HX2 descriptor smoke test")
        component = ROOT / "firmware/components/wdc_extension"
        linker_gc = "-Wl,-dead_strip" if sys.platform == "darwin" else "-Wl,--gc-sections"
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "hx2-descriptor-alignment-smoke"
            build = subprocess.run(
                [
                    compiler,
                    "-std=c11",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-DPULSE_EXTENSION_HOST_TEST",
                    "-ffunction-sections",
                    "-fdata-sections",
                    f"-I{component / 'include'}",
                    f"-I{component}",
                    f"-I{ROOT / 'firmware/components/wdc_elf/include'}",
                    f"-I{ROOT / 'native-sdk/c/include'}",
                    str(ROOT / "tests/contract/hx2_descriptor_alignment_smoke.c"),
                    str(component / "wdc_extension.c"),
                    str(component / "wdc_extension_sha256.c"),
                    linker_gc,
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

    def test_target_stage_one_accepts_the_exact_sealed_s3_elf(self) -> None:
        compiler = shutil.which("cc")
        self.assertIsNotNone(compiler, "host C compiler is required for the HX2 target inspector smoke test")
        component = ROOT / "firmware/components/wdc_extension"
        fixture = (
            ROOT
            / "tests/hardware-in-loop/hx45-s3-aitrip-n8r2/fixtures"
            / "synthetic-loopback-esp32s3.elf"
        )
        linker_gc = "-Wl,-dead_strip" if sys.platform == "darwin" else "-Wl,--gc-sections"
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "hx2-stage-one-elf-smoke"
            build = subprocess.run(
                [
                    compiler,
                    "-std=c11",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-DPULSE_EXTENSION_HOST_TEST",
                    "-ffunction-sections",
                    "-fdata-sections",
                    f"-I{component / 'include'}",
                    f"-I{component}",
                    f"-I{ROOT / 'firmware/components/wdc_elf/include'}",
                    f"-I{ROOT / 'native-sdk/c/include'}",
                    str(ROOT / "tests/contract/hx2_stage_one_elf_smoke.c"),
                    str(component / "wdc_extension.c"),
                    str(component / "wdc_extension_sha256.c"),
                    linker_gc,
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
                [str(executable), str(fixture)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(run.returncode, 0, run.stdout)

    def test_sealed_s3_elf_has_a_solvable_loader_alignment_residue(self) -> None:
        fixture = (
            ROOT
            / "tests/hardware-in-loop/hx45-s3-aitrip-n8r2/fixtures"
            / "synthetic-loopback-esp32s3.elf"
        )
        report = inspect_native_extension.inspect_elf(
            fixture,
            "esp32s3",
            require_extension=True,
            allowed_imports=(
                "pulse_host_complete_effect_v1",
                "pulse_host_emit_event_v1",
                "pulse_host_monotonic_ms_v1",
                "pulse_host_report_health_v1",
                "uxTaskGetStackHighWaterMark",
                "vQueueDelete",
                "vTaskDelay",
                "vTaskDelete",
                "vTaskSetThreadLocalStoragePointerAndDelCallback",
                "xQueueGenericCreateStatic",
                "xQueueGenericSend",
                "xQueueReceive",
                "xTaskCreateStatic",
            ),
        )
        self.assertEqual(report["status"], "PASS", report["validation_errors"])
        layout = report["resource_footprint"]["s3_loader_writable_layout"]
        self.assertEqual(layout["packed_size"], 6978)
        self.assertEqual(layout["allocation_alignment"], 16)
        self.assertEqual(layout["runtime_base_residue"], 14)
        self.assertEqual(
            [
                (item["name"], item["packed_offset"], item["alignment"])
                for item in layout["sections"]
            ],
            [
                (".rodata", 0, 1),
                (".data.rel.ro", 34, 4),
                (".bss", 194, 16),
            ],
        )

    def test_host_component_owns_fixed_registry_and_is_firmware_linked(self) -> None:
        header = (ROOT / "firmware/components/wdc_extension/include/wdc_extension.h").read_text(
            encoding="utf-8"
        )
        cmake = (ROOT / "firmware/main/CMakeLists.txt").read_text(encoding="utf-8")
        app = (ROOT / "firmware/main/app_main.c").read_text(encoding="utf-8")
        self.assertIn("WDC_EXTENSION_REGISTRY_CAPACITY 4u", header)
        self.assertIn("wdc_extension_inspect", header)
        self.assertIn("wdc_extension_load_descriptor", header)
        self.assertIn("wdc_extension_registry_seal", header)
        self.assertNotIn("wdc_extension_start", header)
        self.assertIn("wdc_extension", cmake)
        self.assertIn("wdc_extension_link_anchor", app)

    def test_make_and_split_runner_expose_hx2(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        runner = (ROOT / "tools/run_contract_tests.py").read_text(encoding="utf-8")
        self.assertIn("check-hx2", makefile)
        self.assertIn("host-extension-admission-qualify", makefile)
        self.assertIn("tests.contract.test_hx2_extension_admission", makefile)
        self.assertIn("tests.contract.test_hx2_extension_admission", runner)


if __name__ == "__main__":
    unittest.main()
