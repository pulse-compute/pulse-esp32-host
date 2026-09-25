# HP1 host-kernel resource authority

## Result

HP1 freezes and implements the smallest host-owned control kernel needed before
application-slot, administration, provider, or protocol work can proceed.

The host now has one explicit authority for:

- fixed ISR capture and host-task notification;
- priority assignment;
- bounded work and completion capacity;
- stack, queue, metadata, administration, verification, and recovery reserves;
- C6 no-PSRAM admission; and
- target-visible internal free, largest-block, and optional PSRAM sampling.

The synthetic qualifier closes as `HOST_RESOURCE_AUTHORITY_PROVEN`. HP1 does
not make a new physical result. The HP0 S3 and C6 observations are sizing inputs
only.

The machine-readable authority is
[`PULSE-ESP32-006-host-kernel-resource-authority.json`](../specs/PULSE-ESP32-006-host-kernel-resource-authority.json).

## Boundary

The control path is deliberately one-way:

```text
fixed ISR record
  -> allocation-free ISR ring
  -> direct host-task notification
  -> host-owned priority lane
  -> bounded work ticket
  -> exactly one terminal completion
```

No application-facing record contains an RTOS priority. A work request names a
host-classified source; the kernel maps that source to a fixed class. The
application source always maps to the lowest class.

`wdc_control` is host-private. It does not add an opcode, guest import, native
extension import, or public extension ABI field.

## Fixed priority classes

Higher numeric FreeRTOS values run at higher priority. The five task/queue
budgets are reserved independently so application saturation cannot consume a
safety or administrative ticket.

| Class | Priority | Stack | Queue | Sources | Overflow |
|---|---:|---:|---:|---|---|
| Safety/recovery | 13 | 4,096 B | 8 | safety, watchdog, recovery | reject newest, emit terminal rejection, latch recovery |
| Administration | 11 | 6,144 B | 8 | administration, update | reject newest with terminal rejection |
| Network maintenance | 9 | 6,144 B | 8 | host network maintenance | reject newest with terminal rejection |
| Capability dispatch | 7 | 4,096 B | 16 | bounded capability work | reject newest with terminal rejection |
| Application | 5 | 8,192 B | 16 | application dispatch | reject newest with terminal rejection |

These are host policies, not application hints. HP2 may select a compatible
host profile and build lock; it may not let application configuration rewrite
the ordering.

## ISR contract

`WdcControlIsrCapture` is exactly four `uint32_t` fields: source, signal, value,
and sequence. The ring has eight usable records and one sentinel slot. It has a
single ISR producer and one host-task consumer.

The ISR path may only:

1. validate the fixed fields;
2. copy those fields into the next fixed record;
3. publish an atomic index;
4. increment bounded notification or overflow counters;
5. latch recovery on overflow; and
6. issue `vTaskNotifyGiveFromISR` to the previously bound host task.

It cannot allocate, log, parse, call an application, enter WAMR, or enter the
native-extension lifecycle. Overflow rejects the newest capture and latches
recovery; it is never a silent overwrite.

HP1 creates no production interrupt source. The source used by qualification is
synthetic.

## Queue and completion ownership

Each priority class owns its own fixed slots. Lower classes cannot borrow from
higher classes. A slot remains owned from accepted submission through terminal
completion collection.

An accepted ticket can terminate exactly once as:

- `SUCCEEDED`;
- `FAILED`;
- `TIMED_OUT`; or
- `CANCELLED`.

The caller takes that completion once before the slot becomes reusable. A
duplicate terminal write fails with `WDC_ERR_INVALID_STATE`; a stale collection
fails with `WDC_ERR_NOT_AVAILABLE`.

A request rejected before acceptance receives an immediate
`REJECTED_OVERFLOW` completion record with no ticket. This means backpressure is
observable without manufacturing ownership of work the host did not accept.

Tickets combine a bounded per-class slot and generation. They never encode a
pointer. The component contains no `malloc`, `calloc`, or `realloc` path.

## C6 minimum portable reserve

The C6 profile assumes no PSRAM and makes all control authority internal.

| Reserved item | Bytes |
|---|---:|
| Five host-owned task stacks | 28,672 |
| Fixed kernel, ISR ring, queues, tickets, completions | 8,192 |
| Control metadata | 8,192 |
| Administration working reserve | 12,288 |
| Verification working reserve | 24,576 |
| Recovery working reserve | 16,384 |
| **Fixed control reserve** | **98,304** |

The complete exclusive update mode has an additional 65,536-byte bounded
working set. The largest permitted update allocation is 65,536 bytes and the
largest-block floor is 32,768 bytes. Application internal working memory is
capped at 131,072 bytes and quiesce-transition scratch at 16,384 bytes.

The retained HX5b C6 observations used to size this first conservative profile
were:

- minimum internal free: 255,032 bytes;
- minimum largest internal block: 221,184 bytes; and
- PSRAM: zero bytes.

Those observations do not turn HP1 into a physical run and do not guarantee a
future HP1 image. A later physical gate must retain build, flash, serial,
evaluation, and hash evidence for the HP1 source.

## Admission calculation

Admission uses an explicit pre-launch heap snapshot. Application internal
working memory is the checked sum of:

- guest linear memory;
- runtime stack;
- host-owned network working memory attributable to the application;
- active capability working memory; and
- admitted native-extension internal memory.

The three phase peaks are:

```text
normal     = fixed control reserve + application internal working memory
transition = normal + bounded quiesce/update-transition scratch
update     = fixed control reserve + exclusive update working set
```

The required total free memory is `max(transition, update)`. Because update is
exclusive on the C6, the calculation does not require the complete guest and
complete update working set to coexist after quiescence.

The contiguous-memory gate is separate:

```text
max(
  largest application allocation + largest-block floor,
  largest update allocation + largest-block floor
)
```

Both total free memory and largest contiguous internal memory must pass. All
addition is checked for `uint32_t` overflow and arithmetic ambiguity fails
closed.

The synthetic portable witness uses the exact retained C6 pressure floors with
86,016 bytes of application internal working memory and 8,192 bytes of
transition scratch. It requires:

- 192,512 bytes total internal free;
- a 98,304-byte largest internal block;
- a 62,520-byte total-free margin; and
- a 122,880-byte largest-block margin.

This is a boundary witness, not a default application budget for all future
profiles.

## Explicit denials

Admission fails before application launch when:

- an application requests any RTOS priority instead of accepting host
  assignment;
- an unbounded allocation is requested;
- C6 behavior requires PSRAM;
- application or transition totals exceed the profile;
- total internal free memory is insufficient;
- the largest internal block is insufficient;
- declared S3 external memory plus its floor is unavailable; or
- arithmetic overflows or the request is incomplete.

No admission denial is converted into a best-effort launch.

## S3 optimization boundary

The S3 profile retains the same 98,304-byte internal control reserve, priority
classes, queue capacities, update working set, and contiguous-memory gates.

It may admit up to 1 MiB of explicitly declared application PSRAM while
retaining a 128 KiB PSRAM floor. Such an admission is reported as
`ACCEPTED_TARGET_OPTIMIZED` with `portable=false`. C6 rejects those same external
bytes. PSRAM can therefore optimize a realization, but cannot silently become
the meaning of a portable application contract.

HP2 owns the later separation among board identity, host resource profile,
application intent, build plan, build lock, and running-host fingerprint.

## Synthetic seal

`make check-hp1` and `make host-kernel-qualify` cover:

- nine exact cases;
- eight accepted ISR captures plus one recovery-latching overflow;
- application queue saturation at 16 items while safety and administration
  remain admissible and dispatch first;
- all five lanes saturated without capacity borrowing;
- terminal overflow and duplicate/stale completion behavior;
- eight fail-closed admission classes;
- explicit S3 non-portable PSRAM accounting; and
- 64 five-class pressure rounds, 320 accepted tickets, 320 collected terminal
  completions, and zero retained slots.

## Preserved seals and exclusions

HP1 preserves the exact common Wasm, native-extension ABI, loader fixtures,
HX5b pressure model, and HP0 evidence archive. Adding the host-control component
changes the current firmware source tree, so the old HP0 physical result remains
bound to the v17 source snapshot. It is not relabeled as physical evidence for
the HP1 tree.

Still excluded:

- production GPIO, I2C, SPI, BLE, or interrupt integration;
- MQTT or another application protocol;
- the external ESP32 provider or Pulse configuration ergonomics;
- application slots, fallback, protected administration, or update transport;
- RAX and host-firmware/bootloader/partition OTA; and
- a new hardware claim.

## Handoff

HP1 closes resource authority. HP2 should now separate target intent, host
profile, build plan, exact build lock, and running-host fingerprint without
moving priority or reserve ownership into application configuration.
