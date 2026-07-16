# wdc_security

Production security profile and bundle-policy construction.

R9 models production preflight checks for:

- secure boot;
- flash encryption;
- provisioned signing keys;
- OTA endpoint provisioning.

It also builds fail-closed bundle verification policy for production mode:

- reject dev signatures;
- require Ed25519-class production algorithm identifier;
- require verifier callback;
- enforce trusted key ID;
- enforce anti-rollback floor.

The scaffold tests this policy path with deterministic test vectors. Deployment must wire platform security state and real crypto.
