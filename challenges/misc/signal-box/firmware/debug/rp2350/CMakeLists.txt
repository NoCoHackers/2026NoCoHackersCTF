cmake_minimum_required(VERSION 3.13)

# Keep the RP2040 Makefile and boot chain independent of this port.
if (NOT PICO_SDK_PATH AND DEFINED ENV{PICO_SDK_PATH})
    set(PICO_SDK_PATH "$ENV{PICO_SDK_PATH}")
endif()
if (NOT EXISTS "${PICO_SDK_PATH}/pico_sdk_init.cmake")
    message(FATAL_ERROR "Set PICO_SDK_PATH to a complete Pico SDK 2.2.0 checkout; see README.md")
endif()

set(PICO_BOARD seeed_xiao_rp2350)
set(PICO_PLATFORM rp2350-arm-s)
# Seeed SKU 102010550 datasheet specifies 2 MB, unlike the SDK's 4 MiB default.
set(PICO_FLASH_SIZE_BYTES 2097152)
include("${PICO_SDK_PATH}/pico_sdk_init.cmake")
project(signal_box_debug_rp2350 C CXX ASM)
set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)
pico_sdk_init()

if (NOT PICO_SDK_VERSION_STRING VERSION_EQUAL "2.2.0")
    message(FATAL_ERROR "This bring-up port is pinned to Pico SDK 2.2.0")
endif()

add_executable(signal-box-debug-rp2350 ../src/debug.c)
target_include_directories(signal-box-debug-rp2350 PRIVATE ../src ../../common)
target_compile_options(signal-box-debug-rp2350 PRIVATE -Wall -Wextra -Werror)
# Preserve the existing UART and I2C timing. RP2350 normally defaults to 150 MHz.
target_compile_definitions(signal-box-debug-rp2350 PRIVATE
    SYS_CLK_HZ=125000000
    PICO_FLASH_SIZE_BYTES=${PICO_FLASH_SIZE_BYTES}
    PICO_TIME_DEFAULT_ALARM_POOL_DISABLED=1
)
target_link_libraries(signal-box-debug-rp2350 pico_stdlib)
pico_enable_stdio_uart(signal-box-debug-rp2350 0)
pico_enable_stdio_usb(signal-box-debug-rp2350 0)
option(SIGNAL_BOX_RAM_PROTOTYPE "Build an SRAM payload for offline encryption experiments" OFF)
if (SIGNAL_BOX_RAM_PROTOTYPE)
    pico_set_binary_type(signal-box-debug-rp2350 no_flash)
    target_compile_definitions(signal-box-debug-rp2350 PRIVATE SIGNAL_BOX_RAM_PROTOTYPE=1)
endif()
set(SIGNAL_BOX_SECURITY_PROFILE "none" CACHE STRING "Lab profile: none, recovery, debug-closed, debug-reopen")
set_property(CACHE SIGNAL_BOX_SECURITY_PROFILE PROPERTY STRINGS none recovery debug-closed debug-reopen)
option(SIGNAL_BOX_ACK_PRIVATE_DEBUG_REOPEN "Acknowledge the reopen artifact must remain private until post-event" OFF)
if (NOT SIGNAL_BOX_SECURITY_PROFILE STREQUAL "none")
    if (NOT SIGNAL_BOX_RAM_PROTOTYPE OR
        NOT SIGNAL_BOX_SECURITY_PROFILE MATCHES "^(recovery|debug-closed|debug-reopen)$")
        message(FATAL_ERROR "Security profiles require SIGNAL_BOX_RAM_PROTOTYPE=ON and a listed lab profile")
    endif()
    target_sources(signal-box-debug-rp2350 PRIVATE security_profile.c)
    target_include_directories(signal-box-debug-rp2350 PRIVATE "${CMAKE_CURRENT_LIST_DIR}")
    target_compile_definitions(signal-box-debug-rp2350 PRIVATE
        SIGNAL_BOX_SECURITY_PROFILE="${SIGNAL_BOX_SECURITY_PROFILE}")
    if (SIGNAL_BOX_SECURITY_PROFILE STREQUAL "debug-reopen")
        if (NOT SIGNAL_BOX_ACK_PRIVATE_DEBUG_REOPEN)
            message(FATAL_ERROR "Debug reopen requires SIGNAL_BOX_ACK_PRIVATE_DEBUG_REOPEN=ON; never release this signed image early")
        endif()
        target_compile_definitions(signal-box-debug-rp2350 PRIVATE SIGNAL_BOX_DEBUG_REOPEN=1)
    else()
        target_compile_definitions(signal-box-debug-rp2350 PRIVATE SIGNAL_BOX_DEBUG_REOPEN=0)
    endif()
endif()
pico_add_extra_outputs(signal-box-debug-rp2350)
