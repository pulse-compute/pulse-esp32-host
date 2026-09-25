# Troubleshooting

## `make check-full` reports `PARTIAL`

This is expected in environments without Rust, ESP-IDF, or hardware. Inspect the report:

```text
reports/r9_test_report.md
reports/r9_test_report.json
```

`PARTIAL` is acceptable only when all non-passing gates are bounded skips such as `SKIPPED_ENV` or `SKIPPED_NO_HARDWARE`. Any `FAIL` is a regression.

## Rust guest build skipped

Symptoms:

```text
cargo: not found
rustc: not found
rustup: not found
```

Fix:

```bash
rustup target add wasm32-unknown-unknown
make build-guest
```

A restricted or offline development environment may not allow installation. In that case the report should classify the result explicitly rather than hiding the missing gate.

## ESP-IDF cell build cannot start

First confirm the expected lane and evidence identities in the
[ESP-IDF family build matrix](reference/IDF_FAMILY_MATRIX.md).

Symptoms:

```text
idf.py: not found
```

Fix in a local environment with the matrix-pinned ESP-IDF installed:

```bash
. /path/to/esp-idf/export.sh
make build-firmware
```

The environment must report the exact version and source commit declared in
`firmware/idf-family-matrix.json`. A different installed IDF is rejected rather
than treated as equivalent.

If the builder reports that the evidence directory is not empty, choose a new
directory instead of overwriting a previous observation:

```bash
WDC_IDF_OUT_DIR=reports/idf-family/esp32s3-reference-run-2 make build-firmware
```

IF4 requires a runtime capable of executing the matrix-declared `linux/amd64`
OCI image by digest. Install Docker or Podman, or run the command on a qualified
machine/runner that has one. Do not replace the digest with the `v5.4.4` tag.
A user-space OCI executor may be used when namespaces are unavailable, but its
name and any compatibility adapter must be recorded through
`PULSE_IDF_EXECUTION_ADAPTER`; it is execution provenance, not a different IDF
lane. A missing runtime, blocked registry, emulation failure, timeout, or image
identity mismatch is `INFRASTRUCTURE_FAILURE`, never compile incompatibility.

For IF6, `tools/run_pinned_idf_matrix.sh` performs this selection and fails
before entering the image when neither Docker nor Podman is available. Set
`WDC_CONTAINER_RUNTIME=docker` or `podman` only to select an installed supported
runtime; arbitrary executor commands are rejected. The user-space executor used
to produce this snapshot required an explicit compatibility adapter and remains
manual execution provenance, not a portable substitute baked into the launcher.

If a qualification output directory already contains evidence, select a new
one instead of deleting or overwriting it:

```bash
WDC_IDF_OUT_DIR=reports/idf-family/if4-rerun make idf-reference-qualify
```

For the family aggregate, use a new repository-relative path:

```bash
WDC_IDF_MATRIX_OUT_DIR=reports/idf-family/if6-rerun \
  tools/run_pinned_idf_matrix.sh
```

If a rerun passes but disagrees with the documented report or log hashes, do
not edit the seal to make it green. Confirm the source-tree hash, matrix,
configuration, locks, image digest, and execution adapter; then either reproduce
the sealed observation or record a new explicit seal from a genuinely changed
source revision.

## Exploratory cell fails with an internal DRAM overflow

IF5 observed these exact final-link boundaries in the declared no-PSRAM
profiles:

```text
esp32c3-compile  region `dram0_0_seg' overflowed by 17664 bytes
esp32-compile    region `dram0_0_seg' overflowed by 115120 bytes
```

These are `INCOMPATIBLE` mapping results, not infrastructure failures. Do not
arbitrarily reduce WAMR/runtime heaps, enable an undeclared memory topology, or
change FreeRTOS task policy to make the existing cell pass. A different board,
PSRAM, or memory-policy experiment requires a new explicit realization after
the host-contract design phase. ESP32-C6 completed the same no-PSRAM compile
probe and is `COMPILE_PROVEN`; that still does not establish runtime headroom.

## AITRIP run asserts in `xTaskCreateStaticPinnedToCore`

If serial reaches `extension-initialize` and then reports
`xPortCheckValidTCBMem(pxTaskBuffer)`, the loaded ELF's writable image was
placed in PSRAM. ESP-IDF requires static FreeRTOS TCB memory to be internal and
byte-accessible; enabling external task stacks does not relax the TCB rule.

Use a source package that includes the HX4.5 hybrid ELF allocator, choose a
fresh `RUN_DIR`, rebuild, and reflash. The expected next marker is a passing
`extension-start` case. Do not switch IDF major versions or enable
`CONFIG_FREERTOS_TASK_CREATE_ALLOW_EXT_MEM` as a repair: the target lane remains
pinned to IDF v5.4.4, executable ELF text remains in PSRAM, and writable ELF
state must be internal.

If the TCB assertion is gone but `xQueueGenericCreateStatic` instead raises
`LoadStoreAlignment` in `spinlock_acquire`, the writable block is internal but
still uses the loader's unpadded section addresses. Use a source package with
the allocation-residue solver and paired free wrapper. For the sealed HX4.5
ELF, a writable base ending in hexadecimal `...e` places the descriptor and
`.bss` at their required four- and sixteen-byte boundaries. Do not patch the
queue or weaken the FreeRTOS checks.

If `extension-start` and `extension-event-arrived` pass but WAMR then panics in
`espidf_memmap.c:os_mmap` while zeroing 128 KiB, the native loader repairs are
working. The pinned WAMR port placed writable linear memory in the same
cache-backed PSRAM pool as native executable text. Use a source package with
the HX4.5 WAMR mmap policy: executable mappings remain delegated to WAMR and
non-executable mappings are explicitly internal and byte-accessible. Do not
change the sealed Wasm, lower its memory declaration, or switch IDF versions
to conceal this target-memory boundary.

If the log then reaches `static wasm payload loaded` but the following
`common-wasm-load` marker faults inside `printf` with the same cache-writeback
diagnostic, inspect the buffer passed to `wasm_runtime_load`. WAMR's buffer is
writable and must outlive the module. Passing a flash-resident `const` array by
casting away constness can dirty a flash cache line during load and report the
fault only on later eviction. Use the runtime-owned internal Wasm copy, retain
it through `wasm_runtime_unload`, and free it afterward. Do not make the static
Wasm array writable globally or weaken its artifact identity.

If `common-wasm-load` and `common-wasm-exports` pass but the first guest call
asserts in `pthread_self` with `Failed to find current thread ID`, WAMR is being
driven from ESP-IDF's raw `app_main` FreeRTOS task. The pinned WAMR ESP-IDF port
requires a real pthread identity; `xTaskCreate` alone is explicitly
insufficient. Use the source package whose firmware and HX4.5 entrypoints run
their complete WAMR-owning control flow on one joinable pthread. Do not replace
`os_self_thread` with a cast FreeRTOS task handle: WAMR's ESP-IDF thread APIs
use `pthread_t`, and a forged identity would violate later lifecycle behavior.

## Ninja says `build.ninja` is still dirty after 100 tries

This is normally a future source timestamp, not an inaccurate system clock.
ZIP entry timestamps have no timezone; a snapshot packed in UTC and extracted
on a macOS host west of UTC can make its inputs appear several hours newer than
a freshly generated Ninja manifest. The HX4.5 builder stages sealed copies of
the firmware components and native SDK with a fixed past mtime before invoking
ESP-IDF. Use a source snapshot containing that staging repair and a fresh
`RUN_DIR`. The adjacent `git rev-parse` warning remains expected because the
retained project under `reports/hardware/` is deliberately not a Git checkout.

## Bundle rejected: bad signature

Check:

- signature algorithm in manifest;
- container signature algorithm;
- dev vs production mode;
- trusted key ID;
- verifier callback availability;
- bundle was not modified after signing.

Production mode intentionally rejects development HMAC signatures.

## Bundle rejected: anti-rollback

Check the security counter in the manifest and the metadata security floor. The candidate counter must not be lower than the floor.

## Bundle rejected: missing exports

Run:

```bash
tools/wasm_inspect.py path/to/payload.wasm
```

Required exports:

```text
wdc_module_init
wdc_module_on_event
wdc_module_health
wdc_module_shutdown
```

R8.1 hardened this check to parse the WASM export section, so strings in custom sections do not count.

## Host call denied unexpectedly

Check:

1. safety state is `APP_RUNNING`;
2. authorizer is installed;
3. manifest grants the resource and operation;
4. device profile contains the resource;
5. network topic/URL/method matches profile policy;
6. payload/request/response sizes are within active limits;
7. rate limit has not been exceeded.

## Relay toggles during boot

This should not happen in production defaults. Verify:

```text
WDC_BUILD_PROFILE_PROD=1
WDC_ENABLE_EFFECTFUL_SELF_TESTS=0
```

R8.1 disabled effectful boot self-tests by default.

## Metadata appears corrupted

The OTA metadata journal should select the highest-generation valid committed record. If both records are invalid, the shell should fall back to initialized/no-bundle safe state. Hardware power-loss testing is still required before production.
