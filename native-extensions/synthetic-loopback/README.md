# HX3 synthetic lifecycle extension

This target-native ELF preserves the two-stage HX2 admission contract and adds
the bounded HX3 lifecycle proof on ESP32-S3/Xtensa and ESP32-C6/RISC-V. It
contains one fixed
`.pulse_ext_meta` record, the canonical `pulse_extension_entry_v1` export, one
synthetic event identity (`test:tick` in evidence), and one synthetic operation
identity (`test:echo` in evidence).

`start` creates one static 4,096-byte-stack task and one static queue of four
64-byte items. The task reports health, drains on quiescence, self-deletes, and
uses a FreeRTOS deletion callback so the extension does not release its static
TCB or queue before the kernel confirms cleanup. A deadline miss fails closed
and requires host reset.

The exact two Pulse-service and nine FreeRTOS imports are target-refinement
dependencies. There is no dynamic allocation, GPIO, network, BLE, storage,
RAX, or firmware-OTA import. The echo operation remains unsupported until HX4
owns effect completion, and no target runtime claim is made without hardware.
