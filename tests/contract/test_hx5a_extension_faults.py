from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools import qualify_extension_faults


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_TRANSITIONS = {
    "services-bind-return",
    "init-return",
    "start-return",
    "health-return",
    "invoke-return",
    "quiesce-return",
    "quiesce-health-return",
    "deinit-return",
    "unload-return",
}
EXPECTED_CASES = {
    "bind-failure-is-retryable",
    "init-failure-reverse-unwind",
    "start-failure-reverse-unwind",
    "health-probation-failure-requires-reset",
    "invoke-fault-requires-reset",
    "quiesce-fault-requires-reset",
    "quiesce-health-fault-requires-reset",
    "deinit-fault-requires-reset",
    "partial-unload-fault-requires-reset",
    "invalid-state-is-not-budget",
    "capacity-failure-is-budget",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class HX5aExtensionFaultTests(unittest.TestCase):
    def test_deterministic_injection_executes_every_transition(self) -> None:
        compiler = shutil.which("cc")
        self.assertIsNotNone(compiler, "host C compiler is required for HX5a")
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "hx5a-fault-injection-smoke"
            build = subprocess.run(
                qualify_extension_faults._fault_compile_command(compiler, executable),
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
        self.assertEqual(report["transition_count"], len(EXPECTED_TRANSITIONS))
        self.assertEqual(
            {item["name"] for item in report["cases"]}, EXPECTED_CASES
        )
        self.assertEqual(
            {item["name"] for item in report["transitions"]},
            EXPECTED_TRANSITIONS,
        )
        self.assertTrue(
            all(item["status"] == "PASS" for item in report["cases"])
        )
        self.assertTrue(
            all(item["status"] == "PASS" for item in report["transitions"])
        )

    def test_fault_seam_is_private_and_absent_from_production_translation_unit(self) -> None:
        compiler = shutil.which("cc")
        self.assertIsNotNone(compiler)
        public_abi = (ROOT / "native-sdk/c/include/pulse_extension.h").read_text(
            encoding="utf-8"
        )
        public_host = (
            ROOT / "firmware/components/wdc_extension/include/wdc_extension.h"
        ).read_text(encoding="utf-8")
        internal = (
            ROOT / "firmware/components/wdc_extension/wdc_extension_internal.h"
        ).read_text(encoding="utf-8")
        self.assertNotIn("WdcExtensionTestFault", public_abi)
        self.assertNotIn("WdcExtensionTestFault", public_host)
        self.assertIn("#ifdef PULSE_EXTENSION_HOST_TEST", internal)
        self.assertIn("wdc_extension_test_fault_arm", internal)
        with tempfile.TemporaryDirectory() as temporary:
            preprocessed = Path(temporary) / "lifecycle.i"
            preprocess = subprocess.run(
                [
                    compiler,
                    "-E",
                    "-std=c11",
                    "-Inative-sdk/c/include",
                    "-Ifirmware/components/wdc_extension/include",
                    "-Ifirmware/components/wdc_extension",
                    "-Ifirmware/components/wdc_elf/include",
                    "firmware/components/wdc_extension/wdc_extension_lifecycle.c",
                    "-o",
                    str(preprocessed),
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(preprocess.returncode, 0, preprocess.stdout)
            production_unit = preprocessed.read_text(encoding="utf-8")
            self.assertNotIn("wdc_extension_test_fault_", production_unit)
            self.assertNotIn("WDC_EXTENSION_TEST_FAULT_", production_unit)

    def test_concrete_cleanup_gaps_are_fail_closed(self) -> None:
        source = (
            ROOT / "firmware/components/wdc_extension/wdc_extension_lifecycle.c"
        ).read_text(encoding="utf-8")
        header = (
            ROOT / "firmware/components/wdc_extension/include/wdc_extension.h"
        ).read_text(encoding="utf-8")
        state_check = source.split(
            "for (index = 0u; index < registry->count; ++index)", 1
        )[1]
        self.assertIn("return WDC_EXTENSION_ERR_STATE;", state_check)
        self.assertIn("return WDC_EXTENSION_ERR_BUDGET;", state_check)
        unload = source.split("int32_t wdc_extension_registry_unload_clean", 1)[1]
        self.assertIn("registry->reset_required = 1u", unload)
        self.assertIn("candidate->state = WDC_EXTENSION_RESET_REQUIRED", unload)
        self.assertIn("return WDC_EXTENSION_ERR_RESET_REQUIRED", unload)
        self.assertIn("WDC_EXTENSION_FAULT_UNLOAD", header)

    def test_unified_report_reexecutes_and_hashes_all_corpora(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "hx5a"
            report = qualify_extension_faults.qualify(out)
            self.assertEqual(report["schema"], "pulse.esp32.host-extension-report.v1")
            self.assertEqual(report["pass"], "HX5a")
            self.assertEqual(report["phase"], "FAULT_MODEL_HARDENED")
            self.assertEqual(report["aggregate"], "HOST_HARDENING_PROVEN")
            self.assertEqual(report["coverage"]["executed_case_count"], 56)
            self.assertEqual(report["coverage"]["transition_count"], 9)
            self.assertTrue(report["coverage"]["all_categories_covered"])
            self.assertEqual(report["hardware"]["execution_this_pass"], "NOT_RUN")
            self.assertEqual(
                {item["prior_classification"] for item in report["hardware"]["baselines"]},
                {"NAMED_BOARD_OBSERVED"},
            )
            self.assertTrue((out / "qualification-report.md").is_file())
            for artifact in report["evidence"].values():
                path = out / artifact["path"]
                self.assertTrue(path.is_file())
                self.assertEqual(digest(path), artifact["sha256"])
            for corpus in report["corpora"].values():
                artifact = corpus["artifact"]
                path = out / artifact["path"]
                self.assertTrue(path.is_file())
                self.assertEqual(digest(path), artifact["sha256"])

    def test_model_docs_make_and_runner_freeze_hx5a_scope(self) -> None:
        model = json.loads(
            (ROOT / "specs/PULSE-ESP32-005a-extension-fault-model.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(model["pass"], "HX5a")
        self.assertEqual(model["phase"], "FAULT_MODEL_HARDENED")
        self.assertEqual(
            {item["id"] for item in model["transitions"]}, EXPECTED_TRANSITIONS
        )
        self.assertEqual(len(model["categories"]), 6)
        deferred = " ".join(model["deferred_to_hx5b"]).lower()
        self.assertIn("saturation", deferred)
        self.assertIn("hardware reruns", deferred)
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        runner = (ROOT / "tools/run_contract_tests.py").read_text(encoding="utf-8")
        docs = (ROOT / "docs/HX5A_EXTENSION_FAULT_HARDENING.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("check-hx5a", makefile)
        self.assertIn("host-extension-faults-qualify", makefile)
        self.assertIn("tests.contract.test_hx5a_extension_faults", runner)
        self.assertIn("No new host capability", docs)
        self.assertIn("HX5b", docs)


if __name__ == "__main__":
    unittest.main()
