#include "config.h"
#include "hw.h"
#ifdef SIGNAL_BOX_SECURITY_PROFILE
#include "security_profile.h"
#endif

#define GPIO_FUNC_UART IO_BANK0_GPIO0_CTRL_FUNCSEL_VALUE_UART0_TX
#define GPIO_FUNC_I2C IO_BANK0_GPIO0_CTRL_FUNCSEL_VALUE_I2C0_SDA
#if PICO_RP2350
#define GPIO_FUNC_SIO IO_BANK0_GPIO0_CTRL_FUNCSEL_VALUE_SIOB_PROC_0
#define DEBUG_TIMER_BASE TIMER0_BASE
#define DEBUG_TIMER_RESET RESETS_RESET_TIMER0_BITS
#if SYS_CLK_HZ != 125000000
#error "The debug UART/I2C divisors require SYS_CLK_HZ=125000000"
#endif
#else
#define GPIO_FUNC_SIO IO_BANK0_GPIO0_CTRL_FUNCSEL_VALUE_SIO_0
#define DEBUG_TIMER_BASE TIMER_BASE
#define DEBUG_TIMER_RESET RESETS_RESET_TIMER_BITS
#endif

#define RESET_BANK0_MASK \
    (RESETS_RESET_IO_BANK0_BITS | RESETS_RESET_PADS_BANK0_BITS)
#define RESET_RUNTIME_MASK \
    (RESETS_RESET_I2C1_BITS | RESETS_RESET_SYSCFG_BITS | \
     DEBUG_TIMER_RESET | RESETS_RESET_UART0_BITS)

#if !PICO_RP2350
static uint32_t xosc_attempts;
#endif
static uint32_t last_i2c_abort;
static uint8_t preflight_address_map;
static bool preflight_bus_idle;
static bool preflight_eeprom_ack;
static bool preflight_led_gpio;

static void crude_delay(void)
{
#if PICO_RP2350
    // SDK startup has already initialized TIMER0 and its 1 MHz tick source.
    uint32_t start = hw_read(DEBUG_TIMER_BASE + TIMER_TIMERAWL_OFFSET);
    while ((uint32_t)(hw_read(DEBUG_TIMER_BASE + TIMER_TIMERAWL_OFFSET) -
                      start) < 100000u) {
    }
#else
    for (volatile uint32_t i = 0; i < 180000u; ++i) {
        __asm volatile ("nop");
    }
#endif
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
#if PICO_RP2350
    // RP2350 pads start isolated; selecting a peripheral alone is not enough.
    value &= ~PADS_BANK0_GPIO0_ISO_BITS;
#endif
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
    uint32_t mask = 1u << gpio;
    gpio_set_function(gpio, GPIO_FUNC_SIO);
    gpio_set_pulls(gpio, false, false);
    hw_write(SIO_BASE + SIO_GPIO_OE_CLR_OFFSET, mask);
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

static void boot_led_put(bool on)
{
    gpio_put(BOOT_LED_GPIO, !on); // Blue on RP2040, yellow on RP2350; active-low.
}

static void boot_blinks(uint32_t count)
{
    for (uint32_t i = 0; i < count; ++i) {
        boot_led_put(true);
        crude_delay();
        boot_led_put(false);
        crude_delay();
    }
    crude_delay();
}

#if !PICO_RP2350
// RP2040 retains its proven custom clock path. RP2350 uses SDK startup.
static bool xosc_init(void)
{
    const uint32_t enable =
        (XOSC_CTRL_ENABLE_VALUE_ENABLE << XOSC_CTRL_ENABLE_LSB) |
        (XOSC_CTRL_FREQ_RANGE_VALUE_1_15MHZ << XOSC_CTRL_FREQ_RANGE_LSB);
    const uint32_t disable =
        (XOSC_CTRL_ENABLE_VALUE_DISABLE << XOSC_CTRL_ENABLE_LSB) |
        (XOSC_CTRL_FREQ_RANGE_VALUE_1_15MHZ << XOSC_CTRL_FREQ_RANGE_LSB);

    hw_write(XOSC_BASE + XOSC_STARTUP_OFFSET, 47u);
    for (xosc_attempts = 1u; xosc_attempts <= 3u; ++xosc_attempts) {
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

static bool clock_pll_init(void)
{
    reset_assert(RESETS_RESET_PLL_SYS_BITS);
    if (!reset_release(RESETS_RESET_PLL_SYS_BITS)) {
        return false;
    }

    hw_write(PLL_SYS_BASE + PLL_CS_OFFSET, 1u);
    hw_write(PLL_SYS_BASE + PLL_FBDIV_INT_OFFSET, 125u);
    hw_clear(PLL_SYS_BASE + PLL_PWR_OFFSET,
             PLL_PWR_PD_BITS | PLL_PWR_VCOPD_BITS);
    for (volatile uint32_t wait = 0; wait < 500000u; ++wait) {
        if ((hw_read(PLL_SYS_BASE + PLL_CS_OFFSET) & PLL_CS_LOCK_BITS) != 0u) {
            hw_write(PLL_SYS_BASE + PLL_PRIM_OFFSET,
                     (6u << PLL_PRIM_POSTDIV1_LSB) |
                     (2u << PLL_PRIM_POSTDIV2_LSB));
            hw_clear(PLL_SYS_BASE + PLL_PWR_OFFSET, PLL_PWR_POSTDIVPD_BITS);
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

#endif

static uint32_t time_us(void)
{
    return hw_read(DEBUG_TIMER_BASE + TIMER_TIMELR_OFFSET);
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

static void uart_init(void)
{
    gpio_set_function(UART_TX_GPIO, GPIO_FUNC_UART);
    gpio_set_function(UART_RX_GPIO, GPIO_FUNC_UART);
    gpio_set_pulls(UART_TX_GPIO, false, false);
    gpio_set_pulls(UART_RX_GPIO, true, false);

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

static void uart_putc_raw(char value)
{
    while ((hw_read(UART0_BASE + UART_UARTFR_OFFSET) &
            UART_UARTFR_TXFF_BITS) != 0u) {
    }
    hw_write(UART0_BASE + UART_UARTDR_OFFSET, (uint32_t)(uint8_t)value);
}

static void uart_putc(char value)
{
    if (value == '\n') {
        uart_putc_raw('\r');
    }
    uart_putc_raw(value);
}

static void uart_puts(const char *value)
{
    while (*value != '\0') {
        uart_putc(*value++);
    }
}

static void uart_put_hex8(uint8_t value)
{
    static const char digits[] = "0123456789ABCDEF";
    uart_putc(digits[(value >> 4) & 0x0fu]);
    uart_putc(digits[value & 0x0fu]);
}

static void uart_put_hex16(uint16_t value)
{
    uart_put_hex8((uint8_t)(value >> 8));
    uart_put_hex8((uint8_t)value);
}

static void uart_put_hex32(uint32_t value)
{
    uart_put_hex16((uint16_t)(value >> 16));
    uart_put_hex16((uint16_t)value);
}

static void uart_put_u32(uint32_t value)
{
    static const uint32_t powers[] = {
        1000000000u, 100000000u, 10000000u, 1000000u, 100000u,
        10000u, 1000u, 100u, 10u, 1u
    };
    bool started = false;

    for (size_t i = 0; i < sizeof(powers) / sizeof(powers[0]); ++i) {
        char digit = '0';
        while (value >= powers[i]) {
            value -= powers[i];
            ++digit;
        }
        if (digit != '0' || started || powers[i] == 1u) {
            uart_putc(digit);
            started = true;
        }
    }
}

static bool uart_getc(char *value)
{
    if ((hw_read(UART0_BASE + UART_UARTFR_OFFSET) & UART_UARTFR_RXFE_BITS) != 0u) {
        return false;
    }
    *value = (char)(hw_read(UART0_BASE + UART_UARTDR_OFFSET) & 0xffu);
    return true;
}

static void report(const char *name, bool pass)
{
    uart_puts("RESULT ");
    uart_puts(name);
    uart_putc(' ');
    uart_puts(pass ? "PASS\n" : "FAIL\n");
}

static bool i2c_set_target(uint8_t address)
{
    hw_write(I2C1_BASE + I2C_IC_ENABLE_OFFSET, 0u);
    uint32_t start = time_us();
    while ((hw_read(I2C1_BASE + I2C_IC_ENABLE_STATUS_OFFSET) &
            I2C_IC_ENABLE_STATUS_IC_EN_BITS) != 0u) {
        if (timeout_expired(start, I2C_TRANSACTION_TIMEOUT_US)) {
            return false;
        }
    }
    hw_write(I2C1_BASE + I2C_IC_TAR_OFFSET, address);
    hw_write(I2C1_BASE + I2C_IC_ENABLE_OFFSET, 1u);
    return true;
}

static bool i2c_configure(void)
{
    reset_assert(RESETS_RESET_I2C1_BITS);
    if (!reset_release(RESETS_RESET_I2C1_BITS)) {
        return false;
    }

    gpio_set_function(EEPROM_SDA_GPIO, GPIO_FUNC_I2C);
    gpio_set_function(EEPROM_SCL_GPIO, GPIO_FUNC_I2C);
    gpio_set_pulls(EEPROM_SDA_GPIO, false, false);
    gpio_set_pulls(EEPROM_SCL_GPIO, false, false);

    hw_write(I2C1_BASE + I2C_IC_ENABLE_OFFSET, 0u);
    hw_write(I2C1_BASE + I2C_IC_CON_OFFSET,
             I2C_IC_CON_MASTER_MODE_BITS |
             (I2C_IC_CON_SPEED_VALUE_FAST << I2C_IC_CON_SPEED_LSB) |
             I2C_IC_CON_IC_RESTART_EN_BITS |
             I2C_IC_CON_IC_SLAVE_DISABLE_BITS);
    hw_write(I2C1_BASE + I2C_IC_FS_SCL_HCNT_OFFSET, 500u);
    hw_write(I2C1_BASE + I2C_IC_FS_SCL_LCNT_OFFSET, 750u);
    hw_write(I2C1_BASE + I2C_IC_FS_SPKLEN_OFFSET, 46u);
    hw_write(I2C1_BASE + I2C_IC_SDA_HOLD_OFFSET, 38u);
    return i2c_set_target(EEPROM_I2C_ADDRESS);
}

static bool i2c_failed(void)
{
    if ((hw_read(I2C1_BASE + I2C_IC_RAW_INTR_STAT_OFFSET) &
         I2C_IC_RAW_INTR_STAT_TX_ABRT_BITS) == 0u) {
        return false;
    }
    last_i2c_abort = hw_read(I2C1_BASE + I2C_IC_TX_ABRT_SOURCE_OFFSET);
    (void)hw_read(I2C1_BASE + I2C_IC_CLR_TX_ABRT_OFFSET);
    return true;
}

static bool i2c_wait_idle(uint32_t start)
{
    for (;;) {
        uint32_t status = hw_read(I2C1_BASE + I2C_IC_STATUS_OFFSET);
        if (i2c_failed()) {
            return false;
        }
        if ((status & I2C_IC_STATUS_TFE_BITS) != 0u &&
            (status & I2C_IC_STATUS_MST_ACTIVITY_BITS) == 0u) {
            return true;
        }
        if (timeout_expired(start, I2C_TRANSACTION_TIMEOUT_US)) {
            last_i2c_abort = 0xffffffffu;
            return false;
        }
    }
}

static void i2c_recover(void)
{
    (void)i2c_configure();
}

static bool i2c_probe_address(uint8_t address)
{
    last_i2c_abort = 0u;
    if (!i2c_set_target(address)) {
        last_i2c_abort = 0xffffffffu;
        i2c_recover();
        return false;
    }

    hw_write(I2C1_BASE + I2C_IC_DATA_CMD_OFFSET,
             I2C_IC_DATA_CMD_CMD_BITS | I2C_IC_DATA_CMD_STOP_BITS);
    uint32_t start = time_us();
    for (;;) {
        if (i2c_failed() || timeout_expired(start, I2C_TRANSACTION_TIMEOUT_US)) {
            if (last_i2c_abort == 0u) {
                last_i2c_abort = 0xffffffffu;
            }
            i2c_recover();
            return false;
        }
        if ((hw_read(I2C1_BASE + I2C_IC_STATUS_OFFSET) &
             I2C_IC_STATUS_RFNE_BITS) != 0u) {
            (void)hw_read(I2C1_BASE + I2C_IC_DATA_CMD_OFFSET);
            if (!i2c_wait_idle(start)) {
                i2c_recover();
                return false;
            }
            return true;
        }
    }
}

static uint8_t i2c_scan_eeprom_straps(void)
{
    uint8_t map = 0u;
    for (uint8_t address = 0x50u; address <= 0x57u; ++address) {
        if (i2c_probe_address(address)) {
            map |= (uint8_t)(1u << (address - 0x50u));
        }
    }
    (void)i2c_set_target(EEPROM_I2C_ADDRESS);
    last_i2c_abort = 0u;
    return map;
}

static bool eeprom_read(uint16_t address, uint8_t *data, size_t length)
{
    if (length == 0u || length > 8u) {
        return false;
    }

    last_i2c_abort = 0u;
    if (!i2c_set_target(EEPROM_I2C_ADDRESS)) {
        last_i2c_abort = 0xffffffffu;
        i2c_recover();
        return false;
    }
    hw_write(I2C1_BASE + I2C_IC_DATA_CMD_OFFSET, (uint8_t)(address >> 8));
    hw_write(I2C1_BASE + I2C_IC_DATA_CMD_OFFSET, (uint8_t)address);
    for (size_t i = 0; i < length; ++i) {
        uint32_t command = I2C_IC_DATA_CMD_CMD_BITS;
        if (i == 0u) {
            command |= I2C_IC_DATA_CMD_RESTART_BITS;
        }
        if (i + 1u == length) {
            command |= I2C_IC_DATA_CMD_STOP_BITS;
        }
        hw_write(I2C1_BASE + I2C_IC_DATA_CMD_OFFSET, command);
    }

    uint32_t start = time_us();
    size_t received = 0u;
    while (received < length) {
        if (i2c_failed() || timeout_expired(start, I2C_TRANSACTION_TIMEOUT_US)) {
            if (last_i2c_abort == 0u) {
                last_i2c_abort = 0xffffffffu;
            }
            i2c_recover();
            return false;
        }
        if ((hw_read(I2C1_BASE + I2C_IC_STATUS_OFFSET) &
             I2C_IC_STATUS_RFNE_BITS) != 0u) {
            data[received++] = (uint8_t)hw_read(I2C1_BASE + I2C_IC_DATA_CMD_OFFSET);
        }
    }
    if (!i2c_wait_idle(start)) {
        i2c_recover();
        return false;
    }
    return true;
}

static bool eeprom_write_page(uint16_t address, const uint8_t *data, size_t length)
{
    if (length == 0u || length > EEPROM_RW_TEST_LENGTH ||
        ((uint32_t)address + length) > EEPROM_SIZE ||
        ((address & (EEPROM_PAGE_SIZE - 1u)) + length) > EEPROM_PAGE_SIZE) {
        return false;
    }

    last_i2c_abort = 0u;
    if (!i2c_set_target(EEPROM_I2C_ADDRESS)) {
        last_i2c_abort = 0xffffffffu;
        i2c_recover();
        return false;
    }
    hw_write(I2C1_BASE + I2C_IC_DATA_CMD_OFFSET, (uint8_t)(address >> 8));
    hw_write(I2C1_BASE + I2C_IC_DATA_CMD_OFFSET, (uint8_t)address);
    for (size_t i = 0; i < length; ++i) {
        uint32_t command = data[i];
        if (i + 1u == length) {
            command |= I2C_IC_DATA_CMD_STOP_BITS;
        }
        hw_write(I2C1_BASE + I2C_IC_DATA_CMD_OFFSET, command);
    }

    uint32_t start = time_us();
    if (!i2c_wait_idle(start)) {
        i2c_recover();
        return false;
    }

    start = time_us();
    uint8_t ignored;
    while (!timeout_expired(start, EEPROM_WRITE_TIMEOUT_US)) {
        delay_us(250u);
        if (eeprom_read(address, &ignored, 1u)) {
            return true;
        }
    }
    return false;
}

static bool bytes_equal(const uint8_t *left, const uint8_t *right, size_t length)
{
    for (size_t i = 0; i < length; ++i) {
        if (left[i] != right[i]) {
            return false;
        }
    }
    return true;
}

static bool test_bus_idle(void)
{
    gpio_input_init(EEPROM_SDA_GPIO);
    gpio_input_init(EEPROM_SCL_GPIO);
    delay_us(100u);
    return gpio_get(EEPROM_SDA_GPIO) && gpio_get(EEPROM_SCL_GPIO);
}

static bool fixture_passive_bus_test(void)
{
    gpio_input_init(EEPROM_SDA_GPIO);
    gpio_input_init(EEPROM_SCL_GPIO);
    bool sda_high = gpio_get(EEPROM_SDA_GPIO);
    bool scl_high = gpio_get(EEPROM_SCL_GPIO);
    bool sda_low = false;
    bool scl_low = false;
    uint32_t start = time_us();

    uart_puts("FIXTURE PASSIVE START duration-ms=3000 ");
    uart_puts("drive=SDA-low-then-SCL-low open-drain-only\n");
    while (!timeout_expired(start, FIXTURE_PASSIVE_BUS_WINDOW_US)) {
        bool sda = gpio_get(EEPROM_SDA_GPIO);
        bool scl = gpio_get(EEPROM_SCL_GPIO);
        sda_high |= sda;
        scl_high |= scl;
        sda_low |= !sda;
        scl_low |= !scl;
    }
    uart_puts("FIXTURE PASSIVE END\n");
    report("TP_SDA_INPUT", sda_high && sda_low);
    report("TP_SCL_INPUT", scl_high && scl_low);
    return sda_high && sda_low && scl_high && scl_low;
}

static bool test_eeprom_ack(void)
{
    uint8_t value;
    return eeprom_read(0u, &value, 1u);
}

static bool test_eeprom_restore(void)
{
    uint8_t original[EEPROM_RW_TEST_LENGTH];
    uint8_t pattern[EEPROM_RW_TEST_LENGTH];
    uint8_t observed[EEPROM_RW_TEST_LENGTH];
    bool write_ok;
    bool pattern_ok = false;
    bool restore_write_ok;
    bool restore_ok = false;

    uart_puts("INFO EEPROM scratch=0x");
    uart_put_hex16(EEPROM_RW_SCRATCH_ADDRESS);
    uart_puts(" length=");
    uart_put_u32(EEPROM_RW_TEST_LENGTH);
    uart_putc('\n');

    if (!eeprom_read(EEPROM_RW_SCRATCH_ADDRESS, original,
                     EEPROM_RW_TEST_LENGTH)) {
        return false;
    }
    for (size_t i = 0; i < EEPROM_RW_TEST_LENGTH; ++i) {
        pattern[i] = original[i] ^ (uint8_t)(0xa5u + (uint8_t)(i << 1));
    }

    write_ok = eeprom_write_page(EEPROM_RW_SCRATCH_ADDRESS, pattern,
                                 EEPROM_RW_TEST_LENGTH);
    if (write_ok && eeprom_read(EEPROM_RW_SCRATCH_ADDRESS, observed,
                                EEPROM_RW_TEST_LENGTH)) {
        pattern_ok = bytes_equal(pattern, observed, EEPROM_RW_TEST_LENGTH);
    }

    // Restoration is attempted after every write attempt, including failures
    // that might have partially modified the page.
    restore_write_ok = eeprom_write_page(EEPROM_RW_SCRATCH_ADDRESS, original,
                                         EEPROM_RW_TEST_LENGTH);
    if (restore_write_ok && eeprom_read(EEPROM_RW_SCRATCH_ADDRESS, observed,
                                        EEPROM_RW_TEST_LENGTH)) {
        restore_ok = bytes_equal(original, observed, EEPROM_RW_TEST_LENGTH);
    }

    report("EEPROM_WRITE", write_ok && pattern_ok);
    report("EEPROM_RESTORE", restore_write_ok && restore_ok);
    if (!restore_ok) {
        uart_puts("CRITICAL EEPROM scratch restoration failed\n");
    }
    return write_ok && pattern_ok && restore_write_ok && restore_ok;
}

static bool test_protected_eeprom_restore(void)
{
    uint8_t original[EEPROM_RW_TEST_LENGTH];
    uint8_t pattern[EEPROM_RW_TEST_LENGTH];
    uint8_t observed[EEPROM_RW_TEST_LENGTH];
    bool write_ok;
    bool pattern_ok = false;
    bool restore_write_ok;
    bool restore_ok = false;

    uart_puts("WARNING PROTECTED-RW requires WP LOW and pre-provisioning hardware\n");
    uart_puts("INFO PROTECTED scratch=0x");
    uart_put_hex16(EEPROM_PROTECTED_SCRATCH_ADDRESS);
    uart_puts(" length=");
    uart_put_u32(EEPROM_RW_TEST_LENGTH);
    uart_putc('\n');

    if (!eeprom_read(EEPROM_PROTECTED_SCRATCH_ADDRESS, original,
                     EEPROM_RW_TEST_LENGTH)) {
        return false;
    }
    for (size_t i = 0; i < EEPROM_RW_TEST_LENGTH; ++i) {
        pattern[i] = original[i] ^ (uint8_t)(0x5au + (uint8_t)(i << 1));
    }

    write_ok = eeprom_write_page(EEPROM_PROTECTED_SCRATCH_ADDRESS, pattern,
                                 EEPROM_RW_TEST_LENGTH);
    if (write_ok && eeprom_read(EEPROM_PROTECTED_SCRATCH_ADDRESS, observed,
                                EEPROM_RW_TEST_LENGTH)) {
        pattern_ok = bytes_equal(pattern, observed, EEPROM_RW_TEST_LENGTH);
    }

    restore_write_ok = eeprom_write_page(EEPROM_PROTECTED_SCRATCH_ADDRESS,
                                         original, EEPROM_RW_TEST_LENGTH);
    if (restore_write_ok &&
        eeprom_read(EEPROM_PROTECTED_SCRATCH_ADDRESS, observed,
                    EEPROM_RW_TEST_LENGTH)) {
        restore_ok = bytes_equal(original, observed, EEPROM_RW_TEST_LENGTH);
    }

    report("PROTECTED_WRITE", write_ok && pattern_ok);
    report("PROTECTED_RESTORE", restore_write_ok && restore_ok);
    if (!restore_ok) {
        uart_puts("CRITICAL protected EEPROM restoration failed\n");
    }
    return write_ok && pattern_ok && restore_write_ok && restore_ok;
}

static bool test_eeprom_wp_high(void)
{
    uint8_t original[EEPROM_RW_TEST_LENGTH];
    uint8_t pattern[EEPROM_RW_TEST_LENGTH];
    uint8_t observed[EEPROM_RW_TEST_LENGTH];
    bool attempt_ok;
    bool observed_ok;
    bool write_blocked;
    bool restore_write_ok;
    bool restore_ok = false;

    uart_puts("WARNING WP-CHECK requires WP HIGH; test data must remain unchanged\n");
    uart_puts("INFO WP scratch=0x");
    uart_put_hex16(EEPROM_PROTECTED_SCRATCH_ADDRESS);
    uart_puts(" length=");
    uart_put_u32(EEPROM_RW_TEST_LENGTH);
    uart_putc('\n');

    if (!eeprom_read(EEPROM_PROTECTED_SCRATCH_ADDRESS, original,
                     EEPROM_RW_TEST_LENGTH)) {
        return false;
    }
    for (size_t i = 0; i < EEPROM_RW_TEST_LENGTH; ++i) {
        pattern[i] = original[i] ^ (uint8_t)(0x3cu + (uint8_t)(i << 1));
    }

    attempt_ok = eeprom_write_page(EEPROM_PROTECTED_SCRATCH_ADDRESS, pattern,
                                   EEPROM_RW_TEST_LENGTH);
    observed_ok = eeprom_read(EEPROM_PROTECTED_SCRATCH_ADDRESS, observed,
                              EEPROM_RW_TEST_LENGTH);
    write_blocked = attempt_ok && observed_ok &&
                    bytes_equal(original, observed, EEPROM_RW_TEST_LENGTH);

    // If WP was not actually high, immediately restore the protected bytes.
    // Restoration is harmless when WP is working because the write is ignored.
    restore_write_ok = eeprom_write_page(EEPROM_PROTECTED_SCRATCH_ADDRESS,
                                         original, EEPROM_RW_TEST_LENGTH);
    if (restore_write_ok &&
        eeprom_read(EEPROM_PROTECTED_SCRATCH_ADDRESS, observed,
                    EEPROM_RW_TEST_LENGTH)) {
        restore_ok = bytes_equal(original, observed, EEPROM_RW_TEST_LENGTH);
    }

    report("EEPROM_WP_HIGH", write_blocked);
    report("PROTECTED_RESTORE", restore_write_ok && restore_ok);
    if (!restore_ok) {
        uart_puts("CRITICAL protected EEPROM restoration failed\n");
    }
    return write_blocked && restore_write_ok && restore_ok;
}

static bool test_led_gpio(void)
{
    gpio_output_init(OPTICAL_LED_GPIO, false);
    delay_us(1000u);
    bool low_ok = !gpio_get(OPTICAL_LED_GPIO);
    gpio_put(OPTICAL_LED_GPIO, true);
    delay_us(1000u);
    bool high_ok = gpio_get(OPTICAL_LED_GPIO);
    gpio_put(OPTICAL_LED_GPIO, false);
    return low_ok && high_ok;
}

static void fixture_led_pattern(void)
{
    uart_puts("FIXTURE LED START pattern=D2 bit-ms=100 msb-first\n");
    for (uint32_t i = 0; i < 3u; ++i) {
        gpio_put(OPTICAL_LED_GPIO, true);
        delay_us(FIXTURE_LED_HALF_PERIOD_US);
        gpio_put(OPTICAL_LED_GPIO, false);
        delay_us(FIXTURE_LED_HALF_PERIOD_US);
    }
    delay_us(FIXTURE_LED_HALF_PERIOD_US * 3u);
    for (uint32_t mask = 0x80u; mask != 0u; mask >>= 1) {
        gpio_put(OPTICAL_LED_GPIO, (FIXTURE_LED_BITS & mask) != 0u);
        delay_us(FIXTURE_LED_HALF_PERIOD_US);
    }
    gpio_put(OPTICAL_LED_GPIO, false);
    uart_puts("FIXTURE LED END\n");
}

static void fixture_i2c_activity(void)
{
    uint8_t data[2];
    uart_puts("FIXTURE I2C START address=50 clock-khz=100 transactions=8\n");
    for (uint16_t i = 0; i < 8u; ++i) {
        if (!eeprom_read(i, data, sizeof(data))) {
            uart_puts("INFO I2C abort=0x");
            uart_put_hex32(last_i2c_abort);
            uart_putc('\n');
        }
        delay_us(2000u);
    }
    uart_puts("FIXTURE I2C END\n");
}

static void run_fixture(void)
{
    uart_puts("FIXTURE BEGIN\n");
    uart_puts("INFO UART command receipt proves RX path; this response exercises TX\n");
    report("UART_RX", true);
    report("I2C_IDLE_HIGH", test_bus_idle());
    (void)fixture_passive_bus_test();
    bool i2c_ready = i2c_configure();
    report("I2C_INIT", i2c_ready);
    uint8_t address_map = i2c_ready ? i2c_scan_eeprom_straps() : 0u;
    uart_puts("INFO I2C_SCAN_50_57=0x");
    uart_put_hex8(address_map);
    uart_putc('\n');
    report("EEPROM_ADDRESS_50_ONLY", address_map == 0x01u);
    fixture_i2c_activity();
    report("EEPROM_ACK_50", test_eeprom_ack());
    report("EEPROM_RW_RESTORE", test_eeprom_restore());
    report("LED_GPIO26", test_led_gpio());
    fixture_led_pattern();
    uart_puts("EXTERNAL POWER measure TP_3V3-to-TP_GND expected=3.15..3.45V\n");
    uart_puts("EXTERNAL GROUND TP_GND-to-USB-supply-ground expected<1ohm\n");
    uart_puts("EXTERNAL TP_I2C fixture must observe address 50 and both lines toggling\n");
    uart_puts("EXTERNAL OPTICAL fixture must decode D2\n");
    uart_puts("FIXTURE END external-results-required=3\n");
}

static void print_status(void)
{
#ifdef SIGNAL_BOX_SECURITY_PROFILE
    signal_box_security_check();
    uart_puts("SECURITY PROFILE=" SIGNAL_BOX_SECURITY_PROFILE "\n");
    uart_puts("SECURITY CRITICAL=0x");
    uart_put_hex32(signal_box_security_critical());
    uart_puts(" DEBUGEN=0x");
    uart_put_hex32(signal_box_security_debugen());
    uart_puts(" DEBUGEN_LOCK=0x");
    uart_put_hex32(signal_box_security_debugen_lock());
    uart_puts("\nSECURITY runtime-readback=PASS physical-debug-test=REQUIRED\n");
#endif
#if PICO_RP2350
    uart_puts("STATUS CLOCK_INIT=PICO_SDK SYS_HZ=125000000 TIMER=TIMER0\n");
#else
    uart_puts("STATUS XOSC_ATTEMPTS=");
    uart_put_u32(xosc_attempts);
    uart_putc('\n');
#endif
    report("PREFLIGHT_I2C_IDLE_HIGH", preflight_bus_idle);
    uart_puts("STATUS I2C_SCAN_50_57=0x");
    uart_put_hex8(preflight_address_map);
    uart_putc('\n');
    report("PREFLIGHT_EEPROM_ADDRESS_50_ONLY", preflight_address_map == 0x01u);
    report("PREFLIGHT_EEPROM_ACK_50", preflight_eeprom_ack);
    report("PREFLIGHT_LED_GPIO26", preflight_led_gpio);
    uart_puts("STATUS LAST_I2C_ABORT=0x");
    uart_put_hex32(last_i2c_abort);
    uart_putc('\n');
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

static void print_help(void)
{
    uart_puts("COMMANDS\n");
    uart_puts("  run      full fixture sequence, including EEPROM write/read/restore\n");
    uart_puts("  status   repeat non-destructive status\n");
    uart_puts("  bus      emit eight EEPROM reads for TP capture\n");
    uart_puts("  passive  monitor fixture-driven SDA/SCL for three seconds\n");
    uart_puts("  led      emit optical fixture pattern D2\n");
    uart_puts("  eeprom       unprotected EEPROM write/read/restore\n");
    uart_puts("  protected-rw protected write/read/restore; WP must be LOW\n");
    uart_puts("  wp-check     verify protected writes are blocked; WP must be HIGH\n");
#ifdef SIGNAL_BOX_SECURITY_PROFILE
    uart_puts("  bootsel  lab-only warm ROM USB handoff; no OTP writes\n");
#endif
    uart_puts("  help\n");
}

static void command_loop(void)
{
    char line[32];
    size_t used = 0u;

    uart_puts("debug> ");
    for (;;) {
        char value;
        if (!uart_getc(&value)) {
            continue;
        }
        if (value == '\r' || value == '\n') {
            if (used == 0u) {
                continue;
            }
            line[used] = '\0';
            uart_putc('\n');
            if (string_equal(line, "run")) {
                run_fixture();
            } else if (string_equal(line, "status")) {
                print_status();
            } else if (string_equal(line, "bus")) {
                fixture_i2c_activity();
            } else if (string_equal(line, "passive")) {
                (void)fixture_passive_bus_test();
                (void)i2c_configure();
            } else if (string_equal(line, "led")) {
                fixture_led_pattern();
            } else if (string_equal(line, "eeprom")) {
                report("EEPROM_RW_RESTORE", test_eeprom_restore());
            } else if (string_equal(line, "protected-rw")) {
                report("PROTECTED_RW_RESTORE", test_protected_eeprom_restore());
            } else if (string_equal(line, "wp-check")) {
                report("WP_CHECK", test_eeprom_wp_high());
#ifdef SIGNAL_BOX_SECURITY_PROFILE
            } else if (string_equal(line, "bootsel")) {
                uart_puts("INFO Warm BOOTSEL handoff; memory-retention test required\n");
                uint32_t start = hw_read(DEBUG_TIMER_BASE + TIMER_TIMERAWL_OFFSET);
                while (hw_read(UART0_BASE + UART_UARTFR_OFFSET) & UART_UARTFR_BUSY_BITS) {
                    if ((uint32_t)(hw_read(DEBUG_TIMER_BASE + TIMER_TIMERAWL_OFFSET) - start) >= 100000u) {
                        break;
                    }
                }
                signal_box_security_bootsel();
#endif
            } else if (string_equal(line, "help")) {
                print_help();
            } else {
                uart_puts("ERROR unknown command\n");
            }
            used = 0u;
            uart_puts("debug> ");
        } else if (value == 0x08 || value == 0x7f) {
            if (used != 0u) {
                --used;
            }
        } else if (used + 1u < sizeof(line)) {
            line[used++] = value;
            uart_putc(value);
        }
    }
}

int main(void)
{
#ifdef SIGNAL_BOX_SECURITY_PROFILE
    signal_box_security_check();
#endif
#if PICO_RP2350
    // This diagnostic superloop uses no interrupts, including SDK alarms.
    __asm volatile ("cpsid i");
#endif
    if (!reset_release(RESET_BANK0_MASK)) {
        for (;;) {
        }
    }
    gpio_output_init(BOOT_LED_GPIO, true);
    boot_blinks(3u);

#if !PICO_RP2350
    if (!xosc_init()) {
        for (;;) {
            boot_blinks(4u);
        }
    }
    boot_blinks(1u);

    if (!clock_ref_init()) {
        for (;;) {
            boot_blinks(5u);
        }
    }
    boot_blinks(2u);

    if (!clock_pll_init()) {
        for (;;) {
            boot_blinks(6u);
        }
    }
    if (!clock_sys_init()) {
        for (;;) {
            boot_blinks(7u);
        }
    }
    boot_blinks(3u);
#endif

    if (!reset_release(RESET_RUNTIME_MASK)) {
        for (;;) {
            boot_blinks(8u);
        }
    }
    boot_led_put(true);
    crude_delay();
    crude_delay();
    boot_led_put(false);

    uart_init();
    gpio_output_init(OPTICAL_LED_GPIO, false);

    uart_puts("\nSIGNAL-BOX DEBUG ");
    uart_puts(DEBUG_FIRMWARE_VERSION);
#if PICO_RP2350
    uart_puts("\nBOOT BOARD=XIAO_RP2350 CLOCK_INIT=PICO_SDK\n");
#else
    uart_puts("\nBOOT XOSC_ATTEMPTS=");
    uart_put_u32(xosc_attempts);
    uart_putc('\n');
#endif
    uart_puts("INFO Send 'run' from the fixture to begin destructive-restoring tests\n");

    preflight_bus_idle = test_bus_idle();
    bool i2c_ready = i2c_configure();
    preflight_address_map = i2c_ready ? i2c_scan_eeprom_straps() : 0u;
    preflight_eeprom_ack = preflight_address_map == 0x01u && test_eeprom_ack();
    preflight_led_gpio = test_led_gpio();
    print_status();
    print_help();
    command_loop();
}
