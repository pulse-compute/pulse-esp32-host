# wdc_net

Native network mediation for application-level network behavior. Wi-Fi, TLS,
credentials, raw sockets, and transport policy remain owned by the host.

The original outbound mediator remains available through policy-checked calls:

```text
WDC_OP_NET_STATUS
WDC_OP_MQTT_PUBLISH
WDC_OP_MQTT_SUBSCRIBE
WDC_OP_HTTP_REQUEST
```

It enforces device-profile resources, MQTT topic prefixes, HTTP URL/method
allowlists, fixed payload bounds, and host-owned connection state.

HP5 adds the paired `WDC_OP_HTTP_RESPOND` hook without giving this component
listener or administration authority. The host-private `wdc_http` component
owns the inbound Pulse HTTP service. Its `wdc_http_platform_espidf.c` adapter
it owns station-mode Wi-Fi, reconnect policy, server certificate/private-key
pointers, and two independently bounded HTTPS listeners. The application
listener defaults to port 443 and protected administration to 8443; each has
its own server task, control port, parser, and three-socket cap. Application
traffic therefore cannot occupy the administration listener or its request
storage.

`wdc_http/wdc_http_service.c` supplies the allocation-free normalizer and fixed route
table. Application routes must be exact `GET` or `POST` paths below
`/pulse/v1/app/`; attempts to register `/pulse/v1/admin/` are rejected. A
matched request is encoded as `WDC_EVENT_HTTP_REQUEST` and delivered through
the existing `wdc_module_on_event` runtime path. During that handler only, the
guest may issue one `WDC_OP_HTTP_RESPOND`. The first bounded response wins;
duplicates, wrong request IDs, late responses, and responses outside an active
HTTP event fail closed. A handler may return no body, producing 204.

The reserved administration routes are fixed:

```text
POST   /pulse/v1/admin/session/begin
POST   /pulse/v1/admin/session/finish
DELETE /pulse/v1/admin/session
POST   /pulse/v1/admin/command
GET    /pulse/v1/admin/terminal
```

They do not implement another administration machine. Session begin/finish
uses HP4's replaceable authorizer and authenticated-entry record. Command
bodies use HP4's existing length-prefixed normalizer, then HP4 alone owns
replay, deadlines, control admission, execution, audit, and the retained
terminal. Client loss is counted but does not roll back an application or
cancel accepted administration; HP4 `ABORT` and absolute deadlines remain the
only cancellation authorities.

The host-native qualifier exercises the actual parser, common runtime handler,
paired response effect, external authenticated-entry path, HP4 command and
terminal lifecycle, saturation isolation, deadline/cancellation behavior, and
explicit response-loss accounting. It does not claim an ESP-IDF target build,
TLS handshake, Wi-Fi association, physical board run, production
authenticator, credential provisioning, or key lifecycle; those observations
belong to HP5.5.
