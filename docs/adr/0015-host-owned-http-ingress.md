# ADR 0015 — Host-owned HTTP ingress

## Status

Accepted for HP5; physical realization is deferred to HP5.5.

## Context

HP4 sealed one host-private administration authority but intentionally left
network transport absent. HP5 needs a minimal web path for Pulse application
requests and protected remote administration without making HTTP, TLS, a Wasm
application, or application-facing network mediation into a second security,
command, update, recovery, or boot authority.

Network ingress also creates a resource-isolation problem. Application traffic
must not consume the parser, socket, task, or completion capacity needed to
recover or administer a device when the application is faulty or saturated.

## Decision

The host owns Wi-Fi, TLS, sockets, reconnect policy, credentials, certificate
and private-key references, HTTP parsers, route registration, and response
transmission. Two separately bounded HTTPS listeners reserve independent
application and administration lanes.

Application routes are exact, immutable `GET` or `POST` paths under
`/pulse/v1/app/`. They dispatch one bounded `WDC_EVENT_HTTP_REQUEST` through
the common Wasm event handler. During the active event, the guest may issue at
most one bounded `WDC_OP_HTTP_RESPOND`; first response wins. The application
cannot register in or shadow `/pulse/v1/admin/`.

Administration routes are fixed host routes. Transport processing supplies
bounded bytes and a host-observed channel binding to the existing replaceable
HP4 authenticated-entry seam. The existing HP4 serial-frame normalizer,
session, replay, rate, deadline, HP1 command ownership, terminal, audit,
update, recovery, and HP3 reboot paths remain authoritative. There is no
second HTTP administration state machine.

Malformed, oversized, slow, disconnected, unauthorized, stale, replayed, and
saturated input rejects before HP4 acceptance mutation. Network response loss
is observable but cannot roll back an application or cancel an accepted HP4
command.

`wdc_http` owns this host-private orchestration and may depend on `wdc_admin`.
`wdc_net` remains application-facing and cannot depend on administration; it
offers only a narrow paired-response hook for the active host service.

## Consequences

- Credentials, TLS state, sockets, parser storage, and route authority never
  enter the portable guest or native-extension SDK.
- Application traffic cannot occupy the administration listener's fixed
  parser or socket reserve.
- HP1 remains resource and priority authority; HP3 remains durable boot and
  application-slot authority; HP4 remains administration authority.
- HTTP application handling uses the common event path instead of introducing
  a web-specific application runtime.
- A target build or source-complete adapter is not evidence of Wi-Fi, TLS, or
  physical behavior. Those observations require HP5.5.

## Deferred

HP5.5 owns exact dual-board build, Wi-Fi/TLS/application/admin/update/recovery
execution and resource-floor evidence. HP6 provider ergonomics, HP7/HP7.5
MQTT, HP8 conformance, RAX, host-firmware OTA, partition redesign, broad
peripherals, fleet functions, attestation, and production key lifecycle remain
outside this decision.
