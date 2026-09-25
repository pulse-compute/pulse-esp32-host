# Accepted HP3.5 hardware evidence

The frozen HP3.5 safe physical subset passed on the exact AITRIP ESP32-S3
N8R2 and Seeed XIAO ESP32-C6 boards. Each physical report contains the same 13
ordered checkpoints, preserves the last confirmed application, establishes one
unambiguous boot authority, and launches no application code before authority.

| Target | Board report SHA-256 | Serial SHA-256 | Result |
|---|---|---|---|
| ESP32-S3 | `34e7a64a2ea6a3dca848f31386ca136016bdf64af5e3722c505ec4f80b759337` | `4673297ec9e996661195af1732cdce8887c5f3ad4f7a2c59311bb149cf858474` | `PASS`; 13 checkpoints |
| ESP32-C6 | `6c871c34e5a188970d0d9ad8950fad36e2a8c1e222a60c8211c454587e946de2` | `a3db88e623fa31bde68c979583cf8d0b00a7133a7acf7f22fc14a6705724d26a` | `PASS`; 13 checkpoints |

The dual evaluation has SHA-256
`fda59573053dc9e6e2003e4b631a26964c5061eb9922f2bc2b681c65d3f51168`
and closes as `DUAL_NAMED_BOARD_SAFE_SUBSET_OBSERVED`. Its evidence manifest
has SHA-256
`dd72112eb875a22fa13923848081458f5b7aa7119b08e09a2e4501e4add81549`.

The board evidence is bound to campaign SHA-256
`b482f49a4d50312ba9efcf78d2d0a10495a67cd9e621f8662abed84fc3e2e3d3`
and firmware-tree SHA-256
`c7b4341e00911b3b26b4d9b8abcd831af4abdf7754503a79298e86aa2b9d2c31`.
The exact source-distributed authority is [hp3_5-index.json](hp3_5-index.json).

The complete run directories remain external. The input evidence archive also
contains pre-run full-flash backups; those are private recovery material and
are deliberately excluded from source. This index does not claim physical
power cutting, exhaustive target interruption, application execution,
factory-host writes, host-firmware OTA, an external provider, or RAX.
