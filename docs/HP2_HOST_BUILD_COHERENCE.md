# HP2 host profile, build coherence, lock, and fingerprint

## Result

HP2 separates the compatibility decision from the firmware realization that
implements it. The host now has six distinct artifacts:

1. a board identity and its observed physical resources;
2. a host capability/resource profile;
3. normalized application target intent;
4. a host build plan;
5. an exact resolved host build lock; and
6. a compact running-host fingerprint derived from that lock.

The host-synthetic qualifier closes as `HOST_BUILD_COHERENCE_PROVEN`.
No firmware was built or flashed and no hardware was observed during HP2.

The machine-readable seal is
[`PULSE-ESP32-007-host-build-coherence.json`](../specs/PULSE-ESP32-007-host-build-coherence.json).

## Why the split matters

These artifacts answer different questions:

| Artifact | Question | Authority |
|---|---|---|
| Board identity | What named physical resources are present? | Host board catalog, backed by the retained HP0 observation. |
| Host profile | Which host contracts and HP1 resource limits does this realization provide? | Host firmware. |
| Target intent | What compatibility and bounded resources does the application require? | Future ESP32 provider normalization, not Pulse core internals. |
| Build plan | Which supported board/profile/environment should realize that intent? | Host builder selection. |
| Build lock | Which exact source, IDF, target configuration, partition input, and component graph must be rebuilt? | Explicit lock resolution. |
| Running fingerprint | What exact lock and compatibility surface is this booted host reporting? | Build-derived firmware record. |

The application does not choose task priorities, HP1 reserves, an IDF target,
partition layout, loader behavior, or managed-component versions. The host
profile does not become application configuration. A build lock does not
become a board identity.

## Build coherence rather than a global hard pin

The current supported catalog contains one exact build environment:

| Field | Value |
|---|---|
| Lane | `idf-5.4.4` |
| ESP-IDF | `v5.4.4` |
| Source commit | `296b6eab9445fd720e71aecab961e2d3fbca9944` |
| Platform | `linux/amd64` |
| OCI image | `espressif/idf@sha256:8d1846f61ff8db00ba6530501f90bf43604d923072a616c806fef8e85a88ed82` |
| WAMR | `2.4.0~1`, component hash pinned |
| ELF loader | `1.3.2`, component hash pinned |
| CMake utilities | `0.5.3`, component hash pinned |

That is not a claim that all future hosts must remain on IDF 5.4.4. A future
catalog may add a separately qualified environment. The invariant is that one
resolved build uses one coherent exact set and that its lock remains replayable.

`replay-lock` validates the existing lock directly against every recorded file
and source-tree hash. It does not perform dependency selection and reports
`silent_upgrade=false`. A new lock requires the explicitly named
`resolve-new-lock` operation and fresh output paths. Existing files are never
overwritten by the resolver.

## Named boards and host profiles

HP2 admits only the two boards already observed by HP0:

| Board | Physical resources | Host profile |
|---|---|---|
| `aitrip-esp32s3-devkitc-1-n8r2` | ESP32-S3, 8 MiB flash, 2 MiB quad PSRAM | `esp32s3-psram-slots-v1` |
| `seeed-xiao-esp32c6-4m` | ESP32-C6, 4 MiB flash, no PSRAM | `esp32c6-portable-slots-v1` |

The vendor/model identity remains operator-attested, matching HP0. It is not a
cryptographic board identity.

Both current host profiles expose ABI 1.0 and the implemented Wasm,
event/effect, trusted native-refinement, and HP3 application-slot contracts.
They bind the exact HP1 resource-authority and native-extension ABI hashes.
They do not claim a Pulse HTTP service, MQTT, or production transport.

The checked-in board defaults still reproduce the named HX5b harness inputs.
HP3 additively extends their factory-only partition prefix with `wasm_a`,
`wasm_b`, and `wasm_meta`; the exact HP2 locks and fingerprints were explicitly
refreshed to bind that current layout. The retained HIL files remain unchanged
historical evidence.

## Provider-facing target intent

[`portable-loopback-v1.json`](../examples/host-intents/portable-loopback-v1.json)
is the normalized contract witness. It declares:

- allowed named boards and target families;
- a host ABI range;
- required host capabilities;
- portable versus optional target-optimized placement; and
- bounded guest, stack, network, capability, native-refinement, transition,
  largest-allocation, and optional optimization memory.

The target intent contains no ESP-IDF, sdkconfig, partition, PSRAM, or loader
field. Those are host-builder concepts. A future external ESP32 provider may
normalize ordinary Pulse configuration into this artifact, but HP2 does not
implement that provider or add an ESP32 concept to Pulse core.

## Plan and lock behavior

The plan has two separately hashed parts:

- the request selection records the application intent and compatibility
  result; and
- the host plan records only the selected board/profile/environment and build
  inputs.

Changing a compatible application changes the complete plan hash but not the
host-plan hash. The exact host build lock binds the host-plan hash, not an
application artifact. This is what permits a prebuilt host profile to serve
many compatible Pulse applications without rebuilding firmware.

A lock records:

- the exact board and host profile;
- the exact IDF release, source commit, container digest, and platform;
- every resolved component version and registry component hash;
- exact sdkconfig, partition, component lock, ABI, board, profile, and HP1
  authority file hashes; and
- deterministic source-tree hashes for `firmware/components`,
  `firmware/main`, and `native-sdk`.

The generated C fingerprint source is excluded from the component-tree digest
because it contains the build-lock hash and would otherwise create a circular
lock → fingerprint → source-tree dependency. It is not an unsealed escape:
qualification regenerates the file from both locks and requires byte equality.

## Running fingerprint

Each exact lock produces one JSON fingerprint and one fixed-width 196-byte C
record. The record contains:

- target and physical flash/PSRAM quantities;
- host ABI and capability mask;
- HP1 control-profile identity and resource limits;
- SHA-256 digests for board identity, host-profile identity, build lock, and
  semantic compatibility; and
- a CRC-32 over the complete record.

The CRC detects malformed or corrupted fixed records. It is not a signature or
remote attestation mechanism. Trust still begins in the verified native host
image and its future secure-boot policy.

When the intent matches the running semantic surface, the resolver reports
`APP_ONLY_DEPLOYMENT`. A different or incompatible running surface reports
`HOST_BUILD_PLAN_REQUIRED`; it never silently rebuilds or upgrades the host.

## Prelaunch enforcement

`wdc_host_prelaunch_check` evaluates, in order:

1. fixed fingerprint structure, CRC, target/profile pairing, and resource
   coherence;
2. application target and host ABI compatibility;
3. required host capabilities;
4. portable versus explicit target-optimized placement; and
5. HP1 resource admission using the live internal-free, largest-block, and
   optional target-memory snapshot.

The function always returns with `application_code_launched=0`. A caller may
enter application code only after an accepted result. HP3 now binds its fixed
slot artifact header to these requirements and calls this gate before
lifecycle entry.

The portable C6 witness requires 184,320 bytes total internal free and a
98,304-byte largest internal block. The S3 optimization witness explicitly
requests 262,144 bytes of target-optimized memory and retains a 131,072-byte
floor, requiring 393,216 bytes free. The same request is rejected by C6.

The retained HX5b S3 minimum largest-block observation was 96,256 bytes—below
the conservative HP1 launch floor. HP2 does not reinterpret that old physical
observation as an accepted launch for the current tree.

## Operations

Create a plan without mutating locks:

```bash
python3 -B tools/resolve_host_build.py plan \
  --intent examples/host-intents/portable-loopback-v1.json \
  --board seeed-xiao-esp32c6-4m
```

Check app-only compatibility against a running fingerprint:

```bash
python3 -B tools/resolve_host_build.py check-running \
  --intent examples/host-intents/portable-loopback-v1.json \
  --fingerprint firmware/host-build/fingerprints/seeed-xiao-esp32c6-4m.json
```

Replay an exact lock without resolution:

```bash
python3 -B tools/resolve_host_build.py replay-lock \
  --lock firmware/host-build/locks/seeed-xiao-esp32c6-4m.json \
  --fingerprint firmware/host-build/fingerprints/seeed-xiao-esp32c6-4m.json
```

Run the contract and qualifier:

```bash
make check-hp2
HP2_OUT_DIR=reports/host-build/hp2-local make host-build-qualify
```

## Synthetic seal and claim boundary

The seal covers:

- two board identities and two HP1 host profiles;
- two deterministic plans, exact locks, and running fingerprints;
- exact generated-C reproduction;
- eight C prelaunch cases with no application entry;
- eight Python negative cases spanning lane drift, unknown capability, locked
  input drift, fingerprint tampering, C6 optimization, wrong target, plan path
  substitution, and invalid ABI range; and
- preservation of the HP1 resource authority, native-extension ABI, and common
  Wasm identities.

HP2 is `HOST_EXECUTED_SYNTHETIC_ONLY`. It does not claim a current firmware
build, physical S3/C6 execution, remote attestation, provider integration, or
host-firmware OTA.

## Handoff

HP2 closes the configuration/build-identity unit. HP3 now uses that authority
for two Pulse application slots without mixing application replacement with
host-firmware replacement. HP3.5 power-loss adversarial work, RAX, protected
administration, production transport, MQTT, provider ergonomics, and
host-firmware OTA remain deferred to their named passes.
