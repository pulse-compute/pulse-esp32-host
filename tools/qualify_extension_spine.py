#!/usr/bin/env python3
"""Qualify the HX1 loader build boundary independently on S3 and C6."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

try:
    from tools import build_native_extension, idf_lock
except ModuleNotFoundError:  # Direct execution from tools/.
    import build_native_extension  # type: ignore[no-redef]
    import idf_lock  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = ROOT / "firmware" / "extension-proof-matrix.json"
SCHEMA = "pulse.esp32.extension-loader-qualification.v1"
EXPECTED_PROOFS = {
    "esp32s3-extension-proof": ("esp32s3-reference", "esp32s3", "xtensa"),
    "esp32c6-extension-proof": ("esp32c6-compile", "esp32c6", "riscv32"),
}
EXPECTED_COMPONENTS = {
    "espressif/cmake_utilities": ("0.5.3", "351350613ceafba240b761b4ea991e0f231ac7a9f59a9ee901f751bddc0bb18f"),
    "espressif/elf_loader": ("1.3.2", "9f7f6efa06e0847adeba6c9910c4308f33aae7d35ba0cc36c0850105c45e9874"),
    "espressif/wasm-micro-runtime": ("2.4.0~1", "04f25aad2896b5e906397a061d35cce560609bebd3913a4be7e365ecbf2dd9d6"),
}
EXPECTED_IDF_COMMIT = "296b6eab9445fd720e71aecab961e2d3fbca9944"
EXPECTED_ARTIFACTS = {
    "firmware_elf": "wdc_esp32_host.elf",
    "firmware_bin": "wdc_esp32_host.bin",
    "firmware_map": "wdc_esp32_host.map",
    "bootloader_bin": "bootloader/bootloader.bin",
    "partition_table_bin": "partition_table/partition-table.bin",
}


class QualificationError(RuntimeError):
    """Raised when HX1 cannot produce trustworthy build evidence."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file(path: Path, logical: str | None = None) -> dict[str, Any]:
    return {"path": logical or str(path), "sha256": _sha256(path), "size": path.stat().st_size}


def _tree_digest(root: Path, *, ignored: set[str] | None = None) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    ignored = ignored or set()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root)
        if any(part in ignored for part in relative.parts):
            continue
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(_sha256(path).encode("ascii"))
        digest.update(b"\n")
        count += 1
    return digest.hexdigest(), count


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QualificationError(f"cannot load {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise QualificationError(f"{path} must contain a JSON object")
    return value


def _prepare_out(path: Path, firmware_root: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(firmware_root.resolve())
    except ValueError:
        pass
    else:
        raise QualificationError("qualification output may not be inside the firmware source tree")
    if resolved.exists():
        if not resolved.is_dir() or any(resolved.iterdir()):
            raise QualificationError("qualification output directory must be absent or empty")
    else:
        resolved.mkdir(parents=True)
    return resolved


def _validate_matrix(matrix: dict[str, Any], matrix_path: Path) -> None:
    if matrix.get("schema") != "pulse.esp32.extension-proof-matrix.v1":
        raise QualificationError("extension proof matrix schema is missing or unsupported")
    if set(matrix.get("proofs", {})) != set(EXPECTED_PROOFS):
        raise QualificationError("extension proof matrix must contain exactly the S3 and C6 proofs")
    if matrix.get("preserved_results") != {"esp32c3-compile": "INCOMPATIBLE"}:
        raise QualificationError("the historical C3 incompatibility result was not preserved")
    loader = matrix.get("loader", {})
    for field, expected in {
        "component": "espressif/elf_loader",
        "version": "1.3.2",
        "license": "Apache-2.0",
        "source_commit": "1608d9c922c992986c285fd753ef15ecbbad3cde",
        "source_tree": "d2863c4d7360a3c735a8c801829ad0d10fd002e0",
    }.items():
        if loader.get(field) != expected:
            raise QualificationError(f"loader {field} is not the HX1 pin")
    firmware_root = matrix_path.parent
    baseline = _load_json(firmware_root / matrix["baseline_matrix"])
    for proof_id, (base, target, isa) in EXPECTED_PROOFS.items():
        proof = matrix["proofs"][proof_id]
        if (proof.get("base_realization"), proof.get("target"), proof.get("isa")) != (base, target, isa):
            raise QualificationError(f"{proof_id} does not match its IF7 basis")
        if proof.get("reproducibility_runs") != 2:
            raise QualificationError(f"{proof_id} must require two clean builds")
        if proof.get("runtime_result") != "HARDWARE_NOT_RUN":
            raise QualificationError(f"{proof_id} must not claim sandbox runtime evidence")
        base_entry = baseline.get("realizations", {}).get(base)
        if not isinstance(base_entry, dict) or base_entry.get("target") != target:
            raise QualificationError(f"{proof_id} baseline realization is invalid")
        for field in ("baseline_lock", "dependency_lock", "partitions"):
            path = firmware_root / proof[field]
            if not path.is_file():
                raise QualificationError(f"{proof_id} {field} is missing")
        for relative in proof.get("defaults", []):
            if not (firmware_root / relative).is_file():
                raise QualificationError(f"{proof_id} defaults file is missing: {relative}")


def _validate_extension_lock(path: Path, target: str) -> dict[str, Any]:
    lock, raw = idf_lock.load_lock(path)
    expected_top = {"dependencies", "direct_dependencies", "manifest_hash", "target", "version"}
    if set(lock) != expected_top or lock.get("version") != "2.0.0" or lock.get("target") != target:
        raise QualificationError(f"invalid extension lock structure for {target}")
    if lock.get("direct_dependencies") != ["espressif/elf_loader", "espressif/wasm-micro-runtime"]:
        raise QualificationError(f"invalid direct component graph for {target}")
    dependencies = lock.get("dependencies")
    if not isinstance(dependencies, dict) or set(dependencies) != {*EXPECTED_COMPONENTS, "idf"}:
        raise QualificationError(f"invalid resolved component set for {target}")
    for name, (version, component_hash) in EXPECTED_COMPONENTS.items():
        value = dependencies.get(name)
        if not isinstance(value, dict) or value.get("version") != version or value.get("component_hash") != component_hash:
            raise QualificationError(f"{target} lock does not pin {name} exactly")
    if dependencies["idf"] != {"source": {"type": "idf"}, "version": "5.4.4"}:
        raise QualificationError(f"{target} lock does not resolve exact IDF 5.4.4")
    return {
        "path": str(path),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "target": target,
        "manifest_hash": lock["manifest_hash"],
        "components": {
            name: {"version": dependencies[name]["version"], "component_hash": dependencies[name]["component_hash"]}
            for name in EXPECTED_COMPONENTS
        },
    }


def _run(command: list[str], *, cwd: Path, environment: dict[str, str], timeout: int) -> tuple[str, float]:
    started = time.monotonic()
    try:
        process = subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise QualificationError(f"command timed out: {' '.join(command)}") from exc
    elapsed = time.monotonic() - started
    if process.returncode != 0:
        tail = "\n".join((process.stdout or "").splitlines()[-30:])
        raise QualificationError(
            f"command exited with status {process.returncode}: {' '.join(command)}\n{tail}"
        )
    return process.stdout or "", elapsed


def _last_json(output: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    candidates: list[tuple[int, int, Any]] = []
    for index, character in enumerate(output):
        if character != "{":
            continue
        try:
            value, end = decoder.raw_decode(output[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            candidates.append((index + end, -index, value))
    if not candidates:
        raise QualificationError("IDF size output did not contain a JSON object")
    return max(candidates)[2]


def _copy_firmware(source: Path, destination: Path) -> None:
    ignored = {"build", "managed_components", "dependencies.lock", "sdkconfig", "__pycache__"}

    def ignore(_directory: str, names: list[str]) -> set[str]:
        return set(names) & ignored

    shutil.copytree(source, destination, ignore=ignore)
    native_sdk = source.parent / "native-sdk"
    if native_sdk.is_dir():
        shutil.copytree(native_sdk, destination.parent / "native-sdk", ignore=ignore)


def _make_baseline(project: Path) -> None:
    adapter = project / "components" / "wdc_elf"
    if not adapter.is_dir():
        raise QualificationError("cannot derive baseline: wdc_elf component is missing")
    shutil.rmtree(adapter)
    admission = project / "components" / "wdc_extension"
    if admission.is_dir():
        shutil.rmtree(admission)
    main_cmake = project / "main" / "CMakeLists.txt"
    text = main_cmake.read_text(encoding="utf-8")
    updated = text.replace(" wdc_elf ", " ").replace(" wdc_extension ", " ")
    if updated == text:
        raise QualificationError("cannot derive baseline: main does not require wdc_elf")
    main_cmake.write_text(updated, encoding="utf-8")
    app_main = project / "main" / "app_main.c"
    app_text = app_main.read_text(encoding="utf-8")
    app_updated = (
        app_text.replace('#include "wdc_elf.h"\n', "")
        .replace('#include "wdc_extension.h"\n', "")
        .replace("    (void)wdc_elf_link_anchor();\n", "")
        .replace("    (void)wdc_extension_link_anchor();\n", "")
    )
    if app_updated == app_text:
        raise QualificationError("cannot derive baseline: app link anchor is missing")
    app_main.write_text(app_updated, encoding="utf-8")


def _build_host(
    *,
    firmware_root: Path,
    proof: dict[str, Any],
    cell_dir: Path,
    idf_py: Path,
    lock_path: Path,
    defaults: list[str],
    baseline: bool,
    component_mirror: Path | None,
    timeout: int,
) -> dict[str, Any]:
    cell_dir.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix=f"pulse-hx1-{proof['target']}-") as temp_name:
        temporary = Path(temp_name)
        project = temporary / "firmware"
        build = temporary / "build"
        sdkconfig = temporary / "sdkconfig"
        _copy_firmware(firmware_root, project)
        if baseline:
            _make_baseline(project)
        if component_mirror is not None:
            managed = project / "managed_components"
            managed.mkdir()
            names = ["espressif__wasm-micro-runtime"] if baseline else [
                "espressif__cmake_utilities",
                "espressif__elf_loader",
                "espressif__wasm-micro-runtime",
            ]
            for name in names:
                source_component = component_mirror / name
                if not source_component.is_dir():
                    raise QualificationError(f"offline component mirror is missing {name}")
                shutil.copytree(source_component, managed / name)
        staged_lock = project / "dependencies.lock"
        staged_lock.write_bytes(lock_path.read_bytes())
        default_paths = [str(project / relative) for relative in defaults]
        definitions = [
            "-B",
            str(build),
            f"-DIDF_TARGET={proof['target']}",
            f"-DSDKCONFIG={sdkconfig}",
            f"-DSDKCONFIG_DEFAULTS={';'.join(default_paths)}",
        ]
        commands = [
            [str(idf_py), *definitions, "reconfigure"],
            [str(idf_py), *definitions, "build"],
            [str(idf_py), "-B", str(build), "size", "--format", "json"],
        ]
        environment = os.environ.copy()
        environment.update(
            {
                "IDF_CCACHE_ENABLE": "0",
                "IDF_TARGET": proof["target"],
                "LANG": "C",
                "LC_ALL": "C",
                "SOURCE_DATE_EPOCH": "0",
            }
        )
        logs: list[str] = []
        durations: dict[str, float] = {}
        outputs: list[str] = []
        for stage, command in zip(("reconfigure", "build", "size"), commands):
            output, elapsed = _run(command, cwd=project, environment=environment, timeout=timeout)
            outputs.append(output)
            durations[stage] = round(elapsed, 3)
            logs.append(f"=== {stage} ===\n$ {' '.join(command)}\n{output.rstrip()}\n")
            if staged_lock.read_bytes() != lock_path.read_bytes():
                raise QualificationError(f"{stage} mutated the staged dependency lock")

        log_path = cell_dir / "build.log"
        log_path.write_text("\n".join(logs), encoding="utf-8")
        size = _last_json(outputs[-1])
        size_path = cell_dir / "size.json"
        size_path.write_text(json.dumps(size, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        sdkconfig_path = cell_dir / "sdkconfig"
        shutil.copy2(sdkconfig, sdkconfig_path)
        resolved_lock = cell_dir / "dependencies.lock"
        shutil.copy2(staged_lock, resolved_lock)
        artifacts: dict[str, Any] = {}
        artifact_root = cell_dir / "artifacts"
        artifact_root.mkdir()
        for name, relative in EXPECTED_ARTIFACTS.items():
            source = build / relative
            if not source.is_file():
                raise QualificationError(f"build completed without {relative}")
            destination = artifact_root / Path(relative).name
            shutil.copy2(source, destination)
            artifacts[name] = _file(destination, f"artifacts/{destination.name}")
        managed = project / "managed_components" / "espressif__elf_loader"
        loader_tree = None
        if managed.is_dir():
            loader_tree, loader_files = _tree_digest(managed)
        else:
            loader_files = 0
        report = {
            "status": "PASS",
            "result": "BUILD_PROVEN",
            "target": proof["target"],
            "baseline": baseline,
            "commands": commands,
            "durations_seconds": durations,
            "lock": _file(resolved_lock, "dependencies.lock"),
            "sdkconfig": _file(sdkconfig_path, "sdkconfig"),
            "size": size,
            "size_evidence": _file(size_path, "size.json"),
            "build_log": _file(log_path, "build.log"),
            "artifacts": artifacts,
            "managed_loader_tree_sha256": loader_tree,
            "managed_loader_file_count": loader_files,
        }
        report_path = cell_dir / "cell-report.json"
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return report


def _delta(loader: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    keys = sorted(set(loader["size"]) & set(baseline["size"]))
    sizes = {
        key: loader["size"][key] - baseline["size"][key]
        for key in keys
        if isinstance(loader["size"][key], int) and isinstance(baseline["size"][key], int)
    }
    loader_bin = loader["artifacts"]["firmware_bin"]["size"]
    baseline_bin = baseline["artifacts"]["firmware_bin"]["size"]
    return {
        "size_bytes": sizes,
        "firmware_bin_bytes": loader_bin - baseline_bin,
        "psram_static_bytes": 0,
        "psram_runtime_bytes": "NOT_MEASURED_NO_HARDWARE",
    }


def _reproducibility(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    artifact_matches = {
        name: first["artifacts"][name]["sha256"] == second["artifacts"][name]["sha256"]
        for name in EXPECTED_ARTIFACTS
        if name != "firmware_map"
    }
    return {
        "artifacts": artifact_matches,
        "sdkconfig_identical": first["sdkconfig"]["sha256"] == second["sdkconfig"]["sha256"],
        "lock_identical": first["lock"]["sha256"] == second["lock"]["sha256"],
        "size_identical": first["size"] == second["size"],
        "reproducible": all(artifact_matches.values())
        and first["sdkconfig"]["sha256"] == second["sdkconfig"]["sha256"]
        and first["lock"]["sha256"] == second["lock"]["sha256"]
        and first["size"] == second["size"],
        "map_excluded_reason": "absolute isolated build paths make linker maps non-byte-reproducible",
    }


def _environment(idf_path: Path, idf_py: Path) -> dict[str, Any]:
    if not idf_path.is_dir() or not idf_py.is_file():
        raise QualificationError("IDF_PATH and idf.py must be available")
    commit = subprocess.run(
        ["git", "-C", str(idf_path), "rev-parse", "HEAD"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    ).stdout.strip()
    if commit != EXPECTED_IDF_COMMIT:
        raise QualificationError(f"ESP-IDF checkout is {commit or 'unresolved'}, expected {EXPECTED_IDF_COMMIT}")
    tools: dict[str, Any] = {}
    for name in ("cmake", "ninja", "xtensa-esp32s3-elf-gcc", "riscv32-esp-elf-gcc"):
        discovered = shutil.which(name)
        if discovered is None:
            raise QualificationError(f"required build tool is missing from PATH: {name}")
        path = Path(discovered).resolve()
        version_arg = "--version"
        output = subprocess.run(
            [str(path), version_arg], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False
        ).stdout.splitlines()
        tools[name] = {
            "path": str(path),
            "sha256": _sha256(path),
            "version": output[0] if output else "unobserved",
        }
    component_manager_patch = Path(sys.prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages" / "idf_component_manager" / "prepare_components" / "cmake_pid.py"
    if not component_manager_patch.is_file():
        # Qualification may run under /usr/bin/python while idf.py uses the
        # active PATH environment. Resolve the latter's prefix explicitly.
        active_python = shutil.which("python") or shutil.which("python3")
        process = subprocess.run(
            [str(active_python), "-c", "import pathlib,idf_component_manager; print(pathlib.Path(idf_component_manager.__file__).parent/'prepare_components'/'cmake_pid.py')"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        component_manager_patch = Path(process.stdout.strip())
    return {
        "platform": {"system": platform.system(), "machine": platform.machine(), "python": platform.python_version()},
        "idf": {"path": str(idf_path), "version": "v5.4.4", "source_commit": commit},
        "idf_py": str(idf_py),
        "tools": tools,
        "sandbox_component_manager_pid_workaround": (
            _file(component_manager_patch) if component_manager_patch.is_file() else "NOT_PRESENT"
        ),
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# HX1 ELF loader qualification",
        "",
        f"- Status: `{report['status']}`",
        f"- Aggregate build result: `{report['result']}`",
        f"- Runtime result: `{report['runtime_result']}`",
        f"- Loader: `espressif/elf_loader {report['loader']['version']}`",
        f"- ESP-IDF: `{report['environment']['idf']['version']}` at `{report['environment']['idf']['source_commit']}`",
        "",
        "| Target | Build | Runtime | Reproducible | Firmware delta |",
        "|---|---|---|---|---:|",
    ]
    for target in report["targets"]:
        lines.append(
            f"| {target['target']} | {target['build_result']} | {target['runtime_result']} | "
            f"{'yes' if target['reproducibility']['reproducible'] else 'no'} | "
            f"{target['delta']['firmware_bin_bytes']} bytes |"
        )
    lines.extend(
        [
            "",
            "No board was attached. Load, unload, repeated-cycle, leak, and executable-memory runtime behavior remain `NOT_RUN`; compile evidence is not a runtime claim.",
            "",
        ]
    )
    return "\n".join(lines)


def qualify(
    *,
    matrix_path: Path,
    out_dir: Path,
    idf_path: Path,
    idf_py: Path,
    component_mirror: Path | None,
    timeout: int,
) -> dict[str, Any]:
    matrix_path = matrix_path.resolve()
    firmware_root = matrix_path.parent
    output = _prepare_out(out_dir, firmware_root)
    matrix = _load_json(matrix_path)
    _validate_matrix(matrix, matrix_path)
    environment = _environment(idf_path.resolve(), idf_py.resolve())
    if component_mirror is not None:
        component_mirror = component_mirror.resolve()
        if not component_mirror.is_dir():
            raise QualificationError("offline component mirror is missing")
        mirror_hash, mirror_files = _tree_digest(component_mirror)
        environment["offline_component_mirror"] = {
            "path": str(component_mirror),
            "sha256": mirror_hash,
            "file_count": mirror_files,
        }
    source_hash, source_files = _tree_digest(
        firmware_root, ignored={"build", "managed_components", "dependencies.lock", "sdkconfig", "__pycache__"}
    )
    native_sdk_root = firmware_root.parent / "native-sdk"
    native_sdk_identity = None
    if native_sdk_root.is_dir():
        native_sdk_hash, native_sdk_files = _tree_digest(native_sdk_root, ignored={"__pycache__"})
        native_sdk_identity = {"sha256": native_sdk_hash, "file_count": native_sdk_files}
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "FAIL",
        "result": "UNCLASSIFIED_FAILURE",
        "runtime_result": "HARDWARE_NOT_RUN",
        "loader": matrix["loader"],
        "environment": environment,
        "firmware_source": {"sha256": source_hash, "file_count": source_files},
        "native_sdk_source": native_sdk_identity,
        "matrix": _file(matrix_path),
        "targets": [],
        "source_findings": {
            "constructor_behavior": "esp_elf_relocate loads and relocates only; esp_elf_request is the separate entry execution API",
            "unsupported_relocation_return": "upstream esp_elf_relocate does not propagate esp_elf_arch_relocate return codes; the independent inspector must reject unsupported types before this adapter is called",
            "raw_byte_boundary": "wdc_elf_load_inspected accepts the immutable inspector-approved buffer and does not claim to validate its length internally",
            "c6_segment_start": "the upstream unified-segment path leaves svaddr at zero; the inspector therefore requires the first C6 PT_LOAD virtual address to be zero",
        },
    }
    all_reproducible = True
    for proof_id in EXPECTED_PROOFS:
        proof = matrix["proofs"][proof_id]
        target_dir = output / proof_id
        lock_path = firmware_root / proof["dependency_lock"]
        lock_evidence = _validate_extension_lock(lock_path, proof["target"])
        baseline = _build_host(
            firmware_root=firmware_root,
            proof=proof,
            cell_dir=target_dir / "baseline",
            idf_py=idf_py,
            lock_path=firmware_root / proof["baseline_lock"],
            defaults=proof["defaults"][:-1],
            baseline=True,
            component_mirror=component_mirror,
            timeout=timeout,
        )
        runs = []
        for label in ("a", "b"):
            runs.append(
                _build_host(
                    firmware_root=firmware_root,
                    proof=proof,
                    cell_dir=target_dir / f"host-run-{label}",
                    idf_py=idf_py,
                    lock_path=lock_path,
                    defaults=proof["defaults"],
                    baseline=False,
                    component_mirror=component_mirror,
                    timeout=timeout,
                )
            )
        compiler_name = build_native_extension.COMPILERS[proof["target"]]
        compiler = Path(environment["tools"][compiler_name]["path"])
        probes = []
        for label in ("a", "b"):
            probes.append(
                build_native_extension.build_probe(
                    target=proof["target"],
                    source=build_native_extension.DEFAULT_SOURCE,
                    out_dir=target_dir / f"probe-run-{label}",
                    compiler=compiler,
                )
            )
        host_repro = _reproducibility(runs[0], runs[1])
        probe_repro = (
            probes[0]["artifacts"]["elf"]["sha256"] == probes[1]["artifacts"]["elf"]["sha256"]
        )
        host_repro["native_probe_identical"] = probe_repro
        host_repro["reproducible"] = host_repro["reproducible"] and probe_repro
        all_reproducible = all_reproducible and host_repro["reproducible"]
        first_inspection = _load_json(target_dir / "probe-run-a" / "inspection.json")
        delta = _delta(runs[0], baseline)
        if delta["firmware_bin_bytes"] <= 0:
            raise QualificationError(
                f"{proof['target']} loader build has no positive firmware delta; adapter/loader may have been discarded"
            )
        report["targets"].append(
            {
                "id": proof_id,
                "target": proof["target"],
                "isa": proof["isa"],
                "build_result": "BUILD_PROVEN",
                "runtime_result": "HARDWARE_NOT_RUN",
                "lock": lock_evidence,
                "baseline_report": f"{proof_id}/baseline/cell-report.json",
                "host_reports": [
                    f"{proof_id}/host-run-a/cell-report.json",
                    f"{proof_id}/host-run-b/cell-report.json",
                ],
                "probe_reports": [
                    f"{proof_id}/probe-run-a/build-report.json",
                    f"{proof_id}/probe-run-b/build-report.json",
                ],
                "elf_inventory": {
                    "header": first_inspection["header"],
                    "sections": first_inspection["sections"],
                    "supported_relocations": first_inspection["loader_supported_relocations"],
                    "observed_relocations": first_inspection["observed_relocation_types"],
                    "imports": first_inspection["imports"],
                    "exports": first_inspection["exports"],
                    "constructor_surfaces": first_inspection["constructor_surfaces"],
                },
                "executable_memory": (
                    {
                        "allocation": "separate text allocation with MALLOC_CAP_EXEC; data uses MALLOC_CAP_8BIT",
                        "psram": "disabled by HX1 overlay",
                        "runtime_permission_observation": "NOT_RUN",
                    }
                    if proof["target"] == "esp32s3"
                    else {
                        "allocation": "one cache-aligned MALLOC_CAP_8BIT PT_LOAD segment; source treats it as unified executable/data memory",
                        "psram": "not available in the C6 realization",
                        "runtime_permission_observation": "NOT_RUN",
                    }
                ),
                "delta": delta,
                "reproducibility": host_repro,
                "loader_runtime": {
                    "load_return_codes": "NOT_RUN",
                    "unload_return_codes": "NOT_RUN",
                    "repeated_load_cycles": "NOT_RUN",
                    "leak_growth": "NOT_MEASURED_NO_HARDWARE",
                },
            }
        )
    report["status"] = "PASS" if all_reproducible else "FAIL"
    report["result"] = "BUILD_PROVEN" if all_reproducible else "UNCLASSIFIED_FAILURE"
    (output / "qualification-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output / "qualification-report.md").write_text(_markdown(report), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--idf-path", type=Path, default=Path(os.environ.get("IDF_PATH", "")))
    parser.add_argument("--idf-py", type=Path, default=Path(shutil.which("idf.py") or ""))
    parser.add_argument(
        "--component-mirror",
        type=Path,
        default=Path(os.environ["HX_COMPONENT_MIRROR"]) if os.environ.get("HX_COMPONENT_MIRROR") else None,
    )
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args(argv)
    try:
        report = qualify(
            matrix_path=args.matrix,
            out_dir=args.out_dir,
            idf_path=args.idf_path,
            idf_py=args.idf_py,
            component_mirror=args.component_mirror,
            timeout=args.timeout,
        )
    except (OSError, ValueError, QualificationError, build_native_extension.NativeBuildError) as exc:
        print(f"HX1 qualification failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"status": report["status"], "result": report["result"], "out_dir": str(args.out_dir)}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
