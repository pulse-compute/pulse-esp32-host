# ESP-IDF family build matrix

This is the canonical build-evidence record for the Pulse ESP32 host's IF0–IF7
matrix work.

The S3 reference firmware is reproducibly build-qualified under the pinned
ESP-IDF lane. Additional family targets have explicit compile-probe results.

That statement is deliberately narrow. This record establishes build mapping,
not board portability, target runtime behavior, device safety, or a Pulse
provider implementation.

## Sealed source and lane

The supplied working snapshot has no `.git` metadata, so IF7 does not invent a
Git commit for the modified IF0–IF7 tree. The exact firmware input is instead
identified by the source digest recorded independently by every cell:

| Field | Sealed value |
|---|---|
| Repository | `pulse-compute/pulse-esp32-host` |
| Firmware source-tree SHA-256 | `2e0935fbc0f8fc2013bb09c4f8a5453bc8718a91b3e0b5c3201b997e616c6a9e` |
| Matrix | `firmware/idf-family-matrix.json` |
| Lane | `idf-5.4.4` |
| ESP-IDF | `v5.4.4` |
| ESP-IDF source commit | `296b6eab9445fd720e71aecab961e2d3fbca9944` |
| Platform | `linux/amd64` |
| OCI image | `espressif/idf@sha256:8d1846f61ff8db00ba6530501f90bf43604d923072a616c806fef8e85a88ed82` |
| WAMR component | `espressif/wasm-micro-runtime` `2.4.0~1` |
| WAMR component SHA-256 | `04f25aad2896b5e906397a061d35cce560609bebd3913a4be7e365ecbf2dd9d6` |
| Component manifest SHA-256 | `2915c87bbbb4002ac21c3e598680f5204fded60ca89131ba8adb3a8b8f0a3148` |

The firmware digest covers the matrix, defaults, partition inputs, locks, and
firmware source while excluding generated build outputs. It is the applicable
source revision for these observations. A later Git publication must record
the actual commit separately; it must not relabel the earlier roadmapping
revision as this seal.

## Observed mapping

| Realization | Target | Intent | Result | Exact boundary |
|---|---|---|---|---|
| `esp32s3-reference` | `esp32s3` | required | `BUILD_QUALIFIED` | Two clean builds; inputs, generated configuration, resolved lock, ELF, application binary, bootloader, and partition table were byte-identical. |
| `esp32c3-compile` | `esp32c3` | exploratory | `INCOMPATIBLE` | Final link: `dram0_0_seg` overflowed by 17,664 bytes. |
| `esp32-compile` | `esp32` | exploratory | `INCOMPATIBLE` | Final link: `dram0_0_seg` overflowed by 115,120 bytes. |
| `esp32c6-compile` | `esp32c6` | exploratory | `COMPILE_PROVEN` | Clean build emitted every required artifact and matching evidence hash. |

An exploratory incompatibility is an accepted mapping outcome only because the
build was genuinely attempted and its deterministic linker boundary is present
in both the normalized cell report and hashed build log. It is not a positive
technical result.

## Realization input identities

`Configuration SHA-256` hashes canonical JSON containing the target, the
ordered defaults paths and content hashes, and the selected partition path and
content hash. It identifies the declared realization configuration even when a
failed final link does not publish a generated `sdkconfig`.

| Realization | Configuration SHA-256 | Partition SHA-256 | Dependency-lock SHA-256 |
|---|---|---|---|
| `esp32s3-reference` | `eb4e9dc951af9359a2155eb10d504524b3abd89bded28d4331be7db29a0e7166` | `1fd37cc514bdb529152c6141495293903d57419641a7ab764668bea5acb25f1b` | `b8826d9316e85096bca38cabbcb70a8faf431cd5a392bbce322849bd2470feed` |
| `esp32c3-compile` | `2165303ea146aa322a3870d7463921e41cecb5656fc3386d2845f988ebf8a112` | `d7e0d768a18febd5c8701cfdc45aa649992d2deb25e29b5129af75b9247c7df9` | `6d4fd7e13d6fd68bad5519dd53734d07bcf1a8380cf6759949db9664c637953a` |
| `esp32-compile` | `6ccd323ca570a0f18c3e662f4cb6d4ef4e14cce966853568612a1ce9552cf062` | `d7e0d768a18febd5c8701cfdc45aa649992d2deb25e29b5129af75b9247c7df9` | `25572c7b186419a10288cd0f620f29a2c30657cea667a251f444e016e46c0817` |
| `esp32c6-compile` | `a126b64c1a51f60339cf1c85a3493409260813780acbea9c60fd2bfc4b05398a` | `d7e0d768a18febd5c8701cfdc45aa649992d2deb25e29b5129af75b9247c7df9` | `12814d749bb0e443bb1c3fffbacb853c6effe79c1fc749a8835a889a744b0d97` |

The common defaults SHA-256 is
`a452142e2eddcbd0fff4bcddaf80e702044ff338f1f1f2c07f57951843faac04`.
The realization overlay hashes, in table order, are
`01cf2d07b54d6f8c0b5dc888a4f3b4d243b47bfcd079cc1a7f5b6c27646ed0e9`,
`8ce842f712c04988dbf7d41855d60a3e76f5d9caa8402842bac92f68de51169b`,
`47209e4e17ac792c93dcfaad9c8c029325cdc48bc69a96321f0052b7d9165e21`,
and `ce5e3c5ee94fb948f2c8b7a5fd546a8d8a9b099dac89c236f6f67f59172365c5`.

## Evidence artifact index

Generated evidence is intentionally not committed. The sealed archive is
`pulse-esp32-host-if7-evidence.zip`, SHA-256
`3b9d36d8abb95a69fd3da0a83d2d497efd19a55421f4a21401b349555444d036`.
Its paths below are archive-relative.

| Observation | Report and SHA-256 | Build log and SHA-256 |
|---|---|---|
| Family aggregate | `matrix-report.json` — `9b71e8eb5c1b7ca6d1de426f239b108a5a3573806880d3db9f37245f8abb224c` | Per-cell logs below |
| S3 qualification | `reference/qualification-report.json` — `354d61ff92a9a78e41d11322a65a7b8a911874760ab7b19399552583fd7d9098` | `reference/run-a/build.log` — `12cb3494567030934edd1fe5483573e87239c2acedaec85462e4768faf7511e0`; `reference/run-b/build.log` — `4c79c5d972eda487e91699cc11d9421d5b63e2c5165da14143260e975e5604d2` |
| C3 probe | `exploratory/esp32c3-compile/cell-report.json` — `ad7f1ff36efd654c1718dcca6e8fb45f37b5b8e8eebec82292e549b162495ac1` | `exploratory/esp32c3-compile/build.log` — `f588bf18d2bb3e24071438b84529889a5098bb733afff618f729da8cdf17354b` |
| ESP32 probe | `exploratory/esp32-compile/cell-report.json` — `6d7c2717ad8103c2329ff3f3e8990a3aa08d8ba0d73093c84890a743163e5de2` | `exploratory/esp32-compile/build.log` — `c8401683e98c84d32c4d9aa98e9d9c4b89871951584c50d040915c3be7404f1e` |
| C6 probe | `exploratory/esp32c6-compile/cell-report.json` — `fbe9de055d38080ebb80e97b96b634bbd03ef53425df6643f799bde646fd3c10` | `exploratory/esp32c6-compile/build.log` — `651a5fc27dd04e05a20cd9478af684cdcd0987cae4a7d9ff3606d33ad4a3a073` |

The S3 generated `sdkconfig` SHA-256 is
`5fc023160329a1b4201ecbb3c356e36cdd350d9ac24d59bcdbd080511ebdf026`.
Its reproducible ELF and application binary hashes are
`1d358f7ba797c051f589befa28015455acc9d1350cdb039c50d89c1ed2d88bb8`
and `edbcb48dfd930dce33ca60f7b83bc54fdfe952335c70b739045b9e94cf6a86e6`.
The C6 ELF and application binary hashes are
`947db7d9958b09b1c2b7f694b44345fe004ad4fb4d6c3274f121974bf0821bb6`
and `5a36432f8fbeab35cb939f77626bb1a8280bd3d4b28ece3a9f412809a51c2286`.

## Complete target inventory

| Target | Matrix entry | Intent | Attempt state |
|---|---|---|---|
| ESP32-S3 | `esp32s3-reference` | required | attempted twice and classified |
| ESP32-C3 | `esp32c3-compile` | exploratory | attempted and classified |
| ESP32 | `esp32-compile` | exploratory | attempted and classified |
| ESP32-C6 | `esp32c6-compile` | exploratory | attempted and classified |
| ESP32-P4 | `esp32p4-deferred` | deferred | not attempted by policy |
| ESP32-C5 | `esp32c5-deferred` | deferred | not attempted by policy; preview in this lane |
| ESP32-S2 | `esp32s2-excluded` | excluded | not attempted; absent from pinned WAMR targets |
| ESP32-C2 | `esp32c2-excluded` | excluded | not attempted; absent from pinned WAMR targets |
| ESP32-H2 | `esp32h2-excluded` | excluded | not attempted; absent from pinned WAMR targets |
| ESP32-C61 | `esp32c61-excluded` | excluded | not attempted; preview and absent from pinned WAMR targets |

## Reproduction and gates

From a host with Docker or Podman:

```bash
make idf-family-seal-check
WDC_IDF_MATRIX_OUT_DIR=reports/idf-family/if7-rerun \
  tools/run_pinned_idf_matrix.sh
```

The first command checks the matrix, target locks, documentation vocabulary,
input hashes, and complete inventory. The second enters the digest-pinned image
and performs the two S3 builds followed by the C3, ESP32, and C6 probes.

The family gate fails for a missing attempt, wrong image/lane/lock, changed
source, missing or mismatched evidence, S3 reproducibility difference,
infrastructure failure, or unclassified failure. Deferred and excluded entries
must not be attempted. A fresh output path is mandatory; prior evidence is
never overwritten.

## Explicitly deferred work

This seal contains no implementation or qualification of:

- host capability ABI or opcodes for clock, timers, GPIO, storage, sensors,
  entropy, cryptography, or networking;
- WAMR ownership, invocation lifecycle, target memory sizing, or trap behavior;
- FreeRTOS task topology, priorities, queues, execution epochs, or core pinning;
- ISR/callback-to-guest scheduling;
- Wi-Fi, lwIP, TLS, MQTT, HTTP, reconnect, backpressure, or network brokers;
- `@pulse-compute/provider-esp32` lowering, packaging, or capability mapping;
- flashing, booting, serial monitoring, electrical safety, watchdog/reset,
  persistence, power-loss, native OTA, rollback, or hardware-in-loop work; or
- secure boot, flash encryption, eFuse, provisioning, production signing, or
  production signature verification on device.

Adding another ESP-IDF lane is also deferred. It is a separate maintenance and
architecture decision that multiplies configuration, lock, workflow, evidence,
and upgrade surfaces.

## Handoff

IF7 is the stopping point for ESP-IDF family implementation. The recommended
next lane is specification-only host-contract architecture: authority and
safety invariants, WAMR lifecycle ownership, FreeRTOS topology, event/effect
semantics, bounded queues and deadlines, capability taxonomy, network-broker
ownership, target realization boundaries, and only then the later ESP32
provider contract.
