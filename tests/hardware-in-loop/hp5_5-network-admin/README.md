# HP5.5 dual-board network and administration audit

This campaign is a blocking physical seal, not a host simulation. It runs the
same frozen fixture on the exact AITRIP ESP32-S3-DevKitC-1 N8R2 and Seeed
Studio XIAO ESP32C6 4 MB/no-PSRAM lanes using ESP-IDF v5.4.4.

The build tool stages a local test-only Wi-Fi/TLS/authenticator provision. The
provision directory and generated project contain secrets and must never be
published. Retained build reports, serial logs, client transcripts, and board
reports are checked byte-for-byte for those secret values.

Use `docs/HP5_5_NETWORK_ADMIN_PHYSICAL_SEAL.md` as the authoritative operator
runbook. A single board, synthetic transcript, reordered checkpoint stream,
unbound target identity, missing full-flash backup, or secret-bearing evidence
must remain `HARDWARE_PENDING`.
