# wdc_http

Host-private HP5 HTTPS ingress and administration bridge. This component owns
the fixed request parsers, exact Pulse route table, separate application and
administration listener budgets, and ESP-IDF Wi-Fi/TLS adapter. It may depend
on `wdc_admin`; application-facing `wdc_net` cannot.

Application requests are delivered through the common Wasm event handler and
may produce one bounded `WDC_OP_HTTP_RESPOND` effect. Administration requests
are normalized into the existing HP4 authenticated-entry, serial-frame,
session, replay, deadline, command, terminal, journal, update, and recovery
authorities. No second administration state machine is introduced.
