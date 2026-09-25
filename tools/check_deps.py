#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from tools import check_idf_matrix, verify_idf_environment
except ModuleNotFoundError:  # Direct execution from tools/.
    import check_idf_matrix  # type: ignore[no-redef]
    import verify_idf_environment  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[1]

CORE_COMMANDS = ["python3", "gcc", "g++", "cmake", "ninja", "make", "git"]
OPTIONAL_COMMANDS = ["clang", "wasm-ld", "cargo", "rustc", "rustup", "idf.py", "ccache", "curl", "wget"]


def run(cmd: list[str], timeout: int = 15) -> dict[str, Any]:
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, check=False)
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        }
    except FileNotFoundError:
        return {"ok": False, "returncode": None, "stdout": "", "stderr": "command not found"}
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "returncode": None,
            "stdout": (exc.stdout or "").strip() if isinstance(exc.stdout, str) else "",
            "stderr": "timeout",
        }


def command_info(name: str) -> dict[str, Any]:
    path = shutil.which(name)
    info: dict[str, Any] = {"name": name, "present": bool(path), "path": path, "version": None, "version_error": None}
    if not path:
        return info

    version_cmds = {
        "python3": [name, "--version"],
        "pip3": [name, "--version"],
        "gcc": [name, "--version"],
        "g++": [name, "--version"],
        "cmake": [name, "--version"],
        "ninja": [name, "--version"],
        "make": [name, "--version"],
        "git": [name, "--version"],
        "clang": [name, "--version"],
        "wasm-ld": [name, "--version"],
        "cargo": [name, "--version"],
        "rustc": [name, "--version"],
        "rustup": [name, "--version"],
        "idf.py": [name, "--version"],
        "ccache": [name, "--version"],
        "curl": [name, "--version"],
        "wget": [name, "--version"],
    }
    result = run(version_cmds.get(name, [name, "--version"]), timeout=20)
    output = result["stdout"] or result["stderr"]
    first_line = output.splitlines()[0] if output else None
    info["version"] = first_line if result["ok"] or first_line else None
    info["version_error"] = None if result["ok"] else result["stderr"]
    return info


def rust_target_status() -> dict[str, Any]:
    target = "wasm32-unknown-unknown"
    rustup = shutil.which("rustup")
    rustc = shutil.which("rustc")
    cargo = shutil.which("cargo")
    status: dict[str, Any] = {
        "target": target,
        "cargo_present": bool(cargo),
        "rustc_present": bool(rustc),
        "rustup_present": bool(rustup),
        "installed": False,
        "method": None,
        "detail": None,
    }
    if rustup:
        result = run(["rustup", "target", "list", "--installed"], timeout=30)
        status["method"] = "rustup target list --installed"
        status["detail"] = result["stdout"] or result["stderr"]
        status["installed"] = result["ok"] and target in result["stdout"].splitlines()
        return status
    if rustc:
        result = run(["rustc", "--print", "target-libdir", "--target", target], timeout=30)
        status["method"] = "rustc --print target-libdir"
        status["detail"] = result["stdout"] or result["stderr"]
        status["installed"] = result["ok"]
        return status
    status["detail"] = "rust toolchain not present"
    return status


def esp_idf_status(matrix_path: Path) -> dict[str, Any]:
    idf_py = shutil.which("idf.py")
    idf_path = os.environ.get("IDF_PATH")
    export_candidates = []
    for base in [idf_path, "/opt/esp/esp-idf", str(Path.home() / "esp" / "esp-idf")]:
        if base:
            p = Path(base) / "export.sh"
            export_candidates.append(str(p))
    status: dict[str, Any] = {
        "idf_py_present": bool(idf_py),
        "idf_py_path": idf_py,
        "IDF_PATH": idf_path,
        "export_sh_candidates": export_candidates,
        "export_sh_present": [p for p in export_candidates if Path(p).exists()],
        "version": None,
        "version_error": None,
        "lane_verification": {
            "status": "SKIPPED_ENV",
            "error": "idf.py is not available",
            "evidence": None,
        },
    }
    if idf_py:
        result = run(["idf.py", "--version"], timeout=30)
        status["version"] = (result["stdout"] or result["stderr"]).splitlines()[0] if (result["stdout"] or result["stderr"]) else None
        status["version_error"] = None if result["ok"] else result["stderr"]
        inferred_path = Path(idf_path) if idf_path else Path(idf_py).resolve().parent.parent
        status["IDF_PATH"] = str(inferred_path)
        try:
            evidence = verify_idf_environment.verify_idf_environment(
                matrix_path,
                idf_path=inferred_path,
                idf_py=Path(idf_py),
            )
        except (check_idf_matrix.MatrixContractError, verify_idf_environment.IDFEnvironmentError) as exc:
            status["lane_verification"] = {
                "status": "FAIL",
                "error": str(exc),
                "evidence": None,
            }
        else:
            status["lane_verification"] = {
                "status": "PASS",
                "error": None,
                "evidence": evidence,
            }
    return status


def matrix_status(matrix_path: Path, realization_id: str) -> dict[str, Any]:
    status: dict[str, Any] = {
        "status": "FAIL",
        "matrix_path": str(matrix_path),
        "errors": [],
        "lane_id": None,
        "lane": None,
        "realization": None,
        "locks": None,
    }
    try:
        matrix = check_idf_matrix.load_matrix(matrix_path)
    except check_idf_matrix.MatrixContractError as exc:
        status["errors"] = [str(exc)]
        return status
    errors = check_idf_matrix.validate_matrix(matrix, matrix_path)
    if errors:
        status["errors"] = errors
        return status
    if realization_id not in matrix["realizations"]:
        status["errors"] = [f"unknown or non-attempted realization {realization_id!r}"]
        return status
    lock_errors, locks = check_idf_matrix.validate_locks(matrix, matrix_path)
    if lock_errors:
        status["errors"] = lock_errors
        return status
    realization = matrix["realizations"][realization_id]
    lane_id = realization["lane"]
    status.update(
        {
            "status": "PASS",
            "lane_id": lane_id,
            "lane": matrix["lanes"][lane_id],
            "realization": {"id": realization_id, **realization},
            "locks": locks,
        }
    )
    return status


def make_report(
    matrix_path: Path = check_idf_matrix.DEFAULT_MATRIX,
    realization_id: str = "esp32s3-reference",
) -> dict[str, Any]:
    commands = {cmd: command_info(cmd) for cmd in [*CORE_COMMANDS, *OPTIONAL_COMMANDS]}
    core_ok = all(commands[cmd]["present"] for cmd in CORE_COMMANDS)
    rust = rust_target_status()
    matrix = matrix_status(matrix_path, realization_id)
    idf = esp_idf_status(matrix_path)
    checks = []
    for name, info in commands.items():
        checks.append({"name": name, "status": "PASS" if info["present"] else "SKIPPED_ENV", "path": info.get("path"), "version": info.get("version")})
    checks.append({"name": "rust-target:wasm32-unknown-unknown", "status": "PASS" if rust["installed"] else "SKIPPED_ENV", "path": None, "version": rust.get("detail")})
    checks.append(
        {
            "name": "ESP-IDF family matrix and locks",
            "status": matrix["status"],
            "path": str(matrix_path),
            "version": matrix.get("lane_id"),
        }
    )
    checks.append(
        {
            "name": "ESP-IDF idf.py",
            "status": idf["lane_verification"]["status"],
            "path": idf.get("idf_py_path"),
            "version": idf.get("version"),
        }
    )
    summary = {"pass": sum(1 for c in checks if c["status"] == "PASS"), "fail": sum(1 for c in checks if c["status"] == "FAIL"), "skipped_env": sum(1 for c in checks if c["status"] == "SKIPPED_ENV")}
    return {
        "schema": "wdc.r3_5.dependency_report.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(ROOT),
        "platform": {
            "python": sys.version.split()[0],
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "user": os.environ.get("USER"),
        },
        "commands": commands,
        "checks": checks,
        "summary": summary,
        "tools": checks,
        "core_host_tools_ok": core_ok,
        "rust": rust,
        "esp_idf": idf,
        "idf_matrix": matrix,
        "environment": {
            "PATH": os.environ.get("PATH", ""),
            "IDF_PATH": os.environ.get("IDF_PATH"),
            "IDF_TOOLS_PATH": os.environ.get("IDF_TOOLS_PATH"),
            "CARGO_HOME": os.environ.get("CARGO_HOME"),
            "RUSTUP_HOME": os.environ.get("RUSTUP_HOME"),
        },
    }


def write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = []
    lines.append("# R3.5 dependency report")
    lines.append("")
    lines.append(f"Generated: `{report['generated_at']}`")
    lines.append("")
    lines.append("## Command availability")
    lines.append("")
    lines.append("| Command | Present | Path | Version |")
    lines.append("|---|---:|---|---|")
    for name, info in report["commands"].items():
        lines.append(
            f"| `{name}` | {'yes' if info['present'] else 'no'} | `{info['path'] or ''}` | `{(info['version'] or '').replace('`', '')}` |"
        )
    lines.append("")
    rust = report["rust"]
    lines.append("## Rust / WASM target")
    lines.append("")
    lines.append(f"- Cargo present: `{rust['cargo_present']}`")
    lines.append(f"- rustc present: `{rust['rustc_present']}`")
    lines.append(f"- rustup present: `{rust['rustup_present']}`")
    lines.append(f"- `{rust['target']}` installed/available: `{rust['installed']}`")
    lines.append(f"- Method: `{rust['method']}`")
    lines.append("")
    idf = report["esp_idf"]
    lines.append("## ESP-IDF")
    lines.append("")
    lines.append(f"- `idf.py` present: `{idf['idf_py_present']}`")
    lines.append(f"- `idf.py` path: `{idf['idf_py_path'] or ''}`")
    lines.append(f"- `IDF_PATH`: `{idf['IDF_PATH'] or ''}`")
    lines.append(f"- Version: `{idf['version'] or ''}`")
    lines.append(f"- Export scripts found: `{', '.join(idf['export_sh_present'])}`")
    lines.append(f"- Pinned lane verification: `{idf['lane_verification']['status']}`")
    if idf["lane_verification"]["error"]:
        lines.append(f"- Lane error: `{idf['lane_verification']['error'].replace('`', '')}`")
    lines.append("")
    matrix = report["idf_matrix"]
    lines.append("## ESP-IDF family matrix")
    lines.append("")
    lines.append(f"- Matrix status: `{matrix['status']}`")
    lines.append(f"- Selected lane: `{matrix['lane_id'] or ''}`")
    selected = matrix.get("realization") or {}
    lines.append(f"- Selected realization: `{selected.get('id', '')}`")
    lines.append(f"- Selected target: `{selected.get('target', '')}`")
    for error in matrix["errors"]:
        lines.append(f"- Error: `{error.replace('`', '')}`")
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check host, Rust/WASM, and ESP-IDF dependencies for WDC R3.5.")
    parser.add_argument("--repo-root", type=Path, default=ROOT, help="Accepted for R3.5 orchestration; report root is script-relative unless overridden.")
    parser.add_argument("--json", action="store_true", help="Compatibility option; stdout is JSON regardless.")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--md-out", type=Path)
    parser.add_argument("--matrix", type=Path, default=check_idf_matrix.DEFAULT_MATRIX)
    parser.add_argument("--realization", default="esp32s3-reference")
    parser.add_argument("--strict-core", action="store_true", help="Fail if core host build tools are missing.")
    parser.add_argument("--strict-rust", action="store_true", help="Fail if cargo/rustc or wasm32 target are missing.")
    parser.add_argument("--strict-idf", action="store_true", help="Fail if idf.py is missing.")
    args = parser.parse_args()

    report = make_report(args.matrix.resolve(), args.realization)
    if args.repo_root:
        report["root"] = str(args.repo_root)
    report["summary"] = {
        "core_host_tools_ok": report["core_host_tools_ok"],
        "rust_ready": bool(report["rust"]["cargo_present"] and report["rust"]["rustc_present"] and report["rust"]["installed"]),
        "esp_idf_ready": report["esp_idf"]["lane_verification"]["status"] == "PASS",
        "idf_matrix_ready": report["idf_matrix"]["status"] == "PASS",
    }
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.md_out:
        write_markdown(report, args.md_out)

    print(json.dumps(report, indent=2, sort_keys=True))

    failures = []
    if report["idf_matrix"]["status"] != "PASS":
        failures.append("ESP-IDF family matrix or committed locks invalid")
    if report["esp_idf"]["lane_verification"]["status"] == "FAIL":
        failures.append("ambient ESP-IDF does not match the pinned lane")
    if args.strict_core and not report["core_host_tools_ok"]:
        failures.append("core host tools missing")
    if args.strict_rust:
        rust = report["rust"]
        if not (rust["cargo_present"] and rust["rustc_present"] and rust["installed"]):
            failures.append("Rust/cargo/wasm32 target not ready")
    if args.strict_idf and report["esp_idf"]["lane_verification"]["status"] != "PASS":
        failures.append("pinned ESP-IDF lane not ready")

    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
