#!/usr/bin/env python3
"""Qualify the required ESP32-S3 reference with two clean pinned-lane builds."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

try:
    from tools import build_idf_cell, check_idf_matrix
except ModuleNotFoundError:  # Direct execution from tools/.
    import build_idf_cell  # type: ignore[no-redef]
    import check_idf_matrix  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = ROOT / "firmware" / "idf-family-matrix.json"
REFERENCE_CELL = "esp32s3-reference"
REPORT_SCHEMA = "pulse.esp32.idf-reference-qualification.v1"
DEFERRED_STATUS = "DEFERRED_NO_HARDWARE_IF4"
DEFERRED_HARDWARE = (
    "flashing, booting, and serial monitoring an ESP32-S3",
    "WAMR allocation, lifecycle, trap, and PSRAM behavior on device",
    "GPIO electrical safe-state behavior",
    "watchdog, reset, native OTA, and rollback behavior",
    "flash persistence and controlled power-loss behavior",
    "secure boot, flash encryption, eFuse, and key provisioning",
    "production signature verification on device",
    "Wi-Fi, lwIP, TLS, MQTT, HTTP, reconnect, and backpressure behavior",
    "FreeRTOS task topology, priorities, queues, and core ownership",
    "hardware-in-loop workflow creation",
)

CellBuilder = Callable[..., dict[str, Any]]


class ReferenceQualificationError(RuntimeError):
    """A fail-closed reference qualification gate."""

    def __init__(
        self, gate: str, message: str, result: str = "UNCLASSIFIED_FAILURE"
    ) -> None:
        super().__init__(message)
        self.gate = gate
        self.result = check_idf_matrix.validate_result_name(result)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    build_idf_cell._atomic_write(  # noqa: SLF001 - shared repository evidence primitive.
        path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )


def _prepare_out_dir(out_dir: Path, firmware_root: Path) -> Path:
    resolved = out_dir.expanduser().resolve()
    try:
        resolved.relative_to(firmware_root.resolve())
    except ValueError:
        pass
    else:
        raise ReferenceQualificationError(
            "output", "qualification output may not be inside the firmware source tree"
        )
    if resolved.exists():
        if not resolved.is_dir() or any(resolved.iterdir()):
            raise ReferenceQualificationError(
                "output", "qualification output directory must be absent or empty"
            )
    else:
        resolved.mkdir(parents=True)
    return resolved


def _base_report(
    observed_image: str | None, execution_adapter: str, timeout: int
) -> dict[str, Any]:
    return {
        "schema": REPORT_SCHEMA,
        "status": "FAIL",
        "result": "UNCLASSIFIED_FAILURE",
        "cell": REFERENCE_CELL,
        "required_runs": 2,
        "timeout_seconds_per_run": timeout,
        "observed_container_image": observed_image,
        "execution_adapter": execution_adapter,
        "lane": None,
        "runs": [],
        "comparisons": {
            "inputs_identical": False,
            "sdkconfig_identical": False,
            "dependency_lock_identical": False,
            "artifacts": {},
        },
        "failed_gates": [],
        "deferred_hardware": [
            {"status": DEFERRED_STATUS, "work": item} for item in DEFERRED_HARDWARE
        ],
    }


def _markdown(report: dict[str, Any]) -> str:
    lane = report.get("lane") or {}
    lines = [
        "# ESP32-S3 reference build qualification",
        "",
        f"- Status: `{report['status']}`",
        f"- Result: `{report['result']}`",
        f"- Cell: `{report['cell']}`",
        f"- ESP-IDF: `{lane.get('version', 'unobserved')}`",
        f"- Source commit: `{lane.get('source_commit', 'unobserved')}`",
        f"- Container: `{report.get('observed_container_image') or 'unobserved'}`",
        f"- Execution adapter: `{report['execution_adapter']}`",
        "",
        "## Runs",
        "",
        "| Run | Status | Result | Duration (seconds) | Report |",
        "|---|---|---|---:|---|",
    ]
    for run in report["runs"]:
        lines.append(
            f"| {run['id']} | {run['status']} | {run['result']} | "
            f"{run['duration_seconds']:.3f} | `{run['report']}` |"
        )
    if not report["runs"]:
        lines.append("| — | not run | — | 0 | — |")

    lines.extend(["", "## Reproducibility", ""])
    comparisons = report["comparisons"]
    lines.extend(
        [
            f"- Declared inputs identical: `{comparisons['inputs_identical']}`",
            f"- Generated sdkconfig identical: `{comparisons['sdkconfig_identical']}`",
            f"- Resolved dependency lock identical: `{comparisons['dependency_lock_identical']}`",
        ]
    )
    for name, comparison in sorted(comparisons["artifacts"].items()):
        lines.append(
            f"- `{name}`: identical=`{comparison['identical']}`, "
            f"size=`{comparison['run_a']['size']}`, sha256=`{comparison['run_a']['sha256']}`"
        )

    lines.extend(["", "## Failed gates", ""])
    if report["failed_gates"]:
        lines.extend(f"- `{item['gate']}`: {item['message']}" for item in report["failed_gates"])
    else:
        lines.append("- None.")

    lines.extend(
        [
            "",
            "## Explicitly deferred hardware work",
            "",
            *(
                f"- `{item['status']}` — {item['work']}"
                for item in report["deferred_hardware"]
            ),
            "",
            "This report is build evidence only. It is not runtime, board, electrical, "
            "network, FreeRTOS, provider, security, or production qualification.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_reports(out_dir: Path, report: dict[str, Any]) -> None:
    _write_json(out_dir / "qualification-report.json", report)
    build_idf_cell._atomic_write(  # noqa: SLF001 - shared repository evidence primitive.
        out_dir / "qualification-report.md", _markdown(report).encode("utf-8")
    )


def _run_evidence(run_id: str, run_dir: Path, report: dict[str, Any], duration: float) -> dict[str, Any]:
    report_path = run_dir / "cell-report.json"
    if not report_path.is_file():
        raise ReferenceQualificationError(
            f"run-{run_id}", f"run {run_id} did not write cell-report.json"
        )
    return {
        "id": run_id,
        "status": report.get("status"),
        "result": report.get("result"),
        "duration_seconds": round(duration, 3),
        "report": f"run-{run_id}/cell-report.json",
        "report_sha256": _sha256(report_path),
    }


def _require_run_pass(run_id: str, report: dict[str, Any]) -> None:
    if report.get("status") != "PASS" or report.get("result") != "COMPILE_PROVEN":
        failure = report.get("failure") or {}
        detail = failure.get("message") or "cell build did not produce COMPILE_PROVEN"
        try:
            result = check_idf_matrix.validate_result_name(report.get("result"))
        except check_idf_matrix.MatrixContractError:
            result = "UNCLASSIFIED_FAILURE"
        raise ReferenceQualificationError(f"run-{run_id}", detail, result)


def _compare_runs(
    out_dir: Path,
    first: dict[str, Any],
    second: dict[str, Any],
    report: dict[str, Any],
) -> None:
    first_inputs = first.get("evidence", {}).get("inputs")
    second_inputs = second.get("evidence", {}).get("inputs")
    report["comparisons"]["inputs_identical"] = first_inputs == second_inputs
    if not report["comparisons"]["inputs_identical"]:
        raise ReferenceQualificationError(
            "input-reproducibility", "the two runs did not declare identical source and matrix inputs"
        )

    first_outputs = first.get("evidence", {}).get("outputs", {})
    second_outputs = second.get("evidence", {}).get("outputs", {})
    first_lock = first_outputs.get("resolved_lock")
    second_lock = second_outputs.get("resolved_lock")
    committed_lock = first_inputs.get("dependency_lock") if isinstance(first_inputs, dict) else None
    lock_identical = (
        isinstance(first_lock, dict)
        and first_lock == second_lock
        and isinstance(committed_lock, dict)
        and first_lock.get("sha256") == committed_lock.get("sha256")
    )
    report["comparisons"]["dependency_lock_identical"] = lock_identical
    if not lock_identical:
        raise ReferenceQualificationError(
            "dependency-reproducibility", "resolved dependency locks differ or do not match the committed lock"
        )

    first_sdkconfig = out_dir / "run-a" / "sdkconfig"
    second_sdkconfig = out_dir / "run-b" / "sdkconfig"
    sdkconfig_identical = (
        first_sdkconfig.is_file()
        and second_sdkconfig.is_file()
        and first_sdkconfig.read_bytes() == second_sdkconfig.read_bytes()
    )
    report["comparisons"]["sdkconfig_identical"] = sdkconfig_identical
    if not sdkconfig_identical:
        raise ReferenceQualificationError(
            "configuration-reproducibility", "generated sdkconfig files are not byte-identical"
        )

    first_artifacts = first_outputs.get("artifacts")
    second_artifacts = second_outputs.get("artifacts")
    if not isinstance(first_artifacts, dict) or set(first_artifacts) != set(build_idf_cell.EXPECTED_ARTIFACTS):
        raise ReferenceQualificationError("artifact-evidence", "run a artifact evidence is incomplete")
    if not isinstance(second_artifacts, dict) or set(second_artifacts) != set(first_artifacts):
        raise ReferenceQualificationError("artifact-evidence", "run b artifact evidence is incomplete")

    mismatched: list[str] = []
    for name, relative in build_idf_cell.EXPECTED_ARTIFACTS.items():
        first_path = out_dir / "run-a" / "artifacts" / relative
        second_path = out_dir / "run-b" / "artifacts" / relative
        if not first_path.is_file() or not second_path.is_file():
            raise ReferenceQualificationError(
                "artifact-evidence", f"required artifact {relative} is missing from a qualification run"
            )
        first_size = first_path.stat().st_size
        second_size = second_path.stat().st_size
        first_sha = _sha256(first_path)
        second_sha = _sha256(second_path)
        evidence = {
            "path": f"artifacts/{relative}",
            "run_a": {"size": first_size, "sha256": first_sha},
            "run_b": {"size": second_size, "sha256": second_sha},
            "identical": first_size > 0 and first_size == second_size and first_sha == second_sha,
        }
        report["comparisons"]["artifacts"][name] = evidence
        if not evidence["identical"]:
            mismatched.append(relative)
    if mismatched:
        raise ReferenceQualificationError(
            "artifact-reproducibility", "non-reproducible artifacts: " + ", ".join(mismatched)
        )


def qualify_reference(
    *,
    matrix_path: Path,
    out_dir: Path,
    observed_container_image: str | None,
    execution_adapter: str = "none",
    idf_path: Path | None = None,
    idf_py: Path | None = None,
    timeout: int = 1800,
    cell_builder: CellBuilder = build_idf_cell.build_cell,
) -> dict[str, Any]:
    """Run and compare the two clean observations required for S3 qualification."""
    matrix_path = matrix_path.resolve()
    firmware_root = matrix_path.parent
    prepared_out = _prepare_out_dir(out_dir, firmware_root)
    report = _base_report(observed_container_image, execution_adapter, timeout)

    try:
        matrix = check_idf_matrix.load_matrix(matrix_path)
        errors = check_idf_matrix.validate_matrix(matrix, matrix_path)
        if errors:
            raise ReferenceQualificationError("matrix", "invalid matrix: " + "; ".join(errors))
        realization = matrix["realizations"][REFERENCE_CELL]
        if (
            realization["intent"] != "required"
            or realization["target"] != "esp32s3"
            or realization["reproducibility_runs"] != 2
        ):
            raise ReferenceQualificationError(
                "matrix", "the reference realization must require exactly two esp32s3 builds"
            )
        lane = matrix["lanes"][realization["lane"]]
        report["lane"] = {"id": realization["lane"], **lane}
        if observed_container_image is None:
            raise ReferenceQualificationError(
                "container-identity",
                "the observed pinned container image is required",
                "INFRASTRUCTURE_FAILURE",
            )
        if observed_container_image != lane["container_image"]:
            raise ReferenceQualificationError(
                "container-identity",
                "observed container image does not match the matrix-declared digest",
                "INFRASTRUCTURE_FAILURE",
            )

        run_reports: list[dict[str, Any]] = []
        for run_id in ("a", "b"):
            run_dir = prepared_out / f"run-{run_id}"
            started = time.monotonic()
            run_report = cell_builder(
                matrix_path=matrix_path,
                cell_id=REFERENCE_CELL,
                out_dir=run_dir,
                idf_path=idf_path,
                idf_py=idf_py,
                timeout=timeout,
            )
            duration = time.monotonic() - started
            report["runs"].append(_run_evidence(run_id, run_dir, run_report, duration))
            _require_run_pass(run_id, run_report)
            run_reports.append(run_report)

        _compare_runs(prepared_out, run_reports[0], run_reports[1], report)
        report["status"] = "PASS"
        report["result"] = "BUILD_QUALIFIED"
    except ReferenceQualificationError as exc:
        report["result"] = exc.result
        report["failed_gates"].append({"gate": exc.gate, "message": str(exc)})
    except (OSError, ValueError, check_idf_matrix.MatrixContractError) as exc:
        report["failed_gates"].append({"gate": "qualification", "message": str(exc)})
    except Exception as exc:  # Preserve evidence for an unexpected qualification failure.
        report["failed_gates"].append({"gate": "qualification", "message": str(exc)})

    _write_reports(prepared_out, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument(
        "--observed-container-image",
        default=os.environ.get("PULSE_IDF_CONTAINER_IMAGE"),
    )
    parser.add_argument(
        "--execution-adapter",
        default=os.environ.get("PULSE_IDF_EXECUTION_ADAPTER", "none"),
    )
    parser.add_argument("--idf-path", type=Path)
    parser.add_argument("--idf-py", type=Path)
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args(argv)
    if args.timeout < 1:
        print("ERROR: --timeout must be positive", file=sys.stderr)
        return 2
    try:
        report = qualify_reference(
            matrix_path=args.matrix,
            out_dir=args.out_dir,
            observed_container_image=args.observed_container_image,
            execution_adapter=args.execution_adapter,
            idf_path=args.idf_path,
            idf_py=args.idf_py,
            timeout=args.timeout,
        )
    except ReferenceQualificationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
