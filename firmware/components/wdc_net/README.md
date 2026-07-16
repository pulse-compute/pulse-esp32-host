# wdc_net

Native network mediation for app-level network behavior.

WASM app logic never receives raw Wi-Fi, TCP, TLS, MQTT, or HTTP handles. It may request only contract-level operations:

```text
WDC_OP_NET_STATUS
WDC_OP_MQTT_PUBLISH
WDC_OP_MQTT_SUBSCRIBE
WDC_OP_HTTP_REQUEST
```

Implemented through R9:

- native mediator state and request IDs;
- device-profile network resource checks;
- MQTT publish topic-prefix enforcement;
- MQTT subscribe prefix/filter enforcement;
- HTTP URL-prefix and method allowlist enforcement;
- payload-size checks;
- event/status constants in guest SDKs.

Real Wi-Fi/MQTT/HTTP transport remains future integration work and must remain behind this mediator.
