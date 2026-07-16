# wdc_ota

WASM bundle slot and metadata storage abstraction.

Implemented through R9:

- host-testable slot image registration/read paths;
- ESP-IDF-facing slot read abstraction for `wasm_a` and `wasm_b`;
- metadata read/write API;
- two-record journaled metadata with generation selection and commit markers.

The metadata journal reduces ambiguity after interrupted writes, but real power-loss behavior still needs validation on ESP32-S3 flash.
