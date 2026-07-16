from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FW = ROOT / "firmware"
TOOL = ROOT / "tools/wdc_bundle_tool.py"
MANIFEST = ROOT / "examples/bundles/relay-controller/manifest.json"
STATIC_WASM = FW / "components/wdc_runtime/test_vectors/wdc_static_hello_wasm.wasm"


class R9ProductionHardeningTests(unittest.TestCase):
    def test_r9_version_and_bundle_policy_symbols(self) -> None:
        abi = (FW / "components/wdc_abi/include/wdc_abi.h").read_text(encoding="utf-8")
        for token in [
            'WDC_R9_SHELL_VERSION   "0.1.0-r9"',
            'WDC_R9_BUILD_STAGE     "R9"',
            "WDC_CURRENT_SHELL_VERSION WDC_R9_SHELL_VERSION",
            "WDC_CURRENT_BUILD_STAGE   WDC_R9_BUILD_STAGE",
        ]:
            self.assertIn(token, abi)

        header = (FW / "components/wdc_bundle/include/wdc_bundle.h").read_text(encoding="utf-8")
        for token in [
            "WDC_BUNDLE_SIG_ED25519",
            "WDC_BUNDLE_ED25519_SIGNATURE_BYTES",
            "WdcBundleSignatureVerifyFn",
            "wdc_bundle_make_default_production_policy",
            "required_signature_alg",
            "trusted_signature_key_id",
        ]:
            self.assertIn(token, header)

        source = (FW / "components/wdc_bundle/wdc_bundle.c").read_text(encoding="utf-8")
        for token in [
            "manifest_signature_alg_matches_header",
            "manifest signature algorithm not allowed by policy",
            "manifest signature key id not trusted by policy",
            "local_policy.signature_verify",
            "WDC_BUNDLE_SIG_ED25519",
        ]:
            self.assertIn(token, source)

    def test_r9_bundle_tool_production_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            dev_bundle = tmp_path / "dev.wdcb"
            prod_bundle = tmp_path / "prod.wdcb"
            subprocess.run(
                [str(TOOL), "pack", "--manifest", str(MANIFEST), "--payload", str(STATIC_WASM), "--out", str(dev_bundle)],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    str(TOOL),
                    "pack",
                    "--manifest",
                    str(MANIFEST),
                    "--payload",
                    str(STATIC_WASM),
                    "--out",
                    str(prod_bundle),
                    "--production-test",
                    "--key-id",
                    "prod-test-r9",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
            )

            dev_report = json.loads(
                subprocess.run(
                    [str(TOOL), "inspect", "--bundle", str(dev_bundle)],
                    cwd=ROOT,
                    check=True,
                    text=True,
                    capture_output=True,
                ).stdout
            )
            self.assertEqual(dev_report["status"], "PASS")
            self.assertEqual(dev_report["header"]["signature_alg_name"], "hmac-sha256-dev")

            dev_prod_report = json.loads(
                subprocess.run(
                    [str(TOOL), "inspect", "--bundle", str(dev_bundle), "--production", "--allow-fail"],
                    cwd=ROOT,
                    check=True,
                    text=True,
                    capture_output=True,
                ).stdout
            )
            self.assertEqual(dev_prod_report["status"], "FAIL")
            self.assertFalse(dev_prod_report["checks"]["signature_ok"])

            no_verifier_report = json.loads(
                subprocess.run(
                    [str(TOOL), "inspect", "--bundle", str(prod_bundle), "--production", "--allow-fail"],
                    cwd=ROOT,
                    check=True,
                    text=True,
                    capture_output=True,
                ).stdout
            )
            self.assertEqual(no_verifier_report["status"], "FAIL")
            self.assertEqual(no_verifier_report["header"]["signature_alg_name"], "ed25519")
            self.assertFalse(no_verifier_report["checks"]["signature_ok"])

            prod_report = json.loads(
                subprocess.run(
                    [
                        str(TOOL),
                        "inspect",
                        "--bundle",
                        str(prod_bundle),
                        "--production",
                        "--test-production-verifier",
                    ],
                    cwd=ROOT,
                    check=True,
                    text=True,
                    capture_output=True,
                ).stdout
            )
            self.assertEqual(prod_report["status"], "PASS")
            self.assertEqual(prod_report["header"]["signature_len"], 64)
            self.assertEqual(prod_report["manifest"]["signature"]["key_id"], "prod-test-r9")

            corrupted = bytearray(prod_bundle.read_bytes())
            corrupted[-1] ^= 0x01
            corrupt_path = tmp_path / "prod-corrupt.wdcb"
            corrupt_path.write_bytes(corrupted)
            corrupt_report = json.loads(
                subprocess.run(
                    [
                        str(TOOL),
                        "inspect",
                        "--bundle",
                        str(corrupt_path),
                        "--production",
                        "--test-production-verifier",
                        "--allow-fail",
                    ],
                    cwd=ROOT,
                    check=True,
                    text=True,
                    capture_output=True,
                ).stdout
            )
            self.assertEqual(corrupt_report["status"], "FAIL")
            self.assertFalse(corrupt_report["checks"]["signature_ok"])


if __name__ == "__main__":
    unittest.main()
