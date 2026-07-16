from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FW = ROOT / "firmware"
TOOL = ROOT / "tools/wdc_bundle_tool.py"
MANIFEST = ROOT / "examples/bundles/relay-controller/manifest.json"
STATIC_WASM = FW / "components/wdc_runtime/test_vectors/wdc_static_hello_wasm.wasm"
MISSING_EXPORT_WASM = FW / "components/wdc_runtime/test_vectors/wdc_static_missing_shutdown_wasm.wasm"
EXAMPLE_BUNDLE = ROOT / "examples/bundles/relay-controller/dist/relay-controller-r6.wdcb"


class R6BundleVerificationTests(unittest.TestCase):
    def test_r6_files_and_symbols_exist(self) -> None:
        files = [
            "firmware/components/wdc_bundle/CMakeLists.txt",
            "firmware/components/wdc_bundle/include/wdc_bundle.h",
            "firmware/components/wdc_bundle/wdc_bundle.c",
            "firmware/components/wdc_ota/CMakeLists.txt",
            "firmware/components/wdc_ota/include/wdc_ota.h",
            "firmware/components/wdc_ota/wdc_ota.c",
            "tools/wdc_bundle_tool.py",
            "examples/bundles/relay-controller/dist/relay-controller-r6.wdcb",
        ]
        for rel in files:
            self.assertTrue((ROOT / rel).exists(), rel)

        abi = (FW / "components/wdc_abi/include/wdc_abi.h").read_text(encoding="utf-8")
        for token in [
            'WDC_R6_SHELL_VERSION "0.1.0-r6"',
            'WDC_R6_BUILD_STAGE   "R6"',
            "WDC_CURRENT_SHELL_VERSION WDC_R9_SHELL_VERSION",
        ]:
            self.assertIn(token, abi)

        header = (FW / "components/wdc_bundle/include/wdc_bundle.h").read_text(encoding="utf-8")
        for token in [
            "WDC_BUNDLE_MAGIC_V1",
            "WDC_BUNDLE_SIG_HMAC_SHA256_DEV",
            "WdcBundleVerifyPolicy",
            "WdcBundleVerifyResult",
            "wdc_bundle_verify",
            "wdc_bundle_metadata_mark_verified",
        ]:
            self.assertIn(token, header)

        shell = (FW / "main/shell_main.c").read_text(encoding="utf-8")
        for token in [
            "wdc_shell_run_r6_bundle_metadata_self_test",
            "wdc_ota_read_slot_header",
            "R6 bundle metadata self-test passed",
        ]:
            self.assertIn(token, shell)

    def test_bundle_tool_pack_inspect_install_and_negative_corruption(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bundle = tmp_path / "relay.wdcb"
            manifest_out = tmp_path / "manifest.resolved.json"
            subprocess.run(
                [
                    str(TOOL),
                    "pack",
                    "--manifest",
                    str(MANIFEST),
                    "--payload",
                    str(STATIC_WASM),
                    "--out",
                    str(bundle),
                    "--manifest-out",
                    str(manifest_out),
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
            )
            self.assertTrue(bundle.exists())
            self.assertTrue(manifest_out.exists())

            inspect_json = tmp_path / "inspect.json"
            subprocess.run(
                [str(TOOL), "inspect", "--bundle", str(bundle), "--json-out", str(inspect_json)],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
            )
            report = json.loads(inspect_json.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "PASS")
            self.assertTrue(report["checks"]["signature_ok"])
            self.assertTrue(report["checks"]["required_exports_ok"])
            self.assertEqual(report["header"]["signature_alg_name"], "hmac-sha256-dev")

            slots = tmp_path / "slots"
            subprocess.run(
                [str(TOOL), "install", "--bundle", str(bundle), "--slot", "b", "--slots-dir", str(slots)],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
            )
            meta = json.loads((slots / "wasm_meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["slot_b_state"], "verified")
            self.assertEqual(meta["slot_b_version"], json.loads(manifest_out.read_text(encoding="utf-8"))["bundle_version"])

            corrupted = bytearray(bundle.read_bytes())
            # Flip the last payload byte, not the signature, using the known R6 header layout.
            header_len = 120
            manifest_len = int.from_bytes(corrupted[12:16], "little")
            payload_len = int.from_bytes(corrupted[16:20], "little")
            self.assertGreater(payload_len, 0)
            corrupted[header_len + manifest_len + payload_len - 1] ^= 0x01
            corrupt_path = tmp_path / "corrupt.wdcb"
            corrupt_path.write_bytes(corrupted)
            result = subprocess.run(
                [str(TOOL), "inspect", "--bundle", str(corrupt_path), "--allow-fail"],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
            )
            corrupt_report = json.loads(result.stdout)
            self.assertEqual(corrupt_report["status"], "FAIL")
            self.assertFalse(corrupt_report["checks"]["payload_hash_ok"])

    def test_r6_native_bundle_verification_smoke(self) -> None:
        if shutil.which("gcc") is None:
            self.skipTest("gcc not available")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bad_export = tmp_path / "missing-export.wdcb"
            subprocess.run(
                [
                    str(TOOL),
                    "pack",
                    "--manifest",
                    str(MANIFEST),
                    "--payload",
                    str(MISSING_EXPORT_WASM),
                    "--out",
                    str(bad_export),
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
            )

            program = textwrap.dedent(
                r'''
                #include <assert.h>
                #include <stdint.h>
                #include <stdio.h>
                #include <stdlib.h>
                #include <string.h>
                #include "wdc_abi.h"
                #include "wdc_bundle.h"
                #include "wdc_ota.h"
                #include "wdc_profile.h"

                static uint8_t *read_file(const char *path, uint32_t *out_len) {
                    FILE *f = fopen(path, "rb");
                    assert(f != NULL);
                    assert(fseek(f, 0, SEEK_END) == 0);
                    long n = ftell(f);
                    assert(n > 0 && n < 1000000);
                    assert(fseek(f, 0, SEEK_SET) == 0);
                    uint8_t *buf = (uint8_t *)malloc((size_t)n);
                    assert(buf != NULL);
                    assert(fread(buf, 1, (size_t)n, f) == (size_t)n);
                    assert(fclose(f) == 0);
                    *out_len = (uint32_t)n;
                    return buf;
                }

                int main(int argc, char **argv) {
                    assert(argc == 3);
                    uint32_t good_len = 0u;
                    uint32_t bad_len = 0u;
                    uint8_t *good = read_file(argv[1], &good_len);
                    uint8_t *bad_export = read_file(argv[2], &bad_len);

                    WdcBundleVerifyPolicy policy = wdc_bundle_make_default_dev_policy(wdc_profile_builtin());
                    WdcBundleVerifyResult result;
                    assert(wdc_bundle_verify(good, good_len, &policy, &result) == WDC_OK);
                    assert(result.header_ok);
                    assert(result.manifest_hash_ok);
                    assert(result.payload_hash_ok);
                    assert(result.manifest_payload_binding_ok);
                    assert(result.signature_ok);
                    assert(result.abi_ok);
                    assert(result.target_ok);
                    assert(result.limits_ok);
                    assert(result.capabilities_ok);
                    assert(result.exports_ok);
                    assert(strcmp(result.manifest.bundle_id, "com.example.relay-controller") == 0);
                    assert(result.capability_set.capability_count >= 3u);

                    const uint8_t *payload = NULL;
                    uint32_t payload_len = 0u;
                    assert(wdc_bundle_get_payload(good, good_len, &result.header, &payload, &payload_len) == WDC_OK);
                    assert(payload != NULL && payload_len == result.header.payload_len);

                    WdcBundleMetadataV1 metadata;
                    wdc_bundle_metadata_init(&metadata);
                    assert(wdc_bundle_metadata_validate(&metadata) == WDC_OK);
                    assert(wdc_bundle_metadata_mark_verified(&metadata, WDC_BUNDLE_SLOT_A, &result) == WDC_OK);
                    assert(wdc_bundle_metadata_validate(&metadata) == WDC_OK);
                    assert(metadata.slot_a.state == WDC_SLOT_VERIFIED);
                    assert(metadata.slot_a.bundle_version == result.manifest.bundle_version);
                    assert(metadata.slot_a.security_counter == result.manifest.security_counter);

                    wdc_ota_host_clear_slots();
                    assert(wdc_ota_host_set_slot_image(WDC_BUNDLE_SLOT_A, good, good_len) == WDC_OK);
                    WdcBundleParsedHeader slot_header;
                    assert(wdc_ota_read_slot_header(WDC_BUNDLE_SLOT_A, &slot_header) == WDC_OK);
                    assert(slot_header.payload_len == result.header.payload_len);
                    uint8_t slot_copy[4096];
                    uint32_t slot_copy_len = 0u;
                    assert(wdc_ota_read_slot_to_buffer(WDC_BUNDLE_SLOT_A, slot_copy, sizeof(slot_copy), &slot_copy_len) == WDC_OK);
                    assert(slot_copy_len == good_len);

                    policy.production_mode = true;
                    assert(wdc_bundle_verify(good, good_len, &policy, &result) == WDC_ERR_CONTRACT_VIOLATION);
                    assert(!result.signature_ok);
                    policy.production_mode = false;
                    policy.min_security_counter = 2u;
                    assert(wdc_bundle_verify(good, good_len, &policy, &result) == WDC_ERR_CONTRACT_VIOLATION);
                    assert(!result.anti_rollback_ok);
                    policy.min_security_counter = 0u;

                    uint8_t *corrupt = (uint8_t *)malloc(good_len);
                    assert(corrupt != NULL);
                    memcpy(corrupt, good, good_len);
                    WdcBundleParsedHeader parsed;
                    assert(wdc_bundle_parse_header(corrupt, good_len, &parsed) == WDC_OK);
                    corrupt[parsed.payload_offset + parsed.payload_len - 1u] ^= 0x55u;
                    assert(wdc_bundle_verify(corrupt, good_len, &policy, &result) == WDC_ERR_CONTRACT_VIOLATION);
                    assert(!result.payload_hash_ok);
                    free(corrupt);

                    assert(wdc_bundle_verify(bad_export, bad_len, &policy, &result) == WDC_ERR_NOT_AVAILABLE);
                    assert(!result.exports_ok);

                    free(good);
                    free(bad_export);
                    return 0;
                }
                '''
            )
            test_c = tmp_path / "r6_native_bundle_smoke.c"
            test_c.write_text(program, encoding="utf-8")
            exe = tmp_path / "r6_native_bundle_smoke"
            include_args = [
                "-I", str(FW / "components/wdc_abi/include"),
                "-I", str(FW / "components/wdc_bundle/include"),
                "-I", str(FW / "components/wdc_caps/include"),
                "-I", str(FW / "components/wdc_ota/include"),
                "-I", str(FW / "components/wdc_profile/include"),
            ]
            sources = [
                FW / "components/wdc_abi/wdc_errors.c",
                FW / "components/wdc_abi/wdc_cbor.c",
                FW / "components/wdc_abi/wdc_pointer.c",
                FW / "components/wdc_abi/wdc_host_call.c",
                FW / "components/wdc_bundle/wdc_bundle.c",
                FW / "components/wdc_caps/wdc_caps.c",
                FW / "components/wdc_ota/wdc_ota.c",
                FW / "components/wdc_profile/wdc_profile_static.c",
                test_c,
            ]
            subprocess.run(
                ["gcc", "-std=c11", "-Wall", "-Wextra", "-Werror", *include_args, *map(str, sources), "-o", str(exe)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            subprocess.run([str(exe), str(EXAMPLE_BUNDLE), str(bad_export)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    unittest.main()
