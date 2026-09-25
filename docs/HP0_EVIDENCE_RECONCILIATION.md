# HP0 evidence reconciliation and next-boundary freeze

## Result

HP0 is complete. The exact v17 source authority, the retained AITRIP S3 and
XIAO C6 HX5b runs, and the final dual qualifier agree and close as:

```text
status: PASS
target result: NAMED_BOARD_OBSERVED on esp32s3 and esp32c6
hardware result: DUAL_NAMED_BOARD_OBSERVED
aggregate: DUAL_ISA_PRESSURE_OBSERVED
```

This is an evidence and boundary pass. It adds no firmware behavior, public
extension ABI, host import, provider surface, peripheral, transport, slot
mechanism, or update path.

## Authorities

| Authority | Identity |
|---|---|
| Source snapshot | `pulse-esp32-host-hx5b-source-v17.zip`; SHA-256 `e12962aafe1d3529fe32f27aa161218096660c38c8fadda9c2cad1f8b7c06e0f`; 759,832 bytes; Library version 17 |
| Pre-reconciliation source tree | 368 files; SHA-256 `f430099caeeda6ed143d08e15f1a40de3867b987b648ff6e5993b0670af16bf4` |
| Corrected handoff | `pulse-esp32-host-hx0-hx5b-closure-and-next-phase-handoff-v1.md`; internal revision v2; SHA-256 `dd70e6b5fb5c24ead872c76339a9a054b8120bd3a34468aacf1613148d49e7c9` |
| Supplied evidence | `reports.zip`; SHA-256 `43faf9866044ca24ed76efc056f498d9ea42fb82cfcfb74fbbc86a3f3850872c`; 160,765,931 bytes |
| Common Wasm | 306 bytes; SHA-256 `ef8b21a4b7a423923c09f5e38fc626ff7d1cda856c4935db7f191695a333e5c4` |

The handoff's filename retains `v1`, while the document identifies itself as
revision v2. HP0 records both facts rather than silently renaming or rewriting
the supplied authority.

## Reconciled evidence

HP0 verified 20 evidence JSON documents and 89 embedded path/hash/size records.
It independently recomputed the pre-reconciliation source-tree digest, the
114-file sealed firmware digest, the native-SDK digest, the pressure-model
digest, both native ELF identities, both common-Wasm copies, all raw
serial/build/evaluator references, the HX5a baseline evidence referenced by
the dual report, and the dual pressure corpus.

| Evidence | Result | Report SHA-256 |
|---|---|---|
| `hx5b-aitrip-001` | `PASS`; `NAMED_BOARD_OBSERVED`; pressure `PASS` | `8a3bc822b514f2e23393d9c41bba4d2a6bb96723b71990381ebf9b691d9396e3` |
| `hx5b-xiao-c6-001` | `PASS`; `NAMED_BOARD_OBSERVED`; pressure `PASS` | `5ba86a8355efae492b05663d73bba36310bd478c0717ccdaee8f80c03c699fc6` |
| `hx5b-dual-001` | `PASS`; `DUAL_ISA_PRESSURE_OBSERVED` | `06e9718ea562fbdf0a016e753b4ebfbd7f9780023b3129ab929ad384d20243f8` |

The full accepted evidence is packaged separately from source with a
deterministic manifest. The source-distributed accepted identities live in
[`evidence/hardware/index.json`](../evidence/hardware/index.json).

### Nested workspace reconciliation

The supplied S3 run contains a nested
`project/reports/hardware/hx5b-xiao-c6-001` tree. It is post-build workspace
output, not an input named by the S3 build or evaluator, and duplicates the
independently retained top-level C6 run. The original `reports.zip` hash
preserves the raw supplied boundary. The accepted evidence package excludes
`hardware/hx5b-aitrip-001/project/reports` and packages the verified top-level
C6 run once under its own ISA identity. No evidence byte is synthesized.

## Supersession authority

The corrected handoff bound above supersedes the original HX6/HX7 sequence.
Passing HX5b does not authorize the old provider-composition path. The next
execution namespace is HP, beginning with host platform and recovery
authority.

The intended order is:

1. HP1 — interrupt, priority, bounded-queue, memory-reserve, and admission
   authority;
2. HP2 — board/profile/intent/build-plan/build-lock/fingerprint separation;
3. HP3/HP3.5 — two bounded Pulse application slots, deterministic fallback,
   torn-write and attributed-reset sealing;
4. HP4 — protected administration, exclusive C6 update/recovery mode, and
   host-owned verification authority; and
5. HP5/HP5.5 — host-owned listener/TLS with bounded Pulse HTTP routing and a
   dual-board recovery seal.

## Frozen exclusions

Until HP1 through HP5.5 close, the following remain stopped:

- old HX6/HX7 provider composition;
- the external ESP32 provider and Pulse configuration ergonomics;
- MQTT implementation or use as an administrative, deployment, or rollback
  channel;
- GPIO or broad peripheral expansion as the next vertical slice;
- RAX packaging;
- host-firmware, bootloader, or partition-table OTA;
- production fleet rollout and final secure-boot/eFuse provisioning;
- public extension ABI changes, additional host imports, multiple resident
  native extensions, or hot native replacement; and
- any design that makes an application own network listeners, credentials,
  slot writes, boot choice, confirmation, administration, or recovery.

Pulse application replacement remains distinct from host-firmware
replacement. Native ELF remains trusted, scarce target refinement rather than
the default home for durable host services.

## Gate opened by HP0

HP0 authorizes contract work on HP1 and HP2. It does not authorize firmware
implementation beyond the frozen contract until resource authority, C6
control-plane reserves, build coherence, and application admission have been
made explicit and tested.
