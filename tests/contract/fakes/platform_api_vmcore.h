#ifndef PULSE_TEST_PLATFORM_API_VMCORE_H
#define PULSE_TEST_PLATFORM_API_VMCORE_H

#include <stdint.h>

typedef intptr_t os_file_handle;

enum {
    MMAP_PROT_NONE = 0,
    MMAP_PROT_READ = 1,
    MMAP_PROT_WRITE = 2,
    MMAP_PROT_EXEC = 4,
};

#endif
