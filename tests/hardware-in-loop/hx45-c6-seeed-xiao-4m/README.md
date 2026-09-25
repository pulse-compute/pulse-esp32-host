# HX4.5 Seeed Studio XIAO ESP32C6 harness

This is an isolated, destructive hardware-in-loop image for the named Seeed
Studio XIAO ESP32C6. It is not the production shell and does not use GPIO,
networking, BLE, IEEE 802.15.4, or attached loads.

The image refuses to qualify unless the chip reports ESP32-C6, 4 MB flash, and
no PSRAM. It embeds the exact HX4.5-sealed RISC-V extension and common Wasm,
then runs:

1. one unmeasured allocator warm-up;
2. five measured inspect/load/init/start/WAMR/event/effect/quiesce/deinit/unload
   cycles with exact internal-heap recovery and free/largest-block floors;
3. an unknown-event rejection through the real target bridge;
4. a real WAMR `unreachable` event trap; and
5. an expired quiescence deadline followed by an authoritative software reset
   and retained harness-breadcrumb check.

Both the extension task and the WAMR-driving pthread have explicit lifetime
stack-watermark floors. The raw ESP-IDF `app_main` task only creates and joins
that 16 KiB worker, matching the pinned WAMR ESP-IDF platform's thread-identity
contract.

Use `tools/build_hx45_c6_xiao.py`; the source template deliberately contains
no generated ELF byte array. The Make target supplies the exact sealed ELF from
`fixtures/` rather than rebuilding it with the ambient compiler. See
[`docs/HX4_5_C6_XIAO_HARDWARE.md`](../../../docs/HX4_5_C6_XIAO_HARDWARE.md)
for the complete short run.

HX5b reuses these sealed bytes through the opt-in `--hx5b-pressure` builder
flag (or `make hx5b-c6-xiao-build`). It adds eight complete host-queue
fill/drain rounds and 128 target event/effect latency samples during measured
cycle one. The ordinary HX4.5 target does not define that mode.
