# HX1 host-extension component locks

These locks are independent of the historical IF7 locks. They were resolved
for the exact ESP-IDF 5.4.4 source lane after adding `wdc_elf`, so they include
the existing WAMR component plus exact `elf_loader` 1.3.2 and its resolved
`cmake_utilities` 0.5.3 dependency. S3 and C6 retain separate target-bound
locks even though their component graphs otherwise match.
