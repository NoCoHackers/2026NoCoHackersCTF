.syntax unified
.cpu cortex-m0plus
.thumb

.section .vectors, "a", %progbits
.align 8
.global __vector_table
__vector_table:
    .word __stack_top
    .word reset_handler + 1
    .word default_handler + 1
    .word default_handler + 1
    .word default_handler + 1
    .word default_handler + 1
    .word default_handler + 1
    .word 0
    .word 0
    .word 0
    .word 0
    .word default_handler + 1
    .word default_handler + 1
    .word 0
    .word default_handler + 1
    .word default_handler + 1

.section .text.reset_handler, "ax", %progbits
.align 2
.global reset_handler
.type reset_handler, %function
.thumb_func
reset_handler:
    cpsid i

    ldr r0, =0xe000ed08
    ldr r1, =__vector_table
    str r1, [r0]

    ldr r0, =__data_load
    ldr r1, =__data_start
    ldr r2, =__data_end
1:
    cmp r1, r2
    bcs 2f
    ldr r3, [r0]
    str r3, [r1]
    adds r0, #4
    adds r1, #4
    b 1b

2:
    ldr r0, =__bss_start
    ldr r1, =__bss_end
    movs r2, #0
3:
    cmp r0, r1
    bcs 4f
    str r2, [r0]
    adds r0, #4
    b 3b

4:
    bl main
5:
    b 5b
.size reset_handler, . - reset_handler

.section .text.default_handler, "ax", %progbits
.align 2
.global default_handler
.type default_handler, %function
.thumb_func
default_handler:
    b default_handler
.size default_handler, . - default_handler
