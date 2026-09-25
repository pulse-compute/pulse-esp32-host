#!/usr/bin/env python3
"""Qualify HX2 dual-ISA admission artifacts without making runtime claims."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any

try:
    from tools import build_native_extension, inspect_native_extension
except ModuleNotFoundError:  # Direct execution from tools/.
    import build_native_extension  # type: ignore[no-redef]
    import inspect_native_extension  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[1]
VECTORS = ROOT / "tests" / "contract" / "native_extension_vectors"
SCHEMA = "pulse.esp32.host-extension-report.v1"


class QualificationError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _prepare_output(path: Path) -> Path:
    resolved = path.resolve()
    if resolved.exists():
        if not resolved.is_dir() or any(resolved.iterdir()):
            raise QualificationError("output directory must be absent or empty")
    else:
        resolved.mkdir(parents=True)
    return resolved


def _validate_vectors() -> dict[str, Any]:
    manifest = json.loads((VECTORS / "vectors.json").read_text(encoding="utf-8"))
    valid: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for vector in manifest["valid"]:
        report = inspect_native_extension.inspect_elf(
            VECTORS / vector["file"], vector["expected_target"], require_extension=True
        )
        if report["status"] != "PASS":
            raise QualificationError(f"valid vector failed: {vector['file']}")
        valid.append({"name": vector["file"], "status": "PASS", "sha256": _sha256(VECTORS / vector["file"])})
    for vector in manifest["pre_execution_rejections"]:
        try:
            report = inspect_native_extension.inspect_elf(
                VECTORS / vector["file"], vector["expected_target"], require_extension=True
            )
            errors = report["validation_errors"]
            status = report["status"]
        except inspect_native_extension.ElfInspectionError as exc:
            errors = [str(exc)]
            status = "FAIL"
        if status != "FAIL" or vector["expected_error"] not in " | ".join(errors):
            raise QualificationError(f"negative vector did not fail as expected: {vector['name']}")
        rejected.append(
            {
                "name": vector["name"],
                "stage": "PRE_EXECUTION",
                "status": "REJECTED",
                "lifecycle_calls": 0,
                "errors": errors,
            }
        )

    metadata_report = inspect_native_extension.inspect_elf(
        VECTORS / manifest["descriptor_metadata_file"], "esp32s3", require_extension=True
    )
    metadata = metadata_report["metadata"]
    ranges = {
        "executable_ranges": ((0x1000, 0x100),),
        "readable_ranges": ((0x2000, 0x100),),
        "descriptor_address": 0x2000,
    }
    valid_descriptor = (VECTORS / manifest["valid_descriptor"]).read_bytes()
    if inspect_native_extension.validate_descriptor_bytes(valid_descriptor, metadata, **ranges):
        raise QualificationError("valid descriptor vector failed")
    for vector in manifest["descriptor_rejections"]:
        errors = inspect_native_extension.validate_descriptor_bytes(
            (VECTORS / vector["file"]).read_bytes(), metadata, **ranges
        )
        if vector["expected_error"] not in " | ".join(errors):
            raise QualificationError(f"descriptor vector did not fail: {vector['name']}")
        rejected.append(
            {
                "name": vector["name"],
                "stage": "DESCRIPTOR_PRE_LIFECYCLE",
                "status": "REJECTED",
                "lifecycle_calls": 0,
                "errors": errors,
            }
        )
    registry_errors = inspect_native_extension.validate_registry_catalog(
        [valid_descriptor, valid_descriptor]
    )
    if "duplicate extension identity" not in registry_errors:
        raise QualificationError("duplicate extension registry vector did not fail")
    rejected.append(
        {
            "name": "duplicate-extension-identity",
            "stage": "REGISTRY_PRE_LIFECYCLE",
            "status": "REJECTED",
            "lifecycle_calls": 0,
            "errors": registry_errors,
        }
    )
    return {
        "schema": manifest["schema"],
        "status": "PASS",
        "valid": valid,
        "rejected": rejected,
        "pre_execution_lifecycle_calls": 0,
        "descriptor_rejection_lifecycle_calls": 0,
    }


def qualify(output: Path, compilers: dict[str, Path | None]) -> dict[str, Any]:
    out = _prepare_output(output)
    targets: dict[str, Any] = {}
    for target in ("esp32s3", "esp32c6"):
        target_dir = out / "targets" / target
        run_a = build_native_extension.build_synthetic_extension(
            target=target,
            source=build_native_extension.SYNTHETIC_SOURCE,
            out_dir=target_dir / "run-a",
            compiler=compilers[target],
        )
        run_b = build_native_extension.build_synthetic_extension(
            target=target,
            source=build_native_extension.SYNTHETIC_SOURCE,
            out_dir=target_dir / "run-b",
            compiler=compilers[target],
        )
        if run_a["status"] != "PASS" or run_b["status"] != "PASS":
            raise QualificationError(f"{target} synthetic build failed")
        elf_a = target_dir / "run-a" / run_a["artifacts"]["elf"]["path"]
        elf_b = target_dir / "run-b" / run_b["artifacts"]["elf"]["path"]
        reproducible = elf_a.read_bytes() == elf_b.read_bytes()
        if not reproducible:
            raise QualificationError(f"{target} synthetic ELF is not byte reproducible")
        inspection = json.loads((target_dir / "run-a" / "inspection.json").read_text(encoding="utf-8"))
        targets[target] = {
            "classification": "BUILD_PROVEN",
            "runtime": "HARDWARE_NOT_RUN",
            "lifecycle_execution": "NOT_RUN_NO_TARGET_RUNTIME",
            "reproducible": reproducible,
            "elf": {
                "sha256": _sha256(elf_a),
                "size": elf_a.stat().st_size,
                "machine": inspection["header"]["machine_name"],
                "flags": inspection["header"]["flags"],
                "artifact_sha256": inspection["metadata"]["artifact_sha256"],
                "metadata_sha256": inspection["metadata"]["normalized_metadata_sha256"],
            },
            "imports": [item["name"] for item in inspection["imports"]],
            "relocations": inspection["observed_relocation_types"],
            "constructor_surfaces": inspection["constructor_surfaces"],
            "runs": {"run-a": run_a, "run-b": run_b},
        }

    vector_report = _validate_vectors()
    vector_path = out / "vector-report.json"
    vector_path.write_text(json.dumps(vector_report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    environment = {
        "python": sys.version,
        "platform": platform.platform(),
        "cwd": str(ROOT),
        "LANG": os.environ.get("LANG"),
        "LC_ALL": os.environ.get("LC_ALL"),
        "SOURCE_DATE_EPOCH": os.environ.get("SOURCE_DATE_EPOCH"),
    }
    (out / "environment.json").write_text(
        json.dumps(environment, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report = {
        "schema": SCHEMA,
        "pass": "HX2",
        "status": "PASS",
        "aggregate": "BUILD_ONLY_PROVEN",
        "scope": "TWO_STAGE_ADMISSION_AND_SYNTHETIC_ELF",
        "targets": targets,
        "vectors": {
            "status": vector_report["status"],
            "report": "vector-report.json",
            "sha256": _sha256(vector_path),
            "rejected_count": len(vector_report["rejected"]),
            "lifecycle_calls": 0,
        },
        "runtime": {
            "status": "HARDWARE_NOT_RUN",
            "descriptor_entry": "NOT_RUN_NO_TARGET_RUNTIME",
            "init": "NOT_RUN",
            "start": "NOT_RUN",
            "invoke": "NOT_RUN",
            "health": "NOT_RUN",
            "quiesce": "NOT_RUN",
            "deinit": "NOT_RUN",
        },
    }
    report_path = out / "qualification-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown = [
        "# HX2 extension admission qualification",
        "",
        "- Status: `PASS`",
        "- Aggregate: `BUILD_ONLY_PROVEN`",
        "- Runtime: `HARDWARE_NOT_RUN`",
        f"- Rejected golden vectors: `{len(vector_report['rejected'])}` with `0` lifecycle calls",
        "",
        "| Target | Classification | Machine | ELF SHA-256 | Reproducible |",
        "|---|---|---|---|---|",
    ]
    for target, result in targets.items():
        markdown.append(
            f"| `{target}` | `{result['classification']}` | `{result['elf']['machine']}` | "
            f"`{result['elf']['sha256']}` | `{str(result['reproducible']).lower()}` |"
        )
    markdown.extend(
        [
            "",
            "The report proves bounded host-side rejection and exact dual-ISA artifact builds. It does not prove relocation, descriptor entry execution, or lifecycle behavior on a target; those remain HX3/HX4 hardware work.",
            "",
        ]
    )
    (out / "qualification-report.md").write_text("\n".join(markdown), encoding="utf-8")
    return report


def finalize_with_firmware(output: Path, firmware_report_path: Path) -> dict[str, Any]:
    out = output.resolve()
    report_path = out / "qualification-report.json"
    if not report_path.is_file() or not firmware_report_path.is_file():
        raise QualificationError("HX2 and firmware qualification reports must both exist")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    firmware = json.loads(firmware_report_path.read_text(encoding="utf-8"))
    if report.get("status") != "PASS" or firmware.get("status") != "PASS" or firmware.get("result") != "BUILD_PROVEN":
        raise QualificationError("cannot finalize HX2 from a non-passing qualification")
    firmware_targets: dict[str, Any] = {}
    for target in firmware["targets"]:
        firmware_targets[target["target"]] = {
            "id": target["id"],
            "build_result": target["build_result"],
            "reproducibility": target["reproducibility"],
            "delta": target["delta"],
            "runtime_result": target["runtime_result"],
        }
    report["firmware_qualification"] = {
        "status": firmware["status"],
        "result": firmware["result"],
        "report": str(firmware_report_path.resolve().relative_to(out)),
        "sha256": _sha256(firmware_report_path),
        "firmware_source": firmware["firmware_source"],
        "native_sdk_source": firmware.get("native_sdk_source"),
        "targets": firmware_targets,
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path = out / "qualification-report.md"
    markdown = markdown_path.read_text(encoding="utf-8").split("\n## Firmware integration\n", 1)[0].rstrip()
    markdown += (
        "\n\n## Firmware integration\n\n"
        "The exact ESP-IDF v5.4.4 firmware with `wdc_extension` is byte-reproducible "
        "across two isolated builds for both targets. Runtime remains `HARDWARE_NOT_RUN`.\n\n"
        "| Target | Firmware delta | Internal RAM delta | Remaining internal RAM |\n"
        "|---|---:|---:|---:|\n"
    )
    for target_name in ("esp32s3", "esp32c6"):
        result = firmware_targets[target_name]
        delta = result["delta"]
        size = delta["size_bytes"]
        host_report = next(
            item for item in firmware["targets"] if item["target"] == target_name
        )["host_reports"][0]
        cell = json.loads((firmware_report_path.parent / host_report).read_text(encoding="utf-8"))
        markdown += (
            f"| `{target_name}` | `{delta['firmware_bin_bytes']:+d}` bytes | "
            f"`{size['used_diram']:+d}` bytes | `{cell['size']['diram_remain']}` bytes |\n"
        )
    markdown_path.write_text(markdown + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--s3-compiler", type=Path)
    parser.add_argument("--c6-compiler", type=Path)
    parser.add_argument("--firmware-report", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.firmware_report is not None:
            report = finalize_with_firmware(args.out_dir, args.firmware_report.resolve())
        else:
            report = qualify(
                args.out_dir,
                {"esp32s3": args.s3_compiler, "esp32c6": args.c6_compiler},
            )
    except (OSError, QualificationError, build_native_extension.NativeBuildError,
            inspect_native_extension.ElfInspectionError) as exc:
        print(f"HX2 qualification failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"status": report["status"], "aggregate": report["aggregate"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
