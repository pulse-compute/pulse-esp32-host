# wdc_activation

A/B WASM activation and rollback state machine.

Implemented states:

```text
verified -> pending -> running_pending -> confirmed
running_pending -> failed -> rollback_to_last_good
```

The shell, not the guest, decides whether a candidate becomes confirmed. Candidate boot attempts and faults are tracked so an unconfirmed bundle can roll back to `last_good`.
