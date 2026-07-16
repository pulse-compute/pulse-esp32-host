#!/usr/bin/env python3
"""R9 production hardening acceptance gate."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FW = ROOT / "firmware"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def files_and_symbols_check() -> dict[str, object]:
    required = [
        "firmware/components/wdc_security/include/wdc_security.h",
        "firmware/components/wdc_security/wdc_security.c",
        "firmware/components/wdc_security/CMakeLists.txt",
        "firmware/components/wdc_diag/include/wdc_diag.h",
        "firmware/components/wdc_diag/wdc_diag.c",
        "firmware/components/wdc_safety/wdc_safety.c",
        "firmware/components/wdc_events/include/wdc_events.h",
        "tests/firmware-unit/r9_security_diag_smoke.c",
        "tests/contract/test_r9_security_profile.py",
        "tests/contract/test_r9_production_hardening.py",
        "tools/wdc_bundle_tool.py",
    ]
    missing = [rel for rel in required if not (ROOT / rel).exists()]
    require(not missing, "missing R9 files: " + ", ".join(missing))

    config = (FW / "main/shell_config.h").read_text(encoding="utf-8")
    for token in [
        'WDC_SHELL_VERSION     "0.1.0-r9"',
        'WDC_SHELL_BUILD_STAGE "R9"',
        "WDC_BUILD_PROFILE_PROD 1",
        "WDC_ENABLE_EFFECTFUL_SELF_TESTS 0",
        "WDC_R9_PRODUCTION_SIGNATURE_POLICY 1",
        "WDC_R9_REQUIRE_PRODUCTION_VERIFIER_CALLBACK 1",
        "WDC_R9_PRODUCTION_SECURITY_PROFILE 1",
    ]:
        require(token in config, f"missing shell-config token: {token}")

    abi = (FW / "components/wdc_abi/include/wdc_abi.h").read_text(encoding="utf-8")
    for token in [
        'WDC_R9_SHELL_VERSION   "0.1.0-r9"',
        'WDC_R9_BUILD_STAGE     "R9"',
        "WDC_CURRENT_SHELL_VERSION WDC_R9_SHELL_VERSION",
        "WDC_CURRENT_BUILD_STAGE   WDC_R9_BUILD_STAGE",
    ]:
        require(token in abi, f"missing ABI token: {token}")

    expectations = {
        "firmware/components/wdc_security/include/wdc_security.h": [
            "WdcSecurityPolicy",
            "WdcProvisioningRecord",
            "WdcSecurityPreflightReport",
            "wdc_security_production_policy",
            "wdc_security_make_bundle_verify_policy",
            "wdc_security_validate_bundle_result",
            "wdc_security_validate_provisioning",
            "wdc_security_metadata_security_floor",
            "wdc_security_reset_reason_is_watchdog",
        ],
        "firmware/components/wdc_security/wdc_security.c": [
            "require_secure_bundle_signature = true",
            "reject_dev_signature = true",
            "anti_rollback_enabled = true",
            "effectful_self_tests_allowed = false",
            "serial_install_allowed = false",
            "verify.required_signature_alg",
        ],
        "firmware/components/wdc_bundle/include/wdc_bundle.h": [
            "WDC_BUNDLE_SIG_ED25519",
            "WDC_BUNDLE_ED25519_SIGNATURE_BYTES",
            "WdcBundleSignatureVerifyFn",
            "required_signature_alg",
            "trusted_signature_key_id",
        ],
        "firmware/components/wdc_bundle/wdc_bundle.c": [
            "manifest_signature_alg_matches_header",
            "manifest signature algorithm not allowed by policy",
            "manifest signature key id not trusted by policy",
            "local_policy.signature_verify",
            "WDC_BUNDLE_SIG_ED25519",
        ],
        "firmware/components/wdc_diag/include/wdc_diag.h": [
            "WdcDiagResetClass",
            "WdcDiagBreadcrumb",
            "wdc_diag_classify_reset",
            "wdc_diag_record_breadcrumb",
            "wdc_diag_export_json",
        ],
        "firmware/components/wdc_safety/wdc_safety.c": [
            "wdc_diag_record_breadcrumb",
            "denied_by_rate_limit_count",
        ],
        "firmware/components/wdc_events/include/wdc_events.h": [
            "WDC_EVENT_OVERFLOW_DROP_NEWEST",
            "WdcEventQueueStats",
            "wdc_events_get_stats",
        ],
        "tools/wdc_bundle_tool.py": [
            "--production-test",
            "--test-production-verifier",
            "SIG_ED25519",
            "production_test_signature",
        ],
    }
    for rel, tokens in expectations.items():
        text = (ROOT / rel).read_text(encoding="utf-8")
        for token in tokens:
            require(token in text, f"missing token in {rel}: {token}")
    return {"status": "PASS", "missing_files": 0, "symbol_groups": len(expectations) + 2}


def compile_native_smoke() -> dict[str, object]:
    gcc = shutil.which("gcc")
    if gcc is None:
        return {"status": "SKIPPED_ENV", "reason": "gcc unavailable"}

    include_dirs = [
        FW / "components/wdc_abi/include",
        FW / "components/wdc_bundle/include",
        FW / "components/wdc_caps/include",
        FW / "components/wdc_profile/include",
        FW / "components/wdc_diag/include",
        FW / "components/wdc_security/include",
    ]
    sources = [
        FW / "components/wdc_abi/wdc_errors.c",
        FW / "components/wdc_abi/wdc_cbor.c",
        FW / "components/wdc_abi/wdc_host_call.c",
        FW / "components/wdc_bundle/wdc_bundle.c",
        FW / "components/wdc_caps/wdc_caps.c",
        FW / "components/wdc_profile/wdc_profile_static.c",
        FW / "components/wdc_diag/wdc_diag.c",
        FW / "components/wdc_security/wdc_security.c",
        ROOT / "tests/firmware-unit/r9_security_diag_smoke.c",
    ]

    with tempfile.TemporaryDirectory() as tmp:
        exe = Path(tmp) / "r9_security_diag_smoke"
        cmd = [gcc, "-std=c11", "-Wall", "-Wextra", "-Werror"]
        for inc in include_dirs:
            cmd.extend(["-I", str(inc)])
        cmd.extend(str(src) for src in sources)
        cmd.extend(["-o", str(exe)])
        build = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)
        if build.returncode != 0:
            raise RuntimeError("native R9 smoke compile failed:\n" + build.stdout + build.stderr)
        run = subprocess.run([str(exe)], cwd=ROOT, text=True, capture_output=True, check=False, timeout=30)
        if run.returncode != 0:
            raise RuntimeError("native R9 smoke run failed:\n" + run.stdout + run.stderr)
    return {"status": "PASS", "compiler": Path(gcc).name, "smoke": "r9_security_diag_smoke"}


def bundle_tool_production_vector() -> dict[str, object]:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        dev_bundle = tmp_path / "dev.wdcb"
        prod_bundle = tmp_path / "prod-test.wdcb"
        pack_dev = subprocess.run(
            [
                sys.executable,
                "-B",
                "tools/wdc_bundle_tool.py",
                "pack",
                "--manifest",
                "examples/bundles/relay-controller/manifest.json",
                "--payload",
                "firmware/components/wdc_runtime/test_vectors/wdc_static_hello_wasm.wasm",
                "--out",
                str(dev_bundle),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if pack_dev.returncode != 0:
            raise RuntimeError("dev pack failed:\n" + pack_dev.stdout + pack_dev.stderr)
        pack_prod = subprocess.run(
            [
                sys.executable,
                "-B",
                "tools/wdc_bundle_tool.py",
                "pack",
                "--production-test",
                "--manifest",
                "examples/bundles/relay-controller/manifest.json",
                "--payload",
                "firmware/components/wdc_runtime/test_vectors/wdc_static_hello_wasm.wasm",
                "--key-id",
                "prod-test-r9",
                "--out",
                str(prod_bundle),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if pack_prod.returncode != 0:
            raise RuntimeError("production test-vector pack failed:\n" + pack_prod.stdout + pack_prod.stderr)
        fail_dev = subprocess.run(
            [sys.executable, "-B", "tools/wdc_bundle_tool.py", "inspect", "--production", "--allow-fail", "--bundle", str(dev_bundle)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        require(fail_dev.returncode == 0, "dev inspect as production should return allow-fail JSON")
        require(json.loads(fail_dev.stdout).get("status") == "FAIL", "dev HMAC bundle must fail production policy")
        fail = subprocess.run(
            [sys.executable, "-B", "tools/wdc_bundle_tool.py", "inspect", "--production", "--allow-fail", "--bundle", str(prod_bundle)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        require(fail.returncode == 0, "production inspect without verifier should return allow-fail JSON")
        fail_payload = json.loads(fail.stdout)
        require(fail_payload.get("status") == "FAIL", "production inspect without verifier should fail")
        ok = subprocess.run(
            [sys.executable, "-B", "tools/wdc_bundle_tool.py", "inspect", "--production", "--test-production-verifier", "--bundle", str(prod_bundle)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if ok.returncode != 0:
            raise RuntimeError("production inspect with verifier failed:\n" + ok.stdout + ok.stderr)
        ok_payload = json.loads(ok.stdout)
        require(ok_payload.get("status") == "PASS", "production inspect with verifier should pass")
        require(ok_payload.get("header", {}).get("signature_alg_name") == "ed25519", "test vector should use ed25519 container alg")
    return {"status": "PASS", "test_vector": "ed25519-shaped production verifier hook"}


def run_r9_unittests() -> dict[str, object]:
    proc = subprocess.run(
        [sys.executable, "-B", "-m", "unittest", "tests.contract.test_r9_security_profile", "tests.contract.test_r9_production_hardening", "-v"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError("R9 unittest gate failed:\n" + proc.stdout + proc.stderr)
    return {"status": "PASS", "stdout_lines": len(proc.stdout.splitlines()), "stderr_lines": len(proc.stderr.splitlines())}


def main() -> int:
    checks = {
        "files_and_symbols": files_and_symbols_check(),
        "native_security_diag_smoke": compile_native_smoke(),
        "bundle_tool_production_test_vector": bundle_tool_production_vector(),
        "r9_unittests": run_r9_unittests(),
    }
    status = "PASS" if all(v.get("status") == "PASS" for v in checks.values()) else "PARTIAL"
    result = {
        "schema": "wdc.r9.check.v1",
        "milestone": "R9",
        "status": status,
        "checks": checks,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    print("R9 production hardening check passed" if status == "PASS" else "R9 production hardening check partial")
    return 0 if status in {"PASS", "PARTIAL"} else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"R9 check failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
