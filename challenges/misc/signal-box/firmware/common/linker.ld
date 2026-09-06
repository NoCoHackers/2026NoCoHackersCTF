ENTRY(reset_handler)

MEMORY
{
    FLASH(rx)  : ORIGIN = 0x10000000, LENGTH = 2M
    RAM(rwx)   : ORIGIN = 0x20000000, LENGTH = 264K
}

SECTIONS
{
    .boot2 ORIGIN(FLASH) :
    {
        KEEP(*(.boot2))
    } > FLASH
    ASSERT(SIZEOF(.boot2) == 256, "boot2 must be exactly 256 bytes")

    .vectors ORIGIN(FLASH) + 0x100 :
    {
        KEEP(*(.vectors))
    } > FLASH

    .text :
    {
        *(.text*)
        *(.rodata*)
        . = ALIGN(4);
    } > FLASH

    .data : AT(LOADADDR(.text) + SIZEOF(.text))
    {
        . = ALIGN(4);
        __data_start = .;
        *(.data*)
        . = ALIGN(4);
        __data_end = .;
    } > RAM
    __data_load = LOADADDR(.data);

    .bss (NOLOAD) :
    {
        . = ALIGN(4);
        __bss_start = .;
        *(.bss*)
        *(COMMON)
        . = ALIGN(4);
        __bss_end = .;
    } > RAM

    . = ALIGN(8);
    __heap_start = .;
    __stack_top = ORIGIN(RAM) + LENGTH(RAM);

    /DISCARD/ :
    {
        *(.comment*)
        *(.ARM.attributes*)
        *(.eh_frame*)
    }
}
