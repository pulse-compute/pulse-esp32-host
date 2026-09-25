# HX4.5 AITRIP ESP32-S3 N8R2 hardware run

## Scope

This is the named-board stop after HX4.5. The selected board is the AITRIP
ESP32-S3-DevKitC-1 carrying an `ESP32-S3-WROOM-1-N8R2` module: ESP32-S3, 8 MB
flash, and 2 MB quad PSRAM.

That N8R2 mapping follows Espressif's
[official DevKitC-1 variant table](https://documentation.espressif.com/api/resource/path/docs/projects/esp-dev-kits/en/latest/esp32s3/esp32-s3-devkitc-1/user_guide.html):
8 MB Quad SPI flash and 2 MB Quad SPI PSRAM. The harness still measures both
capacities on the attached device rather than trusting the product label.

The lane is deliberately separate from the canonical 16 MB firmware
realization. Passing it proves target execution of the sealed extension spine
on this named 8 MB / 2 MB board. It does not silently qualify the 16 MB
partition layout.

The canonical S3 image leaves only a nonzero sliver of dedicated IRAM after
static linking, so the isolated named-board lane enables the pinned loader's
supported ESP32-S3 PSRAM execution mode. ELF text is stored in PSRAM and
called through the loader's instruction-cache alias; relocated lifecycle
function pointers receive the same conversion. This is not a relaxation of
ELF inspection, import allowlisting, or descriptor range checks, and it does
not alter the frozen cross-family proof realizations.

The pinned loader also packs loaded data sections contiguously without
restoring every input section's alignment. The sealed ELF's 34-byte `.rodata`
therefore places its otherwise 4-byte-aligned `.data.rel.ro` descriptor at a
two-byte runtime address. The host first bounds the complete returned
descriptor inside loader-owned readable memory, copies exactly 160 bytes with
`memcpy` into aligned candidate-owned storage, and validates only that copy.
Raw ELF alignment requirements and all descriptor contents/function ranges
remain fail-closed.

Physical execution then established a second, independent loader boundary:
the loader's PSRAM adapter routed both executable and writable allocations to
PSRAM. That made the extension-owned static FreeRTOS TCB, queue control block,
and stack fail ESP-IDF's internal-memory checks at `extension-start`. The
isolated lane wraps `esp_elf_malloc`: executable requests retain
`MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT`, while writable `.data/.bss/rodata`
requests use `MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT`.

The first internal-RAM run removed the TCB rejection and exposed the complete
alignment consequence: `xQueueGenericCreateStatic` received its control block
at an address ending in `0x82`, and the first spinlock compare-and-set raised
`LoadStoreAlignment`. Before relocation, the host now models the pinned
loader's exact unpadded order—`.data`, `.rodata`, `.data.rel.ro`, `.bss`—and
solves for one allocation-base residue satisfying every section's declared
power-of-two alignment. For the sealed ELF, the packed size is 6,978 bytes,
the maximum alignment is 16, and the required base residue is 14 modulo 16.
That places `.data.rel.ro` on a four-byte boundary and `.bss` on a sixteen-byte
boundary without changing the ELF. Incompatible layouts fail before
relocation. The wrapper retains the underlying aligned allocation and the
paired `esp_elf_free` wrapper releases that original pointer on unload.

The exact ELF and its direct FreeRTOS import contract remain unchanged.
External task stacks are not enabled, and the canonical no-PSRAM realizations
do not compile these wrappers.

Physical execution with that alignment repair passed `extension-start` and
confirmed that the extension event reached the host. It then exposed a
separate WAMR/PSRAM cache boundary. The pinned WAMR ESP-IDF port selects
`MALLOC_CAP_SPIRAM` for every `os_mmap` allocation when S3 PSRAM support is
enabled, including the interpreter's writable linear memory. The common guest
requested a 128 KiB mapping immediately after the PSRAM-resident native text;
the port faulted in its initial `memset` with a data-cache writeback error.

The isolated lane now wraps that mmap boundary as well. Executable mappings
remain delegated unchanged to WAMR, while non-executable mappings use explicit
`MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT` storage. The wrapper preserves WAMR's
eight-byte alignment and hidden original-pointer prefix, so the unmodified
`os_munmap`/`os_free` path remains paired. The physical run reported 350,343
bytes of internal free heap and a 253,952-byte largest internal block before
WAMR load, so the 131,072-byte mapping fits the observed board state. The
existing per-stage free/largest-block floors and exact recovery checks remain
authoritative; this observation is not a general production sizing claim.

That repair allowed WAMR to instantiate the common guest and report `static
wasm payload loaded`. The next cache writeback failure surfaced while printing
the passing `common-wasm-load` case. This was not another large-allocation
failure: the runtime had passed the flash-resident `const` Wasm array directly
to `wasm_runtime_load` by casting away constness. WAMR 2.4.0's public contract
requires a writable module buffer because the loader may modify it for
footprint and performance, and requires that buffer to remain referenceable
until `wasm_runtime_unload` ([pinned API contract](https://github.com/bytecodealliance/wasm-micro-runtime/blob/WAMR-2.4.0/core/iwasm/include/wasm_export.h#L568-L591)).
The later `printf` merely evicted the dirty flash cache line and exposed the
invalid write.

The runtime now copies the exact verified Wasm bytes into a small explicit
internal/8-bit allocation before calling WAMR. The copy is retained with the
module, unloaded first, and released immediately afterward. The immutable
source artifact, its SHA-256 identity, and the guest memory declaration remain
unchanged. This ownership rule applies to every ESP-IDF runtime load rather
than only this board, because it closes the WAMR API contract rather than
changing target behavior.

The first guest lifecycle call then exposed the pinned ESP-IDF port's host
thread contract. Its `os_self_thread` implementation calls `pthread_self` and
explicitly notes that an ordinary `xTaskCreate` task is insufficient
([pinned platform source](https://github.com/bytecodealliance/wasm-micro-runtime/blob/WAMR-2.4.0/core/shared/platform/esp-idf/espidf_thread.c)).
ESP-IDF invokes `app_main` as a native FreeRTOS task, so WAMR asserted while
recording the execution environment's thread identity. The pinned WAMR
ESP-IDF example resolves the same boundary by creating and joining a pthread
around its runtime control flow
([pinned product-mini entrypoint](https://github.com/bytecodealliance/wasm-micro-runtime/blob/WAMR-2.4.0/product-mini/platforms/esp-idf/main/main.c)).

Both the production firmware entrypoint and this isolated harness now follow
that pattern. The raw `app_main` task creates one joinable 16 KiB pthread and
waits for it; all WAMR initialization, module lifetime, guest calls, and
teardown remain synchronous on that single worker. This does not forge a
pthread identity for a FreeRTOS task, add a cross-thread runtime dispatcher, or
change the sealed guest. The worker stack is internal host memory and is part
of the harness's measured heap baseline; its live high-water mark remains
subject to the existing 1 KiB driver-stack floor.

## Prerequisites

- the module marking reads `ESP32-S3-WROOM-1` with an `N8R2` suffix;
- a data-capable USB cable connected to the board's USB-to-UART port;
- a Linux x86-64, macOS x86-64, or macOS arm64 build/flash host;
- ESP-IDF v5.4.4 at commit
  `296b6eab9445fd720e71aecab961e2d3fbca9944`, activated in the shell; and
- no relay, external load, or peripheral wiring attached.

The flash step replaces the board's current partition table and application.

The builder embeds the exact HX4.5-sealed extension ELF shipped under the HIL
fixture directory; it does not rebuild that ELF with the ambient host compiler.
The HIL firmware itself may be built on the supported macOS hosts above, but
that target-runtime convenience does not broaden or replace the canonical
Linux x86-64 reproducibility lane. The exact IDF version, source commit,
dependency lock, firmware sources, ELF, and Wasm remain fail-closed.

## Shortest complete run

From the repository root:

```bash
. /path/to/esp-idf/export.sh
idf.py --version
git -C "$IDF_PATH" rev-parse HEAD

REPO_ROOT="$PWD"
RUN_DIR="$REPO_ROOT/reports/hardware/hx45-aitrip-n8r2-001"  # must not exist yet
PORT=/dev/ttyUSB0  # use /dev/ttyACM0 if that is the enumerated UART

HX_AITRIP_OUT_DIR="$RUN_DIR" make hx45-s3-aitrip-build

cd "$RUN_DIR/project"
idf.py -B "$RUN_DIR/build" -p "$PORT" flash
idf.py -B "$RUN_DIR/build" -p "$PORT" monitor \
  2>&1 | tee "$RUN_DIR/serial.log"
```

For the S3 native USB-Serial/JTAG port, enter download mode by holding `BOOT`
while tapping `EN` if automatic flashing cannot connect.  After flashing,
start the monitor first and then tap `EN` once so the complete first pass is
captured.  Do not touch either button after `PULSE_HX45_BEGIN`; leave the
monitor attached across the harness-initiated software reboot. Stop it with
`Ctrl+]` only after `PULSE_HX45_FINAL` appears.

Then evaluate from the repository root:

```bash
cd "$REPO_ROOT"
HX_AITRIP_OUT_DIR="$RUN_DIR" \
HX_AITRIP_MODULE_MARKING="ESP32-S3-WROOM-1 N8R2" \
  make hx45-s3-aitrip-evaluate
```

The evaluator exits zero only when the build identity, physical memory facts,
five clean cycles, target WAMR trap, reset-required latch, software reset, and
retained breadcrumb all pass with no panic, watchdog, brownout, assertion, or
heap-corruption signature.

The harness also enforces conservative lane floors at every stressed sample:
8 KiB internal free heap, a 4 KiB largest internal block, 512 KiB free PSRAM,
a 256 KiB largest PSRAM block, 512 bytes of extension-task stack headroom, and
1 KiB of main-task stack headroom. These are stop/go floors for this isolated
test, not production sizing claims; the report retains the observed minima for
later tuning.

Before flashing, the builder also requires the 2 MiB test application slot to
fit, at least 1 KiB of link-reported internal RAM to remain, and a nonzero
dedicated-IRAM remainder. Runtime measurements remain authoritative for live
headroom; those static link floors only reject an already-overfull image. The
dedicated-IRAM remainder is still a firmware-growth warning, but it is no
longer the ELF text-allocation pool in this isolated lane.

The hybrid ELF allocation deliberately consumes internal RAM for the loaded
writable image, including the extension's statically provisioned 4 KiB task
stack and FreeRTOS control blocks. That allocation must recover on every clean
unload and remains covered by the existing 8 KiB free / 4 KiB largest-block
internal floors.

The WAMR linear-memory policy also consumes 128 KiB of the observed internal
largest block while a common guest instance is active. It must recover during
every teardown and may not bypass the same internal free/largest-block floors.
The writable module copy adds only the exact module byte length (306 bytes for
the common HX4 guest) and is covered by the same recovery evidence.

The 16 KiB pthread driver stack is allocated before the first reported heap
sample and persists for the run. It is therefore a fixed part of the named
lane's available internal-memory baseline, while `PULSE_HX45_MAIN_STACK`
measures that actual pthread's remaining stack headroom.

## Expected final marker

```text
PULSE_HX45_FINAL {"status":"PASS",...,"target_runtime":"NAMED_BOARD_OBSERVED"}
```

Retain the entire run directory. Do not reduce the evidence to a copied final
line.

Also retain one clear photo of the board and module marking. Firmware can
measure the chip and memory, but it cannot authenticate the AITRIP PCB vendor;
that part of named-board identity remains operator-attested.

`RUN_DIR` must be absent before the build and its `evaluation/` directory must
be absent before evaluation. Use a new numeric suffix rather than overwriting
an earlier run. Do not create `RUN_DIR` yourself. If the builder reports that
the directory is not empty, select the next unused suffix (for example,
`hx45-aitrip-n8r2-002`) and rerun the build.

## Explicitly deferred

This run does not touch or qualify GPIO, the expansion adapter, Wi-Fi,
networking, BLE, LoRa, native firmware OTA, Pulse application slots, flash
power-loss behavior, secure boot, flash encryption, production provisioning,
the canonical 16 MB partition layout, or ESP32-C6 hardware.
