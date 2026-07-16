from __future__ import annotations

import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FW = ROOT / "firmware"


class R4EventsProfileCapsTests(unittest.TestCase):
    def test_r4_files_and_symbols_exist(self) -> None:
        files = [
            "firmware/components/wdc_caps/CMakeLists.txt",
            "firmware/components/wdc_caps/wdc_caps.c",
            "firmware/components/wdc_caps/include/wdc_caps.h",
            "firmware/components/wdc_events/wdc_event_encode.c",
        ]
        for rel in files:
            self.assertTrue((ROOT / rel).exists(), rel)

        abi = (FW / "components/wdc_abi/include/wdc_abi.h").read_text(encoding="utf-8")
        for token in [
            'WDC_R4_SHELL_VERSION "0.1.0-r4"',
            'WDC_R4_BUILD_STAGE   "R4"',
            "WDC_EVENT_MODULE_PROBATION_STARTED",
            "WDC_CBOR_KEY_EVENT_TYPE",
            "WDC_CBOR_KEY_TIMESTAMP_MS",
            "WdcHostAuthorizeFn",
            "wdc_host_call_set_authorizer",
            "wdc_opcode_supported_r4",
        ]:
            self.assertIn(token, abi)

        shell = (FW / "main/shell_main.c").read_text(encoding="utf-8")
        for token in [
            "wdc_caps_install_host_authorizer",
            "wdc_shell_run_r4_capability_self_test",
            "wdc_runtime_dispatch_event",
            "wdc_shell_log_last_audit",
        ]:
            self.assertIn(token, shell)

    def test_r4_native_events_caps_and_runtime_smoke(self) -> None:
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
            #include "wdc_profile.h"
            #include "wdc_runtime.h"
            #include "wdc_static_wasm.h"

            static int32_t response_status(const uint8_t *rsp, uint32_t rsp_len) {
                int32_t status = 1234;
                assert(wdc_cbor_map_find_i32(rsp, rsp_len, WDC_CBOR_KEY_STATUS, &status) == WDC_OK);
                return status;
            }

            static uint32_t gpio_req(uint8_t *req, uint32_t cap, uint32_t resource_id, bool value) {
                WdcCborBuilder b;
                wdc_cbor_builder_init(&b, req, cap);
                assert(wdc_cbor_begin_map(&b, 2u) == WDC_OK);
                assert(wdc_cbor_put_key_u32(&b, WDC_CBOR_KEY_RESOURCE_ID, resource_id) == WDC_OK);
                assert(wdc_cbor_put_key_bool(&b, WDC_CBOR_KEY_VALUE, value) == WDC_OK);
                return wdc_cbor_len(&b);
            }

            int main(void) {
                assert(wdc_diag_init() == WDC_OK);
                wdc_host_call_reset_for_test();

                const WdcDeviceProfile *profile = wdc_profile_builtin();
                assert(wdc_profile_validate_basic(profile) == WDC_OK);
                const WdcProfileResource *relay = wdc_profile_find_resource_by_name(profile, WDC_RESOURCE_KIND_GPIO, "relay_1");
                const WdcProfileResource *status_led = wdc_profile_find_resource_by_id(profile, WDC_R4_RESOURCE_STATUS_LED);
                assert(relay != 0 && relay->resource_id == WDC_R4_RESOURCE_RELAY_1);
                assert(status_led != 0 && strcmp(status_led->name, "status_led") == 0);
                assert(profile->resource_count >= 6u);

                assert(wdc_caps_install_host_authorizer(profile, wdc_caps_builtin_relay_limited()) == WDC_OK);

                uint8_t req[96];
                uint8_t rsp[128];
                uint32_t rsp_len = 0u;
                uint32_t req_len = gpio_req(req, sizeof(req), WDC_R4_RESOURCE_RELAY_1, true);
                assert(wdc_host_call_dispatch(WDC_OP_GPIO_SET, req, req_len, rsp, sizeof(rsp), &rsp_len) == WDC_OK);
                assert(response_status(rsp, rsp_len) == WDC_OK);
                WdcCapabilityAuditRecord audit;
                wdc_caps_last_audit(&audit);
                assert(strcmp(audit.decision, "allowed") == 0);
                assert(strstr(audit.bundle, "com.example.relay-controller-r4-limited") != 0);
                assert(audit.bundle_version == 4u);
                assert(strcmp(audit.resource_name, "relay_1") == 0);
                assert(strcmp(audit.capability, "gpio.write:relay_1") == 0);

                req_len = gpio_req(req, sizeof(req), WDC_R4_RESOURCE_STATUS_LED, false);
                assert(wdc_host_call_dispatch(WDC_OP_GPIO_SET, req, req_len, rsp, sizeof(rsp), &rsp_len) == WDC_OK);
                assert(response_status(rsp, rsp_len) == WDC_ERR_CAPABILITY_DENIED);
                wdc_caps_last_audit(&audit);
                assert(strcmp(audit.decision, "denied") == 0);
                assert(strcmp(audit.resource_name, "status_led") == 0);
                assert(strcmp(audit.capability, "gpio.write:status_led") == 0);

                req_len = gpio_req(req, sizeof(req), 999u, false);
                assert(wdc_host_call_dispatch(WDC_OP_GPIO_SET, req, req_len, rsp, sizeof(rsp), &rsp_len) == WDC_OK);
                assert(response_status(rsp, rsp_len) == WDC_ERR_INVALID_RESOURCE);

                const uint8_t payload[] = {1u, 0u};
                WdcEvent event;
                assert(wdc_event_make(&event, WDC_EVENT_GPIO_CHANGED, WDC_R4_RESOURCE_BUTTON_1, 1234567890123ull, payload, 2u) == WDC_OK);
                event.event_id = 42u;
                uint8_t encoded[160];
                uint32_t encoded_len = 0u;
                assert(wdc_event_encode_cbor(&event, encoded, sizeof(encoded), &encoded_len) == WDC_OK);
                assert(encoded_len > 0u);
                WdcEvent decoded;
                assert(wdc_event_decode_cbor(encoded, encoded_len, &decoded) == WDC_OK);
                assert(decoded.abi_major == WDC_ABI_MAJOR);
                assert(decoded.event_type == WDC_EVENT_GPIO_CHANGED);
                assert(decoded.event_id == 42u);
                assert(decoded.resource_id == WDC_R4_RESOURCE_BUTTON_1);
                assert(decoded.timestamp_ms == 1234567890123ull);
                assert(decoded.payload_len == 2u && decoded.payload[0] == 1u);

                WdcEventQueue queue;
                assert(wdc_event_queue_init(&queue) == WDC_OK);
                for (uint32_t i = 0u; i < WDC_EVENT_QUEUE_CAPACITY_DEFAULT; ++i) {
                    event.event_id = 0u;
                    assert(wdc_event_queue_push(&queue, &event) == WDC_OK);
                }
                assert(wdc_event_queue_push(&queue, &event) == WDC_ERR_BUSY);
                assert(wdc_event_queue_dropped(&queue) == 1u);

                WdcRuntimeConfig cfg = wdc_runtime_default_config();
                WdcRuntime runtime;
                assert(wdc_runtime_init(&runtime, &cfg) == WDC_OK);
                assert(wdc_runtime_load_static(&runtime, wdc_static_hello_wasm, wdc_static_hello_wasm_len) == WDC_OK);
                assert(wdc_runtime_lookup_exports(&runtime) == WDC_OK);
                assert(wdc_runtime_call_init(&runtime) == WDC_OK);
                assert(wdc_runtime_dispatch_event(&runtime, &event) == WDC_OK);
                const WdcRuntimeReport *report = wdc_runtime_get_report(&runtime);
                assert(report != 0 && report->on_event_called);
                wdc_runtime_teardown(&runtime);

                assert(wdc_runtime_init(&runtime, &cfg) == WDC_OK);
                assert(wdc_runtime_load_static(&runtime, wdc_static_event_fail_wasm, wdc_static_event_fail_wasm_len) == WDC_OK);
                assert(wdc_runtime_lookup_exports(&runtime) == WDC_OK);
                assert(wdc_runtime_call_init(&runtime) == WDC_OK);
                assert(wdc_runtime_dispatch_event(&runtime, &event) == WDC_ERR_CONTRACT_VIOLATION);
                report = wdc_runtime_get_report(&runtime);
                assert(report != 0 && report->outcome == WDC_RUNTIME_OUTCOME_GUEST_NON_OK_STATUS);
                wdc_runtime_teardown(&runtime);

                assert(wdc_runtime_init(&runtime, &cfg) == WDC_OK);
                assert(wdc_runtime_load_static(&runtime, wdc_static_event_trap_wasm, wdc_static_event_trap_wasm_len) == WDC_OK);
                assert(wdc_runtime_lookup_exports(&runtime) == WDC_OK);
                assert(wdc_runtime_call_init(&runtime) == WDC_OK);
                assert(wdc_runtime_dispatch_event(&runtime, &event) == WDC_ERR_CONTRACT_VIOLATION);
                report = wdc_runtime_get_report(&runtime);
                assert(report != 0 && report->outcome == WDC_RUNTIME_OUTCOME_GUEST_TRAPPED);
                wdc_runtime_teardown(&runtime);

                wdc_caps_clear_host_authorizer();
                return 0;
            }
            '''
        )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            test_c = tmp_path / "r4_native_smoke.c"
            test_c.write_text(program, encoding="utf-8")
            exe = tmp_path / "r4_native_smoke"
            include_args = [
                "-I", str(FW / "components/wdc_abi/include"),
                "-I", str(FW / "components/wdc_caps/include"),
                "-I", str(FW / "components/wdc_diag/include"),
                "-I", str(FW / "components/wdc_events/include"),
                "-I", str(FW / "components/wdc_profile/include"),
                "-I", str(FW / "components/wdc_runtime/include"),
            ]
            sources = [
                FW / "components/wdc_abi/wdc_errors.c",
                FW / "components/wdc_abi/wdc_cbor.c",
                FW / "components/wdc_abi/wdc_pointer.c",
                FW / "components/wdc_abi/wdc_host_call.c",
                FW / "components/wdc_caps/wdc_caps.c",
                FW / "components/wdc_diag/wdc_diag.c",
                FW / "components/wdc_events/wdc_event_queue.c",
                FW / "components/wdc_events/wdc_event_encode.c",
                FW / "components/wdc_profile/wdc_profile_static.c",
                FW / "components/wdc_runtime/wdc_runtime.c",
                FW / "components/wdc_runtime/wdc_static_wasm.c",
                test_c,
            ]
            subprocess.run(
                ["gcc", "-std=c11", "-Wall", "-Wextra", "-Werror", *include_args, *map(str, sources), "-o", str(exe)],
                check=True,
            )
            subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    unittest.main()
