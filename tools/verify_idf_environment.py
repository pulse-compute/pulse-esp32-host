#!/usr/bin/env python3
"""Verify that an ambient ESP-IDF installation is the matrix-pinned lane."""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

try:
    from tools import check_idf_matrix
except ModuleNotFoundError:  # Direct execution from tools/.
    import check_idf_matrix  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = ROOT / "firmware" / "idf-family-matrix.json"


class IDFEnvironmentError(RuntimeError):
    """Raised when an ambient IDF cannot prove the selected lane identity."""


Runner = Callable[..., subprocess.CompletedProcess[str]]


def _run(command: list[str], *, runner: Runner, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    try:
        return runner(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise IDFEnvironmentError(f"cannot execute {' '.join(command)}: {exc}") from exc


def _host_platform() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    machine = {"x86_64": "amd64", "aarch64": "arm64"}.get(machine, machine)
    return f"{system}/{machine}"


def verify_idf_environment(
    matrix_path: Path = DEFAULT_MATRIX,
    *,
    idf_path: Path | None = None,
    idf_py: Path | None = None,
    runner: Runner = subprocess.run,
    observed_platform: str | None = None,
    allowed_platforms: tuple[str, ...] | None = None,
) -> dict[str, object]:
    matrix_path = matrix_path.resolve()
    matrix = check_idf_matrix.load_matrix(matrix_path)
    matrix_errors = check_idf_matrix.validate_matrix(matrix, matrix_path)
    if matrix_errors:
        raise IDFEnvironmentError("invalid IDF matrix: " + "; ".join(matrix_errors))

    lane_id = check_idf_matrix.CANONICAL_LANE_ID
    lane = matrix["lanes"][lane_id]
    selected_path = idf_path or (Path(os.environ["IDF_PATH"]) if os.environ.get("IDF_PATH") else None)
    if selected_path is None:
        raise IDFEnvironmentError("IDF_PATH is required to verify the source commit")
    selected_path = selected_path.expanduser().resolve()
    if not selected_path.is_dir():
        raise IDFEnvironmentError(f"IDF_PATH is not a directory: {selected_path}")

    selected_idf_py = idf_py or (Path(found) if (found := shutil.which("idf.py")) else None)
    if selected_idf_py is None:
        raise IDFEnvironmentError("idf.py is not available")
    selected_idf_py = selected_idf_py.expanduser().resolve()
    if not selected_idf_py.is_file():
        raise IDFEnvironmentError(f"idf.py is not a file: {selected_idf_py}")
    try:
        selected_idf_py.relative_to(selected_path)
    except ValueError as exc:
        raise IDFEnvironmentError(
            f"idf.py {selected_idf_py} is outside IDF_PATH {selected_path}"
        ) from exc

    host_platform = observed_platform or _host_platform()
    canonical_platform = str(lane["platform"])
    accepted_platforms = (
        (canonical_platform,) if allowed_platforms is None else allowed_platforms
    )
    if host_platform not in accepted_platforms:
        raise IDFEnvironmentError(
            f"host platform {host_platform!r} is not accepted; expected one of "
            f"{accepted_platforms!r}"
        )

    version_result = _run([str(selected_idf_py), "--version"], runner=runner)
    version_output = (version_result.stdout or version_result.stderr).strip()
    if version_result.returncode != 0:
        raise IDFEnvironmentError(f"idf.py --version failed: {version_output}")
    match = re.search(r"(?:ESP-IDF\s+)?(v\d+\.\d+\.\d+)(?:\s|$)", version_output)
    if match is None:
        raise IDFEnvironmentError(f"cannot parse exact ESP-IDF version from {version_output!r}")
    observed_version = match.group(1)
    if observed_version != lane["version"]:
        raise IDFEnvironmentError(
            f"ESP-IDF version {observed_version!r} does not match lane {lane['version']!r}"
        )

    git = shutil.which("git")
    if git is None:
        raise IDFEnvironmentError("git is required to verify the ESP-IDF source commit")
    commit_result = _run([git, "-C", str(selected_path), "rev-parse", "HEAD"], runner=runner)
    observed_commit = commit_result.stdout.strip()
    if commit_result.returncode != 0 or re.fullmatch(r"[0-9a-f]{40}", observed_commit) is None:
        detail = (commit_result.stderr or commit_result.stdout).strip()
        raise IDFEnvironmentError(f"cannot read exact ESP-IDF source commit: {detail}")
    if observed_commit != lane["source_commit"]:
        raise IDFEnvironmentError(
            f"ESP-IDF commit {observed_commit!r} does not match lane {lane['source_commit']!r}"
        )

    return {
        "schema": "pulse.esp32.idf-environment.v1",
        "status": "PASS",
        "lane_id": lane_id,
        "version": observed_version,
        "source_commit": observed_commit,
        "platform": host_platform,
        "canonical_platform": canonical_platform,
        "accepted_platforms": list(accepted_platforms),
        "container_image": lane["container_image"],
        "idf_path": str(selected_path),
        "idf_py": str(selected_idf_py),
        "attempted_targets": [entry["target"] for entry in matrix["realizations"].values()],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--idf-path", type=Path)
    parser.add_argument("--idf-py", type=Path)
    args = parser.parse_args(argv)
    try:
        report = verify_idf_environment(
            args.matrix,
            idf_path=args.idf_path,
            idf_py=args.idf_py,
        )
    except (check_idf_matrix.MatrixContractError, IDFEnvironmentError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
