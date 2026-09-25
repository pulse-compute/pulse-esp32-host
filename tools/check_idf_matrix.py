#!/usr/bin/env python3
"""Fail-closed validation for the pinned ESP-IDF family matrix."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any

try:
    from tools import idf_lock
except ModuleNotFoundError:  # Direct execution from tools/.
    import idf_lock  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = ROOT / "firmware" / "idf-family-matrix.json"

SCHEMA = "pulse.esp32.idf-family-matrix.v1"
CANONICAL_LANE_ID = "idf-5.4.4"
CANONICAL_LANE = {
    "version": "v5.4.4",
    "source_commit": "296b6eab9445fd720e71aecab961e2d3fbca9944",
    "platform": "linux/amd64",
    "container_image": "espressif/idf@sha256:8d1846f61ff8db00ba6530501f90bf43604d923072a616c806fef8e85a88ed82",
    "wamr_version": "2.4.0~1",
}

INTENTS = frozenset({"required", "exploratory", "deferred", "excluded"})
BUILD_RESULTS = frozenset(
    {
        "BUILD_QUALIFIED",
        "COMPILE_PROVEN",
        "INCOMPATIBLE",
        "INFRASTRUCTURE_FAILURE",
        "UNCLASSIFIED_FAILURE",
    }
)

EXPECTED_REALIZATIONS = {
    "esp32s3-reference": ("esp32s3", "required"),
    "esp32-compile": ("esp32", "exploratory"),
    "esp32c3-compile": ("esp32c3", "exploratory"),
    "esp32c6-compile": ("esp32c6", "exploratory"),
}
EXPECTED_DEFERRED = {
    "esp32p4-deferred": ("esp32p4", "deferred"),
    "esp32c5-deferred": ("esp32c5", "deferred"),
}
EXPECTED_EXCLUDED = {
    "esp32s2-excluded": ("esp32s2", "excluded"),
    "esp32c2-excluded": ("esp32c2", "excluded"),
    "esp32h2-excluded": ("esp32h2", "excluded"),
    "esp32c61-excluded": ("esp32c61", "excluded"),
}

TOP_LEVEL_FIELDS = frozenset({"schema", "lanes", "realizations", "deferred", "excluded"})
LANE_FIELDS = frozenset(CANONICAL_LANE)
REALIZATION_FIELDS = frozenset(
    {
        "lane",
        "target",
        "intent",
        "reason",
        "defaults",
        "partitions",
        "dependency_lock",
        "reproducibility_runs",
    }
)
INVENTORY_FIELDS = frozenset({"id", "lane", "target", "intent", "reason"})

COMMON_CONFIG = {
    "CONFIG_LOG_DEFAULT_LEVEL_INFO": "y",
    "CONFIG_COMPILER_OPTIMIZATION_SIZE": "y",
    "CONFIG_APP_REPRODUCIBLE_BUILD": "y",
}
S3_OVERLAY_CONFIG = {
    "CONFIG_PARTITION_TABLE_CUSTOM": "y",
    "CONFIG_PARTITION_TABLE_CUSTOM_FILENAME": "partitions.csv",
    "CONFIG_ESPTOOLPY_FLASHSIZE_16MB": "y",
    "CONFIG_SPIRAM": "y",
    "CONFIG_SPIRAM_USE_MALLOC": "y",
}
COMPILE_OVERLAY_CONFIG = {
    "CONFIG_PARTITION_TABLE_CUSTOM": "y",
    "CONFIG_PARTITION_TABLE_CUSTOM_FILENAME": "partitions/compile-16m-no-psram.csv",
    "CONFIG_ESPTOOLPY_FLASHSIZE_16MB": "y",
}
ESP32_COMPILE_OVERLAY_CONFIG = {
    **COMPILE_OVERLAY_CONFIG,
    "CONFIG_SPIRAM": "n",
    "CONFIG_SPIRAM_USE_MALLOC": "n",
}
COMPILE_OVERLAY_CONFIGS = {
    "esp32-compile": ESP32_COMPILE_OVERLAY_CONFIG,
    # ESP32-C3/C6 do not expose these SPIRAM Kconfig symbols in IDF 5.4.4.
    # Omitting an unsupported symbol is the exact no-PSRAM configuration.
    "esp32c3-compile": COMPILE_OVERLAY_CONFIG,
    "esp32c6-compile": COMPILE_OVERLAY_CONFIG,
}

SDKCONFIG_SET_RE = re.compile(r"^(CONFIG_[A-Z0-9_]+)=(.*)$")
SDKCONFIG_UNSET_RE = re.compile(r"^# (CONFIG_[A-Z0-9_]+) is not set$")


class DuplicateKeyError(ValueError):
    """Raised when JSON object syntax contains a repeated key."""


class MatrixContractError(ValueError):
    """Raised when a standalone matrix vocabulary value is invalid."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate key {key!r}")
        result[key] = value
    return result


def load_matrix(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except OSError as exc:
        raise MatrixContractError(f"cannot read matrix: {exc}") from exc
    except (json.JSONDecodeError, DuplicateKeyError) as exc:
        raise MatrixContractError(f"invalid matrix JSON: {exc}") from exc
    if not isinstance(loaded, dict):
        raise MatrixContractError("matrix root must be an object")
    return loaded


def validate_result_name(value: Any) -> str:
    """Validate the closed result vocabulary used by later qualification passes."""
    if not isinstance(value, str) or value not in BUILD_RESULTS:
        raise MatrixContractError(f"unsupported build result {value!r}")
    return value


def _check_fields(
    value: Any,
    *,
    label: str,
    allowed: frozenset[str],
    required: frozenset[str],
    errors: list[str],
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        errors.append(f"{label} must be an object")
        return None
    unknown = sorted(set(value) - allowed)
    missing = sorted(required - set(value))
    if unknown:
        errors.append(f"{label} has unknown fields: {', '.join(unknown)}")
    if missing:
        errors.append(f"{label} is missing fields: {', '.join(missing)}")
    return value


def _check_reason(value: Any, label: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{label} reason must be a non-empty string")


def _firmware_path(value: Any, label: str, firmware_root: Path) -> Path:
    if not isinstance(value, str) or not value:
        raise MatrixContractError(f"{label} must be a non-empty relative path")
    if "\\" in value:
        raise MatrixContractError(f"{label} must use POSIX separators")
    pure = PurePosixPath(value)
    if pure.is_absolute() or str(pure) != value or any(part in {".", ".."} for part in pure.parts):
        raise MatrixContractError(f"{label} must be a normalized relative path inside firmware")
    candidate = (firmware_root / Path(*pure.parts)).resolve()
    try:
        candidate.relative_to(firmware_root)
    except ValueError as exc:
        raise MatrixContractError(f"{label} escapes the firmware tree") from exc
    return candidate


def _check_relative_path(value: Any, label: str, firmware_root: Path, errors: list[str]) -> None:
    try:
        _firmware_path(value, label, firmware_root)
    except MatrixContractError as exc:
        errors.append(str(exc))


def parse_sdkconfig_defaults(path: Path) -> dict[str, str]:
    """Parse the strict sdkconfig fragment subset used by matrix realizations."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise MatrixContractError(f"configuration file is missing or unreadable: {path.name}") from exc

    settings: dict[str, str] = {}
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        unset = SDKCONFIG_UNSET_RE.fullmatch(line)
        if unset:
            key = unset.group(1)
            value = "n"
        elif line.startswith("#"):
            continue
        else:
            match = SDKCONFIG_SET_RE.fullmatch(line)
            if match is None or not match.group(2):
                raise MatrixContractError(f"invalid sdkconfig syntax in {path.name}:{line_number}")
            key = match.group(1)
            raw_value = match.group(2)
            if raw_value.startswith('"'):
                try:
                    value = json.loads(raw_value)
                except json.JSONDecodeError as exc:
                    raise MatrixContractError(
                        f"invalid quoted sdkconfig value in {path.name}:{line_number}"
                    ) from exc
                if not isinstance(value, str):
                    raise MatrixContractError(f"invalid sdkconfig string in {path.name}:{line_number}")
            else:
                value = raw_value
        if key in settings:
            raise MatrixContractError(f"duplicate sdkconfig key {key!r} in {path.name}")
        settings[key] = value
    return settings


def _partition_rows(path: Path) -> tuple[str, ...]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise MatrixContractError(f"partition file is missing or unreadable: {path.name}") from exc
    rows = tuple(
        "".join(line.split())
        for line in lines
        if line.strip() and not line.lstrip().startswith("#")
    )
    if not rows:
        raise MatrixContractError(f"partition file has no entries: {path.name}")
    if any(len(row.split(",")) != 6 for row in rows):
        raise MatrixContractError(f"partition file has a non-six-column row: {path.name}")
    return rows


def resolve_realization(
    matrix: dict[str, Any], realization_id: str, matrix_path: Path
) -> dict[str, Any]:
    """Resolve one attempted realization entirely in memory without invoking IDF."""
    realizations = matrix.get("realizations")
    if not isinstance(realizations, dict) or realization_id not in realizations:
        raise MatrixContractError(f"unknown realization {realization_id!r}")
    entry = realizations[realization_id]
    if not isinstance(entry, dict):
        raise MatrixContractError(f"realization {realization_id!r} must be an object")

    firmware_root = matrix_path.resolve().parent
    defaults = entry.get("defaults")
    if not isinstance(defaults, list):
        raise MatrixContractError(f"realization {realization_id!r} defaults must be an array")

    merged: dict[str, str] = {}
    fragments: list[dict[str, Any]] = []
    for index, relative in enumerate(defaults):
        path = _firmware_path(
            relative,
            f"matrix.realizations.{realization_id}.defaults[{index}]",
            firmware_root,
        )
        if not path.is_file():
            raise MatrixContractError(
                f"matrix.realizations.{realization_id}.defaults[{index}] does not exist"
            )
        settings = parse_sdkconfig_defaults(path)
        overlap = sorted(set(merged) & set(settings))
        if overlap:
            raise MatrixContractError(
                f"realization {realization_id!r} redefines sdkconfig keys across fragments: "
                + ", ".join(overlap)
            )
        merged.update(settings)
        fragments.append({"path": relative, "settings": settings})

    partition_relative = entry.get("partitions")
    partition_path = _firmware_path(
        partition_relative,
        f"matrix.realizations.{realization_id}.partitions",
        firmware_root,
    )
    if not partition_path.is_file():
        raise MatrixContractError(f"matrix.realizations.{realization_id}.partitions does not exist")

    return {
        "id": realization_id,
        "target": entry.get("target"),
        "defaults": tuple(defaults),
        "fragments": tuple(fragments),
        "config": merged,
        "partitions": partition_relative,
        "partition_rows": _partition_rows(partition_path),
    }


def _config_difference(actual: dict[str, str], expected: dict[str, str]) -> str:
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    changed = sorted(key for key in set(actual) & set(expected) if actual[key] != expected[key])
    parts = []
    if missing:
        parts.append(f"missing={','.join(missing)}")
    if extra:
        parts.append(f"extra={','.join(extra)}")
    if changed:
        parts.append(f"changed={','.join(changed)}")
    return "; ".join(parts) or "unknown difference"


def _validate_realization_files(
    matrix: dict[str, Any], matrix_path: Path, errors: list[str]
) -> None:
    resolved: dict[str, dict[str, Any]] = {}
    for realization_id in EXPECTED_REALIZATIONS:
        try:
            resolved[realization_id] = resolve_realization(matrix, realization_id, matrix_path)
        except MatrixContractError as exc:
            errors.append(str(exc))

    if not resolved:
        return

    common_path = matrix_path.resolve().parent / "sdkconfig.defaults"
    try:
        common = parse_sdkconfig_defaults(common_path)
    except MatrixContractError as exc:
        errors.append(str(exc))
        common = None
    if common is not None and common != COMMON_CONFIG:
        errors.append(
            "common sdkconfig defaults are not the frozen cross-family invariants: "
            + _config_difference(common, COMMON_CONFIG)
        )

    s3 = resolved.get("esp32s3-reference")
    if s3 is not None:
        expected = {**COMMON_CONFIG, **S3_OVERLAY_CONFIG}
        if s3["config"] != expected:
            errors.append(
                "esp32s3-reference does not preserve the frozen S3 configuration: "
                + _config_difference(s3["config"], expected)
            )

    for realization_id in ("esp32-compile", "esp32c3-compile", "esp32c6-compile"):
        cell = resolved.get(realization_id)
        if cell is None:
            continue
        expected = {**COMMON_CONFIG, **COMPILE_OVERLAY_CONFIGS[realization_id]}
        if cell["config"] != expected:
            errors.append(
                f"{realization_id} is not the frozen non-PSRAM compile configuration: "
                + _config_difference(cell["config"], expected)
            )

    if s3 is not None:
        for realization_id in ("esp32-compile", "esp32c3-compile", "esp32c6-compile"):
            cell = resolved.get(realization_id)
            if cell is not None and cell["partition_rows"] != s3["partition_rows"]:
                errors.append(
                    f"{realization_id} partition rows must mirror the S3 reference layout for compile-only mapping"
                )


def _check_expected_ids(
    observed: set[str], expected: dict[str, tuple[str, str]], label: str, errors: list[str]
) -> None:
    missing = sorted(set(expected) - observed)
    unknown = sorted(observed - set(expected))
    if missing:
        errors.append(f"{label} is missing inventory IDs: {', '.join(missing)}")
    if unknown:
        errors.append(f"{label} has unknown inventory IDs: {', '.join(unknown)}")


def validate_matrix(matrix: dict[str, Any], matrix_path: Path) -> list[str]:
    errors: list[str] = []
    root = _check_fields(
        matrix,
        label="matrix",
        allowed=TOP_LEVEL_FIELDS,
        required=TOP_LEVEL_FIELDS,
        errors=errors,
    )
    if root is None:
        return errors

    if matrix.get("schema") != SCHEMA:
        errors.append(f"matrix schema must be {SCHEMA!r}")

    lanes = matrix.get("lanes")
    if not isinstance(lanes, dict):
        errors.append("matrix.lanes must be an object")
        lanes = {}
    else:
        _check_expected_ids(set(lanes), {CANONICAL_LANE_ID: ("", "")}, "matrix.lanes", errors)

    lane = lanes.get(CANONICAL_LANE_ID)
    lane_obj = _check_fields(
        lane,
        label=f"matrix.lanes.{CANONICAL_LANE_ID}",
        allowed=LANE_FIELDS,
        required=LANE_FIELDS,
        errors=errors,
    )
    if lane_obj is not None:
        for field, expected in CANONICAL_LANE.items():
            if lane_obj.get(field) != expected:
                errors.append(
                    f"matrix.lanes.{CANONICAL_LANE_ID}.{field} must be pinned to {expected!r}"
                )
        version = lane_obj.get("version")
        commit = lane_obj.get("source_commit")
        image = lane_obj.get("container_image")
        platform = lane_obj.get("platform")
        wamr = lane_obj.get("wamr_version")
        if not isinstance(version, str) or not re.fullmatch(r"v\d+\.\d+\.\d+", version):
            errors.append(f"matrix.lanes.{CANONICAL_LANE_ID}.version must be an exact release")
        if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
            errors.append(f"matrix.lanes.{CANONICAL_LANE_ID}.source_commit must be a 40-hex commit")
        if not isinstance(image, str) or not re.fullmatch(r"[^@\s]+@sha256:[0-9a-f]{64}", image):
            errors.append(f"matrix.lanes.{CANONICAL_LANE_ID}.container_image must use a sha256 digest")
        if not isinstance(platform, str) or not re.fullmatch(r"[a-z0-9._-]+/[a-z0-9._-]+", platform):
            errors.append(f"matrix.lanes.{CANONICAL_LANE_ID}.platform must be exact")
        if not isinstance(wamr, str) or not re.fullmatch(r"\d+\.\d+\.\d+(?:~\d+)?", wamr):
            errors.append(f"matrix.lanes.{CANONICAL_LANE_ID}.wamr_version must be an exact version")

    firmware_root = matrix_path.resolve().parent
    seen_ids: set[str] = set()
    seen_targets: dict[str, str] = {}

    realizations = matrix.get("realizations")
    if not isinstance(realizations, dict):
        errors.append("matrix.realizations must be an object")
        realizations = {}
    _check_expected_ids(set(realizations), EXPECTED_REALIZATIONS, "matrix.realizations", errors)

    for realization_id, value in realizations.items():
        seen_ids.add(realization_id)
        entry = _check_fields(
            value,
            label=f"matrix.realizations.{realization_id}",
            allowed=REALIZATION_FIELDS,
            required=REALIZATION_FIELDS,
            errors=errors,
        )
        if entry is None:
            continue
        expected = EXPECTED_REALIZATIONS.get(realization_id)
        if expected is not None:
            expected_target, expected_intent = expected
            if entry.get("target") != expected_target:
                errors.append(f"matrix.realizations.{realization_id}.target must be {expected_target!r}")
            if entry.get("intent") != expected_intent:
                errors.append(f"matrix.realizations.{realization_id}.intent must be {expected_intent!r}")
        intent = entry.get("intent")
        if intent not in INTENTS:
            errors.append(f"matrix.realizations.{realization_id} has unsupported intent {intent!r}")
        elif intent not in {"required", "exploratory"}:
            errors.append(f"matrix.realizations.{realization_id} intent must be required or exploratory")
        if entry.get("lane") not in lanes:
            errors.append(f"matrix.realizations.{realization_id} references missing lane {entry.get('lane')!r}")
        elif entry.get("lane") != CANONICAL_LANE_ID:
            errors.append(f"matrix.realizations.{realization_id} must use {CANONICAL_LANE_ID!r}")
        _check_reason(entry.get("reason"), f"matrix.realizations.{realization_id}", errors)

        target = entry.get("target")
        if isinstance(target, str):
            if target in seen_targets:
                errors.append(
                    f"target {target!r} is duplicated by {seen_targets[target]!r} and {realization_id!r}"
                )
            else:
                seen_targets[target] = realization_id
        else:
            errors.append(f"matrix.realizations.{realization_id}.target must be a string")

        defaults = entry.get("defaults")
        expected_defaults = ["sdkconfig.defaults", f"realizations/{realization_id}.defaults"]
        if not isinstance(defaults, list):
            errors.append(f"matrix.realizations.{realization_id}.defaults must be an array")
        else:
            if defaults != expected_defaults:
                errors.append(
                    f"matrix.realizations.{realization_id}.defaults must be the common defaults followed by its overlay"
                )
            if len(defaults) != len(set(item for item in defaults if isinstance(item, str))):
                errors.append(f"matrix.realizations.{realization_id}.defaults contains duplicates")
            for index, default in enumerate(defaults):
                _check_relative_path(
                    default,
                    f"matrix.realizations.{realization_id}.defaults[{index}]",
                    firmware_root,
                    errors,
                )

        partitions = entry.get("partitions")
        expected_partitions = (
            "partitions.csv" if realization_id == "esp32s3-reference" else "partitions/compile-16m-no-psram.csv"
        )
        if partitions != expected_partitions:
            errors.append(f"matrix.realizations.{realization_id}.partitions must be {expected_partitions!r}")
        _check_relative_path(
            partitions, f"matrix.realizations.{realization_id}.partitions", firmware_root, errors
        )

        expected_lock = f"locks/{CANONICAL_LANE_ID}/{target}/dependencies.lock"
        lock = entry.get("dependency_lock")
        if lock != expected_lock:
            errors.append(f"matrix.realizations.{realization_id}.dependency_lock must be {expected_lock!r}")
        _check_relative_path(
            lock, f"matrix.realizations.{realization_id}.dependency_lock", firmware_root, errors
        )

        runs = entry.get("reproducibility_runs")
        if not isinstance(runs, int) or isinstance(runs, bool):
            errors.append(f"matrix.realizations.{realization_id}.reproducibility_runs must be an integer")
        elif intent == "required" and runs < 2:
            errors.append(f"matrix.realizations.{realization_id} requires at least two reproducibility runs")
        elif intent == "exploratory" and runs != 1:
            errors.append(f"matrix.realizations.{realization_id} exploratory runs must equal one")

    for collection_name, expected_entries in (
        ("deferred", EXPECTED_DEFERRED),
        ("excluded", EXPECTED_EXCLUDED),
    ):
        collection = matrix.get(collection_name)
        if not isinstance(collection, list):
            errors.append(f"matrix.{collection_name} must be an array")
            collection = []
        observed_ids: set[str] = set()
        for index, value in enumerate(collection):
            label = f"matrix.{collection_name}[{index}]"
            entry = _check_fields(
                value,
                label=label,
                allowed=INVENTORY_FIELDS,
                required=INVENTORY_FIELDS,
                errors=errors,
            )
            if entry is None:
                continue
            entry_id = entry.get("id")
            if not isinstance(entry_id, str) or not entry_id:
                errors.append(f"{label}.id must be a non-empty string")
                continue
            if entry_id in observed_ids:
                errors.append(f"matrix.{collection_name} contains duplicate ID {entry_id!r}")
            observed_ids.add(entry_id)
            if entry_id in seen_ids:
                errors.append(f"inventory ID {entry_id!r} is duplicated across collections")
            seen_ids.add(entry_id)

            expected = expected_entries.get(entry_id)
            if expected is not None:
                expected_target, expected_intent = expected
                if entry.get("target") != expected_target:
                    errors.append(f"{label}.target must be {expected_target!r}")
                if entry.get("intent") != expected_intent:
                    errors.append(f"{label}.intent must be {expected_intent!r}")
            intent = entry.get("intent")
            if intent not in INTENTS:
                errors.append(f"{label} has unsupported intent {intent!r}")
            else:
                collection_intent = "deferred" if collection_name == "deferred" else "excluded"
                if intent != collection_intent:
                    errors.append(f"{label}.intent must be {collection_intent!r}")
            if entry.get("lane") not in lanes:
                errors.append(f"{label} references missing lane {entry.get('lane')!r}")
            elif entry.get("lane") != CANONICAL_LANE_ID:
                errors.append(f"{label} must use {CANONICAL_LANE_ID!r}")
            _check_reason(entry.get("reason"), label, errors)

            target = entry.get("target")
            if isinstance(target, str):
                if target in seen_targets:
                    errors.append(
                        f"target {target!r} is duplicated by {seen_targets[target]!r} and {entry_id!r}"
                    )
                else:
                    seen_targets[target] = entry_id
            else:
                errors.append(f"{label}.target must be a string")

        _check_expected_ids(observed_ids, expected_entries, f"matrix.{collection_name}", errors)

    expected_all = set(EXPECTED_REALIZATIONS) | set(EXPECTED_DEFERRED) | set(EXPECTED_EXCLUDED)
    missing_all = sorted(expected_all - seen_ids)
    if missing_all:
        errors.append(f"matrix inventory is incomplete: {', '.join(missing_all)}")

    _validate_realization_files(matrix, matrix_path, errors)

    return errors


def validate_locks(
    matrix: dict[str, Any], matrix_path: Path
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    """Require every attempted cell's target-specific component lock."""
    errors: list[str] = []
    evidence: dict[str, dict[str, Any]] = {}
    firmware_root = matrix_path.resolve().parent
    lane = matrix["lanes"][CANONICAL_LANE_ID]
    for realization_id, realization in matrix["realizations"].items():
        try:
            lock_path = _firmware_path(
                realization["dependency_lock"],
                f"matrix.realizations.{realization_id}.dependency_lock",
                firmware_root,
            )
        except MatrixContractError as exc:
            errors.append(str(exc))
            continue
        lock_errors, lock_evidence = idf_lock.validate_lock(
            lock_path,
            expected_target=realization["target"],
            expected_idf_version=lane["version"],
            expected_wamr_version=lane["wamr_version"],
        )
        if lock_errors:
            errors.extend(f"{realization_id}: {error}" for error in lock_errors)
        else:
            lock_evidence["realization"] = realization_id
            lock_evidence["relative_path"] = realization["dependency_lock"]
            evidence[realization_id] = lock_evidence

    if evidence:
        component_hashes = {item["wamr_component_hash"] for item in evidence.values()}
        manifest_hashes = {item["manifest_hash"] for item in evidence.values()}
        if len(component_hashes) != 1:
            errors.append("attempted locks resolve different WAMR component hashes")
        if len(manifest_hashes) != 1:
            errors.append("attempted locks resolve different manifest hashes")
    return errors, evidence


def summary(
    matrix: dict[str, Any], locks: dict[str, dict[str, Any]] | None = None
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "PASS",
        "lane_count": len(matrix["lanes"]),
        "realization_count": len(matrix["realizations"]),
        "deferred_count": len(matrix["deferred"]),
        "excluded_count": len(matrix["excluded"]),
        "inventory_count": len(matrix["realizations"]) + len(matrix["deferred"]) + len(matrix["excluded"]),
        "resolved_realization_count": len(matrix["realizations"]),
    }
    if locks is not None:
        report["lock_count"] = len(locks)
        report["locks"] = locks
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument(
        "--check-locks",
        action="store_true",
        help="Require and validate every attempted realization's committed dependency lock.",
    )
    args = parser.parse_args(argv)

    try:
        matrix = load_matrix(args.matrix)
    except MatrixContractError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    errors = validate_matrix(matrix, args.matrix)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    locks = None
    if args.check_locks:
        lock_errors, locks = validate_locks(matrix, args.matrix)
        if lock_errors:
            for error in lock_errors:
                print(f"ERROR: {error}", file=sys.stderr)
            return 1

    print(json.dumps(summary(matrix, locks), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
