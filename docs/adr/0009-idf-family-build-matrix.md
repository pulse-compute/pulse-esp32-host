# ADR 0009 — Pinned ESP-IDF family build matrix

## Status

Accepted.

## Context

The repository has an ESP32-S3-oriented firmware prototype, but its current
bootstrap, configuration, and build scripts do not qualify an exact ESP-IDF
toolchain or describe the other ESP32-family targets that intersect with the
selected WAMR component.

A family claim cannot be derived from CPU architecture alone. It must name the
exact toolchain lane, IDF target, configuration overlays, partition layout, and
managed-component lock that were actually evaluated.

## Decision

### Lane and realization are separate axes

An **IDF lane** is one exact build environment:

```text
ESP-IDF release + source commit + container digest + platform
```

The initial and only maintained lane is:

| Field | Value |
|---|---|
| Lane | `idf-5.4.4` |
| ESP-IDF | `v5.4.4` |
| Source commit | `296b6eab9445fd720e71aecab961e2d3fbca9944` |
| Platform | `linux/amd64` |
| Container | `espressif/idf@sha256:8d1846f61ff8db00ba6530501f90bf43604d923072a616c806fef8e85a88ed82` |
| WAMR | `espressif/wasm-micro-runtime` `2.4.0~1` |

A **realization** is a mapping from that lane to an IDF target, defaults
overlay, partition layout, and target-specific dependency lock. A realization
is not a board-support or deployment claim.

Adding another IDF lane is an explicit maintenance and architecture decision.
It must not happen as an opportunistic workaround for a target failure.

### The inventory is closed and explicit

`firmware/idf-family-matrix.json` is the canonical inventory:

| Realization | Target | Intent |
|---|---|---|
| `esp32s3-reference` | `esp32s3` | required |
| `esp32-compile` | `esp32` | exploratory |
| `esp32c3-compile` | `esp32c3` | exploratory |
| `esp32c6-compile` | `esp32c6` | exploratory |
| `esp32p4-deferred` | `esp32p4` | deferred |
| `esp32c5-deferred` | `esp32c5` | deferred |
| `esp32s2-excluded` | `esp32s2` | excluded |
| `esp32c2-excluded` | `esp32c2` | excluded |
| `esp32h2-excluded` | `esp32h2` | excluded |
| `esp32c61-excluded` | `esp32c61` | excluded |

ESP32-S3 is the only required/reference realization. It requires at least two
independent clean builds for reproducibility. Exploratory realizations require
one real build attempt and an explicit result classification. Deterministic
incompatibility is useful mapping evidence; silently skipping the attempt is
not.

Deferred and excluded targets carry stable reasons and must not be attempted by
the family qualification workflow.

### Builds and locks fail closed

- Every maintained lane is identified exactly; moving branches and image tags
  are prohibited.
- Managed-component locks are stored per lane and target because dependency
  solving is target- and IDF-version-aware.
- Qualification builds run in isolated temporary project copies. A build must
  not mutate the source checkout or the committed lock selected for its cell.
- Matrix paths are relative to the firmware tree and may not escape it.
- Unknown schema fields, missing inventory entries, missing reasons, unknown
  intents or results, and unclassified failures are errors.
- `SKIPPED_ENV`, `SKIPPED_NETWORK`, and `PARTIAL` are not qualification results.

The closed build-result vocabulary is:

- `BUILD_QUALIFIED`;
- `COMPILE_PROVEN`;
- `INCOMPATIBLE`;
- `INFRASTRUCTURE_FAILURE`; and
- `UNCLASSIFIED_FAILURE`.

Only `BUILD_QUALIFIED` and `COMPILE_PROVEN` are positive technical results.
`INCOMPATIBLE` is an acceptable exploratory mapping outcome only when the build
was attempted and the deterministic boundary is recorded. Infrastructure and
unclassified failures fail the family workflow.

### Build mapping is not runtime qualification

A successful cell proves only that the source and dependency graph compile for
the recorded realization. It does not establish runtime correctness, board
compatibility, memory headroom, electrical safety, network behavior, watchdog
behavior, flash resilience, or hardware support.

## Out of scope

This decision does not design or implement:

- Pulse host capability ABIs, including clock, GPIO, storage, crypto, or
  network contracts;
- WAMR ownership, invocation lifecycle, or memory qualification;
- FreeRTOS task topology, core pinning, queues, scheduling, or execution
  epochs;
- callback or ISR delivery into guests;
- Wi-Fi, lwIP, TLS, reconnect, backpressure, or network brokers;
- an ESP32 provider for the Pulse compilation pipeline; or
- flashing, hardware-in-loop, electrical, security, or field qualification.

Those are separate host-contract, host-realization, provider, and hardware
lanes. The family matrix intentionally stops at reproducible build mapping.

## Consequences

- IF1 moved S3 assumptions into a realization overlay and kept common defaults
  target-neutral.
- IF2 pins and validates per-target component locks and provides an isolated,
  explicit lock-update path. IF3 provides the full fail-closed cell builder,
  evidence artifacts, and fake-IDF behavioral tests.
- IF4 ran the S3 builder twice in the digest-pinned lane with compiler caching
  disabled. The generated configuration, resolved lock, ELF, application
  binary, bootloader, and partition table were byte-stable, so
  `esp32s3-reference` is `BUILD_QUALIFIED` for compilation only.
- IF5 attempted ESP32-C3, ESP32, and ESP32-C6 in that order. C6 is
  `COMPILE_PROVEN`. The no-PSRAM C3 and classic ESP32 cells are
  `INCOMPATIBLE`: their final links overflow internal DRAM by 17,664 and
  115,120 bytes respectively. No heap, lifecycle, task/core, ABI, or alternate
  lane change was made to hide that boundary. S3 was requalified after the
  overlay correction and retained its byte-identical `BUILD_QUALIFIED` result.
- IF6 wraps those semantics in one fail-closed orchestrator. It requires all
  selected attempts, validates evidence files against their recorded hashes,
  enforces one firmware source-tree hash, accepts exploratory incompatibility
  only with a deterministic failure boundary, and preserves deferred/excluded
  entries as policy inventory rather than invented observations. A pinned local
  workflow invokes the same host launcher and always uploads the evidence tree.
- Documentation may claim only observed build mappings and must keep hardware
  and runtime work explicitly deferred.

The final observed mapping and evidence identities are indexed by the
[IF7 family matrix reference](../reference/IDF_FAMILY_MATRIX.md).

## References

- [ESP-IDF target selection](https://docs.espressif.com/projects/esp-idf/en/v5.4/esp32/api-guides/tools/idf-py.html#select-the-target-chip-set-target)
- [IDF Component Manager manifest format](https://docs.espressif.com/projects/idf-component-manager/en/latest/reference/manifest_file.html)
- [IDF Component Manager lock files](https://docs.espressif.com/projects/idf-component-manager/en/latest/reference/dependencies_lock.html)
- [Espressif WAMR component `2.4.0~1`](https://components.espressif.com/components/espressif/wasm-micro-runtime/versions/2.4.0~1/readme)
