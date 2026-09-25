#ifndef PULSE_TEST_ELF_TYPES_H
#define PULSE_TEST_ELF_TYPES_H

#include <stdint.h>

#define EI_NIDENT 16
#define SHT_PROGBITS 1
#define SHT_STRTAB 3
#define SHT_NOBITS 8
#define SHF_WRITE 1
#define SHF_ALLOC 2
#define ELF_BSS ".bss"
#define ELF_DATA ".data"
#define ELF_RODATA ".rodata"
#define ELF_DATA_REL_RO ".data.rel.ro"

typedef uint32_t Elf32_Addr;
typedef uint32_t Elf32_Off;
typedef uint32_t Elf32_Word;
typedef uint16_t Elf32_Half;

typedef struct elf32_hdr {
    unsigned char ident[EI_NIDENT];
    Elf32_Half type;
    Elf32_Half machine;
    Elf32_Word version;
    Elf32_Addr entry;
    Elf32_Off phoff;
    Elf32_Off shoff;
    Elf32_Word flags;
    Elf32_Half ehsize;
    Elf32_Half phentsize;
    Elf32_Half phnum;
    Elf32_Half shentsize;
    Elf32_Half shnum;
    Elf32_Half shstrndx;
} elf32_hdr_t;

typedef struct elf32_shdr {
    Elf32_Word name;
    Elf32_Word type;
    Elf32_Word flags;
    Elf32_Addr addr;
    Elf32_Off offset;
    Elf32_Word size;
    Elf32_Word link;
    Elf32_Word info;
    Elf32_Word addralign;
    Elf32_Word entsize;
} elf32_shdr_t;

#endif
