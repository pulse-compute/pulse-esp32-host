# Native-extension host evidence index

This index records the accepted HX1 through HX4.5 host/build qualification
reports without embedding their generated ELF, map, binary, and log trees in
the source distribution. The complete trees belong in the separately packaged
host-evidence artifact. Each artifact contains an `EVIDENCE-MANIFEST.json` that
binds every retained path to its size and SHA-256 digest.

| Pass | Accepted run | Status | Classification | JSON report SHA-256 | Markdown report SHA-256 |
|---|---|---|---|---|---|
| HX1 | `hx1-sandbox-20260810f` | `PASS` | `BUILD_PROVEN`; target runtime `HARDWARE_NOT_RUN` | `9647d1c49c0b51d7e537b43a1ffa3f37750856167d14029cf505d0e1ac10452c` | `303ab6840a56cc90cec2237d29759bad8063b1831366c906d2510286d0198169` |
| HX2 | `hx2-sandbox-20260810b` | `PASS` | admission sealed; target runtime `HARDWARE_NOT_RUN` | `0043f91f798f39fc62e9d0a3b8343eb5028fc0b8ac843fa5966ba7172f202b2b` | `a41282fba9c0864459bfba20ead380673be75ae535cb5f742e4e5ac2a5e79c28` |
| HX3 | `hx3-sandbox-20260810c` | `PASS` | lifecycle host-sealed; target runtime `HARDWARE_NOT_RUN` | `a7ceef9e2942f11b2688ba67dbd124eefdf124a4c6268e1ab61f157779754e2c` | `0597994423765f8fafb094f12ac55e2233840637e9a0e997f9e4381a8b730645` |
| HX4 | `hx4-sandbox-20260810h` | `PASS` | happy path host-sealed; target runtime `HARDWARE_NOT_RUN` | `efb498c1f0bbed10337b52d4e50f69993f3a1d33ba016648a641bc1d65840f43` | `74cd17de62bdcc65c95468286dc7c4d25757522249f757add01b9dfbd62d454c` |
| HX4.5 | `hx45-sandbox-20260810a` | `PASS` | adversarial host-sealed; target runtime `HARDWARE_NOT_RUN` | `efca28ed563fbc0b87b2c7bddf77019f9f2a9695a09ec9679863b4ded346ecd2` | `e0ca600e269d72e6f5f96f7a6a97fd646e6b69959eea013821e15be840f05447` |

These reports do not claim physical runtime execution. Named-board ESP32-S3
runtime evidence is accepted only after the hardware evaluator emits a passing
qualification report and the complete run is packaged independently.

