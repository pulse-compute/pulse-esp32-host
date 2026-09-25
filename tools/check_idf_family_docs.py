#!/usr/bin/env python3
"""Fail-closed IF7 documentation and optional evidence-seal validation."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    from tools import check_idf_matrix
except ModuleNotFoundError:  # Direct execution from tools/.
    import check_idf_matrix  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = ROOT / "firmware/idf-family-matrix.json"
DEFAULT_DOCUMENT = ROOT / "docs/reference/IDF_FAMILY_MATRIX.md"
FIRMWARE_SOURCE_SHA256 = "2e0935fbc0f8fc2013bb09c4f8a5453bc8718a91b3e0b5c3201b997e616c6a9e"
ALLOWED_STATUS = (
    "The S3 reference firmware is reproducibly build-qualified under the pinned "
    "ESP-IDF lane. Additional family targets have explicit compile-probe results."
)
FORBIDDEN_CLAIMS = (
    "esp32 family supported",
    "portable across esp32 hardware",
    "runtime qualified",
    "hardware qualified",
    "production provider",
)
EXPECTED_RESULTS = {
    "esp32s3-reference": "BUILD_QUALIFIED",
    "esp32c3-compile": "INCOMPATIBLE",
    "esp32-compile": "INCOMPATIBLE",
    "esp32c6-compile": "COMPILE_PROVEN",
}
EXPECTED_LOGS = {
    "reference/run-a/build.log",
    "reference/run-b/build.log",
    "exploratory/esp32c3-compile/build.log",
    "exploratory/esp32-compile/build.log",
    "exploratory/esp32c6-compile/build.log",
}
LINK_SOURCES = (
    "README.md",
    "docs/README.md",
    "docs/STATUS.md",
    "docs/BUILD_AND_TEST.md",
    "docs/TESTING.md",
    "docs/CODEBASE_MAP.md",
    "docs/runbooks/LOCAL_BRINGUP.md",
    "docs/runbooks/PRODUCTION_RELEASE_CHECKLIST.md",
    "docs/TROUBLESHOOTING.md",
    "reports/README.md",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def configuration_identity(matrix_path: Path, cell: str) -> str:
    """Hash the declared target/default/partition configuration for one realization."""
    matrix = check_idf_matrix.load_matrix(matrix_path)
    realization = matrix["realizations"][cell]
    firmware = matrix_path.resolve().parent
    value = {
        "target": realization["target"],
        "defaults": [
            {"path": relative, "sha256": _sha256(firmware / relative)}
            for relative in realization["defaults"]
        ],
        "partitions": {
            "path": realization["partitions"],
            "sha256": _sha256(firmware / realization["partitions"]),
        },
    }
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _documentation_files(repo: Path) -> list[Path]:
    files = [repo / "README.md", repo / "reports/README.md"]
    files.extend(sorted((repo / "docs").rglob("*.md")))
    return [path for path in files if path.is_file()]


def validate_static(
    *, repo: Path = ROOT, matrix_path: Path = DEFAULT_MATRIX, document: Path = DEFAULT_DOCUMENT
) -> list[str]:
    errors: list[str] = []
    try:
        matrix = check_idf_matrix.load_matrix(matrix_path)
        errors.extend(check_idf_matrix.validate_matrix(matrix, matrix_path))
        lock_errors, _lock_evidence = check_idf_matrix.validate_locks(matrix, matrix_path)
        errors.extend(lock_errors)
    except (OSError, KeyError, check_idf_matrix.MatrixContractError) as exc:
        return [f"matrix validation failed: {exc}"]

    try:
        text = document.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"canonical matrix document is unreadable: {exc}"]
    normalized = " ".join(text.split())
    if ALLOWED_STATUS not in normalized:
        errors.append("canonical document is missing the exact allowed IF7 status statement")
    if FIRMWARE_SOURCE_SHA256 not in text:
        errors.append("canonical document is missing the sealed firmware source hash")

    lane = matrix["lanes"][check_idf_matrix.CANONICAL_LANE_ID]
    for label, value in {
        "lane": check_idf_matrix.CANONICAL_LANE_ID,
        "IDF version": lane["version"],
        "IDF commit": lane["source_commit"],
        "platform": lane["platform"],
        "container": lane["container_image"],
        "WAMR": lane["wamr_version"],
    }.items():
        if value not in text:
            errors.append(f"canonical document is missing {label} identity {value}")

    for cell, result in EXPECTED_RESULTS.items():
        if cell not in text or result not in text:
            errors.append(f"canonical document is missing observed mapping for {cell}")
        expected_config = configuration_identity(matrix_path, cell)
        if expected_config not in text:
            errors.append(f"canonical document has no matching configuration hash for {cell}")
        realization = matrix["realizations"][cell]
        firmware = matrix_path.resolve().parent
        for label, path in (
            ("partition", firmware / realization["partitions"]),
            ("dependency lock", firmware / realization["dependency_lock"]),
        ):
            value = _sha256(path)
            if value not in text:
                errors.append(f"canonical document has no matching {label} hash for {cell}")

    inventory = [*matrix["realizations"], *(item["id"] for item in matrix["deferred"]), *(item["id"] for item in matrix["excluded"])]
    for entry in inventory:
        if entry not in text:
            errors.append(f"canonical document is missing inventory entry {entry}")
    for log in EXPECTED_LOGS:
        if log not in text:
            errors.append(f"canonical document is missing evidence log path {log}")

    artifact = re.search(r"`(pulse-esp32-host-if\d+-evidence\.zip)`, SHA-256\s+`([0-9a-f]{64})`", text)
    if artifact is None:
        errors.append("canonical document is missing the sealed evidence archive identity")

    for source in LINK_SOURCES:
        path = repo / source
        if not path.is_file():
            errors.append(f"required IF7 documentation source is missing: {source}")
        elif "IDF_FAMILY_MATRIX.md" not in path.read_text(encoding="utf-8"):
            errors.append(f"{source} does not link the canonical IDF family matrix reference")

    for path in _documentation_files(repo):
        lower = path.read_text(encoding="utf-8", errors="replace").lower()
        for claim in FORBIDDEN_CLAIMS:
            if claim in lower:
                errors.append(f"forbidden IF7 claim in {path.relative_to(repo)}: {claim}")
    return errors


def validate_evidence(
    *, document: Path, evidence_root: Path, evidence_archive: Path | None = None
) -> list[str]:
    errors: list[str] = []
    text = document.read_text(encoding="utf-8")
    report_path = evidence_root / "matrix-report.json"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot read aggregate evidence: {exc}"]
    if report.get("status") != "PASS" or report.get("failed_gates") != []:
        errors.append("aggregate evidence is not PASS with zero failed gates")
    if report.get("source_tree_sha256") != FIRMWARE_SOURCE_SHA256:
        errors.append("aggregate evidence does not match the sealed firmware source")
    aggregate_sha = _sha256(report_path)
    if aggregate_sha not in text:
        errors.append("canonical document does not contain the aggregate report hash")

    observed = {item.get("id"): item for item in report.get("cells", []) if isinstance(item, dict)}
    if set(observed) != set(EXPECTED_RESULTS):
        errors.append("aggregate evidence does not contain exactly the four attempted realizations")
    for cell, expected_result in EXPECTED_RESULTS.items():
        item = observed.get(cell, {})
        if item.get("result") != expected_result or item.get("evidence_complete") is not True:
            errors.append(f"aggregate evidence is incomplete or misclassified for {cell}")
            continue
        relative = item.get("report")
        if not isinstance(relative, str):
            errors.append(f"aggregate evidence has no report path for {cell}")
            continue
        cell_report = evidence_root / relative
        if not cell_report.is_file() or _sha256(cell_report) != item.get("report_sha256"):
            errors.append(f"preserved report does not match aggregate evidence for {cell}")
        elif item["report_sha256"] not in text:
            errors.append(f"canonical document does not contain the report hash for {cell}")
    for relative in EXPECTED_LOGS:
        log = evidence_root / relative
        if not log.is_file():
            errors.append(f"evidence log is missing: {relative}")
        elif _sha256(log) not in text:
            errors.append(f"canonical document does not contain the log hash for {relative}")
    if evidence_archive is not None:
        if not evidence_archive.is_file():
            errors.append("sealed evidence archive is missing")
        elif _sha256(evidence_archive) not in text:
            errors.append("canonical document does not contain the evidence archive hash")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--document", type=Path, default=DEFAULT_DOCUMENT)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--evidence-archive", type=Path)
    args = parser.parse_args(argv)
    if args.evidence_archive is not None and args.evidence_root is None:
        print("ERROR: --evidence-archive requires --evidence-root", file=sys.stderr)
        return 2
    errors = validate_static(
        repo=args.repo_root.resolve(),
        matrix_path=args.matrix.resolve(),
        document=args.document.resolve(),
    )
    if args.evidence_root is not None:
        errors.extend(
            validate_evidence(
                document=args.document.resolve(),
                evidence_root=args.evidence_root.resolve(),
                evidence_archive=args.evidence_archive.resolve() if args.evidence_archive else None,
            )
        )
    result: dict[str, Any] = {
        "schema": "pulse.esp32.idf-family-docs-check.v1",
        "status": "PASS" if not errors else "FAIL",
        "static_contract": True,
        "evidence_checked": args.evidence_root is not None,
        "errors": errors,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
