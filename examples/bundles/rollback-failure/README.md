# Rollback failure example

`manifest.intentional-invalid-extra-field.json` is intentionally schema-invalid in R0 because it includes `test_behavior`.

Once R7 introduces signed test bundles and a test-only metadata extension, this example should become a real bad-health WASM bundle whose `wdc_module_health()` returns an error during probation.
