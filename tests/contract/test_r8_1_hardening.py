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
ABI = FW / "components/wdc_abi"
TOOL = ROOT / "tools/wdc_bundle_tool.py"
MANIFEST = ROOT / "examples/bundles/relay-controller/manifest.json"
STATIC_WASM = FW / "components/wdc_runtime/test_vectors/wdc_static_hello_wasm.wasm"
R8_BUNDLE = ROOT / "examples/bundles/relay-controller/dist/relay-controller-r8.wdcb"


def _leb_u32(value: int) -> bytes:
    out = bytearray()
    while True:
        b = value & 0x7F
        value >>= 7
        if value:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _fake_wasm_with_names_in_custom_section() -> bytes:
    names = b"wdc_module_init wdc_module_on_event wdc_module_health wdc_module_shutdown"
    custom_name = b"not_exports"
    section_body = _leb_u32(len(custom_name)) + custom_name + names
    return b"\0asm" + b"\x01\0\0\0" + b"\x00" + _leb_u32(len(section_body)) + section_body


def compile_and_run(source: str, exe_name: str, include_dirs: list[Path], sources: list[Path], args: list[str] | None = None) -> None:
    if shutil.which("gcc") is None:
        raise unittest.SkipTest("gcc not available")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        test_c = tmp_path / f"{exe_name}.c"
        test_c.write_text(source, encoding="utf-8")
        exe = tmp_path / exe_name
        include_args: list[str] = []
        for inc in include_dirs:
            include_args.extend(["-I", str(inc)])
        compile_cmd = ["gcc", "-std=c11", "-Wall", "-Wextra", "-Werror", *include_args, *map(str, sources), str(test_c), "-o", str(exe)]
        try:
            subprocess.run(compile_cmd, cwd=ROOT, check=True, text=True, capture_output=True)
            subprocess.run([str(exe), *(args or [])], cwd=ROOT, check=True, text=True, capture_output=True)
        except subprocess.CalledProcessError as exc:
            raise AssertionError((exc.stdout or "") + (exc.stderr or "")) from exc


class R81HardeningTests(unittest.TestCase):
    def test_r81_production_safe_boot_config(self) -> None:
        config = (FW / "main/shell_config.h").read_text(encoding="utf-8")
        for token in [
            'WDC_SHELL_VERSION     "0.1.0-r9"',
            'WDC_SHELL_BUILD_STAGE "R9"',
            "#define WDC_BUILD_PROFILE_PROD 1",
            "#define WDC_ENABLE_EFFECTFUL_SELF_TESTS 0",
            "#define WDC_ENABLE_BOOT_DIAGNOSTIC_PROBES 0",
            "#define WDC_R4_STATIC_RUNTIME_SMOKE 0",
            "#define WDC_R5_STATIC_RUNTIME_SMOKE  0",
            "#define WDC_R7_ACTIVATION_SMOKE      0",
            "#define WDC_R8_NETWORK_SMOKE         WDC_ENABLE_EFFECTFUL_SELF_TESTS",
        ]:
            self.assertIn(token, config)

        shell = (FW / "main/shell_main.c").read_text(encoding="utf-8")
        self.assertEqual(shell.count("#if WDC_ENABLE_EFFECTFUL_SELF_TESTS"), 1)
        self.assertIn("R8.2 production boot: effectful GPIO/network self-tests disabled", shell)

    def test_r81_host_call_fails_closed_without_authorizer(self) -> None:
        program = textwrap.dedent(
            r'''
            #include <assert.h>
            #include <stdbool.h>
            #include <stdint.h>
            #include "wdc_abi.h"

            static int32_t rsp_status(const uint8_t *rsp, uint32_t rsp_len) {
                int32_t status = WDC_ERR_UNKNOWN;
                assert(wdc_cbor_map_find_i32(rsp, rsp_len, WDC_CBOR_KEY_STATUS, &status) == WDC_OK);
                return status;
            }

            static uint32_t gpio_set_req(uint8_t *req, uint32_t cap) {
                WdcCborBuilder b;
                wdc_cbor_builder_init(&b, req, cap);
                assert(wdc_cbor_begin_map(&b, 2u) == WDC_OK);
                assert(wdc_cbor_put_key_u32(&b, WDC_CBOR_KEY_RESOURCE_ID, WDC_R3_RESOURCE_RELAY_1) == WDC_OK);
                assert(wdc_cbor_put_key_bool(&b, WDC_CBOR_KEY_VALUE, true) == WDC_OK);
                return wdc_cbor_len(&b);
            }

            static uint32_t config_set_req(uint8_t *req, uint32_t cap) {
                const uint8_t value[] = {'o','k'};
                WdcCborBuilder b;
                wdc_cbor_builder_init(&b, req, cap);
                assert(wdc_cbor_begin_map(&b, 2u) == WDC_OK);
                assert(wdc_cbor_put_key_text(&b, WDC_CBOR_KEY_KEY, "app.mode") == WDC_OK);
                assert(wdc_cbor_put_key_bytes(&b, WDC_CBOR_KEY_DATA, value, sizeof(value)) == WDC_OK);
                return wdc_cbor_len(&b);
            }

            static uint32_t timer_set_req(uint8_t *req, uint32_t cap) {
                WdcCborBuilder b;
                wdc_cbor_builder_init(&b, req, cap);
                assert(wdc_cbor_begin_map(&b, 3u) == WDC_OK);
                assert(wdc_cbor_put_key_u32(&b, WDC_CBOR_KEY_TIMER_ID, 1u) == WDC_OK);
                assert(wdc_cbor_put_key_u32(&b, WDC_CBOR_KEY_DELAY_MS, 10u) == WDC_OK);
                assert(wdc_cbor_put_key_bool(&b, WDC_CBOR_KEY_REPEAT, false) == WDC_OK);
                return wdc_cbor_len(&b);
            }

            int main(void) {
                uint8_t req[192];
                uint8_t rsp[256];
                uint32_t rsp_len = 0u;
                wdc_host_call_reset_for_test();
                assert(wdc_host_call_dispatch(WDC_OP_SYS_GET_INFO, NULL, 0u, rsp, sizeof(rsp), &rsp_len) == WDC_OK);
                assert(rsp_status(rsp, rsp_len) == WDC_OK);
                uint32_t req_len = gpio_set_req(req, sizeof(req));
                assert(wdc_host_call_dispatch(WDC_OP_GPIO_SET, req, req_len, rsp, sizeof(rsp), &rsp_len) == WDC_OK);
                assert(rsp_status(rsp, rsp_len) == WDC_ERR_CAPABILITY_DENIED);
                req_len = config_set_req(req, sizeof(req));
                assert(wdc_host_call_dispatch(WDC_OP_CONFIG_SET, req, req_len, rsp, sizeof(rsp), &rsp_len) == WDC_OK);
                assert(rsp_status(rsp, rsp_len) == WDC_ERR_CAPABILITY_DENIED);
                req_len = timer_set_req(req, sizeof(req));
                assert(wdc_host_call_dispatch(WDC_OP_TIMER_SET, req, req_len, rsp, sizeof(rsp), &rsp_len) == WDC_OK);
                assert(rsp_status(rsp, rsp_len) == WDC_ERR_CAPABILITY_DENIED);
                return 0;
            }
            '''
        )
        compile_and_run(program, "r8_1_fail_closed", [ABI / "include"], [ABI / "wdc_errors.c", ABI / "wdc_cbor.c", ABI / "wdc_host_call.c"])

    def test_r81_confirmed_boot_does_not_rewrite_metadata(self) -> None:
        program = textwrap.dedent(
            r'''
            #include <assert.h>
            #include <stdint.h>
            #include <string.h>
            #include "wdc_abi.h"
            #include "wdc_activation.h"
            #include "wdc_bundle.h"
            #include "wdc_ota.h"

            static void seed(WdcBundleSlotRecord *record, WdcSlotState state, uint32_t version, uint8_t fill) {
                memset(record, 0, sizeof(*record));
                record->state = state;
                record->bundle_version = version;
                record->security_counter = version;
                memset(record->payload_sha256, fill, WDC_BUNDLE_SHA256_BYTES);
            }

            int main(void) {
                wdc_ota_host_clear_metadata();
                WdcBundleMetadataV1 metadata;
                wdc_bundle_metadata_init(&metadata);
                seed(&metadata.slot_a, WDC_SLOT_CONFIRMED, 8u, 0xa8u);
                metadata.active_slot = WDC_BUNDLE_SLOT_A;
                metadata.last_good_slot = WDC_BUNDLE_SLOT_A;
                metadata.metadata_generation = 10u;
                assert(wdc_bundle_metadata_seal(&metadata) == WDC_OK);
                assert(wdc_ota_write_metadata(&metadata) == WDC_OK);
                uint32_t writes = wdc_ota_host_metadata_write_count();
                WdcActivationDecision decision;
                WdcActivationPolicy policy = wdc_activation_default_policy();
                assert(wdc_activation_on_boot(&metadata, &policy, &decision) == WDC_OK);
                assert(decision.kind == WDC_ACTIVATION_DECISION_RUN_CONFIRMED);
                assert(!decision.metadata_changed);
                assert(metadata.metadata_generation == 10u);
                assert(wdc_ota_write_metadata(&metadata) == WDC_OK);
                assert(wdc_ota_host_metadata_write_count() == writes);
                return 0;
            }
            '''
        )
        compile_and_run(
            program,
            "r8_1_confirmed_no_rewrite",
            [FW / "components/wdc_abi/include", FW / "components/wdc_activation/include", FW / "components/wdc_bundle/include", FW / "components/wdc_caps/include", FW / "components/wdc_profile/include", FW / "components/wdc_ota/include"],
            [FW / "components/wdc_abi/wdc_errors.c", FW / "components/wdc_abi/wdc_cbor.c", FW / "components/wdc_abi/wdc_pointer.c", FW / "components/wdc_abi/wdc_host_call.c", FW / "components/wdc_caps/wdc_caps.c", FW / "components/wdc_profile/wdc_profile_static.c", FW / "components/wdc_bundle/wdc_bundle.c", FW / "components/wdc_ota/wdc_ota.c", FW / "components/wdc_activation/wdc_activation.c"],
        )

    def test_r81_metadata_journal_survives_one_corrupt_record(self) -> None:
        program = textwrap.dedent(
            r'''
            #include <assert.h>
            #include <stdint.h>
            #include <string.h>
            #include "wdc_abi.h"
            #include "wdc_bundle.h"
            #include "wdc_ota.h"

            static void seed(WdcBundleMetadataV1 *metadata, WdcBundleSlotId active, uint32_t generation, uint8_t fill) {
                wdc_bundle_metadata_init(metadata);
                WdcBundleSlotRecord *slot = active == WDC_BUNDLE_SLOT_A ? &metadata->slot_a : &metadata->slot_b;
                memset(slot, 0, sizeof(*slot));
                slot->state = WDC_SLOT_CONFIRMED;
                slot->bundle_version = generation;
                slot->security_counter = generation;
                memset(slot->payload_sha256, fill, WDC_BUNDLE_SHA256_BYTES);
                metadata->active_slot = active;
                metadata->last_good_slot = active;
                metadata->metadata_generation = generation;
                assert(wdc_bundle_metadata_seal(metadata) == WDC_OK);
            }

            int main(void) {
                wdc_ota_host_clear_metadata();
                WdcBundleMetadataV1 m1;
                WdcBundleMetadataV1 m2;
                WdcBundleMetadataV1 loaded;
                seed(&m1, WDC_BUNDLE_SLOT_A, 1u, 0xa1u);
                seed(&m2, WDC_BUNDLE_SLOT_B, 2u, 0xb2u);
                assert(wdc_ota_write_metadata(&m1) == WDC_OK);
                assert(wdc_ota_host_metadata_valid_record_count() == 1u);
                assert(wdc_ota_write_metadata(&m2) == WDC_OK);
                assert(wdc_ota_host_metadata_valid_record_count() == 2u);
                assert(wdc_ota_read_metadata(&loaded) == WDC_OK);
                assert(loaded.metadata_generation == 2u);
                assert(wdc_ota_host_corrupt_metadata_record(1u) == WDC_OK);
                assert(wdc_ota_host_metadata_valid_record_count() == 1u);
                assert(wdc_ota_read_metadata(&loaded) == WDC_OK);
                assert(loaded.metadata_generation == 1u);
                assert(wdc_ota_host_clear_metadata_record(0u) == WDC_OK);
                assert(wdc_ota_host_clear_metadata_record(1u) == WDC_OK);
                assert(wdc_ota_read_metadata(&loaded) == WDC_OK);
                assert(loaded.active_slot == WDC_BUNDLE_SLOT_NONE);
                return 0;
            }
            '''
        )
        compile_and_run(
            program,
            "r8_1_metadata_journal",
            [FW / "components/wdc_abi/include", FW / "components/wdc_bundle/include", FW / "components/wdc_caps/include", FW / "components/wdc_profile/include", FW / "components/wdc_ota/include"],
            [FW / "components/wdc_abi/wdc_errors.c", FW / "components/wdc_abi/wdc_cbor.c", FW / "components/wdc_abi/wdc_pointer.c", FW / "components/wdc_abi/wdc_host_call.c", FW / "components/wdc_caps/wdc_caps.c", FW / "components/wdc_profile/wdc_profile_static.c", FW / "components/wdc_bundle/wdc_bundle.c", FW / "components/wdc_ota/wdc_ota.c"],
        )

    def test_r81_bundle_verifier_rejects_trailing_unsigned_bytes_native(self) -> None:
        self.assertTrue(R8_BUNDLE.exists(), R8_BUNDLE)
        program = textwrap.dedent(
            r'''
            #include <assert.h>
            #include <stdint.h>
            #include <stdio.h>
            #include <stdlib.h>
            #include <string.h>
            #include "wdc_abi.h"
            #include "wdc_bundle.h"
            #include "wdc_profile.h"

            static uint8_t *read_file(const char *path, uint32_t *out_len) {
                FILE *f = fopen(path, "rb");
                assert(f != NULL);
                assert(fseek(f, 0, SEEK_END) == 0);
                long n = ftell(f);
                assert(n > 0 && n < 1000000);
                assert(fseek(f, 0, SEEK_SET) == 0);
                uint8_t *buf = (uint8_t *)malloc((size_t)n + 1u);
                assert(buf != NULL);
                assert(fread(buf, 1u, (size_t)n, f) == (size_t)n);
                assert(fclose(f) == 0);
                *out_len = (uint32_t)n;
                return buf;
            }

            int main(int argc, char **argv) {
                assert(argc == 2);
                uint32_t len = 0u;
                uint8_t *bundle = read_file(argv[1], &len);
                WdcBundleVerifyPolicy policy = wdc_bundle_make_default_dev_policy(wdc_profile_builtin());
                WdcBundleVerifyResult result;
                assert(wdc_bundle_verify(bundle, len, &policy, &result) == WDC_OK);
                assert(result.exports_ok);
                bundle[len] = 0xffu;
                assert(wdc_bundle_verify(bundle, len + 1u, &policy, &result) == WDC_ERR_BAD_LENGTH);
                assert(result.header_ok);
                assert(!result.signature_ok);
                free(bundle);
                return 0;
            }
            '''
        )
        compile_and_run(
            program,
            "r8_1_bundle_trailing",
            [FW / "components/wdc_abi/include", FW / "components/wdc_bundle/include", FW / "components/wdc_caps/include", FW / "components/wdc_profile/include"],
            [FW / "components/wdc_abi/wdc_errors.c", FW / "components/wdc_abi/wdc_cbor.c", FW / "components/wdc_abi/wdc_pointer.c", FW / "components/wdc_abi/wdc_host_call.c", FW / "components/wdc_caps/wdc_caps.c", FW / "components/wdc_profile/wdc_profile_static.c", FW / "components/wdc_bundle/wdc_bundle.c"],
            [str(R8_BUNDLE)],
        )

    def test_r81_network_policy_enforces_topic_and_url_allowlists(self) -> None:
        program = textwrap.dedent(
            r'''
            #include <assert.h>
            #include <stdint.h>
            #include <string.h>
            #include "wdc_abi.h"
            #include "wdc_caps.h"
            #include "wdc_diag.h"
            #include "wdc_events.h"
            #include "wdc_net.h"
            #include "wdc_profile.h"
            #include "wdc_safety.h"

            static int32_t rsp_status(const uint8_t *rsp, uint32_t rsp_len) {
                int32_t status = WDC_ERR_UNKNOWN;
                assert(wdc_cbor_map_find_i32(rsp, rsp_len, WDC_CBOR_KEY_STATUS, &status) == WDC_OK);
                return status;
            }

            static uint32_t mqtt_req(uint8_t *req, uint32_t cap, uint32_t resource_id, const char *topic) {
                const uint8_t payload[] = {'o','k'};
                WdcCborBuilder b;
                wdc_cbor_builder_init(&b, req, cap);
                assert(wdc_cbor_begin_map(&b, 4u) == WDC_OK);
                assert(wdc_cbor_put_key_u32(&b, WDC_CBOR_KEY_RESOURCE_ID, resource_id) == WDC_OK);
                assert(wdc_cbor_put_key_text(&b, WDC_CBOR_KEY_TOPIC, topic) == WDC_OK);
                assert(wdc_cbor_put_key_bytes(&b, WDC_CBOR_KEY_DATA, payload, sizeof(payload)) == WDC_OK);
                assert(wdc_cbor_put_key_u32(&b, WDC_CBOR_KEY_QOS, 0u) == WDC_OK);
                return wdc_cbor_len(&b);
            }

            static uint32_t sub_req(uint8_t *req, uint32_t cap, uint32_t resource_id, const char *topic) {
                WdcCborBuilder b;
                wdc_cbor_builder_init(&b, req, cap);
                assert(wdc_cbor_begin_map(&b, 2u) == WDC_OK);
                assert(wdc_cbor_put_key_u32(&b, WDC_CBOR_KEY_RESOURCE_ID, resource_id) == WDC_OK);
                assert(wdc_cbor_put_key_text(&b, WDC_CBOR_KEY_TOPIC, topic) == WDC_OK);
                return wdc_cbor_len(&b);
            }

            static uint32_t http_req(uint8_t *req, uint32_t cap, uint32_t resource_id, const char *method, const char *url) {
                const uint8_t body[] = {'{','}'};
                WdcCborBuilder b;
                wdc_cbor_builder_init(&b, req, cap);
                assert(wdc_cbor_begin_map(&b, 4u) == WDC_OK);
                assert(wdc_cbor_put_key_u32(&b, WDC_CBOR_KEY_RESOURCE_ID, resource_id) == WDC_OK);
                assert(wdc_cbor_put_key_text(&b, WDC_CBOR_KEY_METHOD, method) == WDC_OK);
                assert(wdc_cbor_put_key_text(&b, WDC_CBOR_KEY_URL, url) == WDC_OK);
                assert(wdc_cbor_put_key_bytes(&b, WDC_CBOR_KEY_DATA, body, sizeof(body)) == WDC_OK);
                return wdc_cbor_len(&b);
            }

            static void dispatch_expect(uint32_t opcode, const uint8_t *req, uint32_t req_len, int32_t expected) {
                uint8_t rsp[160];
                uint32_t rsp_len = 0u;
                assert(wdc_host_call_dispatch(opcode, req, req_len, rsp, sizeof(rsp), &rsp_len) == WDC_OK);
                assert(rsp_status(rsp, rsp_len) == expected);
            }

            int main(void) {
                const WdcDeviceProfile *profile = wdc_profile_builtin();
                assert(wdc_profile_validate_basic(profile) == WDC_OK);
                assert(wdc_diag_init() == WDC_OK);
                assert(wdc_events_init() == WDC_OK);
                wdc_host_call_reset_for_test();
                wdc_safety_reset_for_test();
                wdc_net_reset_for_test();
                assert(wdc_safety_init(profile) == WDC_OK);
                assert(wdc_net_init(profile) == WDC_OK);
                assert(wdc_safety_install_guarded_authorizer(profile, wdc_caps_builtin_relay_full()) == WDC_OK);
                assert(wdc_safety_mark_app_running("com.example.r8_1-policy", 81u) == WDC_OK);
                assert(wdc_net_set_connected(true, "unit") == WDC_OK);

                uint8_t req[320];
                uint32_t len = mqtt_req(req, sizeof(req), WDC_R8_RESOURCE_MQTT_TELEMETRY, "devices/demo/telemetry/state");
                dispatch_expect(WDC_OP_MQTT_PUBLISH, req, len, WDC_OK);
                len = mqtt_req(req, sizeof(req), WDC_R8_RESOURCE_MQTT_TELEMETRY, "other/demo/telemetry/state");
                dispatch_expect(WDC_OP_MQTT_PUBLISH, req, len, WDC_ERR_CAPABILITY_DENIED);
                len = sub_req(req, sizeof(req), WDC_R8_RESOURCE_MQTT_COMMANDS, "devices/demo/commands/#");
                dispatch_expect(WDC_OP_MQTT_SUBSCRIBE, req, len, WDC_OK);
                len = sub_req(req, sizeof(req), WDC_R8_RESOURCE_MQTT_COMMANDS, "devices/other/commands/#");
                dispatch_expect(WDC_OP_MQTT_SUBSCRIBE, req, len, WDC_ERR_CAPABILITY_DENIED);
                len = http_req(req, sizeof(req), WDC_R8_RESOURCE_HTTP_API, "POST", "https://api.example.invalid/devices/demo/state");
                dispatch_expect(WDC_OP_HTTP_REQUEST, req, len, WDC_OK);
                len = http_req(req, sizeof(req), WDC_R8_RESOURCE_HTTP_API, "DELETE", "https://api.example.invalid/devices/demo/state");
                dispatch_expect(WDC_OP_HTTP_REQUEST, req, len, WDC_ERR_CAPABILITY_DENIED);
                len = http_req(req, sizeof(req), WDC_R8_RESOURCE_HTTP_API, "POST", "https://evil.example.invalid/devices/demo/state");
                dispatch_expect(WDC_OP_HTTP_REQUEST, req, len, WDC_ERR_CAPABILITY_DENIED);
                WdcNetStatus status;
                memset(&status, 0, sizeof(status));
                wdc_net_get_status(&status);
                assert(status.publish_count == 1u);
                assert(status.subscribe_count == 1u);
                assert(status.http_request_count == 1u);
                assert(status.rejected_count >= 4u);
                return 0;
            }
            '''
        )
        compile_and_run(
            program,
            "r8_1_network_policy",
            [FW / "components/wdc_abi/include", FW / "components/wdc_caps/include", FW / "components/wdc_diag/include", FW / "components/wdc_events/include", FW / "components/wdc_hal/include", FW / "components/wdc_net/include", FW / "components/wdc_profile/include", FW / "components/wdc_runtime/include", FW / "components/wdc_safety/include"],
            [FW / "components/wdc_abi/wdc_errors.c", FW / "components/wdc_abi/wdc_cbor.c", FW / "components/wdc_abi/wdc_pointer.c", FW / "components/wdc_abi/wdc_host_call.c", FW / "components/wdc_caps/wdc_caps.c", FW / "components/wdc_diag/wdc_diag.c", FW / "components/wdc_events/wdc_event_queue.c", FW / "components/wdc_events/wdc_event_encode.c", FW / "components/wdc_hal/wdc_gpio_espidf.c", FW / "components/wdc_net/wdc_net.c", FW / "components/wdc_profile/wdc_profile_static.c", FW / "components/wdc_safety/wdc_safety.c"],
        )

    def test_r81_bundle_tool_rejects_trailing_unsigned_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bundle = tmp_path / "valid.wdcb"
            subprocess.run([str(TOOL), "pack", "--manifest", str(MANIFEST), "--payload", str(STATIC_WASM), "--out", str(bundle)], cwd=ROOT, check=True, text=True, capture_output=True)
            tampered = tmp_path / "trailing.wdcb"
            tampered.write_bytes(bundle.read_bytes() + b"\0")
            result = subprocess.run([str(TOOL), "inspect", "--bundle", str(tampered), "--allow-fail"], cwd=ROOT, check=True, text=True, capture_output=True)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "FAIL")
            self.assertIn("trailing unsigned bytes", report["reason"])

    def test_r81_bundle_tool_requires_real_wasm_export_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = tmp_path / "custom_names_only.wasm"
            payload.write_bytes(_fake_wasm_with_names_in_custom_section())
            bundle = tmp_path / "fake.wdcb"
            subprocess.run([str(TOOL), "pack", "--manifest", str(MANIFEST), "--payload", str(payload), "--out", str(bundle)], cwd=ROOT, check=True, text=True, capture_output=True)
            result = subprocess.run([str(TOOL), "inspect", "--bundle", str(bundle), "--allow-fail"], cwd=ROOT, check=True, text=True, capture_output=True)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "FAIL")
            self.assertFalse(report["checks"]["required_exports_ok"])
            self.assertTrue(report["checks"]["signature_ok"])
            self.assertTrue(report["checks"]["payload_hash_ok"])


if __name__ == "__main__":
    unittest.main()
