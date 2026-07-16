# wdc_events

Event queue and event envelope encoding.

Implemented behavior:

- deterministic-CBOR event envelope;
- event IDs and timestamps;
- optional resource ID and payload;
- queue overflow/dropped-count tracking;
- runtime dispatch into `wdc_module_on_event`;
- active `max_event_bytes` enforcement before dispatch.
