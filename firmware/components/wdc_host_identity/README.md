# wdc_host_identity

HP2's host-private running-fingerprint and prelaunch compatibility boundary.

The component consumes a build-derived, fixed-width fingerprint. It validates
the fingerprint CRC and exact build/profile authority, checks target, ABI, and
host capabilities, then delegates all heap, largest-block, transition, and
exclusive-update admission to HP1's `wdc_control` authority.

`wdc_host_fingerprint_generated.c` is derived only by the explicit HP2 lock
resolver. It is excluded from the source-tree input digest to avoid a circular
lock → fingerprint → source-tree dependency, but contract tests require it to
reproduce exactly from both committed build locks.

No guest import or public Pulse configuration field is added here. HP3 may
place compatible requirements in its application artifact header and must call
this prelaunch check before entering application code.
