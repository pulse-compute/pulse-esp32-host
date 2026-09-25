#!/usr/bin/env python3
"""Generate or verify HP5.5 target plans, locks, and running fingerprints."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    from tools import host_build_contract
except ModuleNotFoundError:  # Direct execution from tools/.
    import host_build_contract  # type: ignore[no-redef]


ROOT = Path(__file__).resolve().parents[1]
CATALOG_RELATIVE = "firmware/host-build/hp5_5/catalog.json"
CATALOG = ROOT / CATALOG_RELATIVE
INTENT = ROOT / "tests/hardware-in-loop/hp5_5-network-admin/target-intent.json"
OUTPUT_ROOT = ROOT / "firmware/host-build/hp5_5"
BOARD_IDS = (
    "aitrip-esp32s3-devkitc-1-n8r2",
    "seeed-xiao-esp32c6-4m",
)
HISTORICAL_IDENTITIES = {
    "firmware/host-build/locks/aitrip-esp32s3-devkitc-1-n8r2.json":
        "0a350b20da06d3626aa0809cfb004b3e35fc75e35b2477504c3cb8da6ecbdc9b",
    "firmware/host-build/locks/seeed-xiao-esp32c6-4m.json":
        "52406d9d00dbc7e4020ce743716eefc63e29a2d2663a8ed73f552b63641b8130",
    "firmware/host-build/fingerprints/aitrip-esp32s3-devkitc-1-n8r2.json":
        "2ac184770ef7c5134b10b24b9fa52f233d1a1da158ccf71838a7137afddf060e",
    "firmware/host-build/fingerprints/seeed-xiao-esp32c6-4m.json":
        "a5be5350db62f77b22757ad558a7703726f9a6b02b24598552169052255d8638",
}


class ResolutionError(RuntimeError):
    """Raised when an HP5.5 target contract is absent or incoherent."""


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def expected_contracts() -> dict[str, dict[str, dict[str, Any]]]:
    catalog = host_build_contract.load_json(CATALOG)
    intent = host_build_contract.load_json(INTENT)
    host_build_contract.validate_catalog(catalog, ROOT)
    host_build_contract.validate_intent(intent)
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for board_id in BOARD_IDS:
        plan = host_build_contract.make_plan(intent, board_id, catalog, ROOT)
        lock = host_build_contract.make_lock_from_plan(
            plan,
            catalog,
            ROOT,
            catalog_relative=CATALOG_RELATIVE,
        )
        fingerprint = host_build_contract.make_fingerprint(lock, ROOT)
        result[board_id] = {
            "plan": plan,
            "lock": lock,
            "fingerprint": fingerprint,
        }
    return result


def _paths(board_id: str) -> dict[str, Path]:
    return {
        "plan": OUTPUT_ROOT / "plans" / f"{board_id}.json",
        "lock": OUTPUT_ROOT / "locks" / f"{board_id}.json",
        "fingerprint": OUTPUT_ROOT / "fingerprints" / f"{board_id}.json",
    }


def verify_historical() -> None:
    for relative, expected in HISTORICAL_IDENTITIES.items():
        path = ROOT / relative
        if host_build_contract.sha256_file(path) != expected:
            raise ResolutionError(f"historical HP2 authority changed: {relative}")


def generate() -> dict[str, Any]:
    verify_historical()
    contracts = expected_contracts()
    for board_id, artifacts in contracts.items():
        for kind, value in artifacts.items():
            path = _paths(board_id)[kind]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(_json_bytes(value))
    return verify()


def verify() -> dict[str, Any]:
    verify_historical()
    contracts = expected_contracts()
    lanes: list[dict[str, Any]] = []
    for board_id, artifacts in contracts.items():
        paths = _paths(board_id)
        for kind, expected in artifacts.items():
            path = paths[kind]
            if not path.is_file() or path.read_bytes() != _json_bytes(expected):
                raise ResolutionError(f"HP5.5 {kind} drifted: {board_id}")
        lock = artifacts["lock"]
        fingerprint = artifacts["fingerprint"]
        host_build_contract.replay_lock(lock, fingerprint, ROOT)
        if (
            fingerprint["compatibility_surface"]["abi_authority_sha256"]
            != "104753f70693b895afcf33e5a897f09ffec8f63988414c1784f56b8a7fa26f1b"
        ):
            raise ResolutionError("HP5.5 fingerprint does not realize the HP5 ABI")
        lanes.append(
            {
                "board_id": board_id,
                "target": fingerprint["compatibility_surface"]["target"],
                "plan_sha256": artifacts["plan"]["plan_sha256"],
                "lock_sha256": host_build_contract.canonical_sha256(lock),
                "fingerprint_sha256": fingerprint["fingerprint_sha256"],
            }
        )
    return {
        "schema": "pulse.esp32.hp5_5-target-contract-resolution.v1",
        "status": "PASS",
        "historical_hp2_authorities_unchanged": True,
        "lanes": lanes,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("generate", "verify"))
    args = parser.parse_args(argv)
    try:
        report = generate() if args.command == "generate" else verify()
    except (OSError, ValueError, json.JSONDecodeError, ResolutionError) as exc:
        print(f"HP5.5 target-contract resolution failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
