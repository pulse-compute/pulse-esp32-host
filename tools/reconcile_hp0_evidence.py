#!/usr/bin/env python3
"""Verify and package the exact HP0 HX5b hardware evidence boundary."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INDEX = ROOT / "evidence/hardware/index.json"
ARCHIVE_ROOT = "pulse-esp32-host-hx5b-hardware-evidence"
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
IGNORED_PARTS = {".git", "__pycache__"}
IGNORED_NAMES = {".DS_Store"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}


class ReconciliationError(RuntimeError):
    """Raised when retained evidence is missing, stale, or ambiguous."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReconciliationError(f"cannot read JSON authority {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReconciliationError(f"JSON authority is not an object: {path}")
    return value


def verify_file(path: Path, *, digest: str, size: int | None = None) -> None:
    if not path.is_file():
        raise ReconciliationError(f"required evidence file is missing: {path}")
    observed_size = path.stat().st_size
    if size is not None and observed_size != size:
        raise ReconciliationError(
            f"evidence size mismatch for {path}: {observed_size} != {size}"
        )
    observed_digest = sha256_file(path)
    if observed_digest != digest:
        raise ReconciliationError(
            f"evidence hash mismatch for {path}: {observed_digest} != {digest}"
        )


def load_index(path: Path) -> dict[str, Any]:
    index = load_json(path)
    if (
        index.get("schema") != "pulse.esp32.hp0-hardware-evidence-index.v1"
        or index.get("status") != "PASS"
        or index.get("terminal_result") != "DUAL_ISA_PRESSURE_OBSERVED"
        or index.get("hp0", {}).get("pass") != "HP0"
        or index.get("hp0", {}).get("status") != "PASS"
    ):
        raise ReconciliationError("HP0 evidence index identity or result drifted")
    runs = index.get("accepted_runs")
    if not isinstance(runs, dict) or set(runs) != {"esp32s3", "esp32c6"}:
        raise ReconciliationError("HP0 evidence index must name exactly S3 and C6")
    return index


def _zip_file_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = []
    for info in archive.infolist():
        logical = PurePosixPath(info.filename)
        if info.is_dir():
            continue
        if logical.is_absolute() or ".." in logical.parts:
            raise ReconciliationError(f"source archive contains unsafe path: {logical}")
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise ReconciliationError(f"source archive contains a symlink: {logical}")
        members.append(info)
    return members


def _zip_sha256(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> str:
    digest = hashlib.sha256()
    with archive.open(info, "r") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_snapshot_evidence(path: Path) -> dict[str, Any]:
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ReconciliationError(f"source snapshot is not a readable ZIP: {exc}") from exc
    with archive:
        members = _zip_file_members(archive)
        roots = {PurePosixPath(info.filename).parts[0] for info in members}
        if roots != {"pulse-esp32-host-main"}:
            raise ReconciliationError("source snapshot has an unexpected archive root")

        source_digest = hashlib.sha256()
        source_count = 0
        tree_digests = {
            "firmware": hashlib.sha256(),
            "native_sdk": hashlib.sha256(),
        }
        tree_counts = {"firmware": 0, "native_sdk": 0}
        pressure_model_sha256 = None

        # The qualification tree digest sorts Path objects component by
        # component. String ordering differs when one path is a prefix of
        # another (for example, ``firmware/main`` versus
        # ``firmware/CMakeLists.txt``), so preserve the exact Path semantics.
        for info in sorted(
            members,
            key=lambda item: PurePosixPath(*PurePosixPath(item.filename).parts[1:]),
        ):
            logical = PurePosixPath(info.filename)
            relative = PurePosixPath(*logical.parts[1:])
            data = archive.read(info)
            if not any(part in {"reports", "__pycache__"} for part in relative.parts):
                encoded = relative.as_posix().encode("utf-8")
                source_digest.update(len(encoded).to_bytes(4, "big"))
                source_digest.update(encoded)
                source_digest.update(len(data).to_bytes(8, "big"))
                source_digest.update(data)
                source_count += 1

            if relative.as_posix() == "specs/PULSE-ESP32-005b-extension-pressure-seal.json":
                pressure_model_sha256 = sha256_bytes(data)

            for key, prefix, ignored in (
                (
                    "firmware",
                    PurePosixPath("firmware"),
                    {"build", "managed_components", "dependencies.lock", "sdkconfig", "__pycache__"},
                ),
                ("native_sdk", PurePosixPath("native-sdk"), {"__pycache__"}),
            ):
                if not relative.parts or relative.parts[0] != prefix.parts[0]:
                    continue
                tree_relative = PurePosixPath(*relative.parts[1:])
                if any(part in ignored for part in tree_relative.parts):
                    continue
                tree_digests[key].update(tree_relative.as_posix().encode("utf-8"))
                tree_digests[key].update(b"\0")
                tree_digests[key].update(sha256_bytes(data).encode("ascii"))
                tree_digests[key].update(b"\n")
                tree_counts[key] += 1

        if pressure_model_sha256 is None:
            raise ReconciliationError("source snapshot omits the HX5b pressure model")
        return {
            "source_tree": {
                "sha256": source_digest.hexdigest(),
                "file_count": source_count,
            },
            "sealed_sources": {
                key: {
                    "sha256": tree_digests[key].hexdigest(),
                    "file_count": tree_counts[key],
                }
                for key in ("firmware", "native_sdk")
            },
            "pressure_model_sha256": pressure_model_sha256,
        }


def _is_ignored(relative: Path) -> bool:
    return (
        any(part in IGNORED_PARTS for part in relative.parts)
        or relative.name in IGNORED_NAMES
        or relative.suffix in IGNORED_SUFFIXES
    )


def _is_beneath(path: PurePosixPath, prefix: PurePosixPath) -> bool:
    return path == prefix or prefix in path.parents


def collect_run_files(
    *,
    reports_root: Path,
    s3_run: Path,
    c6_run: Path,
    dual_run: Path,
    index: dict[str, Any],
) -> list[tuple[Path, PurePosixPath]]:
    roots = (
        (s3_run, PurePosixPath("hardware/esp32s3") / s3_run.name),
        (c6_run, PurePosixPath("hardware/esp32c6") / c6_run.name),
        (dual_run, PurePosixPath("host-extension") / dual_run.name),
    )
    exclusions = {
        PurePosixPath(item["path"])
        for item in index["hp0"].get("excluded_input_paths", [])
    }
    collected: list[tuple[Path, PurePosixPath]] = []
    for run, archive_prefix in roots:
        if not run.is_dir():
            raise ReconciliationError(f"retained run directory is missing: {run}")
        for path in sorted(run.rglob("*")):
            relative = path.relative_to(run)
            input_logical = PurePosixPath(
                (reports_root / run.relative_to(reports_root) / relative)
                .relative_to(reports_root)
                .as_posix()
            )
            if any(_is_beneath(input_logical, prefix) for prefix in exclusions):
                continue
            if path.is_symlink():
                raise ReconciliationError(f"retained evidence contains a symlink: {path}")
            if path.is_file() and not _is_ignored(relative):
                collected.append((path, archive_prefix / PurePosixPath(relative.as_posix())))
    return sorted(collected, key=lambda item: item[1].as_posix())


def _resolve_recorded_path(
    *,
    value: str,
    digest: str,
    context: Path,
    repo: Path,
    run_roots: dict[str, Path],
) -> Path:
    raw = Path(value)
    candidates: list[Path] = []
    for run_id, run_root in run_roots.items():
        if run_id in raw.parts:
            position = raw.parts.index(run_id)
            candidates.append(run_root.joinpath(*raw.parts[position + 1 :]))
    if not raw.is_absolute():
        candidates.extend([context / raw, run_roots["dual"] / raw, repo / raw])

    unique: list[Path] = []
    seen = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        unique.append(resolved)
    matching = [candidate for candidate in unique if sha256_file(candidate) == digest]
    if len(matching) != 1:
        raise ReconciliationError(
            f"artifact path is missing, stale, or ambiguous: {value}"
        )
    return matching[0]


def _walk_artifacts(
    value: Any,
    *,
    label: str,
    context: Path,
    repo: Path,
    run_roots: dict[str, Path],
) -> int:
    verified = 0
    if isinstance(value, dict):
        path_value = value.get("path")
        digest_value = value.get("sha256")
        if (
            isinstance(path_value, str)
            and isinstance(digest_value, str)
            and len(digest_value) == 64
        ):
            target = _resolve_recorded_path(
                value=path_value,
                digest=digest_value,
                context=context,
                repo=repo,
                run_roots=run_roots,
            )
            size = value.get("size")
            if size is not None and size != target.stat().st_size:
                raise ReconciliationError(
                    f"embedded size mismatch at {label}: {size} != {target.stat().st_size}"
                )
            verified += 1
        for key, child in value.items():
            verified += _walk_artifacts(
                child,
                label=f"{label}.{key}",
                context=context,
                repo=repo,
                run_roots=run_roots,
            )
    elif isinstance(value, list):
        for position, child in enumerate(value):
            verified += _walk_artifacts(
                child,
                label=f"{label}[{position}]",
                context=context,
                repo=repo,
                run_roots=run_roots,
            )
    return verified


def verify_board_run(
    *,
    target: str,
    run: Path,
    accepted: dict[str, Any],
    source: dict[str, Any],
) -> dict[str, Any]:
    if run.name != accepted.get("run_id"):
        raise ReconciliationError(f"{target} run identity does not match the index")
    build_path = run / "build-report.json"
    serial_path = run / "serial.log"
    evaluation_path = run / "evaluation/qualification-report.json"
    evaluation_markdown = run / "evaluation/qualification-report.md"
    verify_file(build_path, digest=accepted["build_report_sha256"])
    verify_file(serial_path, digest=accepted["serial_log_sha256"])
    verify_file(evaluation_path, digest=accepted["evaluation_report_json_sha256"])
    verify_file(
        evaluation_markdown,
        digest=accepted["evaluation_report_markdown_sha256"],
    )
    build = load_json(build_path)
    evaluation = load_json(evaluation_path)
    expected_schema = {
        "esp32s3": "pulse.esp32.hx45-s3-aitrip-hardware-report.v1",
        "esp32c6": "pulse.esp32.hx45-c6-xiao-hardware-report.v1",
    }[target]
    if (
        build.get("status") != "PASS"
        or build.get("campaign") != "HX5b"
        or build.get("board", {}).get("target") != target
        or build.get("pressure_contract", {}).get("status") != "BUILD_CONFIGURED"
        or build.get("sealed_sources") != source["sealed_sources"]
    ):
        raise ReconciliationError(f"{target} build report is not the sealed HX5b build")
    observations = evaluation.get("observations", {})
    pressure = evaluation.get("pressure_seal", {})
    if (
        evaluation.get("schema") != expected_schema
        or evaluation.get("status") != "PASS"
        or evaluation.get("runtime_result") != "NAMED_BOARD_OBSERVED"
        or evaluation.get("board", {}).get("target") != target
        or pressure.get("campaign") != "HX5b"
        or pressure.get("required") is not True
        or pressure.get("status") != "PASS"
        or len(observations.get("measured_clean_cycles", [])) != 5
        or observations.get("fatal_serial_signatures") != []
    ):
        raise ReconciliationError(f"{target} evaluation is not passing HX5b evidence")
    wasm_path = run / build["common_wasm"]["path"]
    native_path = run / build["native_extension"]["elf"]["path"]
    if (
        sha256_file(wasm_path) != evaluation.get("artifacts", {}).get("common_wasm_sha256")
        or sha256_file(native_path)
        != evaluation.get("artifacts", {}).get("native_extension_sha256")
        or sha256_file(native_path) != accepted.get("native_extension_sha256")
    ):
        raise ReconciliationError(f"{target} Wasm or native ELF identity drifted")
    return {"build": build, "evaluation": evaluation}


def verify_dual_run(
    *,
    run: Path,
    accepted: dict[str, Any],
    source: dict[str, Any],
    boards: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if run.name != accepted.get("run_id"):
        raise ReconciliationError("dual run identity does not match the index")
    report_path = run / "qualification-report.json"
    markdown_path = run / "qualification-report.md"
    verify_file(report_path, digest=accepted["qualification_report_json_sha256"])
    verify_file(markdown_path, digest=accepted["qualification_report_markdown_sha256"])
    report = load_json(report_path)
    if (
        report.get("schema") != "pulse.esp32.host-extension-report.v1"
        or report.get("pass") != "HX5b"
        or report.get("status") != "PASS"
        or report.get("aggregate") != "DUAL_ISA_PRESSURE_OBSERVED"
        or report.get("hardware", {}).get("execution_this_pass")
        != "DUAL_NAMED_BOARD_OBSERVED"
        or report.get("source_tree") != source["source_tree"]
        or report.get("model", {}).get("sha256") != source["pressure_model_sha256"]
    ):
        raise ReconciliationError("dual HX5b qualifier is not source-bound and passing")
    for target in ("esp32s3", "esp32c6"):
        embedded = report["hardware"]["results"][target]
        board = boards[target]
        if (
            embedded.get("status") != "PASS"
            or embedded.get("runtime_result") != "NAMED_BOARD_OBSERVED"
            or embedded.get("artifact", {}).get("sha256")
            != sha256_file(
                Path(board["evaluation_path"])
            )
            or embedded.get("raw_artifacts", {}).get("build_report", {}).get("sha256")
            != sha256_file(Path(board["build_path"]))
            or embedded.get("raw_artifacts", {}).get("serial_log", {}).get("sha256")
            != sha256_file(Path(board["serial_path"]))
        ):
            raise ReconciliationError(f"dual qualifier does not bind the accepted {target} run")
    return report


def verify_archive_members(
    *,
    archive_path: Path,
    reports_root: Path,
    files: Iterable[tuple[Path, PurePosixPath]],
) -> int:
    try:
        archive = zipfile.ZipFile(archive_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ReconciliationError(f"input evidence archive is unreadable: {exc}") from exc
    count = 0
    with archive:
        member_map = {info.filename: info for info in _zip_file_members(archive)}
        for source, _ in files:
            try:
                relative = source.relative_to(reports_root).as_posix()
            except ValueError:
                continue
            member_name = f"reports/{relative}"
            info = member_map.get(member_name)
            if info is None or info.file_size != source.stat().st_size:
                raise ReconciliationError(
                    f"accepted evidence is not present in reports.zip: {relative}"
                )
            if _zip_sha256(archive, info) != sha256_file(source):
                raise ReconciliationError(
                    f"accepted evidence differs from reports.zip: {relative}"
                )
            count += 1
    return count


def zip_info(name: str, mode: int = 0o100644) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (mode & 0xFFFF) << 16
    return info


def _normalized_mode(path: Path) -> int:
    return 0o100755 if path.stat().st_mode & 0o111 else 0o100644


def _manifest_entry(path: PurePosixPath, source: Path | bytes) -> dict[str, Any]:
    if isinstance(source, bytes):
        digest = sha256_bytes(source)
        size = len(source)
    else:
        digest = sha256_file(source)
        size = source.stat().st_size
    return {"path": path.as_posix(), "sha256": digest, "size": size}


def write_evidence_package(
    *,
    output: Path,
    files: list[tuple[Path | bytes, PurePosixPath]],
    reconciliation: dict[str, Any],
    exclusions: list[dict[str, str]],
) -> dict[str, Any]:
    resolved = output.expanduser().resolve()
    if resolved.exists():
        raise ReconciliationError("output evidence package must not already exist")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    receipt_bytes = (
        json.dumps(reconciliation, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    payload = list(files)
    payload.append((receipt_bytes, PurePosixPath("HP0-RECONCILIATION.json")))
    payload.sort(key=lambda item: item[1].as_posix())
    entries = [_manifest_entry(path, source) for source, path in payload]
    manifest = {
        "archive_root": ARCHIVE_ROOT,
        "excluded_input_paths": exclusions,
        "file_count": len(entries),
        "files": entries,
        "fixed_zip_timestamp": "1980-01-01T00:00:00",
        "kind": "HX5B_DUAL_HARDWARE_QUALIFICATION_EVIDENCE",
        "schema": "pulse.esp32.hp0-evidence-manifest.v1",
        "terminal_result": "DUAL_ISA_PRESSURE_OBSERVED",
    }
    manifest_bytes = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    try:
        with zipfile.ZipFile(
            resolved, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as archive:
            for source, logical in payload:
                name = f"{ARCHIVE_ROOT}/{logical.as_posix()}"
                if isinstance(source, bytes):
                    archive.writestr(zip_info(name), source, compresslevel=9)
                    continue
                info = zip_info(name, _normalized_mode(source))
                with source.open("rb") as source_handle, archive.open(info, "w") as output_handle:
                    shutil.copyfileobj(source_handle, output_handle, 1024 * 1024)
            archive.writestr(
                zip_info(f"{ARCHIVE_ROOT}/EVIDENCE-MANIFEST.json"),
                manifest_bytes,
                compresslevel=9,
            )
    except Exception:
        if resolved.exists():
            resolved.unlink()
        raise
    return {
        "file_count": len(entries),
        "output": str(resolved),
        "sha256": sha256_file(resolved),
        "size": resolved.stat().st_size,
        "status": "PASS",
        "terminal_result": "DUAL_ISA_PRESSURE_OBSERVED",
    }


def reconcile(
    *,
    index_path: Path,
    source_snapshot: Path,
    handoff: Path,
    input_archive: Path,
    s3_run: Path,
    c6_run: Path,
    dual_run: Path,
    output: Path,
) -> dict[str, Any]:
    index = load_index(index_path)
    source_record = index["source_authority"]
    handoff_record = index["handoff_authority"]
    input_record = index["input_evidence_archive"]
    verify_file(
        source_snapshot,
        digest=source_record["sha256"],
        size=source_record["size"],
    )
    verify_file(handoff, digest=handoff_record["sha256"], size=handoff_record["size"])
    verify_file(
        input_archive,
        digest=input_record["sha256"],
        size=input_record["size"],
    )
    source = source_snapshot_evidence(source_snapshot)
    if (
        source["source_tree"]["sha256"] != source_record["source_tree_sha256"]
        or source["source_tree"]["file_count"] != source_record["file_count"]
        or source["pressure_model_sha256"] != index["pressure_model"]["sha256"]
    ):
        raise ReconciliationError("v17 source snapshot contents do not match the HP0 index")

    reports_root = s3_run.resolve().parents[1]
    if (
        c6_run.resolve().parents[1] != reports_root
        or dual_run.resolve().parents[1] != reports_root
    ):
        raise ReconciliationError("S3, C6, and dual runs must share one reports root")
    board_results = {}
    for target, run in (("esp32s3", s3_run.resolve()), ("esp32c6", c6_run.resolve())):
        result = verify_board_run(
            target=target,
            run=run,
            accepted=index["accepted_runs"][target],
            source=source,
        )
        result.update(
            {
                "build_path": str(run / "build-report.json"),
                "serial_path": str(run / "serial.log"),
                "evaluation_path": str(run / "evaluation/qualification-report.json"),
            }
        )
        board_results[target] = result
    dual_report = verify_dual_run(
        run=dual_run.resolve(),
        accepted=index["dual_qualifier"],
        source=source,
        boards=board_results,
    )

    run_roots = {
        index["accepted_runs"]["esp32s3"]["run_id"]: s3_run.resolve(),
        index["accepted_runs"]["esp32c6"]["run_id"]: c6_run.resolve(),
        index["dual_qualifier"]["run_id"]: dual_run.resolve(),
        "dual": dual_run.resolve(),
    }
    documents: list[tuple[Path, Path]] = []
    for run in (s3_run.resolve(), c6_run.resolve()):
        documents.extend(
            [
                (run / "build-report.json", run),
                (run / "native-extension/build-report.json", run / "native-extension"),
                (run / "native-extension/inspection.json", run / "native-extension"),
                (run / "evaluation/qualification-report.json", run),
            ]
        )
    documents.extend((path, path.parent) for path in sorted(dual_run.rglob("*.json")))
    verified_records = 0
    for document, context in documents:
        verified_records += _walk_artifacts(
            load_json(document),
            label=str(document.relative_to(reports_root)),
            context=context,
            repo=ROOT,
            run_roots=run_roots,
        )
    if len(documents) != 20 or verified_records != 89:
        raise ReconciliationError(
            f"evidence inventory drifted: {len(documents)} JSON documents and "
            f"{verified_records} path/hash records"
        )

    accepted_files = collect_run_files(
        reports_root=reports_root,
        s3_run=s3_run.resolve(),
        c6_run=c6_run.resolve(),
        dual_run=dual_run.resolve(),
        index=index,
    )
    archive_member_count = verify_archive_members(
        archive_path=input_archive,
        reports_root=reports_root,
        files=accepted_files,
    )
    source_records = [
        (index_path.resolve(), PurePosixPath("source-records/evidence/hardware/index.json")),
        (
            (ROOT / "evidence/hardware/INDEX.md").resolve(),
            PurePosixPath("source-records/evidence/hardware/INDEX.md"),
        ),
        (
            (ROOT / "docs/HP0_EVIDENCE_RECONCILIATION.md").resolve(),
            PurePosixPath("source-records/docs/HP0_EVIDENCE_RECONCILIATION.md"),
        ),
    ]
    reconciliation = {
        "aggregate": dual_report["aggregate"],
        "hardware_result": dual_report["hardware"]["execution_this_pass"],
        "input_evidence_archive": input_record,
        "json_documents_checked": len(documents),
        "path_hash_records_verified": verified_records,
        "primary_archive_members_verified": archive_member_count,
        "schema": "pulse.esp32.hp0-evidence-reconciliation.v1",
        "source_authority": source_record,
        "status": "PASS",
        "terminal_result": "DUAL_ISA_PRESSURE_OBSERVED",
    }
    package_files: list[tuple[Path | bytes, PurePosixPath]] = [
        (source, logical) for source, logical in accepted_files
    ]
    package_files.extend(source_records)
    return write_evidence_package(
        output=output,
        files=package_files,
        reconciliation=reconciliation,
        exclusions=index["hp0"].get("excluded_input_paths", []),
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--source-snapshot", type=Path, required=True)
    parser.add_argument("--handoff", type=Path, required=True)
    parser.add_argument("--input-archive", type=Path, required=True)
    parser.add_argument("--s3-run", type=Path, required=True)
    parser.add_argument("--c6-run", type=Path, required=True)
    parser.add_argument("--dual-run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = reconcile(
            index_path=args.index,
            source_snapshot=args.source_snapshot,
            handoff=args.handoff,
            input_archive=args.input_archive,
            s3_run=args.s3_run,
            c6_run=args.c6_run,
            dual_run=args.dual_run,
            output=args.out,
        )
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, ReconciliationError) as exc:
        print(f"HP0 evidence reconciliation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
