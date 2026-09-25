#!/usr/bin/env python3
"""Exact HP5.5 source-successor authority shared by historical qualifiers."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Type


ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "specs/PULSE-ESP32-015-network-administration-physical-seal.json"
EXPECTED_FIRMWARE = {
    "sha256": "d60e2669cd3b2dd5869e2305c92e39913b270ba9d54844d3a34d614681c5a98a",
    "file_count": 168,
}


def validate(
    firmware: dict[str, Any],
    hp5_firmware: dict[str, Any],
    error_type: Type[Exception] = RuntimeError,
) -> None:
    """Accept only the exact pending HP5.5 physical-audit successor."""

    if firmware != EXPECTED_FIRMWARE or not MODEL.is_file() or MODEL.is_symlink():
        raise error_type("the exact HP5.5 source successor is missing")
    try:
        model = json.loads(MODEL.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise error_type("cannot validate the HP5.5 source successor") from exc
    history = model.get("source_history", {})
    if (
        model.get("schema")
        != "pulse.esp32.hp5_5-network-administration-physical-seal.v1"
        or model.get("pass") != "HP5.5"
        or model.get("status") != "READY_FOR_PHYSICAL_EXECUTION"
        or model.get("aggregate") != "HARDWARE_PENDING"
        or history.get("hp5_firmware_sha256") != hp5_firmware["sha256"]
        or history.get("hp5_firmware_file_count") != hp5_firmware["file_count"]
        or history.get("current_firmware_sha256") != EXPECTED_FIRMWARE["sha256"]
        or history.get("current_firmware_file_count") != EXPECTED_FIRMWARE["file_count"]
    ):
        raise error_type("HP5.5 does not preserve the HP5 source history")
