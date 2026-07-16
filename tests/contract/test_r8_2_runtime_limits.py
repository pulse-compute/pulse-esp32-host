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
ABI = FW / "components/wdc_abi"
CAPS = FW / "components/wdc_caps"
PROFILE = FW / "components/wdc_profile"
RUNTIME = FW / "components/wdc_runtime"
DIAG = FW / "components/wdc_diag"
EVENTS = FW / "components/wdc_events"


def compile_and_run(source: str, exe_name: str, include_dirs: list[Path], sources: list[Path]) -> None:
    if os.environ.get("WDC_RUN_NATIVE_R8_2") != "1":
        raise unittest.SkipTest("set WDC_RUN_NATIVE_R8_2=1 to run R8.2 native C smokes")
    if shutil.which("gcc") is None:
        raise unittest.SkipTest("gcc not available")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        src = tmp_path / f"{exe_name}.c"
        src.write_text(source, encoding="utf-8")
        exe = tmp_path / exe_name
        include_args: list[str] = []
        for inc in include_dirs:
            include_args.extend(["-I", str(inc)])
        cmd = ["gcc", "-std=c11", "-Wall", "-Wextra", "-Werror", *include_args, *map(str, sources), str(src), "-o", str(exe)]
        try:
            subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=True)
            subprocess.run([str(exe)], cwd=ROOT, text=True, capture_output=True, check=True)
        except subprocess.CalledProcessError as exc:
            raise AssertionError((exc.stdout or "") + (exc.stderr or "")) from exc


class R82RuntimeLimitTests(unittest.TestCase):
    def test_r82_version_and_limit_symbols_present(self) -> None:
        config = (FW / "main/shell_config.h").read_text(encoding="utf-8")
        self.assertIn('WDC_SHELL_VERSION     "0.1.0-r9"', config)
        self.assertIn('WDC_SHELL_BUILD_STAGE "R9"', config)
        self.assertIn("WDC_R8_2_RUNTIME_LIMITS_FROM_MANIFEST 1", config)

        abi = (ABI / "include/wdc_abi.h").read_text(encoding="utf-8")
        for token in [
            'WDC_R8_2_SHELL_VERSION "0.1.0-r8.2"',
            'WDC_R8_2_BUILD_STAGE   "R8.2"',
            "WDC_CURRENT_SHELL_VERSION WDC_R9_SHELL_VERSION",
            "typedef struct WdcHostCallLimits",
            "wdc_host_call_set_limits",
            "wdc_host_call_reset_limits",
        ]:
            self.assertIn(token, abi)

        app = (FW / "components/wdc_app/wdc_app.c").read_text(encoding="utf-8")
        for token in [
            "runtime_config_from_manifest",
            "install_host_call_limits_from_manifest",
            "wdc_host_call_set_limits",
            "verify->manifest.max_request_bytes",
            "verify->manifest.max_response_bytes",
            "verify->manifest.max_event_bytes",
        ]:
            self.assertIn(token, app)

        caps = (FW / "components/wdc_caps/wdc_caps.c").read_text(encoding="utf-8")
        for token in [
            "max_payload_bytes",
            "max_rate_hz",
            "enforce_payload_limit",
            "enforce_rate_limit",
            "wdc_caps_set_time_ms_for_test",
            "WDC_ERR_RATE_LIMITED",
            "payload_limit",
        ]:
            self.assertIn(token, caps)

    def test_r82_native_runtime_limit_smoke(self) -> None:
        program = (ROOT / "tests/firmware-unit/r8_2_runtime_limits_smoke.c").read_text(encoding="utf-8")
        compile_and_run(
            program,
            "r8_2_native_runtime_limit_smoke",
            [ABI / "include", CAPS / "include", PROFILE / "include", RUNTIME / "include", DIAG / "include", EVENTS / "include"],
            [
                ABI / "wdc_errors.c",
                ABI / "wdc_cbor.c",
                ABI / "wdc_host_call.c",
                CAPS / "wdc_caps.c",
                PROFILE / "wdc_profile_static.c",
                DIAG / "wdc_diag.c",
                EVENTS / "wdc_event_encode.c",
                EVENTS / "wdc_event_queue.c",
                RUNTIME / "wdc_runtime.c",
            ],
        )



if __name__ == "__main__":
    unittest.main()
