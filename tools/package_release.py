#!/usr/bin/env python3
"""Create deterministic source and evidence packages without boundary bleed."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
SOURCE_ARCHIVE_ROOT = "pulse-esp32-host-main"
HOST_EVIDENCE_ARCHIVE_ROOT = "pulse-esp32-host-evidence"
HARDWARE_EVIDENCE_ARCHIVE_ROOT = "pulse-esp32-host-hardware-evidence"
SOURCE_PACKAGE_MAX_BYTES = 2 * 1024 * 1024
SOURCE_ENTRIES = (
    ".github",
    ".gitignore",
    "CHANGELOG.md",
    "Makefile",
    "README.md",
    "docs",
    "evidence",
    "examples",
    "firmware",
    "guest-sdk",
    "native-extensions",
    "native-sdk",
    "reports/.gitkeep",
    "reports/README.md",
    "reports/logs/.gitkeep",
    "schemas",
    "specs",
    "tests",
    "tools",
)
IGNORED_PARTS = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    "build",
    "dist",
    "managed_components",
    "target",
}
IGNORED_NAMES = {".DS_Store", "sdkconfig", "sdkconfig.old"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}
SOURCE_IGNORED_EXCEPTIONS = {
    "examples/bundles/relay-controller/dist/relay-controller-r6.wdcb",
    "examples/bundles/relay-controller/dist/relay-controller-r8.wdcb",
}
GENERATED_SUFFIXES = {".a", ".aot", ".bin", ".elf", ".map", ".o", ".wasm"}
FIXTURE_PREFIXES = (
    "firmware/components/wdc_runtime/test_vectors/",
    "tests/contract/native_extension_vectors/",
    "tests/hardware-in-loop/hx45-s3-aitrip-n8r2/fixtures/",
    "tests/hardware-in-loop/hx45-c6-seeed-xiao-4m/fixtures/",
)


class PackageError(RuntimeError):
    """Raised when a package would cross an evidence or source boundary."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_ignored(relative: Path) -> bool:
    if relative.as_posix() in SOURCE_IGNORED_EXCEPTIONS:
        return False
    return (
        any(part in IGNORED_PARTS for part in relative.parts)
        or relative.name in IGNORED_NAMES
        or relative.suffix in IGNORED_SUFFIXES
    )


def is_evidence_ignored(relative: Path) -> bool:
    return (
        ".git" in relative.parts
        or "__pycache__" in relative.parts
        or relative.name == ".DS_Store"
        or relative.suffix in IGNORED_SUFFIXES
    )


def validate_source_artifact(relative: Path) -> None:
    if relative.suffix not in GENERATED_SUFFIXES:
        return
    logical = relative.as_posix()
    if any(logical.startswith(prefix) for prefix in FIXTURE_PREFIXES):
        return
    raise PackageError(f"generated artifact is not admitted to source: {logical}")


def collect_source_files(repo: Path = ROOT) -> list[tuple[Path, Path]]:
    collected: list[tuple[Path, Path]] = []
    for entry_name in SOURCE_ENTRIES:
        entry = repo / entry_name
        if not entry.exists():
            raise PackageError(f"required source entry is missing: {entry_name}")
        candidates = [entry] if entry.is_file() else sorted(entry.rglob("*"))
        for path in candidates:
            if path.is_symlink():
                raise PackageError(
                    f"source package does not admit symlinks: {path.relative_to(repo)}"
                )
            if not path.is_file():
                continue
            relative = path.relative_to(repo)
            if is_ignored(relative):
                continue
            validate_source_artifact(relative)
            collected.append((path, relative))
    return sorted(collected, key=lambda item: item[1].as_posix())


def manifest_for(
    *,
    kind: str,
    archive_root: str,
    files: Iterable[tuple[Path, Path]],
) -> dict[str, Any]:
    entries = []
    payload_bytes = 0
    for source, relative in files:
        size = source.stat().st_size
        payload_bytes += size
        entries.append(
            {
                "path": relative.as_posix(),
                "sha256": sha256_file(source),
                "size": size,
            }
        )
    return {
        "archive_root": archive_root,
        "file_count": len(entries),
        "files": entries,
        "fixed_zip_timestamp": "1980-01-01T00:00:00",
        "kind": kind,
        "payload_bytes": payload_bytes,
        "schema": "pulse.esp32.release-package-manifest.v1",
    }


def normalized_file_mode(path: Path) -> int:
    """Return a stable regular-file mode while retaining executable intent."""
    return 0o100755 if path.stat().st_mode & 0o111 else 0o100644


def zip_info(name: str, mode: int = 0o100644) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (mode & 0xFFFF) << 16
    return info


def write_package(
    *,
    output: Path,
    archive_root: str,
    files: list[tuple[Path, Path]],
    kind: str,
    manifest_name: str,
    maximum_bytes: int | None = None,
) -> dict[str, Any]:
    output = output.expanduser().resolve()
    if output.exists():
        raise PackageError("output file must not already exist")
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = manifest_for(kind=kind, archive_root=archive_root, files=files)
    manifest_bytes = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    try:
        with zipfile.ZipFile(
            output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as archive:
            for source, relative in files:
                archive.writestr(
                    zip_info(
                        f"{archive_root}/{relative.as_posix()}",
                        normalized_file_mode(source),
                    ),
                    source.read_bytes(),
                    compresslevel=9,
                )
            archive.writestr(
                zip_info(f"{archive_root}/{manifest_name}"),
                manifest_bytes,
                compresslevel=9,
            )
        size = output.stat().st_size
        if maximum_bytes is not None and size > maximum_bytes:
            raise PackageError(
                f"package is {size} bytes, above the {maximum_bytes}-byte boundary"
            )
    except Exception:
        if output.exists():
            output.unlink()
        raise
    return {
        "file_count": manifest["file_count"],
        "kind": kind,
        "output": str(output),
        "sha256": sha256_file(output),
        "size": output.stat().st_size,
        "status": "PASS",
    }


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PackageError(f"JSON root is not an object: {path}")
    return value


def collect_host_evidence_files(
    *, repo: Path = ROOT, report_root: Path | None = None
) -> list[tuple[Path, Path]]:
    index_path = repo / "evidence/host-extension/index.json"
    index = load_json(index_path)
    if index.get("schema") != "pulse.esp32.host-extension-evidence-index.v1":
        raise PackageError("host evidence index schema is unsupported")
    runs = index.get("accepted_runs")
    if not isinstance(runs, list) or not runs:
        raise PackageError("host evidence index contains no accepted runs")
    reports = (report_root or repo / "reports/host-extension").resolve()
    collected: list[tuple[Path, Path]] = [
        (index_path, Path("host-extension/index.json")),
        (
            repo / "evidence/host-extension/INDEX.md",
            Path("host-extension/INDEX.md"),
        ),
    ]
    for run in runs:
        if not isinstance(run, dict) or run.get("status") != "PASS":
            raise PackageError("host evidence index contains a non-passing run")
        run_id = run.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise PackageError("host evidence index contains an invalid run id")
        directory = reports / run_id
        if not directory.is_dir():
            raise PackageError(f"accepted host evidence is missing: {run_id}")
        report_json = directory / "qualification-report.json"
        report_markdown = directory / "qualification-report.md"
        expected = (
            (report_json, run.get("qualification_report_json_sha256")),
            (
                report_markdown,
                run.get("qualification_report_markdown_sha256"),
            ),
        )
        for path, digest in expected:
            if not path.is_file() or sha256_file(path) != digest:
                raise PackageError(f"accepted report hash mismatch: {path}")
        for path in sorted(directory.rglob("*")):
            if path.is_symlink():
                raise PackageError(f"host evidence contains a symlink: {path}")
            if path.is_file() and not is_evidence_ignored(
                path.relative_to(directory)
            ):
                relative = Path("host-extension") / run_id / path.relative_to(
                    directory
                )
                collected.append((path, relative))
    return sorted(collected, key=lambda item: item[1].as_posix())


def collect_hardware_evidence_files(run_dir: Path) -> list[tuple[Path, Path]]:
    run = run_dir.expanduser().resolve()
    build_report = run / "build-report.json"
    serial_log = run / "serial.log"
    evaluation_json = run / "evaluation/qualification-report.json"
    evaluation_markdown = run / "evaluation/qualification-report.md"
    for required in (
        build_report,
        serial_log,
        evaluation_json,
        evaluation_markdown,
    ):
        if not required.is_file():
            raise PackageError(f"hardware evidence is incomplete: {required}")
    evaluation = load_json(evaluation_json)
    if (
        evaluation.get("status") != "PASS"
        or evaluation.get("runtime_result") != "NAMED_BOARD_OBSERVED"
    ):
        raise PackageError("hardware run is not a passing named-board evaluation")
    collected = []
    for path in sorted(run.rglob("*")):
        if path.is_symlink():
            raise PackageError(f"hardware evidence contains a symlink: {path}")
        if path.is_file() and not is_evidence_ignored(path.relative_to(run)):
            collected.append((path, path.relative_to(run)))
    return collected


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    source = subparsers.add_parser("source")
    source.add_argument("--out", type=Path, required=True)
    host = subparsers.add_parser("host-evidence")
    host.add_argument("--out", type=Path, required=True)
    host.add_argument("--report-root", type=Path)
    hardware = subparsers.add_parser("hardware-evidence")
    hardware.add_argument("--out", type=Path, required=True)
    hardware.add_argument("--run-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "source":
            result = write_package(
                output=args.out,
                archive_root=SOURCE_ARCHIVE_ROOT,
                files=collect_source_files(),
                kind="SOURCE",
                manifest_name="PACKAGE-MANIFEST.json",
                maximum_bytes=SOURCE_PACKAGE_MAX_BYTES,
            )
        elif args.command == "host-evidence":
            result = write_package(
                output=args.out,
                archive_root=HOST_EVIDENCE_ARCHIVE_ROOT,
                files=collect_host_evidence_files(report_root=args.report_root),
                kind="HOST_QUALIFICATION_EVIDENCE",
                manifest_name="EVIDENCE-MANIFEST.json",
            )
        else:
            result = write_package(
                output=args.out,
                archive_root=HARDWARE_EVIDENCE_ARCHIVE_ROOT,
                files=collect_hardware_evidence_files(args.run_dir),
                kind="HARDWARE_QUALIFICATION_EVIDENCE",
                manifest_name="EVIDENCE-MANIFEST.json",
            )
    except (OSError, ValueError, json.JSONDecodeError, PackageError) as exc:
        print(f"release packaging failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
