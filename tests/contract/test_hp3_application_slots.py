from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools import host_build_contract, qualify_app_slots


ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "specs/PULSE-ESP32-008-application-slots.json"
CATALOG = ROOT / "firmware/host-build-catalog.json"
BUNDLE = ROOT / "examples/bundles/relay-controller/dist/relay-controller-r8.wdcb"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(path: Path) -> list[str]:
    return [
        "".join(line.split())
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


class HP3ApplicationSlotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.model = json.loads(MODEL.read_text(encoding="utf-8"))

    def test_frozen_model_and_fixed_non_rax_artifact(self) -> None:
        self.assertEqual(
            self.model["schema"],
            "pulse.esp32.hp3-application-slot-authority.v1",
        )
        self.assertEqual(self.model["status"], "FROZEN")
        self.assertEqual(self.model["artifact"]["header_bytes"], 192)
        self.assertFalse(self.model["artifact"]["rax"])
        self.assertEqual(self.model["slots"]["count"], 2)
        header = (ROOT / "firmware/components/wdc_app_slots/include/wdc_app_slots.h").read_text(encoding="utf-8")
        self.assertIn("WDC_APP_ARTIFACT_HEADER_BYTES 192u", header)
        self.assertIn("WdcPulseAppArtifactHeaderV1", header)
        self.assertIn("WDC_APP_SLOT_PORTABLE_MINIMUM_BYTES (896u * 1024u)", header)

    def test_canonical_states_and_legacy_source_aliases(self) -> None:
        self.assertEqual(
            self.model["states"],
            ["EMPTY", "STAGED", "VERIFIED", "TRIAL", "CONFIRMED", "REJECTED"],
        )
        abi = (ROOT / "firmware/components/wdc_abi/include/wdc_abi.h").read_text(encoding="utf-8")
        for token in (
            "WDC_SLOT_EMPTY",
            "WDC_SLOT_STAGED",
            "WDC_SLOT_VERIFIED",
            "WDC_SLOT_TRIAL",
            "WDC_SLOT_TRIAL_RUNNING",
            "WDC_SLOT_CONFIRMED",
            "WDC_SLOT_REJECTED",
        ):
            self.assertIn(token, abi)
        self.assertIn("WDC_SLOT_DOWNLOADED = WDC_SLOT_STAGED", abi)
        self.assertIn("WDC_SLOT_PENDING = WDC_SLOT_TRIAL", abi)

    def test_dual_slot_layout_is_additive_to_retained_hil_inputs(self) -> None:
        pairs = (
            (
                "aitrip-esp32s3-devkitc-1-n8r2",
                "hx45-s3-aitrip-n8r2",
                ("2M", "2M", "0x610000"),
            ),
            (
                "seeed-xiao-esp32c6-4m",
                "hx45-c6-seeed-xiao-4m",
                ("896K", "896K", "0x3d0000"),
            ),
        )
        for board, hil, sizes in pairs:
            canonical = _rows(ROOT / "firmware/boards" / board / "partitions.csv")
            historical = _rows(ROOT / "tests/hardware-in-loop" / hil / "partitions.csv")
            self.assertEqual(canonical[:3], historical)
            self.assertEqual(len(canonical), 6)
            self.assertIn("wasm_a,0x40,0x00,0x210000,%s,encrypted" % sizes[0], canonical)
            self.assertIn("wasm_b,0x40,0x01", canonical[4])
            self.assertIn(sizes[1], canonical[4])
            self.assertIn("wasm_meta,0x40,0x02,%s,64K,encrypted" % sizes[2], canonical)
            self.assertFalse(any(row.startswith(("ota_0,", "ota_1,", "otadata,")) for row in canonical))

    def test_inactive_streaming_verification_and_security_floor(self) -> None:
        source = (ROOT / "firmware/components/wdc_app_slots/wdc_app_slots.c").read_text(encoding="utf-8")
        for token in (
            "slot != wdc_app_slots_inactive_slot(metadata)",
            "wdc_ota_stage_write",
            "stream_hash(",
            "wdc_bundle_verify",
            "security_counter < policy->security_version_floor",
            "artifact_authority_verify",
            "record->state = WDC_SLOT_STAGED",
            "record->state = WDC_SLOT_VERIFIED",
        ):
            self.assertIn(token, source)
        self.assertLess(
            source.index("record->state = WDC_SLOT_STAGED"),
            source.index("record->state = WDC_SLOT_VERIFIED"),
        )

    def test_journal_boot_attribution_and_probation_are_host_owned(self) -> None:
        ota = (ROOT / "firmware/components/wdc_ota/wdc_ota.c").read_text(encoding="utf-8")
        activation = (ROOT / "firmware/components/wdc_activation/wdc_activation.c").read_text(encoding="utf-8")
        self.assertIn("offsetof(WdcOtaMetadataRecord, commit_marker)", ota)
        self.assertIn("sizeof(next.commit_marker)", ota)
        for token in (
            "trial_boot_in_progress",
            "trial_boot_generation",
            "reset_attribution",
            "readiness_observed",
            "administration_responsive",
            "resource_floors_preserved",
            "minimum_stable_ms",
            "readiness_deadline_ms",
        ):
            self.assertIn(token, activation)

    def test_prelaunch_gate_precedes_the_only_managed_entry_edge(self) -> None:
        slots = (ROOT / "firmware/components/wdc_app_slots/wdc_app_slots.c").read_text(encoding="utf-8")
        app = (ROOT / "firmware/components/wdc_app/wdc_app.c").read_text(encoding="utf-8")
        self.assertIn("wdc_host_prelaunch_check", slots)
        managed = app.index("int32_t wdc_app_boot_managed_slot")
        gate = app.index("wdc_app_slots_boot(", managed)
        entry = app.index("wdc_runtime_call_init(runtime)", gate)
        self.assertLess(gate, entry)
        self.assertNotIn("wdc_activation_confirm(", app)
        self.assertIn("application_code_launched = true", app[gate:entry + 100])

    def test_host_profiles_and_exact_hp2_locks_include_slot_authority(self) -> None:
        catalog = host_build_contract.load_json(CATALOG)
        resolved = host_build_contract.validate_catalog(catalog)
        expected_profiles = {
            "esp32s3": "esp32s3-psram-slots-v1",
            "esp32c6": "esp32c6-portable-slots-v1",
        }
        for selected in resolved.values():
            profile = selected["profile"]
            entry = selected["entry"]
            self.assertEqual(profile["profile_id"], expected_profiles[entry["target"]])
            self.assertIn("pulse.application-slots.v1", profile["capabilities"])
            lock = host_build_contract.load_json(ROOT / entry["build_lock"])
            fingerprint = host_build_contract.load_json(ROOT / entry["fingerprint"])
            self.assertEqual(host_build_contract.replay_lock(lock, fingerprint), fingerprint)
            self.assertEqual(
                fingerprint["compatibility_surface"]["host_profile_id"],
                profile["profile_id"],
            )
            self.assertEqual(fingerprint["compatibility_surface"]["capability_mask"], 15)

    def test_synthetic_smoke_is_exact_and_never_launches_application(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            executable = Path(temp_name) / "hp3-smoke"
            build = subprocess.run(
                qualify_app_slots._compile_command("cc", executable),
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(build.returncode, 0, build.stdout)
            run = subprocess.run(
                [str(executable), str(BUNDLE)],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
        self.assertEqual(run.returncode, 0, run.stdout)
        smoke = json.loads(run.stdout)
        self.assertEqual(smoke["cases"], 14)
        self.assertEqual(smoke["failures"], 0)
        self.assertFalse(smoke["application_code_launched"])
        self.assertTrue(smoke["last_confirmed_preserved"])
        self.assertTrue(smoke["recovery_explicit"])

    def test_qualifier_and_project_wiring_are_exact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            report = qualify_app_slots.qualify(Path(temp_name), "cc")
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["aggregate"], "PULSE_APPLICATION_SLOT_AUTHORITY_PROVEN")
        self.assertEqual(report["coverage"]["synthetic_cases"], 14)
        self.assertFalse(report["coverage"]["application_code_launched"])
        self.assertEqual(report["claim_boundary"]["physical_power_loss_campaign"], "DEFERRED_HP3_5")
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        runner = (ROOT / "tools/run_contract_tests.py").read_text(encoding="utf-8")
        checker = (ROOT / "tools/check_docs.py").read_text(encoding="utf-8")
        self.assertIn("check-hp3", makefile)
        self.assertIn("app-slots-qualify", makefile)
        self.assertIn("tests.contract.test_hp3_application_slots", runner)
        self.assertIn("docs/HP3_APPLICATION_SLOTS_AND_FALLBACK.md", checker)
        self.assertIn("docs/adr/0012-application-slots-and-host-owned-confirmation.md", checker)
        self.assertIn("specs/PULSE-ESP32-008-application-slots.json", checker)

    def test_preserved_authorities_and_exclusions(self) -> None:
        preserved = self.model["preserved_authorities"]
        self.assertEqual(
            _sha256(ROOT / "specs/PULSE-ESP32-006-host-kernel-resource-authority.json"),
            preserved["hp1_resource_authority_sha256"],
        )
        self.assertEqual(
            _sha256(ROOT / "native-sdk/c/include/pulse_extension.h"),
            preserved["native_extension_abi_sha256"],
        )
        self.assertEqual(
            _sha256(ROOT / "firmware/components/wdc_runtime/test_vectors/wdc_hx4_event_effect_wasm.wasm"),
            preserved["common_wasm_sha256"],
        )
        self.assertEqual(
            set(self.model["excluded"]),
            {
                "RAX",
                "HOST_FIRMWARE_OTA",
                "MQTT_OR_TRANSPORT_IMPLEMENTATION",
                "EXTERNAL_PROVIDER",
                "PULSE_CORE_CHANGES",
                "PHYSICAL_POWER_LOSS_CAMPAIGN",
            },
        )


if __name__ == "__main__":
    unittest.main()
