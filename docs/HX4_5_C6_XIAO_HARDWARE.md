# HX4.5 Seeed Studio XIAO ESP32C6 hardware run

## Scope

This is the second named-board HX4.5 hardware gate. It targets the Seeed Studio
XIAO ESP32C6 with 4 MB flash and no PSRAM. Seeed's
[board reference](https://wiki.seeedstudio.com/xiao_esp32c6_getting_started/)
identifies the ESP32-C6, 512 KB SRAM, 4 MB flash, and USB-C interface.

The lane is isolated from both the AITRIP S3 test and the canonical compile-only
C6 realization. It embeds the exact accepted RISC-V extension ELF and common
Wasm, then requires one warm-up and five measured inspect/load/start/round-trip/
quiesce/deinitialize/unload cycles, exact internal-heap recovery, a real WAMR
trap, and a reset-required path verified after software reboot.

The XIAO has no PSRAM safety valve. The builder therefore requires at least
160 KiB of link-reported internal RAM to remain: the guest declares a 128 KiB
linear memory and the extra 32 KiB is a fail-fast guard. Physical free heap,
largest block, extension stack, driver stack, and queue high-water measurements
remain authoritative. A build failure at this floor is useful boundary evidence,
not permission to weaken the gate.

The first physical run reached relocation and then faulted at the relocated
entry address. `elf_loader` 1.3.2's unified C6 path requested an executable
segment but discarded that capability, while ESP-IDF's default PMP IRAM/DRAM
split made ordinary heap RW/NX. This gate now disables the fixed split and
wraps the loader allocation to require executable, internal, cache-aligned
memory. Re-enabling the split is a build-validation failure, and an allocator
which cannot satisfy executable intent returns a loader error instead of
deferring failure to an indirect call.

The board marking is operator-attested. Firmware can verify the ESP32-C6 target,
4 MB physical flash, and absence of PSRAM, but cannot electronically authenticate
the PCB vendor.

## Prerequisites

- a Seeed Studio XIAO ESP32C6 whose board marking reads `XIAO ESP32C6`;
- a data-capable USB-C cable with no peripheral wiring attached;
- ESP-IDF v5.4.4 at commit
  `296b6eab9445fd720e71aecab961e2d3fbca9944`, activated in the shell; and
- a Linux x86-64, macOS x86-64, or macOS arm64 build/flash host.

The flash step replaces the board's current partition table and application.
The XIAO exposes the ESP32-C6 integrated USB Serial/JTAG peripheral; ESP-IDF
documents it as supporting console, flashing, and JTAG over the same USB link
([ESP-IDF USB Serial/JTAG guide](https://docs.espressif.com/projects/esp-idf/en/stable/esp32c6/api-guides/usb-serial-jtag-console.html)).

## Shortest complete run

From the repository root:

```bash
. /path/to/esp-idf/export.sh
idf.py --version
git -C "$IDF_PATH" rev-parse HEAD

REPO_ROOT="$PWD"
RUN_DIR="$REPO_ROOT/reports/hardware/hx45-c6-xiao-001"  # must not exist
HX_XIAO_OUT_DIR="$RUN_DIR" make hx45-c6-xiao-build

ls /dev/cu.usbmodem* /dev/cu.usbserial* 2>/dev/null
PORT=/dev/cu.usbmodemNNNN

"$IDF_PATH/tools/idf.py" -B "$RUN_DIR/build" -p "$PORT" flash
"$IDF_PATH/tools/idf.py" -B "$RUN_DIR/build" -p "$PORT" monitor \
  2>&1 | tee "$RUN_DIR/serial.log"
```

If automatic download mode does not connect, hold `BOOT` while connecting USB,
or hold `BOOT`, tap `RESET`, and release `BOOT`; these are Seeed's documented
bootloader-recovery sequences. After flashing, start the monitor and tap `RESET`
once so the complete first boot is captured. Do not touch either button after
`PULSE_HX45_BEGIN`. Leave the monitor attached across the harness-initiated
software reboot, and stop with `Ctrl+]` only after `PULSE_HX45_FINAL` appears.

Then evaluate from the repository root:

```bash
cd "$REPO_ROOT"
HX_XIAO_OUT_DIR="$RUN_DIR" \
HX_XIAO_BOARD_MARKING="XIAO ESP32C6" \
  make hx45-c6-xiao-evaluate
```

The expected final line is:

```text
PULSE_HX45_FINAL {"status":"PASS",...,"target_runtime":"NAMED_BOARD_OBSERVED"}
```

Retain the complete run directory and one clear board photo. A copied final
line is not sufficient evidence. Use a fresh numeric suffix for every attempt;
both the run directory and its later `evaluation/` directory must be absent or
empty when their respective commands start.

After a passing evaluation, package the evidence separately from source:

```bash
HX_XIAO_OUT_DIR="$RUN_DIR" make package-xiao-hardware-evidence
```

## Stop/go floors

- build: 2 MiB application slot and 160 KiB link-reported internal RAM remaining;
- runtime: 8 KiB internal free heap and a 4 KiB largest internal block;
- extension task: 512 bytes minimum stack headroom;
- driver pthread: 1 KiB minimum stack headroom; and
- extension queue: high-water between one and four entries.

These are qualification floors for this isolated gate, not production sizing
claims. The retained report records the actual minima.

## Explicitly deferred

This run does not qualify GPIO, Wi-Fi, BLE, IEEE 802.15.4, I2C/SPI, OTA,
power-loss behavior, secure boot, flash encryption, production provisioning,
or multi-extension residency. It proves only the sealed single-extension plus
common-Wasm spine on this named 4 MB/no-PSRAM board.
