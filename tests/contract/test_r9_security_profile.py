from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FW = ROOT / "firmware"
ABI = FW / "components/wdc_abi"
BUNDLE = FW / "components/wdc_bundle"
CAPS = FW / "components/wdc_caps"
PROFILE = FW / "components/wdc_profile"
DIAG = FW / "components/wdc_diag"
SECURITY = FW / "components/wdc_security"


def compile_and_run_r9_smoke() -> None:
    gcc = shutil.which("gcc")
    if gcc is None:
        raise unittest.SkipTest("gcc unavailable")
    with tempfile.TemporaryDirectory() as tmp:
        exe = Path(tmp) / "r9_security_diag_smoke"
        include_dirs = [
            ABI / "include",
            BUNDLE / "include",
            CAPS / "include",
            PROFILE / "include",
            DIAG / "include",
            SECURITY / "include",
        ]
        sources = [
            ABI / "wdc_errors.c",
            ABI / "wdc_cbor.c",
            ABI / "wdc_host_call.c",
            BUNDLE / "wdc_bundle.c",
            CAPS / "wdc_caps.c",
            PROFILE / "wdc_profile_static.c",
            DIAG / "wdc_diag.c",
            SECURITY / "wdc_security.c",
            ROOT / "tests/firmware-unit/r9_security_diag_smoke.c",
        ]
        cmd = [gcc, "-std=c11", "-Wall", "-Wextra", "-Werror"]
        for inc in include_dirs:
            cmd.extend(["-I", str(inc)])
        cmd.extend(str(src) for src in sources)
        cmd.extend(["-o", str(exe)])
        subprocess.run(cmd, cwd=ROOT, check=True, text=True, capture_output=True)
        subprocess.run([str(exe)], cwd=ROOT, check=True, text=True, capture_output=True)


class R9SecurityProfileTests(unittest.TestCase):
    def test_security_profile_symbols(self) -> None:
        config = (FW / "main/shell_config.h").read_text(encoding="utf-8")
        for token in [
            'WDC_SHELL_VERSION     "0.1.0-r9"',
            'WDC_SHELL_BUILD_STAGE "R9"',
            "WDC_BUILD_PROFILE_PROD 1",
            "WDC_R9_PRODUCTION_SIGNATURE_POLICY 1",
            "WDC_R9_REQUIRE_PRODUCTION_VERIFIER_CALLBACK 1",
            "WDC_R9_PRODUCTION_SECURITY_PROFILE 1",
        ]:
            self.assertIn(token, config)

        security_h = (SECURITY / "include/wdc_security.h").read_text(encoding="utf-8")
        for token in [
            "WdcSecurityPolicy",
            "WdcProvisioningRecord",
            "WdcSecurityPreflightReport",
            "wdc_security_production_policy",
            "wdc_security_development_policy",
            "wdc_security_make_bundle_verify_policy",
            "wdc_security_validate_bundle_result",
            "wdc_security_validate_provisioning",
            "wdc_security_metadata_security_floor",
            "wdc_security_reset_reason_is_watchdog",
            "wdc_security_log_rejection",
            "WDC_SECURITY_DEFAULT_PROD_SIGNATURE_ALG",
        ]:
            self.assertIn(token, security_h)

        security_c = (SECURITY / "wdc_security.c").read_text(encoding="utf-8")
        for token in [
            "require_secure_bundle_signature = true",
            "reject_dev_signature = true",
            "anti_rollback_enabled = true",
            "effectful_self_tests_allowed = false",
            "serial_install_allowed = false",
            "profile_mutation_allowed = false",
            "verify.required_signature_alg",
            "wdc_security_metadata_security_floor",
        ]:
            self.assertIn(token, security_c)

    def test_diagnostics_and_event_policy_symbols(self) -> None:
        diag_h = (DIAG / "include/wdc_diag.h").read_text(encoding="utf-8")
        for token in [
            "WdcDiagResetClass",
            "WdcDiagBreadcrumb",
            "wdc_diag_classify_reset",
            "wdc_diag_record_breadcrumb",
            "wdc_diag_get_breadcrumb",
            "wdc_diag_export_json",
        ]:
            self.assertIn(token, diag_h)

        safety_c = (FW / "components/wdc_safety/wdc_safety.c").read_text(encoding="utf-8")
        self.assertIn("wdc_diag_record_breadcrumb", safety_c)
        self.assertIn("denied_by_rate_limit_count", safety_c)

        events_h = (FW / "components/wdc_events/include/wdc_events.h").read_text(encoding="utf-8")
        for token in ["WdcEventOverflowPolicy", "WDC_EVENT_OVERFLOW_DROP_NEWEST", "wdc_events_get_stats"]:
            self.assertIn(token, events_h)

    def test_native_security_diag_smoke(self) -> None:
        compile_and_run_r9_smoke()


if __name__ == "__main__":
    unittest.main()
