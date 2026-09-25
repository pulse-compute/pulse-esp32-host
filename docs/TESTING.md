# Testing and coverage

The current suite is strongest at host-side contract verification. It is intentionally not a device qualification suite.

## Test layers

| Layer | Location | Purpose |
|---|---|---|
| Python contract tests | `tests/contract/` | Schemas, tools, state machines, policy, and milestone behavior. |
| Native C smoke tests | `tests/firmware-unit/` | Selected firmware components compiled and exercised on the host. |
| Milestone gates | `tools/check_r*.py` | Narrow regression checks and bounded reports. |
| Documentation check | `tools/check_docs.py` | Required docs and local links. |
| IDF family seal | `tools/check_idf_family_docs.py` | Matrix claims, input hashes, evidence index, and forbidden support-language checks. |
| HX extension admission | `tests/contract/test_hx2_extension_admission.py` | Dual-ISA ELF/metadata vectors, descriptor and registry rejection, zero-lifecycle proof, ABI layout, and SHA-256 known answers. |
| HX extension lifecycle | `tests/contract/test_hx3_extension_lifecycle.py` and `tests/contract/hx3_lifecycle_smoke.c` | Twelve lifecycle/failure/reset cases, reverse unwind, static task/queue ownership, exact imports, and 32 repeated cycles. |
| HX event/effect happy path | `tests/contract/test_hx4_extension_event_effect.py`, `hx4_roundtrip_smoke.c`, and `hx4_wasm_smoke.mjs` | Complete host ownership path, real execution of the common Wasm bytes, identical target-neutral artifact, and exactly-once completion sentinel. |
| HX5a fault hardening | `tests/contract/test_hx5a_extension_faults.py` and `hx5a_fault_injection_smoke.c` | Nine private deterministic transition points, reverse cleanup, reset latching, state/budget classification, production-symbol exclusion, and unified report integrity. |
| Hardware-in-loop | `tests/hardware-in-loop/hx45-s3-aitrip-n8r2/` and `hx45-c6-seeed-xiao-4m/` | Isolated named-board harnesses whose retained HX5b S3 and C6 reports pass and reconcile under HP0. |
| HP0 evidence reconciliation | `tools/reconcile_hp0_evidence.py` and `tests/contract/test_hp0_evidence_reconciliation.py` | Exact v17/handoff/input binding, embedded hash verification, dual-report agreement, nested-workspace exclusion, and deterministic manifested packaging. |
| HP1 resource authority | `tools/qualify_host_kernel.py`, `tests/contract/test_hp1_host_kernel_resource_authority.py`, and `hp1_control_kernel_smoke.c` | Fixed ISR capture, direct task-notification source contract, priority preemption, per-class capacity, terminal completion, C6/S3 admission, arithmetic rejection, and zero-retention pressure. |
| HP2 build coherence | `tools/qualify_host_build.py`, `tests/contract/test_hp2_host_build_coherence.py`, and `hp2_host_identity_smoke.c` | Artifact separation, deterministic planning, exact non-upgrading lock replay, fingerprint integrity, app-only selection, target/ABI/capability/placement rejection, and HP1-backed prelaunch admission. |
| HP3 application slots | `tools/qualify_app_slots.py`, `tests/contract/test_hp3_application_slots.py`, and `hp3_app_slots_smoke.c` | Fixed artifact, dual layouts, inactive streaming, stored verification, journal recovery, boot attribution, host probation, fallback preservation, compatibility/security rejection, and explicit recovery. |
| HP3.5 slot adversarial seal | `tools/qualify_app_slot_adversarial.py`, `tests/contract/test_hp3_5_slot_adversarial.py`, and `tests/ota-power-loss/hp3_5_slot_adversarial_smoke.c` | Every payload prefix; both journal records; eight transitions; every erase/body/marker prefix; reset during confirmation; corruption, timeout, traps, watchdogs, invalid hashes/signatures, incompatible fingerprints, durable-authority resynchronization, and atomic confirmed fallback. |
| HP4.0 administration contract | `tools/qualify_admin_contract.py` and `tests/contract/test_hp4_0_administration_contract.py` | Exact identity/replay/session/terminal/audit records, fixed bounds and deadlines, twelve legal mode transitions, five legal scenarios, 62 missing-guard denials, authority hashes, source reconciliation, unchanged firmware seals, and negative claim/surface checks. |
| HP4.1 administration core | `tools/qualify_admin_core.py`, `tests/contract/test_hp4_1_administration_core.py`, and `hp4_1_admin_core_smoke.c` | Allocation-free fixed storage, attended replaceable authorization, strict replay/rate/deadline handling, HP1 capacity ownership, first-terminal-wins completion, bounded serial normalization, audit loss accounting, and a fail-closed artifact-verifier seam. |
| HP4.2 exclusive update | `tools/qualify_admin_update.py`, `tests/contract/test_hp4_2_admin_update.py`, and `hp4_2_admin_update_smoke.c` | Positive quiesce/unload, exact C6 HP1 admission, inactive-only bounded streaming, complete artifact/HP2/security/verifier checks, abort and timeout authority preservation, interrupted journal handling, and durable `TRIAL` reboot handoff. |
| HP4.3 host-only recovery | `tools/qualify_admin_recovery.py`, `tests/contract/test_hp4_3_admin_recovery.py`, and `hp4_3_admin_recovery_smoke.c` | HP3 no-viable and authorized entry, application/refinement absence, fixed status, recovery-origin staging and abort, HP1 denial, complete candidate activation, read-only viable reboot, and no-reboot-loop denial. |
| HP4.4 administration adversarial seal | `tools/qualify_admin_adversarial.py`, `tests/contract/test_hp4_4_admin_adversarial.py`, and `hp4_4_admin_adversarial_smoke.c` | 3,523 exact negative cases across preaccept, replay, quiesce, resource, every safe stream prefix, stream transactions, verification, journal interruptions, saturation, terminal/audit, and recovery; plus 41 inherited HP4 native cases and exact source/authority replay. |
| HP5 host network mediator | `tools/qualify_host_network.py`, `tests/contract/test_hp5_host_network.py`, and `hp5_http_service_smoke.c` | Fixed parser/route/listener bounds, admin namespace isolation, common-Wasm request/paired-response flow, authenticated external HP4 reuse, saturation/deadline/cancellation/trap behavior, network response loss, and exact source/authority replay; 35 new plus 3,564 inherited native cases. |
| Release packaging | `tools/package_release.py` | Deterministic source allowlist, compact accepted-run indexes, and separate manifested host/hardware evidence archives. |
| OTA power-loss | `tests/ota-power-loss/` | HP3.5 deterministic host flash/journal model and exhaustive 11,657-case interruption seal. |
| Target fault injection | `tests/fault-injection/` | Placeholder for HX5b device-backed pressure and driver fault campaigns; HX5a host lifecycle injection lives in `tests/contract/`. |

## Covered well in host tests

- ABI constants, status codes, and deterministic encoding;
- profile and manifest validation;
- capability allow/deny decisions;
- event envelopes and queue accounting;
- safety-state transitions and safe-output model;
- bundle container, hash, signature-policy, and metadata checks;
- activation and rollback state machine;
- native network-policy decisions;
- runtime-limit policy;
- production security-policy behavior.
- HX2 native ELF/metadata/descriptor/registry admission and negative vectors.
- HX3 lifecycle ordering, reverse unwind, illegal-transition rejection,
  reset-required policy, resource declarations, and caller-bounded host-service
  source contracts.
- HX4 event queue reuse, Wasm handler entry, sealed operation resolution,
  host-owned correlation/deadline, bounded completion, and real common-Wasm
  execution on the development host.
- HX4.5 unknown identities, queue overflow, event/effect oversize, deadline
  expiry, late/duplicate completion, quiescence cancellation, real Wasm trap,
  and extension-fault reset latching.
- HX4.5 AITRIP hybrid ELF allocation policy: executable requests select PSRAM
  and writable requests select internal byte-accessible RAM without enabling
  external FreeRTOS task stacks. The exact sealed layout proves a 6,978-byte
  packed image, sixteen-byte maximum alignment, base residue 14, aligned
  descriptor/BSS addresses, and release of the original allocation on unload.
- HX4.5 AITRIP WAMR allocation policy: executable mmap requests retain the
  pinned port behavior while writable linear memory selects internal 8-bit
  RAM with the port-compatible hidden release prefix.
- WAMR module-buffer ownership: immutable verified input is copied into
  internal writable storage, mutation cannot affect the source artifact, and
  the copy is released only after module unload.
- HX5a service-bind, initialize, start, health, invoke, quiesce,
  post-quiesce-health, deinitialize, and unload return faults, including
  partial side effects and partial reverse unload.
- HX5a fail-closed distinction between invalid lifecycle state and real
  capacity exhaustion, plus reset-required unload uncertainty.
- HX5b host pressure: 64 queue rounds, 128 late/duplicate completion
  iterations, 64 native fault/reset simulations, 64 real Wasm trap/recovery
  cycles, and zero tracked retention under fixed reservations.
- named-board HX5b execution on the AITRIP S3 and XIAO C6: five measured
  lifecycle cycles, 128 native/common-Wasm round trips, eight exact overflows,
  heap/largest-block and stack floors, trap containment, reset-required, and
  retained breadcrumb evidence.
- HP1 host control authority: five fixed priority classes, independently
  reserved queues/tickets, eight fixed ISR captures plus recovery-latching
  overflow, eight fail-closed admission classes, exact C6 total/largest-block
  margins, and 320 accepted/terminal work items with zero retained slots.
- HP2 host build coherence: two exact board/profile/lock/fingerprint
  realizations, application-independent host plans, exact input/tree replay,
  eight C prelaunch cases, eight Python negative cases, and zero application
  entry on every check path.
- HP3 application slots: fourteen C cases covering fixed artifact validation,
  sequential inactive staging, `STAGED`/`VERIFIED` commits, persisted trial
  boot, host confirmation, attributed-reset fallback, last-confirmed
  preservation, corrupt artifact, security/authority/target rejection,
  explicit recovery, and one-corrupt-journal-record recovery.
- HP3.5 application-slot interruption: 2,362 payload prefixes, six structural
  erase boundaries, 8,240 two-record transition cuts, 1,030 confirmation
  reset cuts, three journal corruption outcomes, sixteen semantic cases, and
  32 repeated trap cycles with no lost confirmed authority or ambiguous boot.
- HP4.0 protected-administration model: four exact fixed record layouts,
  one-session/one-command capacity, atomic replay reservation, twelve legal
  transitions, five complete paths, 62 guard-removal denials, terminal reboot
  handoff to HP3, and unchanged guest/native-extension administrative surfaces.
- HP4.1 protected-administration core: fourteen native cases covering fixed
  layouts and 9,784 bytes of combined core/serial storage, attended replaceable
  authorization, auth-failure backoff, preaccept rejection, strict epoch/nonce/
  sequence replay, application-pressure isolation, exactly-one terminal
  response, serial fragmentation and bounds, deadlines, audit overwrite/loss,
  and a replaceable verifier that fails closed before HP4.2.
- HP4.2 exclusive update transaction: fifteen native cases covering exact C6
  admission, positive quiesce/unload, active-slot denial, both memory denials,
  stream bounds/rate/timeout, abort, hash and security rejection, verifier
  denial, interrupted `TRIAL` journaling, and durable reboot handoff.
- HP4.3 host-only recovery: twelve native cases covering automatic no-viable
  entry, malformed boot evidence, fixed secret-free status, idle abort,
  no-viable reboot denial, recovery-origin stage/abort, HP1 denial, complete
  candidate activation, administrative entry, malformed unload evidence,
  read-only viable reboot, and preaccept recovery-shape rejection.
- HP4.4 administration adversarial seal: 3,523 new native cases, including
  every prefix of the 2,361-byte stored artifact, all 1,030 erase/body/marker
  cuts across both journal records, authorization/replay/sequence exhaustion,
  quiesce and resource denials, saturation, terminal/audit races, and forty
  recovery interactions. Fourteen HP4.1, fifteen HP4.2, and twelve HP4.3 cases
  also rerun for 3,564 aggregate passing host-native cases.

## Requires target evidence

- actual GPIO levels and electrical safety;
- production watchdog and reset attribution beyond the isolated HX5b harness;
- physical flash slot and metadata persistence under interruption (the
  exhaustive deterministic host model passes);
- physical power-loss recovery on both named boards;
- secure boot, flash encryption, and provisioning state;
- native Wi-Fi/MQTT/HTTP behavior;
- production cryptographic verification;
- long-duration event/rate pressure with radio contention and production
  application load;
- HP1 control-plane reserve, task notification, and interrupt-priority behavior
  on the current S3/C6 firmware under worst-case memory pressure; and
- HP2 fingerprint and prelaunch behavior compiled and executed from the exact
  current locks on both named boards; and
- application-slot power loss plus target execution of trial failure, fallback,
  and protected recovery; and
- HP4.1 compiled and executed on the named targets with a real attended serial
  driver, production authorization/cryptography, and worst-case concurrent
  application pressure.

## Build mapping evidence

The [ESP-IDF family build matrix](reference/IDF_FAMILY_MATRIX.md) records a
separate build-only layer. S3 has two byte-reproducible observations; C3,
classic ESP32, and C6 have explicit compile-probe classifications. These do not
move any item from the target-evidence list above into the host-tested set.

Run `make idf-family-seal-check` for the static matrix/documentation contract.
Run `tools/run_pinned_idf_matrix.sh` only with a fresh evidence directory to
repeat the actual pinned-lane observations.

For the cumulative HX4.5 adversarial seal, run:

```bash
make check-hx0 check-hx1 check-hx2 check-hx3 check-hx4 check-hx4-5
HX_OUT_DIR=reports/host-extension/hx45-<fresh-id> \
  make host-extension-adversarial-qualify
```

The qualifier executes inherited mock lifecycle policy, the complete HX4 host
round trip, all 11 HX4.5 negative cases, exact common-Wasm rejection
propagation, and a real Wasm event trap. It then performs two isolated
synthetic ELF and firmware builds per target. It reports
`ADVERSARIAL_HOST_SEALED`, `BUILD_ONLY_PROVEN`, and `HARDWARE_NOT_RUN`; it never
promotes host or build evidence to a FreeRTOS/WAMR target-runtime claim.

For the HX5a structural hardening report, run:

```bash
make check-hx5a
HX_OUT_DIR=reports/host-extension/hx5a-<fresh-id> \
  make host-extension-faults-qualify
```

That report re-executes 56 host cases across the inherited and HX5a corpora,
hashes every transcript, and records hardware as `NOT_RUN` for the pass.
Sustained pressure and targeted named-board reruns are HX5b.

HX5b executes from `tests/contract/hx5b_pressure_smoke.c` and
`tests/contract/hx5b_wasm_pressure_smoke.mjs`, with its exact bounds frozen in
`specs/PULSE-ESP32-005b-extension-pressure-seal.json`. The S3 and C6 HIL
templates expose pressure only under `PULSE_HX5B_PRESSURE`; the ordinary HX4.5
campaign remains unchanged. HP0 reconciles the separately retained physical
serial/build/evaluator trees; source carries their accepted hashes, not the
generated evidence itself.

Re-run the HP0 static contract with:

```bash
make check-hp0
```

Recreate the deterministic combined evidence artifact only with the exact
source snapshot, corrected handoff, input archive, and three accepted run
roots described in [Packaging and evidence](PACKAGING_AND_EVIDENCE.md).

Run the HP1 static and synthetic resource-authority seal with:

```bash
make check-hp1
HP1_OUT_DIR=reports/host-kernel/hp1-<fresh-id> \
  make host-kernel-qualify
```

The qualifier compiles and executes the allocation-free control kernel with
synthetic work and interrupt sources. It emits a manifested host report with
`HOST_RESOURCE_AUTHORITY_PROVEN` and `hardware_execution_this_pass=NOT_RUN`.
The retained HP0 heap floors are sizing inputs, not promoted HP1 hardware
evidence.

Run the HP2 build-coherence and running-fingerprint seal with:

```bash
make check-hp2
HP2_OUT_DIR=reports/host-build/hp2-<fresh-id> \
  make host-build-qualify
```

The qualifier replays both exact locks, regenerates the fixed C fingerprints,
compiles and executes the prelaunch smoke, and exercises eight independent
negative cases. It reports `HOST_BUILD_COHERENCE_PROVEN` with
`hardware_execution_this_pass=NOT_RUN`; it does not build ESP-IDF firmware or
implement an external provider.

Run the HP3 application-slot seal with:

```bash
make check-hp3
HP3_OUT_DIR=reports/app-slots/hp3-<fresh-id> \
  make app-slots-qualify
```

The qualifier checks both fixed layouts and exact HP2 bindings, compiles with
warnings as errors, and executes the fourteen-case slot smoke. It reports
`PULSE_APPLICATION_SLOT_AUTHORITY_PROVEN` with hardware, firmware build, and
physical power-loss evidence explicitly not claimed. HP3.5 owns exhaustive
interruption work.

Run the HP3.5 host interruption seal with:

```bash
make check-hp3-5
HP3_5_OUT_DIR=reports/app-slots/hp3_5-<fresh-id> \
  make app-slots-adversarial-qualify
```

The qualifier compiles with warnings as errors and requires the exact
11,657-case result. It reports `HOST_SLOT_ADVERSARIAL_POWER_LOSS_SEALED` and
keeps hardware `NOT_RUN`. The frozen physical campaign and dual evaluator are
checked as contracts; they do not manufacture a board observation.

That per-execution classification remains correct for the host qualifier. A
separate retained physical campaign subsequently passed both named boards and
the dual evaluator as `DUAL_NAMED_BOARD_SAFE_SUBSET_OBSERVED`. Its accepted
external identities are frozen in the
[HP3.5 hardware evidence index](../evidence/hardware/HP3_5_INDEX.md); they are
not regenerated by `make check-hp3-5`.

The same contract suite now prepares both canonical HP3 named-board projects,
checks the exact campaign/partition/source seals, exercises the per-board
serial report producer with temporary positive and negative fixtures, and
feeds two accepted fixture reports through the dual gate. These are parser and
build-contract tests, not physical observations. The real backup, erase,
flash/monitor, evaluation, and restore commands are in the
[physical campaign runbook](../tests/hardware-in-loop/hp3_5-slot-power-loss/README.md).

Run the HP4.0 host-model seal with:

```bash
make check-hp4-0
HP4_0_OUT_DIR=reports/administration/hp4_0-<fresh-id> \
  make administration-contract-qualify
```

The historical qualifier reports `HOST_ADMINISTRATION_CONTRACT_FROZEN` and
`HOST_MODEL_ONLY`. It validates the frozen contract and preserved authority
inputs, including the exact accepted HP4.4 successor chain; it does not
build firmware, stage an artifact, run a serial driver, or produce target
evidence.

Run the HP4.1 host-native implementation seal with:

```bash
make check-hp4-1
HP4_1_OUT_DIR=reports/administration/hp4_1-<fresh-id> \
  make administration-core-qualify
```

The qualifier reports `HOST_PROTECTED_ADMINISTRATION_CORE_IMPLEMENTED` and
`HOST_NATIVE_CORE_ONLY`. It compiles and executes fourteen native C cases and
binds the exact source/authority seals. It does not compile ESP-IDF, exercise a
UART, supply production authentication or cryptography, execute HP4.2 update
staging, enter HP4.3 recovery, or produce physical evidence.

Run the HP4.2 host-native transaction seal with:

```bash
make check-hp4-2
HP4_2_OUT_DIR=reports/administration/hp4_2-<fresh-id> \
  make administration-update-qualify
```

The qualifier reports `HOST_EXCLUSIVE_UPDATE_TRANSACTION_IMPLEMENTED` and
`HOST_NATIVE_UPDATE_TRANSACTION_ONLY`. It compiles and executes fifteen native
C cases and binds the exact HP1 through HP4.1 authorities and source history.
It does not compile ESP-IDF, exercise a serial driver or physical flash, supply
production authentication or cryptography, enter recovery, update host
firmware, or produce physical evidence.

Run the HP4.3 host-native recovery seal with:

```bash
make check-hp4-3
HP4_3_OUT_DIR=reports/administration/hp4_3-<fresh-id> \
  make administration-recovery-qualify
```

The qualifier reports `HOST_ONLY_RECOVERY_IMPLEMENTED` and
`HOST_NATIVE_RECOVERY_TRANSACTION_ONLY`. It compiles and executes twelve
native C cases and binds the exact HP1 through HP4.2 authority and source
history. It does not compile ESP-IDF, drive a serial port, update the host or
factory partition, supply production authentication or cryptography, or
produce new physical evidence.

Run the HP4.4 host-native administration adversarial seal with:

```bash
make check-hp4-4
HP4_4_OUT_DIR=reports/administration/hp4_4-<fresh-id> \
  make administration-adversarial-qualify
```

The qualifier reports `HOST_ADMINISTRATION_ADVERSARIAL_SEALED` and
`HOST_NATIVE_ADMINISTRATION_ADVERSARIAL_ONLY`. It compiles and executes 3,523
new C cases, reruns 41 inherited HP4 cases, and binds the exact HP1 through
HP4.3 authorities and source history. It creates no ESP-IDF build, target run,
physical result, serial/network driver, production authenticator/cryptography,
host/factory OTA, or partition change. HP4 is complete.

Run the HP5 host-network mediator gate with:

```bash
make check-hp5
HP5_OUT_DIR=reports/network/hp5-<fresh-id> \
  make host-network-qualify
```

The qualifier reports `HOST_NETWORK_MEDIATOR_IMPLEMENTED` and
`HOST_NATIVE_NETWORK_MEDIATOR_ONLY`. It compiles and executes 35 new native C
cases, reruns all 3,564 HP4 native cases, and binds the exact HP1 through HP4.4
authorities and HP4.4 archive/source history. It validates production-shaped
ESP-IDF Wi-Fi/HTTPS source but does not invoke ESP-IDF, execute a target,
associate Wi-Fi, complete TLS, create a physical result, provide production
authentication/cryptography/provisioning, implement MQTT, or change the
partition table. Those physical observations begin at HP5.5.

The named-board harness contract and evidence parser are checked with:

```bash
make check-hx45-s3-aitrip
```

That test validates the isolated 8 MB / 2 MB configuration, target-runtime
call surface, deterministic sealed-ELF embedding, Make exposure, and strict
serial-evidence evaluator. It does not compile with ESP-IDF or run a board.
Follow the [AITRIP physical run](HX4_5_S3_AITRIP_HARDWARE.md) to cross that
boundary.

## Qualification principle

```text
host-side PASS + bounded skips = useful development evidence
host-side FAIL                 = regression
hardware skip                  = not a production qualification
unclassified absence          = test or documentation gap
```

Before production use, build a hardware matrix covering boot safety, good activation, bad rollback, power-loss windows, network policy, runtime limits, and production security.
