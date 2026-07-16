# wdc_bundle

Bundle container parser and admission verifier.

Implemented through R9:

```text
- WDCB container v1 header parsing
- manifest SHA-256 check
- payload SHA-256 check
- manifest payload hash/size binding
- no trailing unsigned bytes
- deterministic development HMAC-SHA256 test signature path
- production-mode rejection of development signatures
- production verifier callback contract
- trusted key-id policy enforcement
- manifest/container signature-algorithm consistency checks
- ABI, target, runtime feature, and limit policy checks
- anti-rollback security counter check
- capability parsing against the device profile
- required lifecycle export validation by parsing the WASM export section
```

R9 does not include deployment-grade Ed25519 math. A production build must wire `WdcBundleSignatureVerifyFn` to a vetted crypto implementation.
