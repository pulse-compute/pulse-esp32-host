# `wdc_extension`

`wdc_extension` is the host authority for the experimental HX extension spine.
HX2 implements two-stage admission and fixed-capacity registry sealing:

1. `wdc_extension_inspect` validates bounded raw ELF structure, target identity,
   the fixed metadata record and digest, constructor policy, imports,
   relocations, budgets, and the canonical descriptor export without calling
   the loader or extension code.
2. `wdc_extension_load_descriptor` verifies the same immutable bytes, passes
   only inspector-admitted exact name/address bindings to `wdc_elf`, relocates,
   calls only the pure `pulse_extension_entry_v1`, and validates the descriptor
   and every lifecycle address.

HX3 adds the supervised `init` through `deinit` state machine, reverse unwind,
candidate-bounded time/health services, and reset-required teardown. The
extension owns its task and queue. The host owns ordering and the absolute
quiescence deadline, never force-deletes the task as normal cleanup, and permits
clean unload only after positive quiescence and kernel-confirmed task deletion.

HX4 adds `wdc_extension_bridge.c`. It consumes only the existing `wdc_events`
queue, dispatches only through `wdc_runtime`, delegates one target-neutral ABI
opcode through a claimable hook, resolves only a sealed numeric registry, and
owns one bounded completion slot. `pulse_host_emit_event_v1` and
`pulse_host_complete_effect_v1` are now live, candidate-attributed services.

HX4.5 seals the host adversarial corpus. Completion ownership distinguishes an
active not-yet-ready effect from a terminal timeout and lifecycle
cancellation, and every terminal bridge path releases the slot. Deadline races
remain timeouts; quiescence rejects late completion as stale; extension faults
latch the inherited reset-required state.

HX5a adds no capability. It freezes the fault taxonomy, exposes nine one-shot
return overrides only under `PULSE_EXTENSION_HOST_TEST`, distinguishes invalid
initialization state from capacity exhaustion, and makes uncertain or partial
ELF unload preserve fault evidence and require reset. The public extension ABI
and target import table are unchanged.

`wdc_extension_platform_espidf.c` remains the only unit that binds the exact
Pulse and FreeRTOS import names to target addresses. Build and host-smoke
evidence must not be described as target runtime proof. Sustained pressure and
targeted S3/C6 reruns remain the HX5b phase boundary.
