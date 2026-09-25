# wdc_control

HP1's host-owned control-kernel and resource-admission boundary.

The component fixes five priority classes, partitions bounded work and
completion slots per class, captures only fixed ISR records, and reserves the
control-plane memory needed before an application can be admitted. The C6
no-PSRAM profile is the minimum portable profile. The S3 profile may account
for explicitly declared application PSRAM, but all control, administration,
verification, recovery, queue, ticket, and task-stack reserves remain internal.

`wdc_control.c` is allocation-free and platform-neutral. The ESP-IDF adapter
does only two target-specific jobs: sample internal/largest-block heap state
and issue a direct FreeRTOS task notification after an accepted fixed ISR
capture. It does not create a task, enter Wasm or native-extension lifecycle
code, log, parse, or allocate.

HP1 uses synthetic interrupt and pressure sources. This component adds no
production peripheral, network protocol, update transport, or application
authority.
