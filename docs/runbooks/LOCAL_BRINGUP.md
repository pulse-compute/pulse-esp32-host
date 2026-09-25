# Local Bring-up Runbook

## 1. Inspect dependencies

```bash
make deps-check
cat reports/deps_check.md
```

## 2. Run schema/profile/manifest validation

```bash
make validate
```

## 3. Run contract tests

```bash
make test
python3 -B -m unittest discover -s tests -v
```

## 4. Run milestone gates

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

## 5. Run full report

```bash
make check-full
cat reports/r9_test_report.md
```

## 6. Interpret results

Acceptable in a development environment with bounded missing dependencies:

```text
PASS host-side checks
SKIPPED_ENV Rust/ESP-IDF checks if toolchains unavailable
SKIPPED_NO_HARDWARE hardware smoke if no board attached
```

Not acceptable:

```text
FAIL any host-side safety/security/bundle/activation check
silent missing report/log files
ambiguous skipped gate without detail
```

## 7. Optional dependency bootstrap

```bash
make deps-rust
make deps-idf
```

In offline or restricted environments these bootstrap steps may fail. The desired outcome is an explicit logged skip or failure, not an unrecorded unknown.

## 8. Validate the ESP-IDF family inputs

```bash
python3 -B tools/check_idf_matrix.py --check-locks
python3 -B tools/check_deps.py --realization esp32s3-reference
make idf-family-seal-check
```

The [canonical family matrix reference](../reference/IDF_FAMILY_MATRIX.md)
defines the exact claim and evidence identities checked by the seal target.

Do not run `idf.py set-target` in `firmware/`. Lock updates must use the
explicit `tools/build_idf_cell.py --cell <attempted-realization> --update-lock`
path in the pinned lane.

## 9. Build one isolated ESP-IDF cell

After exporting an ESP-IDF environment that matches the matrix exactly:

```bash
python3 -B tools/build_idf_cell.py \
  --matrix firmware/idf-family-matrix.json \
  --cell esp32s3-reference \
  --out-dir reports/idf-family/esp32s3-reference-run-1 \
  --timeout 1800
```

Treat the resulting `COMPILE_PROVEN` report as one build observation.

## 10. Qualify the ESP32-S3 reference

From inside the digest-pinned image, with its digest recorded explicitly:

```bash
PULSE_IDF_CONTAINER_IMAGE='espressif/idf@sha256:8d1846f61ff8db00ba6530501f90bf43604d923072a616c806fef8e85a88ed82' \
PULSE_IDF_EXECUTION_ADAPTER=docker \
make idf-reference-qualify
```

This runs two independent clean builds and fails closed on any input,
configuration, lock, artifact, or image-identity mismatch. Inspect
`reports/idf-family/esp32s3-reference-qualification/qualification-report.md`.
The maintained IF4 observation is `BUILD_QUALIFIED`.

## 11. Interpret the IF5 family mapping

The three exploratory cells were attempted in the pinned lane. The observed
mapping is:

```text
esp32c3-compile  INCOMPATIBLE   internal DRAM overflow by 17,664 bytes
esp32-compile    INCOMPATIBLE   internal DRAM overflow by 115,120 bytes
esp32c6-compile  COMPILE_PROVEN all required build artifacts emitted
```

Do not shrink runtime heaps or change task/core policy merely to turn either
no-PSRAM incompatibility green. A future memory or board realization must be a
new explicit matrix decision.

## 12. Run the IF6 family aggregate

From a host with Docker or Podman and a fresh output path:

```bash
WDC_IDF_MATRIX_OUT_DIR=reports/idf-family/if6-local \
  tools/run_pinned_idf_matrix.sh
```

Inspect `matrix-report.md` and archive its entire sibling evidence tree. A
successful aggregate requires S3 `BUILD_QUALIFIED`, all requested attempts in
canonical order, one source-tree hash, complete hashed evidence, and only
`COMPILE_PROVEN` or deterministic `INCOMPATIBLE` exploratory results. Missing
container execution, network/tool failures, timeouts, unclassified failures,
or missing evidence fail the command.

After a successful rerun, validate it against the documented seal:

```bash
python3 -B tools/check_idf_family_docs.py \
  --evidence-root reports/idf-family/if6-local
```

Do not flash a device as part of this pass. GPIO electrical behavior, watchdog
and reset behavior, runtime memory, FreeRTOS scheduling, network transports,
power-loss handling, and rollback on hardware remain separate deferred work.
