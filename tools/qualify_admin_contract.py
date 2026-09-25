#!/usr/bin/env python3
"""Validate and report the frozen HP4.0 protected-administration model."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

try:
    from tools import hp5_5_source_authority
except ModuleNotFoundError:
    import hp5_5_source_authority  # type: ignore[no-redef]


ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "specs/PULSE-ESP32-009-protected-administration.json"
HP1_MODEL = ROOT / "specs/PULSE-ESP32-006-host-kernel-resource-authority.json"
HP2_MODEL = ROOT / "specs/PULSE-ESP32-007-host-build-coherence.json"
HP3_MODEL = ROOT / "specs/PULSE-ESP32-008-application-slots.json"
HP35_MODEL = ROOT / "specs/PULSE-ESP32-008a-application-slot-adversarial-seal.json"
HP35_INDEX = ROOT / "evidence/hardware/hp3_5-index.json"
HP41_MODEL = ROOT / "specs/PULSE-ESP32-010-protected-administration-core.json"
HP42_MODEL = ROOT / "specs/PULSE-ESP32-011-exclusive-update-transaction.json"
HP43_MODEL = ROOT / "specs/PULSE-ESP32-012-host-only-recovery.json"
HP44_MODEL = ROOT / "specs/PULSE-ESP32-013-administration-adversarial-seal.json"
HP5_MODEL = ROOT / "specs/PULSE-ESP32-014-host-network-mediator.json"
FIRMWARE = ROOT / "firmware"
NATIVE_SDK = ROOT / "native-sdk"

EXPECTED_STATES = [
    "NORMAL",
    "QUIESCE",
    "UPDATE",
    "RECOVERY",
    "REBOOT_HANDOFF",
]
EXPECTED_COMMANDS = [
    "STATUS",
    "BEGIN_UPDATE",
    "WRITE_CHUNK",
    "FINISH_UPDATE",
    "ABORT",
    "ENTER_RECOVERY",
    "ACTIVATE_TRIAL",
    "REBOOT",
]
EXPECTED_TRANSITION_IDS = [
    "normal.begin_update",
    "normal.begin_recovery",
    "normal.no_viable_application",
    "quiesce.update_ready",
    "quiesce.recovery_ready",
    "quiesce.abort_to_normal",
    "quiesce.abort_to_recovery",
    "update.trial_committed",
    "update.abort_to_normal",
    "update.abort_to_recovery",
    "recovery.begin_update",
    "recovery.reboot_viable",
]
EXPECTED_TRANSITION_GUARDS = {
    "normal.begin_update": [
        "session_authorized",
        "replay_fresh",
        "deadline_live",
        "hp1_administration_work_accepted",
    ],
    "normal.begin_recovery": [
        "session_authorized",
        "replay_fresh",
        "deadline_live",
        "recovery_privilege",
        "hp1_recovery_work_accepted",
    ],
    "normal.no_viable_application": [
        "hp3_no_viable_application",
        "recovery_reserve_intact",
    ],
    "quiesce.update_ready": [
        "intent_is_update",
        "guest_quiesced",
        "guest_unloaded",
        "native_refinements_quiesced",
        "native_refinements_unloaded",
        "exclusive_update_admitted",
        "last_confirmed_preserved",
    ],
    "quiesce.recovery_ready": [
        "intent_is_recovery",
        "guest_quiesced",
        "guest_unloaded",
        "native_refinements_quiesced",
        "native_refinements_unloaded",
        "recovery_reserve_intact",
        "boot_authority_unchanged",
    ],
    "quiesce.abort_to_normal": [
        "quiesce_stopped",
        "staging_not_started",
        "last_confirmed_viable",
        "boot_authority_unchanged",
    ],
    "quiesce.abort_to_recovery": [
        "quiesce_stopped",
        "hp3_no_viable_application",
        "boot_authority_unchanged",
        "recovery_reserve_intact",
    ],
    "update.trial_committed": [
        "inactive_slot_only",
        "complete_artifact_verified",
        "authorization_current",
        "hp2_host_compatible",
        "security_floor_valid",
        "artifact_authority_valid",
        "trial_journal_commit_durable",
        "last_confirmed_preserved",
    ],
    "update.abort_to_normal": [
        "staging_aborted",
        "last_confirmed_viable",
        "boot_authority_unchanged",
        "last_confirmed_preserved",
    ],
    "update.abort_to_recovery": [
        "staging_aborted",
        "hp3_no_viable_application",
        "boot_authority_unchanged",
        "recovery_reserve_intact",
    ],
    "recovery.begin_update": [
        "session_authorized",
        "replay_fresh",
        "deadline_live",
        "application_absent",
        "native_refinements_unloaded",
        "exclusive_update_admitted",
        "inactive_slot_selected",
    ],
    "recovery.reboot_viable": [
        "session_authorized",
        "replay_fresh",
        "deadline_live",
        "reboot_privilege",
        "hp3_boot_authority_established",
        "selected_application_viable",
    ],
}
EXPECTED_TRANSITION_SHAPES = {
    "normal.begin_update": ("ADMINISTRATION", "NORMAL", "BEGIN_UPDATE", "QUIESCE", "UPDATE"),
    "normal.begin_recovery": ("RECOVERY", "NORMAL", "ENTER_RECOVERY", "QUIESCE", "RECOVERY"),
    "normal.no_viable_application": ("RECOVERY", "NORMAL", "NO_VIABLE_APPLICATION", "RECOVERY", "RECOVERY"),
    "quiesce.update_ready": ("UPDATE", "QUIESCE", "QUIESCE_COMPLETE", "UPDATE", "UPDATE"),
    "quiesce.recovery_ready": ("RECOVERY", "QUIESCE", "QUIESCE_COMPLETE", "RECOVERY", "RECOVERY"),
    "quiesce.abort_to_normal": ("ADMINISTRATION", "QUIESCE", "ABORT_OR_TIMEOUT", "NORMAL", "NONE"),
    "quiesce.abort_to_recovery": ("RECOVERY", "QUIESCE", "ABORT_OR_TIMEOUT", "RECOVERY", "RECOVERY"),
    "update.trial_committed": ("UPDATE", "UPDATE", "TRIAL_COMMITTED", "REBOOT_HANDOFF", "NONE"),
    "update.abort_to_normal": ("UPDATE", "UPDATE", "ABORT_OR_FAILURE", "NORMAL", "NONE"),
    "update.abort_to_recovery": ("RECOVERY", "UPDATE", "ABORT_OR_FAILURE", "RECOVERY", "RECOVERY"),
    "recovery.begin_update": ("UPDATE", "RECOVERY", "BEGIN_UPDATE", "UPDATE", "UPDATE"),
    "recovery.reboot_viable": ("RECOVERY", "RECOVERY", "REBOOT", "REBOOT_HANDOFF", "NONE"),
}
EXPECTED_BOUNDS = {
    "audit_ring_records": 32,
    "authorization_backoff_ms": 30000,
    "authorization_failures_per_window": 8,
    "authorization_window_ms": 60000,
    "challenge_deadline_ms": 10000,
    "command_default_deadline_ms": 30000,
    "maximum_frame_bytes": 2048,
    "maximum_inflight_commands_per_session": 1,
    "maximum_normalized_request_bytes": 112,
    "maximum_payload_bytes": 1024,
    "maximum_sessions": 1,
    "maximum_status_response_bytes": 1024,
    "maximum_stream_chunk_bytes": 1024,
    "quiesce_deadline_ms": 10000,
    "reboot_handoff_deadline_ms": 5000,
    "session_idle_deadline_ms": 30000,
    "session_lifetime_ms": 900000,
    "stream_idle_deadline_ms": 30000,
    "update_transaction_deadline_ms": 900000,
}
EXPECTED_AUTHORITY_HASHES = {
    HP1_MODEL: "cc3afbfc4ff7d4a7b5b5aca6ae0b5953a34065501bbfea36d4580a2d193fd84d",
    HP2_MODEL: "f9dc94e2ea4bf45af14787671c9fd2ddfb71c888874c6ea8e722cdf0ec5da3f0",
    HP3_MODEL: "79a5c85d8f75ac89ef9903bd8ee54f9400d8754a8c4deb806ab6644dc5e43f38",
    HP35_MODEL: "c52993ff889a3dffe2f87f54bd226e652592018410a24ad36b70592c35219a29",
    HP35_INDEX: "3c7d209298ea0f4444991ec296f9b644bbb42428f1d63d7b475468ce2d71a6e9",
}
EXPECTED_FIRMWARE = {
    "sha256": "c7b4341e00911b3b26b4d9b8abcd831af4abdf7754503a79298e86aa2b9d2c31",
    "file_count": 141,
}
EXPECTED_NATIVE_SDK = {
    "sha256": "a7ceb397ab009950a1ebbdea60280f7944020a6523252b7de0d781e3e798bdd4",
    "file_count": 1,
}
EXPECTED_HP41_FIRMWARE = {
    "sha256": "4f7b56a99adfedfa57c1d5179ad5ca03e6f57dd258a73fa3a6f71f747973253c",
    "file_count": 146,
}
EXPECTED_HP42_FIRMWARE = {
    "sha256": "77f4d2044776c6828e443486ee21199f95b4e1f34ae704c7323e901d51602eca",
    "file_count": 148,
}
EXPECTED_HP43_FIRMWARE = {
    "sha256": "d36978214d8e1d892961e7239facafa49eb1ed4150843dd1eeb23dec5d8ceb5f",
    "file_count": 150,
}
EXPECTED_HP44_FIRMWARE = {
    "sha256": "ff9f571860eda289cc276c6418f887b0af42552380c50f4038b5163ea929a386",
    "file_count": 150,
}
EXPECTED_HP5_FIRMWARE = {
    "sha256": "2e94b65a03a0612d4e770dc0f9b624dab874a75bf334bbd5173023427b7076a5",
    "file_count": 159,
}


class QualificationError(RuntimeError):
    """Raised when the HP4.0 contract is incomplete or internally inconsistent."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_evidence(root: Path, ignored: set[str] | None = None) -> dict[str, Any]:
    digest = hashlib.sha256()
    count = 0
    ignored = ignored or set()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root)
        if any(part in ignored for part in relative.parts):
            continue
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256(path).encode("ascii"))
        digest.update(b"\n")
        count += 1
    return {"sha256": digest.hexdigest(), "file_count": count}


def load_model(path: Path = MODEL) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QualificationError("HP4.0 model is unreadable") from exc
    if not isinstance(value, dict):
        raise QualificationError("HP4.0 model root must be an object")
    return value


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    observed = set(value)
    if observed != expected:
        missing = sorted(expected - observed)
        extra = sorted(observed - expected)
        raise QualificationError(
            "%s keys drifted (missing=%s, extra=%s)" % (label, missing, extra)
        )


def _validate_layout(layout: Any, total_bytes: int, label: str) -> int:
    if not isinstance(layout, list) or not layout:
        raise QualificationError("%s layout is missing" % label)
    occupied: set[int] = set()
    fields: set[str] = set()
    for entry in layout:
        if not isinstance(entry, dict):
            raise QualificationError("%s layout entry is not an object" % label)
        _exact_keys(entry, {"field", "offset", "size"}, "%s field" % label)
        field = entry["field"]
        offset = entry["offset"]
        size = entry["size"]
        if (
            not isinstance(field, str)
            or not field
            or field in fields
            or not isinstance(offset, int)
            or isinstance(offset, bool)
            or not isinstance(size, int)
            or isinstance(size, bool)
            or offset < 0
            or size <= 0
            or offset + size > total_bytes
        ):
            raise QualificationError("%s layout field is invalid: %r" % (label, entry))
        span = set(range(offset, offset + size))
        if occupied & span:
            raise QualificationError("%s layout overlaps at %s" % (label, field))
        fields.add(field)
        occupied |= span
    if occupied != set(range(total_bytes)):
        raise QualificationError("%s layout does not cover exactly %d bytes" % (label, total_bytes))
    return len(fields)


def _validate_authority(model: dict[str, Any]) -> dict[str, Any]:
    bindings = model.get("authority_bindings")
    if not isinstance(bindings, dict):
        raise QualificationError("authority bindings are missing")
    for path, expected in EXPECTED_AUTHORITY_HASHES.items():
        if sha256(path) != expected:
            raise QualificationError("preserved authority changed: %s" % path.relative_to(ROOT))
    if bindings.get("hp1", {}).get("model_sha256") != EXPECTED_AUTHORITY_HASHES[HP1_MODEL]:
        raise QualificationError("HP1 binding hash drifted")
    if bindings.get("hp2", {}).get("model_sha256") != EXPECTED_AUTHORITY_HASHES[HP2_MODEL]:
        raise QualificationError("HP2 binding hash drifted")
    if bindings.get("hp3", {}).get("model_sha256") != EXPECTED_AUTHORITY_HASHES[HP3_MODEL]:
        raise QualificationError("HP3 binding hash drifted")
    if bindings.get("hp3_5", {}).get("evidence_index_sha256") != EXPECTED_AUTHORITY_HASHES[HP35_INDEX]:
        raise QualificationError("HP3.5 evidence binding hash drifted")
    if bindings.get("hp3_5", {}).get("model_sha256") != EXPECTED_AUTHORITY_HASHES[HP35_MODEL]:
        raise QualificationError("HP3.5 model binding hash drifted")
    hp1 = bindings["hp1"]
    if (
        hp1.get("fixed_control_reserve_bytes") != 98304
        or hp1.get("exclusive_update_working_bytes") != 65536
        or hp1.get("update_largest_allocation_bytes") != 65536
        or hp1.get("application_cannot_select_source_or_priority") is not True
    ):
        raise QualificationError("HP1 resource binding drifted")
    if bindings["hp3"].get("factory_host_writable") is not False:
        raise QualificationError("HP4 may not write the factory host")
    if bindings["hp3"].get("slot_model_unchanged") is not True:
        raise QualificationError("HP4 changed HP3 slot semantics")
    return {
        "hp1_model_sha256": EXPECTED_AUTHORITY_HASHES[HP1_MODEL],
        "hp2_model_sha256": EXPECTED_AUTHORITY_HASHES[HP2_MODEL],
        "hp3_model_sha256": EXPECTED_AUTHORITY_HASHES[HP3_MODEL],
        "hp3_5_model_sha256": EXPECTED_AUTHORITY_HASHES[HP35_MODEL],
        "hp3_5_index_sha256": EXPECTED_AUTHORITY_HASHES[HP35_INDEX],
    }


def _validate_source_reconciliation(model: dict[str, Any]) -> dict[str, Any]:
    reconciliation = model.get("source_reconciliation")
    if not isinstance(reconciliation, dict):
        raise QualificationError("source reconciliation is missing")
    expected = {
        "accepted_base_archive_sha256": "928b74de36f5d25d48caecb08a3412314b02f0aece7c804046b5b7942466d00f",
        "accepted_base_manifest_file_count": 440,
        "accepted_base_manifest_payload_bytes": 3033334,
        "classification": "AUTHORIZED_HP3_5_CLOSURE_SEAL_SUCCESSOR",
        "predecessor_v8_archive_sha256": "7be285c47d268721e4a419074d8a551a7db59968bed8738a8ab7ee0c979c4a9a",
        "predecessor_v8_manifest_file_count": 438,
        "predecessor_v8_manifest_payload_bytes": 3022784,
    }
    for key, value in expected.items():
        if reconciliation.get(key) != value:
            raise QualificationError("source reconciliation drifted: %s" % key)
    current_firmware = tree_evidence(
        FIRMWARE,
        {"build", "managed_components", "dependencies.lock", "sdkconfig", "__pycache__"},
    )
    native_sdk = tree_evidence(NATIVE_SDK, {"__pycache__"})
    if native_sdk != EXPECTED_NATIVE_SDK:
        raise QualificationError("HP3.5 native-SDK seal changed during HP4.0")
    successor = None
    if current_firmware != EXPECTED_FIRMWARE:
        if not HP41_MODEL.is_file():
            raise QualificationError("the sealed HP4.1 successor is missing")
        try:
            hp41 = json.loads(HP41_MODEL.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise QualificationError("cannot validate the HP4.1 successor") from exc
        history = hp41.get("source_history", {})
        if (
            hp41.get("schema") !=
                "pulse.esp32.hp4_1-protected-administration-core.v1"
            or hp41.get("pass") != "HP4.1"
            or hp41.get("status") != "IMPLEMENTED"
            or history.get("hp4_0_firmware_sha256") !=
                EXPECTED_FIRMWARE["sha256"]
            or history.get("hp4_0_firmware_file_count") !=
                EXPECTED_FIRMWARE["file_count"]
        ):
            raise QualificationError("HP4.1 does not preserve the HP4.0 firmware history")
        if current_firmware == EXPECTED_HP41_FIRMWARE:
            if (
                history.get("current_firmware_sha256") !=
                    current_firmware["sha256"]
                or history.get("current_firmware_file_count") !=
                    current_firmware["file_count"]
            ):
                raise QualificationError("HP4.1 current firmware seal drifted")
            successor = "HP4.1"
        elif current_firmware in (
            EXPECTED_HP42_FIRMWARE,
            EXPECTED_HP43_FIRMWARE,
            EXPECTED_HP44_FIRMWARE,
            EXPECTED_HP5_FIRMWARE,
            hp5_5_source_authority.EXPECTED_FIRMWARE,
        ) and HP42_MODEL.is_file():
            try:
                hp42 = json.loads(HP42_MODEL.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise QualificationError("cannot validate the HP4.2 successor") from exc
            hp42_history = hp42.get("source_history", {})
            if (
                hp42.get("schema") !=
                    "pulse.esp32.hp4_2-exclusive-update-transaction.v1"
                or hp42.get("pass") != "HP4.2"
                or hp42.get("status") != "IMPLEMENTED"
                or history.get("current_firmware_sha256") !=
                    EXPECTED_HP41_FIRMWARE["sha256"]
                or history.get("current_firmware_file_count") !=
                    EXPECTED_HP41_FIRMWARE["file_count"]
                or hp42_history.get("hp4_1_firmware_sha256") !=
                    EXPECTED_HP41_FIRMWARE["sha256"]
                or hp42_history.get("hp4_1_firmware_file_count") !=
                    EXPECTED_HP41_FIRMWARE["file_count"]
                or hp42_history.get("current_firmware_sha256") !=
                    EXPECTED_HP42_FIRMWARE["sha256"]
                or hp42_history.get("current_firmware_file_count") !=
                    EXPECTED_HP42_FIRMWARE["file_count"]
            ):
                raise QualificationError("HP4.2 does not preserve HP4.0/HP4.1 history")
            if current_firmware == EXPECTED_HP42_FIRMWARE:
                successor = "HP4.2"
            elif HP43_MODEL.is_file():
                try:
                    hp43 = json.loads(HP43_MODEL.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise QualificationError("cannot validate the HP4.3 successor") from exc
                hp43_history = hp43.get("source_history", {})
                if (
                    hp43.get("schema") !=
                        "pulse.esp32.hp4_3-host-only-recovery.v1"
                    or hp43.get("pass") != "HP4.3"
                    or hp43.get("status") != "IMPLEMENTED"
                    or hp43_history.get("hp4_2_firmware_sha256") !=
                        EXPECTED_HP42_FIRMWARE["sha256"]
                    or hp43_history.get("hp4_2_firmware_file_count") !=
                        EXPECTED_HP42_FIRMWARE["file_count"]
                    or hp43_history.get("current_firmware_sha256") !=
                        EXPECTED_HP43_FIRMWARE["sha256"]
                    or hp43_history.get("current_firmware_file_count") !=
                        EXPECTED_HP43_FIRMWARE["file_count"]
                ):
                    raise QualificationError("HP4.3 does not preserve the HP4.2 history")
                if current_firmware == EXPECTED_HP43_FIRMWARE:
                    successor = "HP4.3"
                elif HP44_MODEL.is_file():
                    try:
                        hp44 = json.loads(HP44_MODEL.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError) as exc:
                        raise QualificationError("cannot validate the HP4.4 successor") from exc
                    hp44_history = hp44.get("source_history", {})
                    if (
                        hp44.get("schema")
                        != "pulse.esp32.hp4_4-administration-adversarial-seal.v1"
                        or hp44.get("pass") != "HP4.4"
                        or hp44.get("status") != "SEALED"
                        or hp44_history.get("hp4_3_firmware_sha256")
                        != EXPECTED_HP43_FIRMWARE["sha256"]
                        or hp44_history.get("hp4_3_firmware_file_count")
                        != EXPECTED_HP43_FIRMWARE["file_count"]
                        or hp44_history.get("current_firmware_sha256")
                        != EXPECTED_HP44_FIRMWARE["sha256"]
                        or hp44_history.get("current_firmware_file_count")
                        != EXPECTED_HP44_FIRMWARE["file_count"]
                    ):
                        raise QualificationError("HP4.4 does not preserve the HP4.3 history")
                    if current_firmware == EXPECTED_HP44_FIRMWARE:
                        successor = "HP4.4"
                    elif HP5_MODEL.is_file():
                        try:
                            hp5 = json.loads(HP5_MODEL.read_text(encoding="utf-8"))
                        except (OSError, json.JSONDecodeError) as exc:
                            raise QualificationError("cannot validate the HP5 successor") from exc
                        hp5_history = hp5.get("source_history", {})
                        if (
                            hp5.get("schema") != "pulse.esp32.hp5-host-network-mediator.v1"
                            or hp5.get("pass") != "HP5"
                            or hp5.get("status") != "QUALIFIED"
                            or hp5_history.get("hp4_4_firmware_sha256")
                            != EXPECTED_HP44_FIRMWARE["sha256"]
                            or hp5_history.get("hp4_4_firmware_file_count")
                            != EXPECTED_HP44_FIRMWARE["file_count"]
                            or hp5_history.get("current_firmware_sha256")
                            != EXPECTED_HP5_FIRMWARE["sha256"]
                            or hp5_history.get("current_firmware_file_count")
                            != EXPECTED_HP5_FIRMWARE["file_count"]
                        ):
                            raise QualificationError("HP5 does not preserve the HP4.4 history")
                        if current_firmware == EXPECTED_HP5_FIRMWARE:
                            successor = "HP5"
                        else:
                            hp5_5_source_authority.validate(
                                current_firmware,
                                EXPECTED_HP5_FIRMWARE,
                                QualificationError,
                            )
                            successor = "HP5.5"
                    else:
                        raise QualificationError("the qualified HP5 successor is missing")
                else:
                    raise QualificationError("the sealed HP4.4 successor is missing")
            else:
                raise QualificationError("the sealed HP4.3 successor is missing")
        else:
            raise QualificationError("firmware changed outside the sealed HP4.1/HP4.2/HP4.3/HP4.4/HP5/HP5.5 successors")
    for prefix, observed in (
        ("firmware_source", EXPECTED_FIRMWARE),
        ("native_sdk", EXPECTED_NATIVE_SDK),
    ):
        if (
            reconciliation.get(prefix + "_sha256") != observed["sha256"]
            or reconciliation.get(prefix + "_file_count") != observed["file_count"]
        ):
            raise QualificationError("source reconciliation does not bind %s" % prefix)
    return {
        "firmware": EXPECTED_FIRMWARE,
        "native_sdk": native_sdk,
        "current_firmware": current_firmware,
        "current_successor": successor,
    }


def _find_transition(
    transitions: list[dict[str, Any]],
    state: str,
    trigger: str,
    guards: set[str],
) -> dict[str, Any] | None:
    candidates = []
    for transition in transitions:
        required = transition.get("guards")
        if (
            transition.get("from") == state
            and transition.get("trigger") == trigger
            and isinstance(required, list)
            and set(required).issubset(guards)
        ):
            candidates.append(transition)
    if len(candidates) > 1:
        raise QualificationError("transition guards are ambiguous for %s/%s" % (state, trigger))
    return candidates[0] if candidates else None


def _apply(
    transitions: list[dict[str, Any]],
    state: str,
    intent: str,
    transition_id: str,
) -> tuple[str, str]:
    transition = next(item for item in transitions if item["id"] == transition_id)
    if transition["from"] != state:
        raise QualificationError("scenario entered %s from the wrong state" % transition_id)
    selected = _find_transition(
        transitions,
        state,
        transition["trigger"],
        set(transition["guards"]),
    )
    if selected is None or selected["id"] != transition_id:
        raise QualificationError("scenario could not select %s" % transition_id)
    if state == "QUIESCE" and transition_id == "quiesce.update_ready" and intent != "UPDATE":
        raise QualificationError("update transition lost pending intent")
    if state == "QUIESCE" and transition_id == "quiesce.recovery_ready" and intent != "RECOVERY":
        raise QualificationError("recovery transition lost pending intent")
    return selected["to"], selected["intent_after"]


def _validate_state_machine(model: dict[str, Any]) -> dict[str, Any]:
    machine = model.get("state_machine")
    if not isinstance(machine, dict):
        raise QualificationError("state machine is missing")
    if machine.get("states") != EXPECTED_STATES:
        raise QualificationError("administrative states drifted")
    if machine.get("intent_values") != ["NONE", "UPDATE", "RECOVERY"]:
        raise QualificationError("administrative intents drifted")
    transitions = machine.get("legal_transitions")
    if not isinstance(transitions, list):
        raise QualificationError("legal transitions are missing")
    if [item.get("id") for item in transitions] != EXPECTED_TRANSITION_IDS:
        raise QualificationError("legal transition inventory or order drifted")
    allowed_sources = {"ADMINISTRATION", "UPDATE", "RECOVERY"}
    for transition in transitions:
        _exact_keys(
            transition,
            {"control_source", "from", "guards", "id", "intent_after", "to", "trigger"},
            "transition %s" % transition.get("id"),
        )
        if transition["from"] not in EXPECTED_STATES or transition["to"] not in EXPECTED_STATES:
            raise QualificationError("transition names an unknown state")
        if transition["control_source"] not in allowed_sources:
            raise QualificationError("transition escaped HP1 administrative sources")
        guards = transition["guards"]
        if not isinstance(guards, list) or not guards or len(guards) != len(set(guards)):
            raise QualificationError("transition guards are empty or duplicated")
        if guards != EXPECTED_TRANSITION_GUARDS[transition["id"]]:
            raise QualificationError("transition guards drifted: %s" % transition["id"])
        shape = (
            transition["control_source"],
            transition["from"],
            transition["trigger"],
            transition["to"],
            transition["intent_after"],
        )
        if shape != EXPECTED_TRANSITION_SHAPES[transition["id"]]:
            raise QualificationError("transition shape drifted: %s" % transition["id"])
    if any(item["from"] == "REBOOT_HANDOFF" for item in transitions):
        raise QualificationError("reboot handoff must be terminal")
    if any(item["from"] == "NORMAL" and item["to"] == "UPDATE" for item in transitions):
        raise QualificationError("NORMAL may not bypass QUIESCE")
    if any(item["from"] == "RECOVERY" and item["to"] == "NORMAL" for item in transitions):
        raise QualificationError("RECOVERY may not bypass HP3 reboot selection")

    scenarios = [
        ["normal.begin_update", "quiesce.update_ready", "update.trial_committed"],
        ["normal.begin_recovery", "quiesce.recovery_ready", "recovery.begin_update", "update.abort_to_recovery"],
        ["normal.no_viable_application", "recovery.reboot_viable"],
        ["normal.begin_update", "quiesce.update_ready", "update.abort_to_normal"],
        ["normal.begin_update", "quiesce.abort_to_normal"],
    ]
    scenario_results = []
    for index, steps in enumerate(scenarios, start=1):
        state = "NORMAL"
        intent = "NONE"
        visited = [state]
        for transition_id in steps:
            state, intent = _apply(transitions, state, intent, transition_id)
            visited.append(state)
        scenario_results.append({"scenario": index, "steps": steps, "visited": visited, "final_state": state})

    guard_denials = 0
    for transition in transitions:
        complete = set(transition["guards"])
        for omitted in transition["guards"]:
            selected = _find_transition(
                transitions,
                transition["from"],
                transition["trigger"],
                complete - {omitted},
            )
            if selected is not None:
                raise QualificationError(
                    "missing guard %s still selected %s" % (omitted, selected["id"])
                )
            guard_denials += 1

    reachable = {"NORMAL", "RECOVERY"}
    changed = True
    while changed:
        changed = False
        for transition in transitions:
            if transition["from"] in reachable and transition["to"] not in reachable:
                reachable.add(transition["to"])
                changed = True
    if reachable != set(EXPECTED_STATES):
        raise QualificationError("state graph is not closed and reachable")
    return {
        "states": EXPECTED_STATES,
        "transition_ids": EXPECTED_TRANSITION_IDS,
        "scenario_count": len(scenario_results),
        "scenarios": scenario_results,
        "guard_denial_cases": guard_denials,
        "reboot_handoff_terminal": True,
    }


def validate(model: dict[str, Any]) -> dict[str, Any]:
    required_top = {
        "administrative_identity",
        "audit",
        "authority_bindings",
        "claim",
        "command_contract",
        "deferred",
        "pass",
        "request_bounds",
        "request_record",
        "schema",
        "serial_transport",
        "session_contract",
        "source_reconciliation",
        "state_machine",
        "status",
    }
    _exact_keys(model, required_top, "HP4.0 model")
    if (
        model.get("schema") != "pulse.esp32.hp4_0-protected-administration-contract.v1"
        or model.get("pass") != "HP4.0"
        or model.get("status") != "FROZEN"
    ):
        raise QualificationError("HP4.0 model identity drifted")
    claim = model.get("claim", {})
    if claim != {
        "aggregate": "HOST_ADMINISTRATION_CONTRACT_FROZEN",
        "application_code_executed": False,
        "classification": "HOST_MODEL_ONLY",
        "firmware_implemented": False,
        "network_transport_implemented": False,
        "physical_execution": False,
        "production_cryptography": False,
        "serial_driver_implemented": False,
    }:
        raise QualificationError("HP4.0 claim boundary drifted")
    if model.get("command_contract", {}).get("commands") != EXPECTED_COMMANDS:
        raise QualificationError("command inventory drifted")
    if model.get("command_contract", {}).get("exactly_one_terminal_per_accepted_command") is not True:
        raise QualificationError("terminal ownership is not exact")
    bounds = model.get("request_bounds", {})
    if bounds != EXPECTED_BOUNDS:
        raise QualificationError("request bounds or deadlines drifted")
    layouts = {
        "authenticated_entry": _validate_layout(
            model["session_contract"]["authenticated_entry_layout"],
            model["session_contract"]["authenticated_entry_bytes"],
            "authenticated entry",
        ),
        "request": _validate_layout(
            model["request_record"]["layout"],
            model["request_record"]["bytes"],
            "request",
        ),
        "terminal": _validate_layout(
            model["command_contract"]["terminal_record_layout"],
            model["command_contract"]["terminal_record_bytes"],
            "terminal",
        ),
        "audit": _validate_layout(
            model["audit"]["record_layout"],
            model["audit"]["record_bytes"],
            "audit",
        ),
    }
    serial = model.get("serial_transport", {})
    if (
        serial.get("concrete_transport") != "SERIAL_PHYSICAL_V1"
        or serial.get("transport_kinds")
        != ["SERIAL_PHYSICAL_V1", "AUTHENTICATED_EXTERNAL_V1_RESERVED"]
        or serial.get("maximum_frame_bytes") != 2048
    ):
        raise QualificationError("serial-first transport seam drifted")
    return {
        "authority": _validate_authority(model),
        "source_reconciliation": _validate_source_reconciliation(model),
        "layouts": layouts,
        "state_machine": _validate_state_machine(model),
    }


def _prepare(path: Path) -> Path:
    output = path.expanduser().resolve()
    if output.exists():
        if not output.is_dir() or any(output.iterdir()):
            raise QualificationError("output directory must be absent or empty")
    else:
        output.mkdir(parents=True)
    return output


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def qualify(out_dir: Path) -> dict[str, Any]:
    output = _prepare(out_dir)
    model = load_model()
    validation = validate(model)
    model_copy = output / "protected-administration-model.json"
    shutil.copy2(MODEL, model_copy)
    transition_path = output / "transition-evaluation.json"
    _write_json(transition_path, validation["state_machine"])
    evidence = []
    for path in (model_copy, transition_path):
        evidence.append(
            {
                "path": path.name,
                "sha256": sha256(path),
                "size": path.stat().st_size,
            }
        )
    manifest = {
        "schema": "pulse.esp32.hp4_0-administration-contract-evidence.v1",
        "artifacts": evidence,
        "status": "PASS",
    }
    manifest_path = output / "evidence-manifest.json"
    _write_json(manifest_path, manifest)
    report = {
        "schema": "pulse.esp32.hp4_0-administration-contract-qualification.v1",
        "phase": "PROTECTED_ADMINISTRATION_CONTRACT",
        "pass": "HP4.0",
        "aggregate": "HOST_ADMINISTRATION_CONTRACT_FROZEN",
        "status": "PASS",
        "classification": "HOST_MODEL_ONLY",
        "claim": model["claim"],
        "source_reconciliation": validation["source_reconciliation"],
        "authority": validation["authority"],
        "record_layout_field_counts": validation["layouts"],
        "state_count": len(validation["state_machine"]["states"]),
        "transition_count": len(validation["state_machine"]["transition_ids"]),
        "scenario_count": validation["state_machine"]["scenario_count"],
        "guard_denial_cases": validation["state_machine"]["guard_denial_cases"],
        "application_code_executed": False,
        "firmware_source_changed": False,
        "physical_result_created": False,
        "evidence_manifest": {
            "path": manifest_path.name,
            "sha256": sha256(manifest_path),
            "size": manifest_path.stat().st_size,
        },
    }
    _write_json(output / "qualification-report.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = qualify(args.out_dir)
    except QualificationError as exc:
        print("HP4.0 qualification failed: %s" % exc, file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
