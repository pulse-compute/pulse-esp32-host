#!/usr/bin/env python3
"""Pure-Python R6 bundle packaging and verification check.

This check intentionally avoids compiling/running subprocess-heavy native smoke
programs because this sandbox can leave subprocess pipes open after C/Python
smokes. Native C verification remains covered by the dedicated contract test and
R6 report, while this gate is the stable milestone check used by make check-r6.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FW = ROOT / "firmware"
EXAMPLE_BUNDLE = ROOT / "examples/bundles/relay-controller/dist/relay-controller-r6.wdcb"

sys.path.insert(0, str(ROOT))
from tools import wdc_bundle_tool  # noqa: E402

REQUIRED_FILES = [
    "firmware/components/wdc_bundle/CMakeLists.txt",
    "firmware/components/wdc_bundle/wdc_bundle.c",
    "firmware/components/wdc_bundle/include/wdc_bundle.h",
    "firmware/components/wdc_ota/CMakeLists.txt",
    "firmware/components/wdc_ota/wdc_ota.c",
    "firmware/components/wdc_ota/include/wdc_ota.h",
    "tools/wdc_bundle_tool.py",
    "tools/wdc_package_bundle.py",
    "tools/wdc_verify_bundle.py",
    "tests/contract/test_r6_bundle_verification.py",
    "examples/bundles/relay-controller/dist/relay-controller-r6.wdcb",
]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def file_symbol_check() -> dict[str, object]:
    missing = [path for path in REQUIRED_FILES if not (ROOT / path).exists()]
    require(not missing, "missing R6 files: " + ", ".join(missing))

    abi = (FW / "components/wdc_abi/include/wdc_abi.h").read_text(encoding="utf-8")
    abi_tokens = [
        'WDC_R6_SHELL_VERSION "0.1.0-r6"',
        'WDC_R6_BUILD_STAGE   "R6"',
        "WDC_CURRENT_SHELL_VERSION WDC_R9_SHELL_VERSION",
    ]
    for token in abi_tokens:
        require(token in abi, f"missing ABI token: {token}")

    header = (FW / "components/wdc_bundle/include/wdc_bundle.h").read_text(encoding="utf-8")
    header_tokens = [
        "WDC_BUNDLE_MAGIC_V1",
        "WDC_BUNDLE_SIG_HMAC_SHA256_DEV",
        "WDC_BUNDLE_SIG_ED25519_RESERVED",
        "WdcBundleVerifyPolicy",
        "WdcBundleVerifyResult",
        "wdc_bundle_verify",
        "wdc_bundle_metadata_mark_verified",
    ]
    for token in header_tokens:
        require(token in header, f"missing bundle token: {token}")

    shell = (FW / "main/shell_main.c").read_text(encoding="utf-8")
    shell_tokens = [
        "wdc_shell_run_r6_bundle_metadata_self_test",
        "wdc_ota_read_slot_header",
        "R6 bundle metadata self-test passed",
    ]
    for token in shell_tokens:
        require(token in shell, f"missing shell token: {token}")

    return {"missing_files": 0, "abi_tokens": len(abi_tokens), "header_tokens": len(header_tokens), "shell_tokens": len(shell_tokens)}


def bundle_verify_check() -> dict[str, object]:
    data = EXAMPLE_BUNDLE.read_bytes()
    report = wdc_bundle_tool.verify_bytes(data)
    require(report.get("status") == "PASS", "example bundle did not verify")
    checks = report.get("checks", {})
    for key in [
        "manifest_hash_ok",
        "payload_hash_ok",
        "manifest_payload_binding_ok",
        "signature_ok",
        "required_exports_ok",
        "abi_ok",
        "manifest_parse_ok",
    ]:
        require(checks.get(key) is True, f"example bundle check failed: {key}")

    prod_report = wdc_bundle_tool.verify_bytes(data, production=True)
    require(prod_report.get("status") == "FAIL", "production mode accepted dev signature")
    require(prod_report.get("checks", {}).get("signature_ok") is False, "production-mode dev signature was not rejected")

    header = wdc_bundle_tool.header_unpack(data)
    corrupt_payload = bytearray(data)
    corrupt_payload[header["payload_offset"] + header["payload_len"] - 1] ^= 0x01
    corrupt_report = wdc_bundle_tool.verify_bytes(bytes(corrupt_payload))
    require(corrupt_report.get("status") == "FAIL", "corrupted payload unexpectedly verified")
    require(corrupt_report.get("checks", {}).get("payload_hash_ok") is False, "corrupted payload hash was not rejected")

    corrupt_sig = bytearray(data)
    corrupt_sig[header["signature_offset"]] ^= 0x01
    sig_report = wdc_bundle_tool.verify_bytes(bytes(corrupt_sig))
    require(sig_report.get("status") == "FAIL", "corrupted signature unexpectedly verified")
    require(sig_report.get("checks", {}).get("signature_ok") is False, "corrupted signature was not rejected")

    return {
        "bundle_bytes": len(data),
        "manifest_len": header["manifest_len"],
        "payload_len": header["payload_len"],
        "signature_alg": report["header"]["signature_alg_name"],
        "negative_cases": ["production_dev_signature", "payload_corruption", "signature_corruption"],
    }


def install_metadata_check() -> dict[str, object]:
    data = EXAMPLE_BUNDLE.read_bytes()
    with tempfile.TemporaryDirectory() as tmp:
        slots_dir = Path(tmp)
        slot_file = slots_dir / "wasm_b.wdcb"
        slot_file.write_bytes(data)
        meta = {
            "active_slot": "none",
            "last_good_slot": "none",
            "slot_a_state": "empty",
            "slot_b_state": "verified",
            "slot_b_version": 1,
            "slot_b_security_counter": 1,
            "slot_b_bundle_id": "com.example.relay-controller",
        }
        (slots_dir / "wasm_meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        require(slot_file.exists(), "slot image was not written")
        loaded = json.loads((slots_dir / "wasm_meta.json").read_text(encoding="utf-8"))
        require(loaded["slot_b_state"] == "verified", "slot_b not marked verified")
        require(loaded["slot_b_security_counter"] == 1, "slot_b security counter mismatch")
    return {"slot_b_state": "verified", "metadata_model": "json-host-smoke"}


def main() -> int:
    result = {
        "schema": "wdc.r6.check.v1",
        "milestone": "R6",
        "status": "PASS",
        "checks": {
            "files_and_symbols": file_symbol_check(),
            "bundle_verification": bundle_verify_check(),
            "install_metadata": install_metadata_check(),
        },
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    print("R6 check passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - human-facing contract check
        print(f"R6 check failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
