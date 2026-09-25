#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>

#include "shell_config.h"
#include "wdc_admin.h"
#include "wdc_admin_recovery.h"
#include "wdc_admin_update.h"
#include "wdc_control.h"
#include "wdc_app_slots.h"
#include "wdc_elf.h"
#include "wdc_extension.h"
#include "wdc_host_identity.h"
#include "wdc_http.h"

#define WDC_APP_PTHREAD_STACK_BYTES (16u * 1024u)

void shell_main(void);

static void *wdc_app_pthread(void *arg)
{
    (void)arg;
    (void)wdc_control_link_anchor();
    (void)wdc_app_slots_link_anchor();
    (void)wdc_elf_link_anchor();
    (void)wdc_extension_link_anchor();
    (void)wdc_host_identity_link_anchor();
    shell_main();
    return NULL;
}

static void wdc_app_pthread_fail(const char *operation, int status)
{
    (void)fprintf(stderr,
                  "fatal: WAMR pthread %s failed with status %d\n",
                  operation,
                  status);
    abort();
}

void app_main(void)
{
    pthread_attr_t attributes;
    pthread_t thread;
    (void)wdc_admin_link_anchor();
    (void)wdc_admin_update_link_anchor();
    (void)wdc_admin_recovery_link_anchor();
    (void)wdc_http_link_anchor();
    int status = pthread_attr_init(&attributes);
    if (status != 0) {
        wdc_app_pthread_fail("attribute initialization", status);
    }
    status = pthread_attr_setdetachstate(&attributes, PTHREAD_CREATE_JOINABLE);
    if (status == 0) {
        status = pthread_attr_setstacksize(&attributes,
                                           WDC_APP_PTHREAD_STACK_BYTES);
    }
    if (status == 0) {
        status = pthread_create(&thread, &attributes, wdc_app_pthread, NULL);
    }
    (void)pthread_attr_destroy(&attributes);
    if (status != 0) {
        wdc_app_pthread_fail("creation", status);
    }
    status = pthread_join(thread, NULL);
    if (status != 0) {
        wdc_app_pthread_fail("join", status);
    }
}
