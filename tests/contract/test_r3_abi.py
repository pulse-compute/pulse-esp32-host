from __future__ import annotations

import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FW = ROOT / "firmware"
ABI = FW / "components/wdc_abi"


class R3AbiBoundaryTests(unittest.TestCase):
    def test_r3_abi_files_and_symbols_exist(self) -> None:
        header = (ABI / "include/wdc_abi.h").read_text(encoding="utf-8")
        for token in [
            'WDC_R3_SHELL_VERSION "0.1.0-r3"',
            'WDC_R3_BUILD_STAGE   "R3"',
            "WdcGuestMemory",
            "WdcCborBuilder",
            "wdc_cbor_begin_map",
            "wdc_host_call_dispatch",
            "wdc_host_call_from_guest_memory",
            "wdc_opcode_supported_r3",
            "WDC_CBOR_KEY_RESOURCE_ID",
            "WDC_CBOR_KEY_TIMER_ID",
        ]:
            self.assertIn(token, header)

        cmake = (ABI / "CMakeLists.txt").read_text(encoding="utf-8")
        self.assertIn("wdc_cbor.c", cmake)
        self.assertIn("wdc_host_call.c", cmake)

    def test_r3_native_dispatcher_compiles_and_enforces_contract(self) -> None:
        if shutil.which("gcc") is None:
            self.skipTest("gcc not available")

        program = textwrap.dedent(
            r'''
            #include <assert.h>
            #include <stdbool.h>
            #include <stdint.h>
            #include <string.h>
            #include "wdc_abi.h"

            static int32_t response_status(const uint8_t *rsp, uint32_t rsp_len) {
                int32_t status = 1234;
                assert(wdc_cbor_map_find_i32(rsp, rsp_len, WDC_CBOR_KEY_STATUS, &status) == WDC_OK);
                return status;
            }

            static int32_t allow_all_authorizer(void *ctx, uint32_t opcode, const uint8_t *request, uint32_t request_len, int32_t *decision) {
                (void)ctx;
                (void)opcode;
                (void)request;
                (void)request_len;
                *decision = WDC_OK;
                return WDC_OK;
            }

            static uint32_t build_gpio_req(uint8_t *req, uint32_t cap, uint32_t resource_id, bool include_value, bool value) {
                WdcCborBuilder b;
                wdc_cbor_builder_init(&b, req, cap);
                assert(wdc_cbor_begin_map(&b, include_value ? 2u : 1u) == WDC_OK);
                assert(wdc_cbor_put_key_u32(&b, WDC_CBOR_KEY_RESOURCE_ID, resource_id) == WDC_OK);
                if (include_value) {
                    assert(wdc_cbor_put_key_bool(&b, WDC_CBOR_KEY_VALUE, value) == WDC_OK);
                }
                return wdc_cbor_len(&b);
            }

            int main(void) {
                uint8_t req[160];
                uint8_t rsp[256];
                uint8_t mem[512];
                uint32_t req_len = 0u;
                uint32_t rsp_len = 0u;
                WdcCborBuilder b;

                memset(req, 0, sizeof(req));
                memset(rsp, 0, sizeof(rsp));
                memset(mem, 0, sizeof(mem));
                wdc_host_call_reset_for_test();

                assert(wdc_opcode_supported_r3(WDC_OP_SYS_GET_INFO));
                assert(wdc_opcode_supported_r3(WDC_OP_GPIO_SET));
                assert(!wdc_opcode_supported_r3(WDC_OP_MQTT_PUBLISH));

                assert(wdc_host_call_dispatch(WDC_OP_SYS_GET_INFO, NULL, 0u, rsp, sizeof(rsp), &rsp_len) == WDC_OK);
                assert(rsp_len > 0u);
                assert(response_status(rsp, rsp_len) == WDC_OK);
                uint32_t abi_major = 0u;
                uint32_t abi_minor = 999u;
                assert(wdc_cbor_map_find_u32(rsp, rsp_len, WDC_CBOR_KEY_ABI_MAJOR, &abi_major) == WDC_OK);
                assert(wdc_cbor_map_find_u32(rsp, rsp_len, WDC_CBOR_KEY_ABI_MINOR, &abi_minor) == WDC_OK);
                assert(abi_major == WDC_ABI_MAJOR);
                assert(abi_minor == WDC_ABI_MINOR);
                WdcCborText text;
                assert(wdc_cbor_map_find_text(rsp, rsp_len, WDC_CBOR_KEY_BUILD_STAGE, &text) == WDC_OK);
                assert(text.len == 2u && memcmp(text.ptr, "R9", 2u) == 0);

                wdc_host_call_set_authorizer(allow_all_authorizer, NULL);

                wdc_cbor_builder_init(&b, req, sizeof(req));
                assert(wdc_cbor_begin_map(&b, 3u) == WDC_OK);
                assert(wdc_cbor_put_key_u32(&b, WDC_CBOR_KEY_TIMER_ID, 7u) == WDC_OK);
                assert(wdc_cbor_put_key_u32(&b, WDC_CBOR_KEY_DELAY_MS, 1000u) == WDC_OK);
                assert(wdc_cbor_put_key_bool(&b, WDC_CBOR_KEY_REPEAT, true) == WDC_OK);
                req_len = wdc_cbor_len(&b);
                assert(wdc_host_call_dispatch(WDC_OP_TIMER_SET, req, req_len, rsp, sizeof(rsp), &rsp_len) == WDC_OK);
                assert(response_status(rsp, rsp_len) == WDC_OK);

                wdc_cbor_builder_init(&b, req, sizeof(req));
                assert(wdc_cbor_begin_map(&b, 1u) == WDC_OK);
                assert(wdc_cbor_put_key_u32(&b, WDC_CBOR_KEY_TIMER_ID, 7u) == WDC_OK);
                req_len = wdc_cbor_len(&b);
                assert(wdc_host_call_dispatch(WDC_OP_TIMER_CANCEL, req, req_len, rsp, sizeof(rsp), &rsp_len) == WDC_OK);
                assert(response_status(rsp, rsp_len) == WDC_OK);

                req_len = build_gpio_req(req, sizeof(req), WDC_R3_RESOURCE_RELAY_1, true, true);
                assert(wdc_host_call_dispatch(WDC_OP_GPIO_SET, req, req_len, rsp, sizeof(rsp), &rsp_len) == WDC_OK);
                assert(response_status(rsp, rsp_len) == WDC_OK);

                req_len = build_gpio_req(req, sizeof(req), WDC_R3_RESOURCE_RELAY_1, false, false);
                assert(wdc_host_call_dispatch(WDC_OP_GPIO_GET, req, req_len, rsp, sizeof(rsp), &rsp_len) == WDC_OK);
                assert(response_status(rsp, rsp_len) == WDC_OK);
                uint32_t relay_value = 0u;
                assert(wdc_cbor_map_find_u32(rsp, rsp_len, WDC_CBOR_KEY_VALUE, &relay_value) == WDC_OK);
                assert(relay_value == 1u);

                req_len = build_gpio_req(req, sizeof(req), WDC_R3_RESOURCE_BUTTON_1, true, false);
                assert(wdc_host_call_dispatch(WDC_OP_GPIO_SET, req, req_len, rsp, sizeof(rsp), &rsp_len) == WDC_OK);
                assert(response_status(rsp, rsp_len) == WDC_ERR_INVALID_RESOURCE);

                wdc_cbor_builder_init(&b, req, sizeof(req));
                assert(wdc_cbor_begin_map(&b, 2u) == WDC_OK);
                assert(wdc_cbor_put_key_text(&b, WDC_CBOR_KEY_KEY, "app.mode") == WDC_OK);
                static const uint8_t mode[] = {'a', 'u', 't', 'o'};
                assert(wdc_cbor_put_key_bytes(&b, WDC_CBOR_KEY_DATA, mode, sizeof(mode)) == WDC_OK);
                req_len = wdc_cbor_len(&b);
                assert(wdc_host_call_dispatch(WDC_OP_CONFIG_SET, req, req_len, rsp, sizeof(rsp), &rsp_len) == WDC_OK);
                assert(response_status(rsp, rsp_len) == WDC_OK);

                wdc_cbor_builder_init(&b, req, sizeof(req));
                assert(wdc_cbor_begin_map(&b, 1u) == WDC_OK);
                assert(wdc_cbor_put_key_text(&b, WDC_CBOR_KEY_KEY, "app.mode") == WDC_OK);
                req_len = wdc_cbor_len(&b);
                assert(wdc_host_call_dispatch(WDC_OP_CONFIG_GET, req, req_len, rsp, sizeof(rsp), &rsp_len) == WDC_OK);
                assert(response_status(rsp, rsp_len) == WDC_OK);
                WdcCborBytes bytes;
                assert(wdc_cbor_map_find_bytes(rsp, rsp_len, WDC_CBOR_KEY_DATA, &bytes) == WDC_OK);
                assert(bytes.len == sizeof(mode));
                assert(memcmp(bytes.ptr, mode, sizeof(mode)) == 0);

                WdcGuestMemory gm = { .base = mem, .len = sizeof(mem), .max_request_bytes = 64u, .max_response_bytes = 128u };
                mem[8] = 0xa0u;
                assert(wdc_host_call_from_guest_memory(&gm, WDC_OP_SYS_GET_INFO, 8u, 1u, 64u, 128u, &rsp_len) == WDC_OK);
                assert(rsp_len > 0u);
                assert(wdc_host_call_from_guest_memory(&gm, WDC_OP_SYS_GET_INFO, 500u, 16u, 64u, 128u, &rsp_len) == WDC_ERR_BAD_POINTER);
                assert(wdc_host_call_from_guest_memory(&gm, WDC_OP_SYS_GET_INFO, 8u, 65u, 64u, 128u, &rsp_len) == WDC_ERR_BAD_LENGTH);

                assert(wdc_host_call_dispatch(0x9999u, NULL, 0u, rsp, sizeof(rsp), &rsp_len) == WDC_ERR_UNSUPPORTED_OPCODE);
                assert(wdc_host_call_dispatch(WDC_OP_GPIO_GET, req, req_len, NULL, 1u, &rsp_len) == WDC_ERR_BAD_POINTER);
                assert(wdc_host_call_dispatch(WDC_OP_GPIO_GET, (const uint8_t *)"bad", 3u, rsp, sizeof(rsp), &rsp_len) == WDC_ERR_BAD_ENCODING);
                return 0;
            }
            '''
        )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            test_c = tmp_path / "r3_abi_smoke.c"
            test_c.write_text(program, encoding="utf-8")
            exe = tmp_path / "r3_abi_smoke"
            include_args = ["-I", str(ABI / "include")]
            sources = [
                ABI / "wdc_errors.c",
                ABI / "wdc_cbor.c",
                ABI / "wdc_host_call.c",
                test_c,
            ]
            subprocess.run(
                ["gcc", "-std=c11", "-Wall", "-Wextra", "-Werror", *include_args, *map(str, sources), "-o", str(exe)],
                check=True,
            )
            subprocess.run([str(exe)], check=True)

    def test_guest_sdks_contain_r3_wrappers_and_matching_keys(self) -> None:
        rust_abi = (ROOT / "guest-sdk/rust/wdc_guest/src/abi.rs").read_text(encoding="utf-8")
        rust_host = (ROOT / "guest-sdk/rust/wdc_guest/src/host.rs").read_text(encoding="utf-8")
        rust_encoding = (ROOT / "guest-sdk/rust/wdc_guest/src/encoding.rs").read_text(encoding="utf-8")
        c_guest = (ROOT / "guest-sdk/c/include/wdc_guest.h").read_text(encoding="utf-8")

        for key, value in {
            "WDC_CBOR_KEY_STATUS": 0,
            "WDC_CBOR_KEY_RESOURCE_ID": 3,
            "WDC_CBOR_KEY_VALUE": 4,
            "WDC_CBOR_KEY_TIMER_ID": 5,
            "WDC_CBOR_KEY_DATA": 9,
            "WDC_CBOR_KEY_BUILD_STAGE": 10,
            "WDC_CBOR_KEY_SHELL_VERSION": 11,
        }.items():
            self.assertRegex(rust_abi, rf"pub const {key}: u32 = {value};")
            self.assertRegex(c_guest, rf"#define {key}\s+{value}u")

        for token in ["sys_get_info", "timer_set", "timer_cancel", "gpio_set", "gpio_get", "config_set", "config_get"]:
            self.assertIn(token, rust_host)
        for token in ["Encoder", "find_u32", "find_i32", "find_bytes", "find_text"]:
            self.assertIn(token, rust_encoding)
        for token in ["wdc_guest_timer_set", "wdc_guest_gpio_set", "wdc_guest_gpio_get", "wdc_guest_config_set"]:
            self.assertIn(token, c_guest)


if __name__ == "__main__":
    unittest.main()
