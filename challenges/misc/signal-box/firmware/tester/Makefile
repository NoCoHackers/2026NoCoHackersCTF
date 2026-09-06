PICO_SDK_PATH ?= $(firstword $(wildcard $(HOME)/pico-sdk /tmp/pico-sdk))

ifeq ($(strip $(PICO_SDK_PATH)),)
$(error Set PICO_SDK_PATH to a pico-sdk checkout; see README.md)
endif

CROSS ?= arm-none-eabi-
CC := $(CROSS)gcc
OBJCOPY := $(CROSS)objcopy
SIZE := $(CROSS)size
NM := $(CROSS)nm
PYTHON ?= python3

BUILD := build
COMMON_SRC := ../common
REGISTER_INCLUDE := $(PICO_SDK_PATH)/src/rp2040/hardware_regs/include
TARGET := $(BUILD)/signal-box-tester

CPPFLAGS := -DPICO_RP2040=1 -I$(REGISTER_INCLUDE) -I$(COMMON_SRC) -Isrc
COMMON_FLAGS := -mcpu=cortex-m0plus -mthumb -ffreestanding -fno-builtin \
	-ffunction-sections -fdata-sections -Wall -Wextra -Werror -Os -g3
CFLAGS := $(COMMON_FLAGS) -std=c11
ASFLAGS := $(COMMON_FLAGS)
LDFLAGS := -mcpu=cortex-m0plus -mthumb -nostdlib -Wl,--gc-sections \
	-Wl,-Map,$(TARGET).map -T$(COMMON_SRC)/linker.ld
OBJECTS := $(BUILD)/boot2.o $(BUILD)/startup.o $(BUILD)/tester.o

.PHONY: all clean

all: $(TARGET).uf2

$(BUILD):
	mkdir -p $@

$(BUILD)/boot2.o: $(COMMON_SRC)/boot2.S | $(BUILD)
	$(CC) $(CPPFLAGS) $(ASFLAGS) -MMD -MP -c $< -o $@

$(BUILD)/startup.o: $(COMMON_SRC)/startup.S | $(BUILD)
	$(CC) $(CPPFLAGS) $(ASFLAGS) -MMD -MP -c $< -o $@

$(BUILD)/tester.o: src/tester.c src/config.h | $(BUILD)
	$(CC) $(CPPFLAGS) $(CFLAGS) -MMD -MP -c $< -o $@

$(TARGET).elf: $(OBJECTS) $(COMMON_SRC)/linker.ld
	$(CC) $(LDFLAGS) $(OBJECTS) -o $@
	@if test -n "$$($(NM) -u $@)"; then \
		echo "FATAL: unresolved runtime helpers:"; $(NM) -u $@; exit 1; \
	fi
	$(SIZE) $@

$(TARGET).unpatched.bin: $(TARGET).elf
	$(OBJCOPY) -O binary $< $@

$(TARGET).uf2: $(TARGET).unpatched.bin $(COMMON_SRC)/make_uf2.py
	$(PYTHON) $(COMMON_SRC)/make_uf2.py $< $(TARGET).bin $@

clean:
	rm -rf $(BUILD)

ifeq ($(filter clean,$(MAKECMDGOALS)),)
-include $(OBJECTS:.o=.d)
endif
