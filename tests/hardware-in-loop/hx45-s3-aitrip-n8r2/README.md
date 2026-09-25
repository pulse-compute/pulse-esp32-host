# HX4.5 AITRIP ESP32-S3 N8R2 harness

This is an isolated, destructive hardware-in-loop image for the named AITRIP
ESP32-S3-DevKitC-1 N8R2 board. It is not the production shell and does not use
GPIO, networking, BLE, LoRa, or attached loads.

The image refuses to qualify unless the chip reports ESP32-S3, 8 MB flash, and
2 MB PSRAM. It embeds the exact HX4.5-sealed Xtensa extension and common Wasm,
then runs:

1. one unmeasured allocator warm-up;
2. five measured inspect/load/init/start/WAMR/event/effect/quiesce/deinit/unload
   cycles with exact heap recovery plus internal/PSRAM free and largest-block
   floors;
3. an unknown-event rejection through the real target bridge;
4. a real WAMR `unreachable` event trap; and
5. an expired quiescence deadline followed by an authoritative software reset
   and retained harness-breadcrumb check.

Both the extension task and the WAMR-driving pthread have explicit lifetime
stack-watermark floors. The raw ESP-IDF `app_main` task only creates and joins
that 16 KiB worker, matching the pinned WAMR ESP-IDF platform's thread-identity
contract.

Use `tools/build_hx45_s3_aitrip.py`; the source template deliberately contains
no generated ELF byte array. The Make target supplies the exact sealed ELF from
`fixtures/` rather than rebuilding it with the ambient compiler. See
[`docs/HX4_5_S3_AITRIP_HARDWARE.md`](../../../docs/HX4_5_S3_AITRIP_HARDWARE.md)
for the complete short run.

HX5b reuses these sealed bytes through the opt-in `--hx5b-pressure` builder
flag (or `make hx5b-s3-aitrip-build`). It adds eight complete host-queue
fill/drain rounds and 128 target event/effect latency samples during measured
cycle one. The ordinary HX4.5 target does not define that mode.
