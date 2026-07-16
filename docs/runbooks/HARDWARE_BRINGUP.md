# Hardware Bring-up Plan

This runbook is for the first pass with a real ESP32-S3 board.

## Prerequisites

- ESP32-S3 board, preferably with PSRAM.
- ESP-IDF installed and activated.
- USB serial access.
- Known relay/LED/button wiring that matches or intentionally overrides the example profile.
- Safe test load for any relay output.

## Step 1: Build firmware

```bash
cd firmware
idf.py set-target esp32s3
idf.py build
```

## Step 2: Flash and monitor

```bash
idf.py flash monitor
```

Record:

- reset reason,
- shell version/stage,
- profile validation result,
- safe default application count,
- no-bundle/app-running state.

## Step 3: Safe default electrical check

Before running any app bundle, verify:

| Resource | Expected safe state |
|---|---|
| `relay_1` | off / safe |
| `status_led` | profile-defined safe level |

This is the first critical hardware gate.

## Step 4: Static WASM lifecycle check

Load the static test WASM path if available in firmware build and verify:

- `wdc_module_init` called,
- `wdc_module_on_event` called,
- `wdc_module_health` called,
- `wdc_module_shutdown` called,
- non-OK/trap fixtures stop safely.

## Step 5: Host-call relay check

Use a bundle/case that requests `GPIO_SET relay_1`.

Expected:

- authorized relay write reaches HAL,
- unauthorized status LED write is denied if capability absent,
- invalid resource ID is denied,
- physical action is logged.

## Step 6: Fault-stop check

Run a guest that traps or returns non-OK during probation.

Expected:

- app stops,
- outputs are forced safe,
- fault breadcrumb is recorded,
- further app physical writes are denied.

## Step 7: A/B rollback check

1. Confirm a good bundle in slot A.
2. Install a bad candidate in slot B.
3. Activate slot B.
4. Trigger reset/fault before confirmation.
5. Verify rollback to slot A.

## Step 8: Metadata power-loss check

Interrupt power during metadata write/activation windows.

Expected:

- journal selects last valid committed generation,
- no random slot boots,
- no failed candidate becomes confirmed,
- no-bundle mode is safe if metadata is unrecoverable.

## Step 9: Network mediation check

After Wi-Fi/network implementation is wired:

- permitted MQTT topic prefix succeeds,
- disallowed topic prefix is denied,
- disallowed HTTP method is denied,
- disallowed URL prefix is denied,
- oversized payload is denied,
- disconnected network returns a recoverable status.

## Step 10: Record report

Add a hardware report under:

```text
reports/hardware/
```

Suggested fields:

```text
board model
module flash/PSRAM
ESP-IDF version
firmware git/repo revision
profile hash
bundle hash
observed safe states
rollback outcome
logs
```



## Evidence to retain

For every hardware run, record:

```text
board and module revision
flash and PSRAM configuration
ESP-IDF and WAMR revisions
firmware source revision
profile hash
bundle hash and security counter
observed safe levels
candidate/rollback result
reset and fault breadcrumbs
serial logs
```

Do not treat an undocumented manual run as release evidence.
