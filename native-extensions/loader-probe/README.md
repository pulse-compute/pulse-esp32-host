# HX1 loader probe

This source is a qualification fixture, not the HX2 synthetic extension and
not a Pulse ABI implementation. It produces one `ET_DYN` ELF per proof target
with a visible entry, one explicit qualification-only import, writable and
read-only data, and toolchain-generated relocations. HX1 inventories those
facts without executing the artifact.
