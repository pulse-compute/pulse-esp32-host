#!/usr/bin/env python3
"""Explicit HP2 host plan, lock, replay, and compatibility operations."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

try:
    from tools import host_build_contract
except ModuleNotFoundError:  # Direct execution from tools/.
    import host_build_contract  # type: ignore[no-redef]


def _write_optional(path: Optional[Path], value: dict[str, object]) -> None:
    if path is not None:
        host_build_contract.write_json_new(path, value)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog",
        type=Path,
        default=host_build_contract.DEFAULT_CATALOG,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan")
    plan.add_argument("--intent", type=Path, required=True)
    plan.add_argument("--board", required=True)
    plan.add_argument("--running-fingerprint", type=Path)
    plan.add_argument("--out", type=Path)

    resolve = subparsers.add_parser("resolve-new-lock")
    resolve.add_argument("--plan", type=Path, required=True)
    resolve.add_argument("--out-lock", type=Path, required=True)
    resolve.add_argument("--out-fingerprint", type=Path, required=True)

    replay = subparsers.add_parser("replay-lock")
    replay.add_argument("--lock", type=Path, required=True)
    replay.add_argument("--fingerprint", type=Path)
    replay.add_argument("--out-fingerprint", type=Path)

    check = subparsers.add_parser("check-running")
    check.add_argument("--intent", type=Path, required=True)
    check.add_argument("--fingerprint", type=Path, required=True)
    check.add_argument("--out", type=Path)

    generate = subparsers.add_parser("generate-c")
    generate.add_argument("--out", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    try:
        catalog = host_build_contract.load_json(args.catalog)
        if args.command == "plan":
            intent = host_build_contract.load_json(args.intent)
            running = (
                host_build_contract.load_json(args.running_fingerprint)
                if args.running_fingerprint is not None
                else None
            )
            result = host_build_contract.make_plan(
                intent, args.board, catalog, running_fingerprint=running
            )
            _write_optional(args.out, result)
        elif args.command == "resolve-new-lock":
            plan = host_build_contract.load_json(args.plan)
            lock = host_build_contract.make_lock_from_plan(plan, catalog)
            fingerprint = host_build_contract.make_fingerprint(lock)
            # Both destinations must be fresh before either artifact is written.
            if args.out_lock.expanduser().resolve().exists() or args.out_fingerprint.expanduser().resolve().exists():
                raise host_build_contract.HostBuildContractError(
                    "new-lock resolution refuses an existing output"
                )
            host_build_contract.write_json_new(args.out_lock, lock)
            host_build_contract.write_json_new(args.out_fingerprint, fingerprint)
            result = {
                "schema": "pulse.esp32.host-lock-resolution.v1",
                "status": "PASS",
                "operation": "EXPLICIT_NEW_LOCK",
                "host_plan_sha256": lock["host_plan_sha256"],
                "build_lock_sha256": fingerprint["build_lock_sha256"],
                "fingerprint_sha256": fingerprint["fingerprint_sha256"],
            }
        elif args.command == "replay-lock":
            lock = host_build_contract.load_json(args.lock)
            expected = (
                host_build_contract.load_json(args.fingerprint)
                if args.fingerprint is not None
                else None
            )
            fingerprint = host_build_contract.replay_lock(lock, expected)
            _write_optional(args.out_fingerprint, fingerprint)
            result = {
                "schema": "pulse.esp32.host-lock-replay.v1",
                "status": "PASS",
                "operation": "EXACT_LOCK_REPLAY",
                "build_lock_sha256": fingerprint["build_lock_sha256"],
                "fingerprint_sha256": fingerprint["fingerprint_sha256"],
                "silent_upgrade": False,
            }
        elif args.command == "check-running":
            intent = host_build_contract.load_json(args.intent)
            fingerprint = host_build_contract.load_json(args.fingerprint)
            result = host_build_contract.check_running(intent, fingerprint)
            _write_optional(args.out, result)
        else:
            destination = args.out.expanduser().resolve()
            if destination.exists():
                raise host_build_contract.HostBuildContractError(
                    "generated C output already exists"
                )
            rendered = host_build_contract.render_generated_c(catalog)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(rendered, encoding="utf-8")
            result = {
                "schema": "pulse.esp32.host-fingerprint-c-generation.v1",
                "status": "PASS",
                "operation": "DERIVE_FROM_EXACT_LOCKS",
                "output": str(destination),
            }
    except (OSError, ValueError, host_build_contract.HostBuildContractError) as exc:
        print("HP2 host-build operation failed: %s" % exc, file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("status", "PASS") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
