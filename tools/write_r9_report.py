#!/usr/bin/env python3
"""Run bounded R9 verification gates and write machine-readable reports."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PASS = "PASS"
FAIL = "FAIL"
SKIPPED_ENV = "SKIPPED_ENV"
SKIPPED_NETWORK = "SKIPPED_NETWORK"
SKIPPED_NO_HARDWARE = "SKIPPED_NO_HARDWARE"


def classify(rc: int | None, text: str) -> tuple[str, str]:
    if rc == 0:
        return PASS, ""
    if rc is None:
        return FAIL, "command timeout"
    lower = text.lower()
    if any(tok in lower for tok in ["could not resolve", "unable to access", "network is unreachable", "temporary failure resolving"]):
        return SKIPPED_NETWORK, "network unavailable"
    return FAIL, f"command exited {rc}"


def run(root: Path, logs: Path, name: str, cmd: list[str], timeout: int = 120) -> dict[str, object]:
    start = time.monotonic()
    log = logs / f"{name}.log"
    try:
        proc = subprocess.run(cmd, cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, check=False)
        rc = proc.returncode
        out = proc.stdout
    except subprocess.TimeoutExpired as exc:
        rc = None
        out = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        out += f"\n[timeout] command exceeded {timeout}s\n"
    log.write_text("$ " + " ".join(cmd) + "\n\n" + out, encoding="utf-8")
    status, detail = classify(rc, out)
    return {"name": name, "status": status, "command": cmd, "log": str(log), "returncode": rc, "duration_s": round(time.monotonic() - start, 3), "detail": detail}


def skip(logs: Path, name: str, status: str, cmd: list[str], detail: str) -> dict[str, object]:
    log = logs / f"{name}.log"
    log.write_text(detail + "\n", encoding="utf-8")
    return {"name": name, "status": status, "command": cmd, "log": str(log), "returncode": None, "duration_s": 0.0, "detail": detail}


def write_md(payload: dict[str, object], path: Path) -> None:
    lines = [
        "# R9 verification report",
        "",
        f"Generated: `{payload['generated_at']}`",
        f"Overall status: **{payload['overall_status']}**",
        "",
        "| Step | Status | Duration | Detail | Log |",
        "|---|---:|---:|---|---|",
    ]
    for step in payload["steps"]:  # type: ignore[index]
        detail = str(step.get("detail", "")).replace("|", "/")
        lines.append(f"| {step['name']} | {step['status']} | {step['duration_s']:.3f}s | {detail} | `{step['log']}` |")
    lines += ["", "## Summary"]
    for k, v in payload["summary"].items():  # type: ignore[union-attr]
        lines.append(f"- {k}: {v}")
    lines += ["", "## Notes"]
    for note in payload["notes"]:  # type: ignore[index]
        lines.append(f"- {note}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=Path(__file__).resolve().parents[1])
    ap.add_argument("--report-dir", default=None)
    ap.add_argument("--skip-idf-build", action="store_true")
    ap.add_argument("--fail-on-partial", action="store_true")
    args = ap.parse_args(argv)

    root = Path(args.repo_root).resolve()
    reports = Path(args.report_dir).resolve() if args.report_dir else root / "reports"
    logs = reports / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    py = sys.executable

    steps: list[dict[str, object]] = []
    steps.append(run(root, logs, "dependency_inventory", [py, "tools/check_deps.py", "--repo-root", str(root), "--json-out", str(reports / "deps_check.json"), "--md-out", str(reports / "deps_check.md")], timeout=120))
    steps.append(run(root, logs, "profile_manifest_validation", [py, "-B", "tools/wdc_validate.py", "profile", "--profile", "examples/device-profiles/relay-node-rev-c.json"], timeout=60))
    steps.append(run(root, logs, "manifest_validation", [py, "-B", "tools/wdc_validate.py", "manifest", "--manifest", "examples/bundles/relay-controller/manifest.json", "--profile", "examples/device-profiles/relay-node-rev-c.json"], timeout=60))
    steps.append(run(root, logs, "r9_production_hardening_check", [py, "-B", "tools/check_r9.py"], timeout=180))
    steps.append(run(root, logs, "raw_unittest_discovery", [py, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"], timeout=300))

    if shutil.which("cargo") and shutil.which("rustc"):
        steps.append(run(root, logs, "rust_guest_wasm_build", ["bash", "tools/build_guest_wasm.sh"], timeout=900))
    else:
        steps.append(skip(logs, "rust_guest_wasm_build", SKIPPED_ENV, ["bash", "tools/build_guest_wasm.sh"], "cargo/rustc unavailable in sandbox"))

    idf_available = shutil.which("idf.py") is not None or any(Path(p).exists() for p in [os.environ.get("IDF_PATH", "") + "/export.sh", "/opt/esp/esp-idf/export.sh", str(Path.home() / "esp/esp-idf/export.sh")])
    if args.skip_idf_build:
        steps.append(skip(logs, "esp_idf_firmware_build", SKIPPED_ENV, ["bash", "tools/build_firmware.sh"], "skipped by --skip-idf-build"))
    elif idf_available:
        steps.append(run(root, logs, "esp_idf_firmware_build", ["bash", "tools/build_firmware.sh"], timeout=1800))
    else:
        steps.append(skip(logs, "esp_idf_firmware_build", SKIPPED_ENV, ["bash", "tools/build_firmware.sh"], "idf.py/export.sh unavailable in sandbox"))

    steps.append(skip(logs, "hardware_flash_smoke", SKIPPED_NO_HARDWARE, ["idf.py", "flash", "monitor"], "no attached ESP32-S3 board"))

    summary = {PASS: 0, FAIL: 0, SKIPPED_ENV: 0, SKIPPED_NETWORK: 0, SKIPPED_NO_HARDWARE: 0}
    for step in steps:
        summary[str(step["status"])] = summary.get(str(step["status"]), 0) + 1
    overall = FAIL if summary[FAIL] else ("PARTIAL" if summary[SKIPPED_ENV] or summary[SKIPPED_NETWORK] or summary[SKIPPED_NO_HARDWARE] else PASS)
    payload: dict[str, object] = {
        "schema": "wdc.r9.full_verification_report.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(root),
        "overall_status": overall,
        "summary": summary,
        "steps": steps,
        "gates": steps,
        "notes": [
            "R9 targeted host-side production-security-profile verification passed when PASS count has no FAIL entries.",
            "R9 adds a fail-closed production verifier hook; local tests use a deterministic test-vector callback, not deployment Ed25519 math.",
            "ESP-IDF, Rust/WASM guest build, and hardware flash remain bounded by missing toolchains/hardware in this sandbox.",
        ],
    }
    (reports / "r9_test_report.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_md(payload, reports / "r9_test_report.md")
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"R9 report written: {reports / 'r9_test_report.json'}")
    if overall == FAIL:
        return 1
    if args.fail_on_partial and overall != PASS:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
