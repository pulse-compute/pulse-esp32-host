#define main hp42_sealed_smoke_main
#include "hp4_2_admin_update_smoke.c"
#undef main

static int32_t reinitialize_update_for_profile(
    Harness *harness,
    const WdcControlResourceProfile *profile,
    WdcHostTarget fingerprint_target)
{
    WdcAdminUpdateConfig config;
    const WdcHostFingerprintV1 *fingerprint;

    CHECK(wdc_control_kernel_init(&harness->kernel, profile) == WDC_OK);
    fingerprint = wdc_host_fingerprint_for_target(fingerprint_target);
    CHECK(fingerprint != NULL);
    if (fingerprint == NULL) {
        return WDC_ERR_BAD_POINTER;
    }
    harness->fingerprint = *fingerprint;
    harness->fingerprint.capability_mask |= WDC_HOST_CAP_APPLICATION_SLOTS;
    harness->fingerprint.crc32 =
        wdc_host_fingerprint_crc32(&harness->fingerprint);

    memset(&config, 0, sizeof(config));
    config.core = &harness->core;
    config.metadata = &harness->metadata;
    config.running_host_fingerprint = &harness->fingerprint;
    config.slot_verify_policy = &harness->slot_policy;
    config.activation_policy = &harness->activation_policy;
    config.lifecycle.quiesce_and_unload = fake_quiesce;
    config.lifecycle.heap_snapshot_after_unload = fake_heap;
    config.lifecycle.context = &harness->lifecycle;
    config.working_buffer = harness->working;
    config.working_buffer_bytes = sizeof(harness->working);
    return wdc_admin_update_init(&harness->update, &config);
}

int main(int argc, char **argv)
{
    Harness harness;
    uint32_t before;

    if (argc != 2 || !load_bundle(argv[1])) {
        return 2;
    }
    build_artifact();
    before = s_failures;

    init_harness(&harness, 0u);
    CHECK(reinitialize_update_for_profile(
              &harness, wdc_control_profile_s3_psram(),
              WDC_HOST_TARGET_ESP32S3) == WDC_OK);
    CHECK(reinitialize_update_for_profile(
              &harness, wdc_control_profile_s3_psram(),
              WDC_HOST_TARGET_ESP32C6) == WDC_ERR_BAD_ENCODING);
    CHECK(reinitialize_update_for_profile(
              &harness, wdc_control_profile_c6_minimum(),
              WDC_HOST_TARGET_ESP32S3) == WDC_ERR_BAD_ENCODING);
    CHECK(reinitialize_update_for_profile(
              &harness, wdc_control_profile_c6_minimum(),
              WDC_HOST_TARGET_ESP32C6) == WDC_OK);

    (void)printf(
        "{\"schema\":\"pulse.esp32.hp5_5-update-profile-smoke.v1\","
        "\"status\":\"%s\",\"cases\":4,\"failures\":%" PRIu32 "}\n",
        before == s_failures ? "PASS" : "FAIL", s_failures - before);
    return before == s_failures ? 0 : 1;
}
