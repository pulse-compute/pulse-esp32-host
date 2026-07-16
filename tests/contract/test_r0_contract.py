from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools import wdc_validate

ROOT = Path(__file__).resolve().parents[2]
ABI_HEADER = ROOT / "firmware/components/wdc_abi/include/wdc_abi.h"
PROFILE = ROOT / "examples/device-profiles/relay-node-rev-c.json"
MANIFEST = ROOT / "examples/bundles/relay-controller/manifest.json"


class R0ContractTests(unittest.TestCase):
    def test_examples_validate(self) -> None:
        profile = wdc_validate.load_json(PROFILE)
        manifest = wdc_validate.load_json(MANIFEST)
        errors = []
        errors.extend(wdc_validate.validate_profile(profile))
        errors.extend(wdc_validate.validate_manifest(manifest))
        errors.extend(wdc_validate.validate_manifest_against_profile(manifest, profile))
        self.assertEqual(errors, [])

    def test_manifest_has_no_physical_pin_authority(self) -> None:
        manifest = wdc_validate.load_json(MANIFEST)
        for cap in manifest["capabilities"]:
            self.assertNotIn("pin", cap)
            self.assertNotIn("gpio_num", cap)
            self.assertIsInstance(cap["resource"], str)

    def test_required_lifecycle_names_are_fixed(self) -> None:
        text = ABI_HEADER.read_text(encoding="utf-8")
        for name in [
            "wdc_log",
            "wdc_millis",
            "wdc_random",
            "wdc_yield",
            "wdc_host_call",
            "wdc_module_init",
            "wdc_module_on_event",
            "wdc_module_health",
            "wdc_module_shutdown",
        ]:
            self.assertIn(name, text)

    def test_status_code_range_is_fixed(self) -> None:
        text = ABI_HEADER.read_text(encoding="utf-8")
        expected = {
            "WDC_OK": 0,
            "WDC_ERR_UNKNOWN": -1,
            "WDC_ERR_UNSUPPORTED_ABI": -2,
            "WDC_ERR_BAD_POINTER": -3,
            "WDC_ERR_BAD_LENGTH": -4,
            "WDC_ERR_BAD_ENCODING": -5,
            "WDC_ERR_UNSUPPORTED_OPCODE": -6,
            "WDC_ERR_CAPABILITY_DENIED": -7,
            "WDC_ERR_INVALID_RESOURCE": -8,
            "WDC_ERR_INVALID_STATE": -9,
            "WDC_ERR_BUSY": -10,
            "WDC_ERR_TIMEOUT": -11,
            "WDC_ERR_NO_MEMORY": -12,
            "WDC_ERR_RESPONSE_TOO_SMALL": -13,
            "WDC_ERR_RATE_LIMITED": -14,
            "WDC_ERR_CONTRACT_VIOLATION": -15,
            "WDC_ERR_IO": -16,
            "WDC_ERR_NOT_AVAILABLE": -17,
            "WDC_ERR_NOT_SYNCHRONIZED": -18,
        }
        for symbol, value in expected.items():
            pattern = rf"\b{symbol}\s*=\s*{value}\b"
            self.assertRegex(text, pattern)

    def test_opcode_values_are_fixed(self) -> None:
        text = ABI_HEADER.read_text(encoding="utf-8")
        expected = {
            "WDC_OP_SYS_GET_INFO": "0x0001",
            "WDC_OP_TIMER_SET": "0x0101",
            "WDC_OP_CONFIG_GET": "0x0201",
            "WDC_OP_GPIO_GET": "0x0301",
            "WDC_OP_GPIO_SET": "0x0302",
            "WDC_OP_SENSOR_READ": "0x0401",
            "WDC_OP_NET_STATUS": "0x0501",
            "WDC_OP_MQTT_PUBLISH": "0x0502",
            "WDC_OP_BLE_SET_VALUE": "0x0601",
            "WDC_OP_KV_GET": "0x0701",
        }
        for symbol, value in expected.items():
            self.assertRegex(text, rf"\b{symbol}\s*=\s*{value}\b")

    def test_partition_table_contains_native_and_wasm_slots(self) -> None:
        table = (ROOT / "firmware/partitions.csv").read_text(encoding="utf-8")
        for name in ["ota_0", "ota_1", "wasm_a", "wasm_b", "wasm_meta"]:
            self.assertIn(name, table)

    def test_abi_component_compiles_on_host(self) -> None:
        if shutil.which("gcc") is None:
            self.skipTest("gcc not available")
        with tempfile.TemporaryDirectory() as tmp:
            include = ROOT / "firmware/components/wdc_abi/include"
            sources = [
                ROOT / "firmware/components/wdc_abi/wdc_errors.c",
                ROOT / "firmware/components/wdc_abi/wdc_host_call.c",
            ]
            for src in sources:
                out = Path(tmp) / (src.stem + ".o")
                subprocess.run(
                    ["gcc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(include), "-c", str(src), "-o", str(out)],
                    check=True,
                )

    def test_schema_files_are_valid_json(self) -> None:
        for schema in [
            ROOT / "schemas/wdc_bundle_manifest.schema.json",
            ROOT / "schemas/wdc_device_profile.schema.json",
        ]:
            with schema.open("r", encoding="utf-8") as f:
                value = json.load(f)
            self.assertEqual(value["$schema"], "https://json-schema.org/draft/2020-12/schema")


if __name__ == "__main__":
    unittest.main()
