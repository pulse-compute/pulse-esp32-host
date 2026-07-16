from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FW = ROOT / "firmware"
R8_BUNDLE = ROOT / "examples/bundles/relay-controller/dist/relay-controller-r8.wdcb"


def c_common_args(tmp_path: Path, source: str, exe_name: str) -> tuple[list[str], Path]:
    src = tmp_path / f"{exe_name}.c"
    exe = tmp_path / exe_name
    src.write_text(source, encoding="utf-8")
    include_args = [
        "-I", str(FW / "components/wdc_abi/include"),
        "-I", str(FW / "components/wdc_activation/include"),
        "-I", str(FW / "components/wdc_app/include"),
        "-I", str(FW / "components/wdc_bundle/include"),
        "-I", str(FW / "components/wdc_caps/include"),
        "-I", str(FW / "components/wdc_diag/include"),
        "-I", str(FW / "components/wdc_events/include"),
        "-I", str(FW / "components/wdc_hal/include"),
        "-I", str(FW / "components/wdc_net/include"),
        "-I", str(FW / "components/wdc_ota/include"),
        "-I", str(FW / "components/wdc_profile/include"),
        "-I", str(FW / "components/wdc_runtime/include"),
        "-I", str(FW / "components/wdc_safety/include"),
    ]
    sources = [
        FW / "components/wdc_abi/wdc_errors.c",
        FW / "components/wdc_abi/wdc_cbor.c",
        FW / "components/wdc_abi/wdc_pointer.c",
        FW / "components/wdc_abi/wdc_host_call.c",
        FW / "components/wdc_activation/wdc_activation.c",
        FW / "components/wdc_app/wdc_app.c",
        FW / "components/wdc_bundle/wdc_bundle.c",
        FW / "components/wdc_caps/wdc_caps.c",
        FW / "components/wdc_diag/wdc_diag.c",
        FW / "components/wdc_events/wdc_event_queue.c",
        FW / "components/wdc_events/wdc_event_encode.c",
        FW / "components/wdc_hal/wdc_gpio_espidf.c",
        FW / "components/wdc_net/wdc_net.c",
        FW / "components/wdc_ota/wdc_ota.c",
        FW / "components/wdc_profile/wdc_profile_static.c",
        FW / "components/wdc_runtime/wdc_runtime.c",
        FW / "components/wdc_safety/wdc_safety.c",
        src,
    ]
    cmd = ["gcc", "-std=c11", "-Wall", "-Wextra", "-Werror", *include_args, *map(str, sources), "-o", str(exe)]
    return cmd, exe


class R8ActiveSlotNetworkTests(unittest.TestCase):
    def test_r8_files_and_symbols_exist(self) -> None:
        files = [
            "firmware/components/wdc_net/CMakeLists.txt",
            "firmware/components/wdc_net/wdc_net.c",
            "firmware/components/wdc_net/include/wdc_net.h",
            "firmware/components/wdc_app/CMakeLists.txt",
            "firmware/components/wdc_app/wdc_app.c",
            "firmware/components/wdc_app/include/wdc_app.h",
            "examples/bundles/relay-controller/dist/relay-controller-r8.wdcb",
            "tests/contract/test_r8_active_slot_network.py",
            "tools/check_r8.py",
        ]
        for rel in files:
            self.assertTrue((ROOT / rel).exists(), rel)

        abi = (FW / "components/wdc_abi/include/wdc_abi.h").read_text(encoding="utf-8")
        for token in [
            'WDC_R8_2_SHELL_VERSION "0.1.0-r8.2"',
            'WDC_R8_2_BUILD_STAGE   "R8.2"',
            "WDC_OP_NET_STATUS",
            "WDC_OP_MQTT_PUBLISH",
            "WDC_OP_MQTT_SUBSCRIBE",
            "WDC_OP_HTTP_REQUEST",
            "WDC_EVENT_NET_CONNECTED",
            "WdcHostNetCallFn",
            "wdc_opcode_supported_r8",
        ]:
            self.assertIn(token, abi)

        net = (FW / "components/wdc_net/wdc_net.c").read_text(encoding="utf-8")
        for token in [
            "wdc_net_host_call",
            "WDC_OP_MQTT_PUBLISH",
            "WDC_OP_MQTT_SUBSCRIBE",
            "WDC_OP_HTTP_REQUEST",
            "wdc_host_call_set_net_hook",
            "WDC_EVENT_NET_CONNECTED",
            "WDC_EVENT_NET_DISCONNECTED",
        ]:
            self.assertIn(token, net)

        app = (FW / "components/wdc_app/wdc_app.c").read_text(encoding="utf-8")
        for token in [
            "wdc_app_boot_active_slot",
            "wdc_activation_on_boot",
            "wdc_ota_read_slot_to_buffer",
            "wdc_bundle_verify",
            "wdc_safety_install_guarded_authorizer",
            "wdc_runtime_load_static",
        ]:
            self.assertIn(token, app)

        shell = (FW / "main/shell_main.c").read_text(encoding="utf-8")
        for token in [
            "wdc_net_init",
            "wdc_shell_run_r8_network_self_test",
            "wdc_shell_run_r8_active_slot_probe",
            "wdc_app_boot_active_slot",
        ]:
            self.assertIn(token, shell)

    def test_r8_bundle_tool_active_flow_and_manifest_network_caps(self) -> None:
        import contextlib
        import io
        import json
        import sys
        from types import SimpleNamespace

        sys.path.insert(0, str(ROOT))
        from tools import wdc_bundle_tool as tool  # noqa: E402

        data = R8_BUNDLE.read_bytes()
        report = tool.verify_bytes(data)
        self.assertEqual(report.get("status"), "PASS")
        self.assertEqual(report["manifest"]["bundle_version"], 8)
        caps = report["manifest"].get("capabilities", [])
        network_caps = {(c.get("resource"), tuple(c.get("ops", []))) for c in caps if c.get("kind") == "network"}
        self.assertIn(("mqtt_telemetry", ("publish",)), network_caps)
        self.assertIn(("mqtt_commands", ("subscribe",)), network_caps)
        self.assertIn(("http_api", ("request",)), network_caps)

        def call(func, **kwargs):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = func(SimpleNamespace(**kwargs))
            self.assertEqual(rc, 0, buf.getvalue())
            return json.loads(buf.getvalue())

        with tempfile.TemporaryDirectory() as tmp:
            slots = Path(tmp) / "slots"
            common = {"bundle": str(R8_BUNDLE), "slots_dir": str(slots), "key": None, "allow_unverified": False}
            install = call(tool.cmd_install, slot="a", **common)
            self.assertEqual(install["status"], "PASS")
            status_after_install = call(tool.cmd_status, slots_dir=str(slots))
            self.assertEqual(status_after_install["metadata"]["slot_a_state"], "verified")
            pending = call(tool.cmd_activate, slot="a", slots_dir=str(slots), allow_fail=False)
            self.assertEqual(pending["decision"], "slot_marked_pending")
            boot = call(tool.cmd_boot, slots_dir=str(slots), max_candidate_boots=1, write_no_bundle=False)
            self.assertEqual(boot["selected_slot"], "a")
            self.assertEqual(boot["decision"], "boot_pending")
            confirm = call(tool.cmd_confirm, slots_dir=str(slots), slot=None, allow_fail=False)
            self.assertEqual(confirm["metadata"]["slot_a_state"], "confirmed")
            self.assertEqual(confirm["metadata"]["last_good_slot"], "a")

    def test_r8_native_network_mediator_smoke(self) -> None:
        if shutil.which("gcc") is None:
            self.skipTest("gcc not available")
        program = textwrap.dedent(
            r'''
            #include <assert.h>
            #include <stdbool.h>
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

            static uint32_t mqtt_req(uint8_t *req, uint32_t cap, uint32_t resource_id, const char *topic, const uint8_t *payload, uint32_t payload_len) {
                WdcCborBuilder b;
                wdc_cbor_builder_init(&b, req, cap);
                int32_t st = wdc_cbor_begin_map(&b, 4u);
                if (st == WDC_OK) { st = wdc_cbor_put_key_u32(&b, WDC_CBOR_KEY_RESOURCE_ID, resource_id); }
                if (st == WDC_OK) { st = wdc_cbor_put_key_text(&b, WDC_CBOR_KEY_TOPIC, topic); }
                if (st == WDC_OK) { st = wdc_cbor_put_key_bytes(&b, WDC_CBOR_KEY_DATA, payload, payload_len); }
                if (st == WDC_OK) { st = wdc_cbor_put_key_u32(&b, WDC_CBOR_KEY_QOS, 0u); }
                assert(st == WDC_OK);
                return wdc_cbor_len(&b);
            }

            static uint32_t sub_req(uint8_t *req, uint32_t cap, uint32_t resource_id, const char *topic) {
                WdcCborBuilder b;
                wdc_cbor_builder_init(&b, req, cap);
                int32_t st = wdc_cbor_begin_map(&b, 2u);
                if (st == WDC_OK) { st = wdc_cbor_put_key_u32(&b, WDC_CBOR_KEY_RESOURCE_ID, resource_id); }
                if (st == WDC_OK) { st = wdc_cbor_put_key_text(&b, WDC_CBOR_KEY_TOPIC, topic); }
                assert(st == WDC_OK);
                return wdc_cbor_len(&b);
            }

            static uint32_t http_req(uint8_t *req, uint32_t cap, uint32_t resource_id, const char *method, const char *url) {
                const uint8_t body[] = {'{','}'};
                WdcCborBuilder b;
                wdc_cbor_builder_init(&b, req, cap);
                int32_t st = wdc_cbor_begin_map(&b, 4u);
                if (st == WDC_OK) { st = wdc_cbor_put_key_u32(&b, WDC_CBOR_KEY_RESOURCE_ID, resource_id); }
                if (st == WDC_OK) { st = wdc_cbor_put_key_text(&b, WDC_CBOR_KEY_METHOD, method); }
                if (st == WDC_OK) { st = wdc_cbor_put_key_text(&b, WDC_CBOR_KEY_URL, url); }
                if (st == WDC_OK) { st = wdc_cbor_put_key_bytes(&b, WDC_CBOR_KEY_DATA, body, sizeof(body)); }
                assert(st == WDC_OK);
                return wdc_cbor_len(&b);
            }

            int main(void) {
                const WdcDeviceProfile *profile = wdc_profile_builtin();
                assert(profile != NULL);
                assert(wdc_profile_validate_basic(profile) == WDC_OK);
                assert(wdc_diag_init() == WDC_OK);
                assert(wdc_events_init() == WDC_OK);
                wdc_host_call_reset_for_test();
                wdc_safety_reset_for_test();
                wdc_net_reset_for_test();

                assert(wdc_safety_init(profile) == WDC_OK);
                assert(wdc_net_init(profile) == WDC_OK);
                assert(wdc_safety_install_guarded_authorizer(profile, wdc_caps_builtin_relay_full()) == WDC_OK);
                assert(wdc_safety_mark_app_running("com.example.r8-network-smoke", 8u) == WDC_OK);

                uint8_t req[256];
                uint8_t rsp[128];
                uint32_t rsp_len = 0u;
                WdcCborBuilder empty;
                wdc_cbor_builder_init(&empty, req, sizeof(req));
                assert(wdc_cbor_begin_map(&empty, 0u) == WDC_OK);
                assert(wdc_host_call_dispatch(WDC_OP_NET_STATUS, req, wdc_cbor_len(&empty), rsp, sizeof(rsp), &rsp_len) == WDC_OK);
                assert(rsp_status(rsp, rsp_len) == WDC_OK);
                bool connected = true;
                assert(wdc_cbor_map_find_bool(rsp, rsp_len, WDC_CBOR_KEY_CONNECTED, &connected) == WDC_OK);
                assert(!connected);

                const uint8_t payload[] = {'o','k'};
                uint32_t req_len = mqtt_req(req, sizeof(req), WDC_R8_RESOURCE_MQTT_TELEMETRY, "devices/demo/telemetry", payload, sizeof(payload));
                rsp_len = 0u;
                assert(wdc_host_call_dispatch(WDC_OP_MQTT_PUBLISH, req, req_len, rsp, sizeof(rsp), &rsp_len) == WDC_OK);
                assert(rsp_status(rsp, rsp_len) == WDC_ERR_NOT_SYNCHRONIZED);

                assert(wdc_net_set_connected(true, "unit-test") == WDC_OK);
                req_len = mqtt_req(req, sizeof(req), WDC_R8_RESOURCE_MQTT_TELEMETRY, "devices/demo/telemetry", payload, sizeof(payload));
                rsp_len = 0u;
                assert(wdc_host_call_dispatch(WDC_OP_MQTT_PUBLISH, req, req_len, rsp, sizeof(rsp), &rsp_len) == WDC_OK);
                assert(rsp_status(rsp, rsp_len) == WDC_OK);

                req_len = sub_req(req, sizeof(req), WDC_R8_RESOURCE_MQTT_COMMANDS, "devices/demo/commands/#");
                rsp_len = 0u;
                assert(wdc_host_call_dispatch(WDC_OP_MQTT_SUBSCRIBE, req, req_len, rsp, sizeof(rsp), &rsp_len) == WDC_OK);
                assert(rsp_status(rsp, rsp_len) == WDC_OK);

                req_len = http_req(req, sizeof(req), WDC_R8_RESOURCE_HTTP_API, "POST", "https://api.example.invalid/devices/demo/state");
                rsp_len = 0u;
                assert(wdc_host_call_dispatch(WDC_OP_HTTP_REQUEST, req, req_len, rsp, sizeof(rsp), &rsp_len) == WDC_OK);
                assert(rsp_status(rsp, rsp_len) == WDC_OK);
                uint32_t http_status = 0u;
                assert(wdc_cbor_map_find_u32(rsp, rsp_len, WDC_CBOR_KEY_HTTP_STATUS, &http_status) == WDC_OK);
                assert(http_status == 202u);

                WdcNetStatus status;
                memset(&status, 0, sizeof(status));
                wdc_net_get_status(&status);
                assert(status.publish_count == 1u);
                assert(status.subscribe_count == 1u);
                assert(status.http_request_count == 1u);
                assert(status.last_publish.resource_id == WDC_R8_RESOURCE_MQTT_TELEMETRY);
                assert(strcmp(status.last_publish.topic, "devices/demo/telemetry") == 0);

                assert(wdc_safety_install_guarded_authorizer(profile, wdc_caps_builtin_relay_limited()) == WDC_OK);
                req_len = http_req(req, sizeof(req), WDC_R8_RESOURCE_HTTP_API, "POST", "https://api.example.invalid/devices/demo/state");
                rsp_len = 0u;
                assert(wdc_host_call_dispatch(WDC_OP_HTTP_REQUEST, req, req_len, rsp, sizeof(rsp), &rsp_len) == WDC_OK);
                assert(rsp_status(rsp, rsp_len) == WDC_ERR_CAPABILITY_DENIED);
                return 0;
            }
            '''
        )
        with tempfile.TemporaryDirectory() as tmp:
            cmd, exe = c_common_args(Path(tmp), program, "r8_network_smoke")
            subprocess.run(cmd, cwd=ROOT, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run([str(exe)], cwd=ROOT, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def test_r8_active_slot_runtime_source_smoke(self) -> None:
        if shutil.which("gcc") is None:
            self.skipTest("gcc not available")
        self.assertTrue(R8_BUNDLE.exists(), R8_BUNDLE)
        program = textwrap.dedent(
            r'''
            #include <assert.h>
            #include <stdint.h>
            #include <stdio.h>
            #include <stdlib.h>
            #include <string.h>
            #include "wdc_abi.h"
            #include "wdc_activation.h"
            #include "wdc_app.h"
            #include "wdc_bundle.h"
            #include "wdc_diag.h"
            #include "wdc_events.h"
            #include "wdc_net.h"
            #include "wdc_ota.h"
            #include "wdc_profile.h"
            #include "wdc_runtime.h"
            #include "wdc_safety.h"

            static uint8_t *read_file(const char *path, uint32_t *out_len) {
                FILE *f = fopen(path, "rb");
                assert(f != NULL);
                assert(fseek(f, 0, SEEK_END) == 0);
                long n = ftell(f);
                assert(n > 0 && n < 1024 * 1024);
                assert(fseek(f, 0, SEEK_SET) == 0);
                uint8_t *buf = (uint8_t *)malloc((size_t)n);
                assert(buf != NULL);
                assert(fread(buf, 1u, (size_t)n, f) == (size_t)n);
                fclose(f);
                *out_len = (uint32_t)n;
                return buf;
            }

            static int32_t rsp_status(const uint8_t *rsp, uint32_t rsp_len) {
                int32_t status = WDC_ERR_UNKNOWN;
                assert(wdc_cbor_map_find_i32(rsp, rsp_len, WDC_CBOR_KEY_STATUS, &status) == WDC_OK);
                return status;
            }

            static uint32_t mqtt_req(uint8_t *req, uint32_t cap, uint32_t resource_id) {
                const uint8_t payload[] = {'a','c','t','i','v','e'};
                WdcCborBuilder b;
                wdc_cbor_builder_init(&b, req, cap);
                int32_t st = wdc_cbor_begin_map(&b, 4u);
                if (st == WDC_OK) { st = wdc_cbor_put_key_u32(&b, WDC_CBOR_KEY_RESOURCE_ID, resource_id); }
                if (st == WDC_OK) { st = wdc_cbor_put_key_text(&b, WDC_CBOR_KEY_TOPIC, "devices/demo/telemetry"); }
                if (st == WDC_OK) { st = wdc_cbor_put_key_bytes(&b, WDC_CBOR_KEY_DATA, payload, sizeof(payload)); }
                if (st == WDC_OK) { st = wdc_cbor_put_key_u32(&b, WDC_CBOR_KEY_QOS, 0u); }
                assert(st == WDC_OK);
                return wdc_cbor_len(&b);
            }

            int main(int argc, char **argv) {
                assert(argc == 2);
                const WdcDeviceProfile *profile = wdc_profile_builtin();
                assert(profile != NULL);
                assert(wdc_profile_validate_basic(profile) == WDC_OK);
                assert(wdc_diag_init() == WDC_OK);
                assert(wdc_events_init() == WDC_OK);
                wdc_host_call_reset_for_test();
                wdc_safety_reset_for_test();
                wdc_net_reset_for_test();
                wdc_ota_host_clear_slots();
                wdc_ota_host_clear_metadata();

                assert(wdc_safety_init(profile) == WDC_OK);
                assert(wdc_net_init(profile) == WDC_OK);
                assert(wdc_net_set_connected(true, "active-slot-smoke") == WDC_OK);

                uint32_t bundle_len = 0u;
                uint8_t *bundle = read_file(argv[1], &bundle_len);
                WdcBundleVerifyPolicy verify_policy = wdc_bundle_make_default_dev_policy(profile);
                WdcBundleVerifyResult verify;
                memset(&verify, 0, sizeof(verify));
                assert(wdc_bundle_verify(bundle, bundle_len, &verify_policy, &verify) == WDC_OK);
                assert(verify.capabilities_ok);
                assert(verify.exports_ok);

                WdcBundleMetadataV1 metadata;
                wdc_bundle_metadata_init(&metadata);
                assert(wdc_bundle_metadata_mark_verified(&metadata, WDC_BUNDLE_SLOT_A, &verify) == WDC_OK);
                metadata.slot_a.state = WDC_SLOT_CONFIRMED;
                metadata.active_slot = WDC_BUNDLE_SLOT_A;
                metadata.last_good_slot = WDC_BUNDLE_SLOT_A;
                assert(wdc_bundle_metadata_seal(&metadata) == WDC_OK);
                assert(wdc_ota_host_set_slot_image(WDC_BUNDLE_SLOT_A, bundle, bundle_len) == WDC_OK);
                assert(wdc_ota_host_set_metadata(&metadata) == WDC_OK);

                WdcBundleMetadataV1 loaded;
                assert(wdc_ota_read_metadata(&loaded) == WDC_OK);
                WdcActivationPolicy activation_policy = wdc_activation_default_policy();
                activation_policy.max_candidate_boots = 1u;
                activation_policy.required_health_checks = 1u;
                WdcRuntimeConfig runtime_config = wdc_runtime_default_config();
                WdcRuntime runtime;
                memset(&runtime, 0, sizeof(runtime));
                uint8_t boot_buffer[4096];
                WdcAppBootReport report;
                memset(&report, 0, sizeof(report));
                assert(wdc_app_boot_active_slot(profile,
                                                &loaded,
                                                &activation_policy,
                                                &verify_policy,
                                                &runtime,
                                                &runtime_config,
                                                boot_buffer,
                                                sizeof(boot_buffer),
                                                &report) == WDC_OK);
                assert(report.used_active_slot);
                assert(report.selected_slot == WDC_BUNDLE_SLOT_A);
                assert(report.bundle_version == 8u);
                assert(strcmp(report.bundle_id, "com.example.relay-controller") == 0);
                assert(report.runtime_report.backend == WDC_RUNTIME_BACKEND_HOST_STUB);
                assert(report.runtime_report.init_called);
                assert(report.runtime_report.health_called);
                assert(report.runtime_report.outcome == WDC_RUNTIME_OUTCOME_OK);

                WdcSafetyStatus safety;
                memset(&safety, 0, sizeof(safety));
                wdc_safety_get_status(&safety);
                assert(safety.state == WDC_SAFETY_STATE_APP_RUNNING);
                assert(safety.active_bundle_version == 8u);

                uint8_t req[160];
                uint8_t rsp[96];
                uint32_t req_len = mqtt_req(req, sizeof(req), WDC_R8_RESOURCE_MQTT_TELEMETRY);
                uint32_t rsp_len = 0u;
                assert(wdc_host_call_dispatch(WDC_OP_MQTT_PUBLISH, req, req_len, rsp, sizeof(rsp), &rsp_len) == WDC_OK);
                assert(rsp_status(rsp, rsp_len) == WDC_OK);
                WdcNetStatus net;
                memset(&net, 0, sizeof(net));
                wdc_net_get_status(&net);
                assert(net.publish_count == 1u);
                assert(net.last_publish.resource_id == WDC_R8_RESOURCE_MQTT_TELEMETRY);

                WdcBundleMetadataV1 persisted;
                assert(wdc_ota_read_metadata(&persisted) == WDC_OK);
                assert(persisted.active_slot == WDC_BUNDLE_SLOT_A);
                assert(persisted.last_good_slot == WDC_BUNDLE_SLOT_A);
                assert(persisted.slot_a.state == WDC_SLOT_CONFIRMED);

                wdc_runtime_teardown(&runtime);
                free(bundle);
                return 0;
            }
            '''
        )
        with tempfile.TemporaryDirectory() as tmp:
            cmd, exe = c_common_args(Path(tmp), program, "r8_active_slot_smoke")
            subprocess.run(cmd, cwd=ROOT, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run([str(exe), str(R8_BUNDLE)], cwd=ROOT, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    unittest.main()
