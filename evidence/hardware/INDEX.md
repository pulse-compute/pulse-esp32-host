# Accepted HX5b hardware evidence

HP0 reconciled the retained HX5b S3, C6, and dual-pressure reports against the
exact v17 source authority. Full build trees, firmware artifacts, serial logs,
and evaluator outputs remain outside the source snapshot in the separately
manifested hardware-evidence archive.

| Target | Accepted run | Result | Evaluation JSON SHA-256 | Serial SHA-256 |
|---|---|---|---|---|
| ESP32-S3 / Xtensa | `hx5b-aitrip-001` | `PASS`; `NAMED_BOARD_OBSERVED` | `8a3bc822b514f2e23393d9c41bba4d2a6bb96723b71990381ebf9b691d9396e3` | `105ec5e36e0b9555c98190fbf47aa0b1d94d16c45eb245f424ee3eaf3af5fa13` |
| ESP32-C6 / RISC-V | `hx5b-xiao-c6-001` | `PASS`; `NAMED_BOARD_OBSERVED` | `5ba86a8355efae492b05663d73bba36310bd478c0717ccdaee8f80c03c699fc6` | `dcd19341ae889aade784557800afbe844af6d8343c66d6a61bfcbd91b4f81976` |

The accepted dual qualifier is `hx5b-dual-001`. Its JSON report has SHA-256
`06e9718ea562fbdf0a016e753b4ebfbd7f9780023b3129ab929ad384d20243f8`
and closes with `DUAL_ISA_PRESSURE_OBSERVED` plus
`DUAL_NAMED_BOARD_OBSERVED`.

The machine-readable authority is [index.json](index.json). It also binds the
v17 source archive, pre-reconciliation source-tree identity, corrected
next-phase handoff, input evidence archive, common Wasm, native ELFs, build
reports, Markdown reports, and the one excluded nested workspace path.

The S3 input tree contained `project/reports/hardware/hx5b-xiao-c6-001`, a
post-build duplicate of the independently retained C6 run. HP0 preserves the
input `reports.zip` identity but does not treat that nested workspace copy as
part of the accepted S3 root. The primary C6 root is verified and packaged
once under its own target identity.
