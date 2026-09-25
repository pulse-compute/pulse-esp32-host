# Codebase map

This document maps the repository to the safety boundary it implements.

## Top-level layout

```text
firmware/                 Native ESP-IDF shell scaffold
firmware/components/      Supervisor components
firmware/boards/          Named physical board realizations
firmware/host-profiles/   Host capability/resource profiles
firmware/host-build/      Exact locks and derived fingerprints
native-sdk/               Experimental target-native extension C ABI
native-extensions/        Target-specific extension sources
guest-sdk/                Guest-side bindings/examples
examples/                 Profiles, manifests, generated bundles
schemas/                  JSON schemas
specs/                    Normative design specs
evidence/                 Compact accepted-run indexes; source-distributed
reports/                  Generated local reports and logs; ignored by Git
tests/                    Host-side contract and smoke tests
tools/                    Validation/build/packaging/report scripts
docs/                     Project documentation
```

## Firmware components

### `wdc_abi`

Files:

- `firmware/components/wdc_abi/include/wdc_abi.h`
- `firmware/components/wdc_abi/include/wdc_cbor.h`
- `firmware/components/wdc_abi/include/wdc_guest_memory.h`
- `firmware/components/wdc_abi/wdc_host_call.c`
- `firmware/components/wdc_abi/wdc_cbor.c`
- `firmware/components/wdc_abi/wdc_pointer.c`
- `firmware/components/wdc_abi/wdc_errors.c`

Responsibilities:

- ABI major/minor constants;
- import/export names;
- status codes;
- host-call opcode constants;
- CBOR key constants;
- guest pointer/range validation;
- configurable host-call request/response limits;
- dispatcher and host-hook plumbing.

### `wdc_runtime`

Files:

- `firmware/components/wdc_runtime/include/wdc_runtime.h`
- `firmware/components/wdc_runtime/wdc_runtime.c`
- `firmware/components/wdc_runtime/wdc_static_wasm.c`
- `firmware/components/wdc_runtime/test_vectors/*.wasm`

Responsibilities:

- runtime config;
- runtime outcome reporting;
- WAMR/host-stub backend split;
- static payload loading;
- lifecycle export resolution;
- lifecycle calls;
- event dispatch with maximum event-size enforcement.

### `wdc_events`

Responsibilities:

- event envelope definition;
- event CBOR encode/decode;
- fixed-capacity event queue;
- dropped-count tracking.

### `wdc_control`

Files:

- `firmware/components/wdc_control/include/wdc_control.h`
- `firmware/components/wdc_control/wdc_control.c`
- `firmware/components/wdc_control/wdc_control_platform_espidf.c`

Responsibilities:

- fixed mapping from host source to five priority classes;
- per-class static queue, ticket, and terminal-completion ownership;
- allocation-free single-producer/single-consumer ISR capture;
- ESP-IDF direct task notification and heap/largest-block sampling;
- C6 no-PSRAM and S3 explicit-PSRAM resource profiles; and
- checked normal, quiesce-transition, exclusive-update, and contiguous-block
  admission.

It must not own an application protocol, production peripheral, guest/native
ABI, slot state, build lock, or update authorization.

### `wdc_admin`

Files:

- `firmware/components/wdc_admin/include/wdc_admin.h`
- `firmware/components/wdc_admin/wdc_admin.c`
- `firmware/components/wdc_admin/wdc_admin_serial.c`
- `firmware/components/wdc_admin/wdc_admin_update.c`
- `firmware/components/wdc_admin/wdc_admin_recovery.c`
- `firmware/components/wdc_admin/include/wdc_admin_recovery.h`

Responsibilities:

- maintain one fixed host-private session and one HP1-owned accepted command;
- invoke a replaceable attended authorizer and enforce failure backoff;
- validate epoch, nonce, strictly consecutive sequence, rate, and deadline
  before atomically committing replay and command ownership;
- retain exactly one terminal response until it is consumed;
- incrementally normalize one bounded length-prefixed serial frame;
- expose a replaceable artifact-verifier seam;
- require positive guest/refinement unload and exact HP1 exclusive admission;
- stream and verify one bounded inactive-slot artifact and durably mark it
  `TRIAL` before reboot handoff;
- enter host-only recovery from bound HP3 no-viable evidence or positive
  administrative quiesce/unload evidence;
- keep fixed secret-free status and abort available with no application loaded;
- return recovery-origin candidate failures to recovery and require a read-only
  HP3/HP2 viability proof before reboot handoff; and
- record a 32-entry overwrite audit ring with explicit loss accounting.

It does not expose an application or native-extension ABI, drive a UART,
provide production authentication/cryptography, enter recovery, update host
firmware, or own durable state outside the existing HP3 journal.

### `wdc_host_identity`

Files:

- `firmware/components/wdc_host_identity/include/wdc_host_identity.h`
- `firmware/components/wdc_host_identity/wdc_host_identity.c`
- `firmware/components/wdc_host_identity/wdc_host_fingerprint_generated.c`

Responsibilities:

- validate the fixed build-derived running fingerprint and CRC;
- expose the exact target fingerprint selected at compile time;
- compare application target, ABI, capabilities, and placement requirements;
- delegate live total-free/largest-block/transition admission to `wdc_control`;
  and
- reject before application entry on any malformed or incompatible input.

It does not select or resolve build dependencies, implement remote
attestation, launch application code, or expose host-build concepts to the
guest ABI.

### `wdc_profile`

Responsibilities:

- builtin relay-node profile;
- logical resource lookup;
- GPIO resources with pin/mode/active/safe-level data;
- network resources with topic/URL/method policy.

### `wdc_caps`

Responsibilities:

- capability manifest parsing;
- resource capability checks;
- config-key capability checks;
- rate-limit bookkeeping;
- authorization audit records;
- host-call authorizer installation.

### `wdc_safety`

Responsibilities:

- boot-safe/no-bundle/app-running/fault-stopped states;
- applying safe GPIO defaults;
- forcing outputs safe on fault;
- fail-closed guarded authorizer;
- stopped-state write denial;
- safety counters and status reporting.

### `wdc_bundle`

Responsibilities:

- WDCBNDL container header parsing;
- manifest and payload hash verification;
- manifest-to-payload binding;
- dev HMAC signing support for tests;
- production verifier callback support;
- manifest summary extraction;
- lifecycle export-section parsing;
- metadata record validation/sealing.

### `wdc_ota`

Responsibilities:

- slot label mapping;
- bounded sequential staging and range reads;
- host-side slot stubs;
- two-record metadata journal with commit markers, body-before-marker writes,
  corruption detection, and generation selection.

### `wdc_activation`

Responsibilities:

- trial candidate preparation and persisted boot/reset attribution;
- boot-time trial/confirmed/fallback/recovery decision;
- candidate boot budget;
- host-owned readiness/stability/health/resource-floor confirmation;
- fault recording and fallback selection.

### `wdc_app_slots`

Responsibilities:

- fixed 192-byte application-artifact header validation;
- inactive-only streaming and stored-byte verification;
- bundle authority, security floor, HP2 compatibility, and HP1 prelaunch gates;
- journaled `STAGED`, `VERIFIED`, `TRIAL`, `CONFIRMED`, and `REJECTED`
  transitions; and
- preservation of last-confirmed bytes, fallback-reboot, and explicit recovery.

It does not implement RAX, transport, provider behavior, Pulse-core changes, or
host-firmware OTA, and it never enters application code.

### `wdc_app`

Responsibilities:

- legacy active-slot boot plus the canonical managed-slot runtime bridge;
- entering application code only after `wdc_app_slots_boot` and prelaunch;
- installing verified capability sets;
- clearing active authorizers on teardown.

### `wdc_net`

Responsibilities:

- native-managed network state;
- MQTT publish/subscribe policy checks;
- HTTP request URL/method policy checks;
- network operation counters and last-operation records; and
- a host-private paired HTTP response hook with no administration dependency.

### `wdc_http`

Files:

- `firmware/components/wdc_http/include/wdc_http.h`
- `firmware/components/wdc_http/include/wdc_http_service.h`
- `firmware/components/wdc_http/include/wdc_http_platform.h`
- `firmware/components/wdc_http/wdc_http_service.c`
- `firmware/components/wdc_http/wdc_http_runtime.c`
- `firmware/components/wdc_http/wdc_http_platform_espidf.c`

Responsibilities:

- own HP5 station Wi-Fi, TLS material references, sockets, and reconnect policy;
- reserve distinct application and administration HTTPS servers, parsers,
  tasks, control ports, and socket caps;
- register four exact immutable application routes outside the protected
  namespace;
- dispatch bounded requests through the common Wasm event handler and accept
  at most one matching paired response; and
- normalize fixed protected routes into the existing HP4 authenticated-entry,
  binary-frame, session, command, terminal, update, and recovery authority.

It must not assign principal identity, create another replay/command/terminal
machine, cancel accepted administration on network loss, mutate HP3 boot
authority, expose credentials to portable artifacts, or make `wdc_net` depend
on `wdc_admin`.

### `wdc_security`

Responsibilities:

- development vs production security policy;
- production preflight requirements;
- bundle verifier policy construction;
- trusted key-id enforcement;
- anti-rollback floor derivation;
- provisioning validation.

### `wdc_elf` and `wdc_extension`

Responsibilities:

- keep the exact ELF loader behind an opaque adapter;
- inspect raw ELF structure, metadata, target identity, imports, relocations,
  constructors, budgets, and normalized hashes before relocation;
- validate the canonical runtime descriptor and its executable addresses;
- reject duplicate numeric extension/event/operation identities; and
- seal the complete registry before lifecycle execution;
- supervise ordered init/start/health/quiesce/deinit transitions and reverse
  unwind; and
- latch reset after uncertain post-start teardown without host force-deleting
  the extension task;
- copy admitted extension events into `wdc_events`, dispatch through the
  existing runtime/ABI path, and resolve effects only through the sealed
  registry; and
- own correlation, deadline, and exactly-one bounded completion state.

The sole experimental public ABI header is
`native-sdk/c/include/pulse_extension.h`. HX3 implements the host lifecycle in
`wdc_extension_lifecycle.c`, candidate-bounded services in
`wdc_extension_host_services.c`, and the exact IDF/FreeRTOS import table in
`wdc_extension_platform_espidf.c`. HX4 adds the target-neutral bridge in
`wdc_extension_bridge.c` and the common Wasm fixture under
`wdc_runtime/test_vectors/`.

## Tools

| Tool | Purpose |
|---|---|
| `tools/wdc_validate.py` | Validate profile/manifest examples. |
| `tools/wdc_bundle_tool.py` | Pack, inspect, install, activate, boot, confirm, fail, and status for local bundles/slots. |
| `tools/wasm_inspect.py` | Inspect imports/exports for WASM fixtures. |
| `tools/validate_wasm_exports.py` | Validate lifecycle exports. |
| `tools/check_deps.py` | Inventory local dependencies. |
| `tools/bootstrap_*.sh` | Bounded dependency bootstrap attempts. |
| `tools/build_guest_wasm.sh` | Build Rust guest bundle when Rust is installed. |
| `tools/build_firmware.sh` | Build firmware when ESP-IDF is installed. |
| `tools/build_idf_cell.py` | Build one isolated matrix realization and emit normalized evidence. |
| `tools/qualify_idf_reference.py` | Require two byte-reproducible S3 build observations. |
| `tools/qualify_idf_matrix.py` | Aggregate the required and exploratory IF6 mapping with fail-closed evidence gates. |
| `tools/build_native_extension.py` | Build deterministic loader probes or HX4 synthetic target ELFs. |
| `tools/inspect_native_extension.py` | Dependency-free bounded ELF, metadata, descriptor, and registry inspection. |
| `tools/qualify_extension_admission.py` | Reproducible dual-ISA HX2 builds and zero-lifecycle negative-vector evidence. |
| `tools/qualify_extension_runtime.py` | HX3 lifecycle smoke, exact resource/import evidence, repeated-cycle report, and dual-ISA synthetic reproducibility. |
| `tools/qualify_extension_roundtrip.py` | HX4 native/real-Wasm happy-path evidence, identical common Wasm realizations, and dual-ISA build qualification. |
| `tools/qualify_extension_adversarial.py` | HX4.5 negative corpus, exact-Wasm rejection/trap evidence, source-bound dual-ISA build qualification, and hardware claim boundary. |
| `tools/qualify_extension_faults.py` | HX5a fault-model validation, inherited-corpus re-execution, deterministic lifecycle injection, and unified hashed host report. |
| `tools/host_build_contract.py` | Validate HP2 artifact schemas, make deterministic plans/locks/fingerprints, replay exact inputs, and evaluate compatibility. |
| `tools/resolve_host_build.py` | Explicit plan, new-lock resolution, lock replay, running-host check, and generated-C commands. |
| `tools/qualify_host_build.py` | Replay both HP2 realizations and emit the synthetic C/Python coherence seal. |
| `tools/qualify_app_slots.py` | Replay both locked realizations, validate slot layouts/source contracts, and execute the fourteen-case HP3 synthetic seal. |
| `tools/qualify_app_slot_adversarial.py` | Execute and manifest the exact 11,657-case HP3.5 flash/journal interruption seal. |
| `tools/qualify_admin_contract.py` | Validate HP4.0 fixed records, identity/replay/terminal rules, twelve guarded transitions, authority hashes, source reconciliation, and unchanged HP3.5 firmware seals without claiming implementation. |
| `tools/qualify_admin_core.py` | Compile and execute the fourteen-case HP4.1 native core seal; verify fixed storage, authority hashes, firmware linkage, negative ABI/transport surfaces, and the accepted HP4.0 model. |
| `tools/qualify_admin_update.py` | Compile and execute the fifteen-case HP4.2 native update seal; verify exact resource/stream/authority bounds, durable trial handoff, firmware linkage, source history, and negative claim surfaces. |
| `tools/qualify_admin_recovery.py` | Compile and execute the twelve-case HP4.3 native recovery seal; verify entry evidence, application-free administration, recovery-origin staging, safe reboot proof, exact source history, and negative claim surfaces. |
| `tools/qualify_admin_adversarial.py` | Compile the 3,523-case HP4.4 integrated adversarial matrix, rerun 41 inherited native cases, replay HP1-HP4.3 authority/source history, and emit the manifested HP4 closure. |
| `tools/qualify_host_network.py` | Compile the 35-case HP5 HTTP service harness, rerun all 3,564 HP4 native cases, verify fixed/private source boundaries and exact predecessor hashes, and emit manifested host-network evidence. |
| `tools/qualify_hp5_5_network_hardware.py` | Replay the HP5.5 model, campaign, new target contracts, historical HP2 identities, deterministic fixtures, and four-case dual-profile update smoke while preserving `HARDWARE_PENDING`. |
| `tools/prepare_hp5_5_provision.py` | Create a local mode-0600 test Wi-Fi/TLS/administrator provision outside source without printing or retaining raw secrets. |
| `tools/build_hp5_5_network_hardware.py` | Re-verify the exact HP5 archive, stage the secret-bearing physical project, build either exact named-board lane under pinned ESP-IDF v5.4.4, and emit hash-bound build instructions/evidence. |
| `tools/run_hp5_5_network_client.py` | Drive the physical dual-TLS application, administration, update, reset/fallback, recovery, rate, pressure, and forced-response-loss campaign into a secret-free JSONL transcript. |
| `tools/evaluate_hp5_5_network_board.py` | Bind one attended named-board run to its build, target identity, provision, backup, serial/transcript checkpoints, resource floors, and raw-secret scan. |
| `tools/evaluate_hp5_5_network_hardware.py` | Require two distinct exact PASS board reports before emitting `DUAL_NAMED_BOARD_HP5_NETWORK_ADMIN_OBSERVED`. |
| `tools/evaluate_hp3_5_slot_hardware.py` | Fail closed over two physical named-board safe-subset reports and their serial-log identities. |
| `tools/build_hx45_s3_aitrip.py` | Stage and exact-lane build the isolated AITRIP N8R2 image with the HX4.5-sealed S3 ELF. |
| `tools/evaluate_hx45_s3_aitrip.py` | Re-hash retained build artifacts and fail closed over the complete two-boot AITRIP serial transcript. |
| `tools/package_release.py` | Deterministic allowlisted source packaging plus separately manifested host and hardware evidence archives. |
| `tools/run_pinned_idf_matrix.sh` | Enter the exact matrix image through Docker or Podman and invoke the family gate. |
| `tools/check_r*.py` | Milestone gates. |
| `tools/run_contract_tests.py` | Aggregate contract test runner. |
| `tools/check_docs.py` | Documentation existence/link gate. |
| `tools/check_idf_family_docs.py` | Validate the [IF7 family matrix evidence and claim contract](reference/IDF_FAMILY_MATRIX.md). |

## Tests

Contract tests live under `tests/contract/`. Firmware-unit host C smoke tests
live under `tests/firmware-unit/`. The first concrete hardware-in-loop app is
`tests/hardware-in-loop/hx45-s3-aitrip-n8r2/`; its retained HX5b result and the
XIAO C6 result are reconciled by HP0. HP2 adds
`test_hp2_host_build_coherence.py` and `hp2_host_identity_smoke.c`; HP3 adds
`test_hp3_application_slots.py` and `hp3_app_slots_smoke.c`. HP3.5 adds
`test_hp3_5_slot_adversarial.py` and
`tests/ota-power-loss/hp3_5_slot_adversarial_smoke.c`. The exhaustive host
interruption seal passes; the separately retained named-board safe subset also
passes on both exact boards. Source binds its immutable identities in
`evidence/hardware/hp3_5-index.json` without embedding the run directories.
HP4.0 adds `test_hp4_0_administration_contract.py` and the host-model
qualifier. It adds no firmware source, application ABI, transport driver, or
physical evidence. HP4.1 adds `test_hp4_1_administration_core.py` and
`hp4_1_admin_core_smoke.c`, implementing and qualifying the host-native core
without adding a UART driver, production crypto, update/recovery transaction,
application ABI, or physical evidence. HP4.2 adds
`test_hp4_2_admin_update.py` and `hp4_2_admin_update_smoke.c`, implementing the
exclusive inactive-slot transaction without adding target/physical evidence,
production crypto, host OTA, network transport, or application ABI. HP4.3 adds
`test_hp4_3_admin_recovery.py` and `hp4_3_admin_recovery_smoke.c`, implementing
host-only recovery without widening those deferred surfaces. HP4.4 adds
`test_hp4_4_admin_adversarial.py` and
`hp4_4_admin_adversarial_smoke.c`; it exhaustively seals stream/journal cuts,
negative administration/recovery interactions, fixed reserves, terminal/audit
behavior, and sequence exhaustion without target or physical execution.
HP5 adds `test_hp5_host_network.py` and `hp5_http_service_smoke.c`; it covers
fixed parsing, route/admin isolation, common-Wasm dispatch, paired responses,
external authenticated entry, HP4 terminal reuse, network loss, and exact
source history without claiming target or physical execution.
HP5.5 adds `test_hp5_5_network_hardware.py` and
`hp5_5_update_profile_smoke.c`; it covers target-contract replay, historical
HP2 immutability, matching/crossed update profiles, deterministic artifacts,
external secret staging, strict evidence acceptance, and negative aggregate
gates without manufacturing physical evidence. The hardware fixture is under
`tests/hardware-in-loop/hp5_5-network-admin/`.
