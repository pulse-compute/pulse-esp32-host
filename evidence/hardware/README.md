# Hardware evidence

HP0 has reconciled one passing HX5b run for each named target and the final
dual qualifier. The accepted source-distributed identities are in
[INDEX.md](INDEX.md) and [index.json](index.json); the full evidence remains in
the separate deterministic hardware-evidence archive.

The later HP3.5 safe application-slot campaign also passed both named boards.
Its source-distributed identities are in
[HP3_5_INDEX.md](HP3_5_INDEX.md) and
[hp3_5-index.json](hp3_5-index.json). Complete run directories remain external,
and private pre-run full-flash backups are never source-distributed.

Hardware evidence is never embedded in the source snapshot. A named-board run
is packageable only after its evaluator has emitted:

- `evaluation/qualification-report.json` with `status: PASS` and
  `runtime_result: NAMED_BOARD_OBSERVED`; and
- `evaluation/qualification-report.md`.

Package the complete retained run with:

```bash
HX_AITRIP_OUT_DIR=reports/hardware/hx45-aitrip-n8r2-<id> \
PACKAGE_OUT_DIR=dist \
  make package-hardware-evidence
```

The resulting evidence artifact includes the build inputs and identities,
firmware artifacts, complete serial transcript, evaluator output, and a
deterministic manifest. A copied final serial line is not sufficient.

For the XIAO ESP32C6 lane:

```bash
HX_XIAO_OUT_DIR=reports/hardware/hx45-c6-xiao-<id> \
PACKAGE_OUT_DIR=dist \
  make package-xiao-hardware-evidence
```

Use `make hp0-evidence-reconcile` to reproduce the combined S3/C6/dual archive
from the exact authorities. That path validates embedded hashes and input ZIP
membership in addition to the individual evaluator result.
