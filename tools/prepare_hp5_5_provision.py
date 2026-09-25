#!/usr/bin/env python3
"""Create a local, test-only HP5.5 Wi-Fi/TLS/authenticator provision."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import ssl
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


class ProvisionError(RuntimeError):
    """Raised when a secret-safe test provision cannot be created."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prepare(path: Path) -> Path:
    output = path.expanduser().resolve()
    try:
        output.relative_to(ROOT)
    except ValueError:
        pass
    else:
        raise ProvisionError("test provision must remain outside the source tree")
    if output.exists():
        if not output.is_dir() or any(output.iterdir()):
            raise ProvisionError("provision directory must be absent or empty")
    else:
        output.mkdir(parents=True)
    output.chmod(0o700)
    return output


def prepare(
    out_dir: Path,
    *,
    ssid_env: str,
    password_env: str,
    common_name: str,
    openssl: str,
) -> dict[str, Any]:
    ssid = os.environ.get(ssid_env)
    password = os.environ.get(password_env)
    if ssid is None or not 8 <= len(ssid.encode("utf-8")) < 32:
        raise ProvisionError(f"{ssid_env} must contain an 8-31 byte test SSID")
    if password is None or not 8 <= len(password.encode("utf-8")) < 64:
        raise ProvisionError(f"{password_env} must contain an 8-63 byte test password")
    if not common_name or any(character in common_name for character in "\r\n/="):
        raise ProvisionError("common name contains a forbidden character")
    output = _prepare(out_dir)
    paths = {
        "ssid": output / "wifi-ssid.bin",
        "password": output / "wifi-password.bin",
        "certificate": output / "server-cert.pem",
        "private_key": output / "server-key.pem",
        "admin_proof": output / "admin-proof.bin",
        "channel_binding": output / "channel-binding.bin",
    }
    paths["ssid"].write_bytes(ssid.encode("utf-8"))
    paths["password"].write_bytes(password.encode("utf-8"))
    paths["admin_proof"].write_bytes(secrets.token_bytes(32))
    for role in ("ssid", "password", "admin_proof"):
        paths[role].chmod(0o600)
    command = [
        openssl,
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-sha256",
        "-nodes",
        "-days",
        "14",
        "-subj",
        f"/CN={common_name}",
        "-addext",
        f"subjectAltName=DNS:{common_name}",
        "-keyout",
        str(paths["private_key"]),
        "-out",
        str(paths["certificate"]),
    ]
    process = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    for role in ("certificate", "private_key"):
        if paths[role].exists():
            paths[role].chmod(0o600)
    if process.returncode != 0:
        raise ProvisionError("OpenSSL could not create the test certificate")
    certificate_pem = paths["certificate"].read_text(encoding="ascii")
    certificate_der = ssl.PEM_cert_to_DER_cert(certificate_pem)
    channel_binding = hashlib.sha256(certificate_der).digest()
    paths["channel_binding"].write_bytes(channel_binding)
    for path in paths.values():
        path.chmod(0o600)
    manifest = {
        "schema": "pulse.esp32.hp5_5-test-provision.v1",
        "status": "LOCAL_SECRET_MATERIAL",
        "publishable": False,
        "certificate_sha256": _sha256(paths["certificate"]),
        "admin_proof_sha256": _sha256(paths["admin_proof"]),
        "channel_binding_sha256": channel_binding.hex(),
        "secret_files": [
            {"name": path.name, "size": path.stat().st_size}
            for path in paths.values()
        ],
        "retention": {
            "source_archive": False,
            "logs": False,
            "reports": False,
            "evidence_manifest": False,
            "local_run_directory_only": True,
        },
    }
    manifest_path = output / "provision-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest_path.chmod(0o600)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--ssid-env", default="HP5_5_WIFI_SSID")
    parser.add_argument("--password-env", default="HP5_5_WIFI_PASSWORD")
    parser.add_argument("--common-name", default="pulse-hp55.local")
    parser.add_argument("--openssl", default="openssl")
    args = parser.parse_args(argv)
    try:
        manifest = prepare(
            args.out_dir,
            ssid_env=args.ssid_env,
            password_env=args.password_env,
            common_name=args.common_name,
            openssl=args.openssl,
        )
    except (OSError, ValueError, ProvisionError) as exc:
        print(f"HP5.5 provision failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": "PASS",
                "provision": str(args.out_dir.expanduser().resolve()),
                "certificate_sha256": manifest["certificate_sha256"],
                "publishable": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
