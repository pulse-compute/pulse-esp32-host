# Sealed HX4.5 S3 extension fixture

`synthetic-loopback-esp32s3.elf` is the exact ESP32-S3 extension ELF sealed by
HX4.5. Its SHA-256 is
`7c7c5465de5dc408b4fc79e8bdd9956234099817596d987c7950126ca2921daf`.

The named-board HIL build embeds these bytes directly. Rebuilding the extension
on a different host may be semantically valid but is not expected to reproduce
the sealed byte identity.
