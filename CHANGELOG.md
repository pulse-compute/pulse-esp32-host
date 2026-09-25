# Prototype changelog

This repository began as a contract-first ESP32-S3/Wasm host spike. The `R0`–`R9` labels describe internal prototype milestones, not public releases or compatibility guarantees.

## HP5.5 — Network and administration physical audit implementation

- Added new S3/PSRAM and C6/no-PSRAM plans, locks, and running fingerprints
  without changing or relabelling any historical HP2 authority.
- Corrected update initialization narrowly so both exact matching physical
  profiles pass while crossed profile/fingerprint pairs fail closed; four
  native regression cases lock the behavior.
- Added a deterministic real-Wasm HTTP responder plus version 8 baseline,
  version 9 confirmed-trial, and version 10 stale-trial/fallback artifacts.
- Added external mode-0600 test Wi-Fi/TLS/administrator provisioning, exact HP5
  archive replay, pinned ESP-IDF named-board builders, full-backup/erase/restore
  operator contract, and secret-bearing staged-project boundary.
- Added a 29-checkpoint dual-TLS physical fixture and client covering listener
  separation, application faults/pressure/loss, protected administration,
  response loss, update/abort/trial/fallback, recovery, authorization backoff,
  forced bounded station reconnect, and target resource floors.
- Added strict per-board and distinct-UID dual-board evaluators with complete
  build/evidence re-hashing and six-value retained-evidence secret scans.
- Added a host readiness qualifier, contract/negative tests, Make entrypoints,
  and the attended physical runbook.
- Source readiness closes as `READY_FOR_PHYSICAL_EXECUTION`; physical execution
  remains honestly `HARDWARE_PENDING`, and HP6 remains blocked until both exact
  board reports are accepted as
  `DUAL_NAMED_BOARD_HP5_NETWORK_ADMIN_OBSERVED`.

## HP5 — Host network mediator

- Added the host-private `wdc_http` component with an allocation-free bounded
  parser/service, four exact application routes, and fixed protected
  administration routes.
- Added ESP-IDF station Wi-Fi and two independently bounded HTTPS server
  adapters: separate application/admin ports, control ports, tasks, parsers,
  and three-socket caps keep application pressure out of the admin reserve.
- Routed application requests through `WDC_EVENT_HTTP_REQUEST` and the common
  Wasm handler, with one first-response-wins `WDC_OP_HTTP_RESPOND` effect and
  explicit cancellation, timeout, trap, duplicate, and response-loss behavior.
- Realized HP4's authenticated external transport seam while reusing the
  existing authorizer, binary-frame normalizer, session, replay, deadline,
  rate, HP1 command, terminal, audit, update, recovery, journal, and reboot
  authorities.
- Preserved the sealed dependency boundary by keeping `wdc_net` independent of
  `wdc_admin`; only the host-private `wdc_http` orchestration component may
  join those surfaces.
- Added a 35-case native harness, exact source/authority model, manifested
  qualifier, historical successor replay, docs, and focused/full-suite gates;
  all 3,564 inherited HP4 native cases are rerun.
- Closed as `HOST_NETWORK_MEDIATOR_IMPLEMENTED` /
  `HOST_NATIVE_NETWORK_MEDIATOR_ONLY`. No target build, Wi-Fi/TLS physical
  observation, production authenticator/crypto, credential provisioning,
  MQTT, provider, RAX, host/factory OTA, or partition change is claimed. HP5.5
  remains the combined named-board physical audit barrier.

## HP4.4 — Administration adversarial seal

- Added one integrated host-native harness covering the complete HP4.1 core,
  HP4.2 update transaction, and HP4.3 recovery path with 3,523 exact cases in
  eleven categories.
- Exhausted all 2,362 safe prefixes of the 2,361-byte stored artifact and all
  1,030 erase, body, and marker interruption points across both HP3 journal
  records.
- Exercised unauthorized, expired, stale, replayed, duplicate, out-of-order,
  malformed, quiesce/unload, resource, rate, timeout, abort, verifier,
  security-floor, capacity, terminal/audit, reboot, and no-viable interactions.
- Found and fixed command-sequence exhaustion: `UINT64_MAX` is now rejected
  preaccept before ticket, replay, queue, mode, audit, terminal, or slot
  mutation; a later authenticated epoch can recover without wrap.
- Reran 14 HP4.1, 15 HP4.2, and 12 HP4.3 native cases for 3,564 aggregate
  passing cases with zero failures.
- Added an exact source/authority model, manifested qualifier, historical
  successor replay through HP1-HP4.3, contract gate, and closure documentation.
- Closed HP4 as `HOST_ADMINISTRATION_ADVERSARIAL_SEALED` /
  `HOST_NATIVE_ADMINISTRATION_ADVERSARIAL_ONLY`. HP4.4 adds no target or
  physical result, driver, network transport, production authenticator/crypto,
  host/factory OTA, partition redesign, application execution, provider, or
  RAX surface. HP5 is next; HP5.5 retains the combined physical gate.

## HP4.3 — Host-only recovery

- Added the allocation-free `wdc_admin_recovery` engine and linked it before
  application-thread creation without widening guest or native-extension ABIs.
- Bound automatic recovery to HP3 no-viable evidence with no selected/fallback
  slot, no application launch, active/last-good `NONE`, and no reboot request;
  malformed evidence fails initialization and no-viable state never loops.
- Added authorized `NORMAL -> QUIESCE -> RECOVERY` entry only after positive
  guest and native-refinement quiesce/unload evidence.
- Enabled the exact eight-command HP4.3 mask, a fixed 64-byte secret-free
  status response, and idle abort that retains recovery.
- Reused HP4.2 bounded candidate staging directly from recovery while retaining
  its 65,536-byte working buffer and exact HP1 admission; recovery-origin
  aborts, failures, denials, and timeouts return to recovery.
- Added a read-only HP3 candidate viability check that repeats complete stored
  artifact and HP2 prelaunch validation before `REBOOT_HANDOFF` and performs
  no metadata write or application launch.
- Added durable slot-transition audit emission bound to authenticated request
  identity while retaining bounded audit loss accounting and excluding proof
  bytes.
- Added eleven Python contracts, twelve native C cases, strict source and
  authority qualification, predecessor/successor replay, and documentation
  gates. The recovery engine is 3,112 bytes; the HP4.2 engine remains 3,096.
- Closed as `HOST_ONLY_RECOVERY_IMPLEMENTED` /
  `HOST_NATIVE_RECOVERY_TRANSACTION_ONLY`. HP4.3 adds no target or physical
  result, serial driver, network transport, production authenticator/crypto,
  host/factory OTA, partition redesign, provider, or RAX surface.

## HP4.2 — Exclusive update transaction

- Added the allocation-free `wdc_admin_update` engine for the exact C6-minimum
  path, linked before application-thread creation.
- Required positive guest and native-refinement quiesce/unload evidence before
  post-unload HP1 admission; fixed the gate at 163,840 internal free bytes and
  a 98,304-byte largest block for the 65,536-byte update working set.
- Enabled only the HP4.2 update command subset, binding every command to the
  inactive slot, expected artifact size, and complete-artifact SHA-256 while
  leaving HP4.3 recovery/reboot commands unsupported.
- Added sequential 1,024-byte chunks, 64-chunk/65,536-byte one-second limits, a
  30-second stream-idle deadline, and a 15-minute transaction deadline.
- Reused HP3 inactive-slot staging and complete stored-artifact verification,
  then required the HP4.1 replaceable verifier both before and immediately
  before activation.
- Committed `TRIAL` only through the HP3 journal and required durable read-back
  before `REBOOT_HANDOFF`; abort and every pre-commit failure preserve active,
  last-good, and exact confirmed authority.
- Added thirteen Python contracts, fifteen native C cases, an exact source and
  authority qualifier, historical successor replay, and documentation gates.
- Closed as `HOST_EXCLUSIVE_UPDATE_TRANSACTION_IMPLEMENTED` /
  `HOST_NATIVE_UPDATE_TRANSACTION_ONLY`. HP4.2 adds no target or physical result,
  serial driver, production authenticator/crypto, recovery transaction, host
  OTA, partition redesign, network listener, provider, or RAX surface.

## HP4.1 — Protected administration core

- Added the allocation-free `wdc_admin` component with the exact HP4.0
  authenticated-entry, request, terminal, and audit record layouts.
- Implemented one attended replaceable-authorizer session, strict epoch/nonce/
  consecutive-sequence replay, eight-failures-per-minute authorization
  backoff, and one accepted command owned through the HP1 administration lane.
- Made validation, HP1 submission, replay advancement, and accepted-command
  ownership atomic so preaccept rejection never consumes administration
  capacity or replay state.
- Added first-terminal-wins completion and one-time response consumption,
  including deterministic deadline terminalization while queued or in flight.
- Added an incremental fixed-storage serial normalizer for a four-byte
  little-endian length, exact 112-byte request, and at most 1,024 payload bytes;
  transport bytes cannot authorize themselves.
- Added a replaceable artifact-verifier seam that fails closed before HP4.2 and
  a 32-record overwrite audit ring with saturating loss count.
- Observed 7,712 bytes for the core plus 2,072 bytes for the serial adapter,
  totaling 9,784 bytes inside HP1's 12,288-byte administration reserve.
- Added twelve Python contracts, fourteen strict native C cases, exact source
  and authority sealing, firmware link validation, and inherited HP4.0
  successor reconciliation.
- Closed as `HOST_PROTECTED_ADMINISTRATION_CORE_IMPLEMENTED` /
  `HOST_NATIVE_CORE_ONLY`. HP4.1 adds no UART driver, production authenticator
  or crypto claim, update/recovery transaction, network listener, application
  route, target execution, or physical result.

## HP4.0 — Protected administration contract freeze

- Reconciled the accepted 440-file closure-sealed HP3.5 source successor while
  preserving the exact firmware, native-SDK, campaign, board-report, serial,
  dual-evaluation, and claim identities.
- Froze a transport-neutral 128-byte authenticated-entry record, 112-byte
  request, 64-byte terminal result, and 160-byte audit record with fixed
  zero-reserved layouts.
- Limited v1 to one fixed session and one accepted command, with atomic
  capacity/replay/ownership acceptance, strictly consecutive sequences, and
  exactly one retained terminal result.
- Froze exact request, stream, status, audit, rate, and monotonic-deadline
  bounds under the existing HP1 98,304-byte reserve.
- Defined the only legal transitions among `NORMAL`, `QUIESCE`, `UPDATE`,
  `RECOVERY`, and terminal `REBOOT_HANDOFF`, including positive guest/native
  quiescence and C6 exclusive-update admission before staging.
- Bound administration to HP1 sources/reserves, HP2 running-host compatibility,
  and HP3 inactive-slot, verification, journaled `TRIAL`, and boot authority
  without changing any of those meanings.
- Made `SERIAL_PHYSICAL_V1` the first concrete transport class while reserving
  a transport-neutral authenticated seam for HP5; transport bytes never become
  authorization authority.
- Added ten contract tests, five legal-path evaluations, 62 missing-guard
  denials, an exact host-model qualifier, ADR 0014, and aligned documentation.
- Closed as `HOST_ADMINISTRATION_CONTRACT_FROZEN` / `HOST_MODEL_ONLY`. HP4.0
  adds no firmware component, driver, authenticator, update transaction,
  recovery implementation, network listener, production-crypto claim, or
  physical result.

## HP3.5 — Application-slot adversarial and power-loss seal

- Added deterministic one-shot inactive-slot and two-record journal fault
  injection at erase, payload, metadata-body, and commit-marker boundaries.
- Exhaustively executed 11,657 host cases: every 2,361-byte artifact prefix,
  both journal records, eight state transitions, every record/body/marker
  prefix, reset during confirmation, journal corruption, semantic faults, and
  32 repeated guest-trap cycles.
- Resynchronized caller metadata to the durable journal winner after an
  interrupted commit, including the complete-marker/new-generation boundary.
- Made invalid-confirmed rejection and transfer to a validated confirmed
  alternate one atomic journal transition.
- Froze a thirteen-checkpoint inactive-only physical subset for the exact S3
  and C6 boards, then added the previously missing canonical-layout firmware
  runner, sealed named-board builders, per-board serial report producer, and
  fail-closed dual evaluator. Both physical named-board reports subsequently
  passed all thirteen checkpoints, and the dual evaluator closed as
  `DUAL_NAMED_BOARD_SAFE_SUBSET_OBSERVED`.
- Added a source-distributed HP3.5 closure index that binds the external board
  reports, serial logs, dual evaluation, campaign, exact input archive, and
  unchanged firmware-tree seal without embedding raw hardware evidence or
  private full-flash backups.
- Added no protected administration, transport, provider, RAX, Pulse-core, or
  host-firmware OTA behavior.
- Hardened CRC and flash-journal boundaries to copy complete object
  representations byte-for-byte. This preserves alignment bytes in the
  persisted OTA record and prevents a valid first metadata generation from
  being rejected when the second generation is committed on target.
- Added a structured `PULSE_HP35_STAGE_FAILURE` marker exposing each artifact
  validation gate and the number of completed metadata commits.
- Derived the physical runner's outer application identity, version, and
  security counter from the embedded verified-bundle manifest instead of a
  duplicated campaign identifier, keeping both artifact layers coherent.

## HP3 — Pulse application slots and fallback

- Added a fixed 192-byte Pulse application artifact header around the existing
  signed WDC bundle; the format binds application identity/version, security
  counter, HP2 requirements, stored hashes, and a header CRC without
  introducing RAX.
- Added encrypted A/B Pulse application partitions for both retained boards:
  two 896 KiB slots on C6 and two 2 MiB slots on S3, plus a 64 KiB metadata
  journal. Host firmware remains a fixed factory image outside this authority.
- Added inactive-only sequential staging, full stored-byte and inner-bundle
  verification, production artifact-authority injection, anti-rollback floor,
  and HP2 static compatibility before `STAGED` then `VERIFIED` commits.
- Evolved activation metadata with canonical `EMPTY`, `STAGED`, `VERIFIED`,
  `TRIAL`, `CONFIRMED`, and `REJECTED` states, two-record body-before-marker
  journaling, trial boot generation, reset attribution, and rejected-slot
  provenance.
- Added host-owned probation requiring readiness, health, administration
  responsiveness, preserved HP1 resource floors, and stable time. Application
  code cannot self-confirm; the last confirmed slot remains available until a
  replacement completes probation.
- Added a managed boot bridge that rereads and verifies flash, applies HP2
  fingerprint compatibility and HP1 live admission before runtime entry, and
  produces fallback-reboot or explicit recovery outcomes without guessing.
- Added ten contract tests, fourteen synthetic C cases, and a fresh-directory
  qualifier closing as `PULSE_APPLICATION_SLOT_AUTHORITY_PROVEN`. The evidence
  is host-only; HP3.5 owns exhaustive interruption and physical power-loss
  work. RAX, provider integration, transport, MQTT, Pulse-core changes, and
  host-firmware OTA remain deferred.

## HP2 — Host build coherence and running fingerprint

- Separated named-board identity, host capability/resource profile, normalized
  application target intent, host build plan, exact build lock, and running
  fingerprint into six independently validated artifacts.
- Added exact, replay-only locks for the retained AITRIP ESP32-S3 N8R2 and XIAO
  ESP32C6 4 MB realizations. Existing locks never resolve or silently upgrade;
  creating a new lock is an explicit, non-overwriting operation.
- Bound each realization to ESP-IDF `v5.4.4`, its source commit and container
  digest, exact managed-component hashes, board defaults, partition input,
  HP1 authority, ABI identity, and deterministic host source-tree hashes.
- Added fixed 196-byte build-derived running fingerprints with CRC-32, exact
  lock identity, semantic compatibility identity, board/profile identities,
  capability surface, and HP1 resource limits.
- Added a fail-closed C prelaunch gate that checks fingerprint integrity,
  target, ABI, capabilities, portable/optimized placement, and live HP1
  admission before application entry.
- Added ten contract tests, eight C prelaunch cases, eight Python negative
  cases, and a synthetic qualifier closing as
  `HOST_BUILD_COHERENCE_PROVEN`. No firmware build, flash, hardware execution,
  external provider, Pulse-core change, or host-firmware OTA is claimed.
- Preserved the common Wasm and public native-extension ABI identities. HP3
  subsequently adds application slots; protected administration, transport
  breadth, provider ergonomics, RAX, and host-firmware OTA remain deferred.

## HP1 — Host-kernel resource authority

- Added an allocation-free `wdc_control` component with an eight-record fixed
  ISR ring and direct ESP-IDF host-task notification adapter; ISR overflow
  rejects newest and latches recovery.
- Fixed five descending host-owned FreeRTOS priority classes for
  safety/recovery, administration, network maintenance, capability dispatch,
  and application work. Application records contain no priority selector.
- Partitioned static queue, ticket, and terminal-completion slots per class so
  application pressure cannot consume control-plane capacity; every rejection
  and accepted completion is explicit and bounded.
- Added a 98,304-byte C6 no-PSRAM internal control reserve spanning task
  stacks, queue/ticket state, metadata, administration, verification, and
  recovery, plus an exclusive 65,536-byte update working set.
- Added fail-closed admission across normal, quiesce-transition, and exclusive
  update peaks with separate largest-contiguous-block and arithmetic-overflow
  gates. Arbitrary priority, unbounded allocation, and C6 PSRAM dependence are
  denied before launch.
- Kept the S3 control reserve identical to C6 while allowing explicitly
  declared PSRAM only as `portable=false` target optimization.
- Added nine synthetic cases and 64 pressure rounds: 320 accepted tickets, 320
  terminal completions, and zero retained slots. The qualifier records
  `HOST_EXECUTED_SYNTHETIC_ONLY`; no new physical result is claimed.
- Preserved the public extension ABI, common Wasm, HX5b model, and HP0 evidence
  identities. HP2 subsequently closes build/profile/lock/fingerprint separation; MQTT,
  provider ergonomics, RAX, broad peripherals, and host-firmware OTA remain
  stopped.

## HP0 — Evidence reconciliation and next-boundary freeze

- Bound the exact v17 source snapshot, corrected next-phase handoff, supplied
  evidence archive, both named-board HX5b runs, and the final dual qualifier.
- Recorded passing `NAMED_BOARD_OBSERVED` results for the AITRIP S3 and XIAO C6
  and terminal `DUAL_ISA_PRESSURE_OBSERVED`/
  `DUAL_NAMED_BOARD_OBSERVED` results.
- Added a compact accepted hardware index plus a deterministic reconciler that
  verifies embedded path/hash/size records and every packaged file against the
  supplied evidence ZIP.
- Excluded the post-build nested C6 workspace copy from the accepted S3 root
  while preserving the exact input archive identity and packaging the primary
  C6 root independently.
- Superseded the old HX6/HX7, immediate MQTT, and immediate GPIO paths. HP1
  resource authority and HP2 build coherence are next; provider ergonomics,
  RAX, host-firmware OTA, and capability breadth remain stopped.
- Added no firmware behavior, public ABI, import, capability, peripheral,
  transport, slot, or update mechanism.

## HX5b — Extension pressure seal

- Added 64 sustained queue fill/drain rounds, 128 late/duplicate completion
  iterations, a bounded latency distribution, 64 reset-simulated native fault
  cycles, and 64 real Wasm trap/recovery cycles under fixed reservations.
- Re-execute the complete HX5a baseline and emit a source-bound HX5b report
  with zero tracked host retention and honest `HARDWARE_NOT_RUN` handling.
- Added opt-in S3 and C6 pressure builds which preserve the HX4.5 default,
  execute 128 target event/effect round trips, and record lifecycle timings.
- Added fail-closed physical evaluators and dual-report ingestion; one board
  cannot be reused or inferred as evidence for the other ISA.
- Use `PRIu32` for every HX5b pressure-marker value so both the Xtensa and
  RISC-V ESP-IDF toolchains remain correct when `uint32_t` is not `unsigned int`.
- Added no host capability, public ABI, import, peripheral, provider, RAX, OTA,
  HX6, or HX7 behavior.

## HX5a — Extension fault-model hardening

- Added a six-category machine-readable fault model spanning admission,
  reversible lifecycle failure, cooperative cleanup, uncertain native
  ownership, Wasm/native faults, and bounded pressure rejection.
- Added nine deterministic one-shot lifecycle return points under
  `PULSE_EXTENSION_HOST_TEST`; production objects and the public extension ABI
  expose none of the injection seam.
- Exercised partial side effects, reverse init/start unwind, reset-required
  health/invoke/quiesce/deinit faults, and partial reverse-unload failure.
- Distinguished invalid initialization state from actual budget exhaustion.
- Made uncertain ELF unload fail closed by preserving fault provenance and
  latching reset-required instead of returning a reusable loader failure.
- Added a unified report that re-executes 56 HX2-through-HX5a host cases and
  hashes each corpus while explicitly leaving hardware `NOT_RUN` for the pass.
- Deferred sustained pressure and targeted S3/C6 reruns to HX5b; added no host
  capability, public ABI, peripheral, provider, RAX, or OTA behavior.

## HX4.5 Seeed Studio XIAO ESP32C6 hardware gate

- Converted the first physical C6 failure into an executable-memory invariant:
  loader 1.3.2's unified-segment allocator discarded executable intent and the
  default PMP split left its relocated heap entry RW/NX.
- Disabled the fixed PMP IRAM/DRAM split for C6 extension profiles and wrapped
  loader allocation so executable requests require internal executable RAM,
  failing during relocation if that policy cannot be satisfied.
- Added a host allocator smoke and generated-sdkconfig rejection test for the
  C6 executable-segment policy; the sealed native ELF bytes remain unchanged.
- Added an isolated named-board lane for the XIAO ESP32C6's exact 4 MB
  flash/no-PSRAM configuration without changing the canonical compile-only C6
  realization or the passing AITRIP S3 path.
- Embedded the accepted 8,008-byte RISC-V extension ELF with SHA-256
  `60185086c35486f3b57c8ea1ef9f975499996f207050af37754a3c1c6ff02fb2`
  and the unchanged common HX4 Wasm.
- Added a 160 KiB static-link internal-RAM floor for the guest's 128 KiB linear
  memory plus a 32 KiB fail-fast guard; runtime heap/largest-block and stack
  observations remain authoritative.
- Added the integrated USB Serial/JTAG console configuration, exact 4 MB flash
  and no-PSRAM preflight, five measured clean cycles, WAMR trap, reset-required
  latch, retained breadcrumb, and fail-closed serial evaluator.
- Added deterministic source/evidence packaging boundaries, contract tests,
  Make targets, and the shortest physical runbook.
- Kept the lane at `HARDWARE_NOT_RUN`; the sandbox prepared and contract-tested
  the gate but did not compile it under ESP-IDF or observe the physical board.

## HX4.5 AITRIP hardware candidate — PSRAM ELF execution

- Preserved the exact HX4.5-sealed ESP32-S3 ELF after physical inspection and
  descriptor admission succeeded on the named AITRIP N8R2 board.
- Moved only the isolated named-board lane to the pinned loader's supported
  ESP32-S3 PSRAM execution mode after the one-byte dedicated-IRAM remainder
  made a 2,348-byte executable allocation impossible.
- Added instruction-cache alias conversion for Pulse's directly resolved ELF
  entry symbol and executable descriptor range; the upstream loader already
  applies the same conversion to relocated lifecycle pointers.
- Normalized the loader-bounded fixed descriptor into aligned host-owned
  storage after physical execution exposed the loader's unaligned packing of
  `.data.rel.ro` behind the sealed ELF's 34-byte `.rodata`.
- Split the PSRAM loader allocation policy at its existing executable flag:
  ELF text remains in PSRAM, while writable ELF state uses internal
  byte-accessible RAM so extension-owned static FreeRTOS TCB, stack, and queue
  storage pass the target port's memory invariants.
- Modeled the loader's unpadded writable-section order and solved a bounded
  allocation-base residue from the ELF section alignments after the first
  internal-RAM run exposed a misaligned queue spinlock. The sealed ELF requires
  residue 14 modulo 16; its bytes and direct imports remain unchanged.
- Wrapped loader free alongside allocation so a residue-shifted writable image
  releases the original heap pointer and exact clean-unload recovery remains
  measurable.
- Preserved PSRAM native text but moved non-executable WAMR mmap allocations
  to internal byte-accessible RAM after physical execution passed native event
  delivery and then faulted while zeroing a 128 KiB PSRAM linear-memory map.
- Matched WAMR's hidden original-pointer prefix so its unchanged munmap/free
  path releases the internal mapping correctly; executable mmap requests stay
  under the pinned port's policy.
- Replaced the invalid cast of flash-resident immutable Wasm bytes with a
  runtime-owned internal writable copy, matching WAMR's documented permission
  to modify the input and its requirement that the buffer survive until
  module unload.
- Added a module-buffer ownership smoke proving exact copy, source immutability,
  internal capability selection, and unload-before-release integration.
- Kept external FreeRTOS task stacks disabled and added a host allocator smoke
  covering capability selection, packed layout, aligned runtime addresses, and
  paired release.
- Kept canonical cross-family proof realizations unchanged and retained
  `HARDWARE_NOT_RUN` until a complete passing report is evaluated.

## HX4.5 — Event/effect adversarial seal

- Executed all 11 deferred identity, overflow, oversize, deadline,
  stale/duplicate completion, quiescence, Wasm-trap, and extension-fault cases.
- Distinguished active-not-ready, timed-out, and lifecycle-canceled completion
  states so quiescence terminates an effect immediately and explicitly.
- Closed the host-timeout slot leak and classified an invoke-time deadline race
  as timeout rather than bad encoding.
- Proved that the exact common HX4 Wasm propagates host rejection codes and
  that a real trapping event handler raises a WebAssembly runtime trap.
- Preserved the common Wasm bytes and kept target runtime at
  `HARDWARE_NOT_RUN`; the next action is the named S3 board qualification.

## HX4 — Provisional native event/effect happy path

- Connected candidate-attributed extension event emission to the existing
  bounded `wdc_events` queue and `wdc_runtime` handler path.
- Added one target-neutral effect opcode to the existing dispatcher and
  resolved it only through the sealed extension registry.
- Added host-owned correlation, absolute deadline, and one bounded exactly-once
  completion slot with explicit duplicate behavior.
- Extended the synthetic extension task to emit `test:tick`, copy `test:echo`
  requests into its static queue, and complete them from the task.
- Added one 306-byte common Wasm artifact, a native end-to-end host smoke, and a
  real WebAssembly execution smoke.
- Preserved `BUILD_ONLY_PROVEN`/`HARDWARE_NOT_RUN`; deferred the adversarial seal
  to HX4.5 and hardware testing until after that seal.

## HX3 — Native extension lifecycle and task ownership

- Added the host-owned `init` through `deinit` state machine with strict
  duplicate and out-of-order rejection.
- Added reverse unwind for partial initialization and failed starts.
- Added one extension-owned statically provisioned task and one bounded static
  queue, with exact S3/C6 import and writable-memory inventories.
- Added caller-bounded monotonic-time and health services while keeping HX4
  event/effect services closed.
- Added kernel-confirmed task deletion, host-owned quiescence deadlines, and a
  reset-required latch for unhealthy or uncertain post-start teardown.
- Added 12 host lifecycle cases, 32 repeated cycles, and byte-reproducible
  native ELF and firmware builds for both proof targets.
- Kept target runtime classification at `HARDWARE_NOT_RUN`.

## HX2 — Two-stage native extension admission

- Added the sole experimental public C ABI authority and exact metadata,
  descriptor, lifecycle, and host-service layouts.
- Added bounded raw ELF/metadata inspection before relocation and descriptor
  validation before lifecycle execution.
- Added an inspector-derived exact resolver table with no ambient symbols.
- Added fixed-capacity catalog sealing and duplicate identity rejection.
- Added byte-reproducible ESP32-S3 and ESP32-C6 synthetic ELFs.
- Added 21 fail-closed ELF, metadata, descriptor, and registry vectors with zero
  lifecycle calls on rejection.
- Kept runtime classification at `HARDWARE_NOT_RUN`.

## HX1 — Exact dual-ISA ELF loader build proof

- Pinned Espressif `elf_loader` 1.3.2 and its transitive component graph.
- Added the opaque loader adapter and independent relocation/constructor
  inspector.
- Produced byte-reproducible extension-enabled firmware builds for ESP32-S3
  and ESP32-C6 without promoting them to runtime evidence.

## R9 — Production security profile

- Added development and production security policies.
- Added secure-boot, flash-encryption, provisioning, and OTA preflight contracts.
- Added trusted key-ID and anti-rollback-floor policy.
- Added a fail-closed verifier callback boundary for deployment-grade signatures.
- Added reset and fault breadcrumbs.

## R8.2 — Runtime-limit hardening

- Applied manifest request, response, event, payload, and rate limits at runtime.
- Cleared active authorization and limits during teardown.
- Added event-size and host-call limit enforcement.

## R8.1 — Audit hardening

- Disabled effectful boot self-tests by default.
- Made missing host-call authorization fail closed.
- Added a two-record metadata journal.
- Replaced export-name string matching with Wasm export-section parsing.
- Tightened network-policy enforcement.

## R8 — Active-slot runtime and network mediation

- Booted the verified payload from the selected active slot.
- Installed manifest capabilities and runtime limits before guest execution.
- Added native-mediated MQTT and HTTP intent contracts.

## R7 — A/B activation and rollback

- Added pending, probation, confirmed, failed, and last-good states.
- Added rollback simulation and generation tracking.
- Added candidate boot and fault counters.

## R6 — Bundle packaging and verification

- Added the `WDCBNDL\0` container format.
- Added manifest and payload hashes.
- Added development signing and production rejection of development signatures.
- Added ABI, target, capability, profile, and metadata checks.

## R5 — Safety-enforced hardware MVP

- Added explicit safety states.
- Applied safe GPIO defaults at boot, no-bundle, and fault-stop boundaries.
- Added a HAL-backed relay path.
- Denied physical writes when the guest is not in the running state.

## R4 — Events, profiles, and capabilities

- Added event envelopes and bounded queues.
- Added capability parsing, authorization, resource lookup, and audit records.

## R3.5 — Dependency and verification boundary

- Added bounded dependency inventory and bootstrap helpers.
- Added machine-readable `PASS`, `FAIL`, `SKIPPED_ENV`, and `SKIPPED_NO_HARDWARE` reports.
- Added a Wasm inspector.

## R3 — ABI dispatcher and guest SDK

- Added deterministic CBOR request and response payloads.
- Added guest-memory validation and host-call limits.
- Added system, timer, config, and GPIO opcodes.
- Added Rust and C guest wrappers.

## R2 — Runtime vertical slice

- Added the WAMR runtime integration boundary.
- Added static Wasm fixtures and guest lifecycle lookup/calls.
- Added a host-test backend for local contract verification.

## R1 — Native shell skeleton

- Added boot sequencing and diagnostics.
- Added static profile and safe GPIO initialization.
- Added NVS/partition reporting and no-bundle mode.

## R0 — Contract and repository foundation

- Established the native-supervisor/Wasm-guest split.
- Defined initial ABI names, versioning, status ranges, and opcode groups.
- Added profile and manifest schemas and example inputs.
- Drafted Wasm A/B partitions and metadata storage.
