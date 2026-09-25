#!/usr/bin/env python3
"""Dependency-free parsing and validation for pinned ESP-IDF lock files."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

LOCK_VERSION = "2.0.0"
WAMR_COMPONENT = "espressif/wasm-micro-runtime"
WAMR_COMPONENT_HASH = "04f25aad2896b5e906397a061d35cce560609bebd3913a4be7e365ecbf2dd9d6"
WAMR_MANIFEST_HASH = "2915c87bbbb4002ac21c3e598680f5204fded60ca89131ba8adb3a8b8f0a3148"
WAMR_REGISTRY = "https://components.espressif.com/"
WAMR_TARGETS = ("esp32", "esp32s3", "esp32c3", "esp32c6", "esp32p4", "esp32c5")
HEX_64_RE = re.compile(r"[0-9a-f]{64}")


class LockContractError(ValueError):
    """Raised when a dependency lock does not match the pinned contract."""


def _scalar(value: str, line_number: int) -> str:
    if not value:
        raise LockContractError(f"line {line_number}: empty scalar")
    if value.startswith('"'):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise LockContractError(f"line {line_number}: invalid quoted scalar") from exc
        if not isinstance(parsed, str):
            raise LockContractError(f"line {line_number}: scalar must be a string")
        return parsed
    if value.startswith("'"):
        if len(value) < 2 or not value.endswith("'"):
            raise LockContractError(f"line {line_number}: invalid single-quoted scalar")
        return value[1:-1].replace("''", "'")
    if value[0] in "[{}&*!|>" or " #" in value:
        raise LockContractError(f"line {line_number}: unsupported YAML scalar syntax")
    return value


def _key_value(content: str, line_number: int) -> tuple[str, str]:
    if ":" not in content:
        raise LockContractError(f"line {line_number}: mapping entry requires ':'")
    key, value = content.split(":", 1)
    if not key or not re.fullmatch(r"[A-Za-z0-9_./-]+", key):
        raise LockContractError(f"line {line_number}: invalid mapping key")
    if value and not value.startswith(" "):
        raise LockContractError(f"line {line_number}: ':' must be followed by a space")
    return key, value.strip()


def parse_lock_text(text: str) -> dict[str, Any]:
    """Parse the strict YAML subset emitted by IDF Component Manager 2.4.x."""
    logical: list[tuple[int, int, str]] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        if "\t" in raw:
            raise LockContractError(f"line {number}: tabs are prohibited")
        indent = len(raw) - len(raw.lstrip(" "))
        if indent % 2:
            raise LockContractError(f"line {number}: indentation must use two-space steps")
        content = raw[indent:]
        if content.startswith("#"):
            raise LockContractError(f"line {number}: comments are not permitted in generated locks")
        logical.append((number, indent, content))
    if not logical:
        raise LockContractError("lock is empty")

    def parse_block(index: int, indent: int) -> tuple[Any, int]:
        if logical[index][2].startswith("-"):
            return parse_sequence(index, indent)
        return parse_mapping(index, indent)

    def parse_mapping(index: int, indent: int) -> tuple[dict[str, Any], int]:
        result: dict[str, Any] = {}
        while index < len(logical):
            number, current_indent, content = logical[index]
            if current_indent < indent or (current_indent == indent and content.startswith("-")):
                break
            if current_indent != indent:
                raise LockContractError(f"line {number}: unexpected indentation")
            key, raw_value = _key_value(content, number)
            if key in result:
                raise LockContractError(f"line {number}: duplicate key {key!r}")
            index += 1
            if raw_value:
                result[key] = _scalar(raw_value, number)
                continue
            if index >= len(logical):
                raise LockContractError(f"line {number}: key {key!r} has no value")
            next_number, next_indent, next_content = logical[index]
            if next_indent < indent or (next_indent == indent and not next_content.startswith("-")):
                raise LockContractError(f"line {number}: key {key!r} has no value")
            if next_indent == indent and next_content.startswith("-"):
                value, index = parse_sequence(index, indent)
            elif next_indent > indent:
                value, index = parse_block(index, next_indent)
            else:
                raise LockContractError(f"line {next_number}: invalid nested value")
            result[key] = value
        return result, index

    def parse_sequence(index: int, indent: int) -> tuple[list[Any], int]:
        result: list[Any] = []
        while index < len(logical):
            number, current_indent, content = logical[index]
            if current_indent < indent or (current_indent == indent and not content.startswith("-")):
                break
            if current_indent != indent or not content.startswith("- "):
                raise LockContractError(f"line {number}: invalid sequence indentation")
            item_text = content[2:]
            index += 1
            if ":" not in item_text:
                result.append(_scalar(item_text, number))
                continue
            key, raw_value = _key_value(item_text, number)
            if not raw_value:
                raise LockContractError(f"line {number}: sequence mapping value is required")
            item: dict[str, Any] = {key: _scalar(raw_value, number)}
            if index < len(logical) and logical[index][1] > indent:
                continuation_indent = logical[index][1]
                continuation, index = parse_mapping(index, continuation_indent)
                overlap = set(item) & set(continuation)
                if overlap:
                    raise LockContractError(f"line {number}: duplicate sequence mapping key")
                item.update(continuation)
            result.append(item)
        return result, index

    if logical[0][1] != 0 or logical[0][2].startswith("-"):
        raise LockContractError("lock root must be a zero-indented mapping")
    parsed, final_index = parse_mapping(0, 0)
    if final_index != len(logical):
        number = logical[final_index][0]
        raise LockContractError(f"line {number}: unparsed lock content")
    return parsed


def load_lock(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise LockContractError(f"cannot read dependency lock {path}: {exc}") from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LockContractError(f"dependency lock is not UTF-8: {path}") from exc
    return parse_lock_text(text), raw


def _exact_fields(value: Any, expected: set[str], label: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        errors.append(f"{label} must be a mapping")
        return {}
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing:
        errors.append(f"{label} is missing fields: {', '.join(missing)}")
    if unknown:
        errors.append(f"{label} has unknown fields: {', '.join(unknown)}")
    return value


def validate_lock(
    path: Path,
    *,
    expected_target: str,
    expected_idf_version: str,
    expected_wamr_version: str,
) -> tuple[list[str], dict[str, Any]]:
    """Validate one generated lock and return errors plus normalized evidence."""
    try:
        lock, raw = load_lock(path)
    except LockContractError as exc:
        return [str(exc)], {}

    errors: list[str] = []
    top = _exact_fields(
        lock,
        {"dependencies", "direct_dependencies", "manifest_hash", "target", "version"},
        "lock",
        errors,
    )
    if top.get("version") != LOCK_VERSION:
        errors.append(f"lock.version must be {LOCK_VERSION!r}")
    if top.get("target") != expected_target:
        errors.append(f"lock.target must be {expected_target!r}")
    if top.get("manifest_hash") != WAMR_MANIFEST_HASH:
        errors.append("lock.manifest_hash does not match the pinned component manifest")
    if top.get("direct_dependencies") != [WAMR_COMPONENT]:
        errors.append(f"lock.direct_dependencies must contain only {WAMR_COMPONENT!r}")

    dependencies = _exact_fields(top.get("dependencies"), {WAMR_COMPONENT, "idf"}, "lock.dependencies", errors)
    wamr = _exact_fields(
        dependencies.get(WAMR_COMPONENT),
        {"component_hash", "dependencies", "source", "targets", "version"},
        f"lock.dependencies.{WAMR_COMPONENT}",
        errors,
    )
    if wamr.get("version") != expected_wamr_version:
        errors.append(f"WAMR version must be {expected_wamr_version!r}")
    component_hash = wamr.get("component_hash")
    if not isinstance(component_hash, str) or HEX_64_RE.fullmatch(component_hash) is None:
        errors.append("WAMR component_hash must be 64 lowercase hexadecimal characters")
    elif component_hash != WAMR_COMPONENT_HASH:
        errors.append("WAMR component_hash does not match the pinned registry component")
    if wamr.get("source") != {"registry_url": WAMR_REGISTRY, "type": "service"}:
        errors.append("WAMR source must be the pinned Espressif component registry")
    if wamr.get("targets") != list(WAMR_TARGETS):
        errors.append("WAMR targets do not match the pinned component metadata")
    if expected_target not in (wamr.get("targets") if isinstance(wamr.get("targets"), list) else []):
        errors.append(f"WAMR metadata does not advertise target {expected_target!r}")
    if wamr.get("dependencies") != [{"name": "idf", "require": "private", "version": ">=5.1"}]:
        errors.append("WAMR IDF dependency metadata is not canonical")

    idf = _exact_fields(dependencies.get("idf"), {"source", "version"}, "lock.dependencies.idf", errors)
    if idf.get("version") != expected_idf_version.removeprefix("v"):
        errors.append(f"locked IDF version must be {expected_idf_version.removeprefix('v')!r}")
    if idf.get("source") != {"type": "idf"}:
        errors.append("IDF dependency source must be type 'idf'")

    evidence = {
        "path": str(path),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "target": top.get("target"),
        "idf_version": idf.get("version"),
        "wamr_version": wamr.get("version"),
        "wamr_component_hash": component_hash,
        "manifest_hash": top.get("manifest_hash"),
    }
    return errors, evidence
