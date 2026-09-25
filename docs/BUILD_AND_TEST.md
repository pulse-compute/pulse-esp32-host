# Build and test

The repository separates fast host-side contract checks from toolchain and hardware qualification.

## Host-side checks

```bash
make validate
make test
make check-hp1
make check-hp2
make check-hp3
make check-hp3-5
make check-hp4-0
make check-hp5
make check-hp5-5
make check-r9
make docs-check
make check-full
```

Run raw test discovery when changing test infrastructure:

```bash
python3 -B -m unittest discover -s tests -v
```

Generated reports are written to `reports/` and are ignored by Git.
They are not included in source snapshots; see
[Packaging and evidence](PACKAGING_AND_EVIDENCE.md) for the deterministic
source, host-evidence, and hardware-evidence package boundaries.

## Milestone gates

The historical `R0`–`R9` gates remain useful as narrow regression checks:

```bash
make check-r0
make check-r1
make check-r2
make check-r3
make check-r3-5
make check-r4
make check-r5
make check-r6
make check-r7
make check-r8
make check-r8-1
make check-r8-2
make check-r9
```

The HP namespace adds explicit host-platform gates:

```bash
make check-hp0
make check-hp1
HP1_OUT_DIR=reports/host-kernel/hp1-<fresh-id> \
  make host-kernel-qualify
make check-hp2
HP2_OUT_DIR=reports/host-build/hp2-<fresh-id> \
  make host-build-qualify
make check-hp3
HP3_OUT_DIR=reports/app-slots/hp3-<fresh-id> \
  make app-slots-qualify
make check-hp3-5
HP3_5_OUT_DIR=reports/app-slots/hp3_5-<fresh-id> \
  make app-slots-adversarial-qualify
make check-hp4-0
HP4_0_OUT_DIR=reports/administration/hp4_0-<fresh-id> \
  make administration-contract-qualify
make check-hp4-1
HP4_1_OUT_DIR=reports/administration/hp4_1-<fresh-id> \
  make administration-core-qualify
make check-hp4-2
make check-hp4-3
make check-hp4-4
make check-hp5
HP5_OUT_DIR=reports/network/hp5-<fresh-id> \
  make host-network-qualify
make check-hp5-5
HP5_5_OUT_DIR=reports/network/hp5_5-<fresh-id> \
HP5_SOURCE_ARCHIVE=/sealed/pulse-esp32-host-hp5-source-v1.zip \
  make hp5_5-readiness-qualify
```

HP1 is a host-executed synthetic qualification. It validates fixed ISR,
priority, queue, completion, reserve, and admission behavior without claiming
that the current firmware has been flashed or observed on either named board.

HP2 is also host-synthetic. It validates the six-artifact separation, exact
non-upgrading lock replay, build-derived fingerprints, and fail-closed
prelaunch checks. It does not invoke ESP-IDF, flash a board, or implement the
external ESP32 provider.

HP3 is host-synthetic. It validates both dual-slot layouts and exact lock
bindings, then compiles and executes fourteen staging, verification, trial,
probation, reset-attribution, fallback, corruption, compatibility, and recovery
cases. It does not build firmware, execute a target, deploy production signing,
or manufacture the separately retained HP3.5 physical result.

HP3.5 exhaustively executes 11,657 deterministic host interruption and fault
cases across every payload prefix, both metadata records, eight transitions,
every record/body/marker prefix, and reset during confirmation. It closes as
`HOST_SLOT_ADVERSARIAL_POWER_LOSS_SEALED`. The separately retained two-board
thirteen-checkpoint safe physical campaign has also passed the exact named S3
and C6 lanes; the dual evaluator reports
`DUAL_NAMED_BOARD_SAFE_SUBSET_OBSERVED`. Source binds the accepted hashes in
the [HP3.5 evidence index](../evidence/hardware/HP3_5_INDEX.md). The physical
builders and report producer remain exposed for fresh reproduction runs:

```bash
HP3_5_S3_RUN_DIR=/fresh/s3-run make hp3_5-s3-aitrip-build
HP3_5_C6_RUN_DIR=/fresh/c6-run make hp3_5-c6-xiao-build
HP3_5_S3_RUN_DIR=/completed/s3-run make hp3_5-s3-aitrip-evaluate
HP3_5_C6_RUN_DIR=/completed/c6-run make hp3_5-c6-xiao-evaluate
```

Those build/evaluate commands do not replace the mandatory raw backup,
fresh-chip erase, flash/monitor, and restore procedure. Follow the
[HP3.5 physical campaign runbook](../tests/hardware-in-loop/hp3_5-slot-power-loss/README.md)
before using them.

HP5 is host-native. It compiles the fixed HTTP service and actual common
runtime/HP4 integration, executes 35 new cases, and reruns all 3,564 inherited
HP4 native cases. The qualifier verifies the ESP-IDF adapter source but does
not invoke the target toolchain or create Wi-Fi, TLS, or physical evidence.
Use the [HP5.5 boundary](HP5_HOST_NETWORK_MEDIATOR.md#hp55-gate-and-later-roadmap)
before treating the adapter as physically realized.

HP5.5 implements the exact target contracts, secret-external staging,
deterministic real-Wasm/update fixtures, pinned named-board builders, physical
TLS client, and strict per-board/dual evaluators. Its host gate proves only
`READY_FOR_PHYSICAL_EXECUTION` and deliberately reports `HARDWARE_PENDING`.
The two complete attended procedures and promotion command are documented in
the [HP5.5 physical runbook](HP5_5_NETWORK_ADMIN_PHYSICAL_SEAL.md). Do not use
synthetic evaluator tests or one lane as physical evidence.

HP4.0 validates the frozen host-private administration model. It checks four
exact fixed record layouts, twelve legal transitions, five complete legal
scenarios, 62 individual missing-guard denials, the HP1/HP2/HP3 authority
hashes, the authorized closure-sealed source reconciliation, and the unchanged
historical HP3.5 firmware/native-SDK seals. It closes as
`HOST_ADMINISTRATION_CONTRACT_FROZEN` with `HOST_MODEL_ONLY`; it does not
compile firmware, implement a serial driver or authenticator, write a slot, or
create physical evidence.

HP4.1 compiles and executes the fixed `wdc_admin` component with strict C11
warnings. Fourteen native cases prove the fixed record/storage budget,
attended authorizer boundary, authorization backoff, replay/capacity
immutability, application-pressure isolation, terminal ownership, fragmented
serial normalization, frame rejection, deadline handling, epoch high-water,
audit loss accounting, and fail-closed verifier seam. The result is
`HOST_PROTECTED_ADMINISTRATION_CORE_IMPLEMENTED` / `HOST_NATIVE_CORE_ONLY`;
it does not invoke ESP-IDF, attach a serial driver, enable update/recovery,
execute an application, or create physical/cryptographic evidence.

## Result classes

The report tools distinguish:

```text
PASS                 executed and satisfied
FAIL                 executed and failed
SKIPPED_ENV          required toolchain or environment unavailable
SKIPPED_NO_HARDWARE  required board or rig unavailable
```

A bounded skip is useful during development, but it is not production evidence.

## Rust guest build

```bash
rustup target add wasm32-unknown-unknown
make build-guest
```

Validate generated imports and exports with the included Wasm tools.

## ESP-IDF family lane and component locks

The canonical identities, results, hashes, evidence paths, and claim boundary
are maintained in the [ESP-IDF family build matrix](reference/IDF_FAMILY_MATRIX.md).

```bash
python3 -B tools/check_idf_matrix.py --check-locks
python3 -B tools/check_deps.py --realization esp32s3-reference
```

The canonical lane is `v5.4.4` at commit
`296b6eab9445fd720e71aecab961e2d3fbca9944`. `tools/bootstrap_idf.sh`
reads that identity and the attempted target union from
`firmware/idf-family-matrix.json`; it rejects moving or mismatched ambient IDF
installations.

Regenerate a target lock only in the pinned lane, preferably in the
matrix-declared container image:

```bash
python3 -B tools/build_idf_cell.py --cell esp32s3-reference --update-lock
python3 -B tools/build_idf_cell.py --cell esp32-compile --update-lock
python3 -B tools/build_idf_cell.py --cell esp32c3-compile --update-lock
python3 -B tools/build_idf_cell.py --cell esp32c6-compile --update-lock
```

Each command copies `firmware/` to an owned temporary directory, stages only
the selected lock, configures with the matrix target/defaults/partition, and
validates the generated target, IDF, WAMR source, version, manifest hash, and
component hash. The repository lock can change only with `--update-lock`.
Without that flag, any solver change is a hard failure.

### Isolated cell build

Run one complete IF3 build from a verified `v5.4.4` environment:

```bash
python3 -B tools/build_idf_cell.py \
  --matrix firmware/idf-family-matrix.json \
  --cell esp32s3-reference \
  --out-dir reports/idf-family/esp32s3-reference-run-1 \
  --timeout 1800
```

`make build-firmware` invokes the same builder. Select a different attempted
cell with `WDC_IDF_CELL`, a new evidence directory with `WDC_IDF_OUT_DIR`, and
an optional total deadline with `WDC_IDF_TIMEOUT_SECONDS`. The evidence
directory must be absent or empty; the builder never replaces prior evidence.

The builder verifies the exact lane before doing work, copies only source
inputs into an owned temporary project, stages the matrix-selected lock, passes
the target and defaults explicitly, and keeps the build and generated
`sdkconfig` outside the checkout. It fails if the staged lock or source tree
changes, the deadline expires, size output is invalid, or any required artifact
is missing. A completed directory contains:

```text
artifacts/wdc_esp32_host.elf
artifacts/wdc_esp32_host.bin
artifacts/bootloader/bootloader.bin
artifacts/partition_table/partition-table.bin
sdkconfig
size.json
build.log
cell-report.json
```

`cell-report.json` hashes all file inputs and evidence outputs and classifies a
successful single build as `COMPILE_PROVEN`. Compiler caching is forced off so
a cell cannot inherit a warm host or container cache.

### ESP32-S3 reference qualification

Run the IF4 gate inside the matrix-declared image. This Docker command is the
canonical direct invocation; Podman may be substituted with the same image,
platform, environment, mount, and command:

```bash
IMAGE='espressif/idf@sha256:8d1846f61ff8db00ba6530501f90bf43604d923072a616c806fef8e85a88ed82'
docker run --rm --platform linux/amd64 \
  -e PULSE_IDF_CONTAINER_IMAGE="$IMAGE" \
  -e PULSE_IDF_EXECUTION_ADAPTER=docker \
  -v "$PWD:/work" -w /work "$IMAGE" \
  make idf-reference-qualify
```

The output directory must be absent or empty. Override it only with a fresh
path, for example `-e WDC_IDF_OUT_DIR=reports/idf-family/if4-rerun`. The gate
validates the matrix and observed image digest before building, invokes the S3
cell twice from independent temporary project paths, and requires:

- both cell reports to be `PASS`/`COMPILE_PROVEN`;
- identical declared source/default/partition/lock inputs;
- a resolved lock that is identical between runs and matches the committed lock;
- byte-identical generated `sdkconfig` files; and
- non-empty, byte-identical ELF, application, bootloader, and partition-table binaries.

It writes `qualification-report.json`, `qualification-report.md`, and two full
run evidence directories. Any absent/mismatched digest identity, build failure,
timeout, dirty evidence directory, changed lock/configuration, missing artifact,
or byte difference exits non-zero and never emits `BUILD_QUALIFIED`.

The IF4 observation for this snapshot passed as `BUILD_QUALIFIED` in ESP-IDF
`v5.4.4` at `296b6eab9445fd720e71aecab961e2d3fbca9944`. Both runs produced:

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `wdc_esp32_host.elf` | 7,717,256 | `1d358f7ba797c051f589befa28015455acc9d1350cdb039c50d89c1ed2d88bb8` |
| `wdc_esp32_host.bin` | 489,888 | `edbcb48dfd930dce33ca60f7b83bc54fdfe952335c70b739045b9e94cf6a86e6` |
| `bootloader/bootloader.bin` | 20,880 | `75c187d6e8957f6b43d3e93e488994dd2623e3bc5f1dd065a24ecde6e7ace95e` |
| `partition_table/partition-table.bin` | 3,072 | `157aab03a27cb7c88c3c44857cffd5bdf37d7cd656d51e6f81754ccd82116fdf` |

The generated `sdkconfig` SHA-256 was
`5fc023160329a1b4201ecbb3c356e36cdd350d9ac24d59bcdbd080511ebdf026`;
the committed and resolved S3 lock SHA-256 was
`b8826d9316e85096bca38cabbcb70a8faf431cd5a392bbce322849bd2470feed`.
### IF5 exploratory family probes

IF5 invokes the existing cell builder once per exploratory realization, in
this exact order, from inside the same digest-pinned image:

```bash
python3 -B tools/build_idf_cell.py \
  --cell esp32c3-compile \
  --out-dir reports/idf-family/if5-esp32c3-compile
python3 -B tools/build_idf_cell.py \
  --cell esp32-compile \
  --out-dir reports/idf-family/if5-esp32-compile
python3 -B tools/build_idf_cell.py \
  --cell esp32c6-compile \
  --out-dir reports/idf-family/if5-esp32c6-compile
```

Use fresh output paths on every execution. An `INCOMPATIBLE` cell exits
non-zero but is a valid mapping result only when its deterministic boundary is
present in `cell-report.json` and `build.log`. Infrastructure or unclassified
failures never satisfy the IF5 gate.

The IF5 snapshot observation used firmware source-tree SHA-256
`2e0935fbc0f8fc2013bb09c4f8a5453bc8718a91b3e0b5c3201b997e616c6a9e`:

| Cell | Result | Exact observed boundary |
|---|---|---|
| `esp32c3-compile` | `INCOMPATIBLE` | Final link: `dram0_0_seg` overflowed by 17,664 bytes. |
| `esp32-compile` | `INCOMPATIBLE` | Final link: `dram0_0_seg` overflowed by 115,120 bytes. |
| `esp32c6-compile` | `COMPILE_PROVEN` | ELF, application, bootloader, partition table, sdkconfig, size, log, and report emitted. |

S3 was requalified after the overlay repair against that same source-tree
hash and remained `BUILD_QUALIFIED` with identical IF4 artifact hashes.

The C3 and C6 overlays omit unsupported SPIRAM symbols rather than feeding
unknown assignments to Kconfig. Classic ESP32 explicitly disables its
supported SPIRAM symbols. The two incompatibilities belong to those declared
no-PSRAM realizations; they are not blanket chip-support claims. IF5 did not
reduce WAMR heaps, alter ownership/lifecycle behavior, invent a task/core
policy, or add another IDF lane to force a green build.

The C6 application ELF is 7,869,808 bytes with SHA-256
`947db7d9958b09b1c2b7f694b44345fe004ad4fb4d6c3274f121974bf0821bb6`;
its application binary is 485,328 bytes with SHA-256
`5a36432f8fbeab35cb939f77626bb1a8280bd3d4b28ece3a9f412809a51c2286`.
IF6 adds orchestration around these cell semantics without reinterpreting
deterministic incompatibility as a skipped or passing build.

No compile result is hardware, runtime, memory, GPIO, FreeRTOS, networking, or
provider qualification. Flashing, attached-board tests, electrical checks, and
hardware-in-loop rollback remain explicitly deferred.

### IF6 family qualification

From a host with Docker or Podman installed, run the canonical sealed command
with a fresh repository-relative evidence path:

```bash
WDC_IDF_MATRIX_OUT_DIR=reports/idf-family/if6-local \
  tools/run_pinned_idf_matrix.sh
```

The launcher validates the complete matrix and all four dependency locks before
selecting a runtime. It reads the exact image digest from the validated matrix,
requires `linux/amd64`, records the runtime as execution provenance, mounts the
checkout once, and invokes `make idf-family-qualify` inside the image. If no
Docker or Podman runtime is installed, it exits non-zero before qualification;
install one or move the command to a qualified runner instead of substituting
an ambient IDF or mutable image tag.

Inside an already-entered exact image, the equivalent canonical target is:

```bash
PULSE_IDF_CONTAINER_IMAGE='espressif/idf@sha256:8d1846f61ff8db00ba6530501f90bf43604d923072a616c806fef8e85a88ed82' \
PULSE_IDF_EXECUTION_ADAPTER=docker \
WDC_IDF_MATRIX_OUT_DIR=reports/idf-family/if6-local \
make idf-family-qualify
```

The orchestrator always runs the two-build S3 reference gate and, in family
mode, attempts C3, ESP32, and C6 in that exact order even after an exploratory
failure. It never attempts deferred or excluded inventory. The aggregate exits
non-zero for an invalid matrix/image, failed S3 qualification, missing or
out-of-order attempt, infrastructure or unclassified result, incomplete or
mismatched evidence, source-tree drift, or non-reproducible S3 output.
Exploratory `INCOMPATIBLE` is accepted only when the normalized failure and
hashed build log preserve a recognized deterministic compiler/linker boundary.

The local `.github/workflows/idf-family-matrix.yml` definition runs the same
launcher on `ubuntu-24.04`, has read-only contents permission, pins checkout and
artifact upload actions to full commits, uses no build cache or
`continue-on-error`, and uploads the complete evidence tree with `if: always()`.
This snapshot defines the workflow locally only; no GitHub remote was modified.

The final IF6 observation passed with source-tree SHA-256
`2e0935fbc0f8fc2013bb09c4f8a5453bc8718a91b3e0b5c3201b997e616c6a9e`:

| Cell | Aggregate-accepted result | Evidence rule |
|---|---|---|
| `esp32s3-reference` | `BUILD_QUALIFIED` | Two complete, byte-reproducible clean builds. |
| `esp32c3-compile` | `INCOMPATIBLE` | Exact final-link internal-DRAM overflow by 17,664 bytes. |
| `esp32-compile` | `INCOMPATIBLE` | Exact final-link internal-DRAM overflow by 115,120 bytes. |
| `esp32c6-compile` | `COMPILE_PROVEN` | All required artifacts and matching hashes present. |

The aggregate contains no failed gates. It explicitly marks P4/C5 deferred and
S2/C2/H2/C61 excluded by policy; it does not manufacture build observations for
them. Board flashing, WAMR runtime behavior, electrical safety, watchdog/reset,
power-loss, native OTA/rollback, production security, networking, provider
integration, and FreeRTOS task/core ownership remain separate hardware and host
architecture work.

### IF7 documentation seal

```bash
make idf-family-seal-check
```

This combines the matrix/lock validator with the IF7 documentation contract.
It recomputes each realization's declared configuration, partition, and lock
hash; requires the complete inventory and exact lane; rejects broadened status
language; and requires every listed repository entry document to link the
[canonical matrix evidence](reference/IDF_FAMILY_MATRIX.md). With preserved
evidence available, `tools/check_idf_family_docs.py --evidence-root <dir>
--evidence-archive <zip>` additionally verifies the aggregate, cell reports,
logs, and archive against the seal record.

## HX4 native-extension event/effect qualification

Run the cumulative contract gates first:

```bash
make check-hx0 check-hx1 check-hx2 check-hx3 check-hx4
```

Then activate the exact ESP-IDF v5.4.4 lane and use a fresh evidence path:

```bash
HX_OUT_DIR=reports/host-extension/hx4-<fresh-id> \
  make host-extension-runtime-qualify
```

The target performs five distinct checks:

1. compile and execute the inherited native host lifecycle smoke;
2. compile and execute the complete HX4 host event/effect round trip;
3. execute the exact common Wasm bytes in a real WebAssembly engine and require
   one target-neutral effect call;
4. build each synthetic S3/C6 ELF twice, require byte identity, independently
   copy and compare the common Wasm bytes, and inspect the ELF's
   exact imports, relocations, constructor surface, metadata, and writable
   backing; and
5. build the extension-enabled firmware twice from isolated project copies for
   each target and compare application, bootloader, partition, sdkconfig, lock,
   and normalized size evidence.

The output directory must be absent or empty. If an offline component mirror is
used, set `HX_COMPONENT_MIRROR` to a directory containing the exact three
locked managed components. The accepted report is documented in
[HX4 event/effect round trip](HX4_EXTENSION_EVENT_EFFECT.md).

The phase is `PROVISIONAL_HAPPY_PATH` and aggregate result cannot exceed
`BUILD_ONLY_PROVEN`. No board is attached by this command, so WAMR-on-target,
task scheduling, target queue/latency/stack/heap measurements, loader unload,
reset reason, retained diagnostics, and hardware runtime remain
`HARDWARE_NOT_RUN`. HX4.5 must seal the adversarial cases before the planned S3
hard stop.

## HX4.5 native-extension adversarial qualification

Run the cumulative host gates:

```bash
make check-hx0 check-hx1 check-hx2 check-hx3 check-hx4 check-hx4-5
```

Then activate the exact ESP-IDF v5.4.4 lane and use a fresh evidence path:

```bash
HX_OUT_DIR=reports/host-extension/hx45-<fresh-id> \
  make host-extension-adversarial-qualify
```

This reruns the HX4 happy path and dual-ISA realization checks, then requires
all 11 identity, overflow, oversize, deadline, completion ownership,
quiescence, Wasm-trap, and extension-fault cases. The exact common Wasm must
propagate host failures unchanged and remain byte-identical across targets.
The firmware report is accepted only when its firmware and native-SDK source
digests match the current HX4.5 tree.

The phase is `ADVERSARIAL_HOST_SEALED`; the aggregate remains
`BUILD_ONLY_PROVEN`, and target runtime remains `HARDWARE_NOT_RUN`. See the
[HX4.5 adversarial seal](HX4_5_EXTENSION_ADVERSARIAL.md). The next action is the
named S3 board qualification, not HX5.

## HX4.5 AITRIP ESP32-S3 N8R2 hardware qualification

The isolated first-board lane uses an AITRIP ESP32-S3-DevKitC-1 with an
`ESP32-S3-WROOM-1-N8R2` module. On an exact activated ESP-IDF v5.4.4 Linux
x86-64 lane, create a fresh run directory with:

```bash
HX_AITRIP_OUT_DIR=reports/hardware/hx45-aitrip-n8r2-001 \
  make hx45-s3-aitrip-build
```

Flash and retain the complete monitor transcript across the harness software
reset, then evaluate it with:

```bash
HX_AITRIP_OUT_DIR=reports/hardware/hx45-aitrip-n8r2-001 \
  make hx45-s3-aitrip-evaluate
```

The build refuses a different sealed ELF, common Wasm, IDF commit, target,
dependency lock, flash size, or PSRAM size. The evaluator re-hashes the build
artifacts and requires both boots, one warmup and five measured clean cycles,
exact heap recovery, bounded stack and queue observations, a real WAMR trap,
main-task stack headroom, free/largest-block internal and PSRAM floors, and the
reset-required path. See the
[complete physical runbook](HX4_5_S3_AITRIP_HARDWARE.md).

Because the statically linked S3 image has no useful dynamic executable-IRAM
pool, this isolated lane uses the pinned loader's supported S3 PSRAM execution
mode and validates Pulse's instruction-alias mapping for directly resolved ELF
entry symbols. The lane also wraps the loader allocator so executable text
remains in PSRAM while writable ELF state remains in internal byte-accessible
RAM. It models the loader's unpadded writable-section order and selects a
bounded allocation-base residue that satisfies every section alignment; the
sealed ELF requires residue 14 modulo 16. This keeps the extension-owned
static FreeRTOS task, stack, and queue control blocks internally resident and
properly aligned. External task stacks are not enabled. The canonical
extension-proof realizations remain unchanged.

The same lane keeps WAMR's writable linear-memory mmap in internal
byte-accessible RAM after physical execution exposed a cache writeback fault
when the pinned port placed that 128 KiB mapping adjacent to PSRAM-resident
native text. Executable WAMR mappings retain the pinned port policy, and all
active/teardown heap floors remain measured rather than inferred.
WAMR also receives a runtime-owned internal writable copy of the verified
module bytes. The pinned API permits the loader to modify that buffer and
requires it to remain alive until unload, so the host unloads the module before
releasing the copy. The sealed source Wasm and its digest remain unchanged.

The harness is implemented but has not yet produced a passing retained report
in this snapshot. Its presence does not change `HARDWARE_NOT_RUN`, qualify the
canonical 16 MB layout, or prove any peripheral behavior.

After evaluation passes, package the complete retained run separately:

```bash
HX_AITRIP_OUT_DIR=reports/hardware/hx45-aitrip-n8r2-<id> \
PACKAGE_OUT_DIR=dist \
  make package-hardware-evidence
```

Do not place that evidence archive inside a source snapshot.

## HX4.5 Seeed Studio XIAO ESP32C6 hardware qualification

The parallel C6 lane targets the XIAO ESP32C6's exact 4 MB/no-PSRAM
configuration and uses the accepted RISC-V extension fixture:

```bash
HX_XIAO_OUT_DIR=reports/hardware/hx45-c6-xiao-001 \
  make hx45-c6-xiao-build
```

After flashing and retaining the complete monitor transcript across the
harness software reset, evaluate it with:

```bash
HX_XIAO_OUT_DIR=reports/hardware/hx45-c6-xiao-001 \
HX_XIAO_BOARD_MARKING="XIAO ESP32C6" \
  make hx45-c6-xiao-evaluate
```

The static build gate requires the 2 MiB application slot to fit and at least
160 KiB of internal RAM to remain for the guest's 128 KiB linear memory plus a
32 KiB fail-fast guard. Runtime free/largest-block heap and stack evidence is
still authoritative. See the
[complete XIAO C6 runbook](HX4_5_C6_XIAO_HARDWARE.md).

After a passing evaluation, package the complete retained run separately:

```bash
HX_XIAO_OUT_DIR=reports/hardware/hx45-c6-xiao-<id> \
PACKAGE_OUT_DIR=dist \
  make package-xiao-hardware-evidence
```

Do not place that evidence archive inside a source snapshot.

## HX5a extension fault-model hardening

HX5a is a host-only hardening gate. It adds no capability and does not require
ESP-IDF or a board. Run the narrow contract with:

```bash
make check-hx5a
```

Generate the unified, source-bound host report into a fresh directory:

```bash
HX_OUT_DIR=reports/host-extension/hx5a-<fresh-id> \
  make host-extension-faults-qualify
```

The qualifier re-executes the HX2 admission corpus, HX3 lifecycle corpus, HX4
happy path, HX4.5 adversarial corpus, and all nine HX5a deterministic
lifecycle transition points. It emits pass `HX5a`, phase
`FAULT_MODEL_HARDENED`, aggregate `HOST_HARDENING_PROVEN`, and separately
hashed corpus transcripts under the existing
`pulse.esp32.host-extension-report.v1` report schema.

This command does not invoke the ESP-IDF toolchain, flash a board, or ingest
the prior named-board reports. Hardware execution is therefore `NOT_RUN` for
this pass even when an earlier S3 or C6 baseline is listed as external context.
See [HX5a fault-model hardening](HX5A_EXTENSION_FAULT_HARDENING.md).

Sustained saturation, deadline/late-completion storms, repeated faults under
memory pressure, and targeted S3/C6 reruns remain HX5b.

## HX5b extension pressure seal

HX5b remains a hardening-only pass. Run the bounded host pressure contract:

```bash
make check-hx5b
```

Generate a fresh report:

```bash
HX_OUT_DIR=reports/host-extension/hx5b-<fresh-id> \
  make host-extension-pressure-qualify
```

The default report re-executes HX5a and records hardware as `NOT_RUN`. Use
`hx5b-s3-aitrip-build` / `hx5b-s3-aitrip-evaluate` and
`hx5b-c6-xiao-build` / `hx5b-c6-xiao-evaluate` for the opt-in physical lanes.
Both evaluation reports must be supplied together through `HX5B_HARDWARE_ARGS`
to close the dual-ISA pressure observation. See
[HX5b extension pressure seal](HX5B_EXTENSION_PRESSURE_SEAL.md).

## HP0 evidence reconciliation

The exact retained S3, C6, and dual HX5b reports are closed by HP0. Run the
source-distributed contract with:

```bash
make check-hp0
```

That test validates the accepted index, supersession/exclusion document, and
deterministic package mechanics without embedding hardware evidence in source.
To verify the external authorities and recreate the full archive, supply the
exact v17 source ZIP, corrected handoff, `reports.zip`, and three accepted run
roots to `make hp0-evidence-reconcile`; see
[Packaging and evidence](PACKAGING_AND_EVIDENCE.md).

## Dependency inventory

```bash
make deps-check
```

Optional bootstrap helpers are bounded and log their results:

```bash
make deps-rust
make deps-idf
```

They may fail in restricted or offline environments. A failed bootstrap must not be reported as a product failure unless the dependency was expected to be available.

## Documentation check

```bash
make docs-check
```

The checker verifies the canonical external documentation set and local Markdown links.

## Cleaning

```bash
make clean
```

This removes generated firmware, guest, and report outputs.

See [Testing](TESTING.md) for the coverage boundary and [Local bring-up](runbooks/LOCAL_BRINGUP.md) for a step-by-step workflow.
