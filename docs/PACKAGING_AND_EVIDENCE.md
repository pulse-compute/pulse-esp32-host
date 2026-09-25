# Packaging and evidence

## Boundary

Pulse ESP32 Host has three distinct distribution concerns:

1. The source snapshot contains code, contracts, documentation, dependency
   locks, compact evidence indexes, and explicitly admitted test fixtures.
2. ESP-IDF, compiler/debugger toolchains, and managed components are installed
   dependencies. They are selected and verified by the pinned lane rather than
   copied into the source snapshot.
3. Qualification output is durable evidence. ELF files, linker maps, firmware
   binaries, logs, and hardware transcripts are packaged separately from
   source.

`reports/` remains an ignored local workspace. It is never a source-package
input.

## Installed dependencies

The supported lane is ESP-IDF v5.4.4 at commit
`296b6eab9445fd720e71aecab961e2d3fbca9944`. Use an existing exact installation
or the bounded bootstrap helper:

```bash
make deps-idf
```

The environment verifier rejects version, commit, target, or tool drift. WAMR
and the ELF loader are resolved by ESP-IDF Component Manager from
`idf_component.yml` and the target-specific `dependencies.lock` files. Neither
component is vendored into a source release.

## Deterministic packages

Create a lean source snapshot:

```bash
PACKAGE_OUT_DIR=dist make package-source
```

The source packager uses a top-level allowlist, fixed ZIP timestamps, normalized
permissions, stable ordering, and a generated `PACKAGE-MANIFEST.json`. It fails
if an unapproved ELF, map, firmware binary, object, archive, or Wasm artifact
appears outside the explicit contract-fixture locations. The compressed source
package is capped at 2 MiB to catch evidence or build-tree regressions.

Create the complete accepted HX1 through HX4.5 host/build evidence artifact:

```bash
PACKAGE_OUT_DIR=dist make package-host-evidence
```

The packager validates every accepted qualification-report hash from
[`evidence/host-extension/index.json`](../evidence/host-extension/index.json),
then archives the complete corresponding report trees with an
`EVIDENCE-MANIFEST.json`.

After a passing named-board evaluation, create a separate hardware artifact:

```bash
HX_AITRIP_OUT_DIR=reports/hardware/hx45-aitrip-n8r2-<id> \
PACKAGE_OUT_DIR=dist \
  make package-hardware-evidence
```

This command refuses unevaluated or non-passing runs. Full evidence archives
may be large; their size is not source footprint and must not be addressed by
discarding required audit material.

For a passing XIAO ESP32C6 run, use the board-specific target:

```bash
HX_XIAO_OUT_DIR=reports/hardware/hx45-c6-xiao-<id> \
PACKAGE_OUT_DIR=dist \
  make package-xiao-hardware-evidence
```

### HP0 reconciled dual-board evidence

HP0 binds the exact v17 source snapshot, corrected next-phase handoff,
supplied `reports.zip`, both named-board run roots, and the final dual qualifier
before producing one deterministic manifested archive:

```bash
PACKAGE_OUT_DIR=dist \
HP0_SOURCE_SNAPSHOT=/path/to/pulse-esp32-host-hx5b-source-v17.zip \
HP0_HANDOFF=/path/to/pulse-esp32-host-hx0-hx5b-closure-and-next-phase-handoff-v1.md \
HP0_INPUT_ARCHIVE=/path/to/reports.zip \
HP0_S3_RUN_DIR=/path/to/reports/hardware/hx5b-aitrip-001 \
HP0_C6_RUN_DIR=/path/to/reports/hardware/hx5b-xiao-c6-001 \
HP0_DUAL_RUN_DIR=/path/to/reports/host-extension/hx5b-dual-001 \
  make hp0-evidence-reconcile
```

The reconciler validates the source ZIP and pre-reconciliation source-tree
identity, every path/hash/size record in the accepted reports, both raw serial
and build reports, the HX5a/pressure evidence referenced by the dual report,
and every packaged file against the supplied `reports.zip`. It emits
`HP0-RECONCILIATION.json` and `EVIDENCE-MANIFEST.json` inside the archive.

The supplied S3 project contains a post-build nested `project/reports` copy of
the C6 run. The exact input archive identity is retained, but that duplicate
workspace output is excluded from the accepted S3 root and the verified
top-level C6 run is packaged once under its own target identity. See the
[HP0 reconciliation](HP0_EVIDENCE_RECONCILIATION.md).

### HP1 synthetic host-kernel evidence

HP1 produces a fresh host-only resource-authority report:

```bash
HP1_OUT_DIR=reports/host-kernel/hp1-<fresh-id> \
  make host-kernel-qualify
```

The output contains the frozen model, compile/run logs, native smoke executable,
normalized smoke JSON, and JSON/Markdown qualification reports with hashes for
each supporting artifact. The qualifier requires an absent or empty output
directory and never overwrites evidence.

The HP1 report is classified `HOST_EXECUTED_SYNTHETIC_ONLY`; it is not appended
to the HP0 hardware archive and does not relabel the retained v17 S3/C6 runs.
Package a new source snapshot after HP1 through `make package-source`. A future
physical HP gate requires a separate exact build/serial/evaluator archive for
the HP1-or-later firmware tree.

### HP2 synthetic host-build evidence

HP2 produces a fresh host-only build-coherence report:

```bash
HP2_OUT_DIR=reports/host-build/hp2-<fresh-id> \
  make host-build-qualify
```

The output contains both deterministic plans, exact replay results, normalized
fingerprints, generated-C equality evidence, native smoke compile/run output,
eight negative-case records, and JSON/Markdown qualification reports. The
qualifier requires an absent or empty output directory and does not overwrite
evidence.

The report is classified `HOST_EXECUTED_SYNTHETIC_ONLY`. It does not extend the
HP0 hardware archive or claim that the HP2 firmware tree was built, flashed, or
observed. A source release after HP2 must carry the exact board/profile/catalog,
lock, fingerprint, generated C, contract, and documentation inputs together.
Any later physical HP2 evidence must use those exact locks and a separate
manifested build/serial/evaluator archive.

### HP3 synthetic application-slot evidence

HP3 produces a fresh host-only slot-authority report:

```bash
HP3_OUT_DIR=reports/app-slots/hp3-<fresh-id> \
  make app-slots-qualify
```

The output contains the frozen model, exact input bundle, both current
profiles/partition layouts/locks/fingerprints, smoke source and executable,
compile/run logs, normalized fourteen-case result, JSON/Markdown report, and a
hash manifest. The qualifier requires an absent or empty directory.

The report is `HOST_EXECUTED_SYNTHETIC_ONLY`. It does not extend HP0 hardware
evidence or claim a current firmware build, target execution, production
signing deployment, or physical power-loss result. HP3.5 evidence must be a
separate manifested interruption/fault/physical campaign bound to the exact
HP3 source and locks.

### HP3.5 host interruption evidence

HP3.5 produces a separate exhaustive host report:

```bash
HP3_5_OUT_DIR=reports/app-slots/hp3_5-<fresh-id> \
  make app-slots-adversarial-qualify
```

The manifested output contains the frozen addendum and physical campaign,
hardware evaluator, exact input bundle, smoke source and executable,
compile/run logs, both regenerated lock/fingerprint bindings, and the exact
11,657-case result. Its aggregate is
`HOST_SLOT_ADVERSARIAL_POWER_LOSS_SEALED`.

This archive is not physical evidence. Actual S3 and C6 board directories must
remain separate and are promoted only by
`tools/evaluate_hp3_5_slot_hardware.py`; a missing, synthetic, single-board, or
hash-mismatched report is insufficient.

The accepted external HP3.5 campaign now satisfies that promotion gate on both
named boards and closes as `DUAL_NAMED_BOARD_SAFE_SUBSET_OBSERVED`. Source
retains only the exact campaign, build-report, board-report, serial-log, dual
evaluation, and input-archive identities in
[`evidence/hardware/hp3_5-index.json`](../evidence/hardware/hp3_5-index.json).
Complete run directories and private pre-run full-flash backups remain external
to every source package.

## Claim rule

Compact indexes make accepted identities discoverable from source, but they
are not substitutes for their full evidence artifacts. A source snapshot,
build report, or copied final marker alone does not promote a hardware claim.
