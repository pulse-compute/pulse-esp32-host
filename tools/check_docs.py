#!/usr/bin/env python3
"""Documentation integrity checks for the Pulse ESP32 host.

The checker is dependency-free. It verifies the canonical external-facing
Markdown set and resolves local Markdown links inside the repository.
Generated report material is excluded.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import unquote

REQUIRED = [
    "README.md",
    "CHANGELOG.md",
    "docs/README.md",
    "docs/ARCHITECTURE.md",
    "docs/TRUST_BOUNDARY.md",
    "docs/STATUS.md",
    "docs/BUILD_AND_TEST.md",
    "docs/PACKAGING_AND_EVIDENCE.md",
    "docs/HP1_HOST_KERNEL_RESOURCE_AUTHORITY.md",
    "docs/HP2_HOST_BUILD_COHERENCE.md",
    "docs/HP3_APPLICATION_SLOTS_AND_FALLBACK.md",
    "docs/HP3_5_APPLICATION_SLOT_ADVERSARIAL_SEAL.md",
    "docs/HP4_0_PROTECTED_ADMINISTRATION_CONTRACT.md",
    "docs/HP4_1_PROTECTED_ADMINISTRATION_CORE.md",
    "docs/HP4_2_EXCLUSIVE_UPDATE_TRANSACTION.md",
    "docs/HP4_3_HOST_ONLY_RECOVERY.md",
    "docs/HP4_4_ADMINISTRATION_ADVERSARIAL_SEAL.md",
    "docs/HP5_HOST_NETWORK_MEDIATOR.md",
    "docs/HX1_ELF_LOADER_QUALIFICATION.md",
    "docs/HX2_EXTENSION_ADMISSION.md",
    "docs/HX3_EXTENSION_LIFECYCLE.md",
    "docs/HX4_5_S3_AITRIP_HARDWARE.md",
    "docs/HX4_5_C6_XIAO_HARDWARE.md",
    "docs/HX5A_EXTENSION_FAULT_HARDENING.md",
    "docs/TESTING.md",
    "docs/CODEBASE_MAP.md",
    "docs/NETWORK_MEDIATION.md",
    "docs/DIAGNOSTICS.md",
    "docs/TROUBLESHOOTING.md",
    "docs/reference/ABI_REFERENCE.md",
    "docs/reference/BUNDLE_AND_ACTIVATION.md",
    "docs/reference/COMPONENT_MAP.md",
    "docs/reference/DEVICE_PROFILE_AND_CAPABILITIES.md",
    "docs/reference/GLOSSARY.md",
    "docs/reference/GUEST_APP_DEVELOPER_GUIDE.md",
    "docs/reference/IDF_FAMILY_MATRIX.md",
    "docs/reference/RUNTIME_LIMITS.md",
    "docs/reference/SECURITY_PROFILE.md",
    "docs/runbooks/LOCAL_BRINGUP.md",
    "docs/runbooks/HARDWARE_BRINGUP.md",
    "docs/runbooks/FIELD_OPERATIONS.md",
    "docs/runbooks/PRODUCTION_RELEASE_CHECKLIST.md",
    "docs/adr/0001-native-supervisor-boundary.md",
    "docs/adr/0002-dispatcher-based-abi.md",
    "docs/adr/0003-logical-resources-and-capabilities.md",
    "docs/adr/0004-reboot-based-activation.md",
    "docs/adr/0005-native-network-mediation.md",
    "docs/adr/0006-deterministic-cbor-subset.md",
    "docs/adr/0007-fail-closed-host-call-authorization.md",
    "docs/adr/0008-production-verifier-contract.md",
    "docs/adr/0009-idf-family-build-matrix.md",
    "docs/adr/0010-native-extension-loader-and-abi.md",
    "docs/adr/0011-host-build-coherence-and-fingerprint.md",
    "docs/adr/0012-application-slots-and-host-owned-confirmation.md",
    "docs/adr/0013-application-slot-interruption-authority.md",
    "docs/adr/0014-protected-host-administration-authority.md",
    "docs/adr/0015-host-owned-http-ingress.md",
    "specs/PULSE-ESP32-003-native-target-refinement-addendum.md",
    "specs/PULSE-ESP32-004-host-extension-spine.md",
    "specs/PULSE-ESP32-006-host-kernel-resource-authority.json",
    "specs/PULSE-ESP32-007-host-build-coherence.json",
    "specs/PULSE-ESP32-008-application-slots.json",
    "specs/PULSE-ESP32-008a-application-slot-adversarial-seal.json",
    "specs/PULSE-ESP32-009-protected-administration.json",
    "specs/PULSE-ESP32-010-protected-administration-core.json",
    "specs/PULSE-ESP32-011-exclusive-update-transaction.json",
    "specs/PULSE-ESP32-012-host-only-recovery.json",
    "specs/PULSE-ESP32-013-administration-adversarial-seal.json",
    "specs/PULSE-ESP32-014-host-network-mediator.json",
    "evidence/README.md",
    "evidence/host-extension/INDEX.md",
    "evidence/hardware/README.md",
]

LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def strip_code_fences(text: str) -> str:
    lines = []
    in_fence = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            lines.append(line)
    return "\n".join(lines)


def is_external(target: str) -> bool:
    return target.lower().startswith(("http://", "https://", "mailto:", "tel:", "sandbox:"))


def local_target_path(source: Path, raw_target: str) -> Path | None:
    target = raw_target.strip().split()[0]
    if not target or target.startswith("#") or is_external(target):
        return None
    target = target.split("#", 1)[0]
    if not target:
        return None
    return (source.parent / unquote(target)).resolve()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=Path(__file__).resolve().parents[1])
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--md-out", default=None)
    args = ap.parse_args(argv)

    repo = Path(args.repo_root).resolve()
    missing_required = [p for p in REQUIRED if not (repo / p).exists()]

    broken: list[dict[str, str]] = []
    checked_links = 0
    for md in sorted(repo.rglob("*.md")):
        parts = md.relative_to(repo).parts
        if "reports" in parts or "audit_reports" in parts:
            continue
        text = strip_code_fences(md.read_text(encoding="utf-8", errors="replace"))
        for match in LINK_RE.finditer(text):
            raw = match.group(1).strip()
            path = local_target_path(md, raw)
            if path is None:
                continue
            checked_links += 1
            try:
                path.relative_to(repo)
            except ValueError:
                broken.append({"source": str(md.relative_to(repo)), "target": raw, "reason": "outside repo"})
                continue
            if not path.exists():
                broken.append({"source": str(md.relative_to(repo)), "target": raw, "reason": "not found"})

    status = "PASS" if not missing_required and not broken else "FAIL"
    payload = {
        "schema": "pulse.esp32.docs-check.v1",
        "status": status,
        "required_count": len(REQUIRED),
        "missing_required": missing_required,
        "checked_links": checked_links,
        "broken_links": broken,
    }

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.md_out:
        lines = [
            "# Documentation check report",
            "",
            f"Status: **{status}**",
            "",
            f"Required files: {len(REQUIRED)}",
            f"Checked local links: {checked_links}",
            "",
        ]
        if missing_required:
            lines.append("## Missing required files")
            lines.extend(f"- `{p}`" for p in missing_required)
            lines.append("")
        if broken:
            lines.append("## Broken local links")
            lines.extend(
                f"- `{item['source']}` -> `{item['target']}` ({item['reason']})"
                for item in broken
            )
            lines.append("")
        Path(args.md_out).write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
