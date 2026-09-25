# wdc_events

Event queue and event envelope encoding.

Implemented behavior:

- deterministic-CBOR event envelope;
- event IDs and timestamps;
- optional resource ID and payload;
- queue overflow/dropped-count tracking;
- runtime dispatch into `wdc_module_on_event`;
- active `max_event_bytes` enforcement before dispatch.

HX4 reuses this same queue for candidate-attributed native extension events.
The extension service copies a bounded payload into the queue; the extension
bridge is the sole HX4 consumer and continues through `wdc_runtime` rather than
calling Wasm directly.
