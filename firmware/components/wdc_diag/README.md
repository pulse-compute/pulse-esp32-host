# wdc_diag

Diagnostics, ring buffer, reset/fault breadcrumbs, and counters.

Diagnostics are native-owned evidence. They should be sufficient to reconstruct bundle activation, host-call allow/deny decisions, safety transitions, runtime faults, and rollback decisions without trusting guest state.
