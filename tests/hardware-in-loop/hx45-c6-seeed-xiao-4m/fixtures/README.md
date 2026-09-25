# Sealed HX4.5 C6 extension fixture

`synthetic-loopback-esp32c6.elf` is the exact ESP32-C6 extension ELF accepted
by the cumulative HX4.5 host qualification. Its SHA-256 is
`60185086c35486f3b57c8ea1ef9f975499996f207050af37754a3c1c6ff02fb2`.

The named-board HIL build embeds these bytes directly. Rebuilding the extension
on a different host may be semantically valid but is not expected to reproduce
the sealed byte identity.
