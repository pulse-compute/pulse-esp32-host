#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Keep these split into separate interpreter invocations. Running every module in
# one unittest-discover process can leave the sandbox stdout pipe open after OK
# when multiple subprocess-heavy smoke tests have run.
COMMANDS = [
    [sys.executable, "-B", "tools/check_r0.py"],
    [sys.executable, "-B", "tools/check_r1.py"],
    [sys.executable, "-B", "tools/check_r2.py"],
    [sys.executable, "-B", "tools/check_r3.py"],
    [sys.executable, "-B", "-m", "unittest", "tests.contract.test_r3_5_verification"],
    [sys.executable, "-B", "-m", "unittest", "tests.contract.test_r3_5_deps"],
    [sys.executable, "-B", "-m", "unittest", "tests.contract.test_idf_family_matrix", "-v"],
    [sys.executable, "-B", "tools/check_r4.py"],
    [sys.executable, "-B", "tools/check_r5.py"],
    [sys.executable, "-B", "-m", "unittest", "tests.contract.test_hx0_extension_contract", "-v"],
    [sys.executable, "-B", "-m", "unittest", "tests.contract.test_hx1_elf_loader", "-v"],
    [sys.executable, "-B", "-m", "unittest", "tests.contract.test_hx2_extension_admission", "-v"],
    [sys.executable, "-B", "-m", "unittest", "tests.contract.test_hx3_extension_lifecycle", "-v"],
    [sys.executable, "-B", "-m", "unittest", "tests.contract.test_hx4_extension_event_effect", "-v"],
    [sys.executable, "-B", "-m", "unittest", "tests.contract.test_hx45_extension_adversarial", "-v"],
    [sys.executable, "-B", "-m", "unittest", "tests.contract.test_hx5a_extension_faults", "-v"],
    [sys.executable, "-B", "-m", "unittest", "tests.contract.test_hx5b_extension_pressure", "-v"],
    [sys.executable, "-B", "-m", "unittest", "tests.contract.test_hp0_evidence_reconciliation", "-v"],
    [sys.executable, "-B", "-m", "unittest", "tests.contract.test_hp1_host_kernel_resource_authority", "-v"],
    [sys.executable, "-B", "-m", "unittest", "tests.contract.test_hp2_host_build_coherence", "-v"],
    [sys.executable, "-B", "-m", "unittest", "tests.contract.test_hp3_application_slots", "-v"],
    [sys.executable, "-B", "-m", "unittest", "tests.contract.test_hp3_5_slot_adversarial", "-v"],
    [sys.executable, "-B", "-m", "unittest", "tests.contract.test_hp4_0_administration_contract", "-v"],
    [sys.executable, "-B", "-m", "unittest", "tests.contract.test_hp4_1_administration_core", "-v"],
    [sys.executable, "-B", "-m", "unittest", "tests.contract.test_hp4_2_admin_update", "-v"],
    [sys.executable, "-B", "-m", "unittest", "tests.contract.test_hp4_3_admin_recovery", "-v"],
    [sys.executable, "-B", "-m", "unittest", "tests.contract.test_hp4_4_admin_adversarial", "-v"],
    [sys.executable, "-B", "-m", "unittest", "tests.contract.test_hp5_host_network", "-v"],
    [sys.executable, "-B", "-m", "unittest", "tests.contract.test_hp5_5_network_hardware", "-v"],
    [sys.executable, "-B", "-m", "unittest", "tests.contract.test_hx45_s3_aitrip_hardware", "-v"],
    [sys.executable, "-B", "-m", "unittest", "tests.contract.test_hx45_c6_xiao_hardware", "-v"],
    [sys.executable, "-B", "-m", "unittest", "tests.contract.test_release_packaging", "-v"],
    [sys.executable, "-B", "tools/check_r6.py"],
    [sys.executable, "-B", "tools/check_r7.py"],
    [sys.executable, "-B", "tools/check_r8.py"],
    [sys.executable, "-B", "-m", "unittest", "tests.contract.test_r8_1_hardening", "-v"],
    [sys.executable, "-B", "tools/check_r8_2.py"],
    [sys.executable, "-B", "tools/check_r9.py"],
]


def main() -> int:
    for cmd in COMMANDS:
        print("$", " ".join(cmd), flush=True)
        env = None
        if cmd and cmd[-1] == "tools/check_r8_1.py":
            env = os.environ.copy()
            env["WDC_R8_1_SKIP_RAW_DISCOVERY"] = "1"
        result = subprocess.run(
            cmd,
            cwd=ROOT,
            check=False,
            timeout=300,
            env=env,
        )
        if result.returncode != 0:
            return result.returncode
    print("All split contract tests passed through R9, HX5b, HP0, HP1, HP2, HP3, HP3.5, HP4.0, HP4.1, HP4.2, HP4.3, HP4.4, HP5, and HP5.5 readiness")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
