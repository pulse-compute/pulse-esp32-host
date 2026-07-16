#!/usr/bin/env python3
"""Pack, inspect, install, and activate WDC bundle containers."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import shutil
import struct
from pathlib import Path
from typing import Any

MAGIC = b"WDCBNDL\0"
VERSION = 1
HEADER_LEN = 120
SIG_NONE = 0
SIG_HMAC_SHA256_DEV = 1
SIG_ED25519 = 2
ED25519_SIG_LEN = 64
DEFAULT_DEV_KEY = b"wdc-dev-bundle-signing-key-r6"
DEFAULT_PROD_TEST_KEY_ID = "prod-test-r9"
PROD_TEST_CONTEXT = b"WDC-R9-ED25519-TEST-VECTOR"
REQUIRED_EXPORTS = [
    "wdc_module_init",
    "wdc_module_on_event",
    "wdc_module_health",
    "wdc_module_shutdown",
]


def _read_u32_leb(data: bytes, offset: int, limit: int) -> tuple[int, int]:
    result = 0
    shift = 0
    for _ in range(5):
        if offset >= limit:
            raise ValueError("truncated LEB128")
        byte = data[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, offset
        shift += 7
    raise ValueError("invalid LEB128")


def wasm_exported_functions(payload: bytes) -> set[str]:
    if len(payload) < 8 or payload[:4] != b"\0asm" or payload[4:8] != b"\x01\0\0\0":
        return set()
    exports: set[str] = set()
    offset = 8
    previous_non_custom = 0
    try:
        while offset < len(payload):
            section_id = payload[offset]
            offset += 1
            section_len, offset = _read_u32_leb(payload, offset, len(payload))
            section_end = offset + section_len
            if section_end > len(payload):
                return set()
            if section_id != 0:
                if section_id <= previous_non_custom:
                    return set()
                previous_non_custom = section_id
            if section_id == 7:
                sec_off = offset
                count, sec_off = _read_u32_leb(payload, sec_off, section_end)
                for _ in range(count):
                    name_len, sec_off = _read_u32_leb(payload, sec_off, section_end)
                    if sec_off + name_len > section_end:
                        return set()
                    name = payload[sec_off : sec_off + name_len].decode("utf-8", errors="strict")
                    sec_off += name_len
                    if sec_off >= section_end:
                        return set()
                    kind = payload[sec_off]
                    sec_off += 1
                    _index, sec_off = _read_u32_leb(payload, sec_off, section_end)
                    if kind == 0:
                        exports.add(name)
            offset = section_end
    except (UnicodeDecodeError, ValueError):
        return set()
    return exports


def has_required_exports(payload: bytes) -> bool:
    exports = wasm_exported_functions(payload)
    return all(name in exports for name in REQUIRED_EXPORTS)



def signature_alg_name(sig_alg: int) -> str:
    if sig_alg == SIG_NONE:
        return "none"
    if sig_alg == SIG_HMAC_SHA256_DEV:
        return "hmac-sha256-dev"
    if sig_alg == SIG_ED25519:
        return "ed25519"
    return "unknown"


def production_test_signature(header: bytes, manifest: bytes, payload: bytes, key_id: str) -> bytes:
    # Deterministic R9 test-vector verifier. This is not a cryptographic
    # Ed25519 implementation; firmware production mode still requires a
    # verifier callback to be installed. The test vector lets CI exercise
    # fail-closed production-policy plumbing without external crypto deps.
    first = hashlib.sha256(PROD_TEST_CONTEXT + key_id.encode("utf-8") + header + manifest + payload).digest()
    second = hashlib.sha256(PROD_TEST_CONTEXT + b"/2/" + first).digest()
    return first + second


def verify_production_test_signature(header: bytes, manifest: bytes, payload: bytes, signature: bytes, key_id: str) -> bool:
    if not key_id.startswith("prod-") or len(signature) != ED25519_SIG_LEN:
        return False
    return hmac.compare_digest(production_test_signature(header, manifest, payload, key_id), signature)

def canonical_json_bytes(obj: dict[str, Any]) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def header_pack(manifest: bytes, payload: bytes, sig_alg: int, sig_len: int) -> bytes:
    manifest_hash = hashlib.sha256(manifest).digest()
    payload_hash = hashlib.sha256(payload).digest()
    return struct.pack(
        "<8sHHII32s32sHH32s",
        MAGIC,
        VERSION,
        HEADER_LEN,
        len(manifest),
        len(payload),
        manifest_hash,
        payload_hash,
        sig_alg,
        sig_len,
        bytes(32),
    )


def header_unpack(data: bytes) -> dict[str, Any]:
    if len(data) < HEADER_LEN:
        raise ValueError("bundle shorter than header")
    magic, version, header_len, manifest_len, payload_len, manifest_hash, payload_hash, sig_alg, sig_len, _reserved = struct.unpack(
        "<8sHHII32s32sHH32s", data[:HEADER_LEN]
    )
    if magic != MAGIC:
        raise ValueError("invalid magic")
    if version != VERSION or header_len != HEADER_LEN:
        raise ValueError("unsupported container version/header length")
    manifest_offset = header_len
    payload_offset = manifest_offset + manifest_len
    signature_offset = payload_offset + payload_len
    total_len = signature_offset + sig_len
    if total_len > len(data):
        raise ValueError("bundle truncated")
    if total_len != len(data):
        raise ValueError("bundle has trailing unsigned bytes")
    return {
        "version": version,
        "header_len": header_len,
        "manifest_len": manifest_len,
        "payload_len": payload_len,
        "manifest_sha256": manifest_hash,
        "payload_sha256": payload_hash,
        "signature_alg": sig_alg,
        "signature_len": sig_len,
        "manifest_offset": manifest_offset,
        "payload_offset": payload_offset,
        "signature_offset": signature_offset,
        "total_len": total_len,
    }


def patch_manifest(manifest: dict[str, Any], payload: bytes, alg_name: str, key_id: str) -> dict[str, Any]:
    out = json.loads(json.dumps(manifest))
    out.setdefault("payload", {})
    out["payload"]["sha256"] = hashlib.sha256(payload).hexdigest()
    out["payload"]["size_bytes"] = len(payload)
    out.setdefault("signature", {})
    out["signature"]["alg"] = alg_name
    out["signature"]["key_id"] = key_id
    out["signature"]["value"] = "container-signature"
    return out


def sign(header: bytes, manifest: bytes, payload: bytes, alg: int, key: bytes, key_id: str = DEFAULT_PROD_TEST_KEY_ID) -> bytes:
    if alg == SIG_NONE:
        return b""
    if alg == SIG_HMAC_SHA256_DEV:
        return hmac.new(key, header + manifest + payload, hashlib.sha256).digest()
    if alg == SIG_ED25519:
        return production_test_signature(header, manifest, payload, key_id)
    raise ValueError(f"unsupported signature algorithm: {alg}")


def verify_bytes(data: bytes, key: bytes = DEFAULT_DEV_KEY, production: bool = False, allow_unsigned_dev: bool = False, test_production_verifier: bool = False) -> dict[str, Any]:
    try:
        h = header_unpack(data)
    except Exception as exc:  # noqa: BLE001 - CLI diagnostic
        return {"status": "FAIL", "reason": str(exc)}

    manifest = data[h["manifest_offset"] : h["payload_offset"]]
    payload = data[h["payload_offset"] : h["signature_offset"]]
    signature = data[h["signature_offset"] : h["total_len"]]
    manifest_hash_ok = hashlib.sha256(manifest).digest() == h["manifest_sha256"]
    payload_hash = hashlib.sha256(payload).digest()
    payload_hash_ok = payload_hash == h["payload_sha256"]

    sig_alg = h["signature_alg"]
    manifest_key_id = ""
    manifest_alg = ""

    if sig_alg == SIG_NONE:
        signature_ok = bool(allow_unsigned_dev and not production and h["signature_len"] == 0)
    elif sig_alg == SIG_HMAC_SHA256_DEV and not production and h["signature_len"] == 32:
        signature_ok = hmac.compare_digest(sign(data[:HEADER_LEN], manifest, payload, sig_alg, key), signature)
    elif sig_alg == SIG_ED25519 and production and h["signature_len"] == ED25519_SIG_LEN:
        signature_ok = bool(test_production_verifier)
    else:
        signature_ok = False

    try:
        manifest_json = json.loads(manifest.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        manifest_json = None
        manifest_error = str(exc)
    else:
        manifest_error = None

    required_exports_ok = has_required_exports(payload)
    manifest_payload_binding_ok = False
    abi_ok = False
    manifest_signature_alg_ok = False
    production_key_id_ok = False
    if isinstance(manifest_json, dict):
        payload_info = manifest_json.get("payload", {})
        manifest_payload_binding_ok = payload_info.get("sha256") == payload_hash.hex() and payload_info.get("size_bytes") == len(payload)
        abi = manifest_json.get("abi", {})
        abi_ok = abi.get("major") == 1 and abi.get("min_minor", 999) <= 0 <= abi.get("max_minor", -1)
        sig_info = manifest_json.get("signature", {})
        manifest_alg = str(sig_info.get("alg", ""))
        manifest_key_id = str(sig_info.get("key_id", ""))
        manifest_signature_alg_ok = manifest_alg == signature_alg_name(sig_alg)
        production_key_id_ok = manifest_key_id.startswith("prod-") if sig_alg == SIG_ED25519 else True
        if sig_alg == SIG_ED25519 and production and test_production_verifier:
            signature_ok = verify_production_test_signature(data[:HEADER_LEN], manifest, payload, signature, manifest_key_id)

    checks = {
        "manifest_hash_ok": manifest_hash_ok,
        "payload_hash_ok": payload_hash_ok,
        "manifest_payload_binding_ok": manifest_payload_binding_ok,
        "signature_ok": signature_ok,
        "manifest_signature_alg_ok": manifest_signature_alg_ok,
        "production_key_id_ok": production_key_id_ok,
        "required_exports_ok": required_exports_ok,
        "abi_ok": abi_ok,
        "manifest_parse_ok": manifest_error is None,
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    return {
        "status": status,
        "reason": "bundle verified" if status == "PASS" else "one or more verification checks failed",
        "header": {
            "container_version": h["version"],
            "header_len": h["header_len"],
            "manifest_len": h["manifest_len"],
            "payload_len": h["payload_len"],
            "signature_alg": sig_alg,
            "signature_alg_name": signature_alg_name(sig_alg),
            "signature_len": h["signature_len"],
            "total_len": h["total_len"],
        },
        "checks": checks,
        "manifest_error": manifest_error,
        "manifest": manifest_json,
    }


def default_meta() -> dict[str, Any]:
    return {
        "active_slot": "none",
        "last_good_slot": "none",
        "slot_a_state": "empty",
        "slot_b_state": "empty",
        "slot_a_version": 0,
        "slot_b_version": 0,
        "slot_a_security_counter": 0,
        "slot_b_security_counter": 0,
        "candidate_boot_count": 0,
        "candidate_fault_count": 0,
        "last_failure_reason": 0,
        "metadata_generation": 0,
    }


def meta_path(slots_dir: Path) -> Path:
    return slots_dir / "wasm_meta.json"


def load_meta(slots_dir: Path) -> dict[str, Any]:
    path = meta_path(slots_dir)
    meta = default_meta()
    if path.exists():
        meta.update(json.loads(path.read_text(encoding="utf-8")))
    return meta


def save_meta(slots_dir: Path, meta: dict[str, Any]) -> Path:
    slots_dir.mkdir(parents=True, exist_ok=True)
    meta["metadata_generation"] = int(meta.get("metadata_generation", 0)) + 1
    path = meta_path(slots_dir)
    path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def normalize_slot(slot: str) -> str:
    slot = slot.lower()
    if slot in {"a", "wasm_a", "slot_a"}:
        return "a"
    if slot in {"b", "wasm_b", "slot_b"}:
        return "b"
    if slot == "none":
        return "none"
    raise ValueError("slot must be a, b, wasm_a, wasm_b, or none")


def slot_state_key(slot: str) -> str:
    return "slot_a_state" if slot == "a" else "slot_b_state"


def slot_version_key(slot: str) -> str:
    return "slot_a_version" if slot == "a" else "slot_b_version"


def slot_counter_key(slot: str) -> str:
    return "slot_a_security_counter" if slot == "a" else "slot_b_security_counter"


def other_slot(slot: str) -> str:
    return "b" if slot == "a" else "a"


def slot_is_confirmed(meta: dict[str, Any], slot: str) -> bool:
    return slot in {"a", "b"} and meta.get(slot_state_key(slot)) == "confirmed"


def choose_fallback(meta: dict[str, Any], failed_slot: str = "none") -> str:
    last_good = normalize_slot(str(meta.get("last_good_slot", "none")))
    if last_good != failed_slot and slot_is_confirmed(meta, last_good):
        return last_good
    if failed_slot in {"a", "b"}:
        alt = other_slot(failed_slot)
        if slot_is_confirmed(meta, alt):
            return alt
    for slot in ("a", "b"):
        if slot_is_confirmed(meta, slot):
            return slot
    return "none"


def activation_report(status: str, decision: str, meta: dict[str, Any], reason: str, selected_slot: str = "none", failed_slot: str = "none", probation: bool = False) -> dict[str, Any]:
    return {
        "status": status,
        "decision": decision,
        "selected_slot": selected_slot,
        "slot_to_run": selected_slot,
        "failed_slot": failed_slot,
        "probation": probation,
        "reason": reason,
        "metadata": meta,
    }


def cmd_pack(args: argparse.Namespace) -> int:
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    payload = Path(args.payload).read_bytes()
    if args.production_test or args.fake_ed25519:
        alg = SIG_ED25519
        alg_name = "ed25519"
        if args.key_id == "dev-r6":
            args.key_id = DEFAULT_PROD_TEST_KEY_ID
    else:
        alg = SIG_NONE if args.unsigned_dev else SIG_HMAC_SHA256_DEV
        alg_name = "none" if args.unsigned_dev else "hmac-sha256-dev"
    key = args.key.encode("utf-8") if args.key else DEFAULT_DEV_KEY
    patched = patch_manifest(manifest, payload, alg_name, args.key_id)
    manifest_bytes = canonical_json_bytes(patched)
    sig_len = 0 if alg == SIG_NONE else ED25519_SIG_LEN if alg == SIG_ED25519 else 32
    header = header_pack(manifest_bytes, payload, alg, sig_len)
    sig = sign(header, manifest_bytes, payload, alg, key, args.key_id)
    bundle = header + manifest_bytes + payload + sig
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_bytes(bundle)
    if args.manifest_out:
        Path(args.manifest_out).write_text(json.dumps(patched, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "out": args.out, "bytes": len(bundle), "payload_sha256": hashlib.sha256(payload).hexdigest()}, indent=2))
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    key = args.key.encode("utf-8") if args.key else DEFAULT_DEV_KEY
    result = verify_bytes(Path(args.bundle).read_bytes(), key=key, production=args.production, allow_unsigned_dev=args.allow_unsigned_dev, test_production_verifier=args.test_production_verifier)
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result.get("status") == "PASS" or args.allow_fail else 1


def cmd_install(args: argparse.Namespace) -> int:
    slot = normalize_slot(args.slot)
    if slot not in {"a", "b"}:
        raise SystemExit("slot must be a or b")
    data = Path(args.bundle).read_bytes()
    key = args.key.encode("utf-8") if args.key else DEFAULT_DEV_KEY
    production = getattr(args, "production", False)
    test_production_verifier = getattr(args, "test_production_verifier", False)
    result = verify_bytes(data, key=key, production=production, test_production_verifier=test_production_verifier)
    if result.get("status") != "PASS" and not args.allow_unverified:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1
    slots_dir = Path(args.slots_dir)
    slots_dir.mkdir(parents=True, exist_ok=True)
    slot_file = slots_dir / f"wasm_{slot}.wdcb"
    shutil.copyfile(args.bundle, slot_file)
    meta = load_meta(slots_dir)
    meta[slot_state_key(slot)] = "verified" if result.get("status") == "PASS" else "downloaded"
    manifest = result.get("manifest") if isinstance(result.get("manifest"), dict) else {}
    meta[slot_version_key(slot)] = manifest.get("bundle_version", 0)
    meta[slot_counter_key(slot)] = manifest.get("security_counter", 0)
    path = save_meta(slots_dir, meta)
    print(json.dumps({"status": "PASS", "slot_file": str(slot_file), "metadata": str(path)}, indent=2))
    return 0


def cmd_activate(args: argparse.Namespace) -> int:
    slot = normalize_slot(args.slot)
    if slot not in {"a", "b"}:
        raise SystemExit("slot must be a or b")
    slots_dir = Path(args.slots_dir)
    meta = load_meta(slots_dir)
    state = meta.get(slot_state_key(slot), "empty")
    if state not in {"verified", "confirmed"}:
        result = activation_report("FAIL", "activation_rejected", meta, f"slot_{slot} state {state!r} is not verified/confirmed", slot)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if args.allow_fail else 1
    fallback = choose_fallback(meta, failed_slot=slot)
    if fallback in {"a", "b"}:
        meta["last_good_slot"] = fallback
    if state == "verified":
        meta[slot_state_key(slot)] = "pending"
    meta["active_slot"] = slot
    meta["candidate_boot_count"] = 0
    meta["candidate_fault_count"] = 0
    meta["last_failure_reason"] = 0
    save_meta(slots_dir, meta)
    print(json.dumps(activation_report("PASS", "slot_marked_pending", meta, "slot marked pending for reboot activation", slot), indent=2, sort_keys=True))
    return 0


def cmd_boot(args: argparse.Namespace) -> int:
    slots_dir = Path(args.slots_dir)
    meta = load_meta(slots_dir)
    active = normalize_slot(str(meta.get("active_slot", "none")))
    selected = "none"
    failed_slot = "none"
    probation = False
    decision = "no_bundle"
    reason = "no bootable bundle slot"
    changed = False

    if active in {"a", "b"}:
        state = meta.get(slot_state_key(active), "empty")
        if state == "confirmed":
            selected = active
            decision = "run_active"
            reason = "confirmed slot selected"
            if meta.get("last_good_slot") != active:
                meta["last_good_slot"] = active
                changed = True
        elif state == "pending":
            boot_count = int(meta.get("candidate_boot_count", 0))
            if boot_count >= int(args.max_candidate_boots):
                meta[slot_state_key(active)] = "failed"
                failed_slot = active
                meta["candidate_boot_count"] = 0
                meta["candidate_fault_count"] = int(meta.get("candidate_fault_count", 0)) + 1
                meta["last_failure_reason"] = -11
                fallback = choose_fallback(meta, active)
                meta["active_slot"] = fallback
                selected = fallback
                failed_slot = active
                decision = "rollback_to_last_good" if fallback != "none" else "candidate_failed"
                reason = "candidate exceeded boot-attempt budget; rolled back" if fallback != "none" else "candidate exceeded boot-attempt budget; no fallback"
                if fallback != "none":
                    meta["last_good_slot"] = fallback
                changed = True
            else:
                meta["candidate_boot_count"] = boot_count + 1
                meta[slot_state_key(active)] = "running_pending"
                selected = active
                probation = True
                decision = "boot_pending"
                reason = "pending candidate selected for probation"
                probation = True
                changed = True
        elif state == "running_pending":
            meta[slot_state_key(active)] = "failed"
            failed_slot = active
            meta["candidate_boot_count"] = 0
            meta["candidate_fault_count"] = int(meta.get("candidate_fault_count", 0)) + 1
            meta["last_failure_reason"] = -18
            fallback = choose_fallback(meta, active)
            meta["active_slot"] = fallback
            selected = fallback
            failed_slot = active
            decision = "rollback_to_last_good" if fallback != "none" else "candidate_failed"
            reason = "previous candidate reset during probation; rolled back" if fallback != "none" else "previous candidate reset during probation; no fallback"
            if fallback != "none":
                meta["last_good_slot"] = fallback
            changed = True

    if decision == "no_bundle":
        fallback = choose_fallback(meta, failed_slot="none")
        if fallback in {"a", "b"}:
            meta["active_slot"] = fallback
            meta["last_good_slot"] = fallback
            selected = fallback
            decision = "rollback_to_last_good"
            reason = "last_good confirmed slot selected"
            changed = True
        elif args.write_no_bundle:
            meta["active_slot"] = "none"
            changed = True

    if changed:
        save_meta(slots_dir, meta)
    print(json.dumps(activation_report("PASS", decision, meta, reason, selected, failed_slot, probation), indent=2, sort_keys=True))
    return 0


def cmd_confirm(args: argparse.Namespace) -> int:
    slots_dir = Path(args.slots_dir)
    meta = load_meta(slots_dir)
    slot = normalize_slot(args.slot) if args.slot else normalize_slot(str(meta.get("active_slot", "none")))
    if slot not in {"a", "b"}:
        result = activation_report("FAIL", "confirm_rejected", meta, "no active slot to confirm", "none")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if args.allow_fail else 1
    state = meta.get(slot_state_key(slot), "empty")
    if meta.get("active_slot") != slot or state not in {"pending", "running_pending", "confirmed"}:
        result = activation_report("FAIL", "confirm_rejected", meta, f"slot_{slot} is not active pending/running_pending", slot)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if args.allow_fail else 1
    meta[slot_state_key(slot)] = "confirmed"
    meta["active_slot"] = slot
    meta["last_good_slot"] = slot
    meta["candidate_boot_count"] = 0
    meta["candidate_fault_count"] = 0
    meta["last_failure_reason"] = 0
    save_meta(slots_dir, meta)
    print(json.dumps(activation_report("PASS", "confirmed", meta, "candidate confirmed healthy", slot), indent=2, sort_keys=True))
    return 0


def cmd_fail(args: argparse.Namespace) -> int:
    slots_dir = Path(args.slots_dir)
    meta = load_meta(slots_dir)
    slot = normalize_slot(args.slot) if args.slot else normalize_slot(str(meta.get("active_slot", "none")))
    if slot not in {"a", "b"}:
        result = activation_report("FAIL", "fail_rejected", meta, "no active slot to fail", "none")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if args.allow_fail else 1
    meta[slot_state_key(slot)] = "failed"
    meta["candidate_boot_count"] = 0
    meta["candidate_fault_count"] = int(meta.get("candidate_fault_count", 0)) + 1
    meta["last_failure_reason"] = int(args.failure_reason)
    fallback = choose_fallback(meta, slot)
    meta["active_slot"] = fallback
    if fallback != "none":
        meta["last_good_slot"] = fallback
    save_meta(slots_dir, meta)
    decision = "rollback_to_last_good" if fallback != "none" else "candidate_failed"
    reason = "candidate failed; rolled back to last_good" if fallback != "none" else "candidate failed; no fallback"
    print(json.dumps(activation_report("PASS", decision, meta, reason, fallback, slot), indent=2, sort_keys=True))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    meta = load_meta(Path(args.slots_dir))
    print(json.dumps(activation_report("PASS", "status", meta, "metadata loaded", str(meta.get("active_slot", "none"))), indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    pack = sub.add_parser("pack")
    pack.add_argument("--manifest", required=True)
    pack.add_argument("--payload", required=True)
    pack.add_argument("--out", required=True)
    pack.add_argument("--manifest-out")
    pack.add_argument("--key", default=None)
    pack.add_argument("--key-id", default="dev-r6")
    pack.add_argument("--unsigned-dev", action="store_true")
    pack.add_argument("--fake-ed25519", action="store_true", help="emit a test-only ed25519-shaped signature; native production still requires a verifier hook")
    pack.add_argument("--production-test", action="store_true", help="create an R9 production-policy test-vector bundle using header alg ed25519")
    pack.set_defaults(func=cmd_pack)

    inspect = sub.add_parser("inspect")
    inspect.add_argument("--bundle", required=True)
    inspect.add_argument("--json-out")
    inspect.add_argument("--key", default=None)
    inspect.add_argument("--production", action="store_true")
    inspect.add_argument("--allow-unsigned-dev", action="store_true")
    inspect.add_argument("--test-production-verifier", action="store_true", help="enable the deterministic R9 production test-vector verifier")
    inspect.add_argument("--allow-fail", action="store_true")
    inspect.set_defaults(func=cmd_inspect)

    install = sub.add_parser("install")
    install.add_argument("--bundle", required=True)
    install.add_argument("--slot", required=True)
    install.add_argument("--slots-dir", required=True)
    install.add_argument("--key", default=None)
    install.add_argument("--production", action="store_true")
    install.add_argument("--test-production-verifier", action="store_true")
    install.add_argument("--allow-unverified", action="store_true")
    install.set_defaults(func=cmd_install)

    activate = sub.add_parser("activate")
    activate.add_argument("--slot", required=True)
    activate.add_argument("--slots-dir", required=True)
    activate.add_argument("--allow-fail", action="store_true")
    activate.set_defaults(func=cmd_activate)

    boot = sub.add_parser("boot")
    boot.add_argument("--slots-dir", required=True)
    boot.add_argument("--max-candidate-boots", "--max-boots", dest="max_candidate_boots", type=int, default=1)
    boot.add_argument("--write-no-bundle", action="store_true")
    boot.set_defaults(func=cmd_boot)

    confirm = sub.add_parser("confirm")
    confirm.add_argument("--slots-dir", required=True)
    confirm.add_argument("--slot")
    confirm.add_argument("--allow-fail", action="store_true")
    confirm.set_defaults(func=cmd_confirm)

    fail = sub.add_parser("fail")
    fail.add_argument("--slots-dir", required=True)
    fail.add_argument("--slot")
    fail.add_argument("--failure-reason", "--reason", dest="failure_reason", type=int, default=-15)
    fail.add_argument("--allow-fail", action="store_true")
    fail.set_defaults(func=cmd_fail)

    status = sub.add_parser("status")
    status.add_argument("--slots-dir", required=True)
    status.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
