from __future__ import annotations

import json
import struct
import tempfile
import unittest
from pathlib import Path

from tools import inspect_native_extension, qualify_extension_spine


ROOT = Path(__file__).resolve().parents[2]
FIRMWARE = ROOT / "firmware"
MATRIX_PATH = FIRMWARE / "extension-proof-matrix.json"


class HX1ElfLoaderTests(unittest.TestCase):
    def test_matrix_is_exact_independent_and_preserves_c3(self) -> None:
        matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
        self.assertEqual(matrix["schema"], "pulse.esp32.extension-proof-matrix.v1")
        self.assertEqual(set(matrix["proofs"]), set(qualify_extension_spine.EXPECTED_PROOFS))
        for proof_id, (base, target, isa) in qualify_extension_spine.EXPECTED_PROOFS.items():
            proof = matrix["proofs"][proof_id]
            self.assertEqual((proof["base_realization"], proof["target"], proof["isa"]), (base, target, isa))
            self.assertEqual(proof["reproducibility_runs"], 2)
            self.assertEqual(proof["runtime_result"], "HARDWARE_NOT_RUN")
            self.assertIn("locks/host-extension/", proof["dependency_lock"])
        self.assertEqual(matrix["preserved_results"], {"esp32c3-compile": "INCOMPATIBLE"})
        self.assertNotEqual(MATRIX_PATH, FIRMWARE / "idf-family-matrix.json")

    def test_loader_identity_license_and_transitive_graph_are_pinned(self) -> None:
        matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
        loader = matrix["loader"]
        self.assertEqual(loader["version"], "1.3.2")
        self.assertEqual(loader["license"], "Apache-2.0")
        self.assertEqual(loader["source_commit"], "1608d9c922c992986c285fd753ef15ecbbad3cde")
        self.assertEqual(loader["source_tree"], "d2863c4d7360a3c735a8c801829ad0d10fd002e0")
        self.assertEqual(loader["transitive_constraint"], "espressif/cmake_utilities 0.*")
        manifest = (FIRMWARE / "components/wdc_elf/idf_component.yml").read_text(encoding="utf-8")
        self.assertIn('version: "1.3.2"', manifest)
        self.assertNotIn("*", manifest)

    def test_target_locks_have_exact_generated_component_hashes(self) -> None:
        matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
        hashes = set()
        for proof in matrix["proofs"].values():
            evidence = qualify_extension_spine._validate_extension_lock(  # noqa: SLF001
                FIRMWARE / proof["dependency_lock"], proof["target"]
            )
            hashes.add(evidence["sha256"])
            self.assertEqual(evidence["components"]["espressif/elf_loader"]["version"], "1.3.2")
            self.assertEqual(evidence["components"]["espressif/cmake_utilities"]["version"], "0.5.3")
        self.assertEqual(len(hashes), 2, "target-bound locks must remain distinct")

    def test_adapter_is_opaque_and_loader_types_do_not_leak(self) -> None:
        header = (FIRMWARE / "components/wdc_elf/include/wdc_elf.h").read_text(encoding="utf-8")
        source = (FIRMWARE / "components/wdc_elf/wdc_elf.c").read_text(encoding="utf-8")
        self.assertIn("typedef struct WdcElfImage WdcElfImage;", header)
        self.assertNotIn("esp_elf", header)
        self.assertNotIn("elf_symbol", header)
        for name in [
            "wdc_elf_load_inspected",
            "wdc_elf_link_anchor",
            "wdc_elf_map_virtual",
            "wdc_elf_memory_layout",
            "wdc_elf_loader_code",
            "wdc_elf_unload",
        ]:
            self.assertIn(name, header)
            self.assertIn(name, source)
        self.assertIn("esp_elf_relocate", source)
        self.assertNotIn("esp_elf_request", source)
        main = (FIRMWARE / "main/CMakeLists.txt").read_text(encoding="utf-8")
        self.assertIn("wdc_elf", main)

    def test_symbol_tables_and_psram_loading_are_fail_closed(self) -> None:
        s3 = (FIRMWARE / "realizations/esp32s3-extension-proof.defaults").read_text(encoding="utf-8")
        c6 = (FIRMWARE / "realizations/esp32c6-extension-proof.defaults").read_text(encoding="utf-8")
        for text in (s3, c6):
            self.assertIn("CONFIG_ELF_LOADER=y", text)
            self.assertIn("# CONFIG_ELF_DYNAMIC_LOAD_SHARED_OBJECT is not set", text)
            self.assertIn("# CONFIG_ELF_LOADER_LIBC_SYMBOLS is not set", text)
            self.assertIn("# CONFIG_ELF_LOADER_ESPIDF_SYMBOLS is not set", text)
            self.assertIn("# CONFIG_ELF_LOADER_CUSTOMER_SYMBOLS is not set", text)
        self.assertIn("# CONFIG_ELF_LOADER_LOAD_PSRAM is not set", s3)
        self.assertIn("# CONFIG_ESP_SYSTEM_PMP_IDRAM_SPLIT is not set", c6)

    @staticmethod
    def _minimal_elf(machine: int) -> bytes:
        names = b"\0.shstrtab\0.text\0"
        text = b"\0\0\0\0"
        shstr_offset = 84
        text_offset = shstr_offset + len(names)
        shoff = text_offset + len(text)
        ident = b"\x7fELF" + bytes([1, 1, 1]) + bytes(9)
        header = struct.pack(
            "<16sHHIIIIIHHHHHH",
            ident,
            3,
            machine,
            1,
            0,
            52,
            shoff,
            0,
            52,
            32,
            1,
            40,
            3,
            1,
        )
        program = struct.pack("<IIIIIIII", 1, 0, 0, 0, text_offset + len(text), text_offset + len(text), 5, 0x1000)
        null = bytes(40)
        shstr = struct.pack("<IIIIIIIIII", 1, 3, 0, 0, shstr_offset, len(names), 0, 0, 1, 0)
        text_header = struct.pack("<IIIIIIIIII", 11, 1, 6, 0, text_offset, len(text), 0, 0, 4, 0)
        return header + program + names + text + null + shstr + text_header

    def test_inspector_checks_machine_without_executing_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            elf = Path(temp_name) / "probe.elf"
            elf.write_bytes(self._minimal_elf(94))
            valid = inspect_native_extension.inspect_elf(elf, "esp32s3")
            wrong = inspect_native_extension.inspect_elf(elf, "esp32c6")
        self.assertEqual(valid["status"], "PASS")
        self.assertEqual(valid["header"]["type_name"], "ET_DYN")
        self.assertEqual(valid["header"]["machine_name"], "EM_XTENSA")
        self.assertEqual(wrong["status"], "FAIL")
        self.assertTrue(any("does not match esp32c6" in item for item in wrong["validation_errors"]))

    def test_supported_relocations_are_closed_per_isa(self) -> None:
        self.assertEqual(inspect_native_extension.LOADER_SUPPORTED[94], (2, 3, 4, 5))
        self.assertEqual(inspect_native_extension.LOADER_SUPPORTED[243], (0, 1, 3, 5))
        self.assertNotEqual(
            inspect_native_extension.LOADER_SUPPORTED[94],
            inspect_native_extension.LOADER_SUPPORTED[243],
        )

    def test_source_risk_and_hardware_limits_are_explicit(self) -> None:
        document = " ".join(
            (ROOT / "docs/HX1_ELF_LOADER_QUALIFICATION.md").read_text(encoding="utf-8").split()
        )
        qualifier = (ROOT / "tools/qualify_extension_spine.py").read_text(encoding="utf-8")
        for token in [
            "does not propagate the return from `esp_elf_arch_relocate`",
            "runtime-seal blocker",
            "HARDWARE_NOT_RUN",
            "NOT_RUN",
            "MALLOC_CAP_EXEC",
            "drops its executable allocation flag",
            "PMP IRAM/DRAM split",
        ]:
            self.assertIn(token, document)
        self.assertIn("load_return_codes", qualifier)
        self.assertIn("repeated_load_cycles", qualifier)
        self.assertIn("NOT_MEASURED_NO_HARDWARE", qualifier)

    def test_make_and_split_runner_expose_hx1(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        runner = (ROOT / "tools/run_contract_tests.py").read_text(encoding="utf-8")
        self.assertIn("check-hx1", makefile)
        self.assertIn("host-extension-loader-qualify", makefile)
        self.assertIn("tests.contract.test_hx1_elf_loader", makefile)
        self.assertIn("tests.contract.test_hx1_elf_loader", runner)


if __name__ == "__main__":
    unittest.main()
