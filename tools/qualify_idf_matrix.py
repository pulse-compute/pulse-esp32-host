#!/usr/bin/env python3
"""Run the pinned ESP-IDF family matrix as one fail-closed qualification."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Callable

try:
    from tools import build_idf_cell, check_idf_matrix, qualify_idf_reference
except ModuleNotFoundError:  # Direct execution from tools/.
    import build_idf_cell  # type: ignore[no-redef]
    import check_idf_matrix  # type: ignore[no-redef]
    import qualify_idf_reference  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = ROOT / "firmware" / "idf-family-matrix.json"
REPORT_SCHEMA = "pulse.esp32.idf-matrix-qualification.v1"
REFERENCE_CELL = "esp32s3-reference"
EXPLORATORY_CELLS = ("esp32c3-compile", "esp32-compile", "esp32c6-compile")
ACCEPTABLE_EXPLORATORY_RESULTS = frozenset({"COMPILE_PROVEN", "INCOMPATIBLE"})
POLICY_STATUS = "NOT_ATTEMPTED_POLICY"

ReferenceQualifier = Callable[..., dict[str, Any]]
CellBuilder = Callable[..., dict[str, Any]]


class MatrixQualificationError(RuntimeError):
    """Raised when aggregate qualification cannot safely start."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write(path: Path, data: bytes) -> None:
    build_idf_cell._atomic_write(path, data)  # noqa: SLF001 - shared evidence primitive.


def _write_json(path: Path, value: Any) -> None:
    _write(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def _prepare_out_dir(out_dir: Path, firmware_root: Path) -> Path:
    resolved = out_dir.expanduser().resolve()
    try:
        resolved.relative_to(firmware_root.resolve())
    except ValueError:
        pass
    else:
        raise MatrixQualificationError("matrix output may not be inside the firmware source tree")
    if resolved.exists():
        if not resolved.is_dir() or any(resolved.iterdir()):
            raise MatrixQualificationError("matrix output directory must be absent or empty")
    else:
        resolved.mkdir(parents=True)
    return resolved


def _base_report(
    *, include_exploratory: bool, observed_image: str | None, execution_adapter: str, timeout: int
) -> dict[str, Any]:
    return {
        "schema": REPORT_SCHEMA,
        "status": "FAIL",
        "mode": "family" if include_exploratory else "reference-only",
        "observed_container_image": observed_image,
        "execution_adapter": execution_adapter,
        "timeout_seconds_per_build": timeout,
        "lane": None,
        "source_tree_sha256": None,
        "cells": [],
        "inventory": {"deferred": [], "excluded": []},
        "result_counts": {},
        "failed_gates": [],
        "disclaimer": (
            "Build evidence only; no board, runtime, electrical, network, FreeRTOS, provider, "
            "security, or production behavior was qualified."
        ),
    }


def _fail(report: dict[str, Any], gate: str, message: str) -> None:
    item = {"gate": gate, "message": message}
    if item not in report["failed_gates"]:
        report["failed_gates"].append(item)


def _file_matches(root: Path, evidence: Any) -> bool:
    if not isinstance(evidence, dict):
        return False
    relative = evidence.get("path")
    expected_sha = evidence.get("sha256")
    expected_size = evidence.get("size")
    if not isinstance(relative, str) or not relative or not isinstance(expected_sha, str):
        return False
    pure = PurePosixPath(relative)
    if (
        "\\" in relative
        or pure.is_absolute()
        or str(pure) != relative
        or any(part in {".", ".."} for part in pure.parts)
    ):
        return False
    path = root.joinpath(*pure.parts)
    return (
        path.is_file()
        and isinstance(expected_size, int)
        and path.stat().st_size == expected_size
        and _sha256(path) == expected_sha
    )


def _cell_source(report: dict[str, Any]) -> str | None:
    inputs = report.get("evidence", {}).get("inputs", {})
    value = inputs.get("source_tree_sha256") if isinstance(inputs, dict) else None
    return (
        value
        if isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
        else None
    )


def _verify_cell_evidence(cell_dir: Path, report: dict[str, Any]) -> tuple[bool, str]:
    if report.get("schema") != build_idf_cell.REPORT_SCHEMA:
        return False, "cell report schema is missing or unsupported"
    if not _cell_source(report):
        return False, "source-tree hash is missing"
    outputs = report.get("evidence", {}).get("outputs", {})
    if not isinstance(outputs, dict) or not _file_matches(cell_dir, outputs.get("build_log")):
        return False, "build-log evidence is missing or does not match disk"
    result = report.get("result")
    if result == "COMPILE_PROVEN":
        if report.get("status") != "PASS":
            return False, "COMPILE_PROVEN cell is not PASS"
        artifacts = outputs.get("artifacts")
        if not isinstance(artifacts, dict) or set(artifacts) != set(build_idf_cell.EXPECTED_ARTIFACTS):
            return False, "artifact evidence is incomplete"
        for name, evidence in artifacts.items():
            if not _file_matches(cell_dir, evidence):
                return False, f"artifact evidence does not match disk: {name}"
        for name in ("sdkconfig", "size"):
            if not _file_matches(cell_dir, outputs.get(name)):
                return False, f"{name} evidence is missing or does not match disk"
        lock = outputs.get("resolved_lock")
        inputs = report.get("evidence", {}).get("inputs", {})
        committed = inputs.get("dependency_lock") if isinstance(inputs, dict) else None
        if not isinstance(lock, dict) or not isinstance(committed, dict):
            return False, "dependency-lock evidence is incomplete"
        if lock.get("sha256") != committed.get("sha256"):
            return False, "resolved dependency lock does not match the committed lock"
        return True, "complete compile evidence"
    if result == "INCOMPATIBLE":
        failure = report.get("failure")
        if report.get("status") != "FAIL" or not isinstance(failure, dict):
            return False, "INCOMPATIBLE cell has no normalized failure"
        stage, message = failure.get("stage"), failure.get("message")
        if not isinstance(stage, str) or not stage or not isinstance(message, str) or not message:
            return False, "INCOMPATIBLE failure boundary is incomplete"
        if not any(pattern.search(message) for pattern in build_idf_cell.FAILURE_DETAIL_PATTERNS):
            return False, "INCOMPATIBLE failure boundary is generic rather than deterministic"
        return True, "complete deterministic incompatibility evidence"
    if result in {"INFRASTRUCTURE_FAILURE", "UNCLASSIFIED_FAILURE"}:
        return True, "failure report and build log preserved"
    return False, f"unsupported result {result!r}"


def _summary(
    *, cell: str, intent: str, report_path: Path, root: Path, report: dict[str, Any]
) -> dict[str, Any]:
    on_disk: dict[str, Any] | None = None
    try:
        loaded = json.loads(report_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            on_disk = loaded
    except (OSError, json.JSONDecodeError):
        pass
    effective = on_disk or report
    complete, detail = _verify_cell_evidence(report_path.parent, effective)
    if on_disk is None:
        complete, detail = False, "cell report is missing or invalid"
    elif on_disk != report:
        complete, detail = False, "returned cell report does not match the preserved report"
    failure = effective.get("failure")
    return {
        "id": cell,
        "intent": intent,
        "status": effective.get("status"),
        "result": effective.get("result"),
        "report": report_path.relative_to(root).as_posix(),
        "report_sha256": _sha256(report_path) if report_path.is_file() else None,
        "source_tree_sha256": _cell_source(effective),
        "evidence_complete": complete,
        "evidence_detail": detail,
        "failure": failure if isinstance(failure, dict) else None,
    }


def _reference_summary(root: Path, reference_dir: Path, report: dict[str, Any]) -> dict[str, Any]:
    report_path = reference_dir / "qualification-report.json"
    runs = report.get("runs")
    complete = report_path.is_file() and isinstance(runs, list) and len(runs) == 2
    sources: list[str] = []
    if complete:
        for run in ("a", "b"):
            cell_path = reference_dir / f"run-{run}" / "cell-report.json"
            try:
                cell_report = json.loads(cell_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                complete = False
                continue
            valid, _detail = _verify_cell_evidence(cell_path.parent, cell_report)
            complete = complete and valid
            source = _cell_source(cell_report)
            if source:
                sources.append(source)
    comparisons = report.get("comparisons", {})
    reproducible = (
        isinstance(comparisons, dict)
        and comparisons.get("inputs_identical") is True
        and comparisons.get("sdkconfig_identical") is True
        and comparisons.get("dependency_lock_identical") is True
        and isinstance(comparisons.get("artifacts"), dict)
        and set(comparisons["artifacts"]) == set(build_idf_cell.EXPECTED_ARTIFACTS)
        and all(item.get("identical") is True for item in comparisons["artifacts"].values())
    )
    complete = complete and reproducible and len(sources) == 2 and len(set(sources)) == 1
    return {
        "id": REFERENCE_CELL,
        "intent": "required",
        "status": report.get("status"),
        "result": report.get("result"),
        "report": report_path.relative_to(root).as_posix(),
        "report_sha256": _sha256(report_path) if report_path.is_file() else None,
        "source_tree_sha256": sources[0] if len(set(sources)) == 1 else None,
        "evidence_complete": complete,
        "evidence_detail": "two complete reproducible builds" if complete else "reference evidence is incomplete",
        "failure": None,
    }


def _markdown(report: dict[str, Any]) -> str:
    lane = report.get("lane") or {}
    lines = [
        "# ESP-IDF family matrix qualification",
        "",
        f"- Status: `{report['status']}`",
        f"- Mode: `{report['mode']}`",
        f"- ESP-IDF: `{lane.get('version', 'unobserved')}`",
        f"- Source commit: `{lane.get('source_commit', 'unobserved')}`",
        f"- Container: `{report.get('observed_container_image') or 'unobserved'}`",
        f"- Execution adapter: `{report['execution_adapter']}`",
        f"- Firmware source tree: `{report.get('source_tree_sha256') or 'unobserved'}`",
        "",
        "## Attempted cells",
        "",
        "| Cell | Intent | Status | Result | Evidence | Report |",
        "|---|---|---|---|---|---|",
    ]
    for cell in report["cells"]:
        lines.append(
            f"| {cell['id']} | {cell['intent']} | {cell['status']} | {cell['result']} | "
            f"{'complete' if cell['evidence_complete'] else 'incomplete'} | `{cell['report']}` |"
        )
    if not report["cells"]:
        lines.append("| — | — | not run | — | incomplete | — |")
    lines.extend(["", "## Failed gates", ""])
    if report["failed_gates"]:
        lines.extend(f"- `{item['gate']}`: {item['message']}" for item in report["failed_gates"])
    else:
        lines.append("- None.")
    lines.extend(["", "## Policy inventory", ""])
    for kind in ("deferred", "excluded"):
        for item in report["inventory"][kind]:
            lines.append(f"- `{item['id']}`: `{item['status']}` — {item['reason']}")
    lines.extend(["", report["disclaimer"], ""])
    return "\n".join(lines)


def _write_reports(out_dir: Path, report: dict[str, Any]) -> None:
    _write_json(out_dir / "matrix-report.json", report)
    _write(out_dir / "matrix-report.md", _markdown(report).encode("utf-8"))


def qualify_matrix(
    *,
    matrix_path: Path,
    out_dir: Path,
    observed_container_image: str | None,
    include_exploratory: bool,
    execution_adapter: str = "none",
    idf_path: Path | None = None,
    idf_py: Path | None = None,
    timeout: int = 1800,
    reference_qualifier: ReferenceQualifier = qualify_idf_reference.qualify_reference,
    cell_builder: CellBuilder = build_idf_cell.build_cell,
) -> dict[str, Any]:
    """Run all requested matrix observations and aggregate their evidence."""
    matrix_path = matrix_path.resolve()
    prepared = _prepare_out_dir(out_dir, matrix_path.parent)
    report = _base_report(
        include_exploratory=include_exploratory,
        observed_image=observed_container_image,
        execution_adapter=execution_adapter,
        timeout=timeout,
    )
    try:
        matrix = check_idf_matrix.load_matrix(matrix_path)
        errors = check_idf_matrix.validate_matrix(matrix, matrix_path)
        if errors:
            _fail(report, "matrix", "invalid matrix: " + "; ".join(errors))
            _write_reports(prepared, report)
            return report
        lock_errors, _lock_evidence = check_idf_matrix.validate_locks(matrix, matrix_path)
        if lock_errors:
            _fail(report, "dependency-locks", "invalid matrix locks: " + "; ".join(lock_errors))
            _write_reports(prepared, report)
            return report
        lane_id = matrix["realizations"][REFERENCE_CELL]["lane"]
        lane = matrix["lanes"][lane_id]
        report["lane"] = {"id": lane_id, **lane}
        for kind in ("deferred", "excluded"):
            report["inventory"][kind] = [
                {**item, "status": POLICY_STATUS} for item in matrix[kind]
            ]
        if observed_container_image != lane["container_image"]:
            _fail(report, "container-identity", "observed image must equal the matrix-pinned digest")
            _write_reports(prepared, report)
            return report

        reference_dir = prepared / "reference"
        try:
            reference = reference_qualifier(
                matrix_path=matrix_path,
                out_dir=reference_dir,
                observed_container_image=observed_container_image,
                execution_adapter=execution_adapter,
                idf_path=idf_path,
                idf_py=idf_py,
                timeout=timeout,
                cell_builder=cell_builder,
            )
            item = _reference_summary(prepared, reference_dir, reference)
            report["cells"].append(item)
            if item["status"] != "PASS" or item["result"] != "BUILD_QUALIFIED":
                _fail(report, REFERENCE_CELL, "required S3 qualification did not pass")
            if not item["evidence_complete"]:
                _fail(report, f"{REFERENCE_CELL}-evidence", item["evidence_detail"])
        except Exception as exc:  # Preserve aggregate evidence and continue requested attempts.
            _fail(report, REFERENCE_CELL, f"reference qualifier raised: {exc}")

        if include_exploratory:
            for cell in EXPLORATORY_CELLS:
                cell_dir = prepared / "exploratory" / cell
                try:
                    cell_report = cell_builder(
                        matrix_path=matrix_path,
                        cell_id=cell,
                        out_dir=cell_dir,
                        idf_path=idf_path,
                        idf_py=idf_py,
                        timeout=timeout,
                    )
                    report_path = cell_dir / "cell-report.json"
                    item = _summary(
                        cell=cell,
                        intent="exploratory",
                        report_path=report_path,
                        root=prepared,
                        report=cell_report,
                    )
                    report["cells"].append(item)
                    if item["result"] not in ACCEPTABLE_EXPLORATORY_RESULTS:
                        _fail(report, cell, f"exploratory result {item['result']!r} is not acceptable")
                    if not item["evidence_complete"]:
                        _fail(report, f"{cell}-evidence", item["evidence_detail"])
                except Exception as exc:  # Continue so every requested attempt is observable.
                    _fail(report, cell, f"cell builder raised: {exc}")

        expected = 1 + (len(EXPLORATORY_CELLS) if include_exploratory else 0)
        actual_ids = [item["id"] for item in report["cells"]]
        expected_ids = [REFERENCE_CELL, *(EXPLORATORY_CELLS if include_exploratory else ())]
        if len(actual_ids) != expected or actual_ids != expected_ids:
            _fail(report, "attempt-completeness", "requested cells were not all recorded in canonical order")

        source_values = [item["source_tree_sha256"] for item in report["cells"]]
        source_hashes = {value for value in source_values if value}
        if len(source_hashes) != 1 or any(value is None for value in source_values):
            _fail(report, "source-reproducibility", "attempted cells do not share one observed source-tree hash")
        else:
            report["source_tree_sha256"] = next(iter(source_hashes))

        counts: dict[str, int] = {}
        for item in report["cells"]:
            result = str(item["result"])
            counts[result] = counts.get(result, 0) + 1
        report["result_counts"] = dict(sorted(counts.items()))
        if not report["failed_gates"]:
            report["status"] = "PASS"
    except (OSError, ValueError, check_idf_matrix.MatrixContractError) as exc:
        _fail(report, "orchestration", str(exc))
    except Exception as exc:  # Always preserve a normalized aggregate report.
        _fail(report, "orchestration", str(exc))
    _write_reports(prepared, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--include-exploratory", action="store_true")
    parser.add_argument(
        "--observed-container-image", default=os.environ.get("PULSE_IDF_CONTAINER_IMAGE")
    )
    parser.add_argument(
        "--execution-adapter", default=os.environ.get("PULSE_IDF_EXECUTION_ADAPTER", "none")
    )
    parser.add_argument("--idf-path", type=Path)
    parser.add_argument("--idf-py", type=Path)
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args(argv)
    if args.timeout < 1:
        print("ERROR: --timeout must be positive", file=sys.stderr)
        return 2
    try:
        report = qualify_matrix(
            matrix_path=args.matrix,
            out_dir=args.out_dir,
            observed_container_image=args.observed_container_image,
            include_exploratory=args.include_exploratory,
            execution_adapter=args.execution_adapter,
            idf_path=args.idf_path,
            idf_py=args.idf_py,
            timeout=args.timeout,
        )
    except MatrixQualificationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
