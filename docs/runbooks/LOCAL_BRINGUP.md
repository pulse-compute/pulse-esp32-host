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

