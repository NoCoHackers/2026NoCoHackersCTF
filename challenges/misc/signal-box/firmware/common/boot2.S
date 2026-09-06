// Generic 03h second-stage boot for RP2040.
// Copyright (c) 2019-2021 Raspberry Pi (Trading) Ltd.
// SPDX-License-Identifier: BSD-3-Clause
// Adapted from pico-sdk boot2_generic_03h.S.
// Register constants come directly from pico-sdk generated headers.

#include "hardware/regs/addressmap.h"
#include "hardware/regs/ssi.h"

.syntax unified
.cpu cortex-m0plus
.thumb

.section .boot2, "ax", %progbits
.align 2
.global __boot2_start__
.type __boot2_start__, %function
.thumb_func
__boot2_start__:
    push {lr}
    ldr r3, =XIP_SSI_BASE

    movs r1, #0
    str r1, [r3, #SSI_SSIENR_OFFSET]

    movs r1, #4
    str r1, [r3, #SSI_BAUDR_OFFSET]

    // Standard SPI, 32-bit frames, EEPROM-read transaction mode.
    ldr r1, =(SSI_CTRLR0_SPI_FRF_VALUE_STD << SSI_CTRLR0_SPI_FRF_LSB) | \
              (31 << SSI_CTRLR0_DFS_32_LSB) | \
              (SSI_CTRLR0_TMOD_VALUE_EEPROM_READ << SSI_CTRLR0_TMOD_LSB)
    str r1, [r3, #SSI_CTRLR0_OFFSET]

    // 03h command, 24-bit address, 8-bit instruction, serial command/address.
    ldr r1, =(0x03 << SSI_SPI_CTRLR0_XIP_CMD_LSB) | \
              (6 << SSI_SPI_CTRLR0_ADDR_L_LSB) | \
              (2 << SSI_SPI_CTRLR0_INST_L_LSB) | \
              (SSI_SPI_CTRLR0_TRANS_TYPE_VALUE_1C1A << SSI_SPI_CTRLR0_TRANS_TYPE_LSB)
    ldr r0, =(XIP_SSI_BASE + SSI_SPI_CTRLR0_OFFSET)
    str r1, [r0]

    movs r1, #0
    str r1, [r3, #SSI_CTRLR1_OFFSET]
    movs r1, #1
    str r1, [r3, #SSI_SSIENR_OFFSET]

    pop {r0}
    cmp r0, #0
    bne 1f

    ldr r0, =0x10000100
    ldr r1, [r0]
    mov sp, r1
    ldr r0, [r0, #4]
1:
    bx r0

    .ltorg
.size __boot2_start__, . - __boot2_start__

// The ROM verifies the checksum in the final word. common/make_uf2.py patches
// that word after objcopy; keeping the section exactly 256 bytes also fixes
// the application vector table at 0x10000100.
.space 252 - (. - __boot2_start__), 0
.word 0
