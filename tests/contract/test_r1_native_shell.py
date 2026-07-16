from __future__ import annotations

import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FW = ROOT / "firmware"


class R1NativeShellTests(unittest.TestCase):
    def test_r1_component_files_exist(self) -> None:
        required = [
            "firmware/components/wdc_diag/include/wdc_diag.h",
            "firmware/components/wdc_diag/wdc_diag.c",
            "firmware/components/wdc_events/include/wdc_events.h",
            "firmware/components/wdc_events/wdc_event_queue.c",
            "firmware/components/wdc_profile/include/wdc_profile.h",
            "firmware/components/wdc_profile/wdc_profile_static.c",
            "firmware/components/wdc_hal/include/wdc_gpio.h",
            "firmware/components/wdc_hal/wdc_gpio_espidf.c",
        ]
        for rel in required:
            self.assertTrue((ROOT / rel).exists(), rel)

    def test_shell_config_keeps_r1_fields_and_enters_r3_runtime_mode(self) -> None:
        text = (FW / "main/shell_config.h").read_text(encoding="utf-8")
        self.assertIn('WDC_SHELL_VERSION     "0.1.0-r9"', text)
        self.assertIn('WDC_SHELL_BUILD_STAGE "R9"', text)
        self.assertRegex(text, r"#define\s+WDC_NO_BUNDLE_MODE\s+0")
        self.assertRegex(text, r"#define\s+WDC_R4_STATIC_RUNTIME_SMOKE\s+0")
        self.assertIn("WDC_SHELL_TASK_STACK_BYTES", text)
        self.assertIn("WDC_NO_BUNDLE_IDLE_PERIOD_MS", text)

    def test_shell_main_has_r1_boot_sequence(self) -> None:
        text = (FW / "main/shell_main.c").read_text(encoding="utf-8")
        for token in [
            "esp_reset_reason",
            "wdc_reset_reason_name",
            "esp_ota_get_running_partition",
            "esp_partition_find_first",
            "nvs_flash_init",
            "wdc_safety_init",
            "wdc_safety_force_safe_outputs",
            "wdc_events_init",
            "wdc_shell_run_internal_event_self_test",
            "wdc_shell_run_r5_runtime_smoke",
            "wdc_runtime_dispatch_event",
            "xTaskCreate",
            "no-bundle mode active",
        ]:
            self.assertIn(token, text)

    def test_main_component_requires_r1_components(self) -> None:
        text = (FW / "main/CMakeLists.txt").read_text(encoding="utf-8")
        for component in ["wdc_caps", "wdc_diag", "wdc_events", "wdc_profile", "wdc_hal", "wdc_runtime", "wdc_safety", "wdc_bundle", "wdc_ota", "wdc_activation", "nvs_flash", "app_update"]:
            self.assertIn(component, text)

    def test_static_profile_matches_logical_resources(self) -> None:
        text = (FW / "components/wdc_profile/wdc_profile_static.c").read_text(encoding="utf-8")
        for resource in ["relay_1", "status_led", "button_1"]:
            self.assertIn(resource, text)
        self.assertIn("safe_level = 0", text)
        self.assertIn("safe_level = 1", text)
        self.assertIn("apply_safe_level = true", text)

    def test_r1_components_compile_and_run_on_host(self) -> None:
        if shutil.which("gcc") is None:
            self.skipTest("gcc not available")

        program = textwrap.dedent(
            r'''
            #include <assert.h>
            #include <string.h>
            #include "wdc_abi.h"
            #include "wdc_diag.h"
            #include "wdc_events.h"
            #include "wdc_gpio.h"
            #include "wdc_profile.h"

            int main(void) {
                assert(wdc_diag_init() == WDC_OK);
                wdc_diag_note_boot(1u, "poweron");
                assert(wdc_diag_log(WDC_LOG_INFO, "r1 host smoke") == WDC_OK);
                WdcDiagMetrics metrics;
                memset(&metrics, 0, sizeof(metrics));
                wdc_diag_get_metrics(&metrics);
                assert(metrics.boot_count == 1u);
                assert(metrics.ring_count >= 2u);

                const WdcDeviceProfile *profile = wdc_profile_builtin();
                assert(profile != 0);
                assert(wdc_profile_validate_basic(profile) == WDC_OK);
                assert(wdc_profile_find_gpio_by_name(profile, "relay_1") != 0);
                assert(wdc_hal_apply_safe_gpio_defaults(profile) == WDC_OK);
                assert(wdc_hal_safe_gpio_defaults_applied() == 2u);

                WdcEventQueue queue;
                assert(wdc_event_queue_init(&queue) == WDC_OK);
                WdcEvent event;
                memset(&event, 0, sizeof(event));
                assert(wdc_event_make(&event, WDC_EVENT_BOOT, WDC_EVENT_RESOURCE_NONE, 0u, NULL, 0u) == WDC_OK);
                assert(wdc_event_queue_push(&queue, &event) == WDC_OK);
                assert(wdc_event_queue_count(&queue) == 1u);
                WdcEvent out;
                memset(&out, 0, sizeof(out));
                assert(wdc_event_queue_pop(&queue, &out) == WDC_OK);
                assert(out.event_type == WDC_EVENT_BOOT);
                assert(wdc_event_queue_pop(&queue, &out) == WDC_ERR_NOT_AVAILABLE);
                return 0;
            }
            '''
        )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            test_c = tmp_path / "r1_smoke.c"
            test_c.write_text(program, encoding="utf-8")
            exe = tmp_path / "r1_smoke"
            include_args = [
                "-I", str(FW / "components/wdc_abi/include"),
                "-I", str(FW / "components/wdc_activation/include"),
                "-I", str(FW / "components/wdc_app/include"),
                "-I", str(FW / "components/wdc_caps/include"),
                "-I", str(FW / "components/wdc_bundle/include"),
                "-I", str(FW / "components/wdc_diag/include"),
                "-I", str(FW / "components/wdc_events/include"),
                "-I", str(FW / "components/wdc_profile/include"),
                "-I", str(FW / "components/wdc_hal/include"),
                "-I", str(FW / "components/wdc_runtime/include"),
            ]
            sources = [
                FW / "components/wdc_abi/wdc_errors.c",
                FW / "components/wdc_abi/wdc_cbor.c",
                FW / "components/wdc_diag/wdc_diag.c",
                FW / "components/wdc_events/wdc_event_queue.c",
                FW / "components/wdc_events/wdc_event_encode.c",
                FW / "components/wdc_profile/wdc_profile_static.c",
                FW / "components/wdc_hal/wdc_gpio_espidf.c",
                test_c,
            ]
            subprocess.run(
                ["gcc", "-std=c11", "-Wall", "-Wextra", "-Werror", *include_args, *map(str, sources), "-o", str(exe)],
                check=True,
            )
            subprocess.run([str(exe)], check=True)


    def test_shell_main_compiles_on_host(self) -> None:
        if shutil.which("gcc") is None:
            self.skipTest("gcc not available")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            obj = tmp_path / "shell_main.o"
            include_args = [
                "-I", str(FW / "main"),
                "-I", str(FW / "components/wdc_abi/include"),
                "-I", str(FW / "components/wdc_activation/include"),
                "-I", str(FW / "components/wdc_app/include"),
                "-I", str(FW / "components/wdc_caps/include"),
                "-I", str(FW / "components/wdc_bundle/include"),
                "-I", str(FW / "components/wdc_diag/include"),
                "-I", str(FW / "components/wdc_events/include"),
                "-I", str(FW / "components/wdc_profile/include"),
                "-I", str(FW / "components/wdc_hal/include"),
                "-I", str(FW / "components/wdc_runtime/include"),
                "-I", str(FW / "components/wdc_net/include"),
                "-I", str(FW / "components/wdc_ota/include"),
                "-I", str(FW / "components/wdc_safety/include"),
                "-I", str(FW / "components/wdc_security/include"),
            ]
            subprocess.run(
                [
                    "gcc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                    *include_args, "-c", str(FW / "main/shell_main.c"), "-o", str(obj),
                ],
                check=True,
            )
            self.assertTrue(obj.exists())


if __name__ == "__main__":
    unittest.main()
