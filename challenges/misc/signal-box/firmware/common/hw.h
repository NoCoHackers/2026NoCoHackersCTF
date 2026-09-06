#ifndef SIGNAL_BOX_DEBUG_HW_H
#define SIGNAL_BOX_DEBUG_HW_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

// These are generated pico-sdk register headers. Keeping the register names in
// the code avoids recreating field positions by hand; see SIGNAL-BOX-HANDOFF.md.
#include "hardware/regs/adc.h"
#include "hardware/regs/addressmap.h"
#include "hardware/regs/clocks.h"
#include "hardware/regs/i2c.h"
#include "hardware/regs/io_bank0.h"
#include "hardware/regs/pads_bank0.h"
#include "hardware/regs/pio.h"
#include "hardware/regs/pll.h"
#include "hardware/regs/resets.h"
#include "hardware/regs/sio.h"
#include "hardware/regs/timer.h"
#include "hardware/regs/uart.h"
#include "hardware/regs/watchdog.h"
#include "hardware/regs/xosc.h"

static inline volatile uint32_t *hw_reg(uint32_t address)
{
    return (volatile uint32_t *)(uintptr_t)address;
}

static inline uint32_t hw_read(uint32_t address)
{
    return *hw_reg(address);
}

static inline void hw_write(uint32_t address, uint32_t value)
{
    *hw_reg(address) = value;
}

static inline void hw_set(uint32_t address, uint32_t bits)
{
    hw_write(address, hw_read(address) | bits);
}

static inline void hw_clear(uint32_t address, uint32_t bits)
{
    hw_write(address, hw_read(address) & ~bits);
}

static inline uint32_t gpio_ctrl_address(uint32_t gpio)
{
    // GPIO control/status register pairs have an 8-byte stride.
    return IO_BANK0_BASE + IO_BANK0_GPIO0_CTRL_OFFSET + (gpio << 3);
}

static inline uint32_t gpio_pad_address(uint32_t gpio)
{
    return PADS_BANK0_BASE + PADS_BANK0_GPIO0_OFFSET + (gpio << 2);
}

#endif
