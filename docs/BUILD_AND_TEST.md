# Build and test

The repository separates fast host-side contract checks from toolchain and hardware qualification.

## Host-side checks

```bash
make validate
make test
make check-r9
make docs-check
make check-full
```

Run raw test discovery when changing test infrastructure:

```bash
python3 -B -m unittest discover -s tests -v
```

Generated reports are written to `reports/` and are ignored by Git.

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

## ESP-IDF firmware build

```bash
cd firmware
idf.py set-target esp32s3
idf.py build
```

Or:

```bash
make build-firmware
```

Record the ESP-IDF version and target configuration in any hardware-validation report.

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
