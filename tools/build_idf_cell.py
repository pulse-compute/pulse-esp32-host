#!/usr/bin/env python3
"""Build one isolated ESP-IDF matrix cell or explicitly update its lock."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

try:
    from tools import check_idf_matrix, idf_lock, verify_idf_environment
except ModuleNotFoundError:  # Direct execution from tools/.
    import check_idf_matrix  # type: ignore[no-redef]
    import idf_lock  # type: ignore[no-redef]
    import verify_idf_environment  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = ROOT / "firmware" / "idf-family-matrix.json"
REPORT_SCHEMA = "pulse.esp32.idf-cell-report.v1"
PROJECT_NAME = "wdc_esp32_host"
GENERATED_NAMES = frozenset(
    {
        "build",
        "managed_components",
        "sdkconfig",
        "sdkconfig.old",
        "dependencies.lock",
        "locks",
        "__pycache__",
    }
)
EXPECTED_ARTIFACTS = {
    "application_elf": f"{PROJECT_NAME}.elf",
    "application_binary": f"{PROJECT_NAME}.bin",
    "bootloader_binary": "bootloader/bootloader.bin",
    "partition_table_binary": "partition_table/partition-table.bin",
}
INFRASTRUCTURE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(?:network|registry|connection|download|proxy)\b.*\b(?:fail|error|timeout|timed out|refused)\b",
        r"\b(?:timeout|timed out|temporary failure|connection reset|name resolution)\b",
        r"cannot establish a connection",
        r"component registry.*(?:skipping|unavailable)",
        r"\b(?:TLS|certificate|SSL)\b.*\b(?:fail|error|invalid|unable)\b",
        r"no space left on device",
        r"tool(?:chain)? .* (?:missing|not found|unavailable)",
    )
)
INCOMPATIBLE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"(?:fatal )?error:",
        r"undefined reference",
        r"unsupported (?:target|architecture|option|configuration)",
        r"unknown (?:kconfig|configuration|compiler) (?:symbol|option)",
        r"component .* (?:not found|is incompatible)",
    )
)
FAILURE_DETAIL_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"region [`']?[^`'\r\n]+[`']? overflowed by \d+ bytes",
        r"(?:fatal )?error: [^\r\n]+",
        r"undefined reference to [^\r\n]+",
        r"DRAM segment data does not fit\.",
    )
)


class CellLockError(RuntimeError):
    """Raised when an isolated lock operation cannot complete safely."""


class CellBuildError(RuntimeError):
    """A classified cell-build failure with normalized stage evidence."""

    def __init__(self, result: str, stage: str, message: str, log: str = "") -> None:
        super().__init__(message)
        self.result = check_idf_matrix.validate_result_name(result)
        self.stage = stage
        self.log = log


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_evidence(path: Path, logical_path: str) -> dict[str, Any]:
    data = path.read_bytes()
    return {"path": logical_path, "sha256": _sha256(data), "size": len(data)}


def _firmware_snapshot(firmware_root: Path, ignored_lock: Path | None = None) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    ignored = ignored_lock.resolve() if ignored_lock is not None else None
    for path in sorted(item for item in firmware_root.rglob("*") if item.is_file()):
        if ignored is not None and path.resolve() == ignored:
            continue
        relative = path.relative_to(firmware_root).as_posix()
        snapshot[relative] = _sha256(path.read_bytes())
    return snapshot


def _is_generated(relative: Path) -> bool:
    return any(part in GENERATED_NAMES for part in relative.parts)


def _source_inputs(firmware_root: Path) -> tuple[list[dict[str, Any]], str]:
    files: list[dict[str, Any]] = []
    digest = hashlib.sha256()
    for path in sorted(item for item in firmware_root.rglob("*") if item.is_file()):
        relative = path.relative_to(firmware_root)
        if _is_generated(relative):
            continue
        evidence = _file_evidence(path, relative.as_posix())
        files.append(evidence)
        digest.update(evidence["path"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(evidence["sha256"].encode("ascii"))
        digest.update(b"\n")
    return files, digest.hexdigest()


def _copy_firmware(source: Path, destination: Path) -> None:
    def ignore(_directory: str, names: list[str]) -> set[str]:
        return {name for name in names if name in GENERATED_NAMES}

    shutil.copytree(source, destination, ignore=ignore)


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_json(path: Path, value: Any) -> None:
    _atomic_write(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def _validate_owned_temp_root(path: Path) -> None:
    resolved = path.resolve()
    temp_base = Path(tempfile.gettempdir()).resolve()
    try:
        resolved.relative_to(temp_base)
    except ValueError as exc:
        raise CellBuildError(
            "UNCLASSIFIED_FAILURE", "temporary-root", "temporary root is outside the system temporary directory"
        ) from exc
    stat = resolved.stat()
    if not resolved.is_dir() or resolved.is_symlink() or stat.st_uid != os.getuid():
        raise CellBuildError(
            "UNCLASSIFIED_FAILURE", "temporary-root", "temporary root is not an owned, real directory"
        )


def _prepare_out_dir(out_dir: Path, firmware_root: Path) -> Path:
    resolved = out_dir.expanduser().resolve()
    try:
        resolved.relative_to(firmware_root.resolve())
    except ValueError:
        pass
    else:
        raise CellBuildError(
            "UNCLASSIFIED_FAILURE", "output", "output directory may not be inside the firmware source tree"
        )
    if resolved.exists():
        if not resolved.is_dir() or any(resolved.iterdir()):
            raise CellBuildError(
                "UNCLASSIFIED_FAILURE", "output", "output directory must be absent or empty"
            )
    else:
        resolved.mkdir(parents=True)
    return resolved


def _normalizer(replacements: dict[str, str]):
    ordered = sorted(
        ((key, value) for key, value in replacements.items() if key),
        key=lambda item: len(item[0]),
        reverse=True,
    )

    def normalize(value: str) -> str:
        normalized = value.replace("\\", "/")
        for actual, logical in ordered:
            normalized = normalized.replace(actual.replace("\\", "/"), logical)
        return normalized

    return normalize


def _normalize_json(value: Any, normalize) -> Any:
    if isinstance(value, str):
        return normalize(value)
    if isinstance(value, list):
        return [_normalize_json(item, normalize) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_json(item, normalize) for key, item in value.items()}
    return value


def _classify_command_failure(output: str) -> str:
    if any(pattern.search(output) for pattern in INFRASTRUCTURE_PATTERNS):
        return "INFRASTRUCTURE_FAILURE"
    if any(pattern.search(output) for pattern in INCOMPATIBLE_PATTERNS):
        return "INCOMPATIBLE"
    return "UNCLASSIFIED_FAILURE"


def _command_failure_detail(output: str) -> str | None:
    """Return the most specific deterministic boundary without log-path noise."""
    for pattern in FAILURE_DETAIL_PATTERNS:
        matches = tuple(pattern.finditer(output))
        if matches:
            return matches[-1].group(0)
    return None


def _timeout_output(exc: subprocess.TimeoutExpired) -> str:
    output = exc.stdout or ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output


def _run_command(
    command: list[str],
    *,
    stage: str,
    cwd: Path,
    environment: dict[str, str],
    deadline: float,
    normalize,
) -> tuple[str, str]:
    remaining = deadline - time.monotonic()
    display = normalize(" ".join(command))
    header = f"=== {stage} ===\n$ {display}\n"
    if remaining <= 0:
        raise CellBuildError(
            "INFRASTRUCTURE_FAILURE", stage, f"cell timeout expired before {stage}", header
        )
    try:
        process = subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=remaining,
        )
    except subprocess.TimeoutExpired as exc:
        partial = normalize(_timeout_output(exc))
        raise CellBuildError(
            "INFRASTRUCTURE_FAILURE",
            stage,
            f"cell timeout expired during {stage}",
            header + partial.rstrip() + "\n",
        ) from exc
    output = process.stdout or ""
    entry = header + normalize(output).rstrip() + "\n"
    if process.returncode != 0:
        message = f"{stage} command exited with status {process.returncode}"
        detail = _command_failure_detail(output)
        if detail is not None:
            message += f": {detail}"
        raise CellBuildError(
            _classify_command_failure(output),
            stage,
            message,
            entry,
        )
    return output, entry


def _parse_json_output(output: str) -> Any:
    decoder = json.JSONDecoder()
    parsed: list[tuple[int, int, Any]] = []
    for index, character in enumerate(output):
        if character not in "[{":
            continue
        try:
            value, end = decoder.raw_decode(output[index:])
        except json.JSONDecodeError:
            continue
        parsed.append((index + end, index, value))
    if not parsed:
        raise CellBuildError(
            "UNCLASSIFIED_FAILURE", "size", "idf.py size did not emit a JSON value"
        )
    # Prefer the value that reaches farthest into stdout. When an outer object
    # and one of its nested objects end together, prefer the outer object.
    return max(parsed, key=lambda item: (item[0], -item[1]))[2]


def _assert_staged_lock(
    staged_lock: Path,
    committed_bytes: bytes,
    *,
    stage: str,
    target: str,
    lane: dict[str, Any],
) -> dict[str, Any]:
    if not staged_lock.is_file():
        raise CellBuildError(
            "UNCLASSIFIED_FAILURE", stage, f"{stage} removed the staged dependency lock"
        )
    lock_errors, evidence = idf_lock.validate_lock(
        staged_lock,
        expected_target=target,
        expected_idf_version=lane["version"],
        expected_wamr_version=lane["wamr_version"],
    )
    if lock_errors:
        raise CellBuildError(
            "UNCLASSIFIED_FAILURE", stage, "staged dependency lock is invalid: " + "; ".join(lock_errors)
        )
    if staged_lock.read_bytes() != committed_bytes:
        raise CellBuildError(
            "UNCLASSIFIED_FAILURE", stage, f"{stage} mutated the staged dependency lock"
        )
    return evidence


def _assert_sdkconfig_target(sdkconfig: Path, target: str) -> None:
    expected = f'CONFIG_IDF_TARGET="{target}"'
    values = {
        line.strip()
        for line in sdkconfig.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("CONFIG_IDF_TARGET=")
    }
    if values != {expected}:
        observed = ", ".join(sorted(values)) if values else "missing"
        raise CellBuildError(
            "UNCLASSIFIED_FAILURE",
            "artifacts",
            f"generated sdkconfig target mismatch: expected {expected}, observed {observed}",
        )


def _base_report(cell_id: str, timeout: int) -> dict[str, Any]:
    return {
        "schema": REPORT_SCHEMA,
        "status": "FAIL",
        "result": "UNCLASSIFIED_FAILURE",
        "cell": cell_id,
        "timeout_seconds": timeout,
        "lane": None,
        "realization": None,
        "commands": [],
        "evidence": {"inputs": {}, "outputs": {}},
        "failure": None,
    }


def _write_failure_report(
    out_dir: Path,
    report: dict[str, Any],
    error: CellBuildError,
    log_entries: list[str],
    normalize,
) -> dict[str, Any]:
    if error.log:
        log_entries.append(error.log)
    log = "\n".join(entry.rstrip() for entry in log_entries if entry).rstrip() + "\n"
    if log.strip():
        log_path = out_dir / "build.log"
        _atomic_write(log_path, log.encode("utf-8"))
        report["evidence"]["outputs"]["build_log"] = _file_evidence(log_path, "build.log")
    report["status"] = "FAIL"
    report["result"] = error.result
    report["failure"] = {"stage": error.stage, "message": normalize(str(error))}
    _write_json(out_dir / "cell-report.json", report)
    return report


def build_cell(
    *,
    matrix_path: Path,
    cell_id: str,
    out_dir: Path,
    idf_path: Path | None = None,
    idf_py: Path | None = None,
    timeout: int = 1800,
) -> dict[str, Any]:
    """Run one complete isolated build and always emit a normalized cell report."""
    matrix_path = matrix_path.resolve()
    firmware_root = matrix_path.parent
    prepared_out = _prepare_out_dir(out_dir, firmware_root)
    report = _base_report(cell_id, timeout)
    log_entries: list[str] = []
    source_before: dict[str, str] | None = None
    deadline = time.monotonic() + timeout
    replacements = {
        str(ROOT.resolve()): "<repo>",
        str(firmware_root.resolve()): "<firmware>",
        str(prepared_out): "<out>",
        str(idf_path.resolve()) if idf_path else "": "<idf>",
        str(idf_py.resolve()) if idf_py else "": "<idf.py>",
    }
    normalize = _normalizer(replacements)

    try:
        try:
            matrix = check_idf_matrix.load_matrix(matrix_path)
        except check_idf_matrix.MatrixContractError as exc:
            raise CellBuildError("UNCLASSIFIED_FAILURE", "matrix", str(exc)) from exc
        matrix_errors = check_idf_matrix.validate_matrix(matrix, matrix_path)
        if matrix_errors:
            raise CellBuildError(
                "UNCLASSIFIED_FAILURE", "matrix", "invalid matrix: " + "; ".join(matrix_errors)
            )
        if cell_id not in matrix["realizations"]:
            raise CellBuildError(
                "UNCLASSIFIED_FAILURE", "matrix", f"unknown or non-attempted realization {cell_id!r}"
            )

        realization = matrix["realizations"][cell_id]
        resolved = check_idf_matrix.resolve_realization(matrix, cell_id, matrix_path)
        if resolved["config"].get("CONFIG_PARTITION_TABLE_CUSTOM_FILENAME") != realization["partitions"]:
            raise CellBuildError(
                "UNCLASSIFIED_FAILURE", "matrix", "resolved partition setting does not match the matrix"
            )
        lane = matrix["lanes"][realization["lane"]]

        def deadline_runner(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout)
            requested = kwargs.get("timeout")
            kwargs["timeout"] = min(float(requested), remaining) if requested is not None else remaining
            return subprocess.run(command, **kwargs)

        try:
            environment_evidence = verify_idf_environment.verify_idf_environment(
                matrix_path,
                idf_path=idf_path,
                idf_py=idf_py,
                runner=deadline_runner,
            )
        except verify_idf_environment.IDFEnvironmentError as exc:
            raise CellBuildError("INFRASTRUCTURE_FAILURE", "lane-verification", str(exc)) from exc

        committed_lock = (firmware_root / realization["dependency_lock"]).resolve()
        try:
            committed_lock.relative_to(firmware_root.resolve())
        except ValueError as exc:
            raise CellBuildError(
                "UNCLASSIFIED_FAILURE", "matrix", "dependency lock escapes the firmware tree"
            ) from exc
        if not committed_lock.is_file():
            raise CellBuildError(
                "UNCLASSIFIED_FAILURE", "inputs", "matrix-declared dependency lock is missing"
            )

        source_before = _firmware_snapshot(firmware_root)
        source_files, source_tree_sha = _source_inputs(firmware_root)
        committed_bytes = committed_lock.read_bytes()
        matrix_logical = matrix_path.name
        report["lane"] = {
            "id": realization["lane"],
            "version": environment_evidence["version"],
            "source_commit": environment_evidence["source_commit"],
            "platform": environment_evidence["platform"],
            "container_image": lane["container_image"],
            "wamr_version": lane["wamr_version"],
        }
        report["realization"] = {
            "id": cell_id,
            "target": realization["target"],
            "intent": realization["intent"],
            "defaults": realization["defaults"],
            "partitions": realization["partitions"],
            "dependency_lock": realization["dependency_lock"],
        }
        report["evidence"]["inputs"] = {
            "matrix": _file_evidence(matrix_path, matrix_logical),
            "source_tree_sha256": source_tree_sha,
            "source_files": source_files,
            "defaults": [
                _file_evidence(firmware_root / relative, relative)
                for relative in realization["defaults"]
            ],
            "partitions": _file_evidence(
                firmware_root / realization["partitions"], realization["partitions"]
            ),
            "dependency_lock": _file_evidence(
                committed_lock, realization["dependency_lock"]
            ),
        }

        with tempfile.TemporaryDirectory(prefix=f"pulse-idf-{realization['target']}-") as temp_name:
            temporary_root = Path(temp_name)
            _validate_owned_temp_root(temporary_root)
            project = temporary_root / "firmware"
            build_dir = temporary_root / "build"
            sdkconfig = temporary_root / "sdkconfig"
            _copy_firmware(firmware_root, project)
            staged_lock = project / "dependencies.lock"
            staged_lock.write_bytes(committed_bytes)

            replacements.update(
                {
                    str(temporary_root): "<tmp>",
                    str(project): "<project>",
                    str(build_dir): "<build>",
                    str(sdkconfig): "<sdkconfig>",
                    str(environment_evidence["idf_path"]): "<idf>",
                    str(environment_evidence["idf_py"]): "<idf.py>",
                }
            )
            normalize = _normalizer(replacements)
            defaults = [str(project / relative) for relative in realization["defaults"]]
            definitions = [
                "-B",
                str(build_dir),
                f"-DIDF_TARGET={realization['target']}",
                f"-DSDKCONFIG={sdkconfig}",
                f"-DSDKCONFIG_DEFAULTS={';'.join(defaults)}",
            ]
            reconfigure_command = [str(environment_evidence["idf_py"]), *definitions, "reconfigure"]
            build_command = [str(environment_evidence["idf_py"]), *definitions, "build"]
            size_command = [
                str(environment_evidence["idf_py"]),
                "-B",
                str(build_dir),
                "size",
                "--format",
                "json",
            ]
            report["commands"] = [
                normalize(" ".join(reconfigure_command)),
                normalize(" ".join(build_command)),
                normalize(" ".join(size_command)),
            ]
            process_environment = os.environ.copy()
            process_environment["IDF_TARGET"] = realization["target"]
            process_environment["IDF_PATH"] = str(environment_evidence["idf_path"])
            # Qualification must not inherit a warm host/container compiler cache.
            # Each cell therefore observes a clean compiler invocation even when
            # the surrounding ESP-IDF environment enables ccache by default.
            process_environment["IDF_CCACHE_ENABLE"] = "0"
            try:
                _output, entry = _run_command(
                    reconfigure_command,
                    stage="reconfigure",
                    cwd=project,
                    environment=process_environment,
                    deadline=deadline,
                    normalize=normalize,
                )
                log_entries.append(entry)
            except CellBuildError as exc:
                if exc.log:
                    log_entries.append(exc.log)
                    exc.log = ""
                raise
            lock_evidence = _assert_staged_lock(
                staged_lock,
                committed_bytes,
                stage="reconfigure",
                target=realization["target"],
                lane=lane,
            )

            try:
                _output, entry = _run_command(
                    build_command,
                    stage="build",
                    cwd=project,
                    environment=process_environment,
                    deadline=deadline,
                    normalize=normalize,
                )
                log_entries.append(entry)
            except CellBuildError as exc:
                if exc.log:
                    log_entries.append(exc.log)
                    exc.log = ""
                raise
            _assert_staged_lock(
                staged_lock,
                committed_bytes,
                stage="build",
                target=realization["target"],
                lane=lane,
            )

            missing = [
                relative for relative in EXPECTED_ARTIFACTS.values() if not (build_dir / relative).is_file()
            ]
            if missing:
                raise CellBuildError(
                    "UNCLASSIFIED_FAILURE",
                    "artifacts",
                    "build completed without required artifacts: " + ", ".join(missing),
                )
            if not sdkconfig.is_file():
                raise CellBuildError(
                    "UNCLASSIFIED_FAILURE", "artifacts", "build completed without generated sdkconfig"
                )
            _assert_sdkconfig_target(sdkconfig, realization["target"])

            try:
                size_output, entry = _run_command(
                    size_command,
                    stage="size",
                    cwd=project,
                    environment=process_environment,
                    deadline=deadline,
                    normalize=normalize,
                )
                log_entries.append(entry)
            except CellBuildError as exc:
                if exc.log:
                    log_entries.append(exc.log)
                    exc.log = ""
                raise
            _assert_staged_lock(
                staged_lock,
                committed_bytes,
                stage="size",
                target=realization["target"],
                lane=lane,
            )
            size_value = _normalize_json(_parse_json_output(size_output), normalize)

            if _firmware_snapshot(firmware_root) != source_before:
                raise CellBuildError(
                    "UNCLASSIFIED_FAILURE",
                    "source-integrity",
                    "firmware source tree changed during isolated build",
                )

            artifacts_root = prepared_out / "artifacts"
            artifact_evidence: dict[str, Any] = {}
            for name, relative in EXPECTED_ARTIFACTS.items():
                destination = artifacts_root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(build_dir / relative, destination)
                artifact_evidence[name] = _file_evidence(
                    destination, f"artifacts/{relative}"
                )
            shutil.copy2(sdkconfig, prepared_out / "sdkconfig")
            _write_json(prepared_out / "size.json", size_value)
            normalized_log = "\n".join(entry.rstrip() for entry in log_entries).rstrip() + "\n"
            _atomic_write(prepared_out / "build.log", normalized_log.encode("utf-8"))

            report["evidence"]["outputs"] = {
                "artifacts": artifact_evidence,
                "sdkconfig": _file_evidence(prepared_out / "sdkconfig", "sdkconfig"),
                "size": _file_evidence(prepared_out / "size.json", "size.json"),
                "build_log": _file_evidence(prepared_out / "build.log", "build.log"),
                "resolved_lock": {
                    "path": realization["dependency_lock"],
                    "sha256": lock_evidence["sha256"],
                    "target": lock_evidence["target"],
                    "wamr_version": lock_evidence["wamr_version"],
                    "wamr_component_hash": lock_evidence["wamr_component_hash"],
                },
            }

        if _firmware_snapshot(firmware_root) != source_before:
            raise CellBuildError(
                "UNCLASSIFIED_FAILURE", "source-integrity", "firmware source tree changed during isolated build"
            )
        report["status"] = "PASS"
        report["result"] = "COMPILE_PROVEN"
        report["failure"] = None
        _write_json(prepared_out / "cell-report.json", report)
        return report

    except CellBuildError as exc:
        if source_before is not None and _firmware_snapshot(firmware_root) != source_before:
            exc = CellBuildError(
                "UNCLASSIFIED_FAILURE", "source-integrity", "firmware source tree changed during isolated build"
            )
        return _write_failure_report(prepared_out, report, exc, log_entries, normalize)
    except (OSError, ValueError) as exc:
        error = CellBuildError("UNCLASSIFIED_FAILURE", "builder", str(exc))
        if source_before is not None and _firmware_snapshot(firmware_root) != source_before:
            error = CellBuildError(
                "UNCLASSIFIED_FAILURE", "source-integrity", "firmware source tree changed during isolated build"
            )
        return _write_failure_report(prepared_out, report, error, log_entries, normalize)
    except Exception as exc:  # Preserve a cell report for unexpected builder failures.
        error = CellBuildError("UNCLASSIFIED_FAILURE", "builder", str(exc))
        if source_before is not None and _firmware_snapshot(firmware_root) != source_before:
            error = CellBuildError(
                "UNCLASSIFIED_FAILURE", "source-integrity", "firmware source tree changed during isolated build"
            )
        return _write_failure_report(prepared_out, report, error, log_entries, normalize)


def configure_lock(
    *,
    matrix_path: Path,
    cell_id: str,
    update_lock: bool,
    idf_path: Path | None = None,
    idf_py: Path | None = None,
    timeout: int = 900,
) -> dict[str, Any]:
    """Preserve IF2's explicit, isolated lock update and no-diff verification mode."""
    matrix_path = matrix_path.resolve()
    matrix = check_idf_matrix.load_matrix(matrix_path)
    matrix_errors = check_idf_matrix.validate_matrix(matrix, matrix_path)
    if matrix_errors:
        raise CellLockError("invalid matrix: " + "; ".join(matrix_errors))
    realizations = matrix["realizations"]
    if cell_id not in realizations:
        raise CellLockError(f"unknown or non-attempted realization {cell_id!r}")

    realization = realizations[cell_id]
    resolved = check_idf_matrix.resolve_realization(matrix, cell_id, matrix_path)
    if resolved["config"].get("CONFIG_PARTITION_TABLE_CUSTOM_FILENAME") != realization["partitions"]:
        raise CellLockError("resolved partition setting does not match the matrix")

    environment = verify_idf_environment.verify_idf_environment(
        matrix_path, idf_path=idf_path, idf_py=idf_py
    )
    lane = matrix["lanes"][realization["lane"]]
    firmware_root = matrix_path.parent
    committed_lock = (firmware_root / realization["dependency_lock"]).resolve()
    try:
        committed_lock.relative_to(firmware_root.resolve())
    except ValueError as exc:
        raise CellLockError("dependency lock escapes the firmware tree") from exc
    if not update_lock and not committed_lock.is_file():
        raise CellLockError(f"committed lock is required for normal resolution: {committed_lock}")

    before = _firmware_snapshot(firmware_root, committed_lock if update_lock else None)
    committed_bytes = committed_lock.read_bytes() if committed_lock.is_file() else None
    with tempfile.TemporaryDirectory(prefix=f"pulse-idf-{realization['target']}-") as temp_name:
        temporary_root = Path(temp_name)
        _validate_owned_temp_root(temporary_root)
        project = temporary_root / "firmware"
        build_dir = temporary_root / "build"
        sdkconfig = temporary_root / "sdkconfig"
        _copy_firmware(firmware_root, project)
        staged_lock = project / "dependencies.lock"
        if committed_bytes is not None:
            staged_lock.write_bytes(committed_bytes)

        defaults = [str(project / relative) for relative in realization["defaults"]]
        command = [
            str(environment["idf_py"]),
            "-B",
            str(build_dir),
            f"-DIDF_TARGET={realization['target']}",
            f"-DSDKCONFIG={sdkconfig}",
            f"-DSDKCONFIG_DEFAULTS={';'.join(defaults)}",
            "reconfigure",
        ]
        process_environment = os.environ.copy()
        process_environment["IDF_TARGET"] = realization["target"]
        process_environment["IDF_PATH"] = str(environment["idf_path"])
        try:
            process = subprocess.run(
                command,
                cwd=project,
                env=process_environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise CellLockError(f"IDF lock configuration timed out after {timeout}s") from exc
        if process.returncode != 0:
            raise CellLockError(
                f"IDF lock configuration failed ({process.returncode}):\n{process.stdout.strip()}"
            )
        if not staged_lock.is_file():
            raise CellLockError("IDF configuration did not produce dependencies.lock")
        lock_errors, evidence = idf_lock.validate_lock(
            staged_lock,
            expected_target=realization["target"],
            expected_idf_version=lane["version"],
            expected_wamr_version=lane["wamr_version"],
        )
        if lock_errors:
            raise CellLockError("generated lock is invalid: " + "; ".join(lock_errors))
        generated_bytes = staged_lock.read_bytes()

    changed = committed_bytes != generated_bytes
    if update_lock:
        if changed:
            _atomic_write(committed_lock, generated_bytes)
    elif changed:
        raise CellLockError(
            "normal resolution would mutate the committed dependency lock; "
            "run the explicit --update-lock command and review the diff"
        )
    after = _firmware_snapshot(firmware_root, committed_lock if update_lock else None)
    if before != after:
        raise CellLockError("files outside the selected dependency lock changed during isolated resolution")

    evidence["path"] = realization["dependency_lock"]
    return {
        "schema": "pulse.esp32.idf-lock-update.v1",
        "status": "PASS",
        "lane_id": realization["lane"],
        "cell": cell_id,
        "target": realization["target"],
        "defaults": realization["defaults"],
        "partitions": realization["partitions"],
        "update_lock": update_lock,
        "changed": changed,
        "lock": evidence,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--cell", required=True)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--update-lock", action="store_true")
    parser.add_argument("--idf-path", type=Path)
    parser.add_argument("--idf-py", type=Path)
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args(argv)
    if args.timeout < 1:
        print("ERROR: --timeout must be positive", file=sys.stderr)
        return 2
    if args.update_lock:
        if args.out_dir is not None:
            print("ERROR: --out-dir cannot be combined with --update-lock", file=sys.stderr)
            return 2
        try:
            report = configure_lock(
                matrix_path=args.matrix,
                cell_id=args.cell,
                update_lock=True,
                idf_path=args.idf_path,
                idf_py=args.idf_py,
                timeout=args.timeout,
            )
        except (
            check_idf_matrix.MatrixContractError,
            verify_idf_environment.IDFEnvironmentError,
            CellLockError,
            OSError,
        ) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    if args.out_dir is None:
        print("ERROR: --out-dir is required for a cell build", file=sys.stderr)
        return 2
    try:
        report = build_cell(
            matrix_path=args.matrix,
            cell_id=args.cell,
            out_dir=args.out_dir,
            idf_path=args.idf_path,
            idf_py=args.idf_py,
            timeout=args.timeout,
        )
    except CellBuildError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
