from __future__ import annotations

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools import check_idf_matrix, host_build_contract, qualify_host_build


ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "firmware/host-build-catalog.json"
INTENT_PATH = ROOT / "examples/host-intents/portable-loopback-v1.json"
GENERATED_C = (
    ROOT
    / "firmware/components/wdc_host_identity/wdc_host_fingerprint_generated.c"
)
BOARD_IDS = (
    "aitrip-esp32s3-devkitc-1-n8r2",
    "seeed-xiao-esp32c6-4m",
)


class HP2HostBuildCoherenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = host_build_contract.load_json(CATALOG_PATH)
        self.intent = host_build_contract.load_json(INTENT_PATH)
        self.resolved = host_build_contract.validate_catalog(self.catalog)

    def _lock_and_fingerprint(
        self, board_id: str
    ) -> tuple[dict[str, object], dict[str, object]]:
        entry = self.resolved[board_id]["entry"]
        return (
            host_build_contract.load_json(ROOT / entry["build_lock"]),
            host_build_contract.load_json(ROOT / entry["fingerprint"]),
        )

    def test_six_artifact_classes_remain_separate(self) -> None:
        self.assertEqual(self.catalog["schema"], host_build_contract.CATALOG_SCHEMA)
        self.assertEqual(set(self.resolved), set(BOARD_IDS))
        self.assertEqual(self.intent["schema"], host_build_contract.INTENT_SCHEMA)
        for board_id in BOARD_IDS:
            selected = self.resolved[board_id]
            entry = selected["entry"]
            board = selected["board"]
            profile = selected["profile"]
            self.assertEqual(board["schema"], host_build_contract.BOARD_SCHEMA)
            self.assertEqual(profile["schema"], host_build_contract.PROFILE_SCHEMA)
            self.assertNotEqual(board["board_id"], profile["profile_id"])
            self.assertNotEqual(entry["board"], entry["host_profile"])
            plan = host_build_contract.make_plan(
                self.intent, board_id, self.catalog
            )
            lock, fingerprint = self._lock_and_fingerprint(board_id)
            self.assertEqual(plan["schema"], host_build_contract.PLAN_SCHEMA)
            self.assertEqual(lock["schema"], host_build_contract.LOCK_SCHEMA)
            self.assertEqual(
                fingerprint["schema"], host_build_contract.FINGERPRINT_SCHEMA
            )
            self.assertNotIn("intent", lock)
            self.assertNotIn("application_id", fingerprint)

    def test_target_intent_has_no_host_build_implementation_vocabulary(self) -> None:
        normalized = json.dumps(self.intent, sort_keys=True).lower()
        for forbidden in ("esp-idf", "sdkconfig", "partition", "psram", "loader"):
            self.assertNotIn(forbidden, normalized)
        host_build_contract.validate_intent(self.intent)
        self.assertEqual(self.intent["placement"], "portable")
        self.assertEqual(self.intent["resources"]["target_optimization_bytes"], 0)

    def test_host_plan_is_application_independent(self) -> None:
        changed = copy.deepcopy(self.intent)
        changed["intent_id"] = "portable-loopback-variant-v1"
        changed["application_id"] = "pulse.example.portable-loopback-variant"
        changed["resources"]["capability_working_bytes"] = 8192
        for board_id in BOARD_IDS:
            first = host_build_contract.make_plan(self.intent, board_id, self.catalog)
            second = host_build_contract.make_plan(changed, board_id, self.catalog)
            self.assertNotEqual(first["plan_sha256"], second["plan_sha256"])
            self.assertEqual(first["host_plan"], second["host_plan"])
            self.assertEqual(first["host_plan_sha256"], second["host_plan_sha256"])
            lock, _ = self._lock_and_fingerprint(board_id)
            self.assertEqual(lock["host_plan_sha256"], first["host_plan_sha256"])

    def test_exact_locks_replay_without_resolution_or_silent_upgrade(self) -> None:
        lock_hashes = set()
        fingerprint_hashes = set()
        for board_id in BOARD_IDS:
            lock, fingerprint = self._lock_and_fingerprint(board_id)
            replayed = host_build_contract.replay_lock(lock, fingerprint)
            self.assertEqual(replayed, fingerprint)
            lock_hashes.add(fingerprint["build_lock_sha256"])
            fingerprint_hashes.add(fingerprint["fingerprint_sha256"])
            self.assertEqual(lock["environment"], self.catalog["lane"])
            self.assertEqual(lock["resolved_components"], self.catalog["components"])
        self.assertEqual(len(lock_hashes), 2)
        self.assertEqual(len(fingerprint_hashes), 2)

        drifted_catalog = copy.deepcopy(self.catalog)
        drifted_catalog["lane"]["version"] = "v5.5.0"
        with self.assertRaises(host_build_contract.HostBuildContractError):
            host_build_contract.make_plan(
                self.intent, "seeed-xiao-esp32c6-4m", drifted_catalog
            )
        # Existing locks replay directly and do not consult a changed catalog.
        c6_lock, c6_fingerprint = self._lock_and_fingerprint(
            "seeed-xiao-esp32c6-4m"
        )
        self.assertEqual(
            host_build_contract.replay_lock(c6_lock), c6_fingerprint
        )

    def test_running_fingerprint_selects_app_only_or_explicit_host_plan(self) -> None:
        for board_id in BOARD_IDS:
            _, fingerprint = self._lock_and_fingerprint(board_id)
            result = host_build_contract.check_running(self.intent, fingerprint)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["deployment"], "APP_ONLY_DEPLOYMENT")
            self.assertFalse(result["application_code_launched"])
            plan = host_build_contract.make_plan(
                self.intent,
                board_id,
                self.catalog,
                running_fingerprint=fingerprint,
            )
            self.assertEqual(
                plan["selection"]["deployment"], "APP_ONLY_DEPLOYMENT"
            )

        _, s3_fingerprint = self._lock_and_fingerprint(
            "aitrip-esp32s3-devkitc-1-n8r2"
        )
        c6_plan = host_build_contract.make_plan(
            self.intent,
            "seeed-xiao-esp32c6-4m",
            self.catalog,
            running_fingerprint=s3_fingerprint,
        )
        self.assertEqual(
            c6_plan["selection"]["deployment"], "HOST_BUILD_PLAN_REQUIRED"
        )

    def test_c6_minimum_and_s3_optimization_do_not_change_portable_semantics(self) -> None:
        optimized = copy.deepcopy(self.intent)
        optimized["placement"] = "target-optimized"
        optimized["resources"]["target_optimization_bytes"] = 262144
        _, c6 = self._lock_and_fingerprint("seeed-xiao-esp32c6-4m")
        _, s3 = self._lock_and_fingerprint("aitrip-esp32s3-devkitc-1-n8r2")
        c6_result = host_build_contract.check_running(optimized, c6)
        s3_result = host_build_contract.check_running(optimized, s3)
        self.assertEqual(c6_result["status"], "FAIL")
        self.assertIn(
            "TARGET_OPTIMIZATION_UNAVAILABLE",
            c6_result["compatibility"]["reasons"],
        )
        self.assertFalse(c6_result["application_code_launched"])
        self.assertEqual(s3_result["status"], "PASS")
        self.assertEqual(s3_result["deployment"], "APP_ONLY_DEPLOYMENT")

    def test_tampering_fails_before_replay_or_application_launch(self) -> None:
        lock, fingerprint = self._lock_and_fingerprint(
            "seeed-xiao-esp32c6-4m"
        )
        tampered_lock = copy.deepcopy(lock)
        tampered_lock["inputs"][0]["sha256"] = "0" * 64
        with self.assertRaises(host_build_contract.HostBuildContractError):
            host_build_contract.replay_lock(tampered_lock)
        tampered_fingerprint = copy.deepcopy(fingerprint)
        tampered_fingerprint["compatibility_surface"]["capability_mask"] = 1
        with self.assertRaises(host_build_contract.HostBuildContractError):
            host_build_contract.validate_fingerprint(tampered_fingerprint)

        with tempfile.TemporaryDirectory() as temp_name:
            temp = Path(temp_name)
            plan_path = temp / "plan.json"
            output_lock = temp / "existing-lock.json"
            output_fingerprint = temp / "fingerprint.json"
            plan = host_build_contract.make_plan(
                self.intent, "seeed-xiao-esp32c6-4m", self.catalog
            )
            plan_path.write_text(
                json.dumps(plan, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            output_lock.write_text("preserve-me\n", encoding="utf-8")
            process = subprocess.run(
                [
                    "python3",
                    "-B",
                    "tools/resolve_host_build.py",
                    "resolve-new-lock",
                    "--plan",
                    str(plan_path),
                    "--out-lock",
                    str(output_lock),
                    "--out-fingerprint",
                    str(output_fingerprint),
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(process.returncode, 1)
            self.assertEqual(output_lock.read_text(encoding="utf-8"), "preserve-me\n")
            self.assertFalse(output_fingerprint.exists())

    def test_board_realizations_match_named_hardware_inputs(self) -> None:
        pairs = (
            (
                "aitrip-esp32s3-devkitc-1-n8r2",
                "hx45-s3-aitrip-n8r2",
            ),
            (
                "seeed-xiao-esp32c6-4m",
                "hx45-c6-seeed-xiao-4m",
            ),
        )
        for board_id, hil_id in pairs:
            canonical = ROOT / "firmware/boards" / board_id
            hil = ROOT / "tests/hardware-in-loop" / hil_id
            self.assertEqual(
                check_idf_matrix.parse_sdkconfig_defaults(
                    canonical / "sdkconfig.defaults"
                ),
                check_idf_matrix.parse_sdkconfig_defaults(
                    hil / "sdkconfig.defaults"
                ),
            )
            canonical_rows = [
                "".join(line.split())
                for line in (canonical / "partitions.csv")
                .read_text(encoding="utf-8")
                .splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            ]
            hil_rows = [
                "".join(line.split())
                for line in (hil / "partitions.csv")
                .read_text(encoding="utf-8")
                .splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            ]
            self.assertEqual(canonical_rows[:3], hil_rows)
            self.assertEqual(len(canonical_rows), 6)
            self.assertTrue(canonical_rows[3].startswith("wasm_a,"))
            self.assertTrue(canonical_rows[4].startswith("wasm_b,"))
            self.assertTrue(canonical_rows[5].startswith("wasm_meta,"))

    def test_generated_c_and_native_smoke_are_exact(self) -> None:
        self.assertEqual(
            GENERATED_C.read_text(encoding="utf-8"),
            host_build_contract.render_generated_c(self.catalog),
        )
        with tempfile.TemporaryDirectory() as temp_name:
            executable = Path(temp_name) / "hp2-smoke"
            command = [
                "cc",
                "-std=c11",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-DWDC_HOST_TEST_TARGET_C6=1",
                "-Ifirmware/components/wdc_abi/include",
                "-Ifirmware/components/wdc_control/include",
                "-Ifirmware/components/wdc_host_identity/include",
                "tests/contract/hp2_host_identity_smoke.c",
                "firmware/components/wdc_control/wdc_control.c",
                "firmware/components/wdc_host_identity/wdc_host_identity.c",
                "firmware/components/wdc_host_identity/wdc_host_fingerprint_generated.c",
                "-o",
                str(executable),
            ]
            subprocess.run(command, cwd=ROOT, check=True)
            result = subprocess.run(
                [str(executable)],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                check=True,
            )
        smoke = json.loads(result.stdout)
        self.assertEqual(smoke["status"], "PASS")
        self.assertEqual(smoke["case_count"], 8)
        self.assertEqual(smoke["failures"], 0)
        self.assertFalse(smoke["application_code_launched"])

    def test_generated_c_selects_esp_idf_running_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            temp = Path(temp_name)
            (temp / "sdkconfig.h").write_text(
                "#define CONFIG_IDF_TARGET_ESP32S3 1\n", encoding="utf-8"
            )
            (temp / "target_probe.c").write_text(
                """#include "wdc_host_identity.h"

int main(void)
{
    const WdcHostFingerprintV1 *fingerprint =
        wdc_host_running_fingerprint();
    return fingerprint != 0 &&
                   fingerprint->target == WDC_HOST_TARGET_ESP32S3
               ? 0
               : 1;
}
""",
                encoding="utf-8",
            )
            executable = temp / "target-probe"
            command = [
                "cc",
                "-std=c11",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-DESP_PLATFORM=1",
                f"-I{temp}",
                "-Ifirmware/components/wdc_abi/include",
                "-Ifirmware/components/wdc_control/include",
                "-Ifirmware/components/wdc_host_identity/include",
                str(temp / "target_probe.c"),
                "firmware/components/wdc_host_identity/wdc_host_fingerprint_generated.c",
                "-o",
                str(executable),
            ]
            subprocess.run(command, cwd=ROOT, check=True)
            subprocess.run([str(executable)], cwd=ROOT, check=True)

    def test_qualifier_make_runner_docs_and_preserved_seals(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            report = qualify_host_build.qualify(Path(temp_name), "cc")
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["aggregate"], "HOST_BUILD_COHERENCE_PROVEN")
        self.assertEqual(report["coverage"]["negative_cases"], 8)
        self.assertEqual(
            report["claim_boundary"]["hardware_execution_this_pass"],
            "NOT_RUN",
        )
        self.assertEqual(
            report["claim_boundary"]["external_provider"], "NOT_IMPLEMENTED"
        )
        self.assertEqual(
            host_build_contract.sha256_file(
                ROOT / "native-sdk/c/include/pulse_extension.h"
            ),
            "e92aaae33b4016f5e3d1ac41f34fac0b19569c7f0bbabba6ce3d4e2604f6e023",
        )
        self.assertEqual(
            host_build_contract.sha256_file(
                ROOT
                / "firmware/components/wdc_runtime/test_vectors/wdc_hx4_event_effect_wasm.wasm"
            ),
            "ef8b21a4b7a423923c09f5e38fc626ff7d1cda856c4935db7f191695a333e5c4",
        )
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        runner = (ROOT / "tools/run_contract_tests.py").read_text(encoding="utf-8")
        docs = (ROOT / "docs/HP2_HOST_BUILD_COHERENCE.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("check-hp2", makefile)
        self.assertIn("host-build-qualify", makefile)
        self.assertIn("tests.contract.test_hp2_host_build_coherence", runner)
        self.assertIn("APP_ONLY_DEPLOYMENT", docs)
        self.assertIn("HOST_BUILD_PLAN_REQUIRED", docs)


if __name__ == "__main__":
    unittest.main()
