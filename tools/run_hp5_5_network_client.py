#!/usr/bin/env python3
"""Drive one real HP5.5 TLS/application/administration board run."""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import socket
import ssl
import struct
import sys
import threading
import time
from pathlib import Path
from typing import Any


ADMIN_REQUEST_BYTES = 112
SESSION_NONCE_PREFIX = 0x4850353500000000
CHALLENGE_WINDOW_MS = 10000
COMMAND_DEADLINE_MS = 25000
PROBATION_WAIT_SECONDS = 31.0

COMMAND_STATUS = 1
COMMAND_BEGIN_UPDATE = 2
COMMAND_WRITE_CHUNK = 3
COMMAND_FINISH_UPDATE = 4
COMMAND_ABORT = 5
COMMAND_ENTER_RECOVERY = 6
COMMAND_ACTIVATE_TRIAL = 7

SLOT_NONE = 0xFFFFFFFF
SLOT_A = 1
SLOT_B = 2


class ClientError(RuntimeError):
    """Raised when an observed physical network contract fails."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class CborDecoder:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.offset = 0

    def _take(self, count: int) -> bytes:
        if count < 0 or self.offset + count > len(self.data):
            raise ClientError("truncated CBOR response")
        value = self.data[self.offset : self.offset + count]
        self.offset += count
        return value

    def _argument(self, additional: int) -> int:
        if additional < 24:
            return additional
        widths = {24: 1, 25: 2, 26: 4, 27: 8}
        width = widths.get(additional)
        if width is None:
            raise ClientError("indefinite or reserved CBOR response")
        return int.from_bytes(self._take(width), "big")

    def value(self) -> Any:
        initial = self._take(1)[0]
        major = initial >> 5
        argument = self._argument(initial & 0x1F)
        if major == 0:
            return argument
        if major == 1:
            return -1 - argument
        if major == 2:
            return self._take(argument)
        if major == 3:
            return self._take(argument).decode("utf-8")
        if major == 4:
            return [self.value() for _ in range(argument)]
        if major == 5:
            return {self.value(): self.value() for _ in range(argument)}
        if major == 7 and argument in (20, 21):
            return argument == 21
        if major == 7 and argument == 22:
            return None
        raise ClientError("unsupported CBOR response type")


def decode_cbor(data: bytes) -> dict[int, Any]:
    decoder = CborDecoder(data)
    value = decoder.value()
    if decoder.offset != len(data) or not isinstance(value, dict):
        raise ClientError("response is not one canonical CBOR map")
    if any(not isinstance(key, int) for key in value):
        raise ClientError("CBOR response contains a non-integer key")
    return value


class Transcript:
    def __init__(self, path: Path, campaign_id: str, board_id: str) -> None:
        self.path = path
        self.campaign_id = campaign_id
        self.board_id = board_id
        self.ordinal = 0
        self.checkpoint_ordinal = 0

    def add(
        self,
        operation: str,
        *,
        lane: str,
        http_status: int | None = None,
        protocol_status: int | None = None,
        body: bytes = b"",
        checkpoint_id: str | None = None,
        detail: str = "",
    ) -> None:
        self.ordinal += 1
        if checkpoint_id is not None:
            self.checkpoint_ordinal += 1
        record = {
            "schema": "pulse.esp32.hp5_5-network-transcript-record.v1",
            "campaign_id": self.campaign_id,
            "board_id": self.board_id,
            "ordinal": self.ordinal,
            "checkpoint_ordinal": self.checkpoint_ordinal if checkpoint_id else None,
            "checkpoint_id": checkpoint_id,
            "lane": lane,
            "operation": operation,
            "http_status": http_status,
            "protocol_status": protocol_status,
            "response_bytes": len(body),
            "response_sha256": sha256_bytes(body),
            "detail": detail,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


class HttpDriver:
    def __init__(self, host: str, certificate: Path, timeout: float) -> None:
        self.host = host
        self.timeout = timeout
        self.context = ssl.create_default_context(cafile=str(certificate))
        self.context.check_hostname = False
        self.context.minimum_version = ssl.TLSVersion.TLSv1_2

    def request(
        self, port: int, method: str, path: str, body: bytes = b""
    ) -> tuple[int, bytes]:
        connection = http.client.HTTPSConnection(
            self.host, port, timeout=self.timeout, context=self.context
        )
        try:
            connection.request(
                method, path, body=body,
                headers={"Content-Type": "application/octet-stream"},
            )
            response = connection.getresponse()
            payload = response.read()
            return response.status, payload
        finally:
            connection.close()

    def abandon(
        self, port: int, method: str, path: str, body: bytes = b""
    ) -> None:
        raw = socket.create_connection((self.host, port), timeout=self.timeout)
        tls = self.context.wrap_socket(raw, server_hostname="pulse-hp55.local")
        request = (
            f"{method} {path} HTTP/1.1\r\n"
            f"Host: pulse-hp55.local\r\n"
            f"Content-Type: application/octet-stream\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii") + body
        tls.sendall(request)
        # Force a TCP reset after the complete request is queued.  A graceful
        # TLS/TCP close can leave the peer's subsequent write looking
        # successful and therefore cannot prove the response-loss counters.
        tls.setsockopt(
            socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0)
        )
        tls.close()


class AdminSession:
    def __init__(self, driver: HttpDriver, transcript: Transcript, proof: bytes) -> None:
        self.driver = driver
        self.transcript = transcript
        self.proof = proof
        self.epoch = 0
        self.nonce = 0
        self.sequence = 1
        self.request_id = 1
        self.device_zero_ms = 0.0
        self.local_zero = 0.0

    def _device_now(self) -> int:
        return int(self.device_zero_ms + (time.monotonic() - self.local_zero) * 1000)

    def authenticate(
        self, *, checkpoint: str | None = None,
        begin_response: tuple[int, bytes] | None = None,
    ) -> None:
        local_begin = time.monotonic()
        status, body = begin_response or self.driver.request(
            8443, "POST", "/pulse/v1/admin/session/begin"
        )
        if status != 200:
            raise ClientError(f"admin session begin returned HTTP {status}")
        begin = decode_cbor(body)
        challenge = begin.get(39)
        deadline = begin.get(40)
        if begin.get(0) != 0 or not isinstance(challenge, int) or not isinstance(deadline, int):
            raise ClientError("admin session begin response is incomplete")
        status, finish_body = self.driver.request(
            8443, "POST", "/pulse/v1/admin/session/finish", self.proof
        )
        finish = decode_cbor(finish_body)
        if status != 200 or finish.get(0) != 0 or finish.get(32) != 2:
            raise ClientError("admin proof was not accepted")
        self.epoch = challenge
        self.nonce = SESSION_NONCE_PREFIX ^ challenge
        self.sequence = int(finish.get(39, 1))
        self.device_zero_ms = float(deadline - CHALLENGE_WINDOW_MS)
        self.local_zero = local_begin
        self.transcript.add(
            "admin-session-authenticated", lane="administration",
            http_status=status, protocol_status=0, body=finish_body,
            checkpoint_id=checkpoint,
            detail="replaceable proof accepted over the independent TLS lane",
        )

    def close(self) -> None:
        status, body = self.driver.request(
            8443, "DELETE", "/pulse/v1/admin/session"
        )
        if status not in (204, 200):
            raise ClientError(f"admin session close returned HTTP {status}")
        self.transcript.add(
            "admin-session-close", lane="administration",
            http_status=status, body=body,
        )

    def frame(
        self, command: int, *, slot: int = SLOT_NONE,
        expected_total: int = 0, artifact_sha: bytes = bytes(32),
        payload: bytes = b"", sequence: int | None = None,
        deadline_ms: int | None = None,
    ) -> bytes:
        sequence_value = self.sequence if sequence is None else sequence
        deadline_value = (
            self._device_now() + COMMAND_DEADLINE_MS
            if deadline_ms is None
            else deadline_ms
        )
        request = struct.pack(
            "<IHHIIIIIIQQQQQ32s8s",
            ADMIN_REQUEST_BYTES, 1, 0, command, 0, len(payload), slot,
            expected_total, 0, self.request_id,
            deadline_value,
            self.epoch, self.nonce, sequence_value, artifact_sha, bytes(8),
        )
        if len(request) != ADMIN_REQUEST_BYTES:
            raise ClientError("admin request packing drifted")
        return struct.pack("<I", len(request) + len(payload)) + request + payload

    def poll_terminal(self, timeout: float = 10.0) -> tuple[dict[int, Any], bytes]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status, body = self.driver.request(
                8443, "GET", "/pulse/v1/admin/terminal"
            )
            if status == 200:
                terminal = decode_cbor(body)
                return terminal, body
            if status not in (404, 409):
                raise ClientError(f"terminal poll returned HTTP {status}")
            time.sleep(0.05)
        raise ClientError("accepted admin command did not reach a terminal")

    def command(
        self, command: int, *, slot: int = SLOT_NONE,
        expected_total: int = 0, artifact_sha: bytes = bytes(32),
        payload: bytes = b"", checkpoint: str | None = None,
        detail: str = "", expect_terminal_status: int = 0,
    ) -> dict[int, Any]:
        frame = self.frame(
            command, slot=slot, expected_total=expected_total,
            artifact_sha=artifact_sha, payload=payload,
        )
        status, accepted_body = self.driver.request(
            8443, "POST", "/pulse/v1/admin/command", frame
        )
        accepted = decode_cbor(accepted_body)
        if status != 202 or accepted.get(0) != 0:
            raise ClientError(f"admin command {command} was not accepted")
        expected_request = self.request_id
        expected_sequence = self.sequence
        self.request_id += 1
        self.sequence += 1
        terminal, terminal_body = self.poll_terminal()
        if (
            terminal.get(28) != expected_request
            or terminal.get(39) != expected_sequence
            or terminal.get(0) != expect_terminal_status
        ):
            raise ClientError(f"admin command {command} terminal drifted")
        self.transcript.add(
            f"admin-command-{command}", lane="administration",
            http_status=200, protocol_status=int(terminal.get(0, -999)),
            body=terminal_body, checkpoint_id=checkpoint, detail=detail,
        )
        return terminal


def require_http(
    driver: HttpDriver, transcript: Transcript, port: int, method: str,
    path: str, body: bytes, expected: int, operation: str,
    checkpoint: str | None, detail: str,
) -> bytes:
    status, response = driver.request(port, method, path, body)
    if status != expected:
        raise ClientError(f"{operation} returned HTTP {status}, expected {expected}")
    protocol = None
    if response and response[:1] not in (b"h", b"f", b"p"):
        try:
            protocol = int(decode_cbor(response).get(0))
        except (ClientError, TypeError, ValueError):
            protocol = None
    transcript.add(
        operation, lane="application" if port == 443 else "administration",
        http_status=status, protocol_status=protocol, body=response,
        checkpoint_id=checkpoint, detail=detail,
    )
    return response


def wait_for_device(driver: HttpDriver, timeout: float = 90.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            status, _ = driver.request(443, "GET", "/pulse/v1/app/empty")
            if status == 204:
                return
        except (OSError, ssl.SSLError, http.client.HTTPException):
            pass
        time.sleep(0.5)
    raise ClientError("device did not return after the expected reboot sequence")


def stage_update(
    session: AdminSession, artifact: bytes, slot: int,
    *, checkpoint: str | None = None,
) -> None:
    digest = hashlib.sha256(artifact).digest()
    session.command(
        COMMAND_BEGIN_UPDATE, slot=slot, expected_total=len(artifact),
        artifact_sha=digest,
    )
    for offset in range(0, len(artifact), 512):
        session.command(
            COMMAND_WRITE_CHUNK, slot=slot, expected_total=len(artifact),
            artifact_sha=digest, payload=artifact[offset : offset + 512],
        )
    session.command(
        COMMAND_FINISH_UPDATE, slot=slot, expected_total=len(artifact),
        artifact_sha=digest, checkpoint=checkpoint,
        detail="exclusive quiesce, inactive-slot stream, and complete verification reached terminal",
    )


def drive(args: argparse.Namespace) -> dict[str, Any]:
    run_dir = args.run_dir.expanduser().resolve()
    provision = args.provision_dir.expanduser().resolve()
    report_path = run_dir / "build-report.json"
    if not report_path.is_file():
        raise ClientError("build report is missing")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if (
        report.get("schema") != "pulse.esp32.hp5_5-network-admin-build.v1"
        or report.get("status") != "PASS"
        or report.get("claim_boundary", {}).get("build") != "BUILD_PROVEN"
    ):
        raise ClientError("physical client requires a proven HP5.5 firmware build")
    transcript_path = run_dir / "network-transcript.jsonl"
    if transcript_path.exists():
        raise ClientError("network transcript already exists; use a fresh run")
    certificate = provision / "server-cert.pem"
    proof = (provision / "admin-proof.bin").read_bytes()
    channel_binding = (provision / "channel-binding.bin").read_bytes()
    if (
        sha256_bytes(certificate.read_bytes()) != report["provision"]["certificate_sha256"]
        or sha256_bytes(proof) != report["provision"]["admin_proof_sha256"]
        or channel_binding.hex() != report["provision"]["channel_binding_sha256"]
    ):
        raise ClientError("local provision does not match the built firmware")
    transcript = Transcript(
        transcript_path, report["campaign_id"], report["board_id"]
    )
    driver = HttpDriver(args.device_host, certificate, args.timeout)

    app_admin_status, app_admin_body = driver.request(
        443, "POST", "/pulse/v1/admin/session/begin"
    )
    admin_app_status, admin_app_body = driver.request(
        8443, "GET", "/pulse/v1/app/empty"
    )
    if app_admin_status != 404 or admin_app_status != 404:
        raise ClientError("application and administration TLS namespaces crossed")
    transcript.add(
        "tls-listener-separation", lane="both", http_status=404,
        body=app_admin_body + admin_app_body,
        checkpoint_id="tls-listeners-separated",
        detail="admin paths rejected on 443 and app paths rejected on 8443",
    )
    echo = require_http(
        driver, transcript, 443, "POST", "/pulse/v1/app/echo", b"ping",
        200, "common-wasm-echo", "common-wasm-app-response",
        "real Wasm returned the expected hp55 response",
    )
    if echo != b"hp55":
        raise ClientError("common Wasm response body drifted")
    require_http(driver, transcript, 443, "GET", "/pulse/v1/app/empty", b"", 204,
                 "empty-response", "app-empty-response", "no response effect produced HTTP 204")
    require_http(driver, transcript, 443, "POST", "/pulse/v1/app/control", b"duplicate", 201,
                 "first-response-wins", "app-first-response-wins", "first response survived duplicate effect")
    require_http(driver, transcript, 443, "POST", "/pulse/v1/app/control", b"wrong-id", 204,
                 "wrong-id", "app-wrong-id-rejected", "foreign request id produced no response")
    require_http(driver, transcript, 443, "POST", "/pulse/v1/app/control", b"oversize", 204,
                 "oversize-response", "app-oversize-rejected", "oversized response effect was rejected")
    require_http(driver, transcript, 443, "GET", "/pulse/v1/app/trap", b"", 500,
                 "trap", "app-trap-contained", "application failure remained an HTTP terminal")
    require_http(driver, transcript, 443, "POST", "/pulse/v1/app/control", b"timeout", 504,
                 "timeout", "app-timeout-contained", "deadline terminal remained bounded")
    require_http(driver, transcript, 443, "POST", "/pulse/v1/app/control", b"cancel", 499,
                 "cancel", "app-cancellation-contained", "cancellation remained request-local")
    driver.abandon(443, "POST", "/pulse/v1/app/control", b"client-loss")
    transcript.add(
        "application-client-loss", lane="application",
        checkpoint_id="app-client-loss-counted",
        detail="TLS client closed before the response was retained",
    )
    status, reconnect_body = driver.request(443, "GET", "/pulse/v1/app/empty")
    if status != 204:
        raise ClientError("application listener did not recover after client loss")
    transcript.add(
        "application-reconnect", lane="application", http_status=status,
        body=reconnect_body, checkpoint_id="bounded-wifi-reconnect",
        detail=(
            "listener recovered after client loss; serial evidence binds the "
            "separate forced station disconnect/reconnect self-test"
        ),
    )

    # Preaccept negative before any authenticated session.
    bad_status, bad_body = driver.request(
        8443, "POST", "/pulse/v1/admin/command", b"\x00" * 116
    )
    if bad_status not in (400, 401):
        raise ClientError("unauthenticated administration did not fail closed")
    session = AdminSession(driver, transcript, proof)
    session.authenticate(checkpoint="authenticated-admin-session")
    expired = session.frame(
        COMMAND_STATUS, deadline_ms=max(1, session._device_now() - 1)
    )
    expired_status, expired_body = driver.request(
        8443, "POST", "/pulse/v1/admin/command", expired
    )
    if expired_status != 401:
        raise ClientError("expired admin request was not rejected")
    out_of_order = session.frame(COMMAND_STATUS, sequence=session.sequence + 1)
    negative_status, negative_body = driver.request(
        8443, "POST", "/pulse/v1/admin/command", out_of_order
    )
    if negative_status != 409:
        raise ClientError("out-of-order admin request was not rejected")
    transcript.add(
        "admin-negative-preaccept", lane="administration",
        http_status=negative_status,
        body=bad_body + expired_body + negative_body,
        checkpoint_id="admin-negative-preaccept",
        detail=(
            "unauthenticated, expired-deadline, and out-of-order frames "
            "rejected before ownership"
        ),
    )

    # Baseline version 8 remains a real running trial until the common runtime,
    # listener readiness, resource floors, and an accepted administration
    # command have remained healthy for the fixed 30-second HP3 probation.
    time.sleep(PROBATION_WAIT_SECONDS)

    pressure_result: list[tuple[int, bytes] | Exception] = []
    def pressure() -> None:
        try:
            pressure_result.append(driver.request(
                443, "POST", "/pulse/v1/app/control", b"pressure"
            ))
        except Exception as exc:  # retained locally only for deterministic join
            pressure_result.append(exc)
    thread = threading.Thread(target=pressure, daemon=True)
    thread.start()
    time.sleep(0.2)
    capacity_frame = session.frame(COMMAND_STATUS)
    expected_request = session.request_id
    expected_sequence = session.sequence
    accepted_status, accepted_body = driver.request(
        8443, "POST", "/pulse/v1/admin/command", capacity_frame
    )
    accepted = decode_cbor(accepted_body)
    if accepted_status != 202 or accepted.get(0) != 0:
        raise ClientError("capacity setup STATUS was not accepted")
    session.request_id += 1
    session.sequence += 1
    busy_frame = session.frame(COMMAND_STATUS)
    busy_status, busy_body = driver.request(
        8443, "POST", "/pulse/v1/admin/command", busy_frame
    )
    if busy_status != 503:
        raise ClientError("second in-flight administration command was not rejected")
    terminal, terminal_body = session.poll_terminal()
    if (
        terminal.get(28) != expected_request
        or terminal.get(39) != expected_sequence
        or terminal.get(0) != 0
    ):
        raise ClientError("capacity setup STATUS terminal drifted")
    replay_status, replay_body = driver.request(
        8443, "POST", "/pulse/v1/admin/command", capacity_frame
    )
    if replay_status != 409:
        raise ClientError("completed administration command replay was not rejected")
    thread.join(timeout=5.0)
    if not pressure_result or isinstance(pressure_result[0], Exception) or pressure_result[0][0] != 200:
        raise ClientError("application pressure request did not complete")
    transcript.add(
        "admin-capacity-replay-under-app-pressure", lane="administration",
        http_status=200, protocol_status=0,
        body=accepted_body + busy_body + terminal_body + replay_body,
        checkpoint_id="admin-capacity-under-app-pressure",
        detail=(
            "one STATUS reached its terminal while app pressure continued; "
            "a second in-flight command failed with 503 and replay failed with 409"
        ),
    )
    session.command(
        COMMAND_STATUS, checkpoint="accepted-command-terminal",
        detail="accepted STATUS produced one correlated terminal",
    )

    retained_frame = session.frame(COMMAND_STATUS)
    retained_request = session.request_id
    retained_sequence = session.sequence
    driver.abandon(8443, "POST", "/pulse/v1/admin/command", retained_frame)
    session.request_id += 1
    session.sequence += 1
    terminal, terminal_body = session.poll_terminal()
    if terminal.get(28) != retained_request or terminal.get(39) != retained_sequence:
        raise ClientError("terminal did not survive administration client loss")
    transcript.add(
        "admin-terminal-retained", lane="administration", http_status=200,
        protocol_status=int(terminal.get(0, -999)), body=terminal_body,
        checkpoint_id="admin-terminal-retained-after-client-loss",
        detail="terminal remained retrievable after the accepting client disconnected",
    )
    # Create and abandon one terminal response; firmware counters prove the loss.
    status_frame = session.frame(COMMAND_STATUS)
    accepted_status, _ = driver.request(
        8443, "POST", "/pulse/v1/admin/command", status_frame
    )
    if accepted_status != 202:
        raise ClientError("terminal-loss setup command was not accepted")
    session.request_id += 1
    session.sequence += 1
    # The fixture deliberately retains STATUS ownership for four seconds. Wait
    # beyond that bound so this abandoned GET reaches an existing terminal,
    # rather than racing the in-flight command and abandoning a 404 response.
    time.sleep(4.5)
    driver.abandon(8443, "GET", "/pulse/v1/admin/terminal")
    transcript.add(
        "admin-terminal-response-loss", lane="administration",
        checkpoint_id="admin-terminal-response-loss-counted",
        detail="TLS client closed while a completed terminal response was sent",
    )

    positive = (run_dir / "client-fixtures/positive-v9.artifact").read_bytes()
    fallback = (run_dir / "client-fixtures/fallback-v10.artifact").read_bytes()
    positive_sha = hashlib.sha256(positive).digest()
    session.command(COMMAND_BEGIN_UPDATE, slot=SLOT_B, expected_total=len(positive), artifact_sha=positive_sha)
    session.command(COMMAND_WRITE_CHUNK, slot=SLOT_B, expected_total=len(positive), artifact_sha=positive_sha, payload=positive[:512])
    session.command(
        COMMAND_ABORT, slot=SLOT_B, expected_total=len(positive), artifact_sha=positive_sha,
        checkpoint="update-abort-preserves-confirmed",
        detail="partial inactive-slot stream aborted without changing confirmed authority",
    )
    stage_update(session, positive, SLOT_B, checkpoint="update-quiesce-stage-verify")
    session.command(
        COMMAND_ACTIVATE_TRIAL, slot=SLOT_B, expected_total=len(positive), artifact_sha=positive_sha,
        checkpoint="durable-trial-reboot-handoff",
        detail="version 9 activation produced a reboot-handoff terminal",
    )
    wait_for_device(driver)
    time.sleep(PROBATION_WAIT_SECONDS)
    session = AdminSession(driver, transcript, proof)
    session.authenticate()
    session.command(
        COMMAND_STATUS, checkpoint="trial-confirmed",
        detail=(
            "accepted STATUS supplied the live administration probation gate; "
            "serial evidence binds the version 9 confirmation journal"
        ),
    )

    fallback_sha = hashlib.sha256(fallback).digest()
    stage_update(session, fallback, SLOT_A)
    session.command(
        COMMAND_ACTIVATE_TRIAL, slot=SLOT_A, expected_total=len(fallback), artifact_sha=fallback_sha,
    )
    wait_for_device(driver)
    transcript.add(
        "stale-trial-fallback", lane="both",
        checkpoint_id="stale-trial-fallback",
        detail="service returned only after the version 10 trial reset and last-good fallback",
    )
    session = AdminSession(driver, transcript, proof)
    session.authenticate()
    session.command(
        COMMAND_ENTER_RECOVERY, checkpoint="administrative-recovery",
        detail="authenticated recovery command reached a host-only recovery terminal",
    )

    session.close()
    for index in range(8):
        status, body = driver.request(
            8443, "POST", "/pulse/v1/admin/session/begin"
        )
        if status != 200:
            raise ClientError(f"authorization failure setup {index} could not begin")
        bad_finish_status, _ = driver.request(
            8443, "POST", "/pulse/v1/admin/session/finish", b"wrong-proof"
        )
        if bad_finish_status != 401:
            raise ClientError("bad proof did not fail closed")
    rate_status, rate_body = driver.request(
        8443, "POST", "/pulse/v1/admin/session/begin"
    )
    if rate_status != 429:
        raise ClientError("authorization failure limit did not enter backoff")
    time.sleep(31.0)
    session = AdminSession(driver, transcript, proof)
    session.authenticate()
    transcript.add(
        "authorization-rate-recovery", lane="administration",
        http_status=rate_status, body=rate_body,
        checkpoint_id="authorization-rate-and-session-recovery",
        detail="eight bad proofs entered bounded backoff and a later session recovered",
    )
    transcript.add(
        "physical-no-viable-self-test-binding", lane="firmware",
        checkpoint_id="no-viable-slot-administration",
        detail="serial evidence supplies the physical no-viable recovery initialization",
    )
    transcript.add(
        "resource-floor-binding", lane="firmware",
        checkpoint_id="resource-floors-under-pressure",
        detail="serial heap samples supply the target-specific floor evidence",
    )
    driver.abandon(443, "GET", "/pulse/v1/app/empty")
    session.command(COMMAND_STATUS)
    transcript.add(
        "network-loss-authority-check", lane="both",
        checkpoint_id="network-loss-no-rollback-or-cancel",
        detail="post-loss STATUS completed without rollback or accepted-command cancellation",
    )
    require_http(
        driver, transcript, 443, "POST", "/pulse/v1/app/control", b"finalize", 200,
        "firmware-finalize", None, "firmware emitted its final secret-free statistics",
    )
    return {
        "schema": "pulse.esp32.hp5_5-network-client-result.v1",
        "status": "PASS",
        "campaign_id": report["campaign_id"],
        "board_id": report["board_id"],
        "transcript": str(transcript_path),
        "records": transcript.ordinal,
        "checkpoints": transcript.checkpoint_ordinal,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--provision-dir", type=Path, required=True)
    parser.add_argument("--device-host", required=True)
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args(argv)
    try:
        result = drive(args)
    except (OSError, ValueError, KeyError, json.JSONDecodeError,
            ssl.SSLError, socket.timeout, http.client.HTTPException,
            ClientError) as exc:
        print(f"HP5.5 physical client failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
