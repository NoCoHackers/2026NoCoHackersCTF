#include "security_profile.h"

#include "hardware/structs/accessctrl.h"
#include "hardware/structs/otp.h"
#include "pico/bootrom.h"
#include "pico/runtime_init.h"

#if !PICO_RP2350 || !defined(SIGNAL_BOX_RAM_PROTOTYPE)
#error "Security probes require the RP2350 ARM Secure SRAM build"
#endif

#if SIGNAL_BOX_DEBUG_REOPEN
#define EXPECTED_DEBUGEN OTP_DEBUGEN_BITS
#else
#define EXPECTED_DEBUGEN 0u
#endif

void signal_box_security_check(void)
{
    if ((otp_hw->debugen & OTP_DEBUGEN_BITS) != EXPECTED_DEBUGEN ||
        (otp_hw->debugen_lock & OTP_DEBUGEN_LOCK_BITS) != OTP_DEBUGEN_LOCK_BITS ||
        (accessctrl_hw->otp & (ACCESSCTRL_OTP_NSP_BITS | ACCESSCTRL_OTP_NSU_BITS))) {
        __asm volatile ("cpsid i");
        // A warm launch can inherit locked overrides. Never proceed to the
        // console on mismatched policy; recover using a full power cycle.
        for (;;) {
            __asm volatile ("nop");
        }
    }
}

static void signal_box_security_init(void)
{
    __asm volatile ("cpsid i");
    // These are volatile control registers, NOT OTP programming registers.
    // Zero only closes overrides: physical debug also needs the OTP disable flag.
    otp_hw->debugen = EXPECTED_DEBUGEN;
    __asm volatile ("dsb sy\nisb sy" ::: "memory");
    if ((otp_hw->debugen & OTP_DEBUGEN_BITS) != EXPECTED_DEBUGEN) {
        for (;;) {
            __asm volatile ("nop");
        }
    }
    otp_hw->debugen_lock = OTP_DEBUGEN_LOCK_BITS;
    __asm volatile ("dsb sy\nisb sy" ::: "memory");
    signal_box_security_check();
}

// Before SDK bootrom reset (00050), clocks and main. This is still AFTER the
// embedded decryptor, not a claim that its earlier key handling is covered.
PICO_RUNTIME_INIT_FUNC_HW(signal_box_security_init, PICO_RUNTIME_INIT_EARLIEST);

uint32_t signal_box_security_critical(void)
{
    return otp_hw->critical;
}

uint32_t signal_box_security_debugen(void)
{
    return otp_hw->debugen;
}

uint32_t signal_box_security_debugen_lock(void)
{
    return otp_hw->debugen_lock;
}

void signal_box_security_bootsel(void)
{
    // Test a firmware-triggered ROM handoff, not just cold unplug/replug.
    reset_usb_boot(0, 0);
    for (;;) {
    }
}
