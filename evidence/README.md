# Durable evidence indexes

This directory contains compact, source-distributed indexes for accepted
qualification evidence. It does not contain generated firmware images, linker
maps, build trees, or serial captures.

The evidence boundary is intentional:

- `evidence/` records accepted run identities, report hashes, classifications,
  and claim boundaries;
- `reports/` is an ignored local workspace for fresh validation output;
- full host and hardware evidence trees are packaged as separate release
  artifacts; and
- ESP-IDF, compiler toolchains, and managed components are installed from the
  pinned environment and dependency locks rather than embedded in a source
  snapshot.

See [Packaging and evidence](../docs/PACKAGING_AND_EVIDENCE.md) for the package
contracts and commands.

