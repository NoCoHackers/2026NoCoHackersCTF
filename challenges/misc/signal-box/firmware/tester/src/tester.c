#include "config.h"
#include "hw.h"

#if DUT_UART_BAUD != 115200u || TESTER_LOG_BAUD != 115200u
#error UART divisors and PIO timing are fixed for 115200 baud
#endif

#define GPIO_FUNC_PIO IO_BANK0_GPIO0_CTRL_FUNCSEL_VALUE_PIO0_0
#define GPIO_FUNC_UART IO_BANK0_GPIO0_CTRL_FUNCSEL_VALUE_UART0_TX
#define GPIO_FUNC_SIO IO_BANK0_GPIO0_CTRL_FUNCSEL_VALUE_SIO_0
#define GPIO_FUNC_NULL IO_BANK0_GPIO0_CTRL_FUNCSEL_VALUE_NULL

#define RESET_BANK0_MASK \
    (RESETS_RESET_IO_BANK0_BITS | RESETS_RESET_PADS_BANK0_BITS)
#define RESET_RUNTIME_MASK \
    (RESETS_RESET_ADC_BITS | RESETS_RESET_PIO0_BITS | \
     RESETS_RESET_SYSCFG_BITS | RESETS_RESET_TIMER_BITS | \
     RESETS_RESET_UART0_BITS)

#define PIO_RX_SM 0u
#define PIO_TX_SM 1u
#define PIO_RX_OFFSET 0u
#define PIO_TX_OFFSET 4u
#define PIO_SM_STRIDE (PIO_SM1_CLKDIV_OFFSET - PIO_SM0_CLKDIV_OFFSET)
#define PIO_TXF_STRIDE (PIO_TXF1_OFFSET - PIO_TXF0_OFFSET)
#define PIO_RXF_STRIDE (PIO_RXF1_OFFSET - PIO_RXF0_OFFSET)
#define PIO_INSTR_STRIDE (PIO_INSTR_MEM1_OFFSET - PIO_INSTR_MEM0_OFFSET)

#define RESULT_UART_RX (1u << 0)
#define RESULT_I2C_IDLE (1u << 1)
#define RESULT_TP_SDA (1u << 2)
#define RESULT_TP_SCL (1u << 3)
#define RESULT_I2C_INIT (1u << 4)
#define RESULT_ADDRESS (1u << 5)
#define RESULT_ACK (1u << 6)
#define RESULT_EEPROM_WRITE (1u << 7)
#define RESULT_EEPROM_RESTORE (1u << 8)
#define RESULT_EEPROM_RW (1u << 9)
#define RESULT_LED_GPIO (1u << 10)
#define RESULT_PROTECTED_WRITE (1u << 11)
#define RESULT_PROTECTED_RESTORE (1u << 12)
#define RESULT_PROTECTED_RW (1u << 13)
#define RESULT_WP_HIGH (1u << 14)
#define RESULT_WP_CHECK (1u << 15)

#define RUN_RESULTS \
    (RESULT_UART_RX | RESULT_I2C_IDLE | RESULT_TP_SDA | RESULT_TP_SCL | \
     RESULT_I2C_INIT | RESULT_ADDRESS | RESULT_ACK | RESULT_EEPROM_WRITE | \
     RESULT_EEPROM_RESTORE | RESULT_EEPROM_RW | RESULT_LED_GPIO)
#define PREPROVISION_RESULTS \
    (RESULT_PROTECTED_WRITE | RESULT_PROTECTED_RESTORE | RESULT_PROTECTED_RW)
#define FINAL_RESULTS \
    (RESULT_WP_HIGH | RESULT_PROTECTED_RESTORE | RESULT_WP_CHECK)

struct result_name {
    const char *name;
    uint32_t bit;
};

static const struct result_name result_names[] = {
    {"UART_RX", RESULT_UART_RX},
    {"I2C_IDLE_HIGH", RESULT_I2C_IDLE},
    {"TP_SDA_INPUT", RESULT_TP_SDA},
    {"TP_SCL_INPUT", RESULT_TP_SCL},
    {"I2C_INIT", RESULT_I2C_INIT},
    {"EEPROM_ADDRESS_50_ONLY", RESULT_ADDRESS},
    {"EEPROM_ACK_50", RESULT_ACK},
    {"EEPROM_WRITE", RESULT_EEPROM_WRITE},
    {"EEPROM_RESTORE", RESULT_EEPROM_RESTORE},
    {"EEPROM_RW_RESTORE", RESULT_EEPROM_RW},
    {"LED_GPIO26", RESULT_LED_GPIO},
    {"PROTECTED_WRITE", RESULT_PROTECTED_WRITE},
    {"PROTECTED_RESTORE", RESULT_PROTECTED_RESTORE},
    {"PROTECTED_RW_RESTORE", RESULT_PROTECTED_RW},
    {"EEPROM_WP_HIGH", RESULT_WP_HIGH},
    {"WP_CHECK", RESULT_WP_CHECK},
};

static bool tester_wp_high;

struct command_state {
    uint32_t expected;
    uint32_t seen;
    bool failed;
    bool run_command;
    bool fixture_end;
    bool passive_exercised;
    bool capture_i2c;
    bool sda_high;
    bool sda_low;
    bool scl_high;
    bool scl_low;
};

static bool adc_read(uint16_t *result);

static void crude_delay(void)
{
    for (volatile uint32_t i = 0; i < 180000u; ++i) {
        __asm volatile ("nop");
    }
}

static void reset_assert(uint32_t bits)
{
    hw_set(RESETS_BASE + RESETS_RESET_OFFSET, bits);
}

static bool reset_release(uint32_t bits)
{
    hw_clear(RESETS_BASE + RESETS_RESET_OFFSET, bits);
    for (volatile uint32_t wait = 0; wait < 200000u; ++wait) {
        if ((hw_read(RESETS_BASE + RESETS_RESET_DONE_OFFSET) & bits) == bits) {
            return true;
        }
    }
    return false;
}

static void gpio_set_function(uint32_t gpio, uint32_t function)
{
    uint32_t address = gpio_ctrl_address(gpio);
    uint32_t value = hw_read(address);
    value &= ~IO_BANK0_GPIO0_CTRL_FUNCSEL_BITS;
    value |= function << IO_BANK0_GPIO0_CTRL_FUNCSEL_LSB;
    hw_write(address, value);
}

static void gpio_set_pulls(uint32_t gpio, bool up, bool down)
{
    uint32_t address = gpio_pad_address(gpio);
    uint32_t value = hw_read(address);
    value |= PADS_BANK0_GPIO0_IE_BITS;
    value &= ~(PADS_BANK0_GPIO0_OD_BITS | PADS_BANK0_GPIO0_PUE_BITS |
               PADS_BANK0_GPIO0_PDE_BITS);
    if (up) {
        value |= PADS_BANK0_GPIO0_PUE_BITS;
    }
    if (down) {
        value |= PADS_BANK0_GPIO0_PDE_BITS;
    }
    hw_write(address, value);
}

static void gpio_output_init(uint32_t gpio, bool high)
{
    uint32_t mask = 1u << gpio;
    gpio_set_function(gpio, GPIO_FUNC_SIO);
    gpio_set_pulls(gpio, false, false);
    hw_write(SIO_BASE + (high ? SIO_GPIO_OUT_SET_OFFSET :
                                  SIO_GPIO_OUT_CLR_OFFSET), mask);
    hw_write(SIO_BASE + SIO_GPIO_OE_SET_OFFSET, mask);
}

static void gpio_input_init(uint32_t gpio)
{
    gpio_set_function(gpio, GPIO_FUNC_SIO);
    gpio_set_pulls(gpio, false, false);
    hw_write(SIO_BASE + SIO_GPIO_OE_CLR_OFFSET, 1u << gpio);
}

static void gpio_put(uint32_t gpio, bool high)
{
    hw_write(SIO_BASE + (high ? SIO_GPIO_OUT_SET_OFFSET :
                                  SIO_GPIO_OUT_CLR_OFFSET), 1u << gpio);
}

static bool gpio_get(uint32_t gpio)
{
    return (hw_read(SIO_BASE + SIO_GPIO_IN_OFFSET) & (1u << gpio)) != 0u;
}

static void indicators_init(void)
{
    gpio_output_init(TESTER_RED_LED_GPIO, true);
    gpio_output_init(TESTER_GREEN_LED_GPIO, true);
    gpio_output_init(TESTER_BLUE_LED_GPIO, true);
}

static void indicators_set(bool red, bool green, bool blue)
{
    gpio_put(TESTER_RED_LED_GPIO, !red);
    gpio_put(TESTER_GREEN_LED_GPIO, !green);
    gpio_put(TESTER_BLUE_LED_GPIO, !blue);
}

static void fatal_blink(void)
{
    for (;;) {
        indicators_set(true, false, false);
        crude_delay();
        indicators_set(false, false, false);
        crude_delay();
    }
}

static bool xosc_init(void)
{
    const uint32_t enable =
        (XOSC_CTRL_ENABLE_VALUE_ENABLE << XOSC_CTRL_ENABLE_LSB) |
        (XOSC_CTRL_FREQ_RANGE_VALUE_1_15MHZ << XOSC_CTRL_FREQ_RANGE_LSB);
    const uint32_t disable =
        (XOSC_CTRL_ENABLE_VALUE_DISABLE << XOSC_CTRL_ENABLE_LSB) |
        (XOSC_CTRL_FREQ_RANGE_VALUE_1_15MHZ << XOSC_CTRL_FREQ_RANGE_LSB);

    hw_write(XOSC_BASE + XOSC_STARTUP_OFFSET, 47u);
    for (uint32_t attempt = 0; attempt < 3u; ++attempt) {
        hw_write(XOSC_BASE + XOSC_CTRL_OFFSET, enable);
        for (volatile uint32_t wait = 0; wait < 240000u; ++wait) {
            if ((hw_read(XOSC_BASE + XOSC_STATUS_OFFSET) &
                 XOSC_STATUS_STABLE_BITS) != 0u) {
                return true;
            }
        }
        hw_write(XOSC_BASE + XOSC_CTRL_OFFSET, disable);
        crude_delay();
    }
    return false;
}

static bool clock_ref_init(void)
{
    hw_write(CLOCKS_BASE + CLOCKS_CLK_REF_DIV_OFFSET,
             1u << CLOCKS_CLK_REF_DIV_INT_LSB);
    hw_write(CLOCKS_BASE + CLOCKS_CLK_REF_CTRL_OFFSET,
             CLOCKS_CLK_REF_CTRL_SRC_VALUE_XOSC_CLKSRC
                 << CLOCKS_CLK_REF_CTRL_SRC_LSB);
    for (volatile uint32_t wait = 0; wait < 200000u; ++wait) {
        if ((hw_read(CLOCKS_BASE + CLOCKS_CLK_REF_SELECTED_OFFSET) &
             (1u << CLOCKS_CLK_REF_CTRL_SRC_VALUE_XOSC_CLKSRC)) != 0u) {
            hw_write(WATCHDOG_BASE + WATCHDOG_TICK_OFFSET,
                     WATCHDOG_TICK_ENABLE_BITS | 12u);
            return true;
        }
    }
    return false;
}

static bool pll_init(uint32_t base, uint32_t reset_bit, uint32_t feedback,
                     uint32_t postdiv1, uint32_t postdiv2)
{
    reset_assert(reset_bit);
    if (!reset_release(reset_bit)) {
        return false;
    }
    hw_write(base + PLL_CS_OFFSET, 1u);
    hw_write(base + PLL_FBDIV_INT_OFFSET, feedback);
    hw_clear(base + PLL_PWR_OFFSET, PLL_PWR_PD_BITS | PLL_PWR_VCOPD_BITS);
    for (volatile uint32_t wait = 0; wait < 500000u; ++wait) {
        if ((hw_read(base + PLL_CS_OFFSET) & PLL_CS_LOCK_BITS) != 0u) {
            hw_write(base + PLL_PRIM_OFFSET,
                     (postdiv1 << PLL_PRIM_POSTDIV1_LSB) |
                     (postdiv2 << PLL_PRIM_POSTDIV2_LSB));
            hw_clear(base + PLL_PWR_OFFSET, PLL_PWR_POSTDIVPD_BITS);
            return true;
        }
    }
    return false;
}

static bool clock_sys_init(void)
{
    uint32_t control = hw_read(CLOCKS_BASE + CLOCKS_CLK_SYS_CTRL_OFFSET);
    control &= ~CLOCKS_CLK_SYS_CTRL_SRC_BITS;
    hw_write(CLOCKS_BASE + CLOCKS_CLK_SYS_CTRL_OFFSET, control);
    bool selected = false;
    for (volatile uint32_t wait = 0; wait < 200000u; ++wait) {
        if ((hw_read(CLOCKS_BASE + CLOCKS_CLK_SYS_SELECTED_OFFSET) & 1u) != 0u) {
            selected = true;
            break;
        }
    }
    if (!selected) {
        return false;
    }

    hw_write(CLOCKS_BASE + CLOCKS_CLK_SYS_DIV_OFFSET,
             1u << CLOCKS_CLK_SYS_DIV_INT_LSB);
    control &= ~CLOCKS_CLK_SYS_CTRL_AUXSRC_BITS;
    control |= CLOCKS_CLK_SYS_CTRL_AUXSRC_VALUE_CLKSRC_PLL_SYS
               << CLOCKS_CLK_SYS_CTRL_AUXSRC_LSB;
    control |= CLOCKS_CLK_SYS_CTRL_SRC_BITS;
    hw_write(CLOCKS_BASE + CLOCKS_CLK_SYS_CTRL_OFFSET, control);
    for (volatile uint32_t wait = 0; wait < 200000u; ++wait) {
        if ((hw_read(CLOCKS_BASE + CLOCKS_CLK_SYS_SELECTED_OFFSET) & 2u) != 0u) {
            hw_write(CLOCKS_BASE + CLOCKS_CLK_PERI_CTRL_OFFSET,
                     CLOCKS_CLK_PERI_CTRL_ENABLE_BITS |
                     (CLOCKS_CLK_PERI_CTRL_AUXSRC_VALUE_CLK_SYS
                      << CLOCKS_CLK_PERI_CTRL_AUXSRC_LSB));
            return true;
        }
    }
    return false;
}

static bool clocks_init(void)
{
    if (!xosc_init() || !clock_ref_init() ||
        !pll_init(PLL_SYS_BASE, RESETS_RESET_PLL_SYS_BITS, 125u, 6u, 2u) ||
        !clock_sys_init() ||
        !pll_init(PLL_USB_BASE, RESETS_RESET_PLL_USB_BITS, 40u, 5u, 2u)) {
        return false;
    }

    hw_write(CLOCKS_BASE + CLOCKS_CLK_ADC_DIV_OFFSET,
             1u << CLOCKS_CLK_ADC_DIV_INT_LSB);
    hw_write(CLOCKS_BASE + CLOCKS_CLK_ADC_CTRL_OFFSET,
             CLOCKS_CLK_ADC_CTRL_ENABLE_BITS |
             (CLOCKS_CLK_ADC_CTRL_AUXSRC_VALUE_CLKSRC_PLL_USB
              << CLOCKS_CLK_ADC_CTRL_AUXSRC_LSB));
    return true;
}

static uint32_t time_us(void)
{
    return hw_read(TIMER_BASE + TIMER_TIMELR_OFFSET);
}

static bool timeout_expired(uint32_t start, uint32_t timeout)
{
    return (uint32_t)(time_us() - start) >= timeout;
}

static void delay_us(uint32_t delay)
{
    uint32_t start = time_us();
    while (!timeout_expired(start, delay)) {
    }
}

static void log_uart_init(void)
{
    gpio_set_function(TESTER_LOG_TX_GPIO, GPIO_FUNC_UART);
    gpio_set_function(TESTER_LOG_RX_GPIO, GPIO_FUNC_UART);
    gpio_set_pulls(TESTER_LOG_TX_GPIO, false, false);
    gpio_set_pulls(TESTER_LOG_RX_GPIO, true, false);

    hw_write(UART0_BASE + UART_UARTCR_OFFSET, 0u);
    hw_write(UART0_BASE + UART_UARTIBRD_OFFSET, 67u);
    hw_write(UART0_BASE + UART_UARTFBRD_OFFSET, 52u);
    hw_write(UART0_BASE + UART_UARTLCR_H_OFFSET,
             (3u << UART_UARTLCR_H_WLEN_LSB) | UART_UARTLCR_H_FEN_BITS);
    hw_write(UART0_BASE + UART_UARTIMSC_OFFSET, 0u);
    hw_write(UART0_BASE + UART_UARTICR_OFFSET, 0x7ffu);
    hw_write(UART0_BASE + UART_UARTCR_OFFSET,
             UART_UARTCR_UARTEN_BITS | UART_UARTCR_TXE_BITS |
             UART_UARTCR_RXE_BITS);
}

static void log_putc(char value)
{
    uint32_t start = time_us();
    while ((hw_read(UART0_BASE + UART_UARTFR_OFFSET) &
            UART_UARTFR_TXFF_BITS) != 0u) {
        if (timeout_expired(start, 100000u)) {
            return;
        }
    }
    hw_write(UART0_BASE + UART_UARTDR_OFFSET, (uint32_t)(uint8_t)value);
}

static void log_puts(const char *value)
{
    while (*value != '\0') {
        if (*value == '\n') {
            log_putc('\r');
        }
        log_putc(*value++);
    }
}

static void log_hex16(uint16_t value)
{
    static const char digits[] = "0123456789ABCDEF";
    for (uint32_t shift = 12u;; shift -= 4u) {
        log_putc(digits[(value >> shift) & 0x0fu]);
        if (shift == 0u) {
            return;
        }
    }
}

// Pre-generated from Raspberry Pi's BSD-3-Clause pico-examples uart_rx_mini
// and uart_tx PIO programs. RX occupies instructions 0-3 and TX occupies 4-7.
static const uint16_t pio_uart_rx_program[] = {
    0x2020u, // wait 0 pin 0
    0xea27u, // set x, 7 [10]
    0x4001u, // in pins, 1
    0x0642u, // jmp x--, 2 [6]
};

static const uint16_t pio_uart_tx_program[] = {
    0x9fa0u, // pull block side 1 [7]
    0xf727u, // set x, 7 side 0 [7]
    0x6001u, // out pins, 1
    0x0646u, // jmp x--, 6 [6] (relocated to offset 4)
};

static uint32_t pio_sm_address(uint32_t offset, uint32_t state_machine)
{
    return PIO0_BASE + offset + state_machine * PIO_SM_STRIDE;
}

static bool uart_init(void)
{
    reset_assert(RESETS_RESET_PIO0_BITS);
    if (!reset_release(RESETS_RESET_PIO0_BITS)) {
        return false;
    }
    hw_write(PIO0_BASE + PIO_CTRL_OFFSET, 0u);

    gpio_set_function(DUT_UART_TX_TESTER_RX_GPIO, GPIO_FUNC_PIO);
    gpio_set_function(DUT_UART_RX_TESTER_TX_GPIO, GPIO_FUNC_PIO);
    gpio_set_pulls(DUT_UART_TX_TESTER_RX_GPIO, true, false);
    gpio_set_pulls(DUT_UART_RX_TESTER_TX_GPIO, true, false);

    for (size_t i = 0; i < sizeof(pio_uart_rx_program) /
                                  sizeof(pio_uart_rx_program[0]); ++i) {
        hw_write(PIO0_BASE + PIO_INSTR_MEM0_OFFSET + i * PIO_INSTR_STRIDE,
                 pio_uart_rx_program[i]);
    }
    for (size_t i = 0; i < sizeof(pio_uart_tx_program) /
                                  sizeof(pio_uart_tx_program[0]); ++i) {
        hw_write(PIO0_BASE + PIO_INSTR_MEM0_OFFSET +
                 (i + PIO_TX_OFFSET) * PIO_INSTR_STRIDE,
                 pio_uart_tx_program[i]);
    }

    // 125 MHz / (135 + 162/256) / 8 = 115200.7 baud.
    uint32_t divider = (135u << PIO_SM0_CLKDIV_INT_LSB) |
                       (162u << PIO_SM0_CLKDIV_FRAC_LSB);
    hw_write(pio_sm_address(PIO_SM0_CLKDIV_OFFSET, PIO_RX_SM), divider);
    hw_write(pio_sm_address(PIO_SM0_EXECCTRL_OFFSET, PIO_RX_SM),
             (3u << PIO_SM0_EXECCTRL_WRAP_TOP_LSB) |
             (PIO_RX_OFFSET << PIO_SM0_EXECCTRL_WRAP_BOTTOM_LSB));
    hw_write(pio_sm_address(PIO_SM0_SHIFTCTRL_OFFSET, PIO_RX_SM),
             PIO_SM0_SHIFTCTRL_FJOIN_RX_BITS |
             PIO_SM0_SHIFTCTRL_IN_SHIFTDIR_BITS |
             PIO_SM0_SHIFTCTRL_AUTOPUSH_BITS |
             (8u << PIO_SM0_SHIFTCTRL_PUSH_THRESH_LSB));
    hw_write(pio_sm_address(PIO_SM0_PINCTRL_OFFSET, PIO_RX_SM),
             DUT_UART_TX_TESTER_RX_GPIO << PIO_SM0_PINCTRL_IN_BASE_LSB);
    hw_write(pio_sm_address(PIO_SM0_INSTR_OFFSET, PIO_RX_SM), PIO_RX_OFFSET);

    hw_write(pio_sm_address(PIO_SM0_CLKDIV_OFFSET, PIO_TX_SM), divider);
    hw_write(pio_sm_address(PIO_SM0_EXECCTRL_OFFSET, PIO_TX_SM),
             PIO_SM0_EXECCTRL_SIDE_EN_BITS |
             (7u << PIO_SM0_EXECCTRL_WRAP_TOP_LSB) |
             (PIO_TX_OFFSET << PIO_SM0_EXECCTRL_WRAP_BOTTOM_LSB));
    hw_write(pio_sm_address(PIO_SM0_SHIFTCTRL_OFFSET, PIO_TX_SM),
             PIO_SM0_SHIFTCTRL_FJOIN_TX_BITS |
             PIO_SM0_SHIFTCTRL_OUT_SHIFTDIR_BITS);
    hw_write(pio_sm_address(PIO_SM0_PINCTRL_OFFSET, PIO_TX_SM),
             (2u << PIO_SM0_PINCTRL_SIDESET_COUNT_LSB) |
             (1u << PIO_SM0_PINCTRL_SET_COUNT_LSB) |
             (1u << PIO_SM0_PINCTRL_OUT_COUNT_LSB) |
             (DUT_UART_RX_TESTER_TX_GPIO <<
              PIO_SM0_PINCTRL_SIDESET_BASE_LSB) |
             (DUT_UART_RX_TESTER_TX_GPIO << PIO_SM0_PINCTRL_SET_BASE_LSB) |
             (DUT_UART_RX_TESTER_TX_GPIO << PIO_SM0_PINCTRL_OUT_BASE_LSB));
    hw_write(pio_sm_address(PIO_SM0_INSTR_OFFSET, PIO_TX_SM), 0xe001u);
    hw_write(pio_sm_address(PIO_SM0_INSTR_OFFSET, PIO_TX_SM), 0xe081u);
    hw_write(pio_sm_address(PIO_SM0_INSTR_OFFSET, PIO_TX_SM), PIO_TX_OFFSET);

    hw_write(PIO0_BASE + PIO_CTRL_OFFSET,
             (1u << (PIO_CTRL_SM_RESTART_LSB + PIO_RX_SM)) |
             (1u << (PIO_CTRL_SM_RESTART_LSB + PIO_TX_SM)) |
             (1u << (PIO_CTRL_CLKDIV_RESTART_LSB + PIO_RX_SM)) |
             (1u << (PIO_CTRL_CLKDIV_RESTART_LSB + PIO_TX_SM)));
    hw_write(PIO0_BASE + PIO_CTRL_OFFSET,
             (1u << PIO_RX_SM) | (1u << PIO_TX_SM));
    return true;
}

static void uart_release(void)
{
    hw_write(PIO0_BASE + PIO_CTRL_OFFSET, 0u);
    gpio_input_init(DUT_UART_RX_TESTER_TX_GPIO);
    gpio_input_init(DUT_UART_TX_TESTER_RX_GPIO);
}

static void uart_putc(char value)
{
    uint32_t start = time_us();
    uint32_t full = 1u << (PIO_FSTAT_TXFULL_LSB + PIO_TX_SM);
    while ((hw_read(PIO0_BASE + PIO_FSTAT_OFFSET) & full) != 0u) {
        if (timeout_expired(start, 100000u)) {
            return;
        }
    }
    hw_write(PIO0_BASE + PIO_TXF0_OFFSET + PIO_TX_SM * PIO_TXF_STRIDE,
             (uint32_t)(uint8_t)value);
}

static void uart_puts(const char *value)
{
    while (*value != '\0') {
        uart_putc(*value++);
    }
}

static bool uart_getc(char *value)
{
    uint32_t empty = 1u << (PIO_FSTAT_RXEMPTY_LSB + PIO_RX_SM);
    if ((hw_read(PIO0_BASE + PIO_FSTAT_OFFSET) & empty) != 0u) {
        return false;
    }
    uint32_t data = hw_read(PIO0_BASE + PIO_RXF0_OFFSET +
                            PIO_RX_SM * PIO_RXF_STRIDE);
    *value = (char)(data >> 24);
    return true;
}

static void uart_drain(void)
{
    char ignored;
    while (uart_getc(&ignored)) {
    }
}

static bool dut_power_quick(void)
{
    uint16_t sample;
    return adc_read(&sample) && sample >= DUT_3V3_ADC_PRESENT_MIN;
}

static bool string_equal(const char *left, const char *right)
{
    while (*left != '\0' && *right != '\0') {
        if (*left++ != *right++) {
            return false;
        }
    }
    return *left == *right;
}

static bool string_starts(const char *value, const char *prefix)
{
    while (*prefix != '\0') {
        if (*value++ != *prefix++) {
            return false;
        }
    }
    return true;
}

static bool string_ends(const char *value, const char *suffix)
{
    size_t value_length = 0u;
    size_t suffix_length = 0u;
    while (value[value_length] != '\0') {
        ++value_length;
    }
    while (suffix[suffix_length] != '\0') {
        ++suffix_length;
    }
    if (suffix_length > value_length) {
        return false;
    }
    return string_equal(value + value_length - suffix_length, suffix);
}

static void bus_release(void)
{
    gpio_input_init(DUT_SDA_GPIO);
    gpio_input_init(DUT_SCL_GPIO);
    gpio_put(DUT_SDA_GPIO, false);
    gpio_put(DUT_SCL_GPIO, false);
}

static void bus_pull_low(uint32_t gpio, bool pull_low)
{
    if (pull_low) {
        gpio_put(gpio, false);
        hw_write(SIO_BASE + SIO_GPIO_OE_SET_OFFSET, 1u << gpio);
    } else {
        hw_write(SIO_BASE + SIO_GPIO_OE_CLR_OFFSET, 1u << gpio);
    }
}

static bool delay_while_dut_powered(uint32_t duration)
{
    uint32_t start = time_us();
    uint32_t power_check = start;
    while (!timeout_expired(start, duration)) {
        if (timeout_expired(power_check, DUT_POWER_POLL_US)) {
            power_check = time_us();
            if (!dut_power_quick()) {
                bus_release();
                uart_release();
                return false;
            }
        }
    }
    return true;
}

static bool exercise_passive_bus(void)
{
    bus_release();
    if (!delay_while_dut_powered(50000u)) {
        return false;
    }
    bool idle = gpio_get(DUT_SDA_GPIO) && gpio_get(DUT_SCL_GPIO);

    bus_pull_low(DUT_SDA_GPIO, true);
    if (!delay_while_dut_powered(150000u)) {
        return false;
    }
    bool sda_low = !gpio_get(DUT_SDA_GPIO);
    bus_pull_low(DUT_SDA_GPIO, false);
    if (!delay_while_dut_powered(150000u)) {
        return false;
    }
    bool sda_high = gpio_get(DUT_SDA_GPIO);

    bus_pull_low(DUT_SCL_GPIO, true);
    if (!delay_while_dut_powered(150000u)) {
        return false;
    }
    bool scl_low = !gpio_get(DUT_SCL_GPIO);
    bus_pull_low(DUT_SCL_GPIO, false);
    if (!delay_while_dut_powered(150000u)) {
        return false;
    }
    bool scl_high = gpio_get(DUT_SCL_GPIO);

    return idle && sda_low && sda_high && scl_low && scl_high;
}

static void sample_i2c(struct command_state *state)
{
    bool sda = gpio_get(DUT_SDA_GPIO);
    bool scl = gpio_get(DUT_SCL_GPIO);
    state->sda_high |= sda;
    state->sda_low |= !sda;
    state->scl_high |= scl;
    state->scl_low |= !scl;
}

static uint32_t result_bit(const char *line)
{
    if (!string_starts(line, "RESULT ")) {
        return 0u;
    }
    const char *name = line + 7;
    for (size_t i = 0; i < sizeof(result_names) / sizeof(result_names[0]); ++i) {
        const char *expected = result_names[i].name;
        const char *actual = name;
        while (*expected != '\0' && *actual == *expected) {
            ++expected;
            ++actual;
        }
        if (*expected == '\0' && *actual == ' ') {
            return result_names[i].bit;
        }
    }
    return 0u;
}

static void process_line(struct command_state *state, const char *line)
{
    if (string_starts(line, "RESULT ")) {
        uint32_t bit = result_bit(line);
        if (!string_ends(line, " PASS")) {
            state->failed = true;
        }
        state->seen |= bit;
    }

    if (state->run_command && string_starts(line, "FIXTURE PASSIVE START")) {
        state->passive_exercised = exercise_passive_bus();
    } else if (state->run_command &&
               string_starts(line, "FIXTURE I2C START")) {
        bus_release();
        state->capture_i2c = true;
        sample_i2c(state);
    } else if (state->run_command &&
               string_starts(line, "FIXTURE I2C END")) {
        sample_i2c(state);
        state->capture_i2c = false;
    } else if (state->run_command && string_starts(line, "FIXTURE END")) {
        state->fixture_end = true;
    }
}

static bool collect_command(const char *command, uint32_t expected,
                            bool run_command)
{
    struct command_state state;
    state.expected = expected;
    state.seen = 0u;
    state.failed = false;
    state.run_command = run_command;
    state.fixture_end = false;
    state.passive_exercised = false;
    state.capture_i2c = false;
    state.sda_high = false;
    state.sda_low = false;
    state.scl_high = false;
    state.scl_low = false;
    char line[128];
    size_t used = 0u;
    uint32_t start = time_us();
    uint32_t power_check = start;

    uart_puts(command);
    uart_putc('\n');
    while (!timeout_expired(start, DUT_COMMAND_TIMEOUT_US)) {
        if (timeout_expired(power_check, DUT_POWER_POLL_US)) {
            power_check = time_us();
            if (!dut_power_quick()) {
                uart_release();
                bus_release();
                return false;
            }
        }
        if (state.capture_i2c) {
            sample_i2c(&state);
        }

        char value;
        if (!uart_getc(&value)) {
            continue;
        }
        if (value == '\r') {
            continue;
        }
        if (value == '\n') {
            if (used != 0u) {
                line[used] = '\0';
                process_line(&state, line);
                used = 0u;
            }
        } else if (used + 1u < sizeof(line)) {
            line[used++] = value;
        } else {
            state.failed = true;
            used = 0u;
        }

        bool complete = run_command ? state.fixture_end :
                        ((state.seen & expected) == expected);
        if (complete) {
            bool results_ok = (state.seen & expected) == expected &&
                              !state.failed;
            if (!run_command) {
                return results_ok;
            }
            bool i2c_seen = state.sda_high && state.sda_low &&
                            state.scl_high && state.scl_low;
            return results_ok && state.passive_exercised && i2c_seen;
        }
    }
    bus_release();
    return false;
}

static bool wait_for_dut_prompt(void)
{
    static const char marker[] = "debug> ";
    size_t matched = 0u;
    uint32_t start = time_us();
    uint32_t power_check = start;

    while (!timeout_expired(start, DUT_BOOT_TIMEOUT_US)) {
        if (timeout_expired(power_check, DUT_POWER_POLL_US)) {
            power_check = time_us();
            if (!dut_power_quick()) {
                uart_release();
                return false;
            }
        }
        char value;
        if (!uart_getc(&value)) {
            continue;
        }
        if (value == marker[matched]) {
            ++matched;
            if (marker[matched] == '\0') {
                return true;
            }
        } else {
            matched = value == marker[0] ? 1u : 0u;
        }
    }
    return false;
}

static bool adc_init(void)
{
    gpio_set_function(DUT_3V3_ADC_GPIO, GPIO_FUNC_NULL);
    uint32_t pad = hw_read(gpio_pad_address(DUT_3V3_ADC_GPIO));
    pad &= ~(PADS_BANK0_GPIO0_IE_BITS | PADS_BANK0_GPIO0_PUE_BITS |
             PADS_BANK0_GPIO0_PDE_BITS);
    hw_write(gpio_pad_address(DUT_3V3_ADC_GPIO), pad);

    hw_write(ADC_BASE + ADC_CS_OFFSET,
             ADC_CS_EN_BITS |
             (DUT_3V3_ADC_CHANNEL << ADC_CS_AINSEL_LSB));
    uint32_t start = time_us();
    while ((hw_read(ADC_BASE + ADC_CS_OFFSET) & ADC_CS_READY_BITS) == 0u) {
        if (timeout_expired(start, 100000u)) {
            return false;
        }
    }
    return true;
}

static bool adc_read(uint16_t *result)
{
    uint32_t control = ADC_CS_EN_BITS |
        (DUT_3V3_ADC_CHANNEL << ADC_CS_AINSEL_LSB);
    hw_write(ADC_BASE + ADC_CS_OFFSET, control | ADC_CS_START_ONCE_BITS);
    uint32_t start = time_us();
    while ((hw_read(ADC_BASE + ADC_CS_OFFSET) & ADC_CS_READY_BITS) == 0u) {
        if (timeout_expired(start, 100000u)) {
            return false;
        }
    }
    if ((hw_read(ADC_BASE + ADC_CS_OFFSET) & ADC_CS_ERR_BITS) != 0u) {
        return false;
    }
    *result = (uint16_t)(hw_read(ADC_BASE + ADC_RESULT_OFFSET) & ADC_RESULT_BITS);
    return true;
}

static bool dut_voltage(uint16_t *average)
{
    uint32_t total = 0u;
    for (uint32_t i = 0; i < DUT_3V3_ADC_SAMPLES; ++i) {
        uint16_t sample;
        if (!adc_read(&sample)) {
            return false;
        }
        total += sample;
        delay_us(1000u);
    }
    *average = (uint16_t)(total >> 4);
    return true;
}

static bool dut_present(void)
{
    uint16_t average;
    return dut_voltage(&average) && average >= DUT_3V3_ADC_PRESENT_MIN;
}

static bool run_unit(void)
{
    uint16_t voltage;
    if (!dut_voltage(&voltage)) {
        log_puts("POWER ADC_ERROR\n");
        return false;
    }
    log_puts("POWER ADC=0x");
    log_hex16(voltage);
    log_puts("\n");
    if (voltage < DUT_3V3_ADC_MIN || voltage > DUT_3V3_ADC_MAX) {
        log_puts("POWER FAIL\n");
        return false;
    }
    log_puts("POWER PASS\n");

    if (!uart_init()) {
        log_puts("DUT_UART INIT_FAIL\n");
        return false;
    }
    uart_drain();
    if (!wait_for_dut_prompt()) {
        log_puts("DUT_UART PROMPT_FAIL\n");
        return false;
    }
    log_puts("DUT_UART PROMPT_PASS\nRUN START\n");
    if (!collect_command("run", RUN_RESULTS, true)) {
        log_puts("RUN FAIL\n");
        return false;
    }
    log_puts("RUN PASS\n");

    if (!tester_wp_high) {
        log_puts("PROTECTED_RW START\n");
        bool protected_pass = collect_command("protected-rw",
                                              PREPROVISION_RESULTS, false);
        log_puts(protected_pass ? "PROTECTED_RW PASS\n" :
                                  "PROTECTED_RW FAIL\n");
        return protected_pass;
    }

    log_puts("WP_CHECK START\n");
    bool wp_pass = collect_command("wp-check", FINAL_RESULTS, false);
    log_puts(wp_pass ? "WP_CHECK PASS\n" : "WP_CHECK FAIL\n");
    return wp_pass;
}

int main(void)
{
    if (!reset_release(RESET_BANK0_MASK)) {
        for (;;) {
        }
    }
    indicators_init();
    indicators_set(false, false, true);

    if (!clocks_init() || !reset_release(RESET_RUNTIME_MASK)) {
        fatal_blink();
    }
    gpio_input_init(TESTER_MODE_GPIO);
    gpio_set_pulls(TESTER_MODE_GPIO, true, false);
    delay_us(1000u);
    tester_wp_high = gpio_get(TESTER_MODE_GPIO);

    log_uart_init();
    log_puts("SIGNAL-BOX TESTER ");
    log_puts(TESTER_FIRMWARE_VERSION);
    log_puts(tester_wp_high ? " MODE=WP_ON D10=HIGH\n" :
                              " MODE=WP_OFF D10=LOW\n");

    uart_release();
    bus_release();
    if (!adc_init()) {
        log_puts("TESTER ADC_INIT_FAIL\n");
        fatal_blink();
    }

    for (;;) {
        indicators_set(false, false, false);
        log_puts("WAITING FOR DUT\n");
        while (!dut_present()) {
            delay_us(50000u);
        }
        log_puts("DUT DETECTED\n");
        indicators_set(false, false, true);
        delay_us(DUT_POWER_SETTLE_US);

        bool pass = run_unit();
        uart_release();
        bus_release();
        indicators_set(!pass, pass, false);
        log_puts(pass ? "OVERALL PASS\n" : "OVERALL FAIL\n");

        while (dut_present()) {
            delay_us(50000u);
        }
        log_puts("DUT REMOVED\n");
        delay_us(DUT_REMOVAL_FILTER_US);
    }
}
