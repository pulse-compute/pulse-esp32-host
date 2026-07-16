# wdc_hal

Hardware abstraction bridge for physical operations.

Current scope is GPIO. The HAL path is reached only after host-call validation, safety state checks, capability checks, and profile lookup.

Host tests use the HAL to prove that unauthorized requests do not reach physical execution paths.
