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


def esp_idf_status() -> dict[str, Any]:
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
    }
    if idf_py:
        result = run(["idf.py", "--version"], timeout=30)
        status["version"] = (result["stdout"] or result["stderr"]).splitlines()[0] if (result["stdout"] or result["stderr"]) else None
        status["version_error"] = None if result["ok"] else result["stderr"]
    return status


def make_report() -> dict[str, Any]:
    commands = {cmd: command_info(cmd) for cmd in [*CORE_COMMANDS, *OPTIONAL_COMMANDS]}
    core_ok = all(commands[cmd]["present"] for cmd in CORE_COMMANDS)
    rust = rust_target_status()
    idf = esp_idf_status()
    checks = []
    for name, info in commands.items():
        checks.append({"name": name, "status": "PASS" if info["present"] else "SKIPPED_ENV", "path": info.get("path"), "version": info.get("version")})
    checks.append({"name": "rust-target:wasm32-unknown-unknown", "status": "PASS" if rust["installed"] else "SKIPPED_ENV", "path": None, "version": rust.get("detail")})
    checks.append({"name": "ESP-IDF idf.py", "status": "PASS" if idf["idf_py_present"] else "SKIPPED_ENV", "path": idf.get("idf_py_path"), "version": idf.get("version")})
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
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check host, Rust/WASM, and ESP-IDF dependencies for WDC R3.5.")
    parser.add_argument("--repo-root", type=Path, default=ROOT, help="Accepted for R3.5 orchestration; report root is script-relative unless overridden.")
    parser.add_argument("--json", action="store_true", help="Compatibility option; stdout is JSON regardless.")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--md-out", type=Path)
    parser.add_argument("--strict-core", action="store_true", help="Fail if core host build tools are missing.")
    parser.add_argument("--strict-rust", action="store_true", help="Fail if cargo/rustc or wasm32 target are missing.")
    parser.add_argument("--strict-idf", action="store_true", help="Fail if idf.py is missing.")
    args = parser.parse_args()

    report = make_report()
    if args.repo_root:
        report["root"] = str(args.repo_root)
    report["summary"] = {
        "core_host_tools_ok": report["core_host_tools_ok"],
        "rust_ready": bool(report["rust"]["cargo_present"] and report["rust"]["rustc_present"] and report["rust"]["installed"]),
        "esp_idf_ready": bool(report["esp_idf"]["idf_py_present"]),
    }
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.md_out:
        write_markdown(report, args.md_out)

    print(json.dumps(report, indent=2, sort_keys=True))

    failures = []
    if args.strict_core and not report["core_host_tools_ok"]:
        failures.append("core host tools missing")
    if args.strict_rust:
        rust = report["rust"]
        if not (rust["cargo_present"] and rust["rustc_present"] and rust["installed"]):
            failures.append("Rust/cargo/wasm32 target not ready")
    if args.strict_idf and not report["esp_idf"]["idf_py_present"]:
        failures.append("ESP-IDF idf.py not ready")

    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
