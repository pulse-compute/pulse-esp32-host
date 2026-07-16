# wdc_caps

Capability enforcement for the WASM/device contract.

The component translates host-call requests into required resource operations, checks them against the active bundle's manifest-derived capability set, and records audit decisions.

Rules:

- no capability means no access;
- SDK constants are not authority;
- resource IDs must map through the verified manifest;
- resource names must exist in the device profile;
- allowed operations must match the requested opcode/action.
