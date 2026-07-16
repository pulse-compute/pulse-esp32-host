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

## ESP-IDF build skipped

Symptoms:

```text
idf.py: not found
```

Fix in a local environment with ESP-IDF installed:

```bash
. /path/to/esp-idf/export.sh
make build-firmware
```

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
