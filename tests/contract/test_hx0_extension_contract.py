from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "specs/PULSE-ESP32-004-host-extension-spine.md"
ADR = ROOT / "docs/adr/0010-native-extension-loader-and-abi.md"
MATRIX = ROOT / "firmware/idf-family-matrix.json"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _normalized(text: str) -> str:
    return " ".join(text.split())


def _section(text: str, heading: str, next_heading: str) -> str:
    start = text.index(heading)
    end = text.index(next_heading, start)
    return text[start:end]


def _assert_layout(
    case: unittest.TestCase,
    text: str,
    expected: list[tuple[int, int, str]],
    total_size: int,
) -> None:
    occupied: set[int] = set()
    for offset, size, field in expected:
        row = rf"\|\s*{offset}\s*\|\s*{size}\s*\|\s*`{re.escape(field)}`"
        case.assertRegex(text, row, field)
        field_bytes = set(range(offset, offset + size))
        case.assertFalse(occupied & field_bytes, f"overlapping layout field: {field}")
        occupied |= field_bytes
    case.assertEqual(occupied, set(range(total_size)))


class HX0ExtensionContractTests(unittest.TestCase):
    def test_authoritative_documents_exist_and_are_explicitly_experimental(self) -> None:
        self.assertTrue(SPEC.is_file())
        self.assertTrue(ADR.is_file())
        spec = _normalized(_text(SPEC))
        adr = _text(ADR)
        for token in [
            "**Document:** PULSE-ESP32-004",
            "**Status:** HX0 contract; sufficient only for the synthetic dual-ISA proof",
            "HX0 introduces no loader, extension, firmware integration, runtime result, or",
            "This document is authoritative for the HX0-HX7 extension proof.",
            "explicitly amends the illustrative native-extension shape in PULSE-ESP32-003",
        ]:
            self.assertIn(token, spec)
        self.assertIn("Accepted for the HX0-HX7 synthetic proof only.", adr)
        self.assertIn("does not freeze a permanent public Pulse", adr)

    def test_metadata_record_is_fixed_bounded_and_artifact_bound(self) -> None:
        spec = _text(SPEC)
        metadata = _section(spec, "### 5.3 Metadata record v1", "### 5.4 Target identities")
        expected = [
            (0, 8, "magic"),
            (8, 2, "format_major"),
            (10, 2, "format_minor"),
            (12, 4, "record_size"),
            (16, 2, "architecture_id"),
            (18, 2, "soc_id"),
            (20, 4, "flags"),
            (24, 2, "required_host_abi_major"),
            (26, 2, "required_host_abi_min_minor"),
            (28, 2, "extension_abi_major"),
            (30, 2, "extension_abi_minor"),
            (32, 16, "extension_id"),
            (48, 4, "descriptor_size"),
            (52, 4, "descriptor_alignment"),
            (56, 2, "event_count"),
            (58, 2, "operation_count"),
            (60, 4, "reserved0"),
            (64, 16, "event_ids[4]"),
            (80, 16, "operation_ids[4]"),
            (96, 4, "task_count"),
            (100, 4, "task_stack_bytes"),
            (104, 4, "static_memory_bytes"),
            (108, 4, "queue_depth"),
            (112, 4, "queue_item_bytes"),
            (116, 4, "max_event_payload_bytes"),
            (120, 4, "max_effect_request_bytes"),
            (124, 4, "max_effect_completion_bytes"),
            (128, 32, "artifact_sha256"),
            (160, 32, "reserved1"),
        ]
        _assert_layout(self, metadata, expected, 192)
        normalized = _normalized(spec)
        for token in [
            "`.pulse_ext_meta`",
            "exactly 192 bytes",
            "PULSEXT1",
            "replaced by zero bytes",
            "normalized metadata digest",
            "distinct from the artifact digest",
            "sidecar may be retained as",
            "admission recomputes",
        ]:
            self.assertIn(token, normalized)

    def test_pre_execution_admission_has_no_constructor_escape(self) -> None:
        spec = _text(SPEC)
        inspection = _normalized(
            _section(spec, "## 5. Pre-execution ELF admission", "## 6. Runtime descriptor admission")
        )
        for token in [
            "before handing them to the loader",
            "ELFCLASS32",
            "validate `e_machine`",
            "unexpected or unresolved imports",
            "reject any type not explicitly qualified for the exact target and loader",
            "`.init_array`",
            "`DT_INIT`",
            "must not call a module entry point, constructor, or registration hook",
        ]:
            self.assertIn(token, inspection)

    def test_descriptor_layout_and_lifecycle_are_exact(self) -> None:
        spec = _text(SPEC)
        descriptor = _section(spec, "## 6. Runtime descriptor admission", "## 7. Catalog identity")
        expected = [
            (0, 4, "magic"),
            (4, 4, "struct_size"),
            (8, 2, "abi_major"),
            (10, 2, "abi_minor"),
            (12, 4, "flags"),
            (16, 16, "extension_id"),
            (32, 32, "metadata_sha256"),
            (64, 2, "event_count"),
            (66, 2, "operation_count"),
            (68, 4, "reserved0"),
            (72, 16, "event_ids[4]"),
            (88, 16, "operation_ids[4]"),
            (104, 4, "init_fn"),
            (108, 4, "start_fn"),
            (112, 4, "invoke_fn"),
            (116, 4, "health_fn"),
            (120, 4, "quiesce_fn"),
            (124, 4, "deinit_fn"),
            (128, 32, "reserved1"),
        ]
        _assert_layout(self, descriptor, expected, 160)
        self.assertIn("pulse_extension_entry_v1", descriptor)
        self.assertIn("no task", descriptor)
        self.assertIn("immutable raw ELF buffer", descriptor)
        lifecycle = _section(spec, "## 9. Lifecycle contract", "## 10. Stable host-service imports")
        for signature in [
            "int32_t init(const pulse_extension_init_args_v1 *args);",
            "int32_t start(void);",
            "int32_t invoke(const pulse_extension_invoke_v1 *request);",
            "int32_t health(pulse_extension_health_v1 *out_health);",
            "int32_t quiesce(const pulse_extension_quiesce_v1 *request);",
            "int32_t deinit(void);",
        ]:
            self.assertIn(signature, lifecycle)
        self.assertIn("creates exactly one statically provisioned task", lifecycle)
        self.assertIn("The host does not use arbitrary task deletion", lifecycle)

    def test_deadline_span_ownership_and_completion_are_unambiguous(self) -> None:
        spec = _text(SPEC)
        calls = _normalized(
            _section(spec, "## 8. Call records, spans, and deadlines", "## 9. Lifecycle contract")
        )
        for token in [
            "The pointer is borrowed for the call only.",
            "copy an accepted request into its declared queue",
            "absolute host monotonic time",
            "host owns the absolute deadline",
            "never extends it based on extension",
            "return `PULSE_EXT_OK` only after no extension task can call a host service",
        ]:
            self.assertIn(token, calls)
        services = _normalized(
            _section(spec, "## 10. Stable host-service imports", "## 11. Target-refinement import policy")
        )
        for token in [
            "first in-deadline completion: accepted",
            "second completion: `PULSE_EXT_ERR_DUPLICATE`",
            "post-quiescence completion",
            "do not publish an event, mutate the",
        ]:
            self.assertIn(token, services)

    def test_host_service_record_layouts_are_exact(self) -> None:
        spec = _text(SPEC)
        services = _section(spec, "## 10. Stable host-service imports", "## 11. Target-refinement import policy")
        event = _section(services, "### 10.1 Event record", "### 10.2 Completion record")
        completion = _section(services, "### 10.2 Completion record", "### 10.3 Log record")
        log = _section(services, "### 10.3 Log record", "### 10.4 Fault record")
        fault = _section(services, "### 10.4 Fault record", "### 10.5 Service behavior")
        _assert_layout(
            self,
            event,
            [
                (0, 4, "struct_size"),
                (4, 4, "event_id"),
                (8, 8, "causation_id"),
                (16, 4, "payload_ptr"),
                (20, 4, "payload_len"),
                (24, 4, "flags"),
                (28, 12, "reserved"),
            ],
            40,
        )
        _assert_layout(
            self,
            completion,
            [
                (0, 4, "struct_size"),
                (4, 4, "status"),
                (8, 8, "correlation_id"),
                (16, 4, "payload_ptr"),
                (20, 4, "payload_len"),
                (24, 4, "flags"),
                (28, 12, "reserved"),
            ],
            40,
        )
        _assert_layout(
            self,
            log,
            [
                (0, 4, "struct_size"),
                (4, 4, "level"),
                (8, 4, "diagnostic_code"),
                (12, 4, "message_ptr"),
                (16, 4, "message_len"),
                (20, 4, "flags"),
            ],
            24,
        )
        _assert_layout(
            self,
            fault,
            [
                (0, 4, "struct_size"),
                (4, 4, "status"),
                (8, 4, "fault_code"),
                (12, 8, "correlation_id"),
                (20, 4, "flags"),
                (24, 8, "reserved"),
            ],
            32,
        )

    def test_stable_import_surface_is_closed_versioned_and_allocation_free(self) -> None:
        spec = _text(SPEC)
        services = _section(spec, "## 10. Stable host-service imports", "## 11. Target-refinement import policy")
        imports = set(re.findall(r"\| `(pulse_host_[a-z0-9_]+_v1)` \|", services))
        self.assertEqual(
            imports,
            {
                "pulse_host_emit_event_v1",
                "pulse_host_complete_effect_v1",
                "pulse_host_monotonic_ms_v1",
                "pulse_host_log_v1",
                "pulse_host_report_health_v1",
                "pulse_host_report_fault_v1",
            },
        )
        self.assertIn("There is no allocation or release import in v1.", services)
        import_policy = _section(spec, "## 11. Target-refinement import policy", "## 12. Resource budgets")
        for token in [
            "exact per-realization ESP-IDF/FreeRTOS allowlist",
            "Wildcard symbol families",
            "Unexpected or unresolved symbols fail",
            "`malloc`",
            "Static FreeRTOS task and queue primitives",
        ]:
            self.assertIn(token, import_policy)

    def test_registry_is_numeric_provider_resolved_and_sealed_before_init(self) -> None:
        spec = _text(SPEC)
        registry = _section(spec, "## 7. Catalog identity", "## 8. Call records")
        for token in [
            "extension identity: 16 bytes",
            "event identity: nonzero `uint32_t`",
            "operation identity: nonzero `uint32_t`",
            "reject duplicate extension IDs",
            "reject duplicate event IDs",
            "reject duplicate operation IDs",
            "seal registry",
            "There is no registration callback or post-seal catalog mutation.",
        ]:
            self.assertIn(token, registry)

    def test_proof_matrix_is_separate_and_preserves_if7(self) -> None:
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        self.assertEqual(matrix["schema"], "pulse.esp32.idf-family-matrix.v1")
        self.assertEqual(
            (matrix["realizations"]["esp32s3-reference"]["target"], matrix["realizations"]["esp32s3-reference"]["intent"]),
            ("esp32s3", "required"),
        )
        self.assertEqual(
            (matrix["realizations"]["esp32c6-compile"]["target"], matrix["realizations"]["esp32c6-compile"]["intent"]),
            ("esp32c6", "exploratory"),
        )
        spec = _text(SPEC)
        proof = _section(spec, "## 15. Separate dual-ISA proof matrix", "## 16. HX0 negative contract")
        for token in [
            "`firmware/extension-proof-matrix.json`",
            "separate from",
            "does not rewrite IF7 history",
            "no new build/runtime claim",
            "S3 evidence is never reused for C6",
        ]:
            self.assertIn(token, proof)

    def test_cross_document_decisions_and_deferred_scope_are_consistent(self) -> None:
        spec = _text(SPEC)
        adr = _text(ADR)
        for token in [
            ".pulse_ext_meta",
            "pulse_extension_entry_v1",
            "numeric and fixed-width",
            "Reset remains the authoritative production hard teardown",
            "There is no allocation service in v1.",
            "does not alter IF7's historical",
            "WDC bundle v1 remains a single-Wasm container",
        ]:
            self.assertIn(token, adr)
        negative = _section(spec, "## 16. HX0 negative contract", "## 17. HX1 evidence decisions remaining")
        for token in [
            "unbounded C strings",
            "arbitrary runtime event or operation registration",
            "extension-controlled candidate confirmation",
            "direct extension-to-Wasm calls",
            "network, GPIO, BLE, LoRa, storage, RAX, OTA",
            "a host allocation service",
        ]:
            self.assertIn(token, negative)
        remaining = _section(spec, "## 17. HX1 evidence decisions remaining", "## 18. Deferred work")
        for decision in [
            "Exact loader",
            "Accepted ELF type",
            "Relocations",
            "Symbol resolution",
            "Constructor behavior",
            "Executable memory",
            "Loader ownership",
            "C6 fit",
            "Raw-byte inspection handoff",
        ]:
            self.assertIn(decision, remaining)

    def test_make_and_split_runner_expose_hx0_without_broadening_workflow(self) -> None:
        makefile = _text(ROOT / "Makefile")
        runner = _text(ROOT / "tools/run_contract_tests.py")
        workflow = _text(ROOT / ".github/workflows/idf-family-matrix.yml")
        self.assertIn("check-hx0", makefile)
        self.assertIn("tests.contract.test_hx0_extension_contract", makefile)
        self.assertIn("tests.contract.test_hx0_extension_contract", runner)
        self.assertNotIn("check-hx0", workflow)


if __name__ == "__main__":
    unittest.main()
