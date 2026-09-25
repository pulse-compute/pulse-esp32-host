# `wdc_app_slots`

HP3 host-owned Pulse application-slot authority. It stages a fixed artifact
only into the inactive flash partition, verifies the inner bundle and HP2 host
requirements before trial, preserves the confirmed slot, and returns explicit
trial, fallback-reboot, or recovery decisions without launching application
code.

It does not implement RAX, a transport, host-firmware OTA, application-owned
confirmation, or production signing. Production mode requires an installed
artifact-authority verifier in addition to the existing bundle verifier.
