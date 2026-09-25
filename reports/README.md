# Generated reports

Validation commands write machine-readable reports and logs into this directory.

These files are intentionally ignored by Git. Durable release evidence should be archived by the release process with the exact source, toolchain, hardware identity, and command that produced it.
They are also excluded from source packages. Use `make package-host-evidence`
or `make package-hardware-evidence` to preserve generated evidence without
embedding it in a source snapshot. Compact accepted-run identities live under
[`evidence/`](../evidence/README.md).

Common commands:

```bash
make deps-check
make docs-check
make check-full
make idf-reference-qualify
tools/run_pinned_idf_matrix.sh
make idf-family-seal-check
```

The [canonical IF7 evidence index](../docs/reference/IDF_FAMILY_MATRIX.md)
records the archive and per-observation hashes expected from the sealed run.

The IF4 command writes two complete S3 cell observations plus
`qualification-report.json` and `qualification-report.md`. Archive the entire
fresh output directory together; the report hashes are not substitutes for the
evidence files they describe.

IF6's host launcher selects Docker or Podman, enters the exact matrix-pinned
image, and invokes the single `make idf-family-qualify` orchestrator. It writes
`matrix-report.json`, `matrix-report.md`, the two S3 reference observations,
and the C3, ESP32, and C6 cell directories. Preserve the entire fresh output
directory, including failed-cell `build.log` files. A deterministic
`INCOMPATIBLE` report is mapping evidence; an infrastructure or unclassified
failure is not.
