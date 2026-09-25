# Current status and risks

This repository is a strong host-side architecture prototype. It is not a qualified production firmware release.

## Implemented or scaffolded

| Area | Current state |
|---|---|
| Contract and schemas | Implemented and host-tested. |
| Native shell skeleton | Implemented. |
| WAMR integration boundary | Implemented and physically exercised for the sealed HX5b HIL path; production service and recovery integration remain pending. |
| ABI dispatcher | Implemented and host-tested. |
| Event/profile/capability model | Implemented and host-tested. |
| GPIO safety MVP | Implemented against a host HAL; hardware validation pending. |
| Bundle parsing and verification | Implemented and host-tested. |
| Pulse application slots and fallback | HP3 adds a fixed 192-byte artifact, two flash slots on each retained board, inactive-only streaming verification, a two-record metadata journal, persisted trial/reset attribution, HP2/HP1 prelaunch gates, host-owned probation and confirmation, deterministic fallback, and explicit no-viable-slot recovery. Ten contracts and fourteen C cases close as `PULSE_APPLICATION_SLOT_AUTHORITY_PROVEN`; no current target run or physical power-loss campaign is claimed. See [HP3 application slots](HP3_APPLICATION_SLOTS_AND_FALLBACK.md). |
| Application-slot adversarial seal | HP3.5 adds deterministic one-shot inactive-flash and journal interruption, durable-authority RAM resynchronization, and atomic confirmed fallback. Exactly 11,657 host cases cover every payload prefix, both records, eight state transitions, every record/body/marker prefix, reset during confirmation, corruption, timeout, traps, watchdogs, bad signatures/hashes, and incompatible fingerprints. The host aggregate is `HOST_SLOT_ADVERSARIAL_POWER_LOSS_SEALED`; both physical named-board lanes passed the frozen thirteen-checkpoint safe subset and the dual evaluator closed as `DUAL_NAMED_BOARD_SAFE_SUBSET_OBSERVED`. See [HP3.5 adversarial seal](HP3_5_APPLICATION_SLOT_ADVERSARIAL_SEAL.md) and [accepted identities](../evidence/hardware/HP3_5_INDEX.md). |
| Protected administration contract | HP4.0 freezes the host-private authenticated-entry record, one-session/one-command capacity, atomic replay acceptance, exactly-one terminal result, fixed request/deadline/audit bounds, serial-first transport seam, and legal `NORMAL`/`QUIESCE`/`UPDATE`/`RECOVERY`/`REBOOT_HANDOFF` transitions. Ten contract tests, five legal scenarios, and 62 missing-guard denials close as `HOST_ADMINISTRATION_CONTRACT_FROZEN`. HP4.0 itself is `HOST_MODEL_ONLY` and added no firmware component, driver, authenticator, update transaction, recovery implementation, network listener, crypto claim, or physical result; HP4.1 is its exact implementation successor. See [HP4.0 administration contract](HP4_0_PROTECTED_ADMINISTRATION_CONTRACT.md). |
| Protected administration core | HP4.1 implements the fixed `wdc_admin` firmware component: one attended authorizer-issued session, strict replay and authorization backoff, one HP1-owned command, first-terminal-wins response, bounded incremental serial normalization, replaceable artifact-verifier seam, and a 32-record overwrite/loss audit ring. Twelve contracts and fourteen native C cases close as `HOST_PROTECTED_ADMINISTRATION_CORE_IMPLEMENTED`; the observed core plus serial storage is 9,784 bytes inside HP1's 12,288-byte administration reserve. This is `HOST_NATIVE_CORE_ONLY`: no target build, UART driver, update/recovery transaction, production authenticator/crypto, application execution, network listener, or physical result is claimed. See [HP4.1 administration core](HP4_1_PROTECTED_ADMINISTRATION_CORE.md). |
| Exclusive update transaction | HP4.2 extends `wdc_admin` with a C6-minimum transaction requiring positive guest/refinement quiesce and unload, exact HP1 free/largest-block admission, bounded inactive-slot streaming, complete HP3/HP2/security and replaceable-verifier checks, and durable `TRIAL` read-back before `REBOOT_HANDOFF`. Thirteen contracts and fifteen native C cases close as `HOST_EXCLUSIVE_UPDATE_TRANSACTION_IMPLEMENTED`; the observed engine is 3,096 bytes with an external 65,536-byte working buffer. This is `HOST_NATIVE_UPDATE_TRANSACTION_ONLY`: no target build, serial driver, recovery transaction, production authenticator/crypto, host OTA, network listener, application execution, or physical result is claimed. See [HP4.2 exclusive update transaction](HP4_2_EXCLUSIVE_UPDATE_TRANSACTION.md). |
| Host-only recovery | HP4.3 adds deterministic HP3 no-viable and authorized administrative entry, keeps authenticated administration available with no application/refinement loaded, reuses the bounded HP4.2 candidate transaction with recovery failure return, and requires a read-only complete HP3/HP2 viability proof before reboot handoff. Twelve contracts and twelve native C cases close as `HOST_ONLY_RECOVERY_IMPLEMENTED`; the recovery engine is 3,112 bytes and retains the external 65,536-byte working buffer plus HP1's unchanged 16,384-byte recovery reserve. This is `HOST_NATIVE_RECOVERY_TRANSACTION_ONLY`: no target build, serial driver, production authenticator/crypto, host/factory OTA, network listener, application execution, or physical result is claimed. See [HP4.3 host-only recovery](HP4_3_HOST_ONLY_RECOVERY.md). |
| Administration adversarial seal | HP4.4 executes 3,523 deterministic negative cases across preaccept mutation, authorization/replay, quiesce/unload, resource floors, all 2,362 safe artifact prefixes, stream transactions, verifier rejects, all 1,030 two-record journal interruptions, capacity saturation, terminal/audit behavior, and recovery interactions. It also reruns 41 inherited HP4.1-HP4.3 native cases. The matrix found and fixed command-sequence exhaustion before acceptance mutation; all 3,564 cases pass and close HP4 as `HOST_ADMINISTRATION_ADVERSARIAL_SEALED`. This remains `HOST_NATIVE_ADMINISTRATION_ADVERSARIAL_ONLY`: no target build, physical execution, driver, transport, production authenticator/crypto, host/factory OTA, partition change, or application execution is claimed. See [HP4.4 adversarial seal](HP4_4_ADMINISTRATION_ADVERSARIAL_SEAL.md). |
| Host network mediator | HP5 adds host-private station Wi-Fi and independently bounded application/admin HTTPS listener source, fixed parsers and routes, common-Wasm application request dispatch, first-response-wins paired response, and an authenticated external adapter that reuses HP4 rather than creating another admin machine. Thirty-five new native cases and all 3,564 inherited HP4 cases pass as `HOST_NETWORK_MEDIATOR_IMPLEMENTED`. This remains `HOST_NATIVE_NETWORK_MEDIATOR_ONLY`: no target build, Wi-Fi/TLS handshake, physical execution, production authenticator/crypto, provisioning, MQTT, provider, or host OTA is claimed. See [HP5 host network mediator](HP5_HOST_NETWORK_MEDIATOR.md). |
| Network/administration physical audit | HP5.5 implements an exact 29-checkpoint dual-board campaign, new non-relabelled S3/PSRAM and C6/no-PSRAM locks/fingerprints, deterministic real-Wasm application artifacts, external test provisioning, pinned target builders, TLS client, secret-scanning per-board evaluator, and distinct-UID dual evaluator. The narrow update initialization now admits either matching target/profile pair and rejects crossed pairs. Host readiness passes as `READY_FOR_PHYSICAL_EXECUTION`, but the aggregate remains `HARDWARE_PENDING`: no ESP-IDF target build or physical run is claimed by this source. See [HP5.5 physical seal](HP5_5_NETWORK_ADMIN_PHYSICAL_SEAL.md). |
| Network mediation policy | Implemented for outbound intent and HP5 HTTP ingress; MQTT transport remains pending. |
| Runtime limits | Implemented in host-side paths. |
| Host kernel resource authority | HP1 fixes allocation-free ISR capture, five host-owned priority classes, per-class bounded tickets and terminal completions, a 96 KiB internal control reserve, explicit exclusive-update sizing, largest-block admission, and a C6 no-PSRAM minimum profile. Nine synthetic cases and 64 pressure rounds pass with zero retained tickets; the HP1 firmware tree has not been physically rerun. See [HP1 resource authority](HP1_HOST_KERNEL_RESOURCE_AUTHORITY.md). |
| Host build coherence | HP2 separates named-board identity, host capability/resource profile, normalized application intent, deterministic host plan, exact replayable build lock, and build-derived running fingerprint. Both retained board realizations replay exactly; ten contract tests, eight C prelaunch cases, and eight Python negative cases close as `HOST_BUILD_COHERENCE_PROVEN`. The pass is host-synthetic only: no current firmware build, flash, or hardware execution is claimed. See [HP2 build coherence](HP2_HOST_BUILD_COHERENCE.md). |
| Production security policy | Implemented as a fail-closed contract; final crypto integration pending. |
| ESP-IDF family lane | Exact `v5.4.4` lane, four realizations, configuration overlays, and per-target WAMR locks are pinned and host-validated. IF7 seals the observed mapping: S3 `BUILD_QUALIFIED`, C6 `COMPILE_PROVEN`, and the declared no-PSRAM C3/classic ESP32 realizations evidence-complete `INCOMPATIBLE` at final-link internal-DRAM limits. See the [canonical matrix evidence](reference/IDF_FAMILY_MATRIX.md). |
| Packaging and evidence | Source packaging is deterministic, allowlisted, and capped at 2 MiB. Installed ESP-IDF/toolchains and resolved managed components remain external; compact accepted-run indexes are source-distributed, while full host and evaluated hardware evidence receive separate manifested archives. |
| Native extension spine | HX4/HX4.5 establish the existing event/Wasm/effect path, sealed numeric registry, exactly-once completion, and adversarial host boundary. The reconciled HX5b AITRIP S3 and XIAO C6 runs now physically observe raw ELF admission, relocation, descriptor entry, extension-owned task/queue lifecycle, common WAMR behavior, clean unload/recovery, real Wasm trap containment, reset-required handling, and retained resource floors on both named boards. Native ELF remains trusted target refinement, not a sandbox or default host-service container. See [HP0 reconciliation](HP0_EVIDENCE_RECONCILIATION.md). |
| Native extension fault hardening | HX5a freezes six fault categories, re-executes 56 inherited/current host cases, and injects all nine lifecycle return transitions through a test-only seam. Invalid state and real budget exhaustion are distinct; uncertain or partial ELF unload preserves provenance and requires reset. No public ABI, import, capability, or peripheral surface changed. See [HX5a fault-model hardening](HX5A_EXTENSION_FAULT_HARDENING.md). |
| Native extension pressure seal | HX5b re-executes HX5a, then runs 64 queue saturation/recovery rounds, 128 late/duplicate completion iterations, 64 reset-simulated native faults, and 64 real Wasm trap/recovery cycles under fixed reservations with zero tracked host retention. Both opt-in named-board campaigns pass five measured cycles, 128 target native/common-Wasm round trips, eight exact overflows, lifecycle timing, trap/reset behavior, and fail-closed evaluation. The final qualifier reports `DUAL_ISA_PRESSURE_OBSERVED` and `DUAL_NAMED_BOARD_OBSERVED`; exact accepted hashes are in the [hardware evidence index](../evidence/hardware/INDEX.md). |

## Unqualified boundaries

### Target build and hardware

The repository proves the matrix, component-lock inputs, host-side builder and
orchestrator behavior, a reproducible ESP32-S3 compile, and an explicit build
result for all three exploratory realizations in the exact pinned lane. HP0
also reconciles the separate physical HX5b evidence for the exact AITRIP S3 and
XIAO C6 boards. Neither evidence class proves:

- that the no-PSRAM C3 or classic ESP32 realizations fit internal DRAM;
- GPIO levels and safe-state behavior on a real board;
- production watchdog/reset attribution beyond the isolated HX5b harness;
- physical interruption behavior beyond the frozen HP3.5 safe subset, including
  exhaustive byte-prefix target runs or uncontrolled power cutting;
- application-slot trial, confirmation, fallback, or recovery on current
  hardware;
- target execution of HP1 interrupt notification, priority ordering, and
  general C6 application admission for the current firmware tree; or
- target execution of the HP2 fingerprint record and prelaunch gate from a
  current exact locked build; or
- production throughput, radio contention, long-duration soak, power, or
  thermal behavior.

The S3 reference firmware is reproducibly build-qualified under the pinned
ESP-IDF lane. Additional family targets have explicit compile-probe results.
The [IF7 matrix reference](reference/IDF_FAMILY_MATRIX.md) is authoritative for
the source, lane, configuration, lock, report, and log hashes behind that
statement.

The retained AITRIP N8R2 and XIAO ESP32C6 evaluators both report
`NAMED_BOARD_OBSERVED`. Their full build trees, serial logs, firmware artifacts,
and reports remain in a separate manifested artifact; source carries only the
accepted identities. A board-vendor name remains operator-attested rather than
electronically authenticated.

### Production cryptography

The verifier callback and policy are defined, but a vetted Ed25519 or platform-crypto implementation and known-answer tests must be integrated before production deployment.

### Native networking

HP5 implements production-shaped ESP-IDF station Wi-Fi and dual HTTPS listener
source behind fixed host-owned bounds. HP5.5 now implements the exact builders,
fixture, client, secret boundary, and fail-closed two-board evidence evaluators,
but those tools have not yet been run on the named hardware in this snapshot.
Association, TLS, HTTP, administration, update/recovery/reset, response-loss,
and resource-floor claims therefore remain `HARDWARE_PENDING`. MQTT remains
unimplemented and begins only after the later provider/customer-zero boundary.

### Device profiles

The current firmware uses a built-in static profile. Field-updatable profiles would require their own signing, validation, activation, rollback, and compatibility policy.

### Deferred capabilities

BLE, live Wasm hot-swap, raw I2C/SPI passthrough, multi-bundle scheduling, richer storage, and fleet management are intentionally deferred.

## Highest-value next work

1. Execute HP5.5 as the exact dual-board physical administration/web audit,
   including Wi-Fi, TLS, application traffic, protected administration,
   update/recovery/reset, response-loss semantics, and retained HP1 floors.
2. Keep HP6 provider ergonomics, HP7 MQTT, RAX, and host-firmware OTA deferred
   until the HP5.5 evidence is accepted.

Native firmware OTA remains a future plan. Physical firmware updates are
acceptable for the current phase; Pulse application staging, trial activation,
and rollback are the higher-value update-system direction.

## Risks to keep visible

- effectful boot self-tests returning accidentally;
- authorization becoming optional;
- manifest claims bypassing profile validation;
- raw platform APIs leaking into the guest contract;
- production anti-rollback or key policy being skipped;
- candidate confirmation occurring too early;
- outputs not being forced safe after guest failure;
- host-test confidence being mistaken for hardware qualification;
- generated reports being committed as if they were durable release evidence.
- the S3 dedicated-IRAM remainder staying at one byte even though the isolated
  lane places executable ELF text in supported PSRAM;
- the conservative HP1 reserve profile being mistaken for a physical
  observation, production tuning, or a replacement for target admission;
- the HP2 CRC-bearing fingerprint being mistaken for remote attestation, or
  its synthetic prelaunch result being mistaken for a current physical run;
- the passing HP3.5 safe physical subset being mistaken for exhaustive target
  byte-prefix interruption or uncontrolled power-cut evidence;
- the HP4.0 host model being mistaken for a current implementation result;
- the HP4.1 host-native core and serial normalizer being mistaken for a UART
  driver, enabled update/recovery transaction, production authentication, or
  target evidence;
- the HP4.2 host-native transaction being mistaken for a target-tested update
  service, physical flash/power-loss result, production verifier, host OTA, or
  implemented recovery path;
- HX4.5 host adversarial confidence being mistaken for target WAMR, native-task, or hardware qualification.
- HX5a deterministic host fault injection being mistaken for target pressure or hardware fault evidence.
- HX5b host pressure or a single named-board rerun being mistaken for complete dual-ISA pressure evidence.
- the HP4.4 exhaustive host-native seal being mistaken for a target build,
  physical flash/power-loss result, production authenticator, or network
  transport.
- the HP5 source-complete Wi-Fi/HTTPS adapter and host-native result being
  mistaken for a target build, TLS security validation, production credential
  lifecycle, physical listener, or accepted HP5.5 result.
- HP5.5 source readiness, synthetic evaluator tests, or a single named-board
  report being mistaken for the accepted distinct-board physical aggregate.

## Recommended stopping rule

Do not resume the broad per-capability roadmap. HX5b and HP0 through HP5's host
and named-board safe-subset seals are closed, but they authorize only the host
platform/recovery/network source contract unit. Complete HP5.5 before MQTT, provider ergonomics, RAX,
host-firmware OTA, or broad peripherals. Add later capabilities through explicit host-owned
primitives and the provider refinement spine rather than expanding the base
host semantically by accident.
