#include <stdint.h>

/* HX1 qualification-only import. This is not part of the Pulse ABI. */
extern int32_t pulse_hx1_probe_import(uint32_t value);

static volatile uint32_t s_probe_state;
static const uint32_t s_probe_salt = 0x48583131u;

__attribute__((visibility("default")))
int pulse_hx1_probe_entry(int argc, char *argv[])
{
    uint32_t value = (uint32_t)argc ^ s_probe_salt;
    if (argv != 0) {
        value ^= (uint32_t)(uintptr_t)argv;
    }
    s_probe_state = value;
    return pulse_hx1_probe_import(value);
}
