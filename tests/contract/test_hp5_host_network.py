from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from tools import qualify_host_network


ROOT = Path(__file__).resolve().parents[2]


def _model() -> dict:
    return qualify_host_network.load_model()


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


class HP5HostNetworkTests(unittest.TestCase):
    def test_identity_claim_and_deferred_boundary_are_exact(self) -> None:
        model = _model()
        self.assertEqual(
            (
                model["schema"], model["pass"], model["phase"],
                model["status"], model["aggregate"],
            ),
            (
                "pulse.esp32.hp5-host-network-mediator.v1",
                "HP5",
                "HOST_NETWORK_MEDIATOR",
                "QUALIFIED",
                "HOST_NETWORK_MEDIATOR_IMPLEMENTED",
            ),
        )
        self.assertEqual(model["claim"], qualify_host_network.EXPECTED_CLAIM)
        self.assertTrue(model["claim"]["network_transport_source_implemented"])
        self.assertTrue(model["claim"]["authenticated_external_admin_adapter_implemented"])
        for key in (
            "application_code_executed", "host_firmware_ota_implemented",
            "mqtt_transport_implemented", "partition_layout_changed",
            "physical_execution", "production_authenticator_implemented",
            "production_cryptography_validated", "target_build_executed",
        ):
            self.assertFalse(model["claim"][key])
        self.assertTrue(any("HP5.5 dual-board" in item for item in model["deferred"]))
        self.assertTrue(any("HP8 external" in item for item in model["deferred"]))

    def test_routes_bounds_and_authority_invariants_are_fixed(self) -> None:
        model = _model()
        self.assertEqual(model["bounds"], qualify_host_network.EXPECTED_BOUNDS)
        self.assertEqual(len(model["routes"]["admin"]), 5)
        self.assertEqual(model["routes"]["application_namespace"], "/pulse/v1/app/")
        self.assertEqual(model["routes"]["administration_namespace"], "/pulse/v1/admin/")
        self.assertIn("HP4 alone owns", model["invariants"]["admin_authority"])
        self.assertIn("does not roll back", model["invariants"]["client_loss"])
        self.assertIn("HP3 remains", model["invariants"]["boot_authority"])

    def test_exact_hp4_4_source_and_authorities_are_replayed(self) -> None:
        model = _model()
        self.assertEqual(model["source_history"], qualify_host_network.EXPECTED_SOURCE_HISTORY)
        source = qualify_host_network._validate_source_history()
        self.assertEqual(
            source["firmware"],
            qualify_host_network.hp5_5_source_authority.EXPECTED_FIRMWARE,
        )
        self.assertEqual(source["sealed_firmware"], qualify_host_network.EXPECTED_FIRMWARE)
        self.assertEqual(source["current_successor"], "HP5.5")
        self.assertEqual(source["guest_sdk"], qualify_host_network.EXPECTED_GUEST_SDK)
        self.assertEqual(source["native_sdk"], qualify_host_network.EXPECTED_NATIVE_SDK)
        authority = qualify_host_network._validate_authority(model)
        self.assertEqual(len(authority), 10)

    def test_http_orchestration_is_host_private_and_net_remains_admin_free(self) -> None:
        qualify_host_network._validate_component_surface()
        net_cmake = _text("firmware/components/wdc_net/CMakeLists.txt")
        http_cmake = _text("firmware/components/wdc_http/CMakeLists.txt")
        net_source = _text("firmware/components/wdc_net/wdc_net.c")
        main_source = _text("firmware/main/app_main.c")
        self.assertNotIn("wdc_admin", net_cmake)
        self.assertNotIn("wdc_http_service.h", net_source)
        self.assertIn("REQUIRES wdc_abi wdc_admin wdc_net wdc_runtime", http_cmake)
        self.assertIn("wdc_http_link_anchor", main_source)
        self.assertIn("wdc_net_set_http_response_hook", net_source)

    def test_platform_owns_two_bounded_https_listeners_and_wifi(self) -> None:
        platform = _text("firmware/components/wdc_http/wdc_http_platform_espidf.c")
        header = _text("firmware/components/wdc_http/include/wdc_http_platform.h")
        for token in (
            "esp_wifi_init", "esp_wifi_connect", "HTTPD_SSL_CONFIG_DEFAULT",
            "httpd_ssl_start", "WDC_HTTP_APP_CTRL_PORT",
            "WDC_HTTP_ADMIN_CTRL_PORT", "s_platform.app",
            "s_platform.admin",
        ):
            self.assertIn(token, platform)
        self.assertIn("WDC_HTTP_PLATFORM_APP_PORT_DEFAULT 443u", header)
        self.assertIn("WDC_HTTP_PLATFORM_ADMIN_PORT_DEFAULT 8443u", header)
        self.assertIn("WDC_HTTP_PLATFORM_MAX_OPEN_SOCKETS_PER_LANE 3u", header)

    def test_app_event_and_first_response_wins_use_the_common_runtime(self) -> None:
        service = _text("firmware/components/wdc_http/wdc_http_service.c")
        runtime = _text("firmware/components/wdc_http/wdc_http_runtime.c")
        guest_c = _text("guest-sdk/c/include/wdc_guest.h")
        guest_rust = _text("guest-sdk/rust/wdc_guest/src/abi.rs")
        self.assertIn("WDC_EVENT_HTTP_REQUEST", service)
        self.assertIn("wdc_runtime_call_event_cbor", runtime)
        self.assertIn("duplicate_response_rejections", service)
        self.assertIn("WDC_OP_HTTP_RESPOND", guest_c)
        self.assertIn("wdc_guest_http_respond", guest_c)
        self.assertIn("WDC_OP_HTTP_RESPOND", guest_rust)

    def test_admin_http_entry_reuses_hp4_without_second_authority(self) -> None:
        service = _text("firmware/components/wdc_http/wdc_http_service.c")
        admin = _text("firmware/components/wdc_admin/wdc_admin.c")
        admin_header = _text("firmware/components/wdc_admin/include/wdc_admin.h")
        self.assertIn("wdc_admin_serial_feed", service)
        self.assertIn("wdc_admin_authorization_begin", service)
        self.assertIn("wdc_admin_take_terminal", service)
        self.assertNotIn("wdc_admin_submit(", service)
        self.assertIn("WDC_ADMIN_TRANSPORT_AUTHENTICATED_EXTERNAL_V1", admin_header)
        self.assertIn("external_entry", admin)
        for token in ("malloc(", "calloc(", "realloc(", "free("):
            self.assertNotIn(token, service + admin)

    def test_native_http_service_smoke_executes_all_cases(self) -> None:
        result = qualify_host_network._run_native_smoke()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["case_count"], 35)
        self.assertEqual(result["failures"], 0)
        self.assertTrue(result["separate_admin_lane"])
        self.assertTrue(result["external_entry_reuses_hp4"])
        self.assertTrue(result["first_response_wins"])
        self.assertTrue(result["network_loss_does_not_rollback"])

    def test_all_hp4_4_native_cases_remain_green(self) -> None:
        result = qualify_host_network._run_inherited_hp4()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["hp4_4_adversarial_cases"], 3523)
        self.assertEqual(result["hp4_1_through_hp4_3_cases"], 41)
        self.assertEqual(result["aggregate_case_count"], 3564)

    def test_model_tampering_fails_closed(self) -> None:
        model = _model()
        for mutator in (
            lambda value: value["claim"].update({"physical_execution": True}),
            lambda value: value["bounds"].update({"app_route_count": 5}),
            lambda value: value["routes"]["admin"].append("GET /pulse/v1/admin/shadow"),
            lambda value: value["source_history"].update({"current_firmware_file_count": 0}),
        ):
            changed = copy.deepcopy(model)
            mutator(changed)
            with self.assertRaises(qualify_host_network.QualificationError):
                qualify_host_network._validate_model(changed)

    def test_qualifier_emits_manifested_host_native_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "qualification"
            report = qualify_host_network.qualify(out)
            self.assertEqual(
                (report["schema"], report["aggregate"], report["status"]),
                (
                    "pulse.esp32.hp5-host-network-qualification.v1",
                    "HOST_NETWORK_MEDIATOR_IMPLEMENTED",
                    "PASS",
                ),
            )
            self.assertEqual(report["native_case_count"], 35)
            self.assertEqual(report["inherited_hp4_4_native_case_count"], 3564)
            self.assertTrue(report["hp5_closed"])
            self.assertEqual(report["next_pass"], "HP5.5")
            self.assertFalse(report["target_build_executed"])
            self.assertFalse(report["physical_result_created"])
            manifest = json.loads((out / "evidence-manifest.json").read_text())
            self.assertEqual(manifest["status"], "PASS")
            self.assertEqual(len(manifest["artifacts"]), 4)

    def test_docs_make_and_runner_expose_hp5_and_hp5_5_gate(self) -> None:
        makefile = _text("Makefile")
        runner = _text("tools/run_contract_tests.py")
        docs = _text("docs/HP5_HOST_NETWORK_MEDIATOR.md")
        status = _text("docs/STATUS.md")
        self.assertIn("check-hp5", makefile)
        self.assertIn("host-network-qualify", makefile)
        self.assertIn("tests.contract.test_hp5_host_network", runner)
        self.assertIn("HOST_NETWORK_MEDIATOR_IMPLEMENTED", docs)
        self.assertIn("HP5.5", docs)
        self.assertIn("physical", status.lower())
        self.assertNotIn("HP5_OUT_DIR", _text(".github/workflows/idf-family-matrix.yml"))


if __name__ == "__main__":
    unittest.main()
