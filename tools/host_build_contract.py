#!/usr/bin/env python3
"""HP2 board/profile/intent/plan/lock/fingerprint contract authority.

This module is deliberately dependency-free.  It resolves only the checked-in
catalog and already-resolved ESP-IDF component locks; it never contacts a
registry or treats an ambient toolchain as authority.
"""
from __future__ import annotations

import hashlib
import json
import re
import binascii
import struct
from pathlib import Path, PurePosixPath
from typing import Any, Optional

try:
    from tools import idf_lock
except ModuleNotFoundError:  # Direct execution from tools/.
    import idf_lock  # type: ignore[no-redef]


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "firmware/host-build-catalog.json"

CATALOG_SCHEMA = "pulse.esp32.host-build-catalog.v1"
BOARD_SCHEMA = "pulse.esp32.board-identity.v1"
PROFILE_SCHEMA = "pulse.esp32.host-profile.v1"
INTENT_SCHEMA = "pulse.esp32.target-intent.v1"
PLAN_SCHEMA = "pulse.esp32.host-build-plan.v1"
LOCK_SCHEMA = "pulse.esp32.host-build-lock.v1"
FINGERPRINT_SCHEMA = "pulse.esp32.running-host-fingerprint.v1"
HP41_MODEL_RELATIVE = "specs/PULSE-ESP32-010-protected-administration-core.json"
HP42_MODEL_RELATIVE = "specs/PULSE-ESP32-011-exclusive-update-transaction.json"
HP43_MODEL_RELATIVE = "specs/PULSE-ESP32-012-host-only-recovery.json"
HP44_MODEL_RELATIVE = "specs/PULSE-ESP32-013-administration-adversarial-seal.json"
HP5_MODEL_RELATIVE = "specs/PULSE-ESP32-014-host-network-mediator.json"
HP55_MODEL_RELATIVE = "specs/PULSE-ESP32-015-network-administration-physical-seal.json"

HP2_LOCKED_ABI_INPUT = {
    "path": "firmware/components/wdc_abi/include/wdc_abi.h",
    "sha256": "7e0c987fb67749d39a39e3edc1363b1bcb9694c8e8a482dfd8006b466671f879",
    "size": 14239,
}
HP5_HOST_NATIVE_ABI_INPUT = {
    "path": "firmware/components/wdc_abi/include/wdc_abi.h",
    "sha256": "104753f70693b895afcf33e5a897f09ffec8f63988414c1784f56b8a7fa26f1b",
    "size": 14310,
}

# HP2 locks remain the exact realized-host authorities. HP4.1 through HP4.4 are
# deliberately host-native-only, so lock replay may verify their exact source
# successor chain without rewriting the lock or claiming a target realization.
HP40_LOCKED_SOURCE_TREES = {
    "firmware/components": {
        "path": "firmware/components",
        "sha256": "acce751f8bd425c60f1647405e959c680716dffc3033c7352e7103a84df32ef3",
        "file_count": 109,
        "size": 611340,
    },
    "firmware/main": {
        "path": "firmware/main",
        "sha256": "60a2baee6aec7211a511b0bcd165d5503eebbd960cbee1da50749099450165d6",
        "file_count": 4,
        "size": 35480,
    },
}
HP41_HOST_NATIVE_SOURCE_TREES = {
    "firmware/components": {
        "path": "firmware/components",
        "sha256": "0ab8ca010389d4529116ff74c55a9b043bfaae097126575763ef39cb55bc70e1",
        "file_count": 114,
        "size": 679945,
    },
    "firmware/main": {
        "path": "firmware/main",
        "sha256": "f3f1ec3682b3ba8d7fcafceb8004406f52d23019007721612a88ea260c30f0bc",
        "file_count": 4,
        "size": 35548,
    },
}
HP42_HOST_NATIVE_SOURCE_TREES = {
    "firmware/components": {
        "path": "firmware/components",
        "sha256": "d827697d60c06119a9fe36ddfdf3e16060ed87a2a616b3657374a8bbfbdbfeca",
        "file_count": 116,
        "size": 725129,
    },
    "firmware/main": {
        "path": "firmware/main",
        "sha256": "9cd729b440f96738f4d336e917eee9a98a11d1d5cae49573a531714e34ca63ee",
        "file_count": 4,
        "size": 35620,
    },
}
HP43_HOST_NATIVE_SOURCE_TREES = {
    "firmware/components": {
        "path": "firmware/components",
        "sha256": "9a5075af3f34b5201d232d610c63bd2b0d7a72ab5d05e476d7ea2ec997e3f295",
        "file_count": 118,
        "size": 754997,
    },
    "firmware/main": {
        "path": "firmware/main",
        "sha256": "53581064e5442d9d8f56f63ea1acf91ad1f3d925d7d55bb26980feec7376123e",
        "file_count": 4,
        "size": 35696,
    },
}
HP44_HOST_NATIVE_SOURCE_TREES = {
    "firmware/components": {
        "path": "firmware/components",
        "sha256": "aacd2b504b9089a3427be296de6bee09dd8150e8e4fa2e19e692ebc0be9cbccb",
        "file_count": 118,
        "size": 755996,
    },
    "firmware/main": {
        "path": "firmware/main",
        "sha256": "53581064e5442d9d8f56f63ea1acf91ad1f3d925d7d55bb26980feec7376123e",
        "file_count": 4,
        "size": 35696,
    },
}
HP5_HOST_NATIVE_SOURCE_TREES = {
    "firmware/components": {
        "path": "firmware/components",
        "sha256": "170b06e600f1b7b3752b04df9da49a40f447b3bc93d67ba253653d49ebb5a50d",
        "file_count": 127,
        "size": 833288,
    },
    "firmware/main": {
        "path": "firmware/main",
        "sha256": "cc7995885e99cf4617706d6ea7c39e7c294c10ef745c1a64d21e331f2b1a001d",
        "file_count": 4,
        "size": 35761,
    },
}
HP55_TARGET_SOURCE_TREES = {
    "firmware/components": {
        "path": "firmware/components",
        "sha256": "c34a96f7d08055a54659fead1925da1ee7a776fb016c05309e9d11edb821a4a9",
        "file_count": 127,
        "size": 833724,
    },
    "firmware/main": {
        "path": "firmware/main",
        "sha256": "cc7995885e99cf4617706d6ea7c39e7c294c10ef745c1a64d21e331f2b1a001d",
        "file_count": 4,
        "size": 35761,
    },
}

HEX64 = re.compile(r"[0-9a-f]{64}")
IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9._-]{0,95}")
TARGETS = frozenset({"esp32s3", "esp32c6"})
PLACEMENTS = frozenset({"portable", "target-optimized"})
CAPABILITY_BITS = {
    "pulse.wasm-application.v1": 1 << 0,
    "pulse.event-effect.v1": 1 << 1,
    "pulse.native-refinement.v1": 1 << 2,
    "pulse.application-slots.v1": 1 << 3,
}
IGNORED_TREE_PARTS = frozenset(
    {"build", "managed_components", "__pycache__", ".pytest_cache"}
)

CATALOG_FIELDS = frozenset(
    {
        "schema",
        "lane",
        "components",
        "source_roots",
        "derived_source_exclusions",
        "realizations",
    }
)
LANE_FIELDS = frozenset(
    {"id", "version", "source_commit", "platform", "container_image"}
)
COMPONENT_FIELDS = frozenset({"name", "version", "component_hash"})
REALIZATION_FIELDS = frozenset(
    {
        "board",
        "host_profile",
        "target",
        "sdkconfig_defaults",
        "partitions",
        "dependency_lock",
        "build_lock",
        "fingerprint",
    }
)
BOARD_FIELDS = frozenset(
    {
        "schema",
        "board_id",
        "manufacturer",
        "model",
        "module",
        "target",
        "isa",
        "flash_bytes",
        "psram_bytes",
        "psram_mode",
        "identity_authority",
        "hp0_observation",
    }
)
PROFILE_FIELDS = frozenset(
    {
        "schema",
        "profile_id",
        "target",
        "host_abi",
        "capabilities",
        "control_resource_profile",
        "resource_authority",
        "abi_authority",
        "native_extension_abi_sha256",
        "resources",
    }
)
RESOURCE_FIELDS = frozenset(
    {
        "fixed_control_reserve_bytes",
        "exclusive_update_working_bytes",
        "largest_block_floor_bytes",
        "maximum_application_internal_bytes",
        "maximum_transition_scratch_bytes",
        "maximum_target_optimized_bytes",
        "target_optimized_floor_bytes",
    }
)
INTENT_FIELDS = frozenset(
    {
        "schema",
        "intent_id",
        "application_id",
        "allowed_boards",
        "allowed_targets",
        "host_abi",
        "required_capabilities",
        "placement",
        "resources",
    }
)
INTENT_RESOURCE_FIELDS = frozenset(
    {
        "guest_linear_memory_bytes",
        "runtime_stack_bytes",
        "network_working_bytes",
        "capability_working_bytes",
        "native_refinement_bytes",
        "transition_scratch_bytes",
        "largest_application_allocation_bytes",
        "target_optimization_bytes",
    }
)


class HostBuildContractError(ValueError):
    """Raised whenever HP2 input is ambiguous, incompatible, or changed."""


class DuplicateKeyError(ValueError):
    """Raised for duplicate JSON object keys."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError("duplicate JSON key %r" % key)
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except OSError as exc:
        raise HostBuildContractError("cannot read %s: %s" % (path, exc)) from exc
    except (json.JSONDecodeError, DuplicateKeyError) as exc:
        raise HostBuildContractError("invalid JSON in %s: %s" % (path, exc)) from exc
    if not isinstance(value, dict):
        raise HostBuildContractError("JSON root must be an object: %s" % path)
    return value


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_new(path: Path, value: dict[str, Any]) -> None:
    destination = path.expanduser().resolve()
    if destination.exists():
        raise HostBuildContractError("output already exists: %s" % destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _exact(value: Any, fields: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise HostBuildContractError("%s must be an object" % label)
    missing = sorted(fields - set(value))
    unknown = sorted(set(value) - fields)
    if missing or unknown:
        pieces = []
        if missing:
            pieces.append("missing=" + ",".join(missing))
        if unknown:
            pieces.append("unknown=" + ",".join(unknown))
        raise HostBuildContractError("%s fields are not exact: %s" % (label, "; ".join(pieces)))
    return value


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or IDENTIFIER.fullmatch(value) is None:
        raise HostBuildContractError("%s is not a normalized identifier" % label)
    return value


def _hex64(value: Any, label: str) -> str:
    if not isinstance(value, str) or HEX64.fullmatch(value) is None:
        raise HostBuildContractError("%s must be lowercase SHA-256" % label)
    return value


def _positive(value: Any, label: str, allow_zero: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HostBuildContractError("%s must be an integer" % label)
    minimum = 0 if allow_zero else 1
    if value < minimum or value > 0xFFFFFFFF:
        raise HostBuildContractError("%s is outside the uint32 boundary" % label)
    return value


def _sorted_unique_strings(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise HostBuildContractError("%s must be a non-empty array" % label)
    if any(not isinstance(item, str) or not item for item in value):
        raise HostBuildContractError("%s entries must be non-empty strings" % label)
    if value != sorted(set(value)):
        raise HostBuildContractError("%s must be sorted and unique" % label)
    return value


def repo_path(root: Path, relative: Any, label: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise HostBuildContractError("%s must be a normalized repository path" % label)
    pure = PurePosixPath(relative)
    if pure.is_absolute() or str(pure) != relative or any(
        part in {"", ".", ".."} for part in pure.parts
    ):
        raise HostBuildContractError("%s must be a normalized repository path" % label)
    candidate = (root / Path(*pure.parts)).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise HostBuildContractError("%s escapes the repository" % label) from exc
    return candidate


def file_evidence(root: Path, relative: str, label: str) -> dict[str, Any]:
    path = repo_path(root, relative, label)
    if not path.is_file() or path.is_symlink():
        raise HostBuildContractError("%s is missing or not a regular file" % label)
    return {
        "path": relative,
        "sha256": sha256_file(path),
        "size": path.stat().st_size,
    }


def tree_evidence(
    root: Path, relative: str, exclusions: list[str]
) -> dict[str, Any]:
    directory = repo_path(root, relative, "source root")
    if not directory.is_dir() or directory.is_symlink():
        raise HostBuildContractError("source root is missing: %s" % relative)
    exclusion_set = set(exclusions)
    digest = hashlib.sha256()
    count = 0
    total = 0
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise HostBuildContractError("source root contains a symlink: %s" % path)
        if not path.is_file():
            continue
        repository_relative = path.relative_to(root).as_posix()
        if repository_relative in exclusion_set:
            continue
        if any(part in IGNORED_TREE_PARTS for part in path.relative_to(directory).parts):
            continue
        size = path.stat().st_size
        digest.update(repository_relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\n")
        count += 1
        total += size
    if count == 0:
        raise HostBuildContractError("source root is empty: %s" % relative)
    return {
        "path": relative,
        "sha256": digest.hexdigest(),
        "file_count": count,
        "size": total,
    }


def _is_hp4_host_native_successor(
    root: Path,
    expected: dict[str, Any],
    actual: dict[str, Any],
) -> bool:
    """Accept only a sealed HP4 host-native delta while replaying HP2 history."""

    relative = expected.get("path")
    if (
        relative not in HP40_LOCKED_SOURCE_TREES
        or expected != HP40_LOCKED_SOURCE_TREES[relative]
    ):
        return False
    if actual == HP41_HOST_NATIVE_SOURCE_TREES[relative]:
        expected_successor = "HP4.1"
    elif actual == HP42_HOST_NATIVE_SOURCE_TREES[relative]:
        expected_successor = "HP4.2"
    elif actual == HP43_HOST_NATIVE_SOURCE_TREES[relative]:
        expected_successor = "HP4.3"
    elif actual == HP44_HOST_NATIVE_SOURCE_TREES[relative]:
        expected_successor = "HP4.4"
    elif actual == HP5_HOST_NATIVE_SOURCE_TREES[relative]:
        expected_successor = "HP5"
    elif actual == HP55_TARGET_SOURCE_TREES[relative]:
        expected_successor = "HP5.5"
    else:
        return False

    model_path = repo_path(root, HP41_MODEL_RELATIVE, "HP4.1 model")
    if not model_path.is_file() or model_path.is_symlink():
        return False
    try:
        model = json.loads(model_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    history = model.get("source_history", {})
    hp41_valid = bool(
        model.get("schema")
        == "pulse.esp32.hp4_1-protected-administration-core.v1"
        and model.get("pass") == "HP4.1"
        and model.get("status") == "IMPLEMENTED"
        and history.get("hp4_0_firmware_sha256")
        == "c7b4341e00911b3b26b4d9b8abcd831af4abdf7754503a79298e86aa2b9d2c31"
        and history.get("hp4_0_firmware_file_count") == 141
        and history.get("current_firmware_sha256")
        == "4f7b56a99adfedfa57c1d5179ad5ca03e6f57dd258a73fa3a6f71f747973253c"
        and history.get("current_firmware_file_count") == 146
    )
    if not hp41_valid or expected_successor == "HP4.1":
        return hp41_valid

    model_path = repo_path(root, HP42_MODEL_RELATIVE, "HP4.2 model")
    if not model_path.is_file() or model_path.is_symlink():
        return False
    try:
        model = json.loads(model_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    history = model.get("source_history", {})
    hp42_valid = bool(
        model.get("schema") == "pulse.esp32.hp4_2-exclusive-update-transaction.v1"
        and model.get("pass") == "HP4.2"
        and model.get("status") == "IMPLEMENTED"
        and history.get("hp4_1_firmware_sha256")
        == "4f7b56a99adfedfa57c1d5179ad5ca03e6f57dd258a73fa3a6f71f747973253c"
        and history.get("hp4_1_firmware_file_count") == 146
        and history.get("current_firmware_sha256")
        == "77f4d2044776c6828e443486ee21199f95b4e1f34ae704c7323e901d51602eca"
        and history.get("current_firmware_file_count") == 148
    )
    if not hp42_valid or expected_successor == "HP4.2":
        return hp42_valid

    model_path = repo_path(root, HP43_MODEL_RELATIVE, "HP4.3 model")
    if not model_path.is_file() or model_path.is_symlink():
        return False
    try:
        model = json.loads(model_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    history = model.get("source_history", {})
    hp43_valid = bool(
        model.get("schema") == "pulse.esp32.hp4_3-host-only-recovery.v1"
        and model.get("pass") == "HP4.3"
        and model.get("status") == "IMPLEMENTED"
        and history.get("hp4_2_firmware_sha256")
        == "77f4d2044776c6828e443486ee21199f95b4e1f34ae704c7323e901d51602eca"
        and history.get("hp4_2_firmware_file_count") == 148
        and history.get("current_firmware_sha256")
        == "d36978214d8e1d892961e7239facafa49eb1ed4150843dd1eeb23dec5d8ceb5f"
        and history.get("current_firmware_file_count") == 150
    )
    if not hp43_valid or expected_successor == "HP4.3":
        return hp43_valid

    model_path = repo_path(root, HP44_MODEL_RELATIVE, "HP4.4 model")
    if not model_path.is_file() or model_path.is_symlink():
        return False
    try:
        model = json.loads(model_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    history = model.get("source_history", {})
    hp44_valid = bool(
        model.get("schema")
        == "pulse.esp32.hp4_4-administration-adversarial-seal.v1"
        and model.get("pass") == "HP4.4"
        and model.get("status") == "SEALED"
        and history.get("hp4_3_firmware_sha256")
        == "d36978214d8e1d892961e7239facafa49eb1ed4150843dd1eeb23dec5d8ceb5f"
        and history.get("hp4_3_firmware_file_count") == 150
        and history.get("current_firmware_sha256")
        == "ff9f571860eda289cc276c6418f887b0af42552380c50f4038b5163ea929a386"
        and history.get("current_firmware_file_count") == 150
    )
    if not hp44_valid or expected_successor == "HP4.4":
        return hp44_valid

    model_path = repo_path(root, HP5_MODEL_RELATIVE, "HP5 model")
    if not model_path.is_file() or model_path.is_symlink():
        return False
    try:
        model = json.loads(model_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    history = model.get("source_history", {})
    hp5_valid = bool(
        model.get("schema") == "pulse.esp32.hp5-host-network-mediator.v1"
        and model.get("pass") == "HP5"
        and model.get("status") == "QUALIFIED"
        and history.get("hp4_4_firmware_sha256")
        == "ff9f571860eda289cc276c6418f887b0af42552380c50f4038b5163ea929a386"
        and history.get("hp4_4_firmware_file_count") == 150
        and history.get("current_firmware_sha256")
        == "2e94b65a03a0612d4e770dc0f9b624dab874a75bf334bbd5173023427b7076a5"
        and history.get("current_firmware_file_count") == 159
    )
    if not hp5_valid or expected_successor == "HP5":
        return hp5_valid

    model_path = repo_path(root, HP55_MODEL_RELATIVE, "HP5.5 model")
    if not model_path.is_file() or model_path.is_symlink():
        return False
    try:
        model = json.loads(model_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    history = model.get("source_history", {})
    return bool(
        model.get("schema")
        == "pulse.esp32.hp5_5-network-administration-physical-seal.v1"
        and model.get("pass") == "HP5.5"
        and model.get("status") == "READY_FOR_PHYSICAL_EXECUTION"
        and model.get("aggregate") == "HARDWARE_PENDING"
        and history.get("hp5_firmware_sha256")
        == "2e94b65a03a0612d4e770dc0f9b624dab874a75bf334bbd5173023427b7076a5"
        and history.get("hp5_firmware_file_count") == 159
        and history.get("current_firmware_sha256")
        == "d60e2669cd3b2dd5869e2305c92e39913b270ba9d54844d3a34d614681c5a98a"
        and history.get("current_firmware_file_count") == 168
        and history.get("current_components_sha256")
        == HP55_TARGET_SOURCE_TREES["firmware/components"]["sha256"]
        and history.get("current_components_file_count")
        == HP55_TARGET_SOURCE_TREES["firmware/components"]["file_count"]
        and history.get("current_main_sha256")
        == HP55_TARGET_SOURCE_TREES["firmware/main"]["sha256"]
        and history.get("current_main_file_count")
        == HP55_TARGET_SOURCE_TREES["firmware/main"]["file_count"]
    )


def _is_hp5_host_native_abi_successor(
    root: Path,
    expected: dict[str, Any],
    actual: dict[str, Any],
) -> bool:
    """Allow only HP5's exact additive ABI source in an unrebuilt HP2 lock.

    HP5 is deliberately host-native-only: it adds one request event and one
    paired response opcode, but does not claim a regenerated target lock or
    running fingerprint.  The old lock remains replayable only while both the
    exact HP5 source tree and its model are present.  HP5.5 must create new
    target evidence rather than silently upgrading this exception.
    """

    if (
        expected.get("path") != HP2_LOCKED_ABI_INPUT["path"]
        or expected.get("sha256") != HP2_LOCKED_ABI_INPUT["sha256"]
        or ("size" in expected and expected.get("size") != HP2_LOCKED_ABI_INPUT["size"])
        or actual != HP5_HOST_NATIVE_ABI_INPUT
    ):
        return False
    exclusions = [
        "firmware/components/wdc_host_identity/wdc_host_fingerprint_generated.c"
    ]
    component_tree = tree_evidence(root, "firmware/components", exclusions)
    main_tree = tree_evidence(root, "firmware/main", exclusions)
    return _is_hp4_host_native_successor(
        root, HP40_LOCKED_SOURCE_TREES["firmware/components"], component_tree
    ) and _is_hp4_host_native_successor(
        root, HP40_LOCKED_SOURCE_TREES["firmware/main"], main_tree
    )


def _validate_authority(root: Path, value: Any, label: str) -> dict[str, Any]:
    authority = _exact(value, frozenset({"path", "sha256"}), label)
    expected = file_evidence(root, authority["path"], label + ".path")
    if authority["sha256"] != expected["sha256"] and not (
        label == "ABI authority"
        and _is_hp5_host_native_abi_successor(root, authority, expected)
    ):
        raise HostBuildContractError("%s hash no longer matches its authority" % label)
    _hex64(authority["sha256"], label + ".sha256")
    return authority


def validate_board(board: dict[str, Any], expected_id: Optional[str] = None) -> dict[str, Any]:
    _exact(board, BOARD_FIELDS, "board")
    if board.get("schema") != BOARD_SCHEMA:
        raise HostBuildContractError("unsupported board schema")
    board_id = _identifier(board.get("board_id"), "board.board_id")
    if expected_id is not None and board_id != expected_id:
        raise HostBuildContractError("board identity does not match catalog key")
    for field in ("manufacturer", "model", "module", "isa", "psram_mode"):
        if not isinstance(board.get(field), str) or not board[field]:
            raise HostBuildContractError("board.%s must be a non-empty string" % field)
    if board.get("target") not in TARGETS:
        raise HostBuildContractError("board target is unsupported by HP2")
    _positive(board.get("flash_bytes"), "board.flash_bytes")
    psram = _positive(board.get("psram_bytes"), "board.psram_bytes", allow_zero=True)
    if (psram == 0) != (board.get("psram_mode") == "none"):
        raise HostBuildContractError("board PSRAM size and mode disagree")
    if board.get("identity_authority") != "operator_attested_named_board":
        raise HostBuildContractError("board identity authority is not the HP0 boundary")
    if board.get("hp0_observation") != "NAMED_BOARD_OBSERVED":
        raise HostBuildContractError("board lacks the accepted HP0 observation")
    return board


def validate_profile(
    root: Path, profile: dict[str, Any], expected_target: Optional[str] = None
) -> dict[str, Any]:
    _exact(profile, PROFILE_FIELDS, "host profile")
    if profile.get("schema") != PROFILE_SCHEMA:
        raise HostBuildContractError("unsupported host-profile schema")
    _identifier(profile.get("profile_id"), "host profile.profile_id")
    target = profile.get("target")
    if target not in TARGETS or (expected_target is not None and target != expected_target):
        raise HostBuildContractError("host profile target mismatch")
    abi = _exact(profile.get("host_abi"), frozenset({"major", "minor"}), "host profile.host_abi")
    if abi != {"major": 1, "minor": 0}:
        raise HostBuildContractError("host profile ABI must be the current 1.0 contract")
    capabilities = _sorted_unique_strings(profile.get("capabilities"), "host profile.capabilities")
    if any(item not in CAPABILITY_BITS for item in capabilities):
        raise HostBuildContractError("host profile contains an unknown capability")
    _identifier(
        profile.get("control_resource_profile"),
        "host profile.control_resource_profile",
    )
    _validate_authority(root, profile.get("resource_authority"), "resource authority")
    _validate_authority(root, profile.get("abi_authority"), "ABI authority")
    _hex64(profile.get("native_extension_abi_sha256"), "native extension ABI")
    resources = _exact(profile.get("resources"), RESOURCE_FIELDS, "host profile.resources")
    for field in RESOURCE_FIELDS:
        _positive(
            resources.get(field),
            "host profile.resources.%s" % field,
            allow_zero=field in {"maximum_target_optimized_bytes", "target_optimized_floor_bytes"},
        )
    external_max = resources["maximum_target_optimized_bytes"]
    external_floor = resources["target_optimized_floor_bytes"]
    if (external_max == 0) != (external_floor == 0):
        raise HostBuildContractError("target-optimized maximum and floor must both be zero or non-zero")
    if target == "esp32c6" and external_max != 0:
        raise HostBuildContractError("C6 minimum profile cannot depend on target-optimized memory")
    return profile


def validate_catalog(
    catalog: dict[str, Any], root: Path = ROOT
) -> dict[str, dict[str, Any]]:
    _exact(catalog, CATALOG_FIELDS, "catalog")
    if catalog.get("schema") != CATALOG_SCHEMA:
        raise HostBuildContractError("unsupported host-build catalog schema")
    lane = _exact(catalog.get("lane"), LANE_FIELDS, "catalog.lane")
    expected_lane = {
        "id": "idf-5.4.4",
        "version": "v5.4.4",
        "source_commit": "296b6eab9445fd720e71aecab961e2d3fbca9944",
        "platform": "linux/amd64",
        "container_image": "espressif/idf@sha256:8d1846f61ff8db00ba6530501f90bf43604d923072a616c806fef8e85a88ed82",
    }
    if lane != expected_lane:
        raise HostBuildContractError("catalog lane is not the exact supported environment")

    components = catalog.get("components")
    if not isinstance(components, list) or len(components) != 3:
        raise HostBuildContractError("catalog must contain the exact three-component graph")
    names = []
    for index, component in enumerate(components):
        item = _exact(component, COMPONENT_FIELDS, "catalog.components[%d]" % index)
        names.append(item.get("name"))
        if not isinstance(item.get("version"), str) or not item["version"]:
            raise HostBuildContractError("component version is empty")
        _hex64(item.get("component_hash"), "component hash")
    if names != sorted(set(names)):
        raise HostBuildContractError("catalog components must be sorted and unique")

    source_roots = _sorted_unique_strings(catalog.get("source_roots"), "catalog.source_roots")
    if source_roots != ["firmware/components", "firmware/main", "native-sdk"]:
        raise HostBuildContractError("catalog source roots are not the HP2 build boundary")
    exclusions = catalog.get("derived_source_exclusions")
    if exclusions != ["firmware/components/wdc_host_identity/wdc_host_fingerprint_generated.c"]:
        raise HostBuildContractError("catalog derived-source exclusion is not exact")
    for exclusion in exclusions:
        repo_path(root, exclusion, "catalog exclusion")

    realizations = catalog.get("realizations")
    expected_ids = {
        "aitrip-esp32s3-devkitc-1-n8r2",
        "seeed-xiao-esp32c6-4m",
    }
    if not isinstance(realizations, dict) or set(realizations) != expected_ids:
        raise HostBuildContractError("catalog realization inventory is not exact")
    resolved: dict[str, dict[str, Any]] = {}
    for board_id in sorted(realizations):
        entry = _exact(realizations[board_id], REALIZATION_FIELDS, "catalog realization")
        if entry.get("target") not in TARGETS:
            raise HostBuildContractError("catalog realization target is unsupported")
        board_path = repo_path(root, entry.get("board"), "catalog board")
        profile_path = repo_path(root, entry.get("host_profile"), "catalog host profile")
        board = validate_board(load_json(board_path), board_id)
        profile = validate_profile(root, load_json(profile_path), entry["target"])
        if board["target"] != entry["target"] or profile["target"] != entry["target"]:
            raise HostBuildContractError("board/profile/realization target split is incoherent")
        if board["psram_bytes"] == 0 and profile["resources"]["maximum_target_optimized_bytes"] != 0:
            raise HostBuildContractError("no-PSRAM board selected a target-optimized profile")
        for field in ("sdkconfig_defaults", "partitions", "dependency_lock"):
            path = repo_path(root, entry.get(field), "catalog realization.%s" % field)
            if not path.is_file():
                raise HostBuildContractError("catalog realization input is missing: %s" % field)
        for field in ("build_lock", "fingerprint"):
            repo_path(root, entry.get(field), "catalog realization.%s" % field)
        resolved[board_id] = {"entry": entry, "board": board, "profile": profile}
    return resolved


def validate_intent(intent: dict[str, Any]) -> dict[str, Any]:
    _exact(intent, INTENT_FIELDS, "target intent")
    if intent.get("schema") != INTENT_SCHEMA:
        raise HostBuildContractError("unsupported target-intent schema")
    _identifier(intent.get("intent_id"), "target intent.intent_id")
    _identifier(intent.get("application_id"), "target intent.application_id")
    boards = _sorted_unique_strings(intent.get("allowed_boards"), "target intent.allowed_boards")
    for board in boards:
        _identifier(board, "target intent allowed board")
    targets = _sorted_unique_strings(intent.get("allowed_targets"), "target intent.allowed_targets")
    if any(target not in TARGETS for target in targets):
        raise HostBuildContractError("target intent contains an unsupported target")
    abi = _exact(
        intent.get("host_abi"),
        frozenset({"major", "min_minor", "max_minor"}),
        "target intent.host_abi",
    )
    for field in ("major", "min_minor", "max_minor"):
        _positive(abi.get(field), "target intent.host_abi.%s" % field, allow_zero=field != "major")
    if abi["min_minor"] > abi["max_minor"]:
        raise HostBuildContractError("target intent ABI range is reversed")
    capabilities = _sorted_unique_strings(
        intent.get("required_capabilities"), "target intent.required_capabilities"
    )
    if any(capability not in CAPABILITY_BITS for capability in capabilities):
        raise HostBuildContractError("target intent contains an unknown capability")
    placement = intent.get("placement")
    if placement not in PLACEMENTS:
        raise HostBuildContractError("target intent placement is unsupported")
    resources = _exact(intent.get("resources"), INTENT_RESOURCE_FIELDS, "target intent.resources")
    for field in INTENT_RESOURCE_FIELDS:
        _positive(
            resources.get(field),
            "target intent.resources.%s" % field,
            allow_zero=field in {"native_refinement_bytes", "target_optimization_bytes"},
        )
    application_internal = sum(
        resources[field]
        for field in (
            "guest_linear_memory_bytes",
            "runtime_stack_bytes",
            "network_working_bytes",
            "capability_working_bytes",
            "native_refinement_bytes",
        )
    )
    if application_internal > 0xFFFFFFFF:
        raise HostBuildContractError("target intent application memory overflows uint32")
    if resources["largest_application_allocation_bytes"] > application_internal:
        raise HostBuildContractError("target intent largest allocation exceeds its working set")
    if placement == "portable" and resources["target_optimization_bytes"] != 0:
        raise HostBuildContractError("portable target intent cannot require optimized placement")
    return intent


def capability_mask(capabilities: list[str]) -> int:
    mask = 0
    for capability in capabilities:
        mask |= CAPABILITY_BITS[capability]
    return mask


def compatibility_surface(board: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "format_version": 1,
        "board_id": board["board_id"],
        "target": board["target"],
        "flash_bytes": board["flash_bytes"],
        "psram_bytes": board["psram_bytes"],
        "host_profile_id": profile["profile_id"],
        "control_resource_profile": profile["control_resource_profile"],
        "host_abi": profile["host_abi"],
        "capabilities": profile["capabilities"],
        "capability_mask": capability_mask(profile["capabilities"]),
        "resources": profile["resources"],
        "resource_authority_sha256": profile["resource_authority"]["sha256"],
        "abi_authority_sha256": profile["abi_authority"]["sha256"],
        "native_extension_abi_sha256": profile["native_extension_abi_sha256"],
    }


def validate_compatibility_surface(surface: dict[str, Any]) -> dict[str, Any]:
    fields = frozenset(
        {
            "format_version",
            "board_id",
            "target",
            "flash_bytes",
            "psram_bytes",
            "host_profile_id",
            "control_resource_profile",
            "host_abi",
            "capabilities",
            "capability_mask",
            "resources",
            "resource_authority_sha256",
            "abi_authority_sha256",
            "native_extension_abi_sha256",
        }
    )
    _exact(surface, fields, "compatibility surface")
    if surface.get("format_version") != 1:
        raise HostBuildContractError("unsupported compatibility-surface version")
    _identifier(surface.get("board_id"), "compatibility surface.board_id")
    _identifier(surface.get("host_profile_id"), "compatibility surface.host_profile_id")
    _identifier(
        surface.get("control_resource_profile"),
        "compatibility surface.control_resource_profile",
    )
    if surface.get("target") not in TARGETS:
        raise HostBuildContractError("compatibility surface target is unsupported")
    _positive(surface.get("flash_bytes"), "compatibility surface.flash_bytes")
    _positive(
        surface.get("psram_bytes"),
        "compatibility surface.psram_bytes",
        allow_zero=True,
    )
    abi = _exact(
        surface.get("host_abi"), frozenset({"major", "minor"}), "compatibility surface.host_abi"
    )
    _positive(abi.get("major"), "compatibility surface ABI major")
    _positive(abi.get("minor"), "compatibility surface ABI minor", allow_zero=True)
    capabilities = _sorted_unique_strings(
        surface.get("capabilities"), "compatibility surface.capabilities"
    )
    if any(item not in CAPABILITY_BITS for item in capabilities):
        raise HostBuildContractError("compatibility surface capability is unknown")
    if surface.get("capability_mask") != capability_mask(capabilities):
        raise HostBuildContractError("compatibility surface capability mask disagrees")
    resources = _exact(surface.get("resources"), RESOURCE_FIELDS, "compatibility surface.resources")
    for field in RESOURCE_FIELDS:
        _positive(
            resources.get(field),
            "compatibility surface.resources.%s" % field,
            allow_zero=field in {"maximum_target_optimized_bytes", "target_optimized_floor_bytes"},
        )
    for field in (
        "resource_authority_sha256",
        "abi_authority_sha256",
        "native_extension_abi_sha256",
    ):
        _hex64(surface.get(field), "compatibility surface.%s" % field)
    if surface["target"] == "esp32c6" and (
        surface["psram_bytes"] != 0
        or resources["maximum_target_optimized_bytes"] != 0
        or resources["target_optimized_floor_bytes"] != 0
    ):
        raise HostBuildContractError("C6 compatibility surface is not no-PSRAM portable")
    return surface


def check_intent_against_surface(
    intent: dict[str, Any], surface: dict[str, Any]
) -> dict[str, Any]:
    validate_intent(intent)
    validate_compatibility_surface(surface)
    reasons: list[str] = []
    if surface.get("board_id") not in intent["allowed_boards"]:
        reasons.append("BOARD_NOT_ALLOWED")
    if surface.get("target") not in intent["allowed_targets"]:
        reasons.append("TARGET_NOT_ALLOWED")
    host_abi = surface.get("host_abi", {})
    wanted_abi = intent["host_abi"]
    if (
        host_abi.get("major") != wanted_abi["major"]
        or not wanted_abi["min_minor"] <= host_abi.get("minor", -1) <= wanted_abi["max_minor"]
    ):
        reasons.append("HOST_ABI_INCOMPATIBLE")
    available = set(surface.get("capabilities", []))
    if not set(intent["required_capabilities"]).issubset(available):
        reasons.append("CAPABILITY_UNAVAILABLE")
    requested = intent["resources"]
    limits = surface.get("resources", {})
    internal = sum(
        requested[field]
        for field in (
            "guest_linear_memory_bytes",
            "runtime_stack_bytes",
            "network_working_bytes",
            "capability_working_bytes",
            "native_refinement_bytes",
        )
    )
    if internal > limits.get("maximum_application_internal_bytes", -1):
        reasons.append("APPLICATION_INTERNAL_BUDGET")
    if requested["transition_scratch_bytes"] > limits.get("maximum_transition_scratch_bytes", -1):
        reasons.append("TRANSITION_BUDGET")
    optimized = requested["target_optimization_bytes"]
    if optimized > limits.get("maximum_target_optimized_bytes", -1):
        reasons.append("TARGET_OPTIMIZATION_UNAVAILABLE")
    if intent["placement"] == "portable" and optimized != 0:
        reasons.append("PORTABILITY_VIOLATION")
    return {
        "status": "COMPATIBLE" if not reasons else "INCOMPATIBLE",
        "reasons": reasons,
        "application_internal_bytes": internal,
        "target_optimization_bytes": optimized,
        "prelaunch_heap_admission": "REQUIRED" if not reasons else "NOT_REACHED",
    }


def _artifact_digest(value: dict[str, Any], digest_field: str) -> str:
    payload = dict(value)
    observed = payload.pop(digest_field, None)
    expected = canonical_sha256(payload)
    if observed != expected:
        raise HostBuildContractError("%s does not match canonical artifact bytes" % digest_field)
    return expected


def make_plan(
    intent: dict[str, Any],
    board_id: str,
    catalog: dict[str, Any],
    root: Path = ROOT,
    running_fingerprint: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    validate_intent(intent)
    resolved = validate_catalog(catalog, root)
    if board_id not in resolved:
        raise HostBuildContractError("requested board is not in the supported catalog")
    selected = resolved[board_id]
    entry = selected["entry"]
    board = selected["board"]
    profile = selected["profile"]
    surface = compatibility_surface(board, profile)
    compatibility = check_intent_against_surface(intent, surface)
    if compatibility["status"] != "COMPATIBLE":
        raise HostBuildContractError(
            "target intent is incompatible with selected host profile: "
            + ",".join(compatibility["reasons"])
        )

    deployment = "SUPPORTED_LOCK_SELECTED"
    if running_fingerprint is not None:
        validate_fingerprint(running_fingerprint)
        running_check = check_intent_against_surface(
            intent, running_fingerprint["compatibility_surface"]
        )
        same_profile = (
            running_fingerprint["compatibility_surface"]["board_id"] == board_id
            and running_fingerprint["compatibility_sha256"] == canonical_sha256(surface)
        )
        deployment = (
            "APP_ONLY_DEPLOYMENT"
            if same_profile and running_check["status"] == "COMPATIBLE"
            else "HOST_BUILD_PLAN_REQUIRED"
        )

    host_plan = {
        "board_id": board_id,
        "target": entry["target"],
        "host_profile_id": profile["profile_id"],
        "lane": catalog["lane"],
        "components": catalog["components"],
        "source_roots": catalog["source_roots"],
        "derived_source_exclusions": catalog["derived_source_exclusions"],
        "sdkconfig_defaults": entry["sdkconfig_defaults"],
        "partitions": entry["partitions"],
        "dependency_lock": entry["dependency_lock"],
        "canonical_build_lock": entry["build_lock"],
        "canonical_fingerprint": entry["fingerprint"],
    }
    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "intent": {
            "intent_id": intent["intent_id"],
            "sha256": canonical_sha256(intent),
        },
        "selection": {
            "deployment": deployment,
            "compatibility": compatibility,
        },
        "host_plan": host_plan,
        "host_plan_sha256": canonical_sha256(host_plan),
        "catalog_sha256": canonical_sha256(catalog),
    }
    plan["plan_sha256"] = canonical_sha256(plan)
    return plan


def validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    expected = frozenset(
        {
            "schema",
            "intent",
            "selection",
            "host_plan",
            "host_plan_sha256",
            "catalog_sha256",
            "plan_sha256",
        }
    )
    _exact(plan, expected, "build plan")
    if plan.get("schema") != PLAN_SCHEMA:
        raise HostBuildContractError("unsupported build-plan schema")
    if plan.get("host_plan_sha256") != canonical_sha256(plan.get("host_plan")):
        raise HostBuildContractError("host-plan digest mismatch")
    _artifact_digest(plan, "plan_sha256")
    _hex64(plan.get("catalog_sha256"), "build plan catalog digest")
    return plan


def _resolved_components(
    lock_path: Path,
    target: str,
    catalog_components: list[dict[str, Any]],
    expected_idf_version: str,
) -> tuple[list[dict[str, Any]], str, str]:
    try:
        lock, raw = idf_lock.load_lock(lock_path)
    except idf_lock.LockContractError as exc:
        raise HostBuildContractError(str(exc)) from exc
    if set(lock) != {"dependencies", "direct_dependencies", "manifest_hash", "target", "version"}:
        raise HostBuildContractError("resolved component lock has unknown or missing fields")
    if lock.get("version") != "2.0.0" or lock.get("target") != target:
        raise HostBuildContractError("resolved component lock target/version mismatch")
    if lock.get("direct_dependencies") != [
        "espressif/elf_loader",
        "espressif/wasm-micro-runtime",
    ]:
        raise HostBuildContractError("resolved component lock direct graph mismatch")
    dependencies = lock.get("dependencies")
    expected_names = {item["name"] for item in catalog_components}
    if not isinstance(dependencies, dict) or set(dependencies) != expected_names | {"idf"}:
        raise HostBuildContractError("resolved component set is not exact")
    if dependencies.get("idf") != {
        "source": {"type": "idf"},
        "version": expected_idf_version.removeprefix("v"),
    }:
        raise HostBuildContractError("resolved lock IDF dependency mismatch")
    normalized = []
    for expected in catalog_components:
        actual = dependencies.get(expected["name"])
        if (
            not isinstance(actual, dict)
            or actual.get("version") != expected["version"]
            or actual.get("component_hash") != expected["component_hash"]
        ):
            raise HostBuildContractError("resolved component changed: %s" % expected["name"])
        normalized.append(dict(expected))
    return normalized, hashlib.sha256(raw).hexdigest(), lock["manifest_hash"]


def make_lock_from_plan(
    plan: dict[str, Any],
    catalog: dict[str, Any],
    root: Path = ROOT,
    *,
    catalog_relative: str = "firmware/host-build-catalog.json",
) -> dict[str, Any]:
    validate_plan(plan)
    resolved = validate_catalog(catalog, root)
    if plan["catalog_sha256"] != canonical_sha256(catalog):
        raise HostBuildContractError("build plan catalog changed before lock resolution")
    host_plan = plan["host_plan"]
    board_id = host_plan.get("board_id")
    if board_id not in resolved:
        raise HostBuildContractError("build plan board is absent from catalog")
    selected = resolved[board_id]
    entry = selected["entry"]
    board = selected["board"]
    profile = selected["profile"]
    expected_host_plan = make_plan(
        {
            "schema": INTENT_SCHEMA,
            "intent_id": "lock-resolution-placeholder",
            "application_id": "pulse.internal.lock-resolution-placeholder",
            "allowed_boards": [board_id],
            "allowed_targets": [board["target"]],
            "host_abi": {"major": 1, "min_minor": 0, "max_minor": 0},
            "required_capabilities": ["pulse.wasm-application.v1"],
            "placement": "portable",
            "resources": {
                "guest_linear_memory_bytes": 1,
                "runtime_stack_bytes": 1,
                "network_working_bytes": 1,
                "capability_working_bytes": 1,
                "native_refinement_bytes": 0,
                "transition_scratch_bytes": 1,
                "largest_application_allocation_bytes": 1,
                "target_optimization_bytes": 0,
            },
        },
        board_id,
        catalog,
        root,
    )["host_plan"]
    if host_plan != expected_host_plan:
        raise HostBuildContractError("build plan host realization is not catalog-derived")

    dependency_path = repo_path(root, entry["dependency_lock"], "dependency lock")
    components, dependency_sha, manifest_hash = _resolved_components(
        dependency_path,
        board["target"],
        catalog["components"],
        catalog["lane"]["version"],
    )
    exclusions = catalog["derived_source_exclusions"]
    trees = [
        tree_evidence(root, relative, exclusions)
        for relative in catalog["source_roots"]
    ]
    inputs = [
        file_evidence(root, catalog_relative, "catalog"),
        file_evidence(root, entry["board"], "board"),
        file_evidence(root, entry["host_profile"], "host profile"),
        file_evidence(root, entry["sdkconfig_defaults"], "sdkconfig defaults"),
        file_evidence(root, entry["partitions"], "partitions"),
        file_evidence(root, entry["dependency_lock"], "dependency lock"),
        file_evidence(root, profile["resource_authority"]["path"], "resource authority"),
        file_evidence(root, profile["abi_authority"]["path"], "ABI authority"),
        file_evidence(root, "native-sdk/c/include/pulse_extension.h", "native extension ABI"),
    ]
    inputs = sorted(inputs, key=lambda item: item["path"])
    surface = compatibility_surface(board, profile)
    return {
        "schema": LOCK_SCHEMA,
        "lock_version": 1,
        "host_plan_sha256": plan["host_plan_sha256"],
        "catalog_sha256": plan["catalog_sha256"],
        "board": {
            "board_id": board["board_id"],
            "target": board["target"],
            "flash_bytes": board["flash_bytes"],
            "psram_bytes": board["psram_bytes"],
        },
        "host_profile_id": profile["profile_id"],
        "environment": catalog["lane"],
        "resolved_components": components,
        "component_manifest_hash": manifest_hash,
        "dependency_lock_sha256": dependency_sha,
        "source_trees": trees,
        "derived_source_exclusions": exclusions,
        "inputs": inputs,
        "compatibility_surface": surface,
        "compatibility_sha256": canonical_sha256(surface),
    }


def validate_lock(lock: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    fields = frozenset(
        {
            "schema",
            "lock_version",
            "host_plan_sha256",
            "catalog_sha256",
            "board",
            "host_profile_id",
            "environment",
            "resolved_components",
            "component_manifest_hash",
            "dependency_lock_sha256",
            "source_trees",
            "derived_source_exclusions",
            "inputs",
            "compatibility_surface",
            "compatibility_sha256",
        }
    )
    _exact(lock, fields, "host build lock")
    if lock.get("schema") != LOCK_SCHEMA or lock.get("lock_version") != 1:
        raise HostBuildContractError("unsupported host-build lock")
    for field in (
        "host_plan_sha256",
        "catalog_sha256",
        "component_manifest_hash",
        "dependency_lock_sha256",
        "compatibility_sha256",
    ):
        _hex64(lock.get(field), "host build lock.%s" % field)
    if lock["compatibility_sha256"] != canonical_sha256(lock["compatibility_surface"]):
        raise HostBuildContractError("host build lock compatibility surface changed")
    validate_compatibility_surface(lock["compatibility_surface"])
    exclusions = lock.get("derived_source_exclusions")
    if exclusions != ["firmware/components/wdc_host_identity/wdc_host_fingerprint_generated.c"]:
        raise HostBuildContractError("host build lock derived exclusion changed")
    source_trees = lock.get("source_trees")
    if not isinstance(source_trees, list) or [item.get("path") for item in source_trees] != [
        "firmware/components",
        "firmware/main",
        "native-sdk",
    ]:
        raise HostBuildContractError("host build lock source-tree inventory changed")
    for expected in source_trees:
        actual = tree_evidence(root, expected["path"], exclusions)
        if actual != expected and not _is_hp4_host_native_successor(
            root, expected, actual
        ):
            raise HostBuildContractError("locked source tree changed: %s" % expected["path"])
    inputs = lock.get("inputs")
    if not isinstance(inputs, list) or not inputs:
        raise HostBuildContractError("host build lock has no input inventory")
    if [item.get("path") for item in inputs] != sorted(item.get("path") for item in inputs):
        raise HostBuildContractError("host build lock inputs are not sorted")
    for expected in inputs:
        _exact(expected, frozenset({"path", "sha256", "size"}), "locked input")
        actual = file_evidence(root, expected["path"], "locked input")
        if actual != expected and not _is_hp5_host_native_abi_successor(
            root, expected, actual
        ):
            raise HostBuildContractError("locked input changed: %s" % expected["path"])
    dependency = next(
        (item for item in inputs if item["path"].endswith("dependencies.lock")),
        None,
    )
    if dependency is None or dependency["sha256"] != lock["dependency_lock_sha256"]:
        raise HostBuildContractError("dependency-lock evidence is incoherent")
    return lock


def make_fingerprint(lock: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    validate_lock(lock, root)
    surface = lock["compatibility_surface"]
    fingerprint: dict[str, Any] = {
        "schema": FINGERPRINT_SCHEMA,
        "fingerprint_version": 1,
        "build_lock_sha256": canonical_sha256(lock),
        "compatibility_surface": surface,
        "compatibility_sha256": canonical_sha256(surface),
    }
    fingerprint["fingerprint_sha256"] = canonical_sha256(fingerprint)
    return fingerprint


def validate_fingerprint(fingerprint: dict[str, Any]) -> dict[str, Any]:
    fields = frozenset(
        {
            "schema",
            "fingerprint_version",
            "build_lock_sha256",
            "compatibility_surface",
            "compatibility_sha256",
            "fingerprint_sha256",
        }
    )
    _exact(fingerprint, fields, "running-host fingerprint")
    if fingerprint.get("schema") != FINGERPRINT_SCHEMA or fingerprint.get("fingerprint_version") != 1:
        raise HostBuildContractError("unsupported running-host fingerprint")
    for field in ("build_lock_sha256", "compatibility_sha256", "fingerprint_sha256"):
        _hex64(fingerprint.get(field), "running-host fingerprint.%s" % field)
    if fingerprint["compatibility_sha256"] != canonical_sha256(
        fingerprint["compatibility_surface"]
    ):
        raise HostBuildContractError("running-host compatibility digest mismatch")
    validate_compatibility_surface(fingerprint["compatibility_surface"])
    _artifact_digest(fingerprint, "fingerprint_sha256")
    return fingerprint


def replay_lock(
    lock: dict[str, Any], fingerprint: Optional[dict[str, Any]] = None, root: Path = ROOT
) -> dict[str, Any]:
    regenerated = make_fingerprint(lock, root)
    if fingerprint is not None:
        validate_fingerprint(fingerprint)
        if regenerated != fingerprint:
            raise HostBuildContractError("running-host fingerprint does not replay from its lock")
    return regenerated


def check_running(
    intent: dict[str, Any], fingerprint: dict[str, Any]
) -> dict[str, Any]:
    validate_fingerprint(fingerprint)
    result = check_intent_against_surface(intent, fingerprint["compatibility_surface"])
    return {
        "schema": "pulse.esp32.running-host-compatibility.v1",
        "status": "PASS" if result["status"] == "COMPATIBLE" else "FAIL",
        "deployment": (
            "APP_ONLY_DEPLOYMENT"
            if result["status"] == "COMPATIBLE"
            else "HOST_BUILD_PLAN_REQUIRED"
        ),
        "intent_sha256": canonical_sha256(intent),
        "fingerprint_sha256": fingerprint["fingerprint_sha256"],
        "compatibility": result,
        "application_code_launched": False,
    }


def _c_bytes(value: bytes, indent: str = "        ") -> str:
    rows = []
    for offset in range(0, len(value), 8):
        chunk = value[offset : offset + 8]
        rows.append(indent + ", ".join("0x%02xu" % byte for byte in chunk))
    return ",\n".join(rows)


def _render_fingerprint_initializer(
    symbol: str, fingerprint: dict[str, Any]
) -> str:
    validate_fingerprint(fingerprint)
    surface = fingerprint["compatibility_surface"]
    target_codes = {"esp32s3": 1, "esp32c6": 2}
    profile_codes = {
        "esp32s3-psram-optimization-v1": 1,
        "esp32c6-no-psram-minimum-v1": 2,
    }
    resources = surface["resources"]
    numeric = [
        target_codes[surface["target"]],
        surface["host_abi"]["major"],
        surface["host_abi"]["minor"],
        surface["capability_mask"],
        profile_codes[surface["control_resource_profile"]],
        surface["flash_bytes"],
        surface["psram_bytes"],
        resources["fixed_control_reserve_bytes"],
        resources["exclusive_update_working_bytes"],
        resources["largest_block_floor_bytes"],
        resources["maximum_application_internal_bytes"],
        resources["maximum_transition_scratch_bytes"],
        resources["maximum_target_optimized_bytes"],
        resources["target_optimized_floor_bytes"],
    ]
    board_hash = hashlib.sha256(surface["board_id"].encode("utf-8")).digest()
    profile_hash = hashlib.sha256(surface["host_profile_id"].encode("utf-8")).digest()
    lock_hash = bytes.fromhex(fingerprint["build_lock_sha256"])
    compatibility_hash = bytes.fromhex(fingerprint["compatibility_sha256"])
    packed = struct.pack(
        "<IHH14I", 0x57444346, 1, 196, *numeric
    ) + board_hash + profile_hash + lock_hash + compatibility_hash + struct.pack("<I", 0)
    if len(packed) != 196:
        raise HostBuildContractError("generated C fingerprint packing changed")
    crc = binascii.crc32(packed) & 0xFFFFFFFF
    return """static const WdcHostFingerprintV1 %s = {
    .magic = WDC_HOST_FINGERPRINT_MAGIC,
    .version = WDC_HOST_FINGERPRINT_VERSION,
    .struct_bytes = sizeof(WdcHostFingerprintV1),
    .target = %s,
    .host_abi_major = %du,
    .host_abi_minor = %du,
    .capability_mask = 0x%08xu,
    .resource_profile = %s,
    .flash_bytes = %du,
    .psram_bytes = %du,
    .fixed_control_reserve_bytes = %du,
    .exclusive_update_working_bytes = %du,
    .largest_block_floor_bytes = %du,
    .maximum_application_internal_bytes = %du,
    .maximum_transition_scratch_bytes = %du,
    .maximum_target_optimized_bytes = %du,
    .target_optimized_floor_bytes = %du,
    .board_id_sha256 = {
%s
    },
    .host_profile_id_sha256 = {
%s
    },
    .build_lock_sha256 = {
%s
    },
    .compatibility_sha256 = {
%s
    },
    .crc32 = 0x%08xu,
};""" % (
        symbol,
        "WDC_HOST_TARGET_ESP32S3" if surface["target"] == "esp32s3" else "WDC_HOST_TARGET_ESP32C6",
        surface["host_abi"]["major"],
        surface["host_abi"]["minor"],
        surface["capability_mask"],
        (
            "WDC_HOST_RESOURCE_PROFILE_S3_PSRAM_V1"
            if surface["target"] == "esp32s3"
            else "WDC_HOST_RESOURCE_PROFILE_C6_MINIMUM_V1"
        ),
        surface["flash_bytes"],
        surface["psram_bytes"],
        resources["fixed_control_reserve_bytes"],
        resources["exclusive_update_working_bytes"],
        resources["largest_block_floor_bytes"],
        resources["maximum_application_internal_bytes"],
        resources["maximum_transition_scratch_bytes"],
        resources["maximum_target_optimized_bytes"],
        resources["target_optimized_floor_bytes"],
        _c_bytes(board_hash),
        _c_bytes(profile_hash),
        _c_bytes(lock_hash),
        _c_bytes(compatibility_hash),
        crc,
    )


def render_generated_c(catalog: dict[str, Any], root: Path = ROOT) -> str:
    resolved = validate_catalog(catalog, root)
    by_target: dict[str, dict[str, Any]] = {}
    provenance = []
    for board_id in sorted(resolved):
        entry = resolved[board_id]["entry"]
        lock = load_json(repo_path(root, entry["build_lock"], "canonical build lock"))
        fingerprint = load_json(
            repo_path(root, entry["fingerprint"], "canonical fingerprint")
        )
        replay_lock(lock, fingerprint, root)
        surface = fingerprint["compatibility_surface"]
        if surface["board_id"] != board_id or surface["target"] != entry["target"]:
            raise HostBuildContractError("canonical fingerprint identity disagrees with catalog")
        by_target[entry["target"]] = fingerprint
        provenance.append(
            "%s lock=%s fingerprint=%s"
            % (board_id, fingerprint["build_lock_sha256"], fingerprint["fingerprint_sha256"])
        )
    if set(by_target) != TARGETS:
        raise HostBuildContractError("generated C requires exact S3 and C6 fingerprints")
    return """/* Generated by tools/resolve_host_build.py generate-c. Do not edit.
 * %s
 */
#include "wdc_host_identity.h"

#include <stddef.h>

#ifdef ESP_PLATFORM
#include "sdkconfig.h"
#endif

%s

%s

const WdcHostFingerprintV1 *wdc_host_fingerprint_for_target(WdcHostTarget target)
{
    switch (target) {
    case WDC_HOST_TARGET_ESP32S3:
        return &s_esp32s3_fingerprint;
    case WDC_HOST_TARGET_ESP32C6:
        return &s_esp32c6_fingerprint;
    default:
        return NULL;
    }
}

const WdcHostFingerprintV1 *wdc_host_running_fingerprint(void)
{
#if defined(CONFIG_IDF_TARGET_ESP32S3) || defined(WDC_HOST_TEST_TARGET_S3)
    return &s_esp32s3_fingerprint;
#elif defined(CONFIG_IDF_TARGET_ESP32C6) || defined(WDC_HOST_TEST_TARGET_C6)
    return &s_esp32c6_fingerprint;
#else
    return NULL;
#endif
}
""" % (
        " | ".join(provenance),
        _render_fingerprint_initializer("s_esp32s3_fingerprint", by_target["esp32s3"]),
        _render_fingerprint_initializer("s_esp32c6_fingerprint", by_target["esp32c6"]),
    )
