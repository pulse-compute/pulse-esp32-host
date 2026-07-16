from __future__ import annotations

import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FW = ROOT / "firmware"


class R5SafetyHardwareTests(unittest.TestCase):
    def test_r5_files_and_symbols_exist(self) -> None:
        files = [
            "firmware/components/wdc_safety/CMakeLists.txt",
            "firmware/components/wdc_safety/wdc_safety.c",
            "firmware/components/wdc_safety/include/wdc_safety.h",
            "firmware/components/wdc_hal/wdc_gpio_espidf.c",
            "tools/check_r5.py",
        ]
        for rel in files:
            self.assertTrue((ROOT / rel).exists(), rel)

        abi = (FW / "components/wdc_abi/include/wdc_abi.h").read_text(encoding="utf-8")
        for token in [
            'WDC_R5_SHELL_VERSION "0.1.0-r5"',
            'WDC_R5_BUILD_STAGE   "R5"',
            "WDC_EVENT_SAFETY_STATE_CHANGED",
            "WDC_EVENT_PHYSICAL_ACTION",
            "WdcHostGpioWriteFn",
            "wdc_host_call_set_gpio_hooks",
        ]:
            self.assertIn(token, abi)

        shell = (FW / "main/shell_main.c").read_text(encoding="utf-8")
        for token in [
            "wdc_safety_init",
            "wdc_safety_install_guarded_authorizer",
            "wdc_shell_run_r5_safety_self_test",
            "wdc_safety_stop_app",
            "R5 safety self-test passed",
        ]:
            self.assertIn(token, shell)

    def test_r5_native_safety_hardware_smoke(self) -> None:
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
            #include "wdc_gpio.h"
            #include "wdc_profile.h"
            #include "wdc_runtime.h"
            #include "wdc_safety.h"

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

            static void assert_level(const WdcDeviceProfile *profile, uint32_t resource_id, uint32_t expected) {
                uint32_t level = 99u;
                assert(wdc_hal_gpio_get_level_by_resource(profile, resource_id, &level) == WDC_OK);
                assert(level == expected);
            }

            int main(void) {
                assert(wdc_diag_init() == WDC_OK);
                assert(wdc_events_init() == WDC_OK);
                wdc_host_call_reset_for_test();
                wdc_safety_reset_for_test();

                const WdcDeviceProfile *profile = wdc_profile_builtin();
                assert(wdc_profile_validate_basic(profile) == WDC_OK);

                assert(wdc_safety_init(profile) == WDC_OK);
                assert(wdc_hal_safe_gpio_defaults_applied() == 2u);
                assert(wdc_safety_physical_outputs_safe());
                assert_level(profile, WDC_R4_RESOURCE_RELAY_1, 0u);
                assert_level(profile, WDC_R4_RESOURCE_STATUS_LED, 1u);

                WdcSafetyStatus safety;
                wdc_safety_get_status(&safety);
                assert(safety.state == WDC_SAFETY_STATE_BOOT_SAFE);
                assert(safety.physical_outputs_safe);

                assert(wdc_safety_install_guarded_authorizer(profile, wdc_caps_builtin_relay_limited()) == WDC_OK);
                assert(wdc_safety_mark_app_running("com.example.r5-test", 5u) == WDC_OK);
                wdc_safety_get_status(&safety);
                assert(safety.state == WDC_SAFETY_STATE_APP_RUNNING);
                assert(strcmp(safety.active_bundle, "com.example.r5-test") == 0);

                uint8_t req[96];
                uint8_t rsp[128];
                uint32_t rsp_len = 0u;
                uint32_t req_len = gpio_req(req, sizeof(req), WDC_R4_RESOURCE_RELAY_1, true);
                assert(wdc_host_call_dispatch(WDC_OP_GPIO_SET, req, req_len, rsp, sizeof(rsp), &rsp_len) == WDC_OK);
                assert(response_status(rsp, rsp_len) == WDC_OK);
                assert_level(profile, WDC_R4_RESOURCE_RELAY_1, 1u);

                req_len = gpio_req(req, sizeof(req), WDC_R4_RESOURCE_STATUS_LED, false);
                assert(wdc_host_call_dispatch(WDC_OP_GPIO_SET, req, req_len, rsp, sizeof(rsp), &rsp_len) == WDC_OK);
                assert(response_status(rsp, rsp_len) == WDC_ERR_CAPABILITY_DENIED);
                assert_level(profile, WDC_R4_RESOURCE_STATUS_LED, 1u);
                wdc_safety_get_status(&safety);
                assert(safety.denied_by_capability_count == 1u);

                WdcRuntimeReport report;
                memset(&report, 0, sizeof(report));
                report.outcome = WDC_RUNTIME_OUTCOME_GUEST_TRAPPED;
                report.last_status = WDC_ERR_CONTRACT_VIOLATION;
                assert(wdc_safety_stop_app(WDC_SAFETY_FAULT_CONTRACT_VIOLATION,
                                           WDC_ERR_CONTRACT_VIOLATION,
                                           "simulated trap",
                                           &report) == WDC_OK);
                wdc_safety_get_status(&safety);
                assert(safety.state == WDC_SAFETY_STATE_APP_FAULT_STOPPED);
                assert(safety.last_fault_kind == WDC_SAFETY_FAULT_RUNTIME_TRAP);
                assert(safety.fault_count == 1u);
                assert(safety.physical_outputs_safe);
                assert_level(profile, WDC_R4_RESOURCE_RELAY_1, 0u);

                req_len = gpio_req(req, sizeof(req), WDC_R4_RESOURCE_RELAY_1, true);
                rsp_len = 0u;
                assert(wdc_host_call_dispatch(WDC_OP_GPIO_SET, req, req_len, rsp, sizeof(rsp), &rsp_len) == WDC_OK);
                assert(response_status(rsp, rsp_len) == WDC_ERR_INVALID_STATE);
                assert_level(profile, WDC_R4_RESOURCE_RELAY_1, 0u);
                wdc_safety_get_status(&safety);
                assert(safety.denied_while_stopped_count == 1u);

                assert(wdc_safety_mark_app_running("com.example.r5-test", 6u) == WDC_OK);
                assert(wdc_host_call_dispatch(WDC_OP_GPIO_SET, req, req_len, rsp, sizeof(rsp), &rsp_len) == WDC_OK);
                assert(response_status(rsp, rsp_len) == WDC_OK);
                assert_level(profile, WDC_R4_RESOURCE_RELAY_1, 1u);

                assert(wdc_safety_enter_no_bundle_mode("test complete") == WDC_OK);
                wdc_safety_get_status(&safety);
                assert(safety.state == WDC_SAFETY_STATE_NO_BUNDLE);
                assert(safety.physical_outputs_safe);
                assert_level(profile, WDC_R4_RESOURCE_RELAY_1, 0u);

                assert(wdc_host_call_dispatch(WDC_OP_GPIO_SET, req, req_len, rsp, sizeof(rsp), &rsp_len) == WDC_OK);
                assert(response_status(rsp, rsp_len) == WDC_ERR_INVALID_STATE);
                assert_level(profile, WDC_R4_RESOURCE_RELAY_1, 0u);

                wdc_safety_clear_guarded_authorizer();
                return 0;
            }
            '''
        )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            test_c = tmp_path / "r5_native_safety_smoke.c"
            test_c.write_text(program, encoding="utf-8")
            exe = tmp_path / "r5_native_safety_smoke"
            include_args = [
                "-I", str(FW / "components/wdc_abi/include"),
                "-I", str(FW / "components/wdc_caps/include"),
                "-I", str(FW / "components/wdc_diag/include"),
                "-I", str(FW / "components/wdc_events/include"),
                "-I", str(FW / "components/wdc_hal/include"),
                "-I", str(FW / "components/wdc_profile/include"),
                "-I", str(FW / "components/wdc_runtime/include"),
                "-I", str(FW / "components/wdc_safety/include"),
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
                FW / "components/wdc_hal/wdc_gpio_espidf.c",
                FW / "components/wdc_profile/wdc_profile_static.c",
                FW / "components/wdc_runtime/wdc_runtime.c",
                FW / "components/wdc_safety/wdc_safety.c",
                test_c,
            ]
            subprocess.run(
                ["gcc", "-std=c11", "-Wall", "-Wextra", "-Werror", *include_args, *map(str, sources), "-o", str(exe)],
                check=True,
            )
            subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    unittest.main()
